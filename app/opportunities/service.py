"""Dependency-bound offline signals. Probabilities never enter the Arb engine."""
from copy import deepcopy
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal, Context, localcontext
import json

from app.arbitrage import Policy as BookPolicy, eligibility
from app.depth import AcquisitionLadder, Search, size_depth, evaluate_allocation
from app.edge_contracts import loads
from app.fees.engine import Registry, digest, number
from app.matching import Matcher
from app.moneyline import MoneylineMatcher
from app.pricing.baseline import restore as restore_estimate
from app.reference.records import packed
from app.settlement import payout, compare_profiles, SCENARIOS
from app.storage.replay import observation_load
from app.storage.store import exact_time

VERSION = 'offline-opportunities-1'
FORMAT = 'opportunity-bundle-1'
POLICY = dict(version=VERSION, arithmetic='Decimal-100-half-even',
    book_policy=asdict(BookPolicy()), search=asdict(Search()),
    estimate_max_age_seconds=30, probability_basis='unconditional_exclusive_exhaustive_states',
    sizing='same_explicit_contract_quantity_per_arb_leg;single_target_quantity_for_ev',
    fills='one_new_taker_order_per_leg;one_fill_per_consumed_level',
    impact='included_in_walked_prices;no_additional_impact_charge',
    ranking='within_class_event_cutoff_quantity_model;conditional_synthetic_only')


def check_nested_knowledge(value, cutoff):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ('known_at', 'reviewed_at', 'received_at', 'retrieved_at') and isinstance(item, str):
                if exact_time(item) > cutoff: raise ValueError('late nested dependency knowledge/receipt')
            check_nested_knowledge(item, cutoff)
    elif isinstance(value, list):
        for item in value: check_nested_knowledge(item, cutoff)


def known(record, cutoff):
    if not record['evidence'].startswith('synthetic:'):
        raise ValueError('explicit synthetic dependency provenance required')
    if max(exact_time(record['known_at']), exact_time(record['effective_at'])) > cutoff:
        raise ValueError('late knowledge/effective dependency')


@dataclass(frozen=True)
class Audit:
    payload_json: str

    @property
    def data(self): return json.loads(self.payload_json)
    @property
    def id(self): return digest(self.data)
    def export(self): return packed(dict(format=FORMAT, sha256=self.id, payload=self.data))


def evaluate(inputs):
    # Freeze caller input and isolate arithmetic from ambient Decimal context.
    with localcontext(Context(prec=100)):
        return _evaluate(json.loads(packed(inputs)))


def _evaluate(inputs):
    if inputs['policy'] != json.loads(packed(POLICY)):
        raise ValueError('unsupported service policy/version')
    e = restore_estimate(inputs['estimate'])
    ed, market = e.data, inputs['market']
    cutoff = exact_time(inputs['as_of'])
    if exact_time(inputs['evaluated_at']) < cutoff:
        raise ValueError('evaluation precedes cutoff')
    if max(exact_time(ed['as_of']), exact_time(ed['estimated_at'])) > cutoff:
        raise ValueError('late estimate dependency')
    known(market, cutoff)
    check_nested_knowledge(market, cutoff)
    known(inputs['sizing'], cutoff)
    parents = Matcher.from_envelope(market['parents'])
    matcher = MoneylineMatcher.from_envelope(market['markets'])
    terms = loads(ed['target']['terms_json'])
    if terms.canonical_event_id not in parents.snapshot['canonicals']:
        raise ValueError('estimate event absent from prediction books')
    if market['canonical_event_id'] != terms.canonical_event_id:
        raise ValueError('prediction event binding mismatch')
    # Metadata snapshots carry a knowledge receipt for mappings, rules and fee
    # schedules; their native receipts cannot occur after that receipt or cutoff.
    for row in parents.snapshot['observations'].values():
        if row['start'] != terms.scheduled_start.isoformat() or row['league'] != terms.league or set(row['participants']) != set(terms.outcomes):
            raise ValueError('event schedule/participant mismatch')
    for row in matcher.snapshot['observations'].values():
        if exact_time(row['raw']['received_at']) > min(cutoff, exact_time(market['known_at'])):
            raise ValueError('late prediction metadata receipt')
        if row['scope'] != ['synthetic', 'synthetic']:
            raise ValueError('synthetic market scope required')
    ladders = []
    book_ids = []
    book_time_blocks = []
    receipt_times = []
    for book in market['books']:
        known(book, cutoff)
        raw = book['observation']['quote']['raw']
        received = exact_time(raw['received_at'])
        receipt_times.append(received)
        if received > min(cutoff, exact_time(book['known_at'])):
            raise ValueError('late exact book receipt')
        if cutoff-received > Decimal(POLICY['book_policy']['max_receipt_age_seconds']):
            book_time_blocks.append('book_receipt_stale_exact')
        if raw['exchange_at'] is not None:
            source_time = exact_time(raw['exchange_at'])
            if source_time > received: raise ValueError('book source clock later than exact receipt')
            if book['observation']['source_time_semantics']=='snapshot' and cutoff-source_time > Decimal(POLICY['book_policy']['max_source_age_seconds']):
                book_time_blocks.append('book_snapshot_stale_exact')
        obs = observation_load(book['observation'])
        if obs.environment != 'synthetic' or obs.evidence_class != 'synthetic' or obs.quote.raw.kind.value != 'synthetic':
            raise ValueError('synthetic executable book required')
        if obs.quote.raw.ref.venue.value not in ('kalshi', 'polymarket_us') or obs.role != 'taker':
            raise ValueError('only prediction venue taker books supported')
        if exact_time(obs.quote.raw.received_at.isoformat()) > min(cutoff, exact_time(book['known_at'])):
            raise ValueError('late book receipt')
        if obs.quote.raw.exchange_at and obs.quote.raw.exchange_at > obs.quote.raw.received_at:
            raise ValueError('book source clock later than receipt')
        if book['id'] != digest({k:v for k,v in book.items() if k != 'id'}):
            raise ValueError('book observation identity mismatch')
        book_ids.append(book['id'])
        ladders.append(AcquisitionLadder(obs, None if book['levels'] is None else tuple(tuple(x) for x in book['levels']), book['transformation'], book['partial_final']))
    if not ladders or len(set(book_ids)) != len(book_ids):
        raise ValueError('missing or duplicate book identities')
    if max(receipt_times)-min(receipt_times) > Decimal(POLICY['book_policy']['max_observation_skew_seconds']):
        book_time_blocks.append('book_receipt_skew_exceeded')
    contexts = {tuple(k):v for k,v in market['contexts']}
    if len(contexts) != len(market['contexts']): raise ValueError('duplicate fee context')
    report = size_depth(parents, matcher, ladders, contexts,
        evaluation_time=datetime.fromisoformat(inputs['as_of']), registry=Registry(market['registry']),
        policy=BookPolicy(**inputs['policy']['book_policy']), search=Search(**inputs['policy']['search']))
    candidates = [c for c in report['candidates'] if c['id'] == inputs['candidate_id']]
    if len(candidates) != 1: raise ValueError('missing/ambiguous candidate')
    candidate = candidates[0]; base = candidate['input']['base']
    decision = matcher.snapshot['decisions'][base['pair_id']]
    if decision['canonical_market_id'] != terms.canonical_market_id or not decision['structural_match']:
        raise ValueError('target structural market mismatch')
    rows = {matcher.snapshot['observations'][h]['key']:matcher.snapshot['observations'][h] for h in base['market_hashes']}
    target_indices = []
    for i, leg in enumerate(base['legs']):
        row = rows[leg['native_market_key']]
        side = next(s for s in row['sides'] if s['native_id'] == leg['side'])
        if row['venue'] == ed['target']['venue'] and side['participant'] == ed['target']['outcome'] and side['predicate'] == ed['target']['predicate']:
            target_indices.append(i)
    if len(target_indices) != 1: raise ValueError('estimate predicate does not identify one candidate leg')
    i = target_indices[0]; target_row = rows[base['legs'][i]['native_market_key']]
    target_side = next(s for s in target_row['sides'] if s['native_id'] == base['legs'][i]['side'])
    settlement = compare_profiles(json.loads(terms.rules_profile_json), target_row['profile'])
    payouts = {name:payout(target_side, name, target_row['profile']) for name in [*('winner:'+p for p in terms.outcomes), *SCENARIOS]}
    blocks = list(dict.fromkeys(book_time_blocks))
    for n, ladder in enumerate(ladders):
        blocks.extend(f'book-{n}:{r}' for r in eligibility(ladder.observation, datetime.fromisoformat(inputs['as_of']), BookPolicy()) if r != 'non-production-environment')
    if cutoff >= exact_time(terms.scheduled_start.isoformat())-1: blocks.append('pregame_cutoff_reached')
    quantity = inputs['sizing']['quantity']
    allocation = None
    if quantity is None:
        blocks.append('quantity_unknown')
    else:
        if number(quantity) <= 0: raise ValueError('positive explicit quantity required')
        try: allocation = evaluate_allocation(candidate, (quantity, quantity))
        except ValueError as exc: blocks.append('sizing_unavailable:'+str(exc))
    arb_blocks = list(blocks)
    if not base['settlement']['qualified']: arb_blocks.append('settlement_compatibility_unknown_or_incompatible')
    if base['relationship']['complementary_payoffs'] != 'YES': arb_blocks.append('material_complementarity_unavailable')
    if allocation is None or allocation['worst_case_profit'] is None: arb_blocks.append('material_outcome_or_cost_unknown')
    arb_net = None if arb_blocks else allocation['worst_case_profit']
    basis = dict(event=terms.canonical_event_id, as_of=inputs['as_of'], quantity=quantity, unit='USD_per_1_dollar_payout_contract')
    arb = dict(signal_class='arb', status='unavailable' if arb_net is None else 'conditional',
        net_total_usd=arb_net, net_per_contract_usd=None if arb_net is None else str(Decimal(arb_net)/Decimal(quantity)),
        return_fraction=None if arb_net is None else allocation['worst_case_roi'],
        denominator_usd=None if allocation is None else allocation['roi_denominator'],
        denominator_basis='both_legs_entry_cash_plus_consumed_execution_reserve',
        sizing_basis={**basis, 'legs':2, 'model':'worst_case_all_material_states'},
        reasons=arb_blocks, qualification_reasons=candidate['reasons'] if allocation is None else allocation['reasons'],
        conditional_calculation=allocation, current_production_opportunity=False)
    ev_blocks = list(blocks)
    if cutoff-exact_time(ed['as_of']) > POLICY['estimate_max_age_seconds']: ev_blocks.append('stale_estimate')
    if not settlement['qualified']: ev_blocks.append('estimate_target_settlement_incompatible_or_unknown')
    leg = None if allocation is None else allocation['legs'][i]
    cashflows = {name:dict(payout=pay, cashflow=None if leg is None else leg['outcomes'].get(name)) for name,pay in payouts.items()}
    model = inputs['model']; probabilities = None; fair_value = None
    if model is None:
        ev_blocks += ['E3_conditional_normal_winner_probabilities_only', 'exceptional_probability_mass_unknown', 'unconditional_target_value_unknown']
    else:
        known(model, cutoff)
        if model['version'] != 'invented-unconditional-scenarios-1' or model['basis'] != POLICY['probability_basis']:
            raise ValueError('unsupported scenario probability basis')
        if model['target_hash'] != digest(ed['target']) or model['payouts_hash'] != digest(payouts):
            raise ValueError('scenario target/payout dependency mismatch')
        if not model['exclusive_exhaustive_assumption'].startswith('synthetic:'):
            raise ValueError('scenario partition assumption required')
        probabilities = model['probabilities']
        if set(probabilities)-set(payouts): raise ValueError('unmodeled outcome probability')
        values = []
        for v in probabilities.values():
            if v is not None:
                n=number(v)
                if not 0 <= n <= 1: raise ValueError('invalid outcome probability')
                values.append(n)
        mass = sum(values, Decimal(0))
        if mass > 1: raise ValueError('probability mass exceeds one')
        if set(probabilities) != set(payouts) or any(v is None for v in probabilities.values()) or mass != 1:
            ev_blocks.append('unconditional_probability_mass_incomplete')
        else:
            if all(p['kind']=='fraction' for p in payouts.values()):
                fair_value = sum((Decimal(probabilities[n])*Decimal(p['value']) for n,p in payouts.items()), Decimal(0))
            elif leg and all(leg['outcomes'].get(n,{}).get('gross_payout') is not None for n in payouts):
                fair_value = sum((Decimal(probabilities[n])*Decimal(leg['outcomes'][n]['gross_payout'])/Decimal(quantity) for n in payouts), Decimal(0))
            if model['claimed_fair_value_usd'] is not None and (fair_value is None or number(model['claimed_fair_value_usd']) != fair_value):
                raise ValueError('scenario probability relationship to target value mismatch')
    if any(row['cashflow'] is None or row['cashflow'].get('net_cashflow') is None for row in cashflows.values()):
        ev_blocks.append('material_state_cashflow_or_fee_unknown')
    net = None
    if not ev_blocks:
        net = sum((Decimal(probabilities[n])*Decimal(row['cashflow']['net_cashflow']) for n,row in cashflows.items()), Decimal(0))
    cash = None if leg is None else leg['required_cash']
    ev = dict(signal_class='mispricing', status='unavailable' if net is None else 'conditional',
        net_total_usd=None if net is None else str(net), net_per_contract_usd=None if net is None else str(net/Decimal(quantity)),
        return_fraction=None if net is None or cash is None or Decimal(cash)<=0 else str(net/Decimal(cash)),
        denominator_usd=cash, denominator_basis='single_target_entry_cash_requirement',
        sizing_basis={**basis,'legs':1,'model':e.id if model is None else digest(model)},
        reasons=ev_blocks, qualification_reasons=[] if leg is None else leg['reasons'],
        estimate_reasons=ed['reasons'], estimate_status=ed['status'],
        conditional_probability=ed['conditional_target_probability'],
        probability_gap_diagnostic=None if ed['conditional_target_probability'] is None or base['legs'][i]['observation'] is None or base['legs'][i]['observation']['ask'] is None else str(Decimal(ed['conditional_target_probability'])-Decimal(base['legs'][i]['observation']['ask'])),
        gap_basis='conditional_normal_winner_probability_minus_top_ask_fraction;not_dollars_or_return',
        unconditional_fair_value_usd=None if fair_value is None else str(fair_value),
        state_cashflows=cashflows, fee_audit=None if leg is None else leg['fee_audit'],
        current_production_opportunity=False)
    result = dict(version=VERSION, inputs=inputs, estimate_id=e.id, book_ids=book_ids,
        dependency_hashes={k:digest(v) for k,v in inputs.items()},
        settlement=settlement, depth_audit=candidate, detector_report=report['top_of_book'],
        signals=[arb,ev], liquidity_families=sorted({l['liquidity_family'] for l in base['legs']}),
        assumptions=['wholly synthetic; not calibrated or live-qualified', 'specified fills only; fragmentation may change rounded fees',
            'scenario states are invented mutually exclusive settlement paths, not empirical event frequencies'],
        liquidity_note='Alternative scenarios share liquidity. Never sum their profits as independently attainable.')
    return Audit(packed(result))


def replay(audit):
    rebuilt = evaluate(audit.data['inputs'])
    if rebuilt != audit: raise ValueError('opportunity output/dependency mismatch')
    return rebuilt


def restore(text):
    row=json.loads(text)
    if row['format'] != FORMAT: raise ValueError('unsupported opportunity format')
    audit=Audit(packed(row['payload']))
    if audit.id != row['sha256']: raise ValueError('opportunity identity mismatch')
    return replay(audit)


def rank(audits):
    """Alternative comparisons only. Different sizing/model bases get separate lists."""
    groups={}; unavailable=[]; seen=set()
    for audit in audits:
        replay(audit)
        if audit.id in seen: continue
        seen.add(audit.id)
        for signal in audit.data['signals']:
            row=dict(audit_id=audit.id, signal_class=signal['signal_class'], net_total_usd=signal['net_total_usd'],
                status=signal['status'], reasons=signal['reasons'], liquidity_families=audit.data['liquidity_families'])
            if row['net_total_usd'] is None: unavailable.append(row); continue
            key=packed([signal['signal_class'],signal['sizing_basis']])
            groups.setdefault(key,[]).append(row)
    return dict(groups=[dict(basis=json.loads(key), rows=sorted(rows,key=lambda r:(-Decimal(r['net_total_usd']),r['audit_id']))) for key,rows in sorted(groups.items())],
        unavailable=unavailable, aggregate_attainable_profit_usd=None,
        note='Within-class conditional comparisons only; shared liquidity is not additive.')
