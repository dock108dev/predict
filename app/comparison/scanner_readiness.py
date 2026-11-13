"""Read-only readiness contract. No financial classification or acquisition.

Readiness checks inputs, never the existence or profitability of opportunities.
All counts name their selected universe; causes intentionally overlap.
"""
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from copy import deepcopy
from itertools import combinations
from typing import Literal

from .current_dependencies import digest, instant
from .domain import ExactNumber

VERSION = 'predict-scanner-readiness-1'
POLICY = 'predict-scanner-readiness-policy-1'
VENUES = ('kalshi', 'polymarket_us', 'novig', 'prophetx', 'pinnacle')
EXECUTION_VENUES = VENUES[:-1]
STATES = ('ready', 'waiting', 'stale_only', 'partial', 'unsupported', 'failed', 'blocked', 'not_evaluated')
MAX_INSTRUMENTS = 32768
MAX_PAIRS = 32768
MAX_OCCURRENCE_INSTRUMENTS = 128
PAIR_FIELDS = ('sport', 'league', 'market', 'period', 'overtime')
SCORE_DOMAINS = {'winner': 'home_margin', 'spread': 'home_margin', 'total': 'combined_score'}
MAX_BYTES = 8 * 1024 * 1024
# Fixed conservative admission policy, not an observed source update guarantee.
# Native cap inherits current native admission's 30-second window. Aggregate
# execution/reference caps retain net-pregame 900 / gross-reference 1800 seconds.
# Cross-book skew is capped at one native admission window for every pair.
def _policy():
    import json
    from pathlib import Path
    value = json.loads((Path(__file__).resolve().parents[1]/'fixtures/scanner-readiness-policy-v1.json').read_text())
    if value['version'] != POLICY:
        raise ValueError('readiness_policy_identity_conflict')
    return value


POLICY_FACTS = _policy()
POLICY_REVISION = digest(POLICY_FACTS)
LIMITS = POLICY_FACTS['limits']


@dataclass(frozen=True)
class Selection:
    venues: tuple[str, ...] = EXECUTION_VENUES
    sports: tuple[str, ...] = ('football', 'basketball', 'baseball', 'hockey')
    leagues: tuple[str, ...] = ('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL')
    markets: tuple[str, ...] = ('winner', 'spread', 'total')
    periods: tuple[str, ...] = ('full_game',)

    def __post_init__(self):
        for name in ('venues', 'sports', 'leagues', 'markets', 'periods'):
            values = getattr(self, name)
            if not isinstance(values, tuple) or not values or len(values) != len(set(values)) or len(values) > 16:
                raise ValueError('readiness_exact_selection_required')
            if any(not isinstance(x, str) or not x or len(x) > 64 for x in values):
                raise ValueError('readiness_exact_selection_required')
        if set(self.venues) - set(EXECUTION_VENUES):
            raise ValueError('readiness_execution_venue_unsupported')

    def to_dict(self):
        return {k: sorted(v) for k, v in asdict(self).items()}


@dataclass(frozen=True)
class Check:
    state: Literal['ready', 'waiting', 'stale_only', 'partial', 'unsupported', 'failed', 'blocked', 'not_evaluated']
    reason_codes: tuple[str, ...] = ()

    def to_dict(self):
        return dict(state=self.state, reason_codes=sorted(set(self.reason_codes)))


def check(reasons, *, empty='ready'):
    reasons = sorted(set(reasons))
    if not reasons:
        return Check(empty).to_dict()
    if any(r in reasons for r in ('scope_not_authorized', 'aggregate_transport_uncertain', 'ambiguous_dispatch_unresolved')):
        state = 'blocked'
    elif 'source_failed' in reasons or 'readiness_check_failed' in reasons:
        state = 'failed'
    elif any(r.endswith(('_conflict', '_unknown', '_unsupported', '_unqualified', '_missing', '_not_effective', '_expired')) and r not in ('source_price_expired', 'book_price_expired', 'reference_expired') for r in reasons):
        state = 'unsupported'
    elif any(r in reasons for r in ('source_price_expired', 'book_price_expired', 'reference_expired', 'source_disconnected', 'source_unavailable')):
        state = 'stale_only'
    else:
        state = 'waiting'
    return Check(state, tuple(reasons)).to_dict()


def clock_reasons(source_at, received_at, at, limit, prefix='source'):
    """Receipt cannot repair an unknown, future-at-receipt or expired original."""
    if source_at is None or received_at is None:
        return [prefix + '_clock_unknown']
    try:
        source, receipt = instant(source_at), instant(received_at)
    except (ValueError, TypeError):
        return [prefix + '_clock_unknown']
    if source > receipt or source > at or receipt > at:
        return [prefix + '_clock_conflict']
    return [prefix + '_price_expired'] if (at - source).total_seconds() >= limit else []


def _count(n, denominator, unit, scope):
    return dict(value=n, denominator=denominator, unit=unit, scope=scope)


def _status(rows):
    if not rows:
        return 'waiting'
    counts = Counter(r['state'] for r in rows)
    if len(counts) == 1:
        return next(iter(counts))
    return 'partial'


def assemble(instruments, *, selection, at, epoch, input_revision, scopes, evaluations=(),
             pair_limit=MAX_PAIRS, occurrence_limit=None, retain_capacity_gaps=False, transport_limit=MAX_BYTES):
    """Pure typed projection from exact admitted inputs and explicit SC02 evidence.

    Evaluation receipts must bind this readiness revision and exact ready pair
    membership. Stale receipts withdraw automatically. No receipt is invented.
    """
    instant(at)
    scopes = deepcopy(scopes)
    if len(instruments) > MAX_INSTRUMENTS:
        raise ValueError('readiness_instrument_capacity')
    if len({i['id'] for i in instruments}) != len(instruments):
        raise ValueError('readiness_instrument_identity_conflict')
    selected_keys = {s['key'] for s in scopes}
    instruments = sorted((i for i in instruments if i['scope_key'] in selected_keys), key=lambda i: i['id'])
    pair_keys = {}
    for i in instruments:
        if i['scope_key'] != digest({k:i[k] for k in ('venue','sport','league','market','period')}):
            raise ValueError('readiness_scope_identity_conflict')
        pair_keys[i['id']] = _pair_key(i)
    by_scope = defaultdict(list)
    for i in instruments:
        by_scope[i['scope_key']].append(i)
    pairs = []
    by_occurrence = defaultdict(list)
    for i in instruments:
        by_occurrence[i['occurrence_id']].append(i)
    failed_occurrences = set()
    failed_scopes = defaultdict(set)

    def skip_pairs(occurrence, rows, reason):
        if not retain_capacity_gaps:
            raise ValueError(reason)
        failed_occurrences.add(occurrence)
        for instrument in rows:
            failed_scopes[instrument['scope_key']].add(reason)

    # A single oversized occurrence must not censor every other league. Keep its
    # instrument census intact and refuse all pair claims for the affected game.
    paired_occurrences = 0
    for index, (occurrence, rows) in enumerate(by_occurrence.items()):
        if retain_capacity_gaps:
            candidates = _structural_candidates(rows, pair_keys)
            if candidates is None:
                skip_pairs(occurrence, rows, 'readiness_occurrence_capacity')
                continue
            if not candidates:
                continue
            if occurrence_limit is not None and paired_occurrences >= occurrence_limit:
                skip_pairs(occurrence, rows, 'readiness_occurrence_capacity')
                continue
            paired_occurrences += 1
        else:
            if (len(rows) > MAX_OCCURRENCE_INSTRUMENTS
                    or occurrence_limit is not None and index >= occurrence_limit):
                skip_pairs(occurrence, rows, 'readiness_occurrence_capacity')
            candidates = combinations(rows, 2)
        start = len(pairs)
        for left, right in candidates:
            pair = _compatible_pair(left, right, pair_keys)
            if pair is None:
                continue
            if len(pairs) >= pair_limit:
                del pairs[start:]
                skip_pairs(occurrence, rows, 'readiness_pair_capacity')
                break
            pairs.append(pair)
    for scope in scopes:
        if scope['key'] in failed_scopes:
            scope['check'] = check([*scope['check']['reason_codes'], 'readiness_check_failed',
                                    *failed_scopes[scope['key']]])
    boundary = dict(policy=POLICY, policy_revision=POLICY_REVISION, selection=selection.to_dict(), epoch=epoch, input_revision=input_revision,
                    instruments=instruments, scopes=scopes, pairs=pairs)
    # Stable for repeated reads between boundaries; causal receipt changes still
    # alter inputs. Age seconds are calculated by consumers from original clocks.
    from .current_dependencies import streaming_digest
    revision = streaming_digest(boundary)
    by_id = {i['id']: i for i in instruments}
    ready = {p['id'] for p in pairs if p['input_check']['state'] == 'ready'}
    receipts = {}
    for e in evaluations:
        if set(e) != {'pair_id', 'readiness_revision', 'evaluated_at', 'qualifying', 'evaluator_revision'}:
            raise ValueError('readiness_evaluation_receipt_invalid')
        if e['pair_id'] in receipts:
            raise ValueError('readiness_evaluation_identity_conflict')
        if type(e['qualifying']) is not bool or not isinstance(e['evaluator_revision'], str) or not e['evaluator_revision']:
            raise ValueError('readiness_evaluation_receipt_invalid')
        if e['readiness_revision'] != revision or e['pair_id'] not in ready:
            continue
        if instant(e['evaluated_at']) > instant(at):
            raise ValueError('readiness_evaluation_clock_conflict')
        pair = next(p for p in pairs if p['id'] == e['pair_id'])
        if any(instant(c) > instant(e['evaluated_at']) for leg in pair['legs'] for k, c in by_id[leg]['clocks'].items() if k in ('source_at', 'received_at', 'book_at', 'book_received_at', 'provider_book_at', 'provider_market_at') and c):
            raise ValueError('readiness_evaluation_clock_conflict')
        receipts[e['pair_id']] = e
    checked = len(receipts)
    qualifying = sum(e['qualifying'] for e in receipts.values()) if checked else None
    evaluation_state = ('not_evaluated' if not checked else 'partial' if checked != len(ready) else
                        'evaluated_positive' if qualifying else 'evaluated_zero')
    # Missing/blocked selected scopes prevent a global no-opportunities claim.
    for scope in scopes:
        rows = by_scope[scope['key']]
        n = len(rows)
        checks = [check([r for purpose in ('execution', 'contract') for r in i['checks'][purpose]['reason_codes']]) for i in rows]
        base = scope['check']
        scope['state'] = base['state'] if base['state'] != 'ready' else _status(checks)
        if scope.get('discovery', {}).get('contracts', {}).get('value', n) > n and scope['state'] == 'ready':
            scope['state'] = 'partial'
        scope['counts'] = {name: _count(sum(bool(i[field]) for i in rows), n, 'instruments', scope['key']) for name, field in
                           (('identity_bound', 'identity_bound'), ('price_present', 'price_present'), ('synchronized_depth', 'synchronized_depth'))}
        scope['counts']['cashflow_inputs_ready'] = _count(sum(c['state'] == 'ready' for c in checks), n, 'instruments', scope['key'])
    # Scope counts are derived outputs, excluded from revision input identity.
    causes = defaultdict(set)
    for i in instruments:
        for purpose, c in i['checks'].items():
            for code in c['reason_codes']:
                causes[(purpose, code)].add(i['id'])
    states = [dict(state=s['state']) for s in scopes]
    out = dict(universe_basis='selected_current_admitted', version=VERSION, policy=POLICY, policy_revision=POLICY_REVISION, as_of=at, selection=selection.to_dict(), epoch=epoch,
               input_revision=input_revision, revision=revision, state=_status(states),
               expires_at=min((i['expires_at'] for i in instruments), key=instant, default=None),
               scopes=scopes, instruments=instruments, pairs=pairs,
               counts=dict(selected_scopes=_count(len(scopes), len(scopes), 'venue_scopes', 'selected_universe'),
                           observed_occurrences=_count(len({i['occurrence_id'] for i in instruments}), len({i['occurrence_id'] for i in instruments}), 'occurrences', 'selected_observed'),
                           observed_instruments=_count(len(instruments), len(instruments), 'instruments', 'selected_observed'),
                           compatible_pair_inputs=_count(len(pairs), len(pairs), 'pairs', 'selected_exact_opposing_inputs'),
                           cashflow_pairs_ready=_count(len(ready), len(pairs), 'pairs', 'selected_exact_opposing_inputs'),
                           evaluated_pairs=_count(checked, len(ready), 'pairs', 'selected_ready_inputs')),
               pair_coverage='no_compatible_pairs' if not pairs else 'unavailable' if not ready else 'partially_evaluable' if len(ready) < len(pairs) else 'evaluable',
               evaluation=dict(state=evaluation_state, qualifying_pairs=qualifying,
                               no_qualifying_opportunities=bool(checked and checked == len(ready) and not qualifying and all(s['state'] == 'ready' for s in scopes))),
               causes=[dict(purpose=p, code=c, count=_count(len(ids), len(instruments), 'instruments', 'selected_observed')) for (p, c), ids in sorted(causes.items())],
               causes_overlap=True, provider_requests=0)
    from .readiness_encoding import transport_size
    if transport_limit is not None and transport_size(out) > transport_limit:
        raise ValueError('readiness_response_capacity')
    if failed_occurrences:
        out['failed_occurrences'] = sorted(failed_occurrences)
    return out


def _pair_key(row):
    scope = tuple(row[field] for field in PAIR_FIELDS)
    if 'score_partition' not in row:
        return scope
    partition = row['score_partition']
    if (not isinstance(partition, dict) or set(partition) != {'domain', 'threshold'}
            or partition['domain'] != SCORE_DOMAINS.get(row['market'])
            or row['market'] not in SCORE_DOMAINS):
        raise ValueError('readiness_score_partition_invalid')
    threshold = ExactNumber.parse(partition['threshold']).key
    if row['market'] == 'winner' and threshold != (0, 1):
        raise ValueError('readiness_score_partition_invalid')
    return (*scope, partition['domain'], threshold)


def _compatible_pair(left, right, pair_keys):
    if left['venue'] == right['venue'] or pair_keys[left['id']] != pair_keys[right['id']]:
        return None
    # Preserve native NO/Short. Exceptional settlement is verified by finance.
    if left['direction'] is None or right['direction'] is None or left['direction'] == right['direction']:
        return None
    reasons = [reason for leg in (left, right) for purpose in ('execution', 'contract')
               for reason in leg['checks'][purpose]['reason_codes']]
    first_context, second_context = (leg.get('native_execution_context') for leg in (left, right))
    if first_context and second_context and first_context != second_context:
        reasons.append('native_execution_pair_scope_conflict')
    skew = None
    try:
        skew = abs((instant(left['clocks'].get('execution_at',left['clocks']['source_at']))
                    - instant(right['clocks'].get('execution_at',right['clocks']['source_at']))).total_seconds())
        limit = min(LIMITS[leg['venue']]['cross_leg_skew_seconds'] for leg in (left, right))
        if skew > limit:
            reasons.append('cross_leg_skew_exceeded')
    except (TypeError, ValueError):
        reasons.append('pair_clock_unknown')
    return dict(id=digest([VERSION, left['id'], right['id']]), legs=[left['id'], right['id']],
                occurrence_id=left['occurrence_id'], skew_seconds=skew, input_check=check(reasons),
                expires_at=min(left['expires_at'], right['expires_at'], key=instant))


def _structural_candidates(rows, pair_keys):
    """Index only exact opposing legs while preserving combinations order."""
    buckets = defaultdict(lambda: defaultdict(list))
    keys = {}
    for index, row in enumerate(rows):
        direction = row['direction']
        if direction is None:
            continue
        key = pair_keys[row['id']]
        buckets[key][direction, row['venue']].append(index)
        keys[index] = key
    opponents = {}
    candidate_legs = 0
    for key, bucket in buckets.items():
        for (direction, venue), positions in bucket.items():
            matching = [indices for (other_direction, other_venue), indices in bucket.items()
                        if direction != other_direction and venue != other_venue]
            if matching:
                candidate_legs += len(positions)
                if candidate_legs > MAX_OCCURRENCE_INSTRUMENTS:
                    return None
                opponents[key, direction, venue] = sorted(index for indices in matching for index in indices)
    if not opponents:
        return ()

    def pairs():
        for index, key in keys.items():
            row = rows[index]
            matching = opponents.get((key, row['direction'], row['venue']), ())
            for right in matching[bisect_right(matching, index):]:
                yield row, rows[right]

    return pairs()
