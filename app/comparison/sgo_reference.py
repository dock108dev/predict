"""Exact, auditable SGO bookmaker reference calculation.

This is a calculation boundary, not an identity or settlement verifier. Callers
must first bind a native contract to an SGO occurrence and supply reviewed
settlement evidence for both sides. Vendor fair odds are intentionally excluded.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import re

from .game_phase import LIVE_SECONDS

VERSION = 'sgo-book-median-proportional-1'
NAMED_VERSION = 'sgo-named-proportional-1'
BEST_VERSION = 'sgo-best-payout-proportional-1'
BEST_BOOKS = ('fanduel', 'draftkings', 'betmgm', 'caesars')
MAX_AGE_SECONDS = 1800
MIN_BOOKS = 3
OPPOSITE = {'home': 'away', 'away': 'home', 'over': 'under', 'under': 'over'}
DECIMAL = re.compile(r'^[+-]?\d{1,12}(?:\.\d{1,12})?$')


def _time(value):
    if not isinstance(value, str):
        raise ValueError('source_clock_unknown')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('source_clock_invalid') from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('source_clock_unknown')
    return result.astimezone(timezone.utc)


def _line(value):
    if value is None:
        return None
    # Reject floating-point values: upstream precision must survive normalization.
    if not isinstance(value, str) or not DECIMAL.fullmatch(value):
        raise ValueError('line_invalid')
    return Fraction(value)


def american_probability(value):
    if not isinstance(value, str) or not DECIMAL.fullmatch(value):
        raise ValueError('price_invalid')
    n = Fraction(value)
    if abs(n) < 100:
        raise ValueError('price_invalid')
    return Fraction(100, 1) / (n + 100) if n > 0 else -n / (-n + 100)


def _digest(value):
    wire = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(wire.encode()).hexdigest()


def calculate(quotes, contract, *, at, evaluated_venue, named_venue=None, best_payout=False,
              minimum_books=MIN_BOOKS, maximum_age_seconds=MAX_AGE_SECONDS, qualify_pair=None):
    """Return a decisive conditional probability or an explicit unavailable reason.

    ``contract`` identifies a previously matched occurrence, league, phase,
    period, market, side, exact selected line, and a reviewed settlement key.
    Every quote must independently carry that settlement key and nonempty
    settlement_evidence. Duplicate or conflicting sides invalidate the venue;
    all pairs must belong to the contract's same nonempty acquisition frame.
    """
    if type(minimum_books) is not int or minimum_books < 2:
        raise ValueError('minimum_books must be at least two')
    if type(maximum_age_seconds) is not int or maximum_age_seconds <= 0:
        raise ValueError('positive maximum age required')
    clock = _time(at)
    required = ('event_id', 'league', 'phase', 'period', 'market', 'side', 'settlement')
    if any(not contract.get(k) for k in required):
        raise ValueError('complete matched contract required')
    family, side = contract['market'], contract['side']
    if contract['phase'] not in ('pregame', 'live') or contract['period'] != 'game':
        raise ValueError('unsupported phase or period')
    live_start = None
    if contract['phase'] == 'live':
        if not contract.get('starts_at'):
            return {'available': False, 'reason': 'reference_live_start_unknown', 'contributors': [], 'exclusions': {}}
        live_start = _time(contract['starts_at'])
        maximum_age_seconds = min(maximum_age_seconds, LIVE_SECONDS)
    if family not in ('moneyline', 'spread', 'total') or side not in OPPOSITE:
        raise ValueError('unsupported contract')
    if (family == 'total') != (side in ('over', 'under')):
        raise ValueError('side and market conflict')
    selected_line = _line(contract.get('line'))
    if (family == 'moneyline') != (selected_line is None):
        raise ValueError('exact contract line required')
    if not contract.get('occurrence_evidence'):
        return {'available': False, 'reason': 'occurrence_binding_unverified', 'contributors': [], 'exclusions': {}}
    if not contract.get('frame_id'):
        return {'available': False, 'reason': 'reference_frame_unverified', 'contributors': [], 'exclusions': {}}
    if not contract.get('frame_received_at'):
        return {'available': False, 'reason': 'reference_frame_clock_unknown', 'contributors': [], 'exclusions': {}}
    if contract['settlement'] == 'unverified' or not contract.get('settlement_evidence'):
        return {'available': False, 'reason': 'contract_settlement_unverified', 'contributors': [], 'exclusions': {}}
    if not evaluated_venue:
        raise ValueError('evaluated venue required for self-exclusion')
    if best_payout and named_venue:
        raise ValueError('only one reference selection policy is supported')
    if named_venue == evaluated_venue:
        return {'available': False, 'reason': 'evaluated_venue_excluded', 'contributors': [], 'exclusions': {named_venue: 'evaluated_venue_excluded'}}
    grouped = defaultdict(list)
    for quote in quotes:
        if isinstance(quote, dict) and quote.get('venue'):
            if all(quote.get(k) == contract[k] for k in ('event_id', 'league', 'phase', 'period', 'market')):
                grouped[quote['venue']].append(quote)
    contributors, exclusions = [], {}
    for venue, group in sorted(grouped.items()):
        if best_payout and venue not in BEST_BOOKS:
            continue
        if venue == evaluated_venue:
            exclusions[venue] = 'evaluated_venue_excluded'; continue
        if named_venue and venue != named_venue:
            continue
        try:
            sides = {}
            for q in group:
                if q.get('side') not in (side, OPPOSITE[side]):
                    continue
                line = _line(q.get('line'))
                expected = selected_line if q['side'] == side or family != 'spread' else -selected_line
                if line != expected:
                    continue
                if q['side'] in sides:
                    raise ValueError('duplicate_side')
                sides[q['side']] = q
            if set(sides) != {side, OPPOSITE[side]}:
                raise ValueError('exact_opposing_pair_missing')
            pair = [sides[side], sides[OPPOSITE[side]]]
            if any(q.get('frame_id') != contract['frame_id'] for q in pair):
                raise ValueError('pair_frame_unverified')
            if any(q.get('frame_received_at') != contract['frame_received_at'] for q in pair):
                raise ValueError('pair_frame_clock_conflict')
            if not all(q.get('available') is True for q in pair):
                raise ValueError('quote_unavailable')
            if not all(q.get('odd_id') and q.get('opposing_odd_id') for q in pair) or pair[0]['odd_id'] != pair[1]['opposing_odd_id'] or pair[1]['odd_id'] != pair[0]['opposing_odd_id']:
                raise ValueError('opposing_identity_unverified')
            implied = []
            for q in pair:
                source, receipt = _time(q.get('source_at')), _time(q.get('received_at'))
                frame_receipt = _time(q.get('frame_received_at'))
                if source > receipt or receipt > frame_receipt or frame_receipt > clock or source > clock:
                    raise ValueError('clock_future')
                if live_start is not None and source < live_start:
                    raise ValueError('reference_pre_start')
                if (clock - source).total_seconds() > maximum_age_seconds:
                    raise ValueError('source_stale')
                implied.append(american_probability(q.get('price_american')))
            if qualify_pair is not None:
                pair = qualify_pair(pair)
            if not all(q.get('settlement') == contract['settlement'] and q.get('settlement_evidence') for q in pair):
                raise ValueError('settlement_unverified_or_incompatible')
            if pair[0].get('jurisdiction') != pair[1].get('jurisdiction'):
                raise ValueError('pair_jurisdiction_conflict')
            probability = implied[0] / sum(implied)
            evidence = [{k: q.get(k) for k in ('frame_id', 'frame_received_at', 'odd_id', 'opposing_odd_id', 'side', 'line', 'price_american', 'source_at', 'received_at', 'settlement', 'settlement_evidence', 'jurisdiction', 'rule_source', 'rule_reviewed_at')} for q in pair]
            contributors.append({'venue': venue, 'probability': str(probability), 'inputs': evidence})
        except (ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
            exclusions[venue] = str(exc) or 'invalid_quote'
    threshold = 1 if named_venue or best_payout else minimum_books
    if len(contributors) < threshold:
        return {'available': False, 'reason': 'insufficient_qualifying_pairs', 'contributors': contributors, 'exclusions': exclusions}
    probabilities = sorted(Fraction(c['probability']) for c in contributors)
    mid = len(probabilities) // 2
    probability = probabilities[mid] if len(probabilities) % 2 else (probabilities[mid-1] + probabilities[mid]) / 2
    basis = {'version': BEST_VERSION if best_payout else NAMED_VERSION if named_venue else VERSION, 'contract': contract,
             'evaluated_venue': evaluated_venue, 'named_venue': named_venue,
             'minimum_books': minimum_books, 'required_contributors': threshold,
             'maximum_age_seconds': maximum_age_seconds, 'captured_at': at,
             'contributors': contributors, 'exclusions': exclusions}
    if best_payout:
        selected = min(contributors, key=lambda contributor: (
            american_probability(contributor['inputs'][0]['price_american']),
            BEST_BOOKS.index(contributor['venue'])))
        basis['selected_venue'] = selected['venue']
        probability = Fraction(selected['probability'])
    return {'available': True, 'probability': str(probability), 'fair_decimal_odds': str(1 / probability),
            'conditioning': 'decisive win/loss; pushes, ties and exceptional settlement excluded',
            'basis': basis, 'basis_sha256': _digest(basis), 'contributors': contributors, 'exclusions': exclusions}


@dataclass(frozen=True)
class ContributorFrameWitness:
    """Immutable JSON wire value suitable for a captured result's evidence store."""
    wire: str


def capture_witness(quotes, contract, *, at, evaluated_venue, named_venue=None, best_payout=False,
                    minimum_books=MIN_BOOKS, maximum_age_seconds=MAX_AGE_SECONDS, qualify_pair=None):
    """Capture an admitted frame; unavailable inputs never produce a witness."""
    result = calculate(quotes, contract, at=at, evaluated_venue=evaluated_venue,
                       named_venue=named_venue, best_payout=best_payout, minimum_books=minimum_books,
                       maximum_age_seconds=maximum_age_seconds, qualify_pair=qualify_pair)
    if not result['available']:
        return result, None
    payload = {key: result[key] for key in ('probability', 'fair_decimal_odds', 'conditioning', 'basis', 'basis_sha256')}
    return result, ContributorFrameWitness(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False))


def validate_witness(witness, *, at):
    """Recalculate a captured frame, including age at the new evaluation time.

    This verifies arithmetic and witness consistency, not the truth of upstream
    settlement/occurrence evidence. The ingestion and matching owners must
    validate those independently. Exclusion reasons are captured diagnostics;
    excluded inputs are not retained here and are not independently verified.
    """
    try:
        if not isinstance(witness, ContributorFrameWitness) or len(witness.wire) > 2_000_000:
            raise ValueError('invalid_witness')
        saved = json.loads(witness.wire)
        basis = saved['basis']
        if basis['version'] not in (VERSION, NAMED_VERSION, BEST_VERSION) or saved['basis_sha256'] != _digest(basis):
            raise ValueError('witness_basis_invalid')
        if (basis['version'] == NAMED_VERSION) != bool(basis['named_venue']):
            raise ValueError('witness_policy_invalid')
        if _time(basis['captured_at']) > _time(at):
            raise ValueError('capture_clock_future')
        contract = basis['contract']
        quotes = []
        for contributor in basis['contributors']:
            for item in contributor['inputs']:
                quotes.append(dict(item, venue=contributor['venue'], available=True,
                    **{k: contract[k] for k in ('event_id', 'league', 'phase', 'period', 'market')}))
        fresh = calculate(quotes, contract, at=at, evaluated_venue=basis['evaluated_venue'],
                          named_venue=basis['named_venue'], best_payout=basis['version'] == BEST_VERSION,
                          minimum_books=basis['minimum_books'],
                          maximum_age_seconds=basis['maximum_age_seconds'])
        if not fresh['available']:
            return fresh
        if (fresh['probability'] != saved['probability'] or fresh['fair_decimal_odds'] != saved['fair_decimal_odds']
                or fresh['conditioning'] != saved['conditioning'] or fresh['contributors'] != basis['contributors']
                or fresh['basis']['required_contributors'] != basis['required_contributors']
                or fresh['basis']['maximum_age_seconds'] != basis['maximum_age_seconds']
                or fresh['basis'].get('selected_venue') != basis.get('selected_venue')):
            raise ValueError('witness_calculation_conflict')
        return {'available': True, 'probability': fresh['probability'],
                'basis_sha256': saved['basis_sha256'], 'basis': basis,
                'conditioning': saved['conditioning']}
    except (KeyError, TypeError, ValueError, OverflowError, ArithmeticError):
        return {'available': False, 'reason': 'invalid_contributor_witness'}
