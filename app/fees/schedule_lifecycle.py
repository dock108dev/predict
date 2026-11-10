"""Approved public manual-retail terms and prospective verification receipts."""
from datetime import timezone
from fractions import Fraction
import json
from pathlib import Path

from psycopg.types.json import Jsonb

from app.storage.store import hashed, stamp

VENUE = 'prophetx'
SOURCE_URL = 'https://www.prophetx.co/lobby/t-c/trading-fees'
APPROVAL = Path(__file__).resolve().parents[1] / 'fixtures/prophetx-public-straight-approved.json'
REVIEW_REQUIRED = 'public_fee_schedule_review_required'
SCOPE = 'Public retail straight contracts. NHL fees apply per fill. Other events use positive net gains per market.'


def read(db):
    row = db.execute('SELECT state FROM public_fee_schedule WHERE venue=%s', (VENUE,)).fetchone()
    return row['state'] if row else None


def write(db, state):
    db.execute('''INSERT INTO public_fee_schedule VALUES (%s,%s)
        ON CONFLICT(venue) DO UPDATE SET state=excluded.state''', (VENUE, Jsonb(state)))


def validate_rules(rules):
    defaults = 0
    keys = set()
    versions = set()
    for rule in rules:
        market = rule['market_id']
        effective = rule['effective_from']
        if effective is not None and not isinstance(effective, str):
            raise ValueError('invalid_effective_time')
        if market is not None and (not isinstance(market, str) or not market or effective is None):
            raise ValueError('unbound_market_override')
        defaults += market is None and effective is None
        key = (market, stamp(effective) if effective else None)
        if key in keys or rule['version'] in versions:
            raise ValueError('conflicting_approved_rules')
        keys.add(key)
        versions.add(rule['version'])
        terms = rule['terms']
        for field in ('fee_rate', 'nhl_taker_coefficient', 'nhl_maker_coefficient'):
            if not 0 <= Fraction(terms[field]) <= 1:
                raise ValueError('invalid_fee_rate')
        for field, value in {
            'nhl_rounding': 'half_up_cent_with_order_carry',
            'nhl_fee_timing': 'fill',
            'nhl_market_order_funding': 'fee_from_entered_amount',
            'commission_basis': 'positive_net_gains_per_market',
            'commission_timing': 'winning_settlement_for_standalone_position',
            'schedule_application': 'order_placement',
        }.items():
            if terms[field] != value:
                raise ValueError('fee_terms_require_model_review')
    if not defaults and not any(rule['market_id'] is None for rule in rules):
        raise ValueError('missing_default_schedule')


def approved():
    document = json.loads(APPROVAL.read_bytes())
    if (document['venue'], document['profile'], document['product'], document['source_url']) != (
            VENUE, 'manual_retail', 'straight_contract', SOURCE_URL):
        raise ValueError('unsupported_public_fee_scope')
    validate_rules(document['rules'])
    return document


def revision(state):
    if not state:
        return None
    verified = state.get('last_verified') or {}
    review = state.get('review_required') or {}
    return hashed([verified.get('approval_id'), review.get('approval'), review.get('reason')]) if verified or review else None


def publication_revision(state):
    if not state:
        return None
    verified = state.get('last_verified') or {}
    return hashed([revision(state), verified.get('revision')]) if verified or state.get('review_required') else None


def boundaries(state, at):
    verified = (state or {}).get('last_verified')
    if not verified:
        return []
    return [value for value in [verified['review_before'],
            *(rule['effective_from'] for rule in verified['approval']['rules'])]
            if value and stamp(value) > at]


def _rules(verified, at, market_id):
    relevant = [rule for rule in verified['approval']['rules']
                if rule['market_id'] is None or rule['market_id'] == market_id]
    active = [rule for rule in relevant if not rule['effective_from'] or stamp(rule['effective_from']) <= at]
    future = [stamp(rule['effective_from']) for rule in relevant
              if rule['effective_from'] and stamp(rule['effective_from']) > at]
    def precedence(rule):
        return (rule['market_id'] is not None, rule['effective_from'] is not None,
                stamp(rule['effective_from']) if rule['effective_from'] else None)
    cutover = min(future, default=None)
    return (max(active, key=precedence, default=None),
            cutover.astimezone(timezone.utc).isoformat() if cutover else None)


def basis(state, at, market_id=None):
    """Resolve exact-market overrides before the public default at order time."""
    verified = (state or {}).get('last_verified')
    if not verified or at < stamp(verified['verified_at']):
        return None
    approval = verified['approval']
    rule, cutover = _rules(verified, at, market_id)
    if rule is None:
        return None
    deadline = min(verified['review_before'], cutover, key=stamp) if cutover else verified['review_before']
    receipt = verified['retrieval']
    return dict(version=rule['version'], sha256=receipt['document']['sha256'],
        source_url=approval['source_url'], document_url=approval['document_url'],
        reviewed_at=verified['verified_at'], review_before=deadline,
        verification_deadline=verified['review_before'], published_version=approval['published_version'],
        published_update=approval['published_update'], published_effective_from=rule['effective_from'],
        effective_from=(stamp(rule['effective_from']).astimezone(timezone.utc).isoformat()
                        if rule['effective_from'] else verified['verified_at']),
        effective_time_basis='published_cutover' if rule['effective_from'] else 'prospective_verification',
        next_change_at=cutover, market_override=rule['market_id'],
        applicability=SCOPE, profile=approval['profile'], product=approval['product'],
        schedule_revision=revision(state), verification_revision=verified['revision'], retrieval=receipt,
        **rule['terms'],
        **({'unavailable_reason': REVIEW_REQUIRED} if state.get('review_required') else {}))


def for_offer(state, row, at, *, fallback=None):
    if row['venue'] != VENUE:
        return None
    market = (row.get('source') or {}).get('native_market_id')
    model = basis(state, at, market.removeprefix('alternate:') if market else None)
    if model is not None:
        return model
    if state and state.get('review_required'):
        if fallback is None:
            from app.comparison.conditional_benchmark import basis as legacy_basis
            fallback = legacy_basis(VENUE, at=at)
        return dict(fallback, unavailable_reason=REVIEW_REQUIRED)
    return fallback


def summary(state, at):
    verified = (state or {}).get('last_verified')
    changes = [rule for rule in (verified or {}).get('approval', {}).get('rules', ())
               if rule['effective_from'] and stamp(rule['effective_from']) > at]
    next_change = min(changes, key=lambda rule: stamp(rule['effective_from']), default=None)
    review = (state or {}).get('review_required')
    terms = basis(state, at)
    return dict(venue=VENUE, profile='manual_retail', source_url=SOURCE_URL,
        state='review_required' if review else 'verified' if terms and at < stamp(terms['review_before'])
            else 'scheduled' if verified and not terms and next_change and at < stamp(verified['review_before'])
            else 'expired' if verified else 'awaiting_verification',
        terms=terms, last_verified_at=verified['verified_at'] if verified else None,
        review_before=verified['review_before'] if verified else None,
        refresh=(state or {}).get('last_attempt'), next_refresh_at=(state or {}).get('next_attempt_at'),
        next_change=next_change, review_required=review)
