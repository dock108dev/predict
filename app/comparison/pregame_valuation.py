"""Value one exact published offer. The caller owns publication and display."""
from fractions import Fraction as F

from .cashflows import exact_wire as wire
from .trade_preview import parse_amount

VERSION = 'predict-pregame-valuation-1'
SIZING = 'under-budget-max-1pct-capped-at-1usd-v1'
SCORE_TOLERANCE = F(1, 10**14)
MAX_LEVELS = 32
INPUT_ERRORS = (OSError, ValueError, KeyError, TypeError, ArithmeticError)


def _rounded(value, digits=0):
    scale = 10**digits
    ticks = int(abs(value) * scale + F(1, 2))
    return -ticks if value < 0 else ticks


def decimal_display(value, digits=2, *, signed=False):
    ticks = _rounded(value, digits)
    whole, rest = divmod(abs(ticks), 10**digits)
    sign = '-' if ticks < 0 else '+' if signed else ''
    return f'{sign}{whole}.{rest:0{digits}d}' if digits else f'{sign}{whole}'


def american(decimal):
    if decimal <= 1:
        return None
    odds = 100 * (decimal - 1) if decimal >= 2 else -100 / (decimal - 1)
    return decimal_display(odds, 0, signed=True)


def score(probabilities, ratios, ev):
    """Return the unrounded score; nonbinary answers are deterministic to 1e-10 points."""
    if ev <= 0:
        return F(0)
    if set(ratios) == {'win', 'loss'} and ratios['loss'] == -1 and ratios['win'] > 0:
        return 10_000 * min(F(1), ev / ratios['win'])
    active = [(p, ratios[state]) for state, p in probabilities.items() if p]
    upper = min([F(1), *(-1 / r for _, r in active if r < 0)])

    def derivative(f):
        return sum(p * r / (1 + f * r) for p, r in active)

    if all(1 + upper * r > 0 for _, r in active) and derivative(upper) >= 0:
        return 10_000 * upper
    lo, hi = F(0), upper
    while hi - lo > SCORE_TOLERANCE:
        mid = (lo + hi) / 2
        if derivative(mid) > 0:
            lo = mid
        else:
            hi = mid
    return 10_000 * (lo + hi) / 2


def _offer_fee(row, terms, cost):
    from .pregame_valuation_fees import retail_order

    fee = row.get('trade_fee') or {}
    fixed = terms.get('cash_terms')
    if fixed:
        # Only server-owned reviewed terms or labeled fixtures can enter here.
        # This contract takes a versioned rounding/fee policy, not account rates.
        evidence = fixed['evidence']
        if (not evidence.get('revision') or not evidence.get('source')
                or fixed.get('order_type') != terms.get('order_type')
                or evidence.get('class') not in ('exact_public', 'fixture')
                or (evidence['class'] == 'fixture') != (terms.get('evidence_class') == 'fixture')):
            raise ValueError('unit_fee_evidence_missing')
        def evaluated(levels, stake):
            entry = F(fixed.get('flat_entry_usd', '0'))
            entry += F(_rounded(stake * F(fixed.get('entry_rate', '0')), 2), 100)
            reserve = F(fixed.get('reserve_usd', '0'))
            if entry < 0 or reserve < 0:
                raise ValueError('unit_fee_evidence_missing')
            return entry, reserve, fixed, []
        invariant = None
        settlement = row.get('settlement_assessment') or {}
        refund = (settlement.get('refund_cashflows') or {}).get('venue')
        state_rules = (settlement.get('venue_rules') or {}).get('cashflow_states') or {}
        if (not F(fixed.get('entry_rate', '0')) and refund != 'full_outlay'
                and 'full_outlay' not in state_rules.values()
                and not any(F(v) for k in ('settlement_fee_usd', 'settlement_rebate_usd')
                            for v in fixed.get(k, {}).values())):
            invariant = F(fixed.get('flat_entry_usd', '0'))
        return evaluated, evidence, invariant
    return retail_order(row, terms, cost, fee)


def _fill(terms, amount, cost, fees, payout):
    kind = terms['kind']
    step, minimum = F(terms['increment']), F(terms['minimum'])
    if not 0 < step <= minimum or minimum % step or not terms.get('revision'):
        raise ValueError('unit_order_constraints_unverified')
    limit = F(terms['maximum']) if terms.get('maximum') is not None else None
    if limit is not None and limit < minimum:
        raise ValueError('unit_fill_below_minimum')
    if kind == 'stake':
        if terms['order_type'] != 'straight_stake' or limit is None:
            raise ValueError('unit_order_constraints_unverified')
        levels = [(F(1), limit)]
    elif kind == 'exchange':
        asks = terms.get('asks') or ()
        if terms['order_type'] != 'taker' or not asks:
            raise ValueError('unit_fill_depth_unverified')
        levels = [(F(leg['price']), F(leg['quantity'])) for leg in asks]
        if (len(levels) > MAX_LEVELS or levels[0][0] != cost
                or any(not 0 < price < payout or size <= 0 for price, size in levels)
                or any(a[0] >= b[0] for a, b in zip(levels, levels[1:]))):
            raise ValueError('unit_fill_depth_conflict')
    else:
        raise ValueError('unit_order_constraints_unverified')

    depth = sum(size // step for _, size in levels)
    if depth * step < minimum:
        raise ValueError('unit_fill_depth_insufficient' if kind == 'exchange' else 'unit_fill_below_minimum')
    high = min(depth, amount // (levels[0][0] * step))
    if limit is not None:
        high = min(high, limit // step)
    if high * step < minimum:
        raise ValueError('unit_fill_below_minimum')

    def order(ticks, *, final=False):
        remaining = ticks
        legs = []
        for price, available in levels:
            use = min(remaining, available // step)
            if use:
                legs.append((price, use * step))
                remaining -= use
                if not remaining:
                    break
        stake = sum(price * quantity for price, quantity in legs)
        evaluate = fees if final else getattr(fees, 'sizing_bound', fees)
        entry, reserve, cash_terms, trace = evaluate(legs, stake)
        return stake + entry + reserve, legs, stake, entry, reserve, cash_terms, trace

    # Supported order schedules have nondecreasing committed cash on the legal grid.
    low = minimum // step
    best = order(low)
    if best[0] > amount:
        raise ValueError('unit_fill_below_minimum')
    while low < high:
        mid = (low + high + 1) // 2
        fill = order(mid)
        if fill[0] <= amount:
            low, best = mid, fill
        else:
            high = mid - 1
    tolerance = min(F(1), amount / 100)
    reason = None
    if amount - best[0] > tolerance:
        if limit is not None and (low + 1) * step > limit:
            reason = 'unit_fill_limit_insufficient'
        elif low == depth and kind == 'exchange':
            reason = 'unit_fill_depth_insufficient'
        else:
            reason = 'unit_fill_outside_tolerance'
    return order(low, final=True), reason


def _cash_state(state, *, ordinary_win, stake, committed, entry, reserve, fee_terms, settlement):
    rules = settlement.get('venue_rules') or {}
    basis = (rules.get('cashflow_states') or {}).get(state)
    if basis is None:
        basis = {'win': 'ordinary_win', 'loss': 'zero',
                 'refund': (settlement.get('refund_cashflows') or {}).get('venue')}.get(state)
    # A state may override the default payout with a reviewed fraction of stake.
    bases = {'ordinary_win': ordinary_win, 'zero': F(0), 'stake_only': stake,
             'full_outlay': committed - reserve}
    if isinstance(basis, dict) and basis.get('stake_fraction') is not None:
        fraction = F(basis['stake_fraction'])
        if not 0 <= fraction <= 1:
            raise ValueError('unit_settlement_cashflow_unverified')
        gross = stake * fraction
    elif basis in bases:
        gross = bases[basis]
    else:
        raise ValueError('unit_settlement_cashflow_unverified')
    if reserve:
        released = reserve * F(fee_terms['reserve_release'][state])
        if not 0 <= released <= reserve:
            raise ValueError('unit_settlement_cashflow_unverified')
    else:
        released = F(0)
    settlement_fee = F(fee_terms.get('settlement_fee_usd', {}).get(state, '0'))
    settlement_rebate = F(fee_terms.get('settlement_rebate_usd', {}).get(state, '0'))
    if min(settlement_fee, settlement_rebate) < 0:
        raise ValueError('unit_settlement_cashflow_unverified')
    entry_refund = entry if basis == 'full_outlay' else F(0)
    received = gross + released - settlement_fee + settlement_rebate
    return received, dict(gross_receipt_usd=wire(gross), reserve_returned_usd=wire(released),
        entry_fee_refunded_usd=wire(entry_refund), settlement_fee_usd=wire(settlement_fee),
        settlement_rebate_usd=wire(settlement_rebate),
        total_fee_usd=wire(entry - entry_refund + settlement_fee - settlement_rebate),
        net_receipt_usd=wire(received), net_profit_usd=wire(received - committed),
        net_return=wire((received - committed) / committed))


def valuation(row, amount, *, publication_id, snapshot_id):
    """Return one audit packet. All money and probabilities on the wire are exact strings."""
    from app.dashboard.current_contract import price
    from app.storage.store import hashed

    if amount is not None:
        amount = F(amount)
        if (amount * 100).denominator != 1:
            raise ValueError('Unit size requires cents precision')
        parse_amount(decimal_display(amount))
    reference = row.get('pregame_reference') or {}
    observed = reference if reference.get('available') else reference.get('observed_snapshot') or {}
    settlement = row.get('settlement_assessment') or {}
    terms = row.get('valuation_fill_terms') or {}
    fee = row.get('trade_fee') or {}
    source = row.get('source') or {}
    linked = row.get('sgo_native_contract') or {}
    native_ids = {key: linked.get(key) if linked.get('available') else source.get('native_' + key)
                  for key in ('event_id', 'market_id', 'outcome_id')}
    reasons = {}
    result = dict(version=VERSION, status='indicative', offer_id=row['id'], publication_id=publication_id,
        offer_snapshot_id=snapshot_id, member_result_id=row.get('evidence_result_id'),
        price_revision=row.get('price_revision'), economic_revision=row.get('economic_revision'),
        reference_snapshot_id=observed.get('snapshot_id'), reference=reference,
        settlement_revision=hashed(settlement) if settlement else None, settlement=settlement,
        fee_revision=hashed(fee['evidence']) if fee.get('evidence') else None,
        fee_evidence=fee.get('evidence'), fill_revision=terms.get('revision'),
        fill_evidence=terms.get('evidence'), evidence_class=terms.get('evidence_class', 'published'),
        bet_id=reference.get('bet_id'), canonical_game_id=row.get('game_key'),
        canonical_market=observed.get('market') or row.get('market'),
        canonical_selection=row.get('selection'), native_source=source, venue_native_ids=native_ids,
        venue=row['venue'], venue_type=terms.get('venue_type', 'marketplace'),
        offer=row.get('original'), source_clocks=row.get('times'), captured_at=row.get('captured_at'),
        quote_freshness=row.get('quote_freshness'),
        selected_usd=wire(amount), actual_outlay_usd=None, sizing_policy=SIZING,
        assumptions=row.get('estimate_assumptions', []),
        sizing_tolerance_usd=wire(min(F(1), amount / 100)) if amount is not None else None,
        fill=None, fees=None, states={}, raw={}, display={}, reasons=reasons)
    raw, shown = result['raw'], result['display']
    if not reference.get('available'):
        reasons['reference'] = reference.get('reason') or 'exact_reference_pair_unavailable'
    if not settlement.get('available'):
        venue_rule = settlement.get('venue_rules') or {}
        novig_fmv = venue_rule.get('void') == 'fair_market_value' and venue_rule.get('void_payout') is None
        reasons['settlement'] = ('settlement_novig_void_fair_value_unverified' if novig_fmv else
            settlement.get('venue_blocker') or settlement.get('reason') or 'venue_settlement_rules_unverified')
    if amount is None:
        reasons['size'] = 'unit_size_unset'
    elif not terms:
        reasons['fill'] = 'unit_fill_depth_unverified'

    try:
        cost = price(row)
        payout = F(row['original'].get('payout', '1'))
        if not 0 < cost < payout:
            raise ValueError
        posted_decimal = payout / cost
    except INPUT_ERRORS:
        reasons['offer'] = 'source_price_or_selection_unsupported'
        return result

    if reference.get('available') and settlement.get('comparable'):
        try:
            fair = F(reference['probability'])
            if not 0 < fair < 1:
                raise ValueError
            before = fair * posted_decimal - 1
            result['indicative_before_fee'] = dict(raw=wire(before), display=decimal_display(100 * before, signed=True) + '%',
                conditioning=reference.get('conditioning'), basis='posted_price_decisive_states', ranking_eligible=False)
        except INPUT_ERRORS:
            reasons['reference'] = 'unit_reference_probability_invalid'

    try:
        fees, evidence, invariant = _offer_fee(row, terms, cost)
        result['fee_evidence'] = evidence
        result['fee_revision'] = evidence.get('schedule_hash') or evidence.get('revision') or hashed(evidence)
        if invariant is not None:
            result['fees'] = dict(kind='fixed', total_usd=wire(invariant), basis='published_schedule')
            shown['fee'] = '$' + decimal_display(invariant)
    except INPUT_ERRORS as exc:
        reasons['fee'] = str(exc) if isinstance(exc, ValueError) and str(exc).startswith('unit_') else 'unit_fee_schedule_unverified'
        return result
    if amount is None or not terms:
        return result
    try:
        (committed, legs, stake, entry, reserve, fee_terms, trace), fill_reason = _fill(terms, amount, cost, fees, payout)
    except INPUT_ERRORS as exc:
        reason = str(exc) if isinstance(exc, ValueError) and str(exc).startswith('unit_') else 'unit_order_constraints_unverified'
        reasons['fee' if reason.startswith('unit_fee_') else 'fill'] = reason
        return result

    is_stake = terms['kind'] == 'stake'
    quantity = sum(q for _, q in legs)
    gross_win = stake * posted_decimal if is_stake else quantity * payout
    result.update(actual_outlay_usd=wire(committed), fill=dict(
        order_type=terms['order_type'], stake_usd=wire(stake),
        quantity=None if is_stake else wire(quantity),
        levels=[] if is_stake else [dict(price=wire(p), quantity=wire(q)) for p, q in legs],
        increment=terms['increment'], minimum=terms['minimum'], maximum=terms.get('maximum')))
    shown.update(selected_usd=decimal_display(amount), actual_outlay_usd=decimal_display(committed),
                 stake_usd=decimal_display(stake))
    if len(legs) > 1:
        raw['blended_decimal'] = wire(gross_win / stake)
        shown['blended_offer'] = american(gross_win / stake)
    if fill_reason:
        reasons['fill'] = fill_reason

    # Win/loss receipts may be known before the whole probability partition.
    probabilities = settlement.get('state_probabilities') or {}
    states = result['states']
    known_fees = set()
    for state in dict.fromkeys(('win', 'loss', *probabilities)):
        try:
            received, detail = _cash_state(state, ordinary_win=gross_win, stake=stake,
                committed=committed, entry=entry, reserve=reserve, fee_terms=fee_terms, settlement=settlement)
            states[state] = dict(detail, probability=probabilities.get(state),
                display_receipt_usd=decimal_display(received), display_fee_usd=decimal_display(F(detail['total_fee_usd'])))
            known_fees.add(F(detail['total_fee_usd']))
        except INPUT_ERRORS:
            if state == 'win':
                reasons['after_fee_odds'] = 'unit_settlement_cashflow_unverified'
            if state in probabilities:
                reasons['cashflows'] = 'unit_settlement_cashflow_unverified'
    fee_varies = len(known_fees) > 1
    complete_fees = settlement.get('available') and probabilities and set(states) == set(probabilities)
    result['fees'] = dict(kind='varies' if fee_varies else 'fixed' if complete_fees or invariant is not None else 'entry_only',
        total_usd=wire(next(iter(known_fees))) if complete_fees and len(known_fees) == 1 else wire(invariant),
        entry_usd=wire(entry), reserve_usd=wire(reserve), rounding_trace=trace,
        cash_terms=fee_terms or None, basis='actual_fill')
    shown['fee'] = ('Varies' if fee_varies else '$' + decimal_display(F(result['fees']['total_usd']))
                    if result['fees']['total_usd'] is not None else None)
    if 'win' in states and not fill_reason:
        effective = F(states['win']['net_receipt_usd']) / committed
        raw['after_fee_decimal'] = wire(effective)
        shown['after_fee_odds'] = american(effective)
        if shown['after_fee_odds'] is None:
            shown['after_fee_decimal'] = decimal_display(effective, 4)
            reasons['after_fee_odds'] = 'unit_after_fee_american_undefined'
    if not probabilities:
        if settlement.get('available'):
            reasons['probabilities'] = 'unit_state_probabilities_invalid'
        return result
    if set(reasons) - {'after_fee_odds'}:
        return result
    try:
        p = {state: F(probability) for state, probability in probabilities.items()}
        if (set(states) != set(p) or not {'win', 'loss'} <= p.keys() or
                any(v < 0 for v in p.values()) or sum(p.values()) != 1):
            raise ValueError
        ratios = {state: F(states[state]['net_return']) for state in p}
        ev = sum(p[state] * ratios[state] for state in p)
        opportunity = score(p, ratios, ev)
    except INPUT_ERRORS:
        reasons['probabilities'] = 'unit_state_probabilities_invalid'
        return result
    raw.update(expected_net_profit_usd=wire(committed * ev), net_ev=wire(ev), opportunity_score=wire(opportunity))
    shown.update(expected_net_profit_usd=decimal_display(committed * ev), net_ev=decimal_display(100 * ev, signed=True) + '%',
                 opportunity_score=decimal_display(opportunity, 0))
    result['status'] = 'qualified'
    return result


def drawer_order(results):
    def key(result):
        qualified = result['status'] == 'qualified'
        ev = F(result['raw']['net_ev']) if qualified else F(0)
        return not qualified, -ev, result['venue'], result['offer_id']

    return sorted(results, key=key)


def _board_sort_key(result, *, highest_ev=False):
    first, second = ('net_ev', 'opportunity_score') if highest_ev else ('opportunity_score', 'net_ev')
    return -F(result['raw'][first]), -F(result['raw'][second]), result['bet_id']


def board_order(results, *, highest_ev=False, include_alternatives=False):
    """Rank positive EV bets, optionally retaining offers for scoped venue selection."""
    best = {}
    for result in drawer_order(results):
        if (result['status'] == 'qualified' and result['venue_type'] == 'marketplace' and result['bet_id']
                and F(result['raw']['net_ev']) > 0):
            identity = (result['bet_id'], result['offer_id']) if include_alternatives else result['bet_id']
            best.setdefault(identity, result)
    return sorted(best.values(), key=lambda result: _board_sort_key(result, highest_ev=highest_ev))


def fair_odds(reference):
    value = reference['fair_decimal_odds']
    return dict(american=american(F(value)), decimal=value, reason=None)
