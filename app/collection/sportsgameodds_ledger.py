"""Durable conservative SGO object reservations, separate from Odds API records.

One ledger represents one explicitly identified provider account window. The
caller supplies its observed starting use and optional reset; this module never
invents a reset or automatically opens a new window. Dispatch must occur only
after reserve() succeeds, and the provider request must be bounded to that
reservation. In-flight and failed requests remain held across restarts.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import sqlite3
import json
from uuid import uuid4


def _integer(value: int, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < (1 if positive else 0):
        raise ValueError(f'{name} must be a {"positive" if positive else "nonnegative"} integer')
    return value


def _time(value: datetime) -> float:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('time must be timezone-aware')
    return value.timestamp()


class ObjectLedger:
    def __init__(self, path: str):
        self.path = str(path)
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sgo_object_window (
                    id TEXT PRIMARY KEY, limit_objects INTEGER NOT NULL,
                    initial_used INTEGER NOT NULL, reserve_objects INTEGER NOT NULL,
                    reset_at REAL, requests_per_minute INTEGER NOT NULL, paused INTEGER NOT NULL DEFAULT 0,
                    retry_after REAL
                );
                CREATE TABLE IF NOT EXISTS sgo_object_reservation (
                    id TEXT PRIMARY KEY, window_id TEXT NOT NULL REFERENCES sgo_object_window(id),
                    reserved INTEGER NOT NULL, status TEXT NOT NULL,
                    charged INTEGER, evidence TEXT, created_at REAL NOT NULL,
                    resolved_at REAL
                );
                CREATE INDEX IF NOT EXISTS sgo_reservation_window ON sgo_object_reservation(window_id, status);
                CREATE TABLE IF NOT EXISTS sgo_http_request (account TEXT NOT NULL, requested_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS sgo_http_rate ON sgo_http_request(account, requested_at);
                CREATE TABLE IF NOT EXISTS sgo_http_clock (account TEXT PRIMARY KEY, last_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sgo_external_usage (
                    window_id TEXT NOT NULL, observed_at REAL NOT NULL,
                    previous_used INTEGER NOT NULL, observed_used INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sgo_ledger_identity (singleton INTEGER PRIMARY KEY CHECK(singleton=1), account TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sgo_reservation_context (
                    reservation_id TEXT PRIMARY KEY REFERENCES sgo_object_reservation(id),
                    category TEXT NOT NULL, league TEXT
                );
                CREATE TABLE IF NOT EXISTS sgo_request_trace (
                    reservation_id TEXT PRIMARY KEY REFERENCES sgo_object_reservation(id),
                    query TEXT NOT NULL,
                    provider_used_before INTEGER NOT NULL,
                    usage_observed_at REAL NOT NULL,
                    http_status INTEGER,
                    response_at REAL,
                    provider_request_id TEXT,
                    response_sha256 TEXT
                );
                CREATE TABLE IF NOT EXISTS sgo_charge_breakdown (
                    reservation_id TEXT NOT NULL REFERENCES sgo_object_reservation(id),
                    league TEXT NOT NULL, phase TEXT NOT NULL, objects INTEGER NOT NULL,
                    PRIMARY KEY(reservation_id, league, phase)
                );
                CREATE TABLE IF NOT EXISTS sgo_discovery_schedule (
                    league TEXT PRIMARY KEY, completed_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sgo_discovery_progress (
                    league TEXT PRIMARY KEY, checkpoint TEXT NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sgo_discovery_cost (
                    league TEXT PRIMARY KEY REFERENCES sgo_discovery_schedule(league),
                    objects INTEGER NOT NULL
                );
            ''')

    def account_identity(self) -> str:
        """Use one opaque partition per ledger, preserving unambiguous old history.

        Credential rotation must never create a fresh budget or bypass a hold.
        Multiple legacy partitions require reconciliation before any request.
        """
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT account FROM sgo_ledger_identity WHERE singleton=1').fetchone()
            if row:
                db.execute('COMMIT')
                return row[0]
            accounts = {row[0] for row in db.execute('SELECT DISTINCT account FROM sgo_http_request')}
            accounts.update(row[0] for row in db.execute('SELECT account FROM sgo_http_clock'))
            for (window,) in db.execute('SELECT id FROM sgo_object_window'):
                if ':' not in window:
                    raise RuntimeError('legacy ledger identity ambiguous; reconciliation required')
                accounts.add(window.split(':', 1)[0])
            if len(accounts) > 1 or '' in accounts:
                raise RuntimeError('legacy ledger identity ambiguous; reconciliation required')
            account = next(iter(accounts)) if accounts else uuid4().hex
            db.execute('INSERT INTO sgo_ledger_identity VALUES(1,?)', (account,))
            db.execute('COMMIT')
            return account

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()

    def create_window(self, window_id: str, *, limit: int, initial_used: int,
                      reserve: int, reset_at: datetime | None = None, requests_per_minute: int = 1) -> None:
        if not window_id:
            raise ValueError('window id required')
        _integer(limit, 'limit', positive=True)
        _integer(initial_used, 'initial_used')
        _integer(reserve, 'reserve')
        _integer(requests_per_minute, 'requests_per_minute', positive=True)
        if initial_used > limit or reserve > limit:
            raise ValueError('usage or reserve exceeds limit')
        reset = _time(reset_at) if reset_at is not None else None
        with self._connect() as db:
            db.execute('INSERT INTO sgo_object_window(id,limit_objects,initial_used,reserve_objects,reset_at,requests_per_minute) VALUES(?,?,?,?,?,?)',
                       (window_id, limit, initial_used, reserve, reset, requests_per_minute))

    def set_paused(self, window_id: str, paused: bool) -> None:
        if not isinstance(paused, bool):
            raise ValueError('pause must be boolean')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not paused and db.execute("SELECT 1 FROM sgo_object_reservation WHERE window_id=? AND status='overrun' LIMIT 1", (window_id,)).fetchone():
                raise RuntimeError('resolve overrun before resuming')
            if db.execute('UPDATE sgo_object_window SET paused=? WHERE id=?', (int(paused), window_id)).rowcount != 1:
                raise KeyError(window_id)
            db.execute('COMMIT')

    def note_rate_limit(self, window_id: str, *, retry_after: datetime, now: datetime) -> None:
        deadline, current = _time(retry_after), _time(now)
        if deadline <= current:
            raise ValueError('retry time must be in the future')
        with self._connect() as db:
            # Never shorten an existing backoff.
            if db.execute('UPDATE sgo_object_window SET retry_after=MAX(COALESCE(retry_after, ?), ?) WHERE id=?',
                          (deadline, deadline, window_id)).rowcount != 1:
                raise KeyError(window_id)

    @staticmethod
    def _rate_admit(db, account, request_limit, current):
        previous = db.execute('SELECT last_at FROM sgo_http_clock WHERE account=?', (account,)).fetchone()
        if previous and current < previous[0]:
            raise RuntimeError('request clock regressed')
        db.execute('INSERT INTO sgo_http_clock(account,last_at) VALUES(?,?) ON CONFLICT(account) DO UPDATE SET last_at=excluded.last_at', (account,current))
        db.execute('DELETE FROM sgo_http_request WHERE account=? AND requested_at<=?', (account,current-60))
        recent = db.execute('SELECT COUNT(*) FROM sgo_http_request WHERE account=?', (account,)).fetchone()[0]
        if recent >= request_limit:
            raise RuntimeError('request rate limit')
        db.execute('INSERT INTO sgo_http_request(account,requested_at) VALUES(?,?)', (account,current))

    def reserve_request(self, account: str, *, requests_per_minute: int, now: datetime) -> None:
        """Persist a non-object request before dispatch, including usage reads."""
        if not account:
            raise ValueError('account id required')
        _integer(requests_per_minute, 'requests_per_minute', positive=True)
        current = _time(now)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._rate_admit(db, account, requests_per_minute, current)
            db.execute('COMMIT')

    def reserve(self, window_id: str, reservation_id: str, *, objects: int,
                now: datetime, stopped: bool = False, source_paused: bool = False,
                category: str | None = None, league: str | None = None,
                request=None, usage=None) -> None:
        _integer(objects, 'objects', positive=True)
        current = _time(now)
        if not reservation_id:
            raise ValueError('reservation id required')
        if category not in (None, 'discovery', 'event_refresh'):
            raise ValueError('invalid request category')
        if league is not None and (category != 'discovery' or league not in ('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL')):
            raise ValueError('invalid request league')
        if request is not None:
            from .sportsgameodds_transport import validate_params
            request = validate_params(request)
            used = _integer(usage['used'], 'provider usage')
            observed_at = _time(usage['at'])
            if request['limit'] != objects or not 0 <= current - observed_at <= 60:
                raise ValueError('request trace conflicts with reservation')
        if stopped or source_paused:
            raise RuntimeError('collection stopped or source paused')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT limit_objects, initial_used, reserve_objects, reset_at, paused, retry_after, requests_per_minute FROM sgo_object_window WHERE id=?', (window_id,)).fetchone()
            if row is None:
                raise KeyError(window_id)
            limit, initial, reserve, reset, paused, retry, request_limit = row
            if paused or (retry is not None and current < retry):
                raise RuntimeError('collection paused or rate limited')
            if reset is not None and current >= reset:
                raise RuntimeError('account window expired; obtain fresh account evidence')
            account = window_id.split(':',1)[0]
            self._rate_admit(db, account, request_limit, current)
            held, charged = db.execute('''SELECT COALESCE(SUM(CASE WHEN status IN ('held','overrun') THEN MAX(reserved,COALESCE(charged,0)) ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN status='resolved' THEN charged ELSE 0 END), 0)
                FROM sgo_object_reservation WHERE window_id=?''', (window_id,)).fetchone()
            prefix = account + ':'
            other = db.execute("SELECT COUNT(*) FROM sgo_object_reservation WHERE window_id<>? AND (window_id=? OR substr(window_id,1,?)=?) AND status IN ('held','overrun')", (window_id,account,len(prefix),prefix)).fetchone()[0]
            if held or other:
                raise RuntimeError('unresolved object reservation')
            if initial + held + charged + objects + reserve > limit:
                raise RuntimeError('insufficient object allowance')
            db.execute("INSERT INTO sgo_object_reservation(id,window_id,reserved,status,created_at) VALUES(?,?,?,'held',?)",
                       (reservation_id, window_id, objects, current))
            if category is not None:
                db.execute('INSERT INTO sgo_reservation_context VALUES(?,?,?)', (reservation_id, category, league))
            if request is not None:
                db.execute('''INSERT INTO sgo_request_trace
                    (reservation_id,query,provider_used_before,usage_observed_at) VALUES(?,?,?,?)''',
                           (reservation_id, json.dumps(request, sort_keys=True), used, observed_at))
            db.execute('COMMIT')

    def record_response(self, reservation_id, response):
        from hashlib import sha256

        with self._connect() as db:
            db.execute('''UPDATE sgo_request_trace SET http_status=?,response_at=?,
                          provider_request_id=?,response_sha256=?
                          WHERE reservation_id=? AND http_status IS NULL''',
                       (response.status, _time(datetime.fromisoformat(response.received_at.replace('Z', '+00:00'))),
                        response.provider_request_id, sha256(response.body).hexdigest() if response.body else None,
                        reservation_id))

    def holds(self, window_id):
        account = window_id.split(':', 1)[0]
        prefix = account + ':'
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('''SELECT r.id,r.status,r.reserved,r.charged,r.created_at,c.category,c.league,
                                        t.query,t.provider_used_before,t.usage_observed_at,t.http_status,
                                        t.response_at,t.provider_request_id,t.response_sha256
                                 FROM sgo_object_reservation r
                                 LEFT JOIN sgo_reservation_context c ON c.reservation_id=r.id
                                 LEFT JOIN sgo_request_trace t ON t.reservation_id=r.id
                                 WHERE (r.window_id=? OR r.window_id=? OR substr(r.window_id,1,?)=?)
                                 AND r.status IN ('held','overrun') ORDER BY r.created_at LIMIT 32''',
                              (window_id, account, len(prefix), prefix)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            if item['query'] is not None:
                item['query'] = json.loads(item['query'])
                if 'cursor' in item['query']:
                    item['query']['cursor'] = '[present]'
            for key in ('created_at', 'usage_observed_at', 'response_at'):
                if item[key] is not None:
                    item[key] = datetime.fromtimestamp(item[key], timezone.utc).isoformat()
            result.append(item)
        return result

    def resolve(self, reservation_id: str, *, charged: int, evidence: str, now: datetime,
                breakdown: dict[tuple[str, str], int] | None = None) -> None:
        """Resolve only with attributable evidence; unknown failures stay held.

        Zero is allowed only when the caller has evidence that no response was
        charged. Nonempty evidence is an audit description, never a credential.
        """
        _integer(charged, 'charged')
        current = _time(now)
        if not evidence.strip():
            raise ValueError('evidence required')
        if breakdown is not None:
            for (league, phase), count in breakdown.items():
                if league not in ('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL', 'unknown') or phase not in ('pregame', 'live', 'started', 'unknown'):
                    raise ValueError('invalid charge breakdown')
                _integer(count, 'breakdown objects', positive=True)
            if sum(breakdown.values()) != charged:
                raise ValueError('charge breakdown must equal charged objects')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT reserved,status,window_id,charged FROM sgo_object_reservation WHERE id=?', (reservation_id,)).fetchone()
            if row is None:
                raise KeyError(reservation_id)
            reserved, status, window_id, prior_charge = row
            if status not in ('held', 'overrun'):
                raise RuntimeError('reservation already resolved')
            if status == 'overrun' and charged != prior_charge:
                raise ValueError('overrun resolution must retain the observed charge')
            if charged > reserved and status == 'held':
                db.execute("UPDATE sgo_object_reservation SET status='overrun',charged=?,evidence=? WHERE id=?", (charged, evidence, reservation_id))
                db.execute('UPDATE sgo_object_window SET paused=1 WHERE id=?', (window_id,))
                db.execute('COMMIT')
                raise ValueError('charge exceeds reservation; collection paused and hold retained')
            db.execute("UPDATE sgo_object_reservation SET status='resolved',charged=?,evidence=?,resolved_at=? WHERE id=?",
                       (charged, evidence, current, reservation_id))
            if breakdown:
                db.executemany('INSERT INTO sgo_charge_breakdown VALUES(?,?,?,?)',
                               [(reservation_id, league, phase, count) for (league, phase), count in breakdown.items()])
            db.execute('COMMIT')

    def rolling_objects(self, window_id: str, *, since: datetime) -> int:
        """Count recent exposure across this account's pacing boundaries."""
        start = _time(since)
        account = window_id.split(':', 1)[0]
        prefix = account + ':'
        with self._connect() as db:
            return db.execute("SELECT COALESCE(SUM(CASE WHEN status='resolved' THEN charged ELSE MAX(reserved,COALESCE(charged,0)) END),0) FROM sgo_object_reservation WHERE (window_id=? OR substr(window_id,1,?)=?) AND created_at>?", (account,len(prefix),prefix,start)).fetchone()[0]

    def rolling_expirations(self, window_id: str, *, now: datetime) -> list[tuple[datetime, int]]:
        """Read charge ages for scheduling. Existing reservations stay untouched."""
        account = window_id.split(':', 1)[0]
        prefix = account + ':'
        with self._connect() as db:
            rows = db.execute('''SELECT created_at, SUM(CASE WHEN status='resolved' THEN charged
                    ELSE MAX(reserved,COALESCE(charged,0)) END)
                FROM sgo_object_reservation
                WHERE (window_id=? OR substr(window_id,1,?)=?) AND created_at>?
                GROUP BY created_at ORDER BY created_at''', (account, len(prefix), prefix, _time(now)-86400)).fetchall()
        return [(datetime.fromtimestamp(at, timezone.utc)+timedelta(days=1), amount) for at, amount in rows if amount]

    def charge_breakdown(self, window_id: str, *, since: datetime) -> list[dict]:
        """Summarize resolved charges; legacy and unclassified charges stay unknown.

        Outstanding reservations and external account use are separate exposure,
        not attributed charges. Time is the request reservation time.
        """
        with self._connect() as db:
            rows = db.execute('''SELECT COALESCE(c.category,'unknown'),
                    COALESCE(b.league,c.league,'unknown'), COALESCE(b.phase,'unknown'),
                    SUM(COALESCE(b.objects,r.charged))
                FROM sgo_object_reservation r
                LEFT JOIN sgo_reservation_context c ON c.reservation_id=r.id
                LEFT JOIN sgo_charge_breakdown b ON b.reservation_id=r.id
                WHERE r.window_id=? AND r.status='resolved' AND r.created_at>?
                GROUP BY 1,2,3 ORDER BY 1,2,3''', (window_id, _time(since))).fetchall()
        return [dict(category=category, league=league, phase=phase, objects=objects)
                for category, league, phase, objects in rows]

    def save_discovery_progress(self, league: str, checkpoint: dict, *, now: datetime) -> None:
        if league not in ('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL'):
            raise ValueError('invalid discovery league')
        data = json.dumps(checkpoint, sort_keys=True, separators=(',', ':'))
        if len(data.encode()) > 3_000_000:
            raise ValueError('discovery checkpoint too large')
        with self._connect() as db:
            db.execute("INSERT INTO sgo_discovery_progress VALUES(?,?,?) ON CONFLICT(league) DO UPDATE SET checkpoint=excluded.checkpoint,updated_at=excluded.updated_at",
                       (league, data, _time(now)))

    def load_discovery_progress(self, *, now: datetime) -> dict:
        current = _time(now)
        with self._connect() as db:
            rows = db.execute('SELECT league,checkpoint,updated_at FROM sgo_discovery_progress').fetchall()
        result = {}
        for league, data, updated in rows:
            # A long interruption or regressed clock invalidates the walk, not
            # its already admitted source observations.
            if 0 <= current - updated <= 86400:
                try:
                    result[league] = json.loads(data)
                except (ValueError, TypeError):
                    continue
        return result

    def clear_discovery_progress(self, league: str) -> None:
        with self._connect() as db:
            db.execute('DELETE FROM sgo_discovery_progress WHERE league=?', (league,))

    def record_discovery(self, league: str, *, completed_at: datetime, objects: int | None = None) -> None:
        """Persist scheduling only; traversal completion never implies absence."""
        if league not in ('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL'):
            raise ValueError('invalid discovery league')
        if objects is not None:
            _integer(objects, 'discovery objects', positive=True)
        when = _time(completed_at)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM sgo_discovery_progress WHERE league=?', (league,))
            db.execute('''INSERT INTO sgo_discovery_schedule VALUES(?,?)
                ON CONFLICT(league) DO UPDATE SET completed_at=MAX(completed_at,excluded.completed_at)''',
                (league, when))
            if objects is not None:
                db.execute('''INSERT INTO sgo_discovery_cost
                    SELECT league,? FROM sgo_discovery_schedule WHERE league=? AND completed_at=?
                    ON CONFLICT(league) DO UPDATE SET objects=excluded.objects''', (objects, league, when))
            db.execute('COMMIT')

    def discovery_cost(self, *, now: datetime) -> dict[str, int]:
        with self._connect() as db:
            return dict(db.execute('''SELECT c.league,c.objects FROM sgo_discovery_cost c
                JOIN sgo_discovery_schedule s USING(league) WHERE s.completed_at<=?''', (_time(now),)))

    def discovery_schedule(self, *, now: datetime) -> dict[str, datetime]:
        current = _time(now)
        with self._connect() as db:
            rows = db.execute('SELECT league,completed_at FROM sgo_discovery_schedule').fetchall()
        # A regressed local clock must not postpone a fresh discovery.
        return {league: datetime.fromtimestamp(at, timezone.utc) for league, at in rows if at <= current}

    def reconcile_increase(self, window_id: str, *, used: int, now: datetime) -> None:
        """Record additional provider-reported use without releasing any exposure."""
        _integer(used, 'used')
        current = _time(now)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT initial_used,limit_objects FROM sgo_object_window WHERE id=?', (window_id,)).fetchone()
            if row is None:
                raise KeyError(window_id)
            initial, limit = row
            charged, held = db.execute("SELECT COALESCE(SUM(CASE WHEN status='resolved' THEN charged ELSE 0 END),0), COUNT(*) FILTER (WHERE status IN ('held','overrun')) FROM sgo_object_reservation WHERE window_id=?", (window_id,)).fetchone()
            expected = initial + charged
            if held or used < expected or used > limit:
                raise RuntimeError('current account usage evidence unavailable or changed')
            if used > expected:
                db.execute('UPDATE sgo_object_window SET initial_used=initial_used+? WHERE id=?', (used-expected, window_id))
                db.execute('INSERT INTO sgo_external_usage VALUES(?,?,?,?)', (window_id,current,expected,used))
            db.execute('COMMIT')

    def status(self, window_id: str) -> dict:
        with self._connect() as db:
            row = db.execute('SELECT limit_objects,initial_used,reserve_objects,reset_at,paused,retry_after,requests_per_minute FROM sgo_object_window WHERE id=?', (window_id,)).fetchone()
            if row is None:
                raise KeyError(window_id)
            held, charged = db.execute('''SELECT COALESCE(SUM(CASE WHEN status IN ('held','overrun') THEN MAX(reserved,COALESCE(charged,0)) ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN status='resolved' THEN charged ELSE 0 END), 0)
                FROM sgo_object_reservation WHERE window_id=?''', (window_id,)).fetchone()
        limit, initial, reserve, reset, paused, retry, request_limit = row
        return {'limit': limit, 'initial_used': initial, 'held': held, 'charged': charged,
                'reserve': reserve, 'requests_per_minute': request_limit, 'available': max(0, limit - initial - held - charged - reserve),
                'paused': bool(paused),
                'reset_at': datetime.fromtimestamp(reset, timezone.utc) if reset is not None else None,
                'retry_after': datetime.fromtimestamp(retry, timezone.utc) if retry is not None else None}
