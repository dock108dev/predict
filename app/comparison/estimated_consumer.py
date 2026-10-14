"""Versioned fixed-allocation consumer without sizing or probability weighting.

Entry charges are independent of settlement cells and legal execution grids.
Fee/payout profiles use shared storage/expansion and scalar-input interfaces.
Returned cashflows are modeled future values, not actual facts."""
from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction
import json

from app.fees.engine import Registry, calculate, generic_fee
from .costs import CostRule, UnitSpec
from .source_inputs import observation
from .current_dependencies import digest, references, instant, encoded
from .estimated_content import STATES, describe, native_contract
from .estimated_templates import TemplateProvider, payout_provider
from .net_costs import wire
from .payouts import PayoutProfile, CompletionContext, bind_profile
from .domain import CanonicalSelection
from .shared_templates import ProfilePool, resolve

VERSION = 'predict-estimate-components-1'


class AllocationInputs:
    """One synchronous evaluation's exact inputs, discarded with its probes.

    No result, policy or allocation is cached. Callers own the captured quote and
    registry for this finite calculation; nothing survives publication or await.
    Temporal applicability is evaluated at the same explicit consumer instant.
    """
    def __init__(self, q, profiles, at):
        self.quote=q;self.profiles=profiles;self.at=at
        self.content=describe(q,profiles,at=at)
        self.values=references(q,profiles)
        self.payout=None


def _unit(q, fee):
    recipe=fee.get('recipe',{})
    selected=recipe.get('selected')
    if selected:
        return CostRule.from_dict(selected['value']['fee_payload']['rule']).unit
    refdata=recipe.get('metadata',{}).get('selected_reference_data',{})
    if refdata.get('present'):
        if refdata.get('instrument_id')!=q['source']['native_outcome_id'] or refdata.get('market_id')!=q['source']['native_market_id']:
            raise ValueError('estimate_reference_units_native_conflict')
        raw=refdata['values']
        return UnitSpec('fixed_point_contracts','1',raw.get('fractionalQtyScale','1'),raw['priceScale'])
    profile=fee.get('original_profile')
    rule=(profile or {}).get('payload',{}).get('rule')
    if rule and fee['original_status'].get('status')=='available_and_bound':
        return CostRule.from_dict(rule).unit
    if q['original']['units']=='decimal_odds':return UnitSpec('stake_usd')
    if q['original']['units'] in ('usd_per_contract','cents_per_contract'):
        return UnitSpec('novig_v3_cent_contracts','0.01') if q['venue']=='novig' else UnitSpec('dollar_face_contracts','1')
    raise ValueError('estimate_native_units_unknown')


def _selected_fee(q, fee, at):
    selected=fee['recipe']['selected']
    payload=selected['value'].get('fee_payload') if selected else None
    if payload is None and fee['original_profile'] is not None and fee['original_status']['status']=='available_and_bound':
        payload=fee['original_profile']['payload']
    if not payload or not isinstance(payload.get('rule'),dict):return None
    rule=CostRule.from_dict(payload['rule'])
    if rule.account_ref is not None or rule.venue!=q['venue'] or rule.terms is None or rule.terms.role!='taker':
        raise ValueError('estimate_selected_fee_authority_unresolved')
    if rule.event_id not in (None,q['source']['native_event_id']) or rule.market_id not in (None,q['source']['native_market_id']):
        raise ValueError('estimate_selected_fee_native_conflict')
    if rule.effective_from is not None and at<instant(rule.effective_from):
        raise ValueError('estimate_selected_fee_not_effective')
    if any(end is not None and at>=instant(end) for end in (rule.effective_to,rule.expires_at)):
        raise ValueError('estimate_selected_fee_expired')
    if rule.source_kind=='research_proposal':raise ValueError('estimate_selected_fee_terms_unresolved')
    if rule.terms.blockers():raise ValueError('estimate_selected_fee_terms_unresolved')
    return rule,deepcopy(payload)


def _entry(q, fee, unit, fills, at):
    entry,refund,audit,chosen=_entry_base(q,fee,unit,fills,at)
    flat=(chosen[1] if chosen else {}).get('flat_entry_fee_usd')
    if flat is not None:
        if chosen[0].source_kind!='controlled_scenario' or Fraction(flat)<0:
            raise ValueError('estimate_authored_flat_entry_fee_required')
        entry=wire(Fraction(entry)+Fraction(flat));audit['authored_flat_entry_fee_usd']=flat
    return entry,refund,audit,chosen


def _entry_base(q, fee, unit, fills, at):
    chosen=_selected_fee(q,fee,at)
    template=fee['template'];venue=q['venue'];meta=fee['recipe']['metadata'];t=template['fee']
    source=q['source'];stamp=at.isoformat()
    rule,payload=chosen if chosen else (None,None)
    if rule and rule.terms.basis=='net_gain':return '0','0',dict(rule=rule.to_dict(),engine='generic-fees-1'),chosen
    if chosen and unit.unit=='stake_usd':
        if rule.source_kind!='controlled_scenario' or rule.terms.basis!='notional':
            raise ValueError('estimate_stake_entry_terms_adapter_unresolved')
        # generic_fee admits probability-price contract fills. This explicit
        # authored notional bridge preserves each USD stake (p=.5, face=2x
        # stake); it makes no native contract/grid/execution assertion.
        normalized=[dict(f,price='0.5',quantity=wire(2*Fraction(f['quantity']))) for f in fills]
        result=generic_fee(normalized,rule.terms.generic_policy())
        return result['entry_fee'],'0',dict(rule=rule.to_dict(),engine='generic-fees-1',
            allocation_adapter='authored_USD_stake_notional; 0.5_times_twice_stake'),chosen
    if not chosen and venue=='novig' and unit.unit=='stake_usd':
        return '0','0',dict(engine='fees-1',model='aggregate_direct_site_WHEN_LIVE_pregame_zero',native_api_applicability=False),None
    if chosen:
        if not payload.get('engine_context') or not payload.get('engine_registry'):
            if rule.source_kind=='controlled_scenario':
                result=generic_fee(fills,rule.terms.generic_policy())
                return result['entry_fee'],'0',dict(rule=rule.to_dict(),engine='generic-fees-1'),chosen
            raise ValueError('estimate_selected_entry_engine_unbound')
        context=deepcopy(payload['engine_context']);registry=Registry(payload['engine_registry'])
        context.update(venue=venue,product=rule.product,channel=rule.channel)
    elif venue=='prophetx':return '0','0',dict(engine='generic-fees-1',commission_basis='positive_net_gains_per_market'),None
    else:
        schedule=dict(venue=venue,product=t['product'],version=template['version'],
            effective_from=t.get('effective_from'),effective_to=None,coefficient=t['coefficient'])
        if venue=='polymarket_us':schedule['maker_coefficient']=t['maker_coefficient']
        if venue=='novig':schedule['api_regime']='v3'
        registry=Registry(dict(schema=1,schedules=[schedule]))
        context=dict(venue=venue,product=t['product'],schedule_version=template['version'],environment='hypothetical')
        if venue=='kalshi':
            series=meta.get('series_id','model:NFL-game')
            context.update(series_id=series,event_id=source['native_event_id'],balance_precision=meta.get('balance_precision','0.0001'),
                kalshi_metadata=deepcopy(meta.get('kalshi_metadata')) or dict(source='model:'+template['version'],
                series_id=series,event_id=source['native_event_id'],event_history_complete=True,
                series_changes=[dict(scheduled_ts=template['model_effective_from'],fee_type='quadratic',fee_multiplier='1')],event_changes=[]))
        elif venue=='novig':
            if 'market_fee' in meta and meta.get('api_regime')!='v3':raise ValueError('estimate_novig_fee_regime_conflict')
            context.update(api_regime='v3',market_fee=deepcopy(meta.get('market_fee')) or
                dict(coefficient=t['coefficient'],makerCredit=t['maker_credit'],charged=t['charged']))
    context.update(market_id=source['native_market_id'],event_id=source['native_event_id'],trade_time=stamp,calculation_time=stamp,
        fills=deepcopy(fills),complete_order_history=True,outcomes={})
    context.pop('refund_outcomes',None)
    if venue=='polymarket_us':
        if unit.unit=='fixed_point_contracts':
            context.update(public_binding_version='public-contract-bindings-1',quantity_scale=unit.quantity_scale,
                quantity_scale_evidence=dict(market_id=source['native_market_id'],source='explicit_selected_unit'))
        else:
            # Decimal scenario alignment is declared, never a native execution
            # grid attestation. Selected retail metadata overrides this scenario.
            grid=meta.get('selected_public_retail_data',{})
            context.update(public_binding_version='comparison-public-retail-1',public_retail_quantity=dict(
                market_id=source['native_market_id'],authority='public_orders_minimumTradeQty_alignment',
                response_sha256=q['provenance']['sha256'],minimum_contracts=grid.get('minimumTradeQty','0.000001'),
                increment_contracts=grid.get('minimumTradeQty','0.000001'),price_tick_usd=grid.get('orderPriceMinTickSize','0.000001')))
    if chosen:
        from .net_costs import _venue_entry
        from .costs import CostRequest, FillInputs
        request=CostRequest(venue,rule.product,rule.channel,stamp,stamp,market_id=source['native_market_id'],
            event_id=source['native_event_id'],series_id=context.get('series_id'),pinned_version=rule.version,allow_controlled_scenario=rule.source_kind=='controlled_scenario')
        order_ids=tuple(dict.fromkeys(f['order_id'] for f in fills))
        partitions=FillInputs('authored_fills',True,len(fills),len(fills),order_ids)
        _,fee_amount,refunded,engine_ref=_venue_entry(rule,request,fills,partitions,context,registry)
        return wire(fee_amount),wire(refunded),dict(rule=rule.to_dict(),engine_context={k:v for k,v in context.items() if k!='fills'},
            engine_registry=registry.data,engine=engine_ref),chosen
    audit=calculate(context,registry)
    if audit['unsupported']:raise ValueError('estimate_entry_engine_refused')
    refunds=sum((Fraction(c['amount']) for c in audit['credits'] if c['kind']=='order_rounding_refund' and c.get('conditional') is False),Fraction(0))
    details=dict(audit,context={k:v for k,v in audit['context'].items() if k!='fills'},
        trace_sha256=digest(audit['trace']),trace_reopening='recalculate from exact dependency fills and retained engine context/registry')
    details.pop('trace')
    return audit['entry_fees'],wire(refunds),details,chosen


def _payouts(q, profiles, payout, quantity, unit, acquisition, at, inputs=None):
    recipe=payout['recipe'];original=payout['original_profile']
    identity=(inputs.values if inputs is not None else references(q,profiles)).get('identity',{}).get('payload',{})
    bound=original is not None and payout['original_status']['status']=='available_and_bound' and identity.get('completion_context') is not None
    try:values,basis,details=_template_payouts(q,payout,quantity,unit,acquisition)
    except ValueError:
        if not bound:raise
        values=dict.fromkeys(STATES);basis=dict.fromkeys(STATES,'provisional_assumption');details={}
    if bound:
        cached=None if inputs is None else inputs.payout
        if cached is None:
            selection=CanonicalSelection.from_dict(identity['selection'])
            p=PayoutProfile.from_dict(original['payload'])
            leg=bind_profile(selection,p,at=at,rule_revision=identity['rule_revision'],context=CompletionContext.from_dict(identity['completion_context']))
            contract=native_contract(q,dict(period='full_game'))
            if q.get('native_contract') is None:
                contract['scope']['overtime']=selection.scope.overtime
                contract['id']='native-contract:'+digest({k:v for k,v in contract.items() if k!='id'})
            provider=payout_provider(contract,leg,at=at.isoformat())
            if inputs is not None:inputs.payout=(p,provider)
        else:p,provider=cached
        parts={'home_win':'above','away_win':'below','tie':'equal','terminal_noncompletion':'noncompleted'}
        multiplier=quantity if unit.unit=='stake_usd' else Fraction(unit.dollar_face(wire(quantity)))
        for state,part in parts.items():
            cell=provider.resolve(provider.scope_id(part));basis[state]=cell.basis
            if cell.modeled_value is not None:
                values[state]=wire(Fraction(cell.modeled_value)*multiplier)
            else:basis[state]='provisional_assumption'
        details.update(selected_profile=p.to_dict(),refund_fees=p.refund_fees,
            unresolved_actual_cells=[part for part in parts.values() if provider.resolve(provider.scope_id(part)).modeled_value is None])
        if p.noncompleted.value is not None:details.update(proxy=None,terminal_range_usd=[values['terminal_noncompletion']]*2)
        return values,basis,details
    selected=recipe.get('selected')
    # A selected payout that could not bind retains its unknown/conflict; it
    # cannot borrow a generic branch merely because fee arithmetic works.
    if selected:raise ValueError('estimate_selected_payout_binding_unresolved')
    return values,basis,details


def _template_payouts(q,payout,quantity,unit,acquisition):
    recipe=payout['recipe'];values={};details={}
    pred=q['binding']['selection'];venue=q['venue'];native=q['source']['native_side'].lower()
    if pred['predicate']=='draw':raise ValueError('estimate_draw_payout_template_unresolved')
    home=pred['participant']==recipe['home_id']
    win_state='home_win' if home else 'away_win';other='away_win' if home else 'home_win'
    if unit.unit=='stake_usd':win=quantity*Fraction(q['original']['value'])
    else:win=Fraction(unit.dollar_face(wire(quantity)))
    values.update({win_state:wire(win),other:'0'})
    if pred['predicate']=='not_win':values[win_state],values[other]=values[other],values[win_state]
    basis={s:'provisional_assumption' for s in STATES}
    meta=recipe['metadata'];tie=acquisition
    if venue in ('kalshi','polymarket_us'):
        listed=meta.get('tie_strike_listed' if venue=='kalshi' else 'tie_outcome_listed')
        if listed is not None and type(listed) is not bool:raise ValueError('estimate_tie_branch_invalid')
        if venue=='polymarket_us' and listed:raise ValueError('estimate_three_way_payout_unresolved')
        tie=win/2
        if venue=='kalshi' and listed:tie=win if pred['predicate']=='not_win' or native=='no' else Fraction(0)
    values['tie']=wire(tie)
    mark=meta.get('fair_price')
    if mark is not None:
        mark=Fraction(mark)
        if not 0<=mark<=1:raise ValueError('estimate_fair_price_invalid')
    values['terminal_noncompletion']=wire(acquisition if mark is None else win*mark)
    details.update(refund_fees=payout['template']['fee']['fee_refund'],proxy='entry_mark_neutral' if mark is None else 'supplied_fair_mark',
        terminal_scope='all terminal exceptions after selected normal grading; cancellation/abandonment are aliases, not extra states',
        terminal_range_usd=['0',wire(win)],collateral_refund_states=['tie'] if venue in ('novig','prophetx') else [],
        branch='tie_strike_listed' if meta.get('tie_strike_listed') else 'no_tie_strike_assumption' if venue=='kalshi' else payout['template']['payout']['tie'])
    return values,basis,details


def consume(q, profiles, *, at, native_quantity, fills=None, extra_funding=(), hold_returns_usd=None, state_cashflows=None,
            settlement_charge_already_withheld=False, stake_fills=None, retain_profiles=True, settlement_metadata=False, _inputs=None):
    """Recalculate each allocation. Quantity is in the returned UnitSpec units.

    Supplied fills use existing-engine normalized decimal prices / quantities
    (Novig uses integer cent-face contracts). Omitted fills mean one disclosed
    hypothetical order. State overrides are explicitly modeled receipts in USD,
    with exactly the four disjoint states; they do not attest actual settlement.
    """
    from .calculation_control import checkpoint
    checkpoint()
    if _inputs is not None and (_inputs.quote is not q or _inputs.profiles is not profiles or _inputs.at!=at):
        raise ValueError('estimate_allocation_input_context_conflict')
    content=describe(q,profiles,at=at) if _inputs is None else _inputs.content
    fee=content['fee'];payout=content['payout']
    if type(settlement_charge_already_withheld) is not bool:raise ValueError('estimate_withheld_attachment_required')
    reasons={k:list(v['reasons']) for k,v in content.items()};quantity=Fraction(native_quantity)
    if quantity<=0:raise ValueError('estimate_positive_quantity_required')
    if not isinstance(extra_funding,tuple):raise ValueError('estimate_immutable_funding_required')
    for c in extra_funding:
        if c.kind not in ('refundable_hold','consumed_allowance','charge_withheld_from_payout'):
            raise ValueError('estimate_funding_double_count')
    entry=refund=None;audit=None;chosen=None;unit=None;acquisition=None;stake_win=None
    try:
        unit=_unit(q,fee)
        if q['source']['native_side'].lower()=='short' and unit.unit!='fixed_point_contracts' and not fee.get('recipe',{}).get('selected'):
            raise ValueError('estimate_short_collateral_unresolved')
        if unit.unit=='stake_usd':acquisition=quantity;price=None;face=None
        else:
            face=Fraction(unit.dollar_face(native_quantity));price=Fraction(q['original']['value'])/(100 if q['original']['units']=='cents_per_contract' else 1)
            if not 0<price<1:raise ValueError('estimate_price_units_conflict')
            acquisition=face*price
        if stake_fills is not None:
            if unit.unit!='stake_usd' or fills is not None:
                raise ValueError('estimate_stake_adapter_units_conflict')
            if not isinstance(stake_fills,list) or not 1<=len(stake_fills)<=100:
                raise ValueError('estimate_stake_adapter_level_bound')
            if any(set(f)!={'fill_id','order_id','stake_usd','decimal_odds','basis'} or
                   f['basis'] not in ('observed_level','modeled_residual') or
                   Fraction(f['stake_usd'])<=0 or Fraction(f['decimal_odds'])<=1 for f in stake_fills):
                raise ValueError('estimate_stake_adapter_invalid')
            if sum(Fraction(f['stake_usd']) for f in stake_fills)!=quantity:
                raise ValueError('estimate_stake_adapter_quantity_conflict')
            stake_win=sum(Fraction(f['stake_usd'])*Fraction(f['decimal_odds']) for f in stake_fills)
        if fills is None:
            fills=[dict(fill_id=f['fill_id'],order_id=f['order_id'],role='taker',unit='contracts',price='1',quantity=f['stake_usd'])
                for f in (stake_fills or [dict(fill_id='model:fill',order_id='model:order',stake_usd=wire(quantity))])] if unit.unit=='stake_usd' else [dict(fill_id='model:fill',order_id='model:order',role='taker',
                unit='novig_v3_contracts' if q['venue']=='novig' else 'contracts',price=wire(price),
                quantity=native_quantity if q['venue']=='novig' else wire(face),event_status_at_match='OPEN_PREGAME')]
        else:
            fills=deepcopy(fills)
            if unit.unit=='stake_usd' and fills:raise ValueError('estimate_stake_fill_conversion_unresolved')
            if unit.unit!='stake_usd':
                amounts=[Fraction(f['quantity'])/(100 if f['unit']=='novig_v3_contracts' else 1) for f in fills]
                if sum(amounts)!=face:raise ValueError('estimate_fill_quantity_conflict')
                acquisition=sum(Fraction(f['price'])*n for f,n in zip(fills,amounts))
                if any(f['role']!='taker' for f in fills):raise ValueError('estimate_taker_fill_required')
    except (ValueError,KeyError,TypeError,ArithmeticError) as error:
        reasons['fee'].append(str(error));reasons['payout'].append(str(error))
    receipts={s:None for s in STATES};payout_basis={s:'unknown_actual' for s in STATES};payout_details={}
    if payout.get('available') and unit is not None and acquisition is not None and not reasons['payout']:
        try:receipts,payout_basis,payout_details=_payouts(q,profiles,payout,quantity,unit,acquisition,at,_inputs)
        except (ValueError,KeyError,TypeError,ArithmeticError) as error:reasons['payout'].append(str(error))
    if stake_win is not None and not reasons['payout']:
        selection=q['binding']['selection'];home=selection['participant']==payout['recipe']['home_id']
        winning='home_win' if home else 'away_win'
        if selection['predicate']=='not_win':winning='away_win' if home else 'home_win'
        if receipts[winning] is None or Fraction(receipts[winning])!=quantity*Fraction(q['original']['value']):
            receipts[winning]=None;reasons['payout'].append('estimate_stake_ladder_selected_payout_incompatible')
        else:
            receipts[winning]=wire(stake_win)
            payout_details['stake_adapter']='predict-stake-ladder-1; weighted observed odds plus disclosed residual'
    if state_cashflows is not None:
        if set(state_cashflows)!=set(STATES):raise ValueError('estimate_disjoint_state_basis_required')
        if not payout.get('available') or reasons['payout']:
            raise ValueError('estimate_state_override_scope_unresolved')
        receipts={s:None if v is None else wire(Fraction(v)) for s,v in state_cashflows.items()}
        if any(v is not None and Fraction(v)<0 for v in receipts.values()):raise ValueError('estimate_negative_receipt')
        payout_basis={s:'provisional_assumption' for s in STATES};payout_details['state_override']='explicit_modeled_USD_cashflows'
    if fee.get('available') and unit is not None and not reasons['fee']:
        try:entry,refund,audit,chosen=_entry(q,fee,unit,fills,at)
        except (ValueError,KeyError,TypeError,ArithmeticError) as error:reasons['fee'].append(str(error))
    # Commission is on consumed net gains; returned funded holds do not reduce
    # that base. Already-withheld charges are disclosed and never deducted twice.
    held=sum((Fraction(c.amount_usd) for c in extra_funding if c.kind=='refundable_hold'),Fraction(0))
    consumed=sum((Fraction(c.amount_usd) for c in extra_funding if c.kind=='consumed_allowance'),Fraction(0))
    holds=hold_returns_usd or {s:'0' if held==0 else None for s in STATES}
    if set(holds)!=set(STATES):raise ValueError('estimate_complete_hold_state_basis_required')
    if any(v is not None and not 0<=Fraction(v)<=held for v in holds.values()):raise ValueError('estimate_hold_return_exceeds_funding')
    refund_mode=payout_details.get('refund_fees','unknown')
    fee_refunds={s:None if entry is None else wire(Fraction(entry)-Fraction(refund))
        if s in ('tie','terminal_noncompletion') and refund_mode=='returned' else '0' for s in STATES}
    settlement={s:None for s in STATES};settlement_basis='provisional_assumption';withheld=False
    settlement_terms=[]
    if entry is not None:
        rule,payload=chosen if chosen else (None,None)
        # Base market commission and an independent settlement charge are
        # separate terms. A withheld additional charge never suppresses base
        # commission, and needs its explicit modeled receipt attachment.
        terms=[]
        if rule and rule.terms.basis=='net_gain':terms.append(rule.terms)
        withheld=bool(rule and rule.settlement_status=='known_terms' and rule.settlement_treatment=='already_withheld_from_payout')
        withholding_missing=withheld and not settlement_charge_already_withheld
        if withholding_missing:reasons['fee'].append('estimate_withheld_settlement_attachment_required')
        legacy_single=(rule is not None and rule.version=='comparison-source-prophetx-site-rounding-hypothesis-1' and
            rule.venue=='prophetx' and rule.product=='single' and rule.channel=='public_site_hypothetical' and
            rule.source_kind=='controlled_scenario' and rule.terms==rule.settlement_terms and rule.terms.basis=='net_gain')
        if rule and rule.settlement_status=='known_terms' and not withheld and not legacy_single:terms.append(rule.settlement_terms)
        if legacy_single:
            # This exact archived named hypothesis encoded its one commission
            # in both slots. Retain the original profile/legacy engine; the
            # successor maps its documented single charge once. Independent
            # selected settlement terms (even equal rates) remain independent.
            audit['commission_terms_adapter']='ev05-prophetx-legacy-single-commission-1'
        if not rule and q['venue']=='prophetx':
            from .costs import FeeTerms
            terms.append(FeeTerms('net_gain','0.02','0.01','ceiling',None,'taker'))
        # Only an explicit commission-market attachment establishes pair netting.
        # Native market, venue or equal rates alone do not establish a pool.
        pool=(payload or {}).get('commission_pool')
        if pool is not None:
            if (set(pool)-{'venue','channel','market_id','cap_usd'} or
                    not {'venue','channel','market_id'}<=set(pool) or rule is None or
                    pool['venue']!=rule.venue or pool['channel']!=rule.channel or
                    not isinstance(pool['market_id'],str) or not pool['market_id'] or
                    (pool.get('cap_usd') is not None and Fraction(pool['cap_usd'])<0)):
                raise ValueError('estimate_commission_pool_binding_conflict')
        base_present=bool(rule and rule.terms.basis=='net_gain') or bool(not rule and q['venue']=='prophetx')
        for index,term in enumerate(terms):
            settlement_terms.append(dict(policy=term.generic_policy(),
                pool=deepcopy(pool) if index==0 and base_present else None,
                slot='base' if index==0 and base_present else 'additional',
                identity_basis='explicit_commission_market' if pool and index==0 and base_present else 'modeled_independent_pool',state_fees={}))
        for s,v in receipts.items():
            if withholding_missing:continue
            if not terms:settlement[s]='0'
            elif v is not None and holds[s] is not None:
                gain=Fraction(v)+Fraction(holds[s])+Fraction(fee_refunds[s])-(acquisition+Fraction(entry)-Fraction(refund)+held+consumed)
                try:
                    charges=[]
                    for term in terms:
                        result=generic_fee([],term.generic_policy(),positions=dict(account='model:standalone',market=q['source']['native_market_id'],complete=True,net_before={s:'0'}),outcomes={s:wire(gain)}) if term.basis=='net_gain' else generic_fee(fills,term.generic_policy())
                        charges.append(Fraction(result['state_fees'][s] if term.basis=='net_gain' else result['entry_fee']))
                    if pool and pool.get('cap_usd') is not None and terms and base_present:
                        charges[0]=min(charges[0],Fraction(pool['cap_usd']))
                    settlement[s]=wire(sum(charges,Fraction(0)))
                    for descriptor,charge in zip(settlement_terms,charges):descriptor['state_fees'][s]=wire(charge)
                except (ValueError,KeyError,TypeError,ArithmeticError):reasons['fee'].append('estimate_state_commission_base_unresolved')
        if rule and rule.settlement_status=='declared_zero':settlement_basis='published_template' if rule.source_kind=='public_document' else 'provisional_assumption'
        if not chosen and q['venue']=='kalshi':settlement_basis='published_template'
    dependencies=dict(consumer=VERSION,allocation_algebra='ev05-refund-aware-1',content={k:v.get('recipe',{}).get('id') for k,v in content.items()},
        original_refs=deepcopy(q['comparison_input_refs']),native_contract={k:v.get('recipe',{}).get('native_contract_id') for k,v in content.items()},
        observation=observation(q),quote_revision=q['revision'],native_quantity=native_quantity,unit=None if unit is None else asdict(unit),
        fills=deepcopy(fills),stake_fills=deepcopy(stake_fills),state_cashflows=receipts,extra_funding=[asdict(c) for c in extra_funding],hold_returns=deepcopy(holds),
        settlement_charge_already_withheld=settlement_charge_already_withheld,evaluated_at=at.isoformat())
    fee_values=dict(entry_fee_usd=(entry,'provisional_assumption'),rounding_refund_usd=(refund,'provisional_assumption'),
        net_entry_fee_usd=(None if entry is None else wire(Fraction(entry)-Fraction(refund)),'provisional_assumption'),
        additional_mandatory_charges_usd=('0' if entry is not None else None,'provisional_assumption'))
    for s in STATES:
        fee_values['settlement_fee_usd:'+s]=(settlement[s],settlement_basis)
        fee_values['fee_refund_usd:'+s]=(fee_refunds[s],'provisional_assumption')
    payout_values={'receipt_usd:'+s:(v,payout_basis[s]) for s,v in receipts.items()}
    payout_values.update({'hold_return_usd:'+s:(holds[s],'provisional_assumption') for s in STATES})
    if not retain_profiles:
        # Sizing probes and slate summaries retain no rich provider graph. The
        # same allocation algebra runs; selected evidence is reopened by a
        # fresh consume call with exactly these inputs.
        return dict(version=VERSION,components={kind:{name:dict(modeled_value=v[0],actual_value=None,basis=v[1])
            for name,v in values.items()} for kind,values in [('fee',fee_values),('payout',payout_values)]},
            dependencies=dependencies,dependency_revision=digest(dependencies),reasons=reasons,
            acquisition_usd=None if acquisition is None else wire(acquisition),
            deployed_capital_usd=None if entry is None else wire(acquisition+Fraction(entry)-Fraction(refund)+held+consumed),
            settlement_already_withheld=withheld,actual_qualified=False,payout_details=payout_details,
            **(dict(settlement_terms=settlement_terms) if settlement_metadata else {}),
            grid_qualification='original_quantity_profile_if_bound; otherwise_declared_grid_hypothesis_not_execution')
    expiries={}
    for kind in ('fee','payout'):
        item=content[kind];candidates=[item.get('recipe',{}).get('expires_at'),item.get('template',{}).get('expires_at')]
        original=item.get('original_profile') or {}
        candidates.append(original.get('expires_at'))
        if kind=='fee' and chosen:
            candidates.extend([chosen[0].expires_at,chosen[0].effective_to])
        if kind=='payout':candidates.append(payout_details.get('selected_profile',{}).get('effective_until'))
        expiries[kind]=min((v for v in candidates if v is not None),key=instant,default=None)
    payload=dict(consumer_version=VERSION,dependencies=dependencies,actual_value=None,actual_qualified=False,scalar_unit='USD')
    providers={kind:TemplateProvider(kind,json.loads(encoded(dict(payload,content=content[kind],unresolved_reasons=reasons[kind],
        details=audit if kind=='fee' else payout_details,component_metadata={name:dict(unit='USD',actual_value=None,actual_reason='actual_charge_unknown' if kind=='fee' else 'actual_settlement_unknown',model_reason=None if value[0] is not None else '; '.join(reasons[kind]) or 'state_receipt_or_hold_return_unknown',basis=value[1]) for name,value in values.items()},resolved_components={name:list(value) for name,value in values.items()},settlement_already_withheld=withheld if kind=='fee' else None))),values,
        expires_at=expiries[kind]) for kind,values in [('fee',fee_values),('payout',payout_values)]}
    pool=ProfilePool(compact=True);refs={};components={}
    for kind,provider in providers.items():
        key,value=provider.profile()
        if not pool.add(key,value):raise ValueError('estimate_component_representation_capacity')
        refs[kind]=key
        components[kind]={name:provider.resolve(scope).to_dict() for name,scope in provider.to_dict()['components'].items()}
    registry=pool.finish()
    # A serialized consumer reopens through the same shared-profile resolution path.
    for kind,key in refs.items():assert resolve(registry,key)==providers[kind].profile()[1]
    result=dict(version=VERSION,components=components,profile_refs=refs,profiles=registry,
        dependencies=dependencies,dependency_revision=digest(dependencies),reasons=reasons,
        acquisition_usd=None if acquisition is None else wire(acquisition),
        deployed_capital_usd=None if entry is None else wire(acquisition+Fraction(entry)-Fraction(refund)+held+consumed),
        settlement_already_withheld=withheld,actual_qualified=False,
        **(dict(settlement_terms=settlement_terms,payout_details=payout_details) if settlement_metadata else {}),
        assumed_additional_charges='zero_under_funded_direct_site_model; no_evidenced_exemption',
        grid_qualification='original_quantity_profile_if_bound; otherwise_declared_continuous_hypothesis_not_execution',
        fill_basis='explicit_supplied_fills' if fills and fills[0]['fill_id']!='model:fill' else 'hypothetical_one_order')
    result['revision']=digest(result)
    return result


def resolve_component(profiles, profile_ref, component, *, dependency_revision, at):
    """Reopen exact allocation through shared profiles; changed inputs require consume again."""
    value=resolve(profiles,profile_ref)
    if digest(value)!=profile_ref:raise ValueError('estimate_component_profile_digest_conflict')
    payload=value['payload']
    if payload.get('consumer_version')!=VERSION or digest(payload['dependencies'])!=dependency_revision:
        raise ValueError('estimate_component_allocation_changed')
    if at<instant(payload['dependencies']['evaluated_at']):
        raise ValueError('estimate_component_not_effective')
    if value['expires_at'] is not None and at>=instant(value['expires_at']):
        raise ValueError('estimate_component_expired')
    if component not in payload['resolved_components']:raise ValueError('estimate_component_scope_unknown')
    provider=TemplateProvider(value['kind'],payload,payload['resolved_components'],expires_at=value['expires_at'])
    return provider.resolve(provider.scope_id(component))
