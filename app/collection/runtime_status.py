"""Bounded committed runtime status and acknowledged cross-process controls.

A heartbeat proves only owner liveness. It never changes any source clock or
quote authority. Readers fail closed after HEARTBEAT_SECONDS without a write.
"""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
import os
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.storage.store import connect

HEARTBEAT_SECONDS = 8
COMMAND_SECONDS = 12
STATUS_BYTES = 256 * 1024
RUNTIME_LOCK = 120013
AUTHORITY_LOCK = 120015


def clock():
    return datetime.now(timezone.utc)


def _stamp(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def read_runtime(db, at=None):
    """Read committed facts, with bounded death detection independent of app life."""
    row = db.execute('SELECT * FROM data_runtime WHERE singleton=true').fetchone()
    if row is None:
        return dict(healthy=False, active=False, dispatch=False, runtime_id=None,
                    config={}, states={}, revision=0, service_state='unavailable',
                    heartbeat_at=None, reason_code='data_runtime_absent')
    now = _stamp(at) if at is not None else clock()
    age = (now - _stamp(row['heartbeat_at'])).total_seconds()
    healthy = 0 <= age <= HEARTBEAT_SECONDS and row['state'] in ('running', 'starting')
    states = deepcopy(row['source_status'])
    if not healthy:
        for state in states.values():
            state.update(state='unavailable', reason_code='data_runtime_unhealthy',
                         reason='Background data runtime is stopped or its heartbeat expired.')
    return dict(healthy=healthy, active=healthy and row['dispatch'],
                dispatch=healthy and row['dispatch'], runtime_id=row['runtime_id'],
                config=deepcopy(row['config']), states=states, revision=row['revision'],
                heartbeat_at=_stamp(row['heartbeat_at']).astimezone(timezone.utc).isoformat(),
                service_state=row['state'] if healthy else 'unavailable',
                calculations=deepcopy(row['status'].get('background_calculations', {})),
                reason_code=None if healthy else 'data_runtime_unhealthy',
                status=deepcopy(row['status']), paused_sources=row['paused_sources'],
                global_stopped=row['global_stopped'], owner_pid=row['owner_pid'])


class RuntimeState:
    def __init__(self, connector=connect):
        self.connector = connector
        self.started_at = clock()

    def retained_controls(self):
        with self.connector() as db:
            row = db.execute('SELECT paused_sources,global_stopped FROM data_runtime WHERE singleton=true').fetchone()
        return (set(row['paused_sources']), row['global_stopped']) if row else (set(), False)

    def write(self, service, *, state='running', paused_sources=(), global_stopped=False):
        self.write_snapshot(self.snapshot(service, state=state, paused_sources=paused_sources,
                                          global_stopped=global_stopped))

    def snapshot(self, service, *, state='running', paused_sources=(), global_stopped=False):
        """Copy loop-owned state before any asynchronous database work."""
        # CurrentService projects only local bounded vocabulary and validated
        # configuration; exception text is never added to this persisted view.
        status = service.status()
        status['issues'] = status.get('issues', [])[-32:]
        status['exclusions'] = status.get('exclusions', [])[-100:]
        status['status_retention'] = dict(issue_limit=32, exclusion_limit=100,
                                         note='Compact latest status; bounded local diagnostic records retain additional issues.')
        # Source panels already retain these exact structured diagnostics.
        # Repeating discovery/identity/coverage lists in the legacy root metrics
        # can exceed the heartbeat bound after a valid broad acquisition and
        # terminate every source. Keep counters here and full details once.
        panels={p.get('provider'):p.get('metrics',{}) for p in status.get('sources',[])}
        if isinstance(status.get('metrics'),dict):
            status['metrics']={provider:{key:value for key,value in metrics.items()
                if not (isinstance(value,(dict,list)) and key in panels.get(provider,{})
                        and panels[provider][key]==value)}
                for provider,metrics in status['metrics'].items()}
            status['status_retention']['structured_metrics_location']='sources[].metrics; exact repeated root details omitted'
        status['background_calculations'] = deepcopy(getattr(service, 'background_calculations', {}))
        status['background_work'] = deepcopy(getattr(service, 'background_work', {}))
        if status.get('database'):
            status['database']['error'] = 'database_unavailable' if status['database'].get('error') else None
        config = deepcopy(service.config)
        states = deepcopy(service.states)
        # Quote/source receipt clocks remain diagnostics. Only source health and
        # explicit runtime authority change the cross-process control revision.
        from app.storage.observation_publication import health
        material = dict(runtime_id=service.runtime_id, config=config,
                        source_status={key:health(value) for key,value in states.items()},
                        dispatch=bool(service.dispatch), state=state,
                        paused_sources=sorted(paused_sources),global_stopped=bool(global_stopped))
        fingerprint = sha256(json.dumps(material, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        status['data_runtime'] = dict(state=state, heartbeat_timeout_seconds=HEARTBEAT_SECONDS,
                                      paused_sources=sorted(paused_sources), global_stopped=global_stopped)
        if len(json.dumps(status, separators=(',', ':')).encode()) > STATUS_BYTES:
            raise ValueError('data_runtime_status_capacity')
        return dict(runtime_id=service.runtime_id, state=state, status=status, config=config,
                    states=states, dispatch=bool(service.dispatch), fingerprint=fingerprint,
                    paused_sources=sorted(paused_sources), global_stopped=global_stopped)

    def write_snapshot(self, value, *, heartbeat=False):
        from psycopg.errors import LockNotAvailable
        with self.connector() as db:
            if heartbeat:
                # Publication/control serialization uses AUTHORITY_LOCK, so a
                # long publication cannot suppress liveness. Keep the bounded
                # row wait for actual control writes; expiry stays eight seconds.
                db.execute("SET lock_timeout='100ms'")
                try:
                    changed=db.execute('''UPDATE data_runtime SET heartbeat_at=%s,
                        source_status=%s,status=%s,dispatch=%s,
                        revision=revision+CASE WHEN fingerprint<>%s THEN 1 ELSE 0 END,
                        fingerprint=%s
                        WHERE singleton AND runtime_id=%s AND state='running'
                        AND paused_sources=%s AND global_stopped=%s''',
                        (clock(),Jsonb(value['states']),Jsonb(value['status']),value['dispatch'],
                         value['fingerprint'],value['fingerprint'],value['runtime_id'],
                         Jsonb(value['paused_sources']),value['global_stopped'])).rowcount
                except LockNotAvailable:
                    return False
                return bool(changed)
            with db.transaction():
                db.execute('SELECT pg_advisory_xact_lock(%s)', (AUTHORITY_LOCK,))
                self._write_authority(db, value)

    def _write_authority(self, db, value):
        db.execute('''INSERT INTO data_runtime
            (singleton,runtime_id,owner_pid,started_at,heartbeat_at,state,config,source_status,
             dispatch,status,revision,fingerprint,paused_sources,global_stopped)
            VALUES (true,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s)
            ON CONFLICT(singleton) DO UPDATE SET
             runtime_id=excluded.runtime_id,owner_pid=excluded.owner_pid,started_at=excluded.started_at,
             heartbeat_at=excluded.heartbeat_at,state=excluded.state,config=excluded.config,
             source_status=excluded.source_status,dispatch=excluded.dispatch,status=excluded.status,
             revision=data_runtime.revision+CASE WHEN data_runtime.fingerprint<>excluded.fingerprint THEN 1 ELSE 0 END,
             fingerprint=excluded.fingerprint,paused_sources=excluded.paused_sources,
             global_stopped=excluded.global_stopped''',
            (value['runtime_id'], os.getpid(), self.started_at, clock(), value['state'], Jsonb(value['config']),
             Jsonb(value['states']), value['dispatch'], Jsonb(value['status']), value['fingerprint'],
             Jsonb(value['paused_sources']), value['global_stopped']))

    def read(self):
        with self.connector() as db:
            return read_runtime(db)

    def submit(self, runtime_id, action, body):
        if len(json.dumps(body, separators=(',', ':')).encode()) > 8192:
            raise ValueError('data_runtime_control_capacity')
        identity = str(uuid4())
        with self.connector() as db:
            with db.transaction():
                db.execute('SELECT pg_advisory_xact_lock(%s)', (RUNTIME_LOCK + 1,))
                current = read_runtime(db)
                if not current['healthy'] or current['runtime_id'] != runtime_id:
                    raise ValueError('data_runtime_unavailable')
                count = db.execute("SELECT count(*) n FROM data_runtime_command WHERE state='pending'").fetchone()['n']
                if count >= 32:
                    raise ValueError('data_runtime_control_capacity')
                db.execute('''INSERT INTO data_runtime_command(id,runtime_id,action,body,expires_at)
                              VALUES (%s,%s,%s,%s,%s)''',
                           (identity, runtime_id, action, Jsonb(body), clock()+timedelta(seconds=COMMAND_SECONDS)))
        return identity

    def result(self, identity):
        with self.connector() as db:
            row = db.execute('SELECT state,acknowledgment FROM data_runtime_command WHERE id=%s', (identity,)).fetchone()
        return row

    def pending(self):
        with self.connector() as db:
            db.execute("UPDATE data_runtime_command SET state='failed',acknowledgment=%s WHERE state='pending' AND expires_at<clock_timestamp()",
                       (Jsonb(dict(error='data_runtime_control_expired', reason='Control expired before the owning runtime acknowledged it.')),))
            # Retain only bounded recent ACKs. No accumulating control history.
            db.execute("DELETE FROM data_runtime_command WHERE state<>'pending' AND id NOT IN (SELECT id FROM data_runtime_command WHERE state<>'pending' ORDER BY created_at DESC LIMIT 64)")
            return db.execute("SELECT id,runtime_id,action,body FROM data_runtime_command WHERE state='pending' ORDER BY created_at LIMIT 8").fetchall()

    def acknowledge(self, identity, result, *, failed=False):
        with self.connector() as db:
            db.execute("UPDATE data_runtime_command SET state=%s,acknowledgment=%s WHERE id=%s AND state='pending'",
                       ('failed' if failed else 'acknowledged', Jsonb(result), identity))
