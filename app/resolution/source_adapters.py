"""Documented source settlement formats, imported offline with exact provenance.

Venue decisions are not sporting scores. Account payout reports are not quote
prices or per-contract results. Missing publication clocks remain missing.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from app.collection.public_contracts import load, VERSION
from app.fees.public_bindings import integer_scale
from app.dashboard.session_projection import stamp, stable

FORMATS={'kalshi_market':('kalshi','kalshi-market'),
         'us_instrument':('polymarket_us','us-instrument-settlement'),
         'us_retail':('polymarket_us','us-settlement'),
         'prophetx_order':('prophetx','prophetx-order-schema'),
         'novig_v3_market':('novig','novig-market-schema'),
         'odds_scores':('odds_api','odds-scores')}
DECODER_VERSION='source-adapters-2'


def wire(body):
    if not isinstance(body,str) or len(body.encode())>65536:raise ValueError('Bounded original JSON body required')
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:raise ValueError('Duplicate native key')
            d[k]=v
        return d
    def bad(value):raise ValueError('Nonfinite native number')
    return json.loads(body,object_pairs_hook=pairs,parse_float=str,parse_constant=bad)


def decimal(value):
    if not isinstance(value,str):raise ValueError('Exact decimal source value required')
    n=Decimal(value)
    if not n.is_finite() or len(n.as_tuple().digits)>30 or abs(n.as_tuple().exponent)>12:
        raise ValueError('Bounded finite source amount required')
    return n


def fraction(value):
    n=decimal(value)
    if not 0<=n<=1:raise ValueError('Payout outside contract face')
    return str(n)


def derive(format, body, binding):
    if format not in FORMATS:raise ValueError('No documented adapter for format')
    source,doc=FORMATS[format];native=wire(body);c=deepcopy(binding)
    if c.get('adapter_version') not in (None,DECODER_VERSION):raise ValueError('Unknown source adapter version')
    if c['source']!=source or not c.get('native') or not c.get('source_event_id'):
        raise ValueError('Exact source/event/market/outcome binding required')
    if c['source_event_id']!=c['native']['event_id']:raise ValueError('Native event binding conflict')
    p={k:deepcopy(c[k]) for k in ('target','source','source_event_id','native','contract','period')}
    p.update(status='pending',payout=None,source_at=None,published_at=None,supersedes=[],
             adapter=dict(version=VERSION,format=format,document=load()['sources'][doc],
             original_sha256=hashlib.sha256(body.encode()).hexdigest(),
             kind='venue_decision_not_sporting_result',status='implemented_awaiting_real_selected_evidence',
             correction_basis=None))
    if c.get('adapter_version'):p['adapter']['decoder_version']=c['adapter_version']
    value=None;fee='unknown';symbol=None
    if format=='odds_scores':
        keys={'NFL':'americanfootball_nfl','NCAAF':'americanfootball_ncaaf','NBA':'basketball_nba',
              'NCAAB':'basketball_ncaab','MLB':'baseball_mlb','NHL':'icehockey_nhl'}
        target=c['target'];competition=target['market_identity']['competition']
        if c['period']!='full_game' or native['id']!=c['source_event_id'] or native['sport_key']!=keys.get(competition):
            raise ValueError('Exact documented provider event/sport/full-game association required')
        if stamp(native['commence_time'])!=stamp(target['event']['scheduled_start']):raise ValueError('Provider score schedule conflicts with target')
        if (native['home_team'],native['away_team'])!=(c.get('home_label'),c.get('away_label')) or native['home_team']==native['away_team']:
            raise ValueError('Explicit provider home/away label association required')
        if type(native['completed']) is not bool:raise ValueError('Explicit provider completion boolean required')
        scores=native.get('scores');p['source_at']=native.get('last_update')
        if scores is not None:
            if not isinstance(scores,list) or len(scores)!=2 or {v['name'] for v in scores}!={native['home_team'],native['away_team']}:
                raise ValueError('Exact complete provider score participant pair required')
            amounts={}
            for v in scores:
                n=v['score']
                if not isinstance(n,str) or not n.isdigit() or not 0<=int(n)<=1000:raise ValueError('Bounded literal sporting score string required')
                amounts[v['name']]=int(n)
            p.update(home_score=amounts[native['home_team']],away_score=amounts[native['away_team']])
        if native['completed'] and scores is None:raise ValueError('Completed provider game has no score')
        p.update(status='final' if native['completed'] else 'pending',completion=None,revision_type='original')
        p['adapter'].update(kind='provider_sporting_result_not_venue_decision',reported_completed=native['completed'],
            missing=['League-authoritative completion/OT or segment evidence','Publication clock','Correction predecessor format'])
    elif format=='kalshi_market':
        m=native['market']
        if (m['ticker'],m['event_ticker'])!=(c['native']['market_id'],c['native']['event_id']):
            raise ValueError('Kalshi exact event/ticker mismatch')
        side=c['native']['outcome_id']
        if side not in ('yes','no'):raise ValueError('Explicit YES/NO outcome required')
        r=m.get('result','');p['source_at']=m.get('settlement_ts')
        if r in ('yes','no'):value='1' if r==side else '0'
        elif r=='scalar':
            face=decimal(m['notional_value_dollars']);yes=decimal(m['settlement_value_dollars'])
            if face<=0 or not 0<=yes<=face:raise ValueError('Scalar settlement/face conflict')
            value=fraction(str(yes/face if side=='yes' else 1-yes/face))
        elif r!='':raise ValueError('Undocumented Kalshi result')
        if value is not None:p['status']='settled'
    elif format=='us_instrument':
        symbol=native['symbol']
        if symbol!=c.get('instrument_symbol') or c.get('instrument_market_id')!=c['native']['market_id']:
            raise ValueError('Exact case-sensitive instrument/market association required')
        stats=native.get('stats')
        if stats is not None:
            if stats.get('settlementPreliminary') is not False or stats.get('settlementPriceCalculationMethod')!='SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_1':
                raise ValueError('Not a documented final EVENT_TIER_1 settlement')
            scale=integer_scale(native['priceScale']);price=decimal(stats['settlementPx'])
            if price!=price.to_integral_value():raise ValueError('US raw settlement integer required')
            value=fraction(str(price/scale));p['source_at']=stats.get('settlementSetTime');p['status']='settled'
            p['adapter']['decision_text']=stats.get('settlementPriceCalculationText')
        if c.get('side') not in ('long','short'):raise ValueError('Exact LONG/SHORT payout association required')
        if value is not None and c['side']=='short':value=fraction(str(1-Decimal(value)))
    elif format=='us_retail':
        if native.get('slug')!=c.get('slug') or c.get('slug_market_id')!=c['native']['market_id']:
            raise ValueError('Exact slug/market association required')
        if c.get('side') not in ('long','short'):raise ValueError('Exact LONG/SHORT payout association required')
        if native.get('settlement') is not None:
            v=native['settlement'];v=str(v) if type(v) is int else v
            value=fraction(v if c['side']=='long' else str(1-decimal(v)));p['status']='settled'
    elif format=='prophetx_order':
        order=native['data']
        if (str(order['market_id']),str(order['sport_event_id']),str(order['outcome_id']))!=(c['native']['market_id'],c['native']['event_id'],c['native']['outcome_id']) or order['order_id']!=c.get('order_id'):
            raise ValueError('Exact ProphetX order/event/market/outcome conflict')
        result=order['winning_status']
        p['source_at']=order.get('settled_at')
        p['adapter']['reported_sync_at']=native.get('last_synced_at')
        p['adapter']['reported_order_outcome']=result
        p['adapter']['payout_amount_basis']='Actual quantity/profit units and market netting require associated account cashflow data; no price inference'
        if order['status'] in ('closed','manually_settled','settled'):
            if result in ('no_result','draw','push'):
                p['status']='refund';p['payout']=dict(kind='stake_refund',value=None,fee_treatment='unknown')
            elif result in ('loss','lost','manually_lost'):
                p['status']='settled';value='0'
            elif result in ('profit','won','manually_won'):p['status']='settled'
            elif result!='tbd':raise ValueError('Undocumented ProphetX settlement outcome')
        elif result!='tbd':raise ValueError('Conflicting unsettled order outcome')
    else:
        m=native
        if (m['marketId'],m['eventId'])!=(c['native']['market_id'],c['native']['event_id']):
            raise ValueError('Novig exact native market/event conflict')
        outcomes=m['outcomes'];ids=[o['outcomeId'] for o in outcomes]
        if len(ids)<2 or len(set(ids))!=len(ids) or c['native']['outcome_id'] not in ids:
            raise ValueError('Complete unique Novig outcome group required')
        statuses=[o['status'] for o in outcomes];status=statuses[ids.index(c['native']['outcome_id'])]
        if m['status']=='SETTLED':
            if set(statuses)=={'PUSH'} and m['voids']=='PUSH':
                p['status']='refund';p['payout']=dict(kind='stake_refund',value=None,fee_treatment='unknown')
            elif set(statuses)<={'WIN','LOSS'} and statuses.count('WIN')==1:
                value='1' if status=='WIN' else '0';p['status']='settled'
            elif all(s not in ('WIN','LOSS','PUSH','TBD') for s in statuses) and m['voids']=='FMV':
                values=[Decimal(fraction(s)) for s in statuses]
                if sum(values)!=1:raise ValueError('Complete Novig FMV prices must sum to1')
                value=fraction(status);p['status']='void'
            else:raise ValueError('Conflicting/incomplete Novig grade group')
        elif m['status'] in ('OPEN','CLOSED') and set(statuses)=={'TBD'}:
            p['adapter']['correction_basis']='documented_remediation_or_pending; explicit predecessor required'
        else:raise ValueError('Undocumented Novig market/outcome lifecycle')
    if value is not None:p['payout']=dict(kind='fraction',value=value,fee_treatment=fee)
    # Timestamp optionality is preserved; receipt is never substituted here.
    if p['source_at'] is not None:stamp(p['source_at'])
    prior=c.get('prior')
    if prior:
        same=all(prior.get(k)==p[k] for k in ('source','source_event_id','native','contract','target','period'))
        if not same:raise ValueError('Correction predecessor exact lineage conflict')
        if c.get('adapter_version') and prior.get('adapter_format')!=format:raise ValueError('Correction predecessor documented format conflict')
        if format=='us_instrument':
            if c.get('adapter_version') and (prior.get('instrument_symbol')!=c.get('instrument_symbol') or prior.get('price_scale')!=str(native['priceScale'])):
                raise ValueError('US correction instrument/scale conflict')
            if not prior.get('source_at') or not p['source_at'] or stamp(p['source_at'])<=stamp(prior['source_at']):
                raise ValueError('US correction needs a newer explicit settlementSetTime')
            p['adapter']['correction_basis']='local_snapshot_lineage_from_documented_revisable_settlement; not provider revision ID'
        elif format=='novig_v3_market':
            if c.get('remediation_observed') is not True:raise ValueError('Explicit documented remediation/regrade lineage required')
            p['adapter']['correction_basis']='explicit_local_remediation_edge; source publication clock remains unknown'
        else:raise ValueError('Provider correction linkage format is not documented for this adapter')
        p['supersedes']=[prior['id']]
    return p


def adapt(format, body, binding, *, url, received_at, evidence_mode, previous=None):
    from app.resolution import core
    c=deepcopy(binding)
    c['adapter_version']=DECODER_VERSION
    if previous is not None:
        core.validate(previous)
        original=json.loads(previous['raw']['body']).get('source_adapter')
        if not original:raise ValueError('Documented adapter predecessor required')
        c['prior']={k:deepcopy(previous['payload'][k]) for k in ('source','source_event_id','native','contract','target','period','source_at')}
        c['prior']['id']=previous['id']
        c['prior']['adapter_format']=original['format']
        if format=='us_instrument':
            c['prior']['instrument_symbol']=original['binding'].get('instrument_symbol')
            c['prior']['price_scale']=str(wire(original['original_body'])['priceScale'])
    p=derive(format,body,c)
    envelope=dict(source_adapter=dict(format=format,original_body=body,binding=c),normalized=p)
    return core.record('sporting' if format=='odds_scores' else 'venue',json.dumps(envelope,sort_keys=True,separators=(',',':')),url=url,
                       path=['normalized'],received_at=received_at,evidence_mode=evidence_mode)


def validate_envelope(record):
    envelope=json.loads(record['raw']['body'])
    adapter=envelope.get('source_adapter')
    if adapter is None:return
    expected_kind='sporting' if adapter['format']=='odds_scores' else 'venue'
    if record['raw']['path']!=['normalized'] or record['kind']!=expected_kind:raise ValueError('Adapter envelope path conflict')
    if derive(adapter['format'],adapter['original_body'],adapter['binding'])!=record['payload']:
        raise ValueError('Source adapter derived-field conflict')


def kalshi_account_report(report, *, ticker, party_id):
    """Already-decoded FIX repeating groups. No FIX network/session operations."""
    if report['55']!=ticker or report['35']!='UMS':raise ValueError('Exact market settlement report required')
    price=decimal(report['730'])/100
    fraction(str(price))
    parties=[p for p in report['parties'] if p['20109']==party_id]
    if len(parties)!=1:raise ValueError('Exact party required')
    p=parties[0]
    if p['1705']!='PAYOUT' or p['138']!='USD':raise ValueError('USD PAYOUT and deducted fee required')
    net=decimal(p['1704']);fee=decimal(p['137'])
    if net<0 or fee<0:raise ValueError('Negative settlement amounts')
    return dict(version=VERSION,report_id=report['20105'],ticker=ticker,party_id=party_id,
        yes_fraction=str(price),net_payout_usd=str(net),deducted_fee_usd=str(fee),
        gross_before_fee_usd=str(net+fee),source=load()['sources']['kalshi-fix-settlement'],
        kind='actual_account_amount_report_not_sporting_result',correction_lineage=None)


def local_lineage(visible, wrappers):
    """Receipt-local documented edges, independent of provider publication order.

    Never changes authoritative history selection, payout expectations or clocks.
    Unsupported/mismatched predecessors cannot supersede local observations.
    """
    from app.resolution.core import lineage
    rows={w['record']['id']:w for w in wrappers}
    items={v['id']:v for v in visible if v['record']['payload'].get('adapter')}
    output=[];superseded=set()
    for rid,v in items.items():
        r=v['record'];p=r['payload'];parents=p['supersedes'];reason=None
        if v['reason'] and v['reason'].startswith('Unbound:'):reason=v['reason']
        w=rows[rid]
        if r['received_at'] is None or w['observed_at'] is None or stamp(r['received_at'])>stamp(w['observed_at']):reason='Unknown/conflicting local receipt clock'
        if parents and p['adapter']['format'] not in ('us_instrument','novig_v3_market'):reason='Undocumented correction format'
        for pid in parents:
            prior=items.get(pid)
            if not prior or lineage(prior['record'])!=lineage(r):reason='Local predecessor missing or differently bound';break
            if prior['record']['payload']['adapter']['format']!=p['adapter']['format']:reason='Local predecessor documented format conflict';break
            a=rows[pid]
            if not a['record']['received_at'] or not r['received_at'] or stamp(a['record']['received_at'])>stamp(r['received_at']) or a['cursor']>=w['cursor']:reason='Local predecessor ordering conflict';break
        output.append(dict(id=rid,predecessors=parents,local_state='unsupported' if reason else 'corrected_observation' if parents else 'original_observation',
            reason=reason,reported_status=p['status'],reported_payout=p.get('payout'),source_at=p.get('source_at'),published_at=p.get('published_at'),
            received_at=r['received_at'],observed_at=w['observed_at'],cursor=w['cursor'],provider_revision_id=None))
    # Propagate invalid local predecessor chains without inventing an ordering.
    byid={v['id']:v for v in output}
    for _ in output:
        for v in output:
            if v['local_state']!='unsupported' and any(byid.get(pid,{}).get('local_state')=='unsupported' for pid in v['predecessors']):
                v.update(local_state='unsupported',reason='Local predecessor unsupported')
    for v in output:
        if v['local_state']!='unsupported':superseded.update(v['predecessors'])
    for v in output:
        if v['id'] in superseded:v['local_state']='superseded_observation'
    return dict(basis='Local acknowledged receipt sequence and explicit documented snapshot/remediation associations; not provider publication history',
                authoritative_asof_qualification=False,observations=output)
