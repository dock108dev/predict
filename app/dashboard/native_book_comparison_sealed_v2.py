"""Versioned retained native review: normal-winner prices, never qualified hedges."""
from copy import deepcopy
from decimal import Decimal
import json
from hashlib import sha256
from pathlib import Path
from app.dashboard.session_projection import stable, stamp, format_book

VERSION='native-book-comparison-2'
BINDING=Path(__file__).resolve().parents[1]/'fixtures/native-book-comparison-v2.json'


def review():
    body=BINDING.read_bytes()
    if sha256(body).hexdigest()!='010c8d75d15413c80e36dde8fe9ad8c03d8b423ca974637e382b1fcffd0810d6':raise ValueError('Sealed v2 native review changed')
    return json.loads(body)


def settlement(binding):
    k=binding['sources']['kalshi'];p=binding['sources']['polymarket_us']
    return dict(status='INCOMPATIBLE',qualified=False,version=VERSION,
        correspondence='Normal officially declared winner only; NO is not a universal opponent-win payout',
        conflicts=[dict(condition='postponement',left=dict(value='48 hours to begin, then venue fair price'),right=dict(value='rescheduled within two weeks, else last fair market price'))],
        unknown=[dict(condition=k) for k in ('tie_payout','suspension_payout','refund','mandatory_settlement_charges','effective_modification_coverage')],
        native_terms={'kalshi':{k:v for k,v in k['metadata'].items() if k.startswith('rules_')},'polymarket_us':p['metadata']['description']},
        evidence={s:v['provenance'] for s,v in binding['sources'].items()},
        applicability='Observed listing terms at captured receipt; no retrospective/future modification coverage inferred')


def connect(projection, result, at):
    """Add raw games without relaxing the shared qualified NCAAF identity gate."""
    if projection.spec.get('native_discovery',{}).get('slice')!='native-books-v1':return
    binding=review();accepted={};rejections={}
    for venue,b in binding['sources'].items():
        cat=projection.inventory.get(venue,{})
        e=next((e for e in cat.get('events',[]) if e['id']==b['event_id']),None)
        m=next((m for m in cat.get('markets',[]) if m['id']==b['market_id']),None)
        if not e or not m:continue
        reason=None
        if e.get('canonical_key')!=binding['event'] or e.get('identity')!='resolved':reason='Retained canonical event differs from reviewed event'
        elif e.get('conflicting_duplicate') or m.get('conflicting_duplicate') or m.get('exclusion'):reason='Conflicting or excluded retained identity'
        elif stable(e['native_metadata'])!=b['event_metadata_sha256'] or stable(m['native_metadata'])!=b['native_metadata_sha256']:reason='Native metadata differs from exact reviewed listing; outcome mapping unavailable'
        elif b['market_id'] not in cat.get('selection',{}).get('ids',[]):reason='Reviewed market not selected'
        key=(venue,b['event_id'],b['market_id'])
        meta=projection.metadata.get(key)
        if not reason and not meta:reason='Exact selected metadata unavailable at cutoff'
        if not reason:
            raw=meta['market']['raw']
            if raw['ref']!=dict(venue=venue,event_id=b['event_id'],market_id=b['market_id']) or sha256(raw['json_text'].encode()).hexdigest()!=b['provenance'][0]['body_sha256']:
                reason='Selected metadata provenance differs from reviewed listing'
            book=projection.books.get(key)
            if book and book['book']['raw']['ref']!=raw['ref']:reason='Book native reference differs from selected market'
        if reason:rejections[venue]=reason;continue
        accepted[venue]=(e,m,meta,key)
    result['native_comparison_review']=dict(version=VERSION,binding_sha256=stable(binding),rejections=rejections,settlement=settlement(binding))
    result['projection_revision']+='+'+VERSION
    if set(accepted)!=set(binding['sources']):return
    sides={};cards=[]
    for venue,(e,m,meta,key) in accepted.items():
        b=binding['sources'][venue]
        for native,s in b['outcomes'].items():sides[venue+':'+native]=dict(s,native_id=native,native_label=native)
        row=projection.books.get(key)
        formatted=format_book(row,{venue:{n:(s['participant'],n) for n,s in b['outcomes'].items()}}) if row else None
        age=None if not row else str(Decimal(str((stamp(at)-stamp(row['book']['raw']['received_at'])).total_seconds())))
        state='disconnected' if projection.finished else projection.health.get(key,{}).get('state','awaiting_snapshot')
        if key in projection.invalid and state=='connected':state='resynchronization_required'
        if formatted:
            # Health re-emissions retain the same underlying native observation.
            formatted['id']=stable([venue,row['book']['raw']['json_text'],row['book']['raw']['received_at']])
            formatted['native_observation']=deepcopy(projection.book_evidence.get(key))
            formatted['native_raw']=deepcopy(row['book']['raw'])
            formatted['native_ladders']=deepcopy(row['book']['outcomes'])
            formatted['application_received_at']=row.get('application_received_at')
            formatted['local_timing']=deepcopy(row.get('local_timing'))
        cards.append(dict(venue=venue,label={'kalshi':'Kalshi','polymarket_us':'Polymarket US'}[venue],book=formatted,connection=state,age_seconds=age,receipt_stale=age is None or Decimal(age)>15))
    gid=stable([VERSION,binding['event'],[(s,b['event_id'],b['market_id']) for s,b in binding['sources'].items()]])
    game=dict(id=gid,native_raw=True,title='Western Kentucky vs New Mexico State · full-game winner',scheduled_start=binding['event'][0],teams=sorted(binding['participants'].values()),sides=sides,sources={s:dict(event_id=b['event_id'],market_id=b['market_id']) for s,b in binding['sources'].items()},candidates=[],
        product_identity=dict(version=2,event=binding['event'],sport='american_football',competition='NCAAF',season='2026',stage=None,scheduled_start=binding['event'][0],family='moneyline',period='full_game',line=None,subject=None,outcome_set='normal declared winner correspondence',rules=VERSION),
        native_review=dict(version=VERSION,binding_sha256=stable(binding),settlement=settlement(binding),orientation={s:b['orientation_evidence'] for s,b in binding['sources'].items()}))
    result['games'].append(game)
    result['points'][gid]=dict(id=result['durable_cursor'],at=at,cards=cards,label='Exact retained cutoff')
    result['rows_by_game'][gid]=[a[2] for a in accepted.values()]
    for m in result['market_catalog']:
        if m['source_id'] in accepted and m['market_id']==binding['sources'][m['source_id']]['market_id']:
            m['qualified_exclusion']=m['reason'];m['reason']='Raw comparison connected; settlement incompatible and net inputs incomplete'
            m['outcome_review']=deepcopy(binding['sources'][m['source_id']]['orientation_evidence'])


def entry(contract,quantity,at,identity,source):
    from app.dashboard.price_comparison import entry_cost
    value=entry_cost(contract,quantity,at,identity,source)
    b=review()['sources'][contract['venue']]
    value['evidence']=dict(version=VERSION,listing=b['provenance'],coefficient=b['metadata'].get('feeCoefficient'),research=review()['retained_research'])
    if contract['venue']=='polymarket_us':
        if value['notional'] is not None and quantity!=quantity.to_integral_value():
            minimum=Decimal(str(b['metadata']['minimumTradeQty']))
            if quantity<minimum:
                value['reason']='Requested quantity is below retained minimumTradeQty '+str(minimum)
            else:
                from app.depth import consume
                from app.fees.entry_bounds import us_taker_bound
                bound=us_taker_bound(consume(contract['levels'],str(quantity)))
                value.update(lower=value['notional'],upper=str(Decimal(value['notional'])+Decimal(bound['upper'])),audit=bound,reason=None)
                value['basis']+=' Fractional quantity formula scenario; listing minimum quantity is not proof of every allowed execution increment.'
        value['basis']+=' Selected listing feeCoefficient 0.0695 matches retained September 25 04:00 UTC standard schedule; exact fill allocation and extra settlement charges remain unknown.'
    elif value['notional'] is not None:
        # Retained exact series evidence supports a conditional formula, not an
        # invented current event override, account precision, or effective history.
        from app.depth import consume
        from app.fees import calculate
        fills=consume(contract['levels'],str(quantity))
        if quantity==quantity.to_integral_value():
            context=dict(venue='kalshi',environment='production',market_id=source['market_id'],product='event_contract',trade_time=at,calculation_time=at,complete_order_history=True,settlement_status='UNKNOWN',outcomes={},schedule_version='kalshi-july7-observed-sep12',series_id='KXNCAAFGAME',event_id=source['event_id'],balance_precision='0.01',kalshi_metadata=dict(source='Conditional retained September 11 KXNCAAFGAME series scenario; current event override and account precision unverified',series_id='KXNCAAFGAME',event_id=source['event_id'],event_history_complete=False,series_changes=[dict(scheduled_ts=at,fee_type='quadratic_with_maker_fees',fee_multiplier='1')],event_changes=[]),fills=[dict(fill_id=str(i),order_id='hypothetical-new-taker-order',role='taker',price=f['price'],quantity=f['quantity'],unit='contracts') for i,f in enumerate(fills)])
            value['conditional_fee_scenario']=calculate(context)
        value['reason']='Current KXNCAAFGAME/event fee override history and account balance precision unavailable; retained series formula is conditional only'
    return value
