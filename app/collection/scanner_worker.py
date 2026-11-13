"""One bounded, data-owned full-slate Scanner capture and evaluation."""

import json
import os
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path
import sys
from time import monotonic
from types import SimpleNamespace

from app.comparison.calculation_control import cancellation, checkpoint
from app.comparison.current_dependencies import digest, instant
from app.comparison.scanner_projection import Projection
from app.comparison.scanner_readiness import Selection
from app.dashboard.scanner_api import component_binding, scanner_marker, scanner_policy
from app.storage import scanner_latest, scanner_readiness, store
from app.storage.scanner_preparation import PreparationCache
from .continuous import rss
from .coverage_worker import MAX_PROCESS_BYTES, MAX_SECONDS
from .runtime_status import read_runtime


NATIVE_SELECTION = Selection(venues=('kalshi', 'polymarket_us'))
NATIVE_MEMBER_LIMIT = 12
NATIVE_OCCURRENCE_LIMIT = 64
CENSUS_SECONDS = 75
EVALUATION_SECONDS = 5


def capture(db, owner_id, at, *, members=None, expected_control=None):
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        owner = read_runtime(db)
        if (not owner['active'] or owner['runtime_id'] != owner_id or owner.get('global_stopped')
                or expected_control is not None and digest(scanner_latest.control(owner)) != expected_control):
            return None
        config = owner['config']
        clock = at()
        policy = scanner_policy()
        registry = PreparationCache(max_entries=1).registry(at=clock)
        selection = NATIVE_SELECTION if members else None
        frame, inputs, metadata = scanner_readiness.capture(db, config=config, authority=config.get('authority'),
            at=clock, selection=selection, members=members, _shared_facts=True,
            retain_capacity_gaps=True, component_proofs=True)
    return owner, policy, registry, frame, inputs, metadata


def calculate(captured, old, at, started):
    owner, policy, registry, frame, inputs, metadata = captured
    proof = metadata['publication_proof']
    marker = scanner_marker(proof, owner['config'], owner['states'], policy, registry)
    projection = Projection(clock=at)
    scanner = SimpleNamespace(projection=projection, marker=marker, deadline=metadata['revalidate_at'],
                              summaries=SimpleNamespace(store=None), retained_summary=None)
    if old:
        scanner.retained_summary = old['payload'].get('summary')
        scanner_latest.restore(projection, old['payload'], economics_only=True)
        if old['runtime_id'] == owner['runtime_id']:
            scanner_latest.restore_continuity(projection, old['payload'])
    projection._ingest_capture(frame, inputs, input_bytes_bound=metadata['input_bytes_bound'],
                               capture_ms=(monotonic() - started) * 1000, policy=policy,
                               bounded_census=True)
    if projection.frame is None or projection.frame['revision'] != frame['revision']:
        return None
    deadline = monotonic() + EVALUATION_SECONDS
    while projection.pending and monotonic() < deadline:
        if not projection.drain(publish=False):
            break
    projection.publish()
    return scanner


def native_candidates(frame):
    """Find complete native event membership from modeled structural pairs."""
    instruments = {instrument['id']: instrument for instrument in frame['instruments']}
    by_occurrence = defaultdict(set)
    required_venues = set(NATIVE_SELECTION.venues)
    for pair in frame['pairs']:
        legs = [instruments[key] for key in pair['legs']]
        if {leg['venue'] for leg in legs} != required_venues or not all(
                leg['model_versions'].get('native_execution') for leg in legs):
            continue
        by_occurrence[pair['occurrence_id']].update(tuple(leg['native_key'][:2]) for leg in legs)
    return {key: sorted(members) for key, members in by_occurrence.items() if len(members) <= NATIVE_MEMBER_LIMIT}


def rotated(occurrences, after):
    occurrences = sorted(occurrences)
    start = bisect_right(occurrences, after) if after else 0
    return occurrences[start:] + occurrences[:start]


def native_members(candidates, after):
    """Rotate complete event members while bounding each fresh native capture."""
    members = set()
    selected = []
    for occurrence in rotated(candidates, after):
        event_members = set(map(tuple, candidates[occurrence]))
        if len(members | event_members) > NATIVE_MEMBER_LIMIT:
            break
        members.update(event_members)
        selected.append(occurrence)
    return tuple(sorted(members)), selected


def evaluated_pairs(projection):
    return set(projection.receipts) | set(projection.partial_receipts)


def fresh_component(db, owner_id, at, old, census):
    members, selected = native_members(census['native_candidates'], census.get('native_candidate_after'))
    if not members:
        return None
    checkpoint()
    started = monotonic()
    captured = capture(db, owner_id, at, members=members, expected_control=census['control_revision'])
    if captured is None or str(captured[3]['epoch']) != census['epoch']:
        return None
    scanner = calculate(captured, old, at, started)
    if scanner is None:
        return None
    scanner.projection.census = dict(census, native_selected_occurrences=len(selected), native_candidate_after=selected[-1])
    return scanner, captured


def report(db, scanner, captured, at):
    owner, _, registry, frame, _, metadata = captured
    durable = prepare_publication(db, scanner, owner, metadata, registry, at)
    census = scanner.projection.census or dict(as_of=frame['as_of'], counts=frame['counts'],
                                                failed_occurrences=len(frame['failed_occurrences']))
    counts = census['counts']
    return dict(**durable, captured_at=census['as_of'], observed_instruments=counts['observed_instruments']['value'],
        observed_occurrences=counts['observed_occurrences']['value'], selected_scopes=counts['selected_scopes']['value'],
        failed_occurrences=census['failed_occurrences'], provider_requests=0)


def turn(db, owner_id, *, at=store.now):
    started = monotonic()
    old = scanner_latest.read(db)
    previous = old['payload'] if old and old['runtime_id'] == owner_id else {}
    previous_census = previous.get('census', {})
    if previous_census.get('native_candidates') and 0 <= (
            instant(at()) - instant(previous_census['as_of'])).total_seconds() < CENSUS_SECONDS:
        fresh = fresh_component(db, owner_id, at, old, previous_census)
        if fresh is not None:
            return report(db, *fresh, at)

    captured = capture(db, owner_id, at)
    if captured is None:
        return dict(published=False, reason='scanner_runtime_withdrawn')
    owner, _, _, frame, _, _ = captured
    scanner = calculate(captured, old, at, started)
    if scanner is None:
        return dict(published=False, reason='scanner_projection_capacity')
    candidates = native_candidates(frame)
    if candidates:
        after = previous_census.get('native_candidate_after')
        census = dict(as_of=frame['as_of'], counts=frame['counts'], scopes=frame['scopes'],
            failed_occurrences=len(frame['failed_occurrences']), native_candidate_occurrences=len(candidates),
            native_candidates={key:candidates[key] for key in rotated(candidates, after)[:NATIVE_OCCURRENCE_LIMIT]},
            native_candidate_after=after, epoch=str(frame['epoch']), control_revision=digest(scanner_latest.control(owner)))
        if not evaluated_pairs(scanner.projection):
            fresh = fresh_component(db, owner_id, at, old, census)
            if fresh is not None:
                return report(db, *fresh, at)
        scanner.projection.census = census
    return report(db, scanner, captured, at)


def prepare_publication(db, scanner, owner, metadata, registry, at):
    # New books cannot grant authority to old calculations. A full-slate
    # census remains valid as a dated measurement under this runtime and epoch.
    valid_until = scanner.deadline is None or instant(at()) < instant(scanner.deadline)
    owner_id = owner['runtime_id']
    proof = metadata['publication_proof']
    registry_now = PreparationCache(max_entries=1).registry(at=at())
    policy_unchanged = registry == registry_now and scanner.marker == scanner_marker(
        proof, owner['config'], owner['states'], scanner_policy(), registry_now)
    payload = (scanner_latest.snapshot(scanner) if valid_until and policy_unchanged
               and evaluated_pairs(scanner.projection) and not getattr(scanner.projection, 'census', None) else None)
    published = payload is not None and scanner_latest.publish_snapshot(db, payload,
        owner_id=owner_id, proof=proof, runtime_revision=owner['revision'])
    capture_only = not published
    if capture_only:
        payload = scanner_latest.snapshot(scanner, census_only=not policy_unchanged)
        instrument_witnesses = metadata['instrument_witnesses']
        pairs = {}
        if policy_unchanged:
            for key in set(payload['receipts']) | set(payload.get('partial_receipts', {})):
                legs = payload['targets'][key]['pair']['legs']
                if all(leg in instrument_witnesses for leg in legs):
                    pairs[key] = sorted({instrument_witnesses[leg] for leg in legs})
        relevant = {component for members in pairs.values() for component in members}
        witnesses = {key:value for key,value in metadata['component_witnesses'].items() if key in relevant}
        published = scanner_latest.publish_components(db, payload, owner=owner, proof=proof,
            witnesses=witnesses, pairs=pairs,
            binding=component_binding(scanner_policy(), registry_now))
        if published:
            saved = scanner_latest.read(db, payload_only=True)['payload']
            capture_only = saved['capture_only']
            return dict(published=True, capture_only=capture_only, reason=None,
                        current_receipts=len(saved['receipts']),
                        current_partial_receipts=len(saved.get('partial_receipts', {})))
    return dict(published=published, capture_only=capture_only,
                reason=None if published else 'scanner_runtime_withdrawn',
                current_receipts=len(scanner.projection.receipts) if published else 0,
                current_partial_receipts=len(scanner.projection.partial_receipts) if published else 0)




def main():
    store.ROOT = Path(sys.argv[1])
    parent = int(sys.argv[2])
    owner_id = sys.argv[3]
    started = monotonic()
    if hasattr(os, 'nice'):
        os.nice(10)

    def cancelled():
        if monotonic() - started >= MAX_SECONDS:
            raise ValueError('scanner_worker_deadline')
        if rss() >= MAX_PROCESS_BYTES:
            raise ValueError('scanner_worker_memory_capacity')
        return os.getppid() != parent

    try:
        with cancellation(cancelled), store.connect() as db:
            result = turn(db, owner_id)
        result.update(worker_seconds=round(monotonic() - started, 3), worker_peak_rss_bytes=rss())
    except Exception as exc:
        from app.diagnostics import failure_details

        result = dict(worker_error='scanner_worker_failed', worker_failure=failure_details(exc), provider_requests=0)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
