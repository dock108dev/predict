"""Read-only Novig NFLWIN product model, independent of execution qualification.

Original aggregate offers remain unchanged. Dollar risk is a hypothetical
normalization of decimal odds, not native depth, legal grid or a verified fill.
"""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F

from .current_dependencies import digest, instant, references
from .domain import CanonicalSelection, EvidenceReference, ExactNumber
from .net_costs import wire

VERSION = 'novig-nflwin-public-model-20261022-2'
START = '2026-10-22T00:00:00Z'
END = '2026-10-29T00:00:00Z'
FEES = 'https://support.novig.com/en/articles/16195057-fees-on-novig'
RULES = 'https://novig.intercom-attachments-1.com/i/o/y5ui11zw/2574338241/138190d9b820637c62eaad1d0718/NFL%2BWinner%2BSeries.pdf'
BASIS = dict(version=VERSION, effective_from=START, effective_until=END,
    product='Novig NFLWIN full-game including overtime',
    observed='The Odds API Novig pregame h2h decimal odds and original two-sided benchmark',
    rules='NFL-004: winner $1, loser $0, tie $0.50 per contract; void uses fair value with return-of-funds fallback.',
    charges='Published pregame straight-trade fee is zero; full winning payout. Account, transfer and tax costs are outside this trade-only estimate.',
    quantity='Hypothetical USD risk at the retained decimal odds; no native size, depth, fill or execution claim.',
    probability='Decisive weights: original selected two-way proportional no-vig. Full EV sensitivity: tie 0.5%, void 0.1%, decisive 99.4%; these are uncalibrated assumptions, not measured NFL frequencies.',
    exceptional_model='Displayed full EV is a hypothetical refund-only scenario within void, not a central forecast. Refund is the final fallback, not the default rule. Neither refund frequency nor expected fair value conditional on void is estimated. Sensitivity varies both independently; original decisive probability is not reused as future fair value.',
    missing='Calibrated EV still needs validated tie/void probabilities and a fair-value/refund model. Covered arbitrage needs every feasible joint cashflow and supported allocations; the expected void receipt cannot supply a minimum.',
    sources=[FEES, RULES], execution_qualified=False,
    evidence_kind='documented_product_rules_with_uncalibrated_scenarios',
    rule_sections='NFLWIN / NFL-004, Public Appendix A: Payout Criterion (PDF p5), Official Game and Winner Rule (p6-7), Fair Value Settlement Rule (a)-(g) (p8-10). Retrieved 2026-10-22; attachment identity 2574338241/138190d9b820637c62eaad1d0718; no printed revision date.',
    historical_context='2017-2024 completed regular-season games: 7 ties / 2111 (0.332%; descriptive Wilson 95% interval 0.161%-0.683%). Under the changed 2025 overtime rule: 1 / 272 (0.368%; 0.065%-2.053%). nflverse games.csv, retrieved 2026-10-22. Neither sample calibrates this game at its observation time; postseason excluded.',
    review_horizon='Review before 2026-10-29 UTC, the next NFL scheduling week; withdraw earlier on rule/fee changes or kickoff. This is a review deadline, not evidence of probability stability.',
    scenario_parameters=dict(tie_probability='0.005',void_probability='0.001',refund_given_void='1',expected_fair_value_given_nonrefund=None),
    sensitivity_scope='Hypothetical tie 0%-2.5% and void 0%-1%, independently; refund share 0%-100%, expected fair value $0-$1 per face. Probability limits are illustrative, not confidence bounds. Fair-value endpoints follow the public rule, but this aggregate mapping is not a guaranteed settlement binding.')


def single(q, profiles, *, at, event, group, policy, benchmark=None):
    """Return None outside the narrowly supported family; refuse bad bindings."""
    if (q['venue']!='novig' or q['source']['provider']!='the_odds_api' or
            event['league']!='NFL' or group['market']!='winner' or group['period']!='full_game' or
            q['source']['native_side']!='bookmaker_outcome' or q['binding']['selection']['predicate']!='win'):
        return None
    if not instant(START)<=at<instant(END):
        raise ValueError('modeled_winner_basis_expired_or_not_effective')
    if at>=instant(event['start_at']):raise ValueError('modeled_winner_pregame_ended')
    if q['original']['units']!='decimal_odds' or F(q['original']['value'])<=1:
        raise ValueError('modeled_winner_original_units_conflict')
    values=references(q,profiles)
    if any(k in values for k in ('fee','payout')):
        return None  # A public model cannot supersede a bound instrument charge/rule.
    for kind in ('identity','reference'):
        value=values.get(kind)
        if value is None:raise ValueError(kind+'_inputs_missing')
        if value['expires_at'] is not None and at>=instant(value['expires_at']):
            raise ValueError(kind+'_inputs_expired')
    if q.get('comparison_input_refs',{}).get('phase')=='live':
        raise ValueError('modeled_winner_live_scope_unsupported')
    from .bound_finance import gross_quote
    probe=gross_quote(dict(revision='model-probe'),q,profiles,at=at,event=event,group=group,policy=policy,benchmark=benchmark)
    gross=probe['gross_decisive_benchmark']
    if not gross['available']:raise ValueError(gross['reason'])
    values=references(q,profiles)
    selected=CanonicalSelection.from_dict(values['identity']['payload']['selection'])
    # The scoped product mapping is an estimate binding, never a native contract ID.
    # Aggregate decimal odds normalize risk; avoid manufacturing exchange ticks.
    selected=replace(selected,scope=replace(selected.scope,completion='modeled:NFLWIN-official-result'),equality=replace(selected.equality,treatment='unknown',payout=None,
        refund_fees='not_applicable',unknown_reason='modeled_product_equality_in_payout_profile'))
    odds=F(q['original']['value']);amount=F(policy.capital_ceiling_usd)
    risk=(amount*100)//1/F(100)
    if risk<=0:raise ValueError('modeled_winner_amount_below_cent')
    ev=EvidenceReference('model:'+VERSION,digest(BASIS),'manual_review')
    from .payouts import PayoutProfile,PayoutCell,NormalCondition,CompletionContext,bind_profile,selection_digest
    cell=lambda n:PayoutCell(ExactNumber(wire(n)),'estimated','Public NFLWIN product mapping to aggregate offer; not individual execution proof')
    home=selected.participant_id==selected.event.home_id
    payout=PayoutProfile(VERSION,VERSION,VERSION,selected.native.key,selection_digest(selected),
        'usd_per_usd_stake',START,END,(ev,),cell(0 if home else odds),cell(odds/2),cell(odds if home else 0),
        PayoutCell(None,'unknown','Void fair value is determined later; fallback may return funds at risk'),
        'not_applicable',NormalCondition('conditional_completed_result',None,None,None,None))
    bound=bind_profile(selected,payout,at=at,rule_revision=VERSION,
        context=CompletionContext(None,None,'America/New_York',(ev,)))
    from .cashflows import cashflow_inputs
    scenario=cashflow_inputs((bound,),(wire(risk),),at=at)
    from .costs import CostRule,CostRequest,CostRegistry,UnitSpec,FeeTerms,QuantityGridInputs,FillInputs
    # Controlled product scenario scopes public trading fees; no account assertion.
    rule=CostRule(VERSION,'novig','single','public_pregame_model','controlled_scenario',START,END,END,
        UnitSpec('stake_usd',None),FeeTerms('quantity','0','0.00001','half_up','order','taker'),
        'declared_zero',True,(ev,),source_url=FEES)
    request=CostRequest('novig','single','public_pregame_model',at.isoformat(),at.isoformat(),
        pinned_version=VERSION,allow_controlled_scenario=True,
        event_id=selected.native.event_id,market_id=selected.native.market_id)
    from .net_costs import calculate_net_costs
    def cost_for(inputs):
        return calculate_net_costs(request,inputs,native_quantity=wire(risk),native_price=q['original']['value'],
            fills=[],grid=QuantityGridInputs('0.01','0.01',None,ev),
            fill_inputs=FillInputs('hypothetical_one_order',True,1,1,('modeled-order',)),
            registry=CostRegistry(dict(schema=1,version='comparison-cost-inputs-1',rules=[rule.to_dict()])),
            ceiling_usd=policy.capital_ceiling_usd)
    costs=cost_for(scenario)
    if not costs['available']:raise ValueError('; '.join(costs['reasons']))
    probability=F(gross['selected_decisive_probability'])
    home_weight=probability if home else 1-probability
    from .net_ev import ProbabilityInputs,estimated_net_ev
    probabilities=ProbabilityInputs('independent_model',scenario.table.revision,'conditional',
        'decisive_home_or_away_win',(('completed:None:-1',ExactNumber(wire(1-home_weight))),
        ('completed:1:None',ExactNumber(wire(home_weight)))),(ev,),START,END,True)
    natural=estimated_net_ev(scenario,costs,None,at=at,execution_source_at=q['times']['source_at'],
        probability=probabilities,allow_last_known=True)
    if not natural['available']:raise ValueError(natural['reason'])
    conditional=natural
    # Expected receipts within the void bucket are a model input, not a terminal
    # floor. Preserve the actual unknown exceptional cashflow separately below.
    expected_void_per_risk=F(1)  # Explicit refund scenario, not a fitted void expectation.
    modeled_payout=replace(payout,noncompleted=PayoutCell(ExactNumber(wire(expected_void_per_risk)),
        'estimated',BASIS['exceptional_model']))
    modeled_bound=bind_profile(selected,modeled_payout,at=at,rule_revision=VERSION,context=bound.context)
    modeled_scenario=cashflow_inputs((modeled_bound,),(wire(risk),),at=at)
    complete_probabilities=ProbabilityInputs('independent_model',modeled_scenario.table.revision,'complete',
        'uncalibrated_NFLWIN_terminal_expectation_sensitivity',(
            ('completed:None:-1',ExactNumber(wire(F('0.994')*(1-home_weight)))),
            ('completed:0:0',ExactNumber('0.005')),
            ('completed:1:None',ExactNumber(wire(F('0.994')*home_weight))),
            ('noncompleted',ExactNumber('0.001'))),(ev,),START,END,True)
    modeled_costs=cost_for(modeled_scenario)
    natural=estimated_net_ev(modeled_scenario,modeled_costs,None,at=at,execution_source_at=q['times']['source_at'],
        probability=complete_probabilities,allow_last_known=True)
    if not natural['available']:raise ValueError(natural['reason'])
    details=dict(costs=modeled_costs,scenario=modeled_scenario.to_dict(),natural=natural,
        conditional=conditional,actual_cashflow_scenario=scenario.to_dict(),native_quantity=wire(risk))
    from .bound_finance import result_from_metric
    result=result_from_metric(q,values,dict(eligible=gross['state']=='numeric_current',details=details),at=at,policy=policy)
    capital=F(result['deployed_capital_usd']);expected=F(conditional['expected_profit_usd']);full=F(natural['expected_profit_usd'])
    result['financial_metrics'].update(gross_benchmark_ev_usd=wire(expected),
        gross_benchmark_return_percent=wire(100*expected/capital),rule_adjustment_usd=wire(full-expected),
        conditional_net_ev_usd=wire(expected),conditional_buffered_ev_usd=wire(expected-F(result['buffer_usd'])),
        complete_modeled_minimum_usd=None,buffered_complete_modeled_minimum_usd=None,
        net_upfront_fee_usd='0',reconciliation_expected_settlement_fee_usd='0',
        reconciliation_condition='uncalibrated_NFLWIN_terminal_expectation_sensitivity',conditional_return_percent=wire(100*expected/capital),
        conditional_buffered_return_percent=wire(100*(expected-F(result['buffer_usd']))/capital))
    result['classification']['unknown_outcomes']=['noncompleted']
    result['classification']['adverse_outcomes'].pop('noncompleted',None)
    result['classification']['reason']='Full modeled EV under uncalibrated tie/void assumptions; actual void receipt and complete minimum unknown'
    result['gross_decisive_benchmark']=deepcopy(gross)
    result['size_search']=dict(limitation='Hypothetical USD risk rounded down to cents; no executable allocation')
    result.update(evaluator_version=VERSION,modeled_basis=deepcopy(BASIS),size_status='hypothetical_normalized_risk',
        states={s:dict(profit_usd=r['net_profit_usd'],buffered_profit_usd=None if r['net_profit_usd'] is None else
            wire(F(r['net_profit_usd'])-F(result['buffer_usd']))) for s,r in costs['states'].items()},
        eligibility_reasons=[] if gross['state']=='numeric_current' else ['original_prices_last_known'],
        evaluation_frame=dict(evaluated_at=at.isoformat(),mixed_source_times=True,source_times=deepcopy(q['times']),
            reference_originals=deepcopy(gross['reference_originals']),simultaneous_historical_trade=False))
    result['funding'].update(size_status='hypothetical_normalized_risk',actual_fill_support=False,
        residual_reason='Hypothetical cent-denominated risk; no native legal sizing or observed liquidity established')
    result['benchmark'].update(available=True,revision=gross['reference_revision'],conditioning='decisive_home_or_away_win')
    result['model_versions']=dict(policy_revision=policy.revision,product_model=VERSION,
        fees=VERSION,payouts=VERSION,probability='nflwin-terminal-expectation-sensitivity-2',sizing='hypothetical_usd_risk_cent')
    result['dependency_revision']=digest(dict(original=q['original'],source=q['source'],times=q['times'],
        binding=q['binding'],refs=q['comparison_input_refs'],provenance=q['provenance'],
        source_state=q['state'],event_start=event['start_at'],model=BASIS,
        benchmark=gross['reference_revision'],policy=policy.to_dict()))
    result['probabilities']=complete_probabilities.to_dict()['probabilities']
    result['modeled_expected_void_receipt_usd']=wire(expected_void_per_risk*risk)
    result['modeled_basis']['sensitivity']=sensitivity(
        risk=risk, odds=odds, conditional=expected, buffer=F(result['buffer_usd']))
    result['revision']=digest(result)
    return result


def scenario_ev(*, risk, odds, conditional, buffer, tie, void, refund, fair_value=None):
    """Exact terminal expectation; inputs are scenarios, never settlement floors.

    tie/void are unconditional exclusive masses. conditional is the shared
    decisive net EV at this risk; zero scoped product fees are already included.
    """
    risk, odds, conditional, buffer, tie, void, refund = map(F,
        (risk, odds, conditional, buffer, tie, void, refund))
    if risk <= 0 or odds <= 1 or buffer < 0:
        raise ValueError('invalid_scenario_amount_odds_or_buffer')
    if not (0 <= tie <= 1 and 0 <= void <= 1 and tie + void <= 1 and 0 <= refund <= 1):
        raise ValueError('invalid_scenario_probability_partition')
    if fair_value is None and refund != 1:
        raise ValueError('expected_fair_value_missing')
    fair_value = F(0) if fair_value is None else F(fair_value)
    if not 0 <= fair_value <= 1:raise ValueError('invalid_expected_fair_value')
    void_net = risk * (refund + (1-refund)*odds*fair_value - 1)
    return (1-tie-void)*conditional + tie*risk*(odds/2-1) + void*void_net - buffer


def sensitivity(*, risk, odds, conditional, buffer):
    """Multiaffine corner extrema over the explicitly hypothetical box.

    This is an EV range, not a distribution, confidence interval or payoff bound.
    Refund receipt lies between zero and face, so the no-refund fair-value
    endpoints also span every refund mixture in the chosen box.
    """
    rows=[]
    for tie in (F(0),F('0.025')):
        for void in (F(0),F('0.01')):
            for fair in (F(0),F(1)):
                value=scenario_ev(risk=risk,odds=odds,conditional=conditional,buffer=buffer,
                    tie=tie,void=void,refund=0,fair_value=fair)
                rows.append(dict(tie_probability=wire(tie),void_probability=wire(void),
                    refund_given_void='0',expected_fair_value_given_nonrefund=wire(fair),
                    buffered_ev_usd=wire(value)))
    low=min(F(x['buffered_ev_usd']) for x in rows);high=max(F(x['buffered_ev_usd']) for x in rows)
    # At the displayed t/v, solve for total expected void receipt per dollar face.
    t=F('0.005');v=F('0.001')
    threshold=(buffer-(1-t-v)*conditional-t*risk*(odds/2-1)+v*risk)/(v*risk*odds)
    # Also solve maximum void probability before sign changes, at zero void receipt.
    intercept=(1-t)*conditional+t*risk*(odds/2-1)-buffer
    slope=-risk-conditional
    void_threshold=None if slope==0 else -intercept/slope
    return dict(kind='hypothetical_parameter_sensitivity',calibrated_estimate_available=False,
        buffered_ev_low_usd=wire(low),buffered_ev_high_usd=wire(high),sign_changes=low<0<high,
        corners=rows,break_even_expected_void_receipt_per_face=wire(threshold),
        break_even_receipt_feasible=0<=threshold<=1,
        break_even_void_probability_zero_receipt=None if void_threshold is None else wire(void_threshold),
        break_even_void_feasible=void_threshold is not None and 0<=void_threshold<=1-t,
        threshold_condition='Tie 0.5%; receipt threshold fixes void at 0.1%. Void threshold fixes expected void receipt at zero. Both include one selected buffer; thresholds outside feasible intervals are not attainable.',
        formula='EV = (1-t-v)*conditional + t*A*(d/2-1) + v*A*(r+(1-r)*d*f-1) - buffer; f is expected fair value conditional on non-refund void, r is refund share within void.')
