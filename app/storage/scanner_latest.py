"""Bounded latest scanner publication shared across local processes.

Only typed readiness, compact economics and bounded continuity are persisted.
Quote/model/depth inputs remain in current SQL and are captured for selection.
"""
from collections import OrderedDict, deque
from copy import deepcopy
from threading import RLock

from psycopg.types.json import Jsonb

from app.comparison.current_dependencies import digest, encoded_size
from app.storage.current_rows import LOCK
from app.storage.scanner_publication import current_revision
from app.storage.store import encoded

MAX_BYTES = 32 * 1024 * 1024
FIELDS = ('server_id','epoch','generation','publication','frame','targets','rows','receipts',
          'state','errors','stopped','evaluations','reuses','last_capture_ms','published_at',
          'capture_revision','sql_observation','cache')
TRANSITIONS = ('sequence','floor','history','bytes','previous','pairs','episodes',
               'last_improvement','context','censored')


def summary_snapshot(worker):
    store = worker.store
    if store is None:
        return None
    with store.lock:
        return deepcopy(dict(records=store.records, latest=store.latest, meta=store.meta,
            failed=worker.error or store.failed, max_bytes=store.max_bytes,
            max_episodes=store.max_episodes, retention_seconds=store.retention_seconds,
            physical_bytes=store._physical()))


def snapshot(scanner):
    p = scanner.projection
    with p.lock:
        value = {k:deepcopy(getattr(p,k)) for k in FIELDS}
        value['pending'] = list(p.pending)
        value['policy'] = p.policy.to_dict()
        value['members'] = {k:[v['quote']['source']['provider'],v['quote']['source']['native_event_id']]
                            for k,v in p.inputs.items()}
        value['transitions'] = {k:deepcopy(getattr(p.transitions,k)) for k in TRANSITIONS}
        value['transitions']['pairs'] = sorted(value['transitions']['pairs'])
        value['transitions']['history'] = list(value['transitions']['history'])
        value['transitions']['context'] = list(value['transitions']['context']) if value['transitions']['context'] else None
        value['summary'] = summary_snapshot(scanner.summaries)
        value['deadline'] = scanner.deadline
        value['source_marker'] = scanner.marker
    from app.comparison.readiness_encoding import compact
    value['frame'] = compact(value['frame'])
    if encoded_size(value) > MAX_BYTES:
        raise ValueError('scanner_latest_capacity')
    return value


def publish(db, scanner, *, proof, runtime_revision, capture_only=False):
    """Serialized final compare-and-publish against ingress and control state."""
    from app.collection.runtime_status import read_runtime
    from app.storage.current_games import utc
    from app.collection.current_storage_policy import require_disk_space, sql_usage, SQL_BYTE_CAP
    from app.storage.store import ROOT
    payload = snapshot(scanner)
    if capture_only:
        if payload['frame'] is None or str(payload['frame']['epoch'])!=str(proof['epoch']):return False
        payload.update(capture_only=True,source_marker=None,state='unavailable',
            rows={},receipts={},cache={},targets={},pending=[],members={},
            errors=['captured_inputs_changed'],stopped=False)
    size=encoded_size(payload)
    with db.transaction():
        # All ordinary current-row writers use this same transaction lock.
        db.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
        from app.collection.runtime_status import AUTHORITY_LOCK
        db.execute('SELECT pg_advisory_xact_lock_shared(%s)',(AUTHORITY_LOCK,))
        runtime = read_runtime(db)
        withdrawal=(payload['stopped'] and not payload['rows'] and not payload['receipts'] and not payload['cache'])
        if (not runtime['healthy'] or (not runtime['active'] and not withdrawal)
                or runtime['runtime_id'] != scanner.provider.runtime_id
                or runtime['revision'] != runtime_revision
                or (current_revision(db) != proof and not capture_only)):
            return False
        if capture_only and str(current_revision(db)['epoch'])!=str(proof['epoch']):return False
        require_disk_space(ROOT/'.local/postgres',append_bytes=size)
        if sql_usage(db)+size >= SQL_BYTE_CAP:
            raise ValueError('scanner_sql_storage_guard')
        db.execute('''INSERT INTO scanner_latest VALUES(true,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(singleton) DO UPDATE SET runtime_id=excluded.runtime_id,
            runtime_revision=excluded.runtime_revision,dependency_revision=excluded.dependency_revision,
            publication=excluded.publication,published_at=excluded.published_at,payload=excluded.payload
            WHERE scanner_latest.payload IS DISTINCT FROM excluded.payload
               OR scanner_latest.runtime_revision<>excluded.runtime_revision''',
            (runtime['runtime_id'],runtime_revision,digest(proof),scanner.projection.publication,utc(),Jsonb(payload)))
    return True


def restore(projection, value, *, economics_only=False):
    """A restarted worker may reuse economics only after fresh SQL ingestion."""
    if economics_only:
        projection.epoch = value['epoch']
        projection.cache = deepcopy(value['cache'])
        return
    from app.comparison.readiness_encoding import expand
    value = dict(value, frame=expand(value['frame']))
    from app.comparison.estimated_policy import EstimatePolicy
    with projection.lock:
        for name in FIELDS:
            setattr(projection,name,deepcopy(value[name]))
        projection.policy = EstimatePolicy.from_dict(value['policy'])
        projection.pending = OrderedDict((k,projection.targets[k]) for k in value['pending'] if k in projection.targets)
        projection.inputs = {}
        for name,item in value['transitions'].items():
            if name == 'history':item = deque(item)
            elif name == 'pairs':item = set(item)
            elif name == 'context' and item is not None:item = tuple(item)
            setattr(projection.transitions,name,deepcopy(item))
        projection._clear_display()


class SummaryReader:
    def __init__(self, reader):
        self.reader = reader

    def read(self, **kwargs):
        from app.comparison.scanner_summaries import SummaryStore, MAX_BYTES as CAP, MAX_EPISODES, RETENTION_SECONDS
        self.reader.refresh()
        value = self.reader.value.get('summary') if self.reader.value else None
        blank = object.__new__(SummaryStore)
        blank.lock = RLock(); blank.fd = None
        blank.records = {} if value is None else deepcopy(value['records'])
        blank.latest = None if value is None else deepcopy(value['latest'])
        blank.max_bytes = CAP if value is None else value['max_bytes']
        blank.max_episodes = MAX_EPISODES if value is None else value['max_episodes']
        blank.retention_seconds = RETENTION_SECONDS if value is None else value['retention_seconds']
        blank.meta = (dict(first=None,last=None,lost=True,complete_publications=0,gaps=1,evicted=0,high_water=0)
                      if value is None else deepcopy(value['meta']))
        unavailable = self.reader.stopped()
        blank.failed = ('summary_background_unavailable' if unavailable else
                        'summary_initializing' if value is None else value['failed'])
        blank._physical = lambda: 0 if value is None else value['physical_bytes']
        result = blank.read(**kwargs)
        collection_stopped = self.reader.collection_stopped
        if unavailable or (result['state']=='stopped' and not collection_stopped):
            # A retained Stop observation describes that old summary. Only the
            # current runtime's explicit latch can establish collection Stop.
            state = 'stopped' if collection_stopped else 'unavailable'
            result['state'] = state
            result['coverage']['state'] = state
        return result
