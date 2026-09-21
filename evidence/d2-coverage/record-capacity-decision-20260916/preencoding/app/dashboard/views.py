"""Allowlisted browser projections. Financial values remain engine Decimal strings."""
from datetime import datetime, timezone
from decimal import Decimal
from app.arbitrage import wire, seconds

VENUES={'kalshi':'Kalshi','polymarket_us':'Polymarket US','prophetx':'ProphetX','novig':'Novig'}

def plain_reason(reason):
    if 'settlement' in reason or 'complementary' in reason: return 'Settlement rules unresolved'
    if any(x in reason for x in ('ask-unavailable','observation-unavailable','ladder-unavailable')): return 'Missing price or book'
    if 'fee' in reason: return 'Fee assumption required'
    if 'source-time-semantics-unknown' in reason:return 'Source clock meaning unresolved'
    if any(x in reason for x in ('stale','skew','source-time','receipt-in-future')): return 'Stale observation or clock mismatch'
    if 'reconstruction' in reason: return 'Venue disconnected or awaiting a fresh book'
    if 'lock' in reason: return 'Market lock status unresolved'
    if 'market-' in reason: return 'Market is not confirmed active'
    if any(x in reason for x in ('sizing','size-','unit','quantity','increment','minimum')): return 'Sizing not verified'
    if 'guarantee' in reason: return 'Some outcome results are unknown'
    if 'parent' in reason or 'match' in reason: return 'Event or market match needs evidence'
    return 'Additional evidence required'


def fee_view(f):
    if not f: return dict(entry_fees=None,conditions=['Fee calculation unavailable'])
    return {k:f.get(k) for k in ('engine','entry_fees','entry_cash_requirement','assumptions','unsupported','qualification')}


def side_labels(rows):
    return {(r["key"],s["native_id"]):s.get("participant",s["native_id"]).replace("NFL:","")+(" wins" if s.get("predicate")=="win" else " does not win") for r in rows for s in r.get("sides",[])}


def candidate_view(c, titles=None, labels=None):
    titles=titles or {};labels=labels or {}
    calc=c.get('conditional_calculation'); legs=[]
    for leg in c['legs']:
        o=leg.get('observation') or {}
        legs.append(dict(venue=VENUES.get(o.get('venue'), 'Price unavailable'),side=leg['side'],side_label=labels.get((leg['native_market_key'],leg['side']),leg['side']),
            market_key=leg['native_market_key'],title=titles.get(leg['native_market_key'],''),
            price=o.get('ask'),size=o.get('available'),unit=o.get('unit'),received_at=o.get('received_at'),
            source_at=o.get('exchange_at'),source_time_meaning=o.get('source_time_semantics'),
            state=o.get('state'),sync=o.get('sync'),liquidity_family=leg['liquidity_family']))
    reasons=list(dict.fromkeys(plain_reason(r) for r in c['reasons']))
    if calc:
        profit=calc['worst_case_profit']
        label='Qualified modeled' if c['qualified_modeled_arbitrage'] else 'Conditional calculation'
        outcomes={k:{a:v.get(a) for a in ('profit','roi','settlement_fees','net_payout')} for k,v in calc['outcomes'].items()}
    else: profit=None;label='Pricing diagnostic';outcomes={}
    return dict(id=c['id'],pair_id=c['pair_id'],title=next((x['title'] for x in legs if x['title']),c['pair_id']),
        classification=label,reasons=reasons or ['Model conditions apply'],technical_reasons=c['reasons'],legs=legs,
        ask_sum=c['pricing_diagnostic']['ask_sum'],raw_gap=c['pricing_diagnostic']['unit_payout_reference_gap'],
        skew_seconds=c['pricing_diagnostic']['observation_skew_seconds'],profit=profit,
        roi=calc.get('worst_case_roi') if calc else None,minimum_known_profit=calc.get('minimum_known_profit') if calc else None,
        fees=[fee_view(f) for f in calc['fee_audits']] if calc else [],outcomes=outcomes,
        assumptions=calc['assumptions'] if calc else [],quantity=calc.get('quantity') if calc else None,
        quantity_mode=calc.get('quantity_mode') if calc else None,qualified=bool(c['qualified_modeled_arbitrage']),
        current_opportunity=bool(c['current_production_opportunity']),scope=c['scope'])


def age_view(view, *, active=False, health=None):
    """Project time/eligibility on every request; old prices never stay live eligible."""
    import copy
    v=copy.deepcopy(view); at=datetime.now(timezone.utc)
    for market in v.get('markets',[]):
        venue=market['venue_key']; status=(health or {}).get(venue,{}).get('state','stopped')
        if not active: status='saved'
        for q in market.get('quotes',[]):
            t=q.get('received_at')
            q['receipt_age_seconds']=str(seconds(at-datetime.fromisoformat(t))) if t else None
            q['source_age_seconds']=str(seconds(at-datetime.fromisoformat(q['exchange_at']))) if q.get('exchange_at') else None
            q['live_eligible']=bool(active and status=='connected' and t and Decimal(q['receipt_age_seconds'])>=0 and Decimal(q['receipt_age_seconds'])<=Decimal(str(v.get('freshness_seconds',30))) and q.get('sync')=='synchronized' and q.get('state')=='active')
            q['display_state']='Saved observation' if not active else 'Disconnected' if status not in ('connected','snapshot') else 'Stale observation' if t and Decimal(q['receipt_age_seconds'])>Decimal(str(v.get('freshness_seconds',30))) else 'Observed price'
        market['connection']=status
    for c in v.get('candidates',[]):
        for leg in c['legs']:
            t=leg.get('received_at'); leg['receipt_age_seconds']=str(seconds(at-datetime.fromisoformat(t))) if t else None
            leg['source_age_seconds']=str(seconds(at-datetime.fromisoformat(leg['source_at']))) if leg.get('source_at') else None
        healthy=all(any(m['key']==leg['market_key'] and any(q['live_eligible'] for q in m['quotes']) for m in v.get('markets',[])) for leg in c['legs'])
        fresh_legs=all(l.get('receipt_age_seconds') is not None and 0<=Decimal(l['receipt_age_seconds'])<=Decimal(str(v.get('freshness_seconds',30))) for l in c['legs'])
        c['current_opportunity']=bool(active and healthy and fresh_legs and c['current_opportunity'])
    v['active']=active;v['current_opportunities']=sum(c['current_opportunity'] for c in v.get('candidates',[]))
    return v


def depth_view(a):
    return dict(id=a['id'],available=a['search']['optimality']!='unsized-inputs',engine=a['engine'],reasons=[plain_reason(r) for r in a['reasons']],
        search=a['search'],solutions={k:dict(optimality=s['optimality'],allocation={x:s['allocation'].get(x) for x in
            ('quantities','worst_case_profit','worst_case_roi','minimum_known_profit','entry_fees','roi_denominator','required_cash','constraint_reasons','qualified_modeled_arbitrage')}) for k,s in a['solutions'].items()},
        note='Bounded search over supplied levels. Related liquidity cannot be added together; both modeled legs must fill.')
