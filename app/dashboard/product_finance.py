"""Eligibility for product calculations and projection of retained proofs."""
from fractions import Fraction

from app.comparison.cashflows import exact_wire
from app.comparison.sgo_reference import BEST_BOOKS, BEST_VERSION, NAMED_VERSION, VERSION
from app.comparison.snapshot_fee_outcome import outcome
from app.storage.store import stamp


REFERENCE_UNAVAILABLE = 'eligible_reference_unavailable'
EV_UNQUALIFIED = 'ev_calibration_or_settlement_unverified'
REFERENCE_METHODS = {BEST_VERSION, NAMED_VERSION, VERSION}


def excluded_reference(row):
    """Identify legacy reference authority, including compact publication rows."""
    authority = row.get('current_authority') or {}
    if authority.get('exact_pinnacle_reference') or row.get('exact_pinnacle_reference_current'):
        return True
    reference = row.get('reference_calculation') or {}
    if reference.get('venue') == 'pinnacle' or any(
            item.get('venue') == 'pinnacle' for item in reference.get('contributors') or ()):
        return True
    benchmark = row.get('snapshot_benchmark') or row.get('reference') or {}
    if benchmark.get('bookmaker') == 'pinnacle':
        return True
    return any('pinnacle' in str(message).casefold() for message in (
        row.get('probability_missing'), row.get('snapshot_benchmark_reason'), row.get('snapshot_benchmark_missing'),
        (row.get('conditional_trade_benchmark') or {}).get('detail')))


def reference_allowed(row):
    reference = row.get('reference_calculation') or {}
    if not reference.get('available') or excluded_reference(row):
        return False
    return (reference.get('method') in REFERENCE_METHODS
            and reference.get('venue') in (*BEST_BOOKS, 'sportsgameodds_books'))


def qualified_ev(row):
    """The return needs a calibrated confidence bound and full cashflows."""
    if row.get('conditional_return_percent') is None or not reference_allowed(row):
        return False
    model = row.get('conditional_trade_benchmark') or {}
    reference = row['reference_calculation']
    try:
        confidence = Fraction(model['verified_confidence'])
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False
    return bool(model.get('available') and model.get('ranking_eligible') and model.get('calibrated')
                and model.get('execution_qualified') and model.get('full_state_net_ev')
                and reference.get('full_state_probability') and reference.get('venue') in BEST_BOOKS
                and effective_quote(row) is not None and Fraction(99, 100) <= confidence <= 1)


def effective_quote(row):
    """Use funding and winning net receipt from the verified fill model."""
    fee = row.get('trade_fee') or {}
    if not (row.get('price_current') and fee.get('available') and fee.get('execution_qualified')
            and fee.get('classification') in ('account_reviewed', 'exact_public')):
        return None
    try:
        funding = Fraction(fee['funding_usd'])
        receipt = Fraction(fee['winning_net_receipt_usd'])
        if funding <= 0 or receipt <= funding:
            return None
        return dict(decimal_odds=exact_wire(receipt / funding), funding_usd=exact_wire(funding),
                    winning_net_receipt_usd=exact_wire(receipt), quantity=fee['quantity'],
                    quantity_unit=fee['quantity_unit'], liquidity_role=fee['liquidity_role'],
                    fill_count=fee['fill_count'])
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None


def retained_novig_fee(row, captured_at):
    """Recover only a reviewed zero charge at the archive's exact clock and size."""
    model = row.get('conditional_trade_benchmark') or {}
    evidence = model.get('evidence') or {}
    if (row['venue'] != 'novig' or not row.get('price_current') or row.get('trade_fee') is not None
            or row.get('game_state') != 'scheduled' or not model.get('available')
            or model.get('source_times') != row.get('times') or model.get('trade_fee_usd') != '0'
            or model.get('liquidity_role') != 'taker' or model.get('fill_count') != 1
            or model.get('quantity') != '1' or model.get('quantity_unit') != 'USD normal claim'):
        return None
    from app.comparison.conditional_benchmark import basis

    try:
        at = stamp(captured_at)
        review = basis('novig', at=at)
        if (any(review[key] != evidence.get(key) for key in ('version', 'sha256', 'reviewed_at', 'review_before'))
                or stamp(row['start_at']) <= at
                or not 0 < Fraction(model['normalization_risk_usd']) == 1 / Fraction(row['original']['value'])
                or Fraction(model['normal_win_receipt_usd']) != 1):
            return None
        fee = outcome(row, at=at, phase='scheduled', review=review)
    except (OSError, KeyError, TypeError, ValueError, ArithmeticError):
        return None
    if fee['available'] and fee['trade_fee_usd'] == '0':
        return dict(fee, classification='recorded_scope',
                    assumptions=['Saved aggregate pregame straight scenario at this capture and size.'])
    return None


def visible_row(row):
    """Remove legacy financial derivatives while preserving exact venue terms."""
    if not excluded_reference(row):
        authority = row.get('current_authority') or {}
        if 'exact_pinnacle_reference' not in authority and 'exact_pinnacle_reference_current' not in row:
            return row
        row = dict(row)
        row.pop('exact_pinnacle_reference_current', None)
        if 'exact_pinnacle_reference' in authority:
            row['current_authority'] = {key: value for key, value in authority.items()
                                        if key != 'exact_pinnacle_reference'}
        return row
    from app.storage.ordinary_projection import without_finance

    row = without_finance(row, REFERENCE_UNAVAILABLE)
    row.update(snapshot_benchmark=None, reference=None, reference_odds=None,
               snapshot_benchmark_reason=REFERENCE_UNAVAILABLE,
               snapshot_benchmark_missing=None,
               reference_calculation=dict(available=False, reason=REFERENCE_UNAVAILABLE),
               minimum_return_percent=None)
    if row.get('current_authority'):
        row['current_authority'] = {k: v for k, v in row['current_authority'].items()
                                    if k not in ('exact_pinnacle_reference', 'references')}
    for field in ('benchmark_quote', 'benchmark_diagnostics', 'input_basis', 'exact_pinnacle_reference_current'):
        row.pop(field, None)
    return row


def visible_assumptions(assumptions):
    return dict(assumptions, benchmark_venue=None) if assumptions.get('benchmark_venue') == 'pinnacle' else assumptions


def visible_publication(publication):
    sources = publication.get('sources') or {}
    return dict(publication, sources={key: value for key, value in sources.items() if key != 'pinnacle'})


def visible_original(row):
    """Keep the selected venue record and remove archived attached reference prices."""
    fields = ('benchmark_quote', 'snapshot_benchmark', 'reference', 'reference_odds',
              'sharp_reference', 'reference_calculation', 'comparison_input_refs', 'input_basis')
    row = {key: value for key, value in row.items() if key not in fields}
    if record := row.get('original_record'):
        quote = record.get('quote') or {}
        row['original_record'] = dict(record, quote={k: v for k, v in quote.items() if k not in fields})
    return row
