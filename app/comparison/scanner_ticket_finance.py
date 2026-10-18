"""Selected requested-budget reconciliation over observed legal fills.

The existing allocation consumer, settlement-pool algebra and requested balance
solver remain the owners. Scanner classification is applied once to the final
allocation; discovery examples never determine a selected ticket's quantities.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction as F

from .calculation_control import checkpoint
from .current_dependencies import digest, instant
from .estimated_ev import _fills, cell
from .estimated_pair import (Leg, economics, native_key, probabilities,
                             EXPOSURE_FLOOR, MIN_SHARE, MAX_NATIVE)
from .estimated_policy import DEFAULT_POLICY, RequestedTradePolicy
from .net_costs import wire
from .requested_sizing import allocations
from .scanner_finance import _joint, classify

VERSION = 'predict-scanner-ticket-finance-1'


def requested_policy(policy):
    """Omitted Amount uses the projection default with requested-trade sizing."""
    if isinstance(policy, RequestedTradePolicy):
        return replace(policy, sizing_mode='requested_trade')
    return RequestedTradePolicy(capital_ceiling_usd=policy.capital_ceiling_usd,
        buffer_rate=policy.buffer_rate, tie=policy.tie,
        terminal_noncompletion=policy.terminal_noncompletion)


def _american(decimal_odds):
    if decimal_odds <= 1:
        return None
    return wire(100*(decimal_odds-1) if decimal_odds >= 2 else -100/(decimal_odds-1))


def calculate(pair, instruments, inputs, *, at, policy=DEFAULT_POLICY):
    """Calculate one combined funded request or raise for mandatory unknowns.

    No acquisition, persistence, original-quote mutation or execution occurs.
    Missing/incomparable joint meaning stays conditional and explicit. Missing
    reference inputs remove EV only; unknown admitted-state cashflows fail.
    """
    policy=requested_policy(policy)
    keys=sorted(pair['legs'])
    if len(keys)!=2 or len(set(keys))!=2:
        raise ValueError('ticket_two_distinct_legs_required')
    legs=[]
    for key in keys:
        checkpoint();x=inputs[key]
        legs.append(Leg(x['quote'],x['group'],x['profiles'],x['event'],instant(at),policy=policy))
    if len({x.q['venue'] for x in legs})!=2 or any(x.q['venue']=='pinnacle' for x in legs):
        raise ValueError('ticket_distinct_execution_venues_required')
    if legs[0].sign==legs[1].sign:
        raise ValueError('ticket_opposing_decisive_exposures_required')
    if (legs[0].event['id']!=legs[1].event['id'] or
            legs[0].group['period']!=legs[1].group['period']):
        raise ValueError('ticket_occurrence_period_conflict')
    liquidity=[(x.q['venue'],x.q['source']['provider'],*native_key(x.q)[1:4]) for x in legs]
    if (liquidity[0]==liquidity[1] or legs[0].liquidity_ids & legs[1].liquidity_ids or
            (legs[0].shared_depth and legs[0].shared_depth==legs[1].shared_depth)):
        raise ValueError('ticket_shared_depth_conflict')
    for leg in legs:
        if leg._source_reasons():
            raise ValueError('; '.join(leg._source_reasons()))
        if 'state_cashflows' in leg.funding:
            raise ValueError('ticket_absolute_cashflows_require_fixed_allocation')
    upper=[x.floor(min(MAX_NATIVE,sum((n for _,n in x.path['levels']),F(0)))) for x in legs]
    # floor() clamps below its grid minimum, so also inspect raw observed sums.
    if any(sum((n for _,n in x.path['levels']),F(0))<x.lower or n<x.lower for x,n in zip(legs,upper)):
        raise ValueError('ticket_observed_depth_below_meaningful_minimum')
    basis,complete=_joint(legs)
    budget=F(policy.requested_amount_usd)
    candidates,search=allocations(legs,budget,basis,economics,observed_bounds=upper)
    best=None;evaluations=0
    for qs in candidates:
        checkpoint();evaluations+=1
        if any(n<x.lower or n>bound or x.floor(n)!=n for x,n,bound in zip(legs,qs,upper)):
            continue
        components=[x.get(n) for x,n in zip(legs,qs)]
        if any(F(c['pair_support'])!=n for c,n in zip(components,qs)):
            raise ValueError('ticket_unobserved_quantity_forbidden')
        exposures=[c['_pair_exposure'] for c in components]
        if any(v is None for v in exposures):
            raise ValueError('ticket_decisive_exposure_unknown')
        if min(exposures)<EXPOSURE_FLOOR or min(exposures)<MIN_SHARE*sum(exposures):
            continue
        capital,states=economics(components,basis)
        if not 0<capital<=budget:
            continue
        if any(s['profit_usd'] is None for s in states.values()):
            raise ValueError('ticket_mandatory_state_cashflows_unknown')
        score=(-abs(F(states['a_wins']['profit_usd'])-F(states['b_wins']['profit_usd'])),capital,qs)
        if best is None or score>best[0]:
            best=(score,tuple(qs),capital)
    if best is None:
        raise ValueError('ticket_no_feasible_observed_requested_allocation')
    _,qs,_=best
    components=[x.get(n,rich=True) for x,n in zip(legs,qs)]
    capital,states=economics(components,basis)
    if any(s['profit_usd'] is None for s in states.values()):
        raise ValueError('ticket_mandatory_state_cashflows_unknown')
    probs,weight,reference_reason=probabilities(legs,basis,policy)
    conditional=None if weight is None else dict(a_wins=weight,b_wins=1-weight)
    ev_current=any(instruments[k].get('checks',{}).get('ev',{}).get('state')=='ready' for k in keys)
    metrics,categories=classify(states,capital,policy=policy,settlement_complete=complete,
        probabilities=probs,conditional_probabilities=conditional,ev_current=ev_current)
    reasons=[] if complete else ['joint_settlement_meaning_unknown']
    haircut=F(metrics['buffer_usd'])
    for state in states.values():
        state['buffered_profit_usd']=wire(F(state['profit_usd'])-haircut)
    rows=[]
    for key,leg,n,component in zip(keys,legs,qs,components):
        fills,support=_fills(leg.path,n,leg.q['venue'])
        acquire=F(component['acquisition_usd']);fee=cell(component,'fee','net_entry_fee_usd')
        if fee is None:
            raise ValueError('ticket_mandatory_entry_fee_unknown')
        # Price-equivalent odds deliberately exclude fees, holds and settlement.
        if leg.path['stake']:
            odds=sum(F(r['stake_usd'])*F(r['decimal_odds']) for r in fills['stake_fills'])/n
        else:
            probability=acquire/(n*leg.path['per_native'])
            odds=1/probability
        model_versions={k:v.get('recipe',{}).get('id') for k,v in leg.content.items()}
        rows.append(dict(instrument_id=key,quote_id=leg.q['id'],quote_revision=leg.q['revision'],
            venue=leg.q['venue'],source=deepcopy(leg.q['source']),native_key=list(native_key(leg.q)),
            native_action=leg.q['source']['native_side'],predicate=deepcopy(leg.q['binding']['selection']),
            original=deepcopy(leg.q['original']),native_quantity=wire(n),native_unit=asdict(leg.unit),
            observed_native_quantity=wire(support),modeled_native_quantity='0',grid=deepcopy(leg.grid),
            fills=fills,american_odds=_american(odds),decimal_odds=wire(odds),
            odds_basis='observed_fill_price_equivalent_before_costs',
            acquisition_usd=wire(acquire),net_upfront_fee_usd=wire(fee),
            independent_funding_usd=wire(F(component['deployed_capital_usd'])-acquire-fee),
            deployed_capital_usd=component['deployed_capital_usd'],
            source_times=deepcopy(leg.q['times']),model_versions=model_versions,
            input_refs=deepcopy(leg.q['comparison_input_refs']),
            allocation_dependency_revision=component['dependency_revision'],
            funding_components=deepcopy(component['dependencies']['extra_funding']),
            hold_returns=deepcopy(component['dependencies']['hold_returns']),
            allocation_components=deepcopy(component['components']),
            component_refs=component['profile_refs'],component_profiles=component['profiles'],
            settlement_terms=component['settlement_terms'],payout_details=component['payout_details'],
            settlement_already_withheld=component['settlement_already_withheld']))
    funding=dict(requested_amount_usd=wire(budget),funded_budget_usd=wire(budget),
        deployed_capital_usd=wire(capital),residual_cash_usd=wire(budget-capital),
        acquisition_usd=wire(sum(F(r['acquisition_usd']) for r in rows)),
        net_upfront_fee_usd=wire(sum(F(r['net_upfront_fee_usd']) for r in rows)),
        independent_funding_usd=wire(sum(F(r['independent_funding_usd']) for r in rows)),
        buffer_usd=wire(haircut),buffer_applications=1,buffer_consumes_funding=False,
        basis='one_combined_independent_funded_budget; no cross_venue_rehypothecation')
    search.update(evaluations=evaluations,maximum_evaluations=25,maximum_size_proven=False,
        observed_bounds=[wire(n) for n in upper],observed_only=True,
        residual_reason='legal net-balance neighborhood, observed depth, final fees and independent funding',
        basis='requested_trade_observed_legal_net_balance')
    summary=[{k:r[k] for k in ('venue','native_key','native_action','predicate','original',
        'native_quantity','native_unit','american_odds','acquisition_usd','net_upfront_fee_usd',
        'independent_funding_usd','deployed_capital_usd')} for r in rows]
    result=dict(version=VERSION,context=dict(event={k:deepcopy(inputs[keys[0]]['event'][k]) for k in ('id','title','participants','start_at','league') if k in inputs[keys[0]]['event']},
        market={k:deepcopy(inputs[keys[0]]['group'][k]) for k in ('id','market','period') if k in inputs[keys[0]]['group']}),categories=categories,metrics=metrics,legs=rows,manual_legs=summary,
        funding=funding,states=states,reasons=sorted(set(reasons)),settlement_complete=complete,
        size_status='supported_size',search=search,policy=policy.to_dict(),
        probabilities=None if probs is None else {k:None if p is None else wire(p) for k,p in probs.items()},
        conditional_probabilities=None if conditional is None else {k:wire(p) for k,p in conditional.items()},
        ev_reference=dict(available=probs is not None or conditional is not None,current=ev_current,reason=reference_reason),
        constraints=dict(minimum_decisive_exposure_usd=wire(EXPOSURE_FLOOR),minimum_exposure_share=wire(MIN_SHARE)),
        probability_basis=dict(revision=next((x.reference_basis for x in legs if x.reference is not None),None)),
        risks=['modeled_costs_and_settlement; manual_execution_prices_can_change',
               'one_budget_uses_independent_venue_funding; no_cash_reuse',
               'bounded_local_balance_search; global_optimality_and_maximum_size_unproven'],
        evaluated_at=instant(at).isoformat())
    return dict(result,revision=digest(result))
