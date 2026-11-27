"""Passive capture guard estimates and durable historical gap counts."""

from app.collection.current_storage_policy import SQL_BYTE_CAP, MIB, disk_capacity, sql_usage
from app.collection.runtime_status import read_runtime
from app.storage.store import ROOT
from . import records
from .experiment import MIN_CHECKPOINT_RUNWAY


def report(db, experiment):
    at = db.execute('SELECT transaction_timestamp() AS at').fetchone()['at']
    owner = read_runtime(db, at, ordinary_authority=True)
    storage = experiment['storage']
    database_bytes = sql_usage(db)
    disk = disk_capacity(ROOT / '.local/postgres', MIN_CHECKPOINT_RUNWAY * 3)
    dispositions = records.retention_disposition_summary(db)
    accounting = records.retention_accounting(db)
    latest = db.execute('''SELECT max(last_refused_at) AS last_refused_at,
        count(*) FILTER (WHERE checkpoint IN ('early','late') AND state='missed') AS missed_checkpoints
        FROM public.ev_experiment_task WHERE checkpoint IN ('early','late','outcome')''').fetchone()

    blockers = []

    def block(code, message, section):
        blockers.append(dict(code=code, message=message, settings_url='/settings#' + section))

    collection = 'running'
    if owner.get('global_stopped'):
        collection = 'stopped'
        block('collection_stopped', 'Collection is stopped in Settings.', 'collection')
    elif 'sportsgameodds' in owner.get('paused_sources', ()):
        collection = 'paused'
        block('source_paused', 'SportsGameOdds is paused.', 'sources')
    elif not owner['healthy']:
        collection = 'unavailable'
        block('collector_unavailable', 'The collection service has no current heartbeat.', 'collection')
    elif not owner['config'].get('enabled') or not owner['dispatch']:
        collection = 'waiting'
        block('collector_not_dispatching', 'The collection service is waiting to dispatch.', 'collection')
    elif (owner['config'].get('aggregate_enabled') is False
          or owner['config'].get('aggregate_provider') not in (None, 'sportsgameodds')):
        collection = 'unavailable'
        block('research_source_unavailable', 'This research workflow requires the SportsGameOdds source.', 'sources')

    available = storage['remaining_bytes']
    # Early and outcome claims check this minimum. Late claims use the storage
    # estimate for their league and can consume their own reservation.
    if available < MIN_CHECKPOINT_RUNWAY:
        block('research_retention_capacity', 'Unreserved research capacity is too low for a new checkpoint.', 'storage')
    if database_bytes + MIN_CHECKPOINT_RUNWAY * 3 + 8 * MIB > SQL_BYTE_CAP:
        block('research_sql_runway', 'The database guard has too little headroom for a new checkpoint.', 'storage')
    if not disk['available']:
        block('current_observation_disk_free_floor', 'The host disk guard has too little headroom for a new checkpoint.', 'storage')
    if experiment['games'] >= storage['max_games']:
        block('experiment_game_capacity', 'The tracked-game limit has been reached. Existing games can still advance.', 'storage')

    mean = storage['mean_complete_game_payload_bytes']
    limited = mean is not None and available < mean
    missed = latest['missed_checkpoints']
    return dict(
        state='blocked' if blockers else 'limited' if limited else 'ready', observed_at=at,
        blockers=blockers, collection=dict(state=collection, heartbeat_at=owner.get('heartbeat_at')),
        retention=dict(
            remaining_bytes=available, byte_cap=storage['byte_cap'], database_bytes=database_bytes,
            database_byte_cap=SQL_BYTE_CAP, disk_free_bytes=disk['free_bytes'], disk_floor_bytes=disk['floor_bytes'],
            protected_late_bytes=storage['late_reserved_bytes'], tracked_games=experiment['games'],
            max_tracked_games=storage['max_games'], missed_checkpoints=missed,
            discovery_refusals=experiment['discovery_refusals'], declaration_refusals=accounting['declaration_refusals'],
            checkpoint_refusals=sum(row['refusals'] for row in experiment['tasks']),
            last_checkpoint_refused_at=latest['last_refused_at'],
            observation_refusals=dispositions['observation_refusals'], capture_refusals=dispositions['capture_refusals'],
            observation_open_gaps=dispositions['observation_open_gaps'], capture_open_gaps=dispositions['capture_open_gaps'],
            historical_gap_started_at=accounting['prior_first_observed_refusal_at'],
            historical_gap_attempts=accounting['prior_refused_attempts'],
        ),
    )
