"""Read-only capacity forecast from the saved late task and checkpoint ledger."""
from datetime import timedelta

from app.collection.activity_mode import OBJECTS_PER_15_MINUTES, OBJECTS_PER_DAY
from app.collection.experiment_acquisition import REQUEST_RESERVATION_SECONDS
from .experiment import MIN_CHECKPOINT_RUNWAY, clock


def late_capture_forecast(db, *, at, headroom_bytes):
    measurements = db.execute("""WITH timing AS (
        SELECT EXTRACT(EPOCH FROM t.claimed_at-t.target_at)::float AS queue_seconds,
               EXTRACT(EPOCH FROM t.updated_at-t.claimed_at)::float AS service_seconds,
               (r.payload#>>'{summary,requested_at}')::timestamptz requested_at,
               (r.payload#>>'{summary,received_at}')::timestamptz received_at,
               (r.payload#>>'{summary,known_at}')::timestamptz known_at,
               r.recorded_at
          FROM public.ev_experiment_task t JOIN public.ev_experiment_record r ON r.id=t.result_id
         WHERE t.checkpoint='late' AND t.state='captured' AND t.claimed_at IS NOT NULL
           AND t.updated_at BETWEEN %s AND %s
        )
        SELECT count(*) AS samples,
          percentile_disc(0.5) WITHIN GROUP (ORDER BY service_seconds) AS service_median_seconds,
          percentile_disc(0.95) WITHIN GROUP (ORDER BY service_seconds) AS service_p95_seconds,
          percentile_disc(0.95) WITHIN GROUP (ORDER BY queue_seconds) AS queue_p95_seconds,
          percentile_disc(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM received_at-requested_at)::float)
            FILTER(WHERE requested_at IS NOT NULL AND received_at IS NOT NULL) AS provider_response_p95_seconds,
          percentile_disc(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM known_at-received_at)::float)
            FILTER(WHERE known_at IS NOT NULL AND received_at IS NOT NULL) AS processing_p95_seconds,
          percentile_disc(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM recorded_at-known_at)::float)
            FILTER(WHERE known_at IS NOT NULL) AS checkpoint_write_p95_seconds
          FROM timing""", (at-timedelta(days=3), at)).fetchone()

    windows = []
    for row in db.execute("""SELECT late.target_at,late.deadline_at,count(*) tasks,
        count(*) FILTER(WHERE game.event->>'league'='NCAAB') ncaab_tasks,
        count(*) FILTER(WHERE early.state IN ('pending','claimed')) early_work_pending,
        sum(game.late_reserved_bytes) reserved_bytes,
        count(*) FILTER(WHERE game.late_reserved_bytes=0) without_storage_reservation
        FROM public.ev_experiment_task late JOIN public.ev_experiment_game game ON game.id=late.game_id
        LEFT JOIN public.ev_experiment_task early ON early.game_id=late.game_id AND early.checkpoint='early'
        WHERE late.checkpoint='late' AND late.state IN ('pending','claimed')
          AND late.target_at<=%s AND late.deadline_at>=%s
        GROUP BY late.target_at,late.deadline_at ORDER BY late.target_at,late.deadline_at""",
        (at + timedelta(days=1), at)):
        tasks = row['tasks']
        remaining = (row['deadline_at'] - max(at, row['target_at'])).total_seconds()
        service = measurements['service_p95_seconds']
        estimated = round(service * tasks, 3) if service is not None else None
        windows.append(dict(target_at=clock(row['target_at']), deadline_at=clock(row['deadline_at']),
            scheduled_tasks=tasks, ncaab_tasks=row['ncaab_tasks'],
            early_work_pending=row['early_work_pending'], maximum_event_requests=tasks,
            maximum_event_objects=tasks, reserved_bytes=int(row['reserved_bytes']),
            tasks_without_storage_reservation=row['without_storage_reservation'],
            unreserved_admission_floor_bytes=row['without_storage_reservation'] * MIN_CHECKPOINT_RUNWAY,
            seconds_available=remaining, estimated_serial_service_p95_seconds=estimated,
            risk=('insufficient_measured_service_runway' if estimated is not None and estimated > remaining
                  else 'within_estimated_runway' if estimated is not None else 'latency_unmeasured')))

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
        provider_account_observation=account,
        provider_shape='one explicit event per request; cursor does not paginate within that event',
        operating_object_caps=dict(per_15_minutes=OBJECTS_PER_15_MINUTES, per_24_hours=OBJECTS_PER_DAY),
        ordinary_request_handoff_lead_seconds=REQUEST_RESERVATION_SECONDS,
        paid_retry_allowance=0, retry_rule='only a local pre-dispatch rate refusal may wait within the same window',
        unreserved_research_headroom_bytes=headroom_bytes,
        latency=dict(measurements, sample_hours=72, outcomes='successful frozen late tasks'),
        forecast_limitations='success-only history; per-window p95 estimate excludes new writer or ordinary page contention; fresh account and storage checks still apply',
        windows=windows)
