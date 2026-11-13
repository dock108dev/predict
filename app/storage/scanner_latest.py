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


def read(db, *, payload_only=False):
    projection = 'facts AS payload' if payload_only else '''scanner_runtime_id AS runtime_id,
        scanner_runtime_revision AS runtime_revision, revision AS dependency_revision,
        generation AS publication, scanner_published_at AS published_at, facts AS payload'''
    return db.execute(f"""SELECT {projection} FROM comparison_publication
        WHERE kind='scanner' AND id=''""").fetchone()


def payload_size(db):
    row = db.execute("""SELECT octet_length(facts::text) AS size FROM comparison_publication
        WHERE kind='scanner' AND id=''""").fetchone()
    return row['size'] if row else 0


def withdraw(db, runtime_id):
    db.execute('''DELETE FROM comparison_publication WHERE kind='scanner' AND id=''
        AND scanner_runtime_id=%s''', (runtime_id,))


def summary_snapshot(worker):
    store = worker.store
    if store is None:
        return None
    with store.lock:
        return deepcopy(dict(records=store.records, latest=store.latest, meta=store.meta,
            failed=worker.error or store.failed, max_bytes=store.max_bytes,
            max_episodes=store.max_episodes, retention_seconds=store.retention_seconds,
            physical_bytes=store._physical()))


def update_summary(db, row, summary):
    """Attach bounded summary evidence only to the publication it observed."""
    if summary is None:
        return
    db.execute('''UPDATE comparison_publication SET facts=jsonb_set(facts,'{summary}',%s::jsonb)
        WHERE kind='scanner' AND id='' AND scanner_runtime_id=%s AND generation=%s
          AND scanner_published_at=%s
          AND octet_length(facts::text)+octet_length(%s::jsonb::text)<=33554432''',
        (Jsonb(summary), row['runtime_id'], row['publication'], row['published_at'], Jsonb(summary)))


def observe_publication(db, owner_id, summary_worker):
    from app.comparison.scanner_projection import Projection
    from app.comparison.scanner_summaries import observation

    row = read(db)
    if row is None or row['runtime_id'] != owner_id:
        return
    payload = row['payload']
    projection = Projection()
    restore(projection, payload)
    projection.published_at = row['published_at'].isoformat()
    reason = 'capture_failed' if payload.get('capture_only') else 'evaluated'
    summary_worker.offer(observation(projection, reason))
    if summary_worker.flush():
        update_summary(db, row, summary_snapshot(summary_worker))


def snapshot(scanner, *, census_only=False):
    p = scanner.projection
    with p.lock:
        withheld = {'rows', 'receipts', 'cache', 'targets'} if census_only else set()
        value = {k:{} if k in withheld else deepcopy(getattr(p,k)) for k in FIELDS}
        value['pending'] = [] if census_only else list(p.pending)
        value['partial_receipts'] = {} if census_only else deepcopy(p.partial_receipts)
        if p.census is not None:
            value['census'] = deepcopy(p.census)
        value['policy'] = p.policy.to_dict()
        value['members'] = {} if census_only else {
            k:[v['quote']['source']['provider'],v['quote']['source']['native_event_id']]
            for k,v in p.inputs.items()}
        value['transitions'] = {k:deepcopy(getattr(p.transitions,k)) for k in TRANSITIONS}
        value['transitions']['pairs'] = sorted(value['transitions']['pairs'])
        value['transitions']['history'] = list(value['transitions']['history'])
        value['transitions']['context'] = list(value['transitions']['context']) if value['transitions']['context'] else None
        value['summary'] = summary_snapshot(scanner.summaries) or getattr(scanner, 'retained_summary', None)
        value['deadline'] = scanner.deadline
        value['source_marker'] = scanner.marker
    from app.comparison.readiness_encoding import compact
    value['frame'] = compact(value['frame'])
    if encoded_size(value) > MAX_BYTES:
        raise ValueError('scanner_latest_capacity')
    return value


def publish(db, scanner, *, proof, runtime_revision, capture_only=False):
    """Serialized final compare-and-publish against ingress and control state."""
    payload = snapshot(scanner, census_only=capture_only)
    if capture_only:
        if payload['frame'] is None or str(payload['frame']['epoch'])!=str(proof['epoch']):return False
        payload.update(capture_only=True,source_marker=None,state='unavailable',
                       errors=['captured_inputs_changed'],stopped=False)
    return _publish(db, payload, owner_id=scanner.provider.runtime_id, proof=proof,
                    runtime_revision=runtime_revision, capture_only=capture_only)


def publish_components(db, payload, *, owner, proof, witnesses, pairs, binding):
    """Publish a captured slate with authority limited to exact retained components."""
    payload = dict(payload, component_authority=dict(witnesses=witnesses, pairs=pairs, binding=binding))
    capture_control = control(owner)
    payload['capture_control_revision'] = digest(capture_control)
    payload['capture_runtime_revision'] = owner['revision']
    if payload.get('partial_receipts'):
        payload['component_authority']['native_source_health'] = native_source_health(owner)
    return _publish(db, payload, owner_id=owner['runtime_id'], proof=proof, runtime_revision=owner['revision'],
                    capture_only=True, capture_control=capture_control)


def publish_snapshot(db, payload, *, owner_id, proof, runtime_revision):
    return _publish(db, payload, owner_id=owner_id, proof=proof, runtime_revision=runtime_revision,
                    capture_only=False)


def control(owner):
    return {key:owner.get(key) for key in ('config','active','global_stopped','paused_sources')}


def native_source_health(owner):
    states = owner['states']
    return {venue:{field:states.get(venue,{}).get(field) for field in ('state','reason_code')}
            for venue in ('kalshi','polymarket_us')}


def _publish(db, payload, *, owner_id, proof, runtime_revision, capture_only, capture_control=None):
    from app.collection.runtime_status import AUTHORITY_LOCK, read_runtime
    from app.storage.current_games import utc
    from app.collection.current_storage_policy import require_disk_space, sql_usage, SQL_BYTE_CAP
    from app.storage.store import ROOT

    size=encoded_size(payload)
    if size > MAX_BYTES:
        raise ValueError('scanner_latest_capacity')
    with db.transaction():
        # All ordinary current-row writers use this same transaction lock.
        db.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
        db.execute('SELECT pg_advisory_xact_lock_shared(%s)',(AUTHORITY_LOCK,))
        runtime = read_runtime(db)
        withdrawal = payload['stopped'] and not any(
            payload.get(field) for field in ('rows', 'receipts', 'partial_receipts', 'cache'))
        same_revision = runtime['revision'] == runtime_revision
        if (not runtime['healthy'] or (not runtime['active'] and not withdrawal)
                or runtime['runtime_id'] != owner_id
                or (not same_revision and (capture_control is None or control(runtime) != capture_control))
                or (current_revision(db) != proof and not capture_only)):
            return False
        if capture_only:
            if str(db.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch']) != str(proof['epoch']):
                return False
            if 'component_authority' in payload:
                retain_components(db, payload, at=utc(), authorized=same_revision, runtime=runtime)
                size = encoded_size(payload)
        require_disk_space(ROOT/'.local/postgres',append_bytes=size)
        if sql_usage(db)+size >= SQL_BYTE_CAP:
            raise ValueError('scanner_sql_storage_guard')
        db.execute('''INSERT INTO comparison_publication
            (kind,id,scanner_runtime_id,scanner_runtime_revision,revision,generation,scanner_published_at,facts)
            VALUES('scanner','',%s,%s,%s,%s,%s,%s)
            ON CONFLICT(kind,id) DO UPDATE SET scanner_runtime_id=excluded.scanner_runtime_id,
            scanner_runtime_revision=excluded.scanner_runtime_revision,revision=excluded.revision,
            generation=excluded.generation,scanner_published_at=excluded.scanner_published_at,facts=excluded.facts
            WHERE comparison_publication.facts IS DISTINCT FROM excluded.facts
               OR comparison_publication.scanner_runtime_id<>excluded.scanner_runtime_id
               OR comparison_publication.scanner_runtime_revision<>excluded.scanner_runtime_revision''',
            (owner_id,runtime['revision'],digest(proof),payload['publication'],utc(),Jsonb(payload)))
    return True


def retain_components(db, payload, *, at, authorized=True, runtime=None):
    """Discard only receipts whose complete input witness or deadline changed."""
    from app.comparison.current_dependencies import instant
    from .scanner_component import changed

    authority = payload['component_authority']
    moment = instant(at)
    partial = payload.get('partial_receipts', {})
    same_control = (runtime is not None and payload.get('capture_control_revision') == digest(control(runtime))
                    and authority.get('native_source_health') == native_source_health(runtime))
    unavailable = changed(db, authority['witnesses']) if authorized or same_control else set(authority['witnesses'])
    before = set(payload['receipts']) | set(partial)
    keep = {key for key in before if (authorized or same_control and key in partial)
            and key in authority['pairs'] and key in payload['targets']
            and not unavailable.intersection(authority['pairs'][key])
            and instant(payload['targets'][key]['pair']['expires_at']) > moment}
    payload['receipts'] = {key:value for key,value in payload['receipts'].items() if key in keep}
    payload['partial_receipts'] = {key:value for key,value in partial.items() if key in keep}
    payload['rows'] = {key:row for key,row in payload['rows'].items() if row['pair_id'] in keep}
    payload['targets'] = {key:value for key,value in payload['targets'].items() if key in keep}
    payload['pending'] = []
    payload['cache'] = {key:value for key,value in payload['cache'].items() if key in keep}
    needed = {leg for target in payload['targets'].values() for leg in target['pair']['legs']}
    payload['members'] = {key:value for key,value in payload['members'].items() if key in needed}
    pairs = {key:value for key,value in authority['pairs'].items() if key in keep}
    active = {component for components in pairs.values() for component in components}
    payload['component_authority'] = dict(pairs=pairs, binding=authority['binding'],
        witnesses={key:value for key,value in authority['witnesses'].items() if key in active})
    if authority.get('native_source_health') is not None:
        payload['component_authority']['native_source_health'] = authority['native_source_health']
    payload['capture_only'] = not bool(keep)
    # The slate's coverage is dated. Current authority is only the witnessed
    # subset, so no stale or missing component can become a checked-zero slate.
    payload['state'] = 'partial' if keep else 'not_evaluated'
    if not authorized and not same_control and not keep:
        payload['errors'] = ['scanner_runtime_sources_changed']
    elif before != keep:
        payload['errors'] = sorted(set([*payload['errors'],'scanner_component_inputs_changed']))[:32]
    elif not payload.get('errors'):
        payload['errors'] = ['scanner_as_of_census']
    if before != keep:
        censor_transitions(payload)


def censor_transitions(payload):
    from app.comparison.scanner_transitions import Transitions

    transitions = Transitions()
    transitions.sequence = payload['transitions']['sequence']
    transitions.censor('coverage_gap')
    payload['transitions'] = {name:getattr(transitions,name) for name in TRANSITIONS}
    payload['transitions']['history'] = []
    payload['transitions']['pairs'] = []


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
        projection.partial_receipts = deepcopy(value.get('partial_receipts', {}))
        projection.census = deepcopy(value.get('census'))
        projection.policy = EstimatePolicy.from_dict(value['policy'])
        projection.pending = OrderedDict((k,projection.targets[k]) for k in value['pending'] if k in projection.targets)
        projection.inputs = {}
        for name,item in value['transitions'].items():
            if name == 'history':item = deque(item)
            elif name == 'pairs':item = set(item)
            elif name == 'context' and item is not None:item = tuple(item)
            setattr(projection.transitions,name,deepcopy(item))
        projection._clear_display()


def restore_continuity(projection, value):
    """Carry the current runtime's publication clock and bounded transition evidence."""
    from app.comparison.scanner_transitions import Transitions

    with projection.lock:
        for name in ('server_id','epoch','generation','publication','evaluations','reuses','rows'):
            setattr(projection, name, deepcopy(value[name]))
        projection.transitions = Transitions()
        for name, item in value['transitions'].items():
            if name == 'history':item = deque(item)
            elif name == 'pairs':item = set(item)
            elif name == 'context' and item is not None:item = tuple(item)
            setattr(projection.transitions, name, deepcopy(item))
        if value.get('capture_only'):
            projection.transitions.censor('coverage_gap')


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
