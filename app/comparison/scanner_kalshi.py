"""Exact Kalshi series, selected book market, and published direct taker terms."""

from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re

from app.fees.engine import Registry, calculate
from app.fees.evidence import applies

from .current_dependencies import digest, instant
from .net_costs import wire
from .scanner_native import NativeEvidenceError
from .snapshot_fee_scope import ROOT, kalshi_fee_context

VERSION = 'predict-scanner-kalshi-direct-taker-1'
FIXED_POINT = 'https://docs.kalshi.com/getting_started/fixed_point_migration.md'
SETTLEMENT = 'https://docs.kalshi.com/getting_started/market_settlement.md'
ORDERBOOK = 'https://docs.kalshi.com/getting_started/orderbook_responses.md'
FILL_INCREMENT = Fraction('0.01')
DIRECT_PRECISION = Fraction('0.0001')
FAIR_PRICE = re.compile(r'\bfair (?:market )?price\b', re.I)
HALF_TIE = re.compile(r'\bif the game ends in a tie, the market will resolve to \$0\.50 for each team\b', re.I)


@lru_cache(maxsize=4)
def _fee_material(path, expected_sha256, size, mtime_ns):
    raw = path.read_bytes()
    if len(raw) != size or sha256(raw).hexdigest() != expected_sha256:
        raise NativeEvidenceError('kalshi_fee_review_material_conflict')
    return json.loads(raw)


def _schedule(q, evidence, at):
    review = evidence.get('fee_review')
    if not review or review.get('unavailable_reason') or not applies(review, at):
        raise NativeEvidenceError('kalshi_fee_review_unavailable')
    path = Path(review['path'])
    if path.is_absolute() or '..' in path.parts:
        raise NativeEvidenceError('kalshi_fee_review_material_conflict')
    path = ROOT / path
    try:
        info = path.stat()
        body = _fee_material(path, review['sha256'], info.st_size, info.st_mtime_ns)
    except OSError as exc:
        raise NativeEvidenceError('kalshi_fee_review_unavailable') from exc
    group, event = evidence['group'], evidence['event']
    scope = {key: evidence.get(key) for key in ('series_id', 'native_key')}
    normalized = dict(q, league=event['league'], market=group, fee_applicability=scope)
    fee_context, registry, reviewed = kalshi_fee_context(normalized, review, at, body=body)
    fee_context.update(balance_precision='0.0001', applicability_evidence=scope)
    series = body['series'][scope['series_id']]
    if group['period'] != series['period'] or group['period'] != 'full_game':
        raise NativeEvidenceError('kalshi_market_period_unsupported')
    return dict(context=fee_context, registry=registry, scenario='direct_api_taker',
                rounding='upper_bound_minimum_fills_with_documented_order_accumulator',
                account_verified=False, includes_intermediary_charges=False), reviewed, series


def _market_grid(q, evidence):
    source = q['source']
    observed = evidence.get('selected_market_observation') or {}
    raw = evidence.get('market')
    if raw is not None:
        if (raw.get('ticker'), raw.get('event_ticker')) != (source['native_market_id'], source['native_event_id']):
            raise NativeEvidenceError('kalshi_market_observation_identity_conflict')
        if raw.get('market_type') != 'binary' or raw.get('settlement_bounds_type', 'default') != 'default':
            raise NativeEvidenceError('kalshi_market_payout_scope_unsupported')
    if (observed.get('status') != 'observed'
            or observed.get('native_event_id') != source['native_event_id']
            or observed.get('native_market_id') != source['native_market_id']
            or not observed.get('material_sha256')
            or observed['material_sha256'] != evidence.get('material_sha256')
            or not (observed.get('source') or {}).get('body_sha256')):
        raise NativeEvidenceError('kalshi_market_grid_unbound')
    values = observed['values']
    if raw is not None and any(raw.get(key) != values.get(key) for key in ('price_ranges', 'notional_value_dollars')):
        raise NativeEvidenceError('kalshi_market_observation_material_conflict')
    if values.get('market_type', 'binary') != 'binary' or values.get('settlement_bounds_type', 'default') != 'default':
        raise NativeEvidenceError('kalshi_market_payout_scope_unsupported')
    if Fraction(values.get('notional_value_dollars', '0')) != 1:
        raise NativeEvidenceError('kalshi_market_payout_scope_unsupported')
    ranges = values.get('price_ranges')
    if not isinstance(ranges, list) or not 1 <= len(ranges) <= 32:
        raise NativeEvidenceError('kalshi_price_grid_unavailable')
    bands = []
    for band in ranges:
        start, end, step = (Fraction(band[key]) for key in ('start', 'end', 'step'))
        if not (0 <= start < end <= 1 and 0 < step <= 1 and not (end - start) % step):
            raise NativeEvidenceError('kalshi_price_grid_unsupported')
        bands.append([wire(start), wire(end), wire(step)])
    tick = min(Fraction(step) for _, _, step in bands)
    if any(Fraction(value) % tick for band in bands for value in band):
        raise NativeEvidenceError('kalshi_price_grid_unsupported')
    if source['native_side'] == 'no':
        bands = sorted([wire(1 - Fraction(end)), wire(1 - Fraction(start)), step]
                       for start, end, step in bands)
    if not _valid_price(Fraction(q['original']['value']), bands):
        raise NativeEvidenceError('kalshi_price_grid_conflict')
    fractional = raw.get('fractional_trading_enabled') if raw is not None else values.get('fractional_trading_enabled')
    quantity = '0.01' if fractional is True else '1'
    return dict(minimum=quantity, increment=quantity, tick=wire(tick), price_ranges=bands), observed


def _valid_price(price, ranges):
    return 0 < price < 1 and any(start <= price <= end and not (price - start) % step
        for start, end, step in (tuple(map(Fraction, band)) for band in ranges))


def _payout(evidence, series, grid):
    combined = evidence.get('combined_native_binding') or {}
    wording = combined.get('original_terms') or evidence.get('original_wording') or {}
    primary = wording.get('rules_primary')
    secondary = wording.get('rules_secondary') or ''
    if not isinstance(primary, str) or not primary.strip() or primary != evidence.get('rules_primary'):
        raise NativeEvidenceError('kalshi_selected_contract_terms_unbound')
    if secondary != (evidence.get('rules_secondary') or ''):
        raise NativeEvidenceError('kalshi_selected_contract_terms_conflict')
    # Scalar settlement can round to cents. A per-contract 50¢ net value is
    # proven across this quantity grid only when the credit stays on-cent.
    aligned_half_payout = not (Fraction(grid['increment']) * Fraction('0.50')) % Fraction('0.01')
    equal = '0.5' if (series['family'] == 'moneyline' and aligned_half_payout and HALF_TIE.search(secondary)) else None
    payout = dict(below=None, equal=equal, above=None, terminal=None, binary_face='1')
    governing_url = series['response']['series']['contract_terms_url']
    completion = dict(official_result=True, terminal='exchange_discretionary_fair_price' if FAIR_PRICE.search(secondary)
                      else 'exact_terminal_cashflow_unknown', governing_rules=governing_url,
                      original_terms_sha256=digest(wording), scalar_settlement_fee='unqualified')
    return payout, completion


def resolve(q, evidence, *, at):
    """Resolve the named public direct API taker scenario for one admitted offer."""
    if q['venue'] != 'kalshi' or q['source']['provider'] != 'kalshi':
        raise NativeEvidenceError('kalshi_direct_native_source_required')
    if isinstance(at, str):
        at = instant(at)
    fee, review, series = _schedule(q, evidence, at)
    grid, observed = _market_grid(q, evidence)
    payout, completion = _payout(evidence, series, grid)
    waiver = (evidence.get('market') or observed['values']).get('fee_waiver_expiration_time')
    # Standard charge remains a conservative bound during a fee waiver.
    fee['fee_waiver_expires_at'] = instant(waiver).isoformat() if waiver else None
    return dict(version=VERSION, grid=grid, fee=fee, payout=payout, completion=completion,
                valid_until=review.get('review_before'), evidence=dict(
                    fee_schedule=review['sha256'], fee_verification=review.get('verification_revision'),
                    fee_metadata=review['metadata_revision'], market_material=observed['material_sha256'],
                    market_receipt=observed['source']['body_sha256'], quantity_rules=FIXED_POINT,
                    depth_partition_rules=ORDERBOOK,
                    settlement_rules=SETTLEMENT, contract_terms=completion['governing_rules']))


def entry_fee(model, fills):
    """Upper-bound direct taker fees across unobserved order fragments."""
    fee = model['fee']
    ranges = model['grid']['price_ranges']
    standalone, trade = Fraction(0), Fraction(0)
    aligned = True
    for quantity, price in fills:
        fragments = quantity / FILL_INCREMENT
        if quantity <= 0 or fragments.denominator != 1 or not _valid_price(price, ranges):
            raise ValueError('kalshi_fill_grid_conflict')
        aligned &= (price * FILL_INCREMENT) % DIRECT_PRECISION == 0
        # The venue publishes quantities by level, without resting order
        # counts. Trade-fee ceilings and balance alignment are subadditive
        # across equal-price fragments. Charging the smallest possible fill
        # independently, without any order-level rebate, bounds that cost.
        fill = dict(fill_id='scanner-minimum-fragment', order_id='scanner-hypothetical-order',
                    role='taker', price=wire(price), quantity=wire(FILL_INCREMENT), unit='contracts')
        audit = calculate(dict(fee['context'], fills=[fill]), Registry(fee['registry']))
        if audit['entry_fees'] is None:
            raise ValueError('kalshi_modeled_entry_fee_unavailable')
        standalone += fragments * Fraction(audit['entry_fees'])
        trade += fragments * Fraction(audit['trace'][0]['trade_fee'])
    # Whole-cent prices produce balance-aligned debits for every possible
    # fragment. Each positive fee can rebate at least one grid unit, so the
    # single-order accumulator leaves less than one unit of rounding at close.
    # Without aligned debits a small fill can cap rebates below that unit.
    if aligned:
        return -(-trade // DIRECT_PRECISION) * DIRECT_PRECISION
    return standalone
