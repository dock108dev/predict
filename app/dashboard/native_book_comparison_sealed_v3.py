"""Reusable raw comparison from exact versioned native judgments."""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from app.dashboard.session_projection import stable, stamp, format_book
from app.dashboard.native_reviews_sealed_v3 import records, validate
VERSION='native-book-comparison-3'


def review():
    # Compatibility accessor for the sealed regression's retained source inputs.
    from app.dashboard.native_book_comparison_sealed_v2 import review as original
    return original()


def settlement(binding):
    return deepcopy(binding['settlement_assessment'])


def connect(projection,result,at):
    interpretation=getattr(projection,'native_interpretation','native-book-comparison-3')
    if interpretation=='original':return
    if interpretation=='native-book-comparison-2':
        from app.dashboard.native_book_comparison_sealed_v2 import connect as sealed
        return sealed(projection,result,at)
    try:reviews,errors=records(projection)
    except (ValueError,KeyError,OSError) as exc:
        reviews=[];errors={'registry':str(exc)}
    result['native_comparison_review']=dict(version=VERSION,reviews={},rejections={},errors=errors)
    result['projection_revision']+='+'+VERSION
    for binding in reviews:
        try:
            reasons=connect_one(projection,result,at,binding)
            if reasons:result['native_comparison_review']['errors'][binding['sha256']]=reasons
        except (KeyError,ValueError,TypeError,ArithmeticError) as exc:
            result['native_comparison_review']['errors'][binding['sha256']]=str(exc)


def connect_one(projection, result, at, binding):
    """Add raw games without relaxing the shared qualified NCAAF identity gate."""
    accepted={};rejections={}
    token=binding['sha256']
    applicable=binding['applicability']
    if applicable['status']!='SUPPORTED' or not stamp(applicable['start'])<=stamp(at)<=stamp(applicable['end']):
        return {'applicability':'Review is outside its supported effective interval'}
    for venue,b in binding['sources'].items():
        cat=projection.inventory.get(venue,{})
        e=next((e for e in cat.get('events',[]) if e['id']==b['event_id']),None)
        m=next((m for m in cat.get('markets',[]) if m['id']==b['market_id']),None)
        if not e or not m:continue
        if len([x for x in cat.get('events',[]) if x['id']==b['event_id']])!=1 or len([x for x in cat.get('markets',[]) if x['id']==b['market_id']])!=1:
            rejections[venue]='Conflicting duplicate native IDs';continue
        reason=None
        if e.get('canonical_key')!=binding['event'] or e.get('identity')!='resolved':reason='Retained canonical event differs from reviewed event'
        elif e.get('conflicting_duplicate') or m.get('conflicting_duplicate') or m.get('exclusion'):reason='Conflicting or excluded retained identity'
        elif stable(e['native_metadata'])!=b['event_metadata_sha256'] or stable(m['native_metadata'])!=b['native_metadata_sha256']:reason='Native metadata differs from exact reviewed listing; outcome mapping unavailable'
        elif b['market_id'] not in cat.get('selection',{}).get('ids',[]):reason='Reviewed market not selected'
        ident=binding['identity']
        if not reason and (e.get('competition')!=ident['competition'] or {'hockey':'ice_hockey'}.get(e.get('sport'),e.get('sport'))!=ident['sport'] or m.get('event_id')!=e['id'] or m.get('market_type')!=ident['family'] or m.get('period')!=ident['period'] or m.get('line')!=b.get('descriptor',ident).get('line')):
            reason='Normalized native event / market scope differs from selected review'
        if not reason and set(e.get('participants',{}).values() or e.get('field',[]))!=set(binding['participants']):reason='Reviewed canonical participants differ from retained event'
        if not reason and any(s.get('native_direction') and s['native_direction']!=next((x.get('role','').lower() for x in m.get('sides',[]) if x['id']==n),None) for n,s in b['outcomes'].items()):reason='Native execution direction differs from selected orientation review'
        if not reason and set(b['outcomes'])!=({x['id'] for x in m.get('sides',[])} or {x['native_id'] for x in m.get('product_outcomes',[])}):reason='Reviewed native outcomes differ from retained sides'
        if not reason and not e.get('scheduled_start'):reason='Validated native schedule missing'
        if not reason and any(e.get(k) is not None and e.get(k)!=ident.get(k) for k in ('season','stage')):reason='Normalized season/stage differs from selected review'
        normalized=binding.get('normalized_event',{})
        if not reason and any(k in normalized and e.get(k)!=normalized[k] for k in ('competition','season','stage','home','away','game_id','schedule_status','original_start','field','states','category','horizon')):reason='Native event differs from reviewed scoring/state domain'
        key=(venue,b['event_id'],b['market_id'])
        meta=projection.metadata.get(key)
        if not reason and not meta:reason='Exact selected metadata unavailable at cutoff'
        if not reason:
            raw=meta['market']['raw']
            if raw.get('kind')!=binding['evidence_mode']:reason='Native receipt evidence class differs from review'
            if raw['ref']!=dict(venue=venue,event_id=b['event_id'],market_id=b['market_id']) or sha256(raw['json_text'].encode()).hexdigest() not in {p['body_sha256'] for p in b['provenance']}:
                reason='Selected metadata provenance differs from reviewed listing'
            book=projection.books.get(key)
            if book and book['book']['raw']['ref']!=raw['ref']:reason='Book native reference differs from selected market'
            if book and {o['outcome_id'] for o in book['book']['outcomes']}!=set(b['outcomes']):reason='Native book outcomes differ from selected review'
        if reason:rejections[venue]=reason;continue
        accepted[venue]=(e,m,meta,key)
    result['native_comparison_review']['reviews'][token]=dict(version=VERSION,binding_sha256=token,rejections=rejections,settlement=settlement(binding))
    result['native_comparison_review']['rejections'].update(rejections)
    if set(accepted)!=set(binding['sources']):
        for m in result['market_catalog']:
            venue=m['source_id'];b=binding['sources'].get(venue)
            if b and m['market_id']==b['market_id'] and venue in rejections:m['native_review_exclusion']=rejections[venue]
        return rejections
    if len(result['games'])>=64:return {'capacity':'Native comparison game capacity reached'}
    sides={};cards=[]
    for venue,(e,m,meta,key) in accepted.items():
        b=binding['sources'][venue]
        for native,s in b['outcomes'].items():
            side=dict(s,native_id=native,native_label=s.get('native_label',native))
            if s.get('comparison_outcome'):
                from app.normalization.score_lines import descriptor
                domain=descriptor(binding['normalized_event'],b['descriptor'])
                if domain['domain']=='championship_states':label=b['descriptor']['participant']+' · '+s['role'].replace('_',' ')
                else:label=domain['domain'].replace('_',' ').capitalize()+' '+{'gt':'>','ge':'≥','lt':'<','le':'≤','eq':'=','ne':'≠'}[s['operator']]+' '+domain['threshold']
                side['comparison_label']=label
            sides[venue+':'+native]=side
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
    gid=stable([VERSION,token,binding['event'],[(s,b['event_id'],b['market_id']) for s,b in binding['sources'].items()]])
    scheduled=next(iter(accepted.values()))[0]['scheduled_start']
    if any(stamp(e['scheduled_start'])!=stamp(scheduled) for e,m,meta,key in accepted.values()):return {'association':'Reviewed native schedules differ'}
    ident=dict(binding['identity'],version=3,event=binding['event'],scheduled_start=scheduled,rules=token)
    game=dict(id=gid,native_raw=True,title=' vs '.join(binding['participants'].values())+' · '+ident['period'].replace('_',' ')+' '+ident['family']+(' · line '+str(ident['line']) if ident.get('line') is not None else ''),scheduled_start=scheduled,teams=sorted(binding['participants'].values()),sides=sides,sources={s:dict(event_id=b['event_id'],market_id=b['market_id'],native_review=deepcopy(binding)) for s,b in binding['sources'].items()},candidates=[],product_identity=ident,native_review=dict(version=VERSION,binding_sha256=token,record=deepcopy(binding),settlement=settlement(binding),orientation={s:b['orientation_evidence'] for s,b in binding['sources'].items()}))
    result['games'].append(game)
    result['points'][gid]=dict(id=result['durable_cursor'],at=at,cards=cards,label='Exact retained cutoff')
    result['rows_by_game'][gid]=[a[2] for a in accepted.values()]
    for m in result['market_catalog']:
        if m['source_id'] in accepted and m['market_id']==binding['sources'][m['source_id']]['market_id']:
            m['qualified_exclusion']=m['reason'];m['reason']='Raw comparison connected; settlement '+settlement(binding)['status'].lower()+'; net evidence assessed separately'
            m['outcome_review']=deepcopy(binding['sources'][m['source_id']]['orientation_evidence'])


def entry(contract,quantity,at,identity,source):
    if identity.get('rules')=='native-book-comparison-2':
        from app.dashboard.native_book_comparison_sealed_v2 import entry as sealed
        return sealed(contract,quantity,at,identity,source)
    from app.depth import consume
    value=dict(lower=None,upper=None,net=None,notional=None,quantity=str(quantity),reason='Selected native fee review missing',fee_status='UNKNOWN',basis='Provisional entry only; settlement/private costs assessed separately')
    if quantity<=0:return value
    try:
        fills=consume(contract['levels'],str(quantity))
        value['notional']=str(sum(Decimal(f['price'])*Decimal(f['quantity']) for f in fills))
        b=validate(source['native_review'])
        s=b['sources'][contract['venue']]
        if source['event_id']!=s['event_id'] or source['market_id']!=s['market_id'] or identity['rules']!=b['sha256']:raise ValueError('Selected fee review identity differs')
        f=s.get('fee_review',dict(status='UNKNOWN',evidence=[],reason='Selected native fee review missing'));a=f.get('applicability',b['applicability'])
        value['evidence']=dict(version=VERSION,review_sha256=b['sha256'],listing=s['provenance'],fee=deepcopy(f))
        value['fee_status']=f['status']
        if a['status']!='SUPPORTED' or not stamp(a['start'])<=stamp(at)<=stamp(a['end']):raise ValueError('Fee evidence outside effective interval')
        if f['status'] in ('UNKNOWN','INCOMPATIBLE'):raise ValueError(f.get('reason','Fee review '+f['status'].lower()))
        if quantity!=quantity.to_integral_value() and not f.get('fractional'):raise ValueError('Fractional execution applicability unverified')
        if quantity<Decimal(f.get('minimum_quantity','0')):raise ValueError('Requested quantity below reviewed minimum')
        if f['model']=='us_taker_bound' and contract['venue']=='polymarket_us':
            from app.fees.entry_bounds import us_taker_bound
            audit=us_taker_bound(fills,f['coefficient'])
            if f['status']=='SUPPORTED':value.update(lower=value['notional'],upper=str(Decimal(value['notional'])+Decimal(audit['upper'])),audit=audit,reason=None)
            else:value.update(conditional_fee_scenario=audit,reason=f.get('reason','Conditional fee formula only'))
        elif f['model']=='kalshi' and contract['venue']=='kalshi':
            from app.fees import calculate
            c=deepcopy(f['context']);c.update(venue='kalshi',environment='production',market_id=s['market_id'],event_id=s['event_id'],product='event_contract',trade_time=at,calculation_time=at,complete_order_history=True,settlement_status='UNKNOWN',outcomes={},fills=[dict(fill_id=str(i),order_id='hypothetical-new-taker-order',role='taker',price=x['price'],quantity=x['quantity'],unit='contracts') for i,x in enumerate(fills)])
            c['kalshi_metadata']['event_id']=s['event_id']
            for x in c['kalshi_metadata']['series_changes']:x.setdefault('scheduled_ts',a['start'])
            audit=calculate(c)
            if f['status']=='SUPPORTED':value.update(lower=audit['entry_cash_requirement'],upper=audit['entry_cash_requirement'],audit=audit,reason=None if audit['entry_cash_requirement'] else 'Fee engine rejected review context')
            else:value.update(conditional_fee_scenario=audit,reason=f.get('reason','Conditional fee formula only'))
        else:raise ValueError('Unsupported reviewed fee model')
    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:value['reason']=str(exc)
    return value
