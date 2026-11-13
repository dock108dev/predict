"""Standalone trading fees for the ordinary desk's normalized trade profile."""
from .conditional_benchmark import basis, reviewed_fee
from app.fees.evidence import applies

VENUES = ('kalshi', 'polymarket_us', 'novig', 'prophetx')
FAMILIES = ('winner', 'spread', 'total')
CLASSES = ('exact_public', 'conservative', 'account_reviewed', 'partial', 'unknown')
EXPIRED = 'conditional_fee_review_expired_or_not_effective'


def unavailable(reason, *, evidence=None):
    return dict(available=False, classification='partial' if evidence else 'unknown',
                reason=reason, evidence=evidence)


def reviews(at):
    """Verify each schedule once per captured component."""
    results = {}
    for venue in VENUES:
        try:
            results[venue] = basis(venue, at=at)
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
            results[venue] = None
    return results


def outcome(row, *, at, phase, review):
    venue = row['venue']
    if phase == 'live' and venue == 'novig':
        from .snapshot_novig_live import live_fee
        return live_fee(row, at, row.get('novig_v3_evidence'))
    live_supported = venue in ('kalshi', 'polymarket_us') or (
        venue == 'prophetx' and row['source']['provider'] == 'sportsgameodds')
    if phase != 'scheduled' and not (phase == 'live' and live_supported):
        return unavailable('live_market_fee_evidence_unbound' if phase == 'live' else 'fee_game_phase_unverified')
    if row['market']['market'] not in FAMILIES or (venue != 'polymarket_us' and row['market']['period'] != 'full_game'):
        return unavailable('fee_straight_market_scope_unbound')
    if review is None:
        return unavailable('fee_schedule_evidence_unavailable')
    evidence = {key: review[key] for key in (
        'version', 'sha256', 'source_url', 'reviewed_at', 'review_before', 'applicability', 'fee_rate')}
    if review.get('path'):
        evidence['path'] = review['path']
    for key in ('document_url', 'published_version', 'published_update', 'published_effective_from', 'effective_from',
                'effective_time_basis', 'verification_deadline', 'next_change_at', 'market_override', 'schedule_revision',
                'retrieval', 'review_basis', 'product', 'verification_revision', 'standing_public_terms',
                'recheck_due_at', 'verification_scope', 'nhl_taker_coefficient', 'nhl_maker_coefficient',
                'nhl_rounding', 'commission_basis'):
        if key in review:
            evidence[key] = review[key]
    if review.get('unavailable_reason'):
        return unavailable(review['unavailable_reason'], evidence=evidence)
    if not applies(review, at):
        return unavailable(EXPIRED, evidence=evidence)

    if venue == 'kalshi':
        from .snapshot_conservative import kalshi_public_fee
        model = kalshi_public_fee(row, at=at.isoformat(), review=review)
        classification = 'conservative'
    elif venue == 'polymarket_us' and (phase == 'live' or review.get('profile')):
        from .snapshot_polymarket_fee import public_fee
        model = public_fee(row, at=at, phase=phase, review=review)
        classification = 'conservative'
    elif venue == 'prophetx':
        from .snapshot_conservative import prophetx_public_fee
        model = prophetx_public_fee(row, at=at.isoformat(), review=review, phase=phase)
        classification = 'conservative'
    else:
        model = reviewed_fee(row, at=at, event={'start_at': row['start_at']}, group=row['market'], review=review)
        classification = 'exact_public'
    if not model['available']:
        return unavailable(model['reason'], evidence=evidence)

    evidence['review_before'] = model['evidence']['review_before']
    if venue == 'kalshi':
        for key in ('series_id', 'event_id', 'metadata_revision'):
            if key in model['evidence']:
                evidence[key] = model['evidence'][key]
    elif venue == 'polymarket_us':
        for key in ('coefficient', 'order_inserted_at', 'phase', 'market_id', 'instrument_id',
                    'native_side', 'acquired_price_usd'):
            if key in model['evidence']:
                evidence[key] = model['evidence'][key]
    payment = model.get('fee_payment', 'at_fill')
    amount = model['trade_fee_usd']
    cashflows = (dict(at_fill_usd='0', winning_settlement_usd=amount, losing_settlement_usd='0')
                 if payment == 'commission_deducted_from_winning_market_gains'
                 else dict(at_fill_usd=amount))
    return dict(available=True, classification=classification, reason=None, evidence=evidence,
                profile='manual_retail', liquidity_role=model['liquidity_role'], fill_count=model['fill_count'],
                quantity=model['quantity'], quantity_unit=model['quantity_unit'],
                trade_fee_usd=amount, fee_payment=payment, fee_cashflows=cashflows,
                holding_assumption='Hold the standalone claim to settlement',
                assumptions=model.get('assumptions', []))
