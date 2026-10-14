"""Explicit financial names, reconciliation and deterministic opportunity filters."""
from fractions import Fraction as F

from .benchmark import metadata
from .net_costs import wire

VERSION = 'predict-financial-metrics-1'
SUCCESSOR_FIELDS = ('financial_metrics', 'funding', 'benchmark', 'classification', 'model_versions',
                    'sizing_mode', 'requested_amount_usd', 'residual_funding_usd', 'benchmark_venue', 'benchmark_method')


def ws(value):
    return None if value is None else wire(value)


def amount(value):
    return None if value is None else F(value)


def weighted(states, probabilities, field):
    if probabilities is None or any(p is None or (p > 0 and states[s][field] is None) for s,p in probabilities.items()):
        return None
    return sum((p*F(states[s][field]) for s,p in probabilities.items() if p > 0), F(0))


def gross(q, unit, path, quantity, acquisition, weight):
    if weight is None:
        return None
    # Caller supplies the explicitly oriented selected decisive probability.
    if unit.unit == 'stake_usd':
        remaining = quantity; winning = F(0)
        for price,n in path['levels']:
            taken = min(remaining,n); winning += taken*price; remaining -= taken
        winning += remaining*path['last']
    else:
        winning = F(unit.dollar_face(wire(quantity)))
    return weight*winning-F(acquisition)


def classification(kind, net, buffered, decisive, complete, states, *, eligible, condition, reason=None):
    adverse = {s:r['profit_usd'] for s,r in states.items()
               if r['profit_usd'] is not None and F(r['profit_usd']) < 0}
    unknown = [s for s,r in states.items() if r['profit_usd'] is None]
    positive_ev = buffered is not None and buffered > 0
    if kind == 'single':
        category = 'positive_single_ev' if positive_ev and net is not None else 'conditional_single_ev' if positive_ev else 'nonpositive_single' if buffered is not None else 'ev_unavailable'
        main = positive_ev and net is not None
        rule_sensitive = False
    else:
        main = complete is not None and complete > 0
        rule_sensitive = decisive is not None and decisive > 0 and not main
        category = 'positive_complete_modeled_pair' if main else 'rule_sensitive_hedge' if rule_sensitive else 'nonpositive_pair' if decisive is not None else 'pair_unavailable'
    if reason is None:
        reason = ('positive modeled complete minimum' if kind == 'pair' and main else
                  'positive buffered modeled EV' if main else
                  'positive decisive margin; exceptional losses or unknown cashflows remain' if rule_sensitive else
                  'conditional estimate; complete EV unavailable' if condition else
                  'buffered value is zero or negative' if buffered is not None or decisive is not None else
                  'selected benchmark or complete probability/cashflow inputs unavailable')
    return dict(version=VERSION, category=category, main_positive_eligible=bool(main and eligible),
        positive_ev=bool(positive_ev), is_arb=bool(kind == 'pair' and main),
        rule_sensitive=rule_sensitive, positive_rule_sensitive_eligible=bool(rule_sensitive and eligible),
        condition=condition, adverse_outcomes=adverse, unknown_outcomes=unknown,
        reason=reason, guarantees_actual_profit=False)


def funding(result, policy, legs):
    capital = F(result['deployed_capital_usd']); residual = F(policy.capital_ceiling_usd)-capital
    result.update(sizing_mode=policy.sizing_mode, requested_amount_usd=policy.requested_amount_usd,
                  benchmark_venue=policy.benchmark_venue,benchmark_method=policy.benchmark_method,
                  residual_funding_usd=wire(residual))
    result['funding'] = dict(requested_usd=policy.requested_amount_usd, deployed_usd=wire(capital),
        residual_usd=wire(residual), buffer_consumes_funding=False, legs=legs,
        residual_reason=('requested funding fully deployed' if not residual else
                        (result.get('size_search') or result.get('search',{})).get('limitation') or
                        'next legal balanced/grid allocation cannot use residual funding'),
        size_status=result['size_status'], actual_fill_support=False)
    result['model_versions'] = dict(policy_version=policy.version, policy_revision=policy.revision,
        sizing=('ev09-requested-balance-1' if policy.sizing_mode == 'requested_trade' else 'ev06-bounded-ceiling-1') if len(legs)==2 else 'ev05-funded-grid-1',
        financial_metrics=VERSION, benchmark='comparison-two-way-benchmark-1',
        fees='predict-estimate-components-1', payouts='predict-estimate-content-1',
        probability='nfl-disjoint-provisional-prior-1')


def single_metrics(result, policy, reference, weight, component, unit, path, quantity, reference_reason, q):
    from .estimated_ev import cell
    capital = F(result['deployed_capital_usd']); haircut = F(result['buffer_usd'])
    roles = result['orientation']
    selected_home = q['binding']['selection']['participant'] == roles['a_wins']
    selected_probability = None if weight is None else weight if selected_home else 1-weight
    if selected_probability is not None and q['binding']['selection']['predicate'] == 'not_win':
        selected_probability = 1-selected_probability
    g = gross(q,unit,path,quantity,component['acquisition_usd'],selected_probability)
    net = amount(result['fee_adjusted_expected_profit_usd']) if result['conditioning']=='modeled_complete' else None
    conditional = amount(result['conditional_decisive_profit_usd'])
    chosen = net if net is not None else conditional
    probs = None if result['probabilities'] is None else {s:F(p) for s,p in result['probabilities'].items()}
    reconcile_probs = probs if net is not None else None if result['conditional_probabilities'] is None else {s:F(p) for s,p in result['conditional_probabilities'].items()}
    charge = weighted(result['states'],reconcile_probs,'separately_payable_charge_usd')
    upfront = cell(component,'fee','net_entry_fee_usd')
    adjustment = None if g is None or chosen is None or charge is None else chosen-g+upfront+charge
    rows = result['states']; complete = None if any(r['profit_usd'] is None for r in rows.values()) else min(F(r['profit_usd']) for r in rows.values())
    result['financial_metrics'] = dict(version=VERSION, gross_benchmark_ev_usd=ws(g),
        gross_benchmark_return_percent=ws(None if g is None else 100*g/capital),
        net_modeled_ev_usd=ws(net), buffered_ev_usd=ws(None if net is None else net-haircut),
        net_modeled_return_percent=ws(None if net is None else 100*net/capital),
        buffered_return_percent=ws(None if net is None else 100*(net-haircut)/capital),
        conditional_net_ev_usd=ws(conditional), conditional_buffered_ev_usd=ws(None if conditional is None else conditional-haircut),
        decisive_opposing_margin_usd=None, buffered_decisive_opposing_margin_usd=None,
        complete_modeled_minimum_usd=ws(complete), buffered_complete_modeled_minimum_usd=ws(None if complete is None else complete-haircut),
        rule_adjustment_usd=ws(adjustment), net_upfront_fee_usd=ws(upfront),
        expected_settlement_fee_usd=ws(weighted(rows,probs,'separately_payable_charge_usd')),
        reconciliation_expected_settlement_fee_usd=ws(charge),
        reconciliation_condition='complete_disjoint_partition' if net is not None else result['condition'],
        buffer_usd=wire(haircut), percentage_denominator='actual_deployed_capital',
        rule_adjustment_includes='exceptional probability/payout effects, retained/refunded charges, consumed allowances and hold returns',
        expected_charge_is_not_maximum=True, actual_charges=None)
    result['benchmark'] = dict(metadata(reference,policy), reason=reference_reason)
    eligible = not result['eligibility_reasons'] and reference is not None
    result['classification'] = classification('single',net,None if chosen is None else chosen-haircut,
        None,complete,rows,eligible=eligible,condition=result['condition'],reason=reference_reason)
    funding(result,policy,[dict(native_quantity=result['native_quantity'],native_unit=result['native_unit'],
        acquisition_usd=component['acquisition_usd'],upfront_fee_usd=ws(upfront),
        independent_funding_usd=wire(capital-F(component['acquisition_usd'])-upfront))])
    result['model_versions']['content']=component['dependencies']['content']
    result['evaluator_version']='predict-funded-single-2'
    result['version']='predict-estimate-result-2'


def pair_metrics(result, policy, legs, components, probabilities, requested_search):
    capital = F(result['deployed_capital_usd']); haircut = F(result['buffer_usd'])
    net = amount(result['fee_adjusted_expected_profit_usd']); conditional = amount(result['conditional_decisive_profit_usd'])
    refs=[x for x in legs if x.reference is not None]
    # Conflicting revisions withhold all benchmark-derived values.
    coherent = bool(refs) and not any(x.reference_basis!=refs[0].reference_basis for x in refs)
    reference = refs[0].reference if coherent else None
    weight = refs[0].weight if coherent else None
    g = None
    if weight is not None:
        values=[]
        for leg,row,c in zip(legs,result['legs'],components):
            p=weight if leg.q['binding']['selection']['participant']==leg.roles['home'] else 1-weight
            if leg.q['binding']['selection']['predicate']=='not_win':p=1-p
            values.append(gross(leg.q,leg.unit,leg.path,F(row['native_quantity']),c['acquisition_usd'],p))
        g=sum(values,F(0))
    chosen=net if net is not None else conditional
    reconcile_probs=probabilities if net is not None else None if weight is None else dict(a_wins=weight,b_wins=1-weight)
    charge=weighted(result['states'],reconcile_probs,'settlement_charge_usd')
    upfront=F(result['cost_breakdown']['net_upfront_fee_usd'])
    adjustment=None if chosen is None or g is None or charge is None else chosen-g+upfront+charge
    decisive=amount(result['decisive_minimum_usd']); complete=amount(result['all_state_minimum_usd'])
    result['financial_metrics']=dict(version=VERSION,gross_benchmark_ev_usd=ws(g),
        gross_benchmark_return_percent=ws(None if g is None else 100*g/capital),
        net_modeled_ev_usd=ws(net),buffered_ev_usd=ws(None if net is None else net-haircut),
        net_modeled_return_percent=ws(None if net is None else 100*net/capital),
        buffered_return_percent=ws(None if net is None else 100*(net-haircut)/capital),
        conditional_net_ev_usd=ws(conditional),conditional_buffered_ev_usd=ws(None if conditional is None else conditional-haircut),
        decisive_opposing_margin_usd=ws(decisive),buffered_decisive_opposing_margin_usd=ws(None if decisive is None else decisive-haircut),
        buffered_decisive_return_percent=ws(None if decisive is None else 100*(decisive-haircut)/capital),
        complete_modeled_minimum_usd=ws(complete),buffered_complete_modeled_minimum_usd=ws(None if complete is None else complete-haircut),
        rule_adjustment_usd=ws(adjustment),net_upfront_fee_usd=wire(upfront),
        expected_settlement_fee_usd=ws(weighted(result['states'],probabilities,'settlement_charge_usd')),
        reconciliation_expected_settlement_fee_usd=ws(charge),
        reconciliation_condition='complete_disjoint_partition' if net is not None else result['condition'],
        buffer_usd=wire(haircut),percentage_denominator='actual_deployed_capital',
        rule_adjustment_includes='exceptional probability/payout effects, retained/refunded charges, consumed allowances and hold returns',
        expected_charge_is_not_maximum=True,actual_charges=None)
    reason=result['reasons'][0] if result['reasons'] else None
    result['benchmark']=dict(metadata(reference,policy),reason=reason)
    source_ok=all(not x._source_reasons() for x in legs)
    result['classification']=classification('pair',net,None if chosen is None else chosen-haircut,
        None if decisive is None else decisive-haircut,None if complete is None else complete-haircut,
        result['states'],eligible=source_ok,condition=result['condition'],reason=reason if decisive is None else None)
    if requested_search is not None:
        result['search'].update(requested_search)
    result['objective']='requested_funded_net_balance' if policy.sizing_mode=='requested_trade' else result['objective']
    result['version']='predict-funded-pair-2'
    result['minimum_spend_solution']=False if policy.sizing_mode=='requested_trade' else result['minimum_spend_solution']
    funding(result,policy,[dict(leg,deployed_capital_usd=c['deployed_capital_usd'],
        independent_funding_usd=wire(F(c['deployed_capital_usd'])-F(c['acquisition_usd'])-F(leg['net_upfront_fee_usd'])))
        for leg,c in zip(result['legs'],components)])
    result['model_versions']['content']=[{k:v['recipe']['id'] for k,v in x.content.items()} for x in legs]


def unavailable(result, policy, reason, *, pair=False):
    """Unavailable results retain exact settings and a simple filter reason."""
    result.update(version='predict-funded-pair-2' if pair else 'predict-funded-single-2',
        sizing_mode=policy.sizing_mode,requested_amount_usd=policy.requested_amount_usd,
        benchmark_venue=policy.benchmark_venue,benchmark_method=policy.benchmark_method,
        residual_funding_usd=None,benchmark=dict(metadata(None,policy),reason=reason),
        financial_metrics=dict(version=VERSION,gross_benchmark_ev_usd=None,net_modeled_ev_usd=None,
            buffered_ev_usd=None,decisive_opposing_margin_usd=None,buffered_decisive_opposing_margin_usd=None,
            complete_modeled_minimum_usd=None,buffered_complete_modeled_minimum_usd=None),
        classification=classification('pair' if pair else 'single',None,None,None,None,{},
                                    eligible=False,condition=None,reason=reason),
        funding=dict(requested_usd=policy.requested_amount_usd,deployed_usd=None,residual_usd=None,
                     buffer_consumes_funding=False,legs=[],residual_reason=reason,
                     size_status='unavailable',actual_fill_support=False),
        model_versions=dict(policy_version=policy.version,policy_revision=policy.revision,
                            financial_metrics=VERSION))
