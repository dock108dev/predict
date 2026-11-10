"""Single-fill Novig v3 evidence; no aggregate-to-native identity inference."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from .current_dependencies import instant

URL = 'https://docs.novig.com/api/concepts/fees'


def live_fee(row, at, evidence):
    def missing(reason):
        return dict(available=False, classification='partial', reason=reason, evidence=None)
    if not isinstance(evidence, dict):
        return missing('novig_native_market_phase_and_book_missing')
    source = row.get('source') or {}
    identity = evidence.get('identity') or {}
    expected = dict(event_id=source.get('native_event_id'), market_id=source.get('native_market_id'),
                    outcome_id=source.get('native_outcome_id'), side=source.get('native_side'),
                    period=(row.get('market') or {}).get('period'), line=(row.get('market') or {}).get('line'))
    if source.get('provider') != 'novig' or any(k not in identity or identity[k] != expected[k] or (k != 'line' and expected[k] is None) for k in expected):
        return missing('novig_exact_offer_identity_conflict')
    if (evidence.get('fill_count') != 1 or evidence.get('price_levels') != 1
            or not isinstance(evidence.get('available_native_contracts'), int)
            or isinstance(evidence.get('available_native_contracts'), bool)
            or evidence['available_native_contracts'] < 100):
        return missing('novig_single_price_fill_evidence_missing')
    fee = evidence.get('market_fee')
    if not isinstance(fee, dict) or set(fee) != {'coefficient', 'makerCredit', 'charged'} or fee.get('charged') not in ('WHEN_LIVE', 'ALWAYS'):
        return missing('novig_native_market_fee_missing_or_conflicting')
    # Receipt time and a public book sequence are not a lifecycle witness.
    # Only the ordered, gap-free signed stream can currently establish this
    # cross-channel boundary; public cached snapshots must remain uncovered.
    proof = evidence.get('reset_proof') or {}
    transition = proof.get('transition') or {}
    book = proof.get('book') or {}
    if (proof.get('transport') != 'novig_v3_signed_stream' or proof.get('continuous') is not True
            or not proof.get('generation') or proof.get('event_id') != expected['event_id']
            or proof.get('market_id') != expected['market_id']
            or transition.get('kind') != 'GOLIVE' or transition.get('status') != 'OPEN'
            or not isinstance(transition.get('seq'), int) or not isinstance(book.get('seq'), int)
            or not isinstance(transition.get('position'), int) or not isinstance(book.get('position'), int)
            or book['position'] <= transition['position'] or book.get('kind') != 'snapshot'
            or transition.get('received_at') != evidence.get('last_book_reset_at')
            or book.get('received_at') != evidence.get('quote_at')):
        return missing('novig_post_reset_sequence_evidence_missing')
    frames = proof.get('frames')
    if not isinstance(frames, list) or not 2 <= len(frames) <= 2048:
        return missing('novig_post_reset_sequence_evidence_missing')
    try:
        positions = [f['position'] for f in frames]
        changes = frames[0]['lifecycle']['deltas']
        if (any(not isinstance(p, int) or isinstance(p, bool) for p in positions)
                or positions != sorted(set(positions)) or any(f['market_id'] != expected['market_id'] for f in frames)
                or frames[0]['position'] != transition['position']
                or frames[0]['lifecycle']['seq'] != transition['seq']
                or not changes or changes[-1] != {'kind':'GOLIVE','status':'OPEN'}):
            return missing('novig_post_reset_sequence_evidence_missing')
        snapshots = [f for f in frames if 'book' in f and f['position'] == book['position']]
        if len(snapshots) != 1 or snapshots[0]['book'] != proof.get('source_book'):
            return missing('novig_post_reset_sequence_evidence_missing')
        if book.get('source_at') is not None and (
                type(book.get('nonce')) is not int or book['nonce'] <= 1
                or snapshots[0].get('nonce') != book['nonce']
                or instant(book['source_at']) > instant(book['received_at'])
                or instant(book['received_at'])-instant(book['source_at']) > timedelta(seconds=15)):
            return missing('novig_post_reset_sequence_evidence_missing')
        life_seq = transition['seq']
        for frame in frames[1:]:
            if 'lifecycle' in frame:
                item = frame['lifecycle']
                if item['seq'] != life_seq + 1 or any(d.get('kind') in ('GOLIVE','UNLIVE','CLOSE','END','GRADE') for d in item['deltas']):
                    return missing('novig_post_reset_sequence_evidence_missing')
                life_seq = item['seq']
        if frames[-1]['position'] != book['position']:
            return missing('novig_post_reset_sequence_evidence_missing')
    except (KeyError, TypeError, ValueError):
        return missing('novig_post_reset_sequence_evidence_missing')
    market = evidence.get('native_market') or {}
    event = evidence.get('native_event') or {}
    snapshot = proof.get('source_book') or {}
    outcomes = market.get('outcomes') or []
    try:
        ids = [item['outcomeId'] for item in outcomes]
        family = (row.get('market') or {}).get('market')
        if (expected['period'] != 'full_game' or expected['side'] != 'buy'
                or market.get('marketType') != {'winner':'MONEY','spread':'SPREAD','total':'TOTAL'}.get(family)
                or market.get('status') != 'OPEN'
                or (family == 'winner' and (expected['line'] is not None or market.get('strike') is not None))
                or (family in ('spread','total') and Decimal(str(expected['line'])) != Decimal(str(market.get('strike'))))):
            return missing('novig_native_source_identity_conflict')
        if (event.get('eventId') != expected['event_id'] or event.get('status') != evidence.get('event_status')
                or market.get('eventId') != expected['event_id'] or market.get('marketId') != expected['market_id']
                or market.get('fee') != fee or len(ids) != 2 or len(set(ids)) != 2
                or expected['outcome_id'] not in ids or snapshot.get('marketId') != expected['market_id']
                or snapshot.get('seq') != book['seq']):
            return missing('novig_native_source_identity_conflict')
        other = next(x for x in ids if x != expected['outcome_id'])
        orders = snapshot['orders'][other]
        # The first resting order alone must fill the modeled quantity: two
        # orders at one price can still be two fills with independent rounding.
        first = orders[0]
        if (not isinstance(first['qty'], int) or isinstance(first['qty'], bool) or first['qty'] < 100
                or first['qty'] != evidence['available_native_contracts']
                or Decimal('1') - Decimal(first['price']) != Decimal(evidence['price'])):
            return missing('novig_single_price_fill_evidence_missing')
    except (KeyError, IndexError, TypeError, ValueError, InvalidOperation, ArithmeticError):
        return missing('novig_native_source_identity_conflict')
    state = evidence.get('event_status')
    if state not in ('OPEN_PREGAME', 'OPEN_INGAME', 'DELAYED'):
        return missing('novig_event_phase_missing_or_conflicting')
    # Only the current, directly observed phase may govern this hypothetical fill.
    if state != 'OPEN_INGAME':
        return missing('novig_event_phase_conflicts_with_live_offer')
    try:
        quote_at = instant(evidence['quote_at'])
        phase_at = instant(evidence['phase_at'])
        terms_at = instant(evidence['terms_at'])
        reset_at = instant(evidence['last_book_reset_at'])
        deadline = min(quote_at, phase_at, terms_at) + timedelta(seconds=15)
        if max(quote_at, phase_at, terms_at, reset_at) > at or at > deadline:
            return missing('novig_live_evidence_stale_or_future')
        if quote_at <= reset_at or phase_at < reset_at:
            return missing('novig_fresh_quote_required_after_book_reset')
        price = Decimal(str(evidence['price']))
        coefficient = Decimal(str(fee['coefficient']))
        credit = Decimal(str(fee['makerCredit']))
        if not all(x.is_finite() for x in (price, coefficient, credit)) or not 0 < price < 1 or coefficient < 0 or not 0 <= credit <= 1:
            raise ValueError('invalid values')
        # Compare the acquired-side price against the quote, not an opposite side.
        original = row['original']
        if original['units'] == 'decimal_odds':
            quoted = Decimal(1) / Decimal(str(original['value']))
        elif original['units'] == 'usd_per_contract':
            quoted = Decimal(str(original['value']))
        else:
            raise ValueError('unsupported quote units')
        if abs(quoted - price) > Decimal('0.000000000001'):
            return missing('novig_quote_price_conflict')
        amount = (coefficient * price * (1-price)).quantize(Decimal('.00001'), rounding=ROUND_HALF_UP)
    except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError):
        return missing('novig_live_evidence_incomplete')
    captured = dict(version='Novig v3 market fee', source_url=URL,
        reviewed_at=min(quote_at, phase_at, terms_at).isoformat(), review_before=deadline.isoformat(),
        applicability='Exact market and observed event state; one immediate taker fill',
        native=deepcopy(evidence))
    return dict(available=True, classification='exact_public', reason=None, evidence=captured,
        profile='manual_retail', liquidity_role='taker', fill_count=1, quantity='100',
        quantity_unit='Novig native contracts (one-cent payout each)', trade_fee_usd=str(amount),
        fee_payment='at_fill', fee_cashflows=dict(at_fill_usd=str(amount)),
        holding_assumption='Hold the standalone $1 payout claim to settlement',
        assumptions=['100 native one-cent contracts equal one $1-payout claim.',
                     'One immediate fill at the displayed price; multi-price fills are not modeled.'])


def live_metric(row, fee, witnesses):
    """Conditional decisive-outcome benchmark; never infer full settlement EV."""
    from fractions import Fraction
    from .cashflows import exact_wire as wire
    from .snapshot_fee_scope import RANKING_BASIS
    reference = row.get('reference_calculation') or {}
    benchmark = row.get('snapshot_benchmark') or {}
    missing = dict(available=False, reason='novig_live_exact_reference_or_settlement_missing')
    if not fee.get('available'):
        return dict(available=False, reason=fee.get('reason') or 'novig_native_market_phase_and_book_missing')
    if (not reference.get('available') or reference.get('venue') != 'pinnacle'
            or len(witnesses) != 2 or len({w.get('dependency') for w in witnesses}) != 2
            or not all(w.get('dependency') and not w.get('reasons')
                       and w.get('lifecycle', {}).get('state') == 'live' for w in witnesses)
            or not benchmark.get('selected_identity') or not benchmark.get('selected_predicate')
            or row.get('probability') is None or row.get('gross_return_percent') is None
            or row.get('cost_per_normal_claim') is None):
        return missing
    try:
        p = Fraction(row['probability']); cost = Fraction(row['cost_per_normal_claim'])
        charge = Fraction(fee['trade_fee_usd']); risk = cost + charge
        if not 0 < p < 1 or not 0 < cost < 1 or risk <= 0:
            return missing
        value = (p-risk)/risk
        return dict(available=True, classification='novig_v3_live_single_fill', ranking_basis=RANKING_BASIS,
            trade_fee_usd=wire(charge), normalization_risk_usd=wire(risk), normal_win_receipt_usd='1',
            scenario_net_usd=wire(p-risk), net_per_dollar_risk=wire(value), return_percent=wire(100*value),
            selected_decisive_probability=wire(p), quantity='1', quantity_unit='USD normal claim',
            liquidity_role='taker', fill_count=1, fee_payment='at_fill', evidence=deepcopy(fee['evidence']),
            condition='One immediate taker fill; exact Pinnacle benchmark is conditional on decisive settlement.',
            exclusions=['pushes', 'voids', 'cancellations', 'multi-price fills'],
            meaning='Conditional decisive-outcome benchmark; not full-outcome EV or a guaranteed fill.')
    except (KeyError, ValueError, TypeError, ArithmeticError):
        return missing
