"""Read-only capacity forecast from the saved late task and receipt ledger."""
from collections import Counter, defaultdict
from datetime import timedelta
from math import ceil

from app.collection.activity_mode import OBJECTS_PER_15_MINUTES, OBJECTS_PER_DAY, monitor_schedule
from app.collection import experiment_acquisition as acquisition
from app.storage.store import stamp
from .experiment import _closure, _value, clock, late_checkpoint_bytes

SAMPLE_HOURS = 72


def _percentile(samples, fraction=.95):
    if samples:
        ordered = sorted(samples)
        return round(ordered[ceil(len(ordered) * fraction) - 1], 3)
    return None


def _elapsed(clocks, start, end):
    if clocks.get(start) and clocks.get(end):
        seconds = (stamp(clocks[end]) - stamp(clocks[start])).total_seconds()
        if seconds >= 0:
            return seconds
    return None


def _observe_stages(timings, stages, clocks):
    for label, (start, end) in stages.items():
        value = _elapsed(clocks, start, end)
        if value is not None:
            timings[label].append(value)


def _observed_batches(db, since, at):
    request_stages = dict(request_lane_wait=('claimed_at', 'lane_entered_at'),
        claim_to_batch_start=('claimed_at', 'batch_work_started_at'),
        manifest_preparation=('batch_work_started_at', 'manifest_ready_at'),
        account_usage=('usage_requested_at', 'usage_ready_at'),
        provider_response=('dispatch_at', 'response_received_at'),
        original_retention=('response_received_at', 'original_retention_finished_at'),
        parsing=('original_retention_finished_at', 'parse_finished_at'))
    event_stages = dict(calculation=('calculation_started_at', 'calculation_finished_at'),
        projection_and_compression=('calculation_finished_at', 'projection_ready_at'),
        persistence=('projection_ready_at', 'persistence_checked_at'))
    timings = defaultdict(list)
    batches = defaultdict(list)
    rows = db.execute("""SELECT p.details->'batch' batch, p.details->'timings' timings,
            p.details->>'dispatch_at' dispatch_at, p.details->>'attempt_id' attempt_id,
            p.state
        FROM public.market_pull p
        WHERE p.requested_at BETWEEN %s AND %s AND p.details ? 'batch'
          AND p.details ? 'attempt_id'""", (since, at))
    event_samples = 0
    for row in rows:
        timings_for_event = dict(row['timings'] or {}, dispatch_at=row['dispatch_at'])
        checked = timings_for_event.get('persistence_checked_at')
        received = timings_for_event.get('response_received_at')
        if (checked and stamp(checked) > at) or (received and stamp(received) > at):
            continue
        batches[row['attempt_id']].append((row['batch']['size'], row['state'], timings_for_event))
        if row['state'] not in ('complete', 'partial'):
            continue
        event_samples += 1
        _observe_stages(timings, event_stages, timings_for_event)

    durations = defaultdict(list)
    for members in batches.values():
        request_clocks = members[0][2]
        _observe_stages(timings, request_stages, request_clocks)
        size = members[0][0]
        if len(members) != size or any(state not in ('complete', 'partial')
                                      or not t.get('persistence_checked_at') or not t.get('batch_work_started_at')
                                      for _, state, t in members):
            continue
        start = min(stamp(t['batch_work_started_at']) for _, _, t in members)
        end = max(stamp(t['persistence_checked_at']) for _, _, t in members)
        durations[size].append((end - start).total_seconds())
    return dict(samples=event_samples, observed_physical_requests=len(batches),
        batch_timings=[dict(events=size, samples=len(values), service_p95_seconds=_percentile(values))
                       for size, values in sorted(durations.items())],
        stage_p95_seconds={label: _percentile(timings[label]) for label in request_stages | event_stages})


def _windows(db, at, headroom_bytes, observed):
    rows = db.execute("""SELECT late.target_at,late.deadline_at,game.policy_id,game.event->>'league' league,
        coalesce(game.event->>'league'='NCAAB',false) is_ncaab,
        coalesce(early.state IN ('pending','claimed'),false) early_work_pending,
        late.state='claimed' already_claimed, game.late_reserved_bytes reserved_bytes
        FROM public.ev_experiment_task late JOIN public.ev_experiment_game game ON game.id=late.game_id
        LEFT JOIN public.ev_experiment_task early ON early.game_id=late.game_id AND early.checkpoint='early'
        WHERE late.checkpoint='late' AND late.state IN ('pending','claimed')
          AND late.target_at<=%s AND late.deadline_at>=%s
        ORDER BY late.deadline_at,late.target_at,late.game_id""", (at + timedelta(days=1), at)).fetchall()
    shape_by_policy = {}
    for identity in {row['policy_id'] for row in rows}:
        try:
            policies = _closure(db, [identity])
            scope = _value(policies[identity], policies)['requested_scope']
            shape_by_policy[identity] = acquisition.request_shape(dict(event=dict(source_event_id='forecast'),
                checkpoint='late', requested_scope=scope))
        except (KeyError, TypeError, ValueError):
            # An unreadable policy cannot prove compatibility with any peer.
            pass

    grouped = defaultdict(list)
    for row in rows:
        grouped[row['target_at'], row['deadline_at']].append(row)
    non_late = db.execute("""SELECT target_at,deadline_at,state FROM public.ev_experiment_task
        WHERE checkpoint<>'late' AND state IN ('pending','claimed') AND target_at<=%s AND deadline_at>=%s""",
        (at + timedelta(days=1, seconds=acquisition.REQUEST_RESERVATION_SECONDS), at)).fetchall()
    ordinary = db.execute("SELECT settings FROM public.activity_mode WHERE singleton").fetchone()
    monitor_settings = ordinary['settings'] if ordinary else None

    # Windows share the one physical request lane. Use same-size measurements
    # and model spillover only as far as the observed durations permit.
    duration_by_size = {row['events']: row['service_p95_seconds'] for row in observed['batch_timings']}
    lane_available = unknown_until = at
    claim_limit = acquisition.LATE_BATCH_SIZE
    for (target, deadline), group in grouped.items():
        batch_sizes = []
        unverified = 0
        for offset in range(0, len(group), claim_limit):
            shapes = Counter(shape_by_policy.get(row['policy_id']) for row in group[offset:offset + claim_limit])
            missing_shapes = shapes.pop(None, 0)
            unverified += missing_shapes
            batch_sizes.extend(shapes.values())
            batch_sizes.extend([1] * missing_shapes)
        durations = [duration_by_size.get(size) for size in batch_sizes]
        service = None if unverified or any(value is None for value in durations) else round(sum(durations), 3)
        opens = max(target, at)
        known_wait = (max(opens, lane_available) - opens).total_seconds()
        competing_unknown = unknown_until > opens
        if service is None or competing_unknown:
            unknown_until = max(unknown_until, deadline)
            complete = None
        else:
            lane_available = max(opens, lane_available) + timedelta(seconds=service)
            complete = lane_available
        seconds_available = (deadline - opens).total_seconds()
        risk = ('request_scope_unverified' if unverified else
                'batch_size_latency_unmeasured' if service is None else
                'competing_window_latency_unmeasured' if competing_unknown else
                'insufficient_measured_service_runway' if complete > deadline else 'within_estimated_runway')

        lead_starts = target - timedelta(seconds=acquisition.REQUEST_RESERVATION_SECONDS)
        deferred = [task for task in non_late if task['deadline_at'] >= lead_starts
                    and task['target_at'] <= deadline]
        monitor_slot = (stamp(monitor_schedule(monitor_settings, at=deadline)['current_slot_at'])
                        if monitor_settings else None)
        unreserved = sum(row['reserved_bytes'] == 0 for row in group)
        top_ups = [late_checkpoint_bytes(row['league']) - row['reserved_bytes'] for row in group
                   if not row['already_claimed'] and row['reserved_bytes'] < late_checkpoint_bytes(row['league'])]
        minimum_top_up = min(top_ups, default=0)
        tasks = len(group)
        yield dict(target_at=clock(target), deadline_at=clock(deadline), scheduled_tasks=tasks,
            ncaab_tasks=sum(row['is_ncaab'] for row in group),
            early_work_pending=sum(row['early_work_pending'] for row in group),
            already_claimed=sum(row['already_claimed'] for row in group),
            tasks_with_unverified_request_scope=unverified,
            planned_event_requests=len(batch_sizes), planned_batch_sizes=sorted(batch_sizes, reverse=True),
            maximum_event_requests=tasks, maximum_event_objects=tasks,
            reserved_bytes=int(sum(row['reserved_bytes'] for row in group)),
            tasks_without_storage_reservation=unreserved,
            unreserved_admission_floor_bytes=minimum_top_up,
            estimated_storage_top_up_bytes=sum(top_ups),
            current_headroom_below_unreserved_claim_floor=headroom_bytes < minimum_top_up,
            competing_non_late_tasks=len(deferred), competing_claimed_non_late_tasks=sum(
                task['state'] == 'claimed' for task in deferred),
            ordinary_discovery_slot_at=clock(monitor_slot) if monitor_slot and monitor_slot >= lead_starts else None,
            seconds_available=seconds_available, measured_competing_lane_seconds=round(known_wait, 3),
            estimated_window_service_p95_seconds=service, estimated_completion_at=clock(complete) if complete else None,
            risk=risk)


def late_capture_forecast(db, *, at, headroom_bytes):
    since = at - timedelta(hours=SAMPLE_HOURS)
    # Keep legacy successful-task context visible while the new shared request
    # estimates build their own empirical batch-size distribution.
    measurements = db.execute("""WITH timing AS (
        SELECT EXTRACT(EPOCH FROM t.claimed_at-t.target_at)::float AS queue_seconds,
               EXTRACT(EPOCH FROM t.updated_at-t.claimed_at)::float AS service_seconds
          FROM public.ev_experiment_task t JOIN public.ev_experiment_record r ON r.id=t.result_id
         WHERE t.checkpoint='late' AND t.state='captured' AND t.claimed_at IS NOT NULL
           AND t.updated_at BETWEEN %s AND %s
        )
        SELECT count(*) AS samples,
          percentile_disc(0.5) WITHIN GROUP (ORDER BY service_seconds) AS service_median_seconds,
          percentile_disc(0.95) WITHIN GROUP (ORDER BY service_seconds) AS service_p95_seconds,
          percentile_disc(0.95) WITHIN GROUP (ORDER BY queue_seconds) AS queue_p95_seconds
        FROM timing""", (since, at)).fetchone()
    observed = _observed_batches(db, since, at)
    windows = list(_windows(db, at, headroom_bytes, observed))
    account = db.execute("""SELECT runtime.heartbeat_at, panel#>>'{metrics,provider_usage,at}' usage_observed_at,
            panel#>'{metrics,objects,requests_per_minute}' requests_per_minute,
            panel#>'{metrics,objects,available}' available_objects,
            panel#>'{metrics,objects,held}' held_objects,
            panel#>'{metrics,objects,interrupted}' interrupted_objects,
            panel#>'{metrics,experiment_rate_capacity}' rolling_request_slots
        FROM public.data_runtime runtime
        CROSS JOIN LATERAL jsonb_array_elements(runtime.status->'sources') AS panel
        WHERE runtime.heartbeat_at<=%s AND panel->>'provider'='sportsgameodds' LIMIT 1""", (at,)).fetchone()
    if account:
        account = dict(account, heartbeat_at=clock(account['heartbeat_at']))
    return dict(as_of=clock(at), permitted_in_flight_event_requests=1,
        maximum_events_per_request=acquisition.LATE_BATCH_SIZE,
        provider_account_observation=account,
        provider_shape='one physical exact-ID request for games sharing a window and identical request filters',
        operating_object_caps=dict(per_15_minutes=OBJECTS_PER_15_MINUTES, per_24_hours=OBJECTS_PER_DAY),
        ordinary_request_handoff_lead_seconds=acquisition.REQUEST_RESERVATION_SECONDS,
        paid_retry_allowance=0, retry_rule='only a local pre-dispatch rate refusal may wait within the same window',
        unreserved_research_headroom_bytes=headroom_bytes,
        latency=dict(measurements, sample_hours=SAMPLE_HOURS, outcomes='successful frozen late tasks across execution models'),
        current_execution_latency=dict(observed, sample_hours=SAMPLE_HOURS),
        forecast_limitations=('Measured service uses successful fully published batches of the same sizes. '
            'Claim polling, an in-flight ordinary page or shared writer, and local rate waits can consume additional runway. '
            'Planning includes all declared late tasks, including any currently claimed members. '
            'Pending tasks below their league storage estimate use shared headroom at claim. '
            'Account, controls, early baselines and storage are rechecked at execution.'),
        windows=windows)
