"""Durable conservative SGO object reservations, separate from Odds API records.

One ledger represents one explicitly identified provider account window. The
caller supplies its observed starting use and optional reset; this module never
invents a reset or automatically opens a new window. Dispatch must occur only
after reserve() succeeds, and the provider request must be bounded to that
reservation. In-flight and failed requests remain held across restarts.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3


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
            ''')

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
                now: datetime, stopped: bool = False, source_paused: bool = False) -> None:
        _integer(objects, 'objects', positive=True)
        current = _time(now)
        if not reservation_id:
            raise ValueError('reservation id required')
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
            db.execute('COMMIT')

    def resolve(self, reservation_id: str, *, charged: int, evidence: str, now: datetime) -> None:
        """Resolve only with attributable evidence; unknown failures stay held.

        Zero is allowed only when the caller has evidence that no response was
        charged. Nonempty evidence is an audit description, never a credential.
        """
        _integer(charged, 'charged')
        current = _time(now)
        if not evidence.strip():
            raise ValueError('evidence required')
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
            db.execute('COMMIT')

    def rolling_objects(self, window_id: str, *, since: datetime) -> int:
        """Locally accounted or reserved object exposure since the given time."""
        start = _time(since)
        with self._connect() as db:
            return db.execute("SELECT COALESCE(SUM(CASE WHEN status='resolved' THEN charged ELSE MAX(reserved,COALESCE(charged,0)) END),0) FROM sgo_object_reservation WHERE window_id=? AND created_at>?", (window_id,start)).fetchone()[0]

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
