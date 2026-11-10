"""Explicit hypothetical inputs adapted to the shared exact portfolio/policy owners."""
from fractions import Fraction as F
from app.comparison.cashflows import exact_wire as wire, _shared_result
from app.comparison.estimated_policy import EstimateResult, buffer_usd, load, number
from app.comparison.effective_policy import effective_policy
from app.storage.store import hashed

VENUES = ('kalshi', 'polymarket_us', 'novig', 'prophetx')


def assumptions(value=None):
    if value is not None and not isinstance(value,dict):raise ValueError('Snapshot assumptions must be an object')
    value = dict(value or {})
    value.pop('revision', None)
    if not isinstance(value, dict) or set(value)-{'amount','buffer','benchmark_venue','fees','scenario','sizing','exception_probability','scoring'}:
        raise ValueError('Unknown snapshot assumption')
    base = load()
    policy = effective_policy(base, **{k:value[k] for k in ('amount','buffer','benchmark_venue') if k in value})
    fees = value.get('fees', {})
    if not isinstance(fees, dict) or set(fees)-set(VENUES):raise ValueError('Unknown fee venue')
    fees = {v:None if fees.get(v) in (None,'') else fees[v] for v in VENUES}
    for fee in fees.values():
        if fee is not None and (not isinstance(fee,str) or len(fee)>40 or not 0<=number(fee)<=1):
            raise ValueError('Fee must be an explicit rate between zero and one')
    scoring = value.get('scoring','unavailable')
    if scoring not in ('unavailable','ncaab_full_game_overtime'):raise ValueError('Unknown scoring assumption')
    scenario = value.get('scenario','unavailable')
    sizing = value.get('sizing','unavailable')
    probability = value.get('exception_probability')
    if probability=='':probability=None
    if scenario not in ('unavailable','decisive_only','refund_other') or sizing not in ('unavailable','hypothetical_fractional'):
        raise ValueError('Unknown scenario or sizing treatment')
    if probability is not None and (not isinstance(probability,str) or len(probability)>40 or not 0<=number(probability)<=1):
        raise ValueError('Exceptional probability must be between zero and one')
    out = dict(amount=policy.capital_ceiling_usd, buffer=policy.buffer_rate,
        benchmark_venue=getattr(policy,'benchmark_venue','pinnacle'),fees=fees,scenario=scenario,sizing=sizing,
        exception_probability=probability,scoring=scoring)
    return dict(out,revision=hashed(out)), policy


def funded(costs, probabilities, venues, settings, policy):
    """Equal normal-claim allocation, with upfront fees included in funding.

    Fractional quantities and the declared receipts are assumptions, not fills.
    Joint scenario aggregation and buffer/result arithmetic have shared owners.
    """
    missing=[]
    if settings['scenario']=='unavailable':missing.append('payout/scenario assumption')
    if settings['sizing']=='unavailable':missing.append('sizing/depth assumption')
    if any(settings['fees'][v] is None for v in venues):missing.append('upfront fee rate for each leg')
    if missing:return dict(available=False,missing=missing)
    costs=tuple(F(c) for c in costs)
    fees=tuple(c*F(settings['fees'][v]) for c,v in zip(costs,venues))
    quantity=F(policy.capital_ceiling_usd)/sum((c+f for c,f in zip(costs,fees)),F(0))
    cash=tuple((c+f)*quantity for c,f in zip(costs,fees))
    states=('selected_wins','opposite_wins')
    receipts=tuple({states[0]:quantity if i==0 else F(0),states[1]:quantity if i==1 else F(0)} for i in range(len(costs)))
    if settings['scenario']=='refund_other':
        states=(*states,'other_refund')
        for i,row in enumerate(receipts):row['other_refund']=costs[i]*quantity
    result=_shared_result(cash,receipts,states,complete=True,reserve=F(0))
    deployed=sum(cash,F(0));buffer=buffer_usd(deployed,policy.buffer_rate)
    p=None if probabilities[0] is None else F(probabilities[0])
    profits={s:F(v) for s,v in result['states'].items()}
    conditional=None if p is None else p*profits['selected_wins']+(1-p)*profits['opposite_wins']
    expectation=conditional
    if settings['scenario']=='refund_other':
        u=settings['exception_probability']
        expectation=None if p is None or u is None else (1-F(u))*conditional+F(u)*profits['other_refund']
    metric=EstimateResult(policy,wire(deployed),wire(expectation),
        'unavailable' if expectation is None else 'modeled_complete' if settings['scenario']=='refund_other' else 'modeled_conditional',
        'modeled_size').to_dict()
    return dict(available=True,missing=(['decisive benchmark probability'] if p is None else [])+
        (['exceptional-state probability'] if settings['scenario']=='refund_other' and settings['exception_probability'] is None else []),
        **metric, conditional_net_usd=wire(conditional),
        scenario_minimum_usd=wire(min(profits.values())-buffer),
        scenario_minimum_percent=wire((min(profits.values())-buffer)/deployed*100),
        quantity_per_leg=wire(quantity),acquisition_usd=[wire(c*quantity) for c in costs],
        upfront_fees_usd=[wire(f*quantity) for f in fees],scenario_profits_usd=result['states'],
        scenario_receipts_usd=[{k:wire(v) for k,v in r.items()} for r in receipts],
        arithmetic=result['arithmetic'],executable=False,
        formula='q = funding / sum(cost × (1 + fee rate)); state profit = sum(receipts) − deployed; EV = sum(probability × state profit); buffered metric = metric − buffer rate × deployed (once)',
        meaning='Assumed fractional size at captured top prices; fees are upfront fractions of acquisition. Other-refund returns acquisition only and retains fees. No other costs included. No fill or verified settlement claim.')


def before_fee_pair(left, right, market_key):
    """Equal normal payouts on complementary completed-game score ranges."""
    if left['venue'] == right['venue'] or any(row.get('cost_per_normal_claim') is None for row in (left, right)):
        return None
    a, b = (row.get('same_outcome', {}).get('key') for row in (left, right))
    if not a or not b or len(a) != 13 or len(b) != 13:
        return None
    if a[:7] != b[:7] or a[-2:] != b[-2:]:
        return None
    domain, lower, low, subject = a[9]
    other_domain, upper, high, other_subject = b[9]
    if (domain, subject, lower, upper) != (other_domain, other_subject, 'ge', 'le'):
        return None
    gap = F(*low) - F(*high)
    equality = (a[10], b[10])
    payouts = {'first_wins': ['1', '0'], 'second_wins': ['0', '1']}
    if gap == 1 and equality == (['predicate'], ['predicate']):
        pass
    elif gap == 2 and all(eq[0] == 'fraction' and eq[2] is not None for eq in equality):
        if equality[0][1] != equality[1][1] or sum(F(*eq[2]) for eq in equality) != 1:
            return None
        payouts['equality'] = [wire(F(*eq[2])) for eq in equality]
    else:
        return None
    costs = tuple(F(row['cost_per_normal_claim']) for row in (left, right))
    if not all(0 < cost < 1 for cost in costs):
        return None
    from app.opportunities.percentages import normalized_pair
    result = normalized_pair(*costs)
    return dict(market_key=market_key, value=str(F(int(result['numerator']), int(result['denominator']))),
                weights=[str(cost / sum(costs)) for cost in costs], settlement_payouts=payouts)
