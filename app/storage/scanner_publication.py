"""Bounded process-local genuine post-commit observations, no durable history.

An observation exists only for a top-level transaction actually committed by
this process. Nested/foreign writers and unchanged pre-start rows stay unknown.
"""
from app.diagnostics import failure
from collections import OrderedDict
from threading import RLock
from time import perf_counter
from app.storage.store import hashed
from app.storage.current_games import utc

_lock = RLock()
_observations = OrderedDict()
_listeners = set()
MAX_OBSERVATIONS = 512


def subscribe(callback):
    with _lock:
        _listeners.add(callback)
    def close():
        with _lock:
            _listeners.discard(callback)
            if not _listeners:_observations.clear()
    return close


def prepare(db):
    """Capture exact current-row identity inside the committing transaction."""
    with _lock:
        if not _listeners:return None
    return current_revision(db)


def current_revision(db):
    epoch=db.execute('SELECT epoch FROM current_row_epoch WHERE singleton=true').fetchone()['epoch']
    offer_rows=db.execute('SELECT contract_id,revision FROM current_offer LIMIT 16385').fetchall()
    native_rows=db.execute('SELECT b.venue,e.native_event_id,b.native_market_id,b.revision FROM current_native_book b JOIN current_event e ON e.id=b.event_id LIMIT 16385').fetchall()
    if len(offer_rows)>16384 or len(native_rows)>16384:
        raise ValueError('scanner_revision_probe_capacity')
    offers={r['contract_id']:r['revision'] for r in offer_rows}
    native={hashed([r['venue'],r['native_event_id'],r['native_market_id']]):r['revision'] for r in native_rows}
    events={r['id']:r['revision'] for r in db.execute('SELECT id,revision FROM current_event').fetchall()}
    contracts={r['id']:r['revision'] for r in db.execute('SELECT id,revision FROM current_contract').fetchall()}
    statuses={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
    return dict(epoch=epoch,current_rows_revision=hashed([epoch,offers,native]),
                facts_revision=hashed([events,contracts,statuses]))


def committed(proof):
    if proof is None:return
    observation=dict(**proof,sql_committed_observed_at=utc(),monotonic_observed=perf_counter(),
                     meaning='observed_after_successful_top_level_commit')
    with _lock:
        _observations[proof['current_rows_revision']]=observation
        while len(_observations)>MAX_OBSERVATIONS:_observations.popitem(last=False)
        listeners=tuple(_listeners)
    for callback in listeners:
        try:callback(observation)
        except Exception as exc:
            failure(__name__, 'scanner_commit_listener', exc)


def lookup(revision):
    with _lock:
        result=_observations.get(revision)
        return None if result is None else dict(result)


from contextlib import contextmanager

@contextmanager
def transaction(db):
    from psycopg.pq import TransactionStatus
    top = db.info.transaction_status == TransactionStatus.IDLE
    proof = None
    with db.transaction():
        yield
        if top:
            try:
                # A failed optional SQL probe must roll back its savepoint;
                # catching alone leaves PostgreSQL's outer transaction aborted.
                with db.transaction():proof = prepare(db)
            except Exception as exc:
                failure(__name__, 'scanner_commit_probe', exc)
                proof = None
    if top:committed(proof)
