"""Scanner cashflow classification and observed-only bounded discovery sizing.

Existing allocation, nonlinear fee, pool, collateral and joint-cashflow owners
remain authoritative. Probabilities never remove a feasible cashflow state.
"""
from copy import deepcopy
from fractions import Fraction as F
from itertools import product

from .current_dependencies import digest, instant, references
from .estimated_pair import (Leg, economics, joint_basis, native_key, probabilities,
                             expected, EXPOSURE_FLOOR, MIN_SHARE, MAX_NATIVE)
from .estimated_policy import DEFAULT_POLICY, buffer_usd
from .net_costs import wire
from .calculation_control import checkpoint

VERSION = 'predict-scanner-evaluator-1'
MAX_POINTS = 16
MAX_EVALUATIONS = MAX_POINTS ** 2
CATEGORIES = ('covered_outcome_arb', 'conditional_hedge', 'ev')
BASES = dict(covered_outcome_arb='net_complete_minimum_return_percent',
             conditional_hedge='net_decisive_minimum_return_percent',
             ev='net_expected_return_percent')


def exact(value):
    if value is None:
        return None
    from app.dashboard.current_contract import exact_wire, display_decimal
    value = F(value)
    return dict(value=wire(value), display=display_decimal(exact_wire(value)['decimal_approx'], 2, True))


def _classify_raw(states, capital, *, policy=DEFAULT_POLICY, settlement_complete=True,
                  probabilities=None, conditional_probabilities=None, ev_current=False):
    """One scalar classification owner; no presentation during allocation search."""
    capital = F(capital)
    if capital <= 0:
        raise ValueError('scanner_positive_deployed_capital_required')
    haircut = buffer_usd(capital, policy.buffer_rate)
    profits = {k: None if v['profit_usd'] is None else F(v['profit_usd']) for k, v in states.items()}
    def minimum(names):
        values = [profits.get(k) for k in names]
        return None if not values or any(x is None for x in values) else min(values) - haircut
    settlement_complete = settlement_complete and {'a_wins','b_wins','tie','terminal_noncompletion'}.issubset(profits)
    complete = minimum(profits) if settlement_complete else None
    decisive = minimum(('a_wins', 'b_wins'))
    def partition(values, names):
        if values is None or set(values) != set(names) or any(v is None for v in values.values()):
            return None
        values={k:F(v) for k,v in values.items()}
        return values if all(v>=0 for v in values.values()) and sum(values.values())==1 else None
    probabilities=partition(probabilities,states)
    conditional_probabilities=partition(conditional_probabilities,('a_wins','b_wins'))
    complete_ev = expected(states, probabilities) if settlement_complete and probabilities is not None else None
    conditional_ev = expected(states, conditional_probabilities) if conditional_probabilities is not None else None
    ev = complete_ev if complete_ev is not None else conditional_ev
    rows = []
    if complete is not None and complete > 0:
        rows.append(('covered_outcome_arb', 100 * complete / capital, 'all_required_feasible_states', True))
    elif decisive is not None and decisive > 0:
        rows.append(('conditional_hedge', 100 * decisive / capital, 'decisive_home_or_away_win', True))
    if ev is not None:
        rows.append(('ev', 100 * (ev-haircut) / capital,
                     'complete' if complete_ev is not None else 'conditional_decisive', ev_current))
    return (capital, haircut, complete, decisive, ev), rows


def classify(states, capital, *, policy=DEFAULT_POLICY, settlement_complete=True,
             probabilities=None, conditional_probabilities=None, ev_current=False):
    """Independent category metrics; all mandatory states count even at p=0."""
    values, categories = _classify_raw(states, capital, policy=policy, settlement_complete=settlement_complete,
        probabilities=probabilities, conditional_probabilities=conditional_probabilities, ev_current=ev_current)
    capital, haircut, complete, decisive, ev = values
    metrics = dict(complete_minimum_usd=exact(complete), decisive_minimum_usd=exact(decisive),
                   expected_profit_usd=exact(None if ev is None else ev - haircut),
                   deployed_capital_usd=wire(capital), buffer_usd=wire(haircut), buffer_applications=1)
    rows = [dict(category=key, metric=exact(metric), metric_basis=BASES[key], conditioning=conditioning, current=current)
            for key, metric, conditioning, current in categories]
    return metrics, rows


def _needs_provisional_format(values, categories):
    """Only defer formatting when every displayed fraction is plainly bounded.

    A 256-bit numerator/denominator has at most 78 decimal digits each. The
    existing exact display's precision and decimal/exponent bounds cannot be
    exceeded there. Larger values keep the original per-allocation formatter,
    including its refusals on allocations which never become category winners.
    """
    capital, haircut, complete, decisive, ev = values
    scalars = (capital, haircut, complete, decisive, None if ev is None else ev-haircut,
               *(metric for _, metric, _, _ in categories))
    return any(value is not None and (value.numerator.bit_length()>256 or value.denominator.bit_length()>256)
               for value in scalars)


def opportunity_identity(instruments):
    """Native predicates/terms are identity; source clocks, prices and depth revise."""
    if len(instruments) != 2 or len({i['venue'] for i in instruments}) != 2:
        raise ValueError('scanner_distinct_execution_venues_required')
    if any(i['venue'] == 'pinnacle' for i in instruments):
        raise ValueError('scanner_reference_only_venue')
    if any(instruments[0][k] != instruments[1][k] for k in
           ('occurrence_id', 'sport', 'league', 'market', 'period', 'overtime')):
        raise ValueError('scanner_exact_compatible_positions_required')
    fields = ('native_key', 'predicate', 'units', 'native_contract_id', 'terms_sha256')
    return 'opportunity:' + digest(dict(version=VERSION, occurrence=instruments[0]['occurrence_id'],
        dimensions={k: instruments[0][k] for k in ('sport','league','market','period','overtime')},
        legs=sorted(({k: i[k] for k in fields} for i in instruments), key=digest),
        economics='standalone_funded_taker_to_settlement'))


def dependencies(pair, instruments, inputs, policy, engine):
    """Exact economically relevant proof, excluding publication/receipt churn.

    Profile payloads/evidence remain exact. Only known transport-only quote and
    instrument fields are removed; unknown fields invalidate conservatively.
    """
    rows = []
    for key in sorted(pair['legs']):
        i = deepcopy(instruments[key]); x = inputs[key]; q = deepcopy(x['quote'])
        for field in ('revision', 'id', 'calculations'):
            q.pop(field, None)
        for field in ('received_at', 'projected_at'):
            q.get('times', {}).pop(field, None)
        for field in ('received_at', 'book_received_at', 'ingress_projected_at', 'sql_committed_at'):
            i['clocks'].pop(field, None)
        rows.append(dict(instrument=i, quote=q, profiles=references(x['quote'], x['profiles']),
                         event={k:v for k,v in x['event'].items() if k not in ('groups','funded_pairs')},
                         group={k:v for k,v in x['group'].items() if k != 'outcomes'}))
    return digest(dict(rows=rows, policy=policy.to_dict(), evaluator=VERSION, engine=engine))


def _joint(legs):
    """Only derive joint grades for explicit equal or nested completion clauses.

    Unknown/different incomparable completion terms cannot establish an exact
    feasible joint partition. Decisive scenarios remain inspectable separately.
    """
    a, b = [x.conditions for x in legs]
    supported = bool(a and b and a == b)
    if a and b and a.get('kind') == b.get('kind') and a.get('kind') in ('starts_within_hours','rescheduled_within_days'):
        clocks = ('original_start',) if a['kind']=='starts_within_hours' else ('original_scheduled_date','date_timezone')
        supported = all(a.get(k)==b.get(k) and a.get(k) is not None for k in clocks)
        supported = supported and all(x.get('maximum') is not None for x in (a,b))
    if supported:
        return joint_basis(legs), True
    return {k: dict(cells=[v,v], terminal=False, weight=None) for k,v in
            (('a_wins','home_win'), ('b_wins','away_win'), ('tie','tie'))}, False


def _points(leg, budget):
    # Clamp to the observed path before any allocation/fee call; no residual.
    upper = leg.floor(min(MAX_NATIVE, sum((n for _,n in leg.path['levels']), F(0)),
                          budget / leg.path['minimum_cost']))
    if upper < leg.lower:
        return []
    count = int((upper-leg.lower)//leg.increment)+1
    if count <= MAX_POINTS:
        return [leg.lower + j*leg.increment for j in range(count)]
    values = {leg.lower, upper}
    values.update(leg.floor(leg.lower+(upper-leg.lower)*F(j, MAX_POINTS-1)) for j in range(MAX_POINTS))
    return sorted(values)[:MAX_POINTS]


def evaluate(pair, instruments, inputs, *, at, policy=DEFAULT_POLICY):
    """One pair, bounded observed legal allocations; no maximum-size claim."""
    legs = []
    for key in sorted(pair['legs']):
        x = inputs[key]
        legs.append(Leg(x['quote'], x['group'], x['profiles'], x['event'], instant(at), policy=policy))
    if len({x.q['venue'] for x in legs}) != 2 or legs[0].sign == legs[1].sign:
        raise ValueError('scanner_distinct_opposing_execution_legs_required')
    keys = [(x.q['venue'], x.q['source']['provider'], *native_key(x.q)[1:4]) for x in legs]
    if keys[0] == keys[1] or legs[0].liquidity_ids & legs[1].liquidity_ids or (
            legs[0].shared_depth and legs[0].shared_depth == legs[1].shared_depth):
        raise ValueError('scanner_shared_depth_conflict')
    basis, complete = _joint(legs)
    budget = F(policy.capital_ceiling_usd)
    points = [_points(x, budget) for x in legs]
    counts=[max(0,int((x.floor(min(MAX_NATIVE,sum((n for _,n in x.path['levels']),F(0)),budget/x.path['minimum_cost']))-x.lower)//x.increment)+1) for x in legs]
    # Include observed payout-balanced neighborhoods without adding search slots.
    for index,x in enumerate(legs):
        other = legs[1-index]
        balanced = [x.floor(n*other.exposure_per_native/x.exposure_per_native) for n in points[1-index]]
        valid = sorted({n for n in balanced if points[index] and x.lower <= n <= max(points[index])})
        if valid and counts[index]>MAX_POINTS:
            points[index] = sorted(set(points[index][:MAX_POINTS//2] + points[index][-2:] + valid[:MAX_POINTS//2-2]))
    best = {}; evaluations = 0; any_valid = False; cashflows_complete = complete
    # References and their settlement partition are quantity independent.
    probs, weight, reason = probabilities(legs, basis, policy)
    conditional = None if weight is None else dict(a_wins=weight,b_wins=1-weight)
    ev_current = any(instruments[k]['checks']['ev']['state'] == 'ready' for k in pair['legs'])
    # Leg caches retain bounded scalars only. State algebra uses existing owners.
    for qs in product(*points):
        checkpoint(); evaluations += 1
        components = [x.get(n) for x,n in zip(legs, qs)]
        capital = sum((c['_pair_capital'] for c in components), F(0))
        exposures = [c['_pair_exposure'] for c in components]
        if capital <= 0 or capital > budget or min(exposures) < EXPOSURE_FLOOR or min(exposures) < MIN_SHARE*sum(exposures):
            continue
        if any(F(c['pair_support']) != n for c,n in zip(components,qs)):
            continue
        any_valid = True
        capital, states = economics(components, basis, _profit_only=True)
        cashflows_complete = cashflows_complete and all(s['profit_usd'] is not None for s in states.values())
        values, categories = _classify_raw(states, capital, policy=policy, settlement_complete=complete,
            probabilities=probs, conditional_probabilities=conditional, ev_current=ev_current)
        if _needs_provisional_format(values, categories):
            classify(states, capital, policy=policy, settlement_complete=complete,
                probabilities=probs, conditional_probabilities=conditional, ev_current=ev_current)
        for key, metric, _, _ in categories:
            old = best.get(key)
            # Preserve the previous wire-roundtrip score, including terminating
            # decimal precision, before the capital and native-quantity ties.
            score = (F(wire(metric)), capital, tuple(qs))
            if old is None or score > old[0]:
                # Economics owns fresh state dictionaries; Leg.get owns stable
                # bounded component records. Retain at most one winner/category.
                best[key] = (score, states, tuple(qs), tuple(components))
    rows = []
    for key, (score, states, qs, components) in sorted(best.items()):
        capital = score[1]
        metrics, categories = classify(states, capital, policy=policy, settlement_complete=complete,
            probabilities=probs, conditional_probabilities=conditional, ev_current=ev_current)
        category = next(value for value in categories if value['category'] == key)
        allocation = [dict(native_key=list(native_key(x.q)), predicate=deepcopy(x.q['binding']['selection']),
            native_quantity=wire(n), native_unit=x.unit.unit, grid=x.grid,
            deployed_capital_usd=c['deployed_capital_usd'], acquisition_usd=c['acquisition_usd'])
            for x,n,c in zip(legs,qs,components)]
        rows.append(dict(**category, metrics=metrics, allocation=allocation,
            settlement_complete=complete, state_profits={s:v['profit_usd'] for s,v in states.items()},
            reasons=[] if complete else ['joint_settlement_meaning_unknown'],
            size_basis='observed_legal_allocation', size_status='supported_size',
            supported_capital_usd=wire(capital)))
    exhaustive=all(len(values)==count for values,count in zip(points,counts))
    qualified='covered_outcome_arb' in best
    incomplete_reasons=[] if cashflows_complete else ['mandatory_joint_cashflows_unknown']
    if not exhaustive and not qualified:incomplete_reasons.append('bounded_size_search_incomplete')
    return dict(rows=rows, evaluated=True,
        evaluation_complete=not incomplete_reasons,incomplete_reasons=incomplete_reasons, qualifying='covered_outcome_arb' in best,
        reasons=[] if any_valid else ['no_supported_meaningful_allocation'],
        search=dict(evaluations=evaluations, maximum_evaluations=MAX_EVALUATIONS,
                    allocation_grid_exhaustive=exhaustive, global_optimality_proven=False, maximum_size_proven=False,
                    basis='bounded_observed_legal_grid'), evaluator_revision=VERSION)
