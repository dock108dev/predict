"""Bridge fully bound shared cashflow/cost results; no prior or dated recipe.

The generic typed owners support more cells than the dated NFL recipe model.
This adapter publishes only their actually computed values under the funded wire.
"""
from fractions import Fraction as F
from copy import deepcopy

from .current_dependencies import digest, references, eligibility
from .net_costs import wire
from .financial_metrics import classification, funding, VERSION


def single(q, profiles, *, at, event, group, policy):
    """Return None unless the existing strict shared owners qualify this input."""
    values=references(q,profiles)
    required=('identity','fee','payout','quantity','buffer','probability')
    if any(k not in values for k in required) or eligibility(q,profiles,at,kinds=required):
        return None
    from .current_metrics import _calculate_quote
    outcome=next((o for o in group['outcomes'] if o['id']==q['binding']['selection']['outcome_id']),None)
    metric,_=_calculate_quote(q,profiles,at,event=event,group=group,outcome=outcome,estimate_policy=policy)
    return result_from_metric(q,values,metric,at=at,policy=policy)


def result_from_metric(q,values,metric,*,at,policy):
    """Shared funded transport for validated cashflow/cost/probability results."""
    natural=metric.get('details',{}).get('natural',{})
    if not natural.get('available'):
        return None
    details=metric['details'];costs=details['costs']
    capital=F(costs['capital']['deployed_capital_usd']);haircut=capital*F(policy.buffer_rate)
    expected=F(natural['expected_profit_usd'])
    complete=natural['details']['partition_class']=='complete_terminal_state_EV'
    states={s:dict(profit_usd=r['net_profit_usd']) for s,r in costs['states'].items()}
    minimum=None if not details['scenario']['partition_complete'] or any(r['profit_usd'] is None for r in states.values()) else min(F(r['profit_usd']) for r in states.values())
    result=dict(version='predict-funded-single-2',evaluator_version='predict-bound-finance-1',
        model_available=True,ranking_eligible=bool(metric['eligible']),reasons=[],eligibility_reasons=[],
        conditioning='modeled_complete' if complete else 'modeled_conditional',
        condition=None if complete else natural['conditioning'],quote_id=q['id'],quote_revision=q['revision'],
        native_quantity=details['native_quantity'],deployed_capital_usd=wire(capital),unused_cash_usd=wire(F(policy.capital_ceiling_usd)-capital),
        buffer_usd=wire(haircut),buffered_profit_usd=wire(expected-haircut),
        buffered_return_percent=wire(100*(expected-haircut)/capital),
        size_status='modeled_size',policy_revision=policy.revision,evaluated_at=at.isoformat(),
        size_search=dict(limitation='shared maximum funded legal grid; hypothetical one-order allocation'),
        financial_metrics=dict(version=VERSION,gross_benchmark_ev_usd=None,net_modeled_ev_usd=wire(expected) if complete else None,
            buffered_ev_usd=wire(expected-haircut) if complete else None,
            conditional_net_ev_usd=None if complete else wire(expected),conditional_buffered_ev_usd=None if complete else wire(expected-haircut),
            net_modeled_return_percent=wire(100*expected/capital) if complete else None,
            buffered_return_percent=wire(100*(expected-haircut)/capital) if complete else None,
            decisive_opposing_margin_usd=None,buffered_decisive_opposing_margin_usd=None,
            complete_modeled_minimum_usd=None if minimum is None else wire(minimum),
            buffered_complete_modeled_minimum_usd=None if minimum is None else wire(minimum-haircut),
            buffer_usd=wire(haircut),percentage_denominator='actual_deployed_capital',actual_charges=None),
        benchmark=dict(venue=policy.benchmark_venue,method=policy.benchmark_method,
            available=values.get('reference') is not None,revision=q['comparison_input_refs']['refs'].get('reference'),
            conditioning=natural['conditioning'],reason=None),
        model_versions=dict(financial_metrics=VERSION,policy_revision=policy.revision,
            profiles=deepcopy(q['comparison_input_refs']['refs'])),
        classification=classification('single',expected if complete else None,expected-haircut,None,minimum,states,
            eligible=bool(metric['eligible']),condition=None if complete else natural['conditioning']),
        bound_financial_inputs=True)
    rule=costs['rule']['rule'];unit=rule['unit']
    funding(result,policy,[dict(native_quantity=result['native_quantity'],native_unit=unit,
        acquisition_usd=costs['acquisition_usd'],upfront_fee_usd=costs['net_entry_fee_usd'],
        independent_funding_usd=wire(capital-F(costs['acquisition_usd'])-F(costs['net_entry_fee_usd'])))])
    result['dependency_revision']=digest(dict(refs=q['comparison_input_refs'],source=q['source'],times=q['times'],
        original=q['original'],policy=policy.to_dict(),calculation=natural['dependency_revisions']))
    result['bound_details']=deepcopy(details)
    result['revision']=digest(result)
    return result


def gross_quote(result, q, profiles, *, at, event, group, policy, benchmark=None):
    """Independent gross decisive expectation per $1 normal claim, never net EV.

    No executable quantity, fee or exceptional-probability claim is introduced.
    Expired original prices remain explicitly last known.
    """
    if result.get('financial_metrics',{}).get('gross_benchmark_ev_usd') is not None:
        return result
    metric=dict(available=False,value=None,return_percent=None,reason=None,
        basis='one_dollar_normal_claim',conditioning='decisive_home_or_away_win',
        fee_basis='gross_excludes_fees',exceptional_probability=None,executable_size=False,
        source_times=deepcopy(q['times']))
    try:
        # Retained modeled winners already carry a validated typed reference.
        # Keep its identity/expiry checks below; current aggregate pairing is
        # needed only when that reference is absent.
        if (q['source']['provider']=='the_odds_api' and getattr(policy,'benchmark_venue','pinnacle')=='pinnacle'
                and not q.get('comparison_input_refs',{}).get('refs',{}).get('reference')):
            return aggregate_gross(result,q,profiles,at=at,event=event,group=group,metric=metric)
        from .domain import CanonicalSelection
        from .benchmark import resolve
        from .current_metrics import calculation_instant
        calculation_instant((q,),profiles,at)
        values=references(q,profiles);identity=values.get('identity',{}).get('payload',{})
        selected=CanonicalSelection.from_dict(identity['selection'])
        roles={p['role']:p['id'] for p in event['participants']}
        from .estimated_content import native_contract
        contract=native_contract(q,group)
        if group['market']=='winner':
            home=q['binding']['selection']['participant']==roles['home']
            predicate=q['binding']['selection']['predicate']
            expected=('gt' if home else 'lt') if predicate=='win' else ('le' if home else 'ge') if predicate=='not_win' else None
            if (contract['scope']['overtime']!=selected.scope.overtime or contract['scope']['period']!=selected.scope.period or
                selected.predicate.operator!=expected or group['market']!='winner' or group['period']!='full_game' or
                identity.get('current_selection_binding')!=q['binding']['selection'] or not q['binding']['verified'] or
                selected.scope.overtime!='included' or selected.predicate.domain!='home_margin' or
                selected.predicate.threshold.value!=0 or selected.predicate.operator not in ('gt','lt','ge','le') or
                selected.event.home_id!=roles['home'] or selected.event.away_id!=roles['away'] or
                selected.event.league!=event['league'] or selected.participant_id!=q['binding']['selection']['participant'] or
                list(selected.native.key)!=[q['venue'],*[q['source'][k] for k in ('native_event_id','native_market_id','native_outcome_id','native_side')]]):
                raise ValueError('gross_decisive_winner_identity_unsupported')
        else:
            from .same_outcome import quote_identity
            facts=contract.get('same_outcome',{})
            if (group['market'] not in ('spread','total') or group['period']!='full_game' or
                    identity.get('current_selection_binding')!=q['binding']['selection'] or not q['binding']['verified'] or
                    selected.predicate.to_dict()!=facts.get('predicate') or
                    selected.scope.overtime!=contract['scope']['overtime'] or
                    not quote_identity(q,group,event)['supported'] or
                    list(selected.native.key)!=[q['venue'],*[q['source'][k] for k in ('native_event_id','native_market_id','native_outcome_id','native_side')]]):
                raise ValueError('gross_exact_native_score_identity_unsupported')
            if 'reference' not in values:
                raise ValueError(q['comparison_input_status']['reference']['reason'])
        metric['applicability_expiry']={k:v.get('expires_at') for k,v in values.items() if k in ('identity','reference')}
        supplied=(benchmark if group['market']=='winner' else None) or values.get('reference',{}).get('payload')
        weight,reference=resolve(supplied,selected,policy,at,allow_last_known=True)
        probability=weight if selected.predicate.operator in ('gt','ge') else 1-weight
        metric.update(conditioning='score_unequal_to_exact_threshold',selected_predicate=selected.predicate.to_dict(),
            selected_equality=selected.equality.to_dict(),reference_applicability=deepcopy(q.get('comparison_input_status',{}).get('reference')),
            meaning='Exact decisive reference benchmark. Equality, pushes and exceptional settlement excluded; not full net EV or covered arbitrage.')
        original=q['original']
        if original.get('payout_units')!='USD' or F(original['payout'])!=1:
            raise ValueError('gross_one_dollar_normal_face_required')
        value=F(original['value']);units=original['units']
        cost=1/value if units=='decimal_odds' else value/100 if units=='cents_per_contract' else value if units=='usd_per_contract' else None
        if cost is None or cost<=0:raise ValueError('gross_normal_price_unsupported')
        from .estimated_ev import temporal
        status=temporal(q,profiles,at,event)[0]
        current=status=='current' and reference.clock_status(at)=='current' and q['state'] in ('available','budget_delayed')
        metric.update(available=True,value=wire(probability-cost),return_percent=wire(100*(probability-cost)/cost),
            selected_decisive_probability=wire(probability),acquisition_usd_per_normal_claim=wire(cost),
            state='numeric_current' if current else 'numeric_last_known',reference_revision=reference.revision,
            reference_originals=[r.to_dict() for r in reference.outcomes],originals_simultaneously_executable=False)
    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
        metric['reason']=str(exc)
    result['gross_decisive_benchmark']=metric
    result['revision']=digest(dict(financial_revision=result['revision'],gross_decisive_benchmark=metric))
    return result


def pairs(event, profiles, policy, *, existing=()):
    """Publish the existing exact shared portfolio owner across supported cells.

    Base costs already include mandatory funding and fees. Apply the selected
    scalar haircut once; the legacy adverse-price sensitivity stays separate.
    """
    from app.dashboard.current_contract import quotes_of
    quotes={q['id']:q for g in event['groups'] for o in g['outcomes'] for q in quotes_of(o)}
    seen={frozenset(l['quote_id'] for l in p['legs']) for p in existing};results=[]
    for group in event['groups']:
        for pair in group.get('comparison_pairs',[]):
            ids=frozenset(l['quote_id'] for l in pair['legs'])
            if ids in seen:continue
            raw=pair['details'];base=raw['base'];costs=raw['cost_summaries']['base']
            if not raw['available'] or any(c['capital'] is None for c in costs):continue
            capital=sum((F(c['capital']['deployed_capital_usd']) for c in costs),F(0))
            if not 0<capital<=F(policy.capital_ceiling_usd):continue
            haircut=capital*F(policy.buffer_rate);states={s:dict(profit_usd=v) for s,v in base['full']['states'].items()}
            complete=bool(base['partition_complete'] and all(r['profit_usd'] is not None for r in states.values()))
            minimum=min(F(r['profit_usd']) for r in states.values()) if complete else None
            decisive=None
            if group['market']=='winner':
                names=[s['state_id'] for s in raw['state_descriptors'] if s['terminal']=='completed' and
                    s['score_domain']=='home_margin' and s['score_range'] and (
                        s['score_range']['upper'] is not None and s['score_range']['upper']<0 or
                        s['score_range']['lower'] is not None and s['score_range']['lower']>0)]
                if names and all(states[n]['profit_usd'] is not None for n in names):
                    decisive=min(F(states[n]['profit_usd']) for n in names)
            known=[F(r['profit_usd']) for r in states.values() if r['profit_usd'] is not None]
            conditional=min(known) if known else None
            legs=[];funded=[]
            for leg,cost in zip(pair['legs'],costs):
                q=quotes[leg['quote_id']];unit=references(q,profiles)['fee']['payload']['rule']['unit']
                value=dict(quote_id=q['id'],quote_revision=q['revision'],venue=q['venue'],native_key=leg['native_key'],
                    native_quantity=leg['quantity'],native_unit=unit,acquisition_usd=cost['acquisition_usd'],
                    net_upfront_fee_usd=cost['net_entry_fee_usd'],group_id=group['id'])
                legs.append(value)
                funded.append(dict(value,upfront_fee_usd=cost['net_entry_fee_usd'],deployed_capital_usd=cost['capital']['deployed_capital_usd'],
                    independent_funding_usd=wire(F(cost['capital']['deployed_capital_usd'])-F(cost['acquisition_usd'])-F(cost['net_entry_fee_usd']))))
            metrics=dict(version=VERSION,gross_benchmark_ev_usd=None,net_modeled_ev_usd=None,buffered_ev_usd=None,
                conditional_net_ev_usd=None,conditional_buffered_ev_usd=None,
                decisive_opposing_margin_usd=None if decisive is None else wire(decisive),
                buffered_decisive_opposing_margin_usd=None if decisive is None else wire(decisive-haircut),
                complete_modeled_minimum_usd=None if minimum is None else wire(minimum),
                buffered_complete_modeled_minimum_usd=None if minimum is None else wire(minimum-haircut),
                conditional_known_state_minimum_usd=None if conditional is None else wire(conditional),
                buffered_conditional_known_state_minimum_usd=None if conditional is None else wire(conditional-haircut),
                buffer_usd=wire(haircut),percentage_denominator='actual_deployed_capital',actual_charges=None)
            result=dict(id='bound-pair:'+digest(sorted(ids)),version='predict-funded-pair-2',evaluator_version='predict-bound-finance-1',
                model_available=True,ranking_eligible=True,reasons=[],eligibility_reasons=[],legs=legs,
                policy_revision=policy.revision,buffered_profit_usd=None,buffered_return_percent=None,
                benchmark=dict(venue=policy.benchmark_venue,method=policy.benchmark_method,available=False,revision=None,reason='probability_inputs_missing'),
                deployed_capital_usd=wire(capital),buffer_usd=wire(haircut),size_status='supported_size',
                financial_metrics=metrics,bound_financial_inputs=True,
                conditioning='modeled_complete' if complete else 'modeled_conditional',
                condition=None if complete else 'listed_known_joint_states_only',
                classification=classification('pair',None,None,None if decisive is None else decisive-haircut,
                    None if minimum is None else minimum-haircut,states,eligible=True,
                    condition=None if complete else 'listed_known_joint_states_only'),
                model_versions=dict(policy_revision=policy.revision,financial_metrics=VERSION,
                    shared_dependencies=raw['dependency_revisions']),
                search=dict(global_optimality_proven=False,limitation='shared bounded observed allocation search',
                    truncated=group.get('comparison_search',{}).get('truncated',False)))
            funding(result,policy,funded)
            result['dependency_revision']=digest(dict(dependencies=raw['dependency_revisions'],policy=policy.to_dict()))
            result['bound_details']=deepcopy(raw);result['revision']=digest(result)
            results.append(result);seen.add(ids)
    return results


def aggregate_gross(result,q,profiles,*,at,event,group,metric):
    """Use the shared exact benchmark owner for provider-defined two-way bets.

    This compares the provider's identical occurrence/period/line/outcome only.
    It does not attest cross-venue exceptional settlement or a net probability.
    """
    try:
        from app.collection.current_benchmark import calculate,validate_reference
        from app.collection.current_comparison_inputs import PRODUCER_VERSION
        from app.dashboard.current_contract import price
        from .current_dependencies import instant
        ref=q.get('sharp_reference')
        if not ref:raise ValueError('exact_pinnacle_opposition_unavailable')
        validate_reference(ref,q['binding']['selection'])
        values=references(q,profiles)
        payload=values.get('reference',{}).get('payload',{})
        # The ordinary producer preserves both native originals. A game-level
        # winner benchmark cannot replace a spread/total or another line.
        if payload.get('version')==PRODUCER_VERSION:
            originals=payload.get('outcomes',[])
            if (len(originals)!=2 or payload['current_selection_binding']!=q['binding']['selection'] or
                payload['receipt_sha256']!=ref['sha256'] or payload['original_odds']!=ref['odds'] or
                any(r['source']['native_event_id']!=q['source']['native_event_id'] for r in originals)):
                raise ValueError('exact_reference_originals_unavailable')
        else:
            # Combined winner attachment has its own typed original frame;
            # retain the independently bound ordinary quote reference as well.
            if group['market']!='winner' or payload.get('version')!='comparison-two-way-benchmark-1':
                raise ValueError('exact_reference_originals_unavailable')
            originals=payload['outcomes']
            if (payload.get('receipt_sha256')!=ref['sha256'] or len(originals)!=2 or
                sorted((x['decimal_odds'],x.get('market_at') or x.get('book_at')) for x in originals)!=sorted(zip(ref['odds'],ref['source_at'])) or
                any(x['selection']['native']['event_id']!=q['source']['native_event_id'] for x in originals)):
                raise ValueError('exact_reference_originals_unavailable')
        value=calculate(q,at,allow_last_known=True)
        if value.get('value') is None:raise ValueError(value.get('reason') or 'gross_reference_unavailable')
        probability=F(int(value['basis']['probability']['numerator']),int(value['basis']['probability']['denominator']))
        cost=price(q)
        current=(q['state'] in ('available','budget_delayed') and all(t is not None and 0<=(at-instant(t)).total_seconds()<=1800 for t in
            [q['times']['source_at'],*ref['source_at']]) and at<instant(event['start_at']))
        metric.update(available=True,value=wire(probability-cost),return_percent=wire(F(int(value['exact']['numerator']),int(value['exact']['denominator']))),
            selected_decisive_probability=wire(probability),acquisition_usd_per_normal_claim=wire(cost),
            state='numeric_current' if current else 'numeric_last_known',reference_revision=digest(ref),
            reference_originals=deepcopy(originals),reference_binding=deepcopy(ref),
            conditioning='provider_defined_decisive_win_loss',originals_simultaneously_executable=False,
            meaning='Exact provider event, full-game market, outcome and line; proportional no-vig benchmark before fees. Ties, pushes and exceptional settlement excluded. Not net EV or covered arbitrage.',
            settlement_equivalence='not_established_by_aggregate_market_identity')
    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
        metric['reason']=str(exc)
    result['gross_decisive_benchmark']=metric
    result['revision']=digest(dict(financial_revision=result['revision'],gross_decisive_benchmark=metric))
    return result


def age_benchmarks(result,q,event,at,*,reasons=(),source_assessment=None):
    """Age only inputs required by gross/conditional metrics, not net EV models."""
    from .source_clock import assess
    from .current_dependencies import instant,link_reasons
    from .event_eligibility import assess as event_assess,quote_event
    gross=result.get('gross_decisive_benchmark',{})
    if not gross.get('available'):return
    source_assessment=source_assessment or assess(q,at)
    why=[*reasons,*source_assessment['reasons'],*link_reasons(q,at)]
    gross['source_currentness']=source_assessment
    if q.get('state',q.get('source_state')) not in ('available','budget_delayed'):why.append('source_unavailable')
    er=event_assess(quote_event(q,event),at.isoformat())['reason']
    if er:why.append(er)
    if at>=instant(event['start_at']):why.append('pregame_ended')
    refs=gross.get('reference_originals',[])
    if len(refs)!=2:why.append('reference_pair_missing')
    for r in refs:
        clock=r.get('source_at') or r.get('market_at') or r.get('book_at')
        receipt=r.get('received_at')
        if clock is None or receipt is None:why.append('reference_clock_unknown');continue
        if instant(clock)>at or instant(receipt)>at or instant(clock)>instant(receipt):why.append('reference_clock_future')
        elif (at-instant(clock)).total_seconds()>1800:why.append('reference_expired')
    for kind,expiry in gross.get('applicability_expiry',{}).items():
        if expiry is not None and at>=instant(expiry):why.append(kind+'_profile_expired')
    gross['currentness_reasons']=sorted(set(why))
    gross['state']='numeric_last_known' if why else 'numeric_current'
    conditional=result.get('conditional_trade_benchmark',{})
    if conditional.get('available'):
        if not instant(conditional['evidence']['reviewed_at'])<=at<instant(conditional['evidence']['review_before']):
            why.append('conditional_fee_review_expired_or_not_effective')
        conditional['currentness_reasons']=sorted(set(why))
        conditional['state']='numeric_last_known' if why else 'numeric_current'
