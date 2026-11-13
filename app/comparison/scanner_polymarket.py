"""Polymarket US direct standard-sports Scanner evidence and entry costs."""

from datetime import datetime, timezone
from fractions import Fraction
from functools import lru_cache
import re
from zoneinfo import ZoneInfo

from app.collection.public_contracts import load
from app.fees.evidence import applies
from app.fees.product_schedules import approved, for_offer

from .conditional_benchmark import rounded_cents
from .current_dependencies import instant
from .net_costs import wire
from .scanner_native import NativeEvidenceError
from .snapshot_polymarket_fee import PROFILE, STANDARD_TIERS, URL


PRODUCT = 'polymarket_us:standard_sports'
EFFECTIVE_FROM = '2026-11-11T18:00:00Z'
FRACTIONAL = 'https://docs.polymarket.us/learn/trading/basics/fractional-shares'
COLLATERAL = 'https://docs.polymarket.us/market-structure/collateral-and-margin'
SETTLEMENT = 'https://docs.polymarket.us/learn/markets/contract-settlement'
CLEARING = ('https://polymarketexchange.com/files/clearing-notices/'
            'Clearinghouse%20Notice%20-%20Fees%20(2026.05.18).pdf')
CLEARING_SHA256 = 'b9ec50389b3c10bb2920ad409da63f043f07ccaf5b201b01b6fc88cf8e1e7ac6'
RULEBOOK = 'https://polymarketexchange.com/files/legal/latest/rulebook'
ORIGINAL_START = re.compile(r'scheduled for ([A-Z][a-z]+ \d{1,2}, \d{4}) at (\d{1,2}:\d{2}[AP]M) ET '
                            r'\(as of the listing of the event\x27s first instrument\)\.', re.ASCII)
FAIR_MARK = ('If the game is delayed, postponed, suspended or otherwise rescheduled to a date and time '
             'not within two days of the originally scheduled date and time, the market will settle '
             'to the last fair market price.')
TIE = re.compile(r'If the game ends in a tie, the market will settle to \$(0(?:\.\d+)?|1(?:\.0+)?)\.', re.ASCII)
NORMAL_FAMILIES = {'winner': 'moneyline', 'spread': 'spread', 'total': 'total'}
MINIMUM_PRICE = Fraction(1, 100)
MAXIMUM_PRICE = Fraction(99, 100)


@lru_cache(maxsize=1)
def _schedule_hashes():
    review = approved(PRODUCT)
    return {review[key] for key in ('normalized_sha256', 'alternate_normalized_sha256') if review.get(key)}


def _fee_review(review, at):
    if not isinstance(review, dict):
        raise NativeEvidenceError('polymarket_scanner_fee_review_missing')
    if 'last_verified' in review:
        review = for_offer({PRODUCT: review}, {'venue': 'polymarket_us'}, at)
    if (not review or not review.get('reviewed_at') or not applies(review, at)
            or review.get('unavailable_reason') or at < instant(EFFECTIVE_FROM)
            or review.get('profile') != PROFILE or review.get('fee_rate') != STANDARD_TIERS[0]
            or review.get('product') != 'standard_sports' or not review.get('verification_revision')
            or (review.get('retrieval') or {}).get('normalized_sha256') not in _schedule_hashes()):
        raise NativeEvidenceError('polymarket_scanner_fee_review_unavailable')
    return review


def _market(quote, evidence):
    source = quote['source']
    side = source.get('native_side')
    market_id, outcome_id = (source.get(field) for field in ('native_market_id', 'native_outcome_id'))
    native_key = ['polymarket_us', source.get('native_event_id'), market_id, outcome_id, side]
    listing = evidence.get('public_retail_observation') or {}
    event, group = evidence['event'], evidence['group']
    native = load('us_types').get(evidence.get('native_market_type'), {})
    if (quote['venue'] != 'polymarket_us' or source.get('provider') != 'polymarket_us'
            or source.get('quote_side') != 'buy' or side not in ('Long', 'Short')
            or not all(native_key) or native_key != evidence.get('native_key')
            or group['period'] != 'full_game' or native.get('period') != group['period']
            or native.get('family') != NORMAL_FAMILIES.get(group['market'])
            or event['league'] not in native.get('competitions', ())
            or listing.get('market_id') != market_id or listing.get('instrument_id') != outcome_id
            or listing.get('long') is not (side == 'Long') or listing.get('is_combo') not in (False, None)
            or not quote['binding']['verified']):
        raise NativeEvidenceError('polymarket_scanner_selected_market_unbound')
    digest = listing.get('material_sha256', '')
    if not re.fullmatch('[0-9a-f]{64}', digest) or digest != evidence.get('material_sha256'):
        raise NativeEvidenceError('polymarket_scanner_market_material_conflict')
    return native_key, listing


def _grid(quote, listing):
    original = quote['original']
    if (original.get('units'), original.get('quantity_units'), original.get('payout_units')) != (
            'usd_per_contract', 'contracts', 'USD') or Fraction(original.get('payout', '0')) != 1:
        raise NativeEvidenceError('polymarket_scanner_quantity_unit_unsupported')
    price = Fraction(original['value'])
    if listing['long'] is False and (original.get('transformation') != 'one_minus_native_bid'
            or original.get('native_units') != 'usd_per_contract' or price != 1 - Fraction(original['native_value'])):
        raise NativeEvidenceError('polymarket_scanner_short_price_unbound')
    values = listing['values']
    minimum, tick = Fraction(values['minimumTradeQty']), Fraction(values['orderPriceMinTickSize'])
    if minimum not in (Fraction(1, 100), 1) or tick <= 0 or 1 % tick or price % tick:
        raise NativeEvidenceError('polymarket_scanner_order_grid_unbound')
    if not MINIMUM_PRICE <= price <= MAXIMUM_PRICE:
        raise NativeEvidenceError('polymarket_scanner_fee_price_unsupported')
    return dict(minimum=wire(minimum), increment=wire(minimum), tick=wire(tick),
                minimum_price=wire(MINIMUM_PRICE), maximum_price=wire(MAXIMUM_PRICE))


def _payout(evidence, listing):
    contract = evidence.get('native_contract') or {}
    descriptor = contract.get('same_outcome') or evidence.get('same_outcome') or {}
    predicate, equality = descriptor.get('predicate') or {}, descriptor.get('equality') or {}
    if (contract.get('scope', {}).get('overtime') != 'included'
            or predicate.get('operator') not in ('lt', 'le', 'gt', 'ge')
            or predicate.get('domain') not in ('home_margin', 'combined_score')):
        raise NativeEvidenceError('polymarket_scanner_settlement_predicate_unbound')
    description = listing.get('description')
    group = evidence['group']
    prefix = 'This market will settle to the winner of ' if group['market'] == 'winner' else 'This market will settle to Yes if '
    if (not isinstance(description, str) or not description.startswith(prefix)
            or not 1 <= len(description) <= 8192
            or not any(clause in description for clause in ('Overtime is included if played.',
                                                             'Overtime and any shootout are included if played.',
                                                             'Extra innings are included if played.'))):
        raise NativeEvidenceError('polymarket_scanner_settlement_terms_unbound')
    above = predicate['operator'] in ('gt', 'ge')
    equal = None
    if equality.get('treatment') == 'fraction' and group['market'] == 'winner':
        tie = TIE.search(description)
        if not tie:
            raise NativeEvidenceError('polymarket_scanner_tie_terms_unbound')
        long_payout = Fraction(tie[1])
        equal = long_payout if listing['long'] else 1 - long_payout
        if equal != Fraction(equality['payout']):
            raise NativeEvidenceError('polymarket_scanner_tie_terms_conflict')
    elif equality.get('treatment') == 'not_feasible' and Fraction(predicate['threshold']).denominator == 2:
        equal = None  # An integral game score cannot equal the listed half-line.
    completion = None
    listed_start = ORIGINAL_START.search(description)
    if listed_start and FAIR_MARK in description:
        eastern = ZoneInfo('America/New_York')
        original = datetime.strptime(' '.join(listed_start.groups()), '%B %d, %Y %I:%M%p').replace(tzinfo=eastern)
        completion = dict(kind='rescheduled_within_days', maximum='2',
            original_start=original.astimezone(timezone.utc).isoformat(), original_scheduled_date=original.date().isoformat(),
            date_timezone=eastern.key, terminal='discretionary_last_fair_market_price')
    return dict(below='0' if above else '1', equal=None if equal is None else wire(equal),
                above='1' if above else '0', terminal=None), completion


def resolve(quote, evidence, *, at):
    """Bind the legal grid, fee bound and selected cashflow cells to one quote."""
    at = instant(at) if isinstance(at, str) else at
    try:
        phase = evidence.get('phase')
        if phase not in ('pregame', 'live'):
            raise NativeEvidenceError('polymarket_scanner_phase_unbound')
        native_key, listing = _market(quote, evidence)
        review = _fee_review(evidence.get('fee_review'), at)
        grid = _grid(quote, listing)
        payout, completion = _payout(evidence, listing)
    except (KeyError, TypeError, ZeroDivisionError):
        raise NativeEvidenceError('polymarket_scanner_evidence_incomplete') from None
    fee = dict(coefficient=STANDARD_TIERS[0], basis='public_standard_taker_tier_upper_bound',
        order='one_aggressive_order', rounding='half_even_cents_cumulative_order_cap', rebates='0',
        clearing='0', account_verified=False)
    witnesses = dict(native_key=native_key, market_sha256=listing['material_sha256'],
        terms=SETTLEMENT, fee_schedule=URL, fee_schedule_revision=review['verification_revision'],
        quantity=FRACTIONAL, collateral=COLLATERAL, clearing=CLEARING, clearing_sha256=CLEARING_SHA256,
        exchange_rulebook=RULEBOOK)
    return dict(grid=grid, payout=payout, completion=completion, fee=fee, evidence=witnesses,
        valid_until=review.get('review_before'), phase=phase)


def entry_fee(model, fills):
    """Upper-bound standard taker fees when L2 does not identify individual fills."""
    coefficient = Fraction(model['fee']['coefficient'])
    exact = Fraction(0)
    for quantity, price in fills:
        if quantity <= 0 or not MINIMUM_PRICE <= price <= MAXIMUM_PRICE:
            raise ValueError('polymarket_scanner_fill_outside_fee_scope')
        exact += coefficient * quantity * price * (1 - price)
    # Every reported execution partition is capped by this amount. Rounding
    # once per aggregate L2 price could charge less than actual per-fill rounding.
    return rounded_cents(exact)
