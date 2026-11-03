"""Bounded process-local genuine post-commit observations, no durable history.

An observation exists only for a top-level transaction actually committed by
this process. Nested/foreign writers and unchanged pre-start rows stay unknown.
"""
from app.diagnostics import failure
from collections import OrderedDict
from threading import RLock
from time import perf_counter
from app.storage.store import hashed, encoded
from hashlib import sha256
from app.storage.current_games import utc

_lock = RLock()
_observations = OrderedDict()
_listeners = set()
_wake_listeners = set()
MAX_OBSERVATIONS = 512
MAX_PROBE_BYTES = 32 * 1024 * 1024


def subscribe(callback, *, proof=True):
    listeners = _listeners if proof else _wake_listeners
    with _lock:
        listeners.add(callback)
    def close():
        with _lock:
            listeners.discard(callback)
            if not _listeners:_observations.clear()
    return close


def prepare(db):
    """Capture exact current-row identity inside the committing transaction."""
    with _lock:
        if not _listeners:return None
    return current_revision(db)


def current_revision(db):
    epoch=db.execute('SELECT epoch FROM current_row_epoch WHERE singleton=true').fetchone()['epoch']
    # Revision witnesses are tiny, not hydrated financial records. Stream them
    # under their own byte guard; a full-record count cap refused ordinary busy
    # slates even though this probe held only IDs and hashes.
    def mapping_into(digest,query,key,value):
        digest.update(b'{');charged=0;separator=b''
        with db.cursor(name='scanner_revision_witnesses') as cursor:
            cursor.itersize=256;cursor.execute(query)
            for row in cursor:
                wire=encoded(row[key])+b':'+encoded(row[value]);charged+=len(wire)
                if charged>MAX_PROBE_BYTES:raise ValueError('scanner_revision_probe_capacity')
                digest.update(separator);digest.update(wire);separator=b','
        digest.update(b'}')
    # Preserve the exact canonical JSON revision used by CurrentRowStore.
    # SQL ordering matches its string-key ordering; only native hash keys need
    # a bounded sort in Python. No decoded market or financial graph is held.
    with db.transaction():
        rows_hash=sha256();rows_hash.update(b'['+encoded(epoch)+b',')
        mapping_into(rows_hash,'SELECT contract_id,revision FROM current_offer ORDER BY contract_id COLLATE "C"','contract_id','revision')
        native={};charged=0
        with db.cursor(name='scanner_native_witnesses') as cursor:
            cursor.itersize=256
            cursor.execute('SELECT b.venue,e.native_event_id,b.native_market_id,b.revision FROM current_native_book b JOIN current_event e ON e.id=b.event_id')
            for row in cursor:
                key=hashed([row['venue'],row['native_event_id'],row['native_market_id']])
                charged+=6*len(encoded([key,row['revision']]))+256
                if charged>MAX_PROBE_BYTES:raise ValueError('scanner_revision_probe_capacity')
                native[key]=row['revision']
        rows_hash.update(b','+encoded(native)+b']')
        facts_hash=sha256();facts_hash.update(b'[')
        mapping_into(facts_hash,'SELECT id,revision FROM current_event ORDER BY id COLLATE "C"','id','revision')
        facts_hash.update(b',')
        mapping_into(facts_hash,'SELECT id,revision FROM current_contract ORDER BY id COLLATE "C"','id','revision')
        facts_hash.update(b',')
        mapping_into(facts_hash,'SELECT venue,state FROM current_source_status ORDER BY venue COLLATE "C"','venue','state')
        facts_hash.update(b']')
    return dict(epoch=epoch,current_rows_revision=rows_hash.hexdigest(),facts_revision=facts_hash.hexdigest())


def committed(proof):
    # A wake signal carries no revision or claimed commit-to-display evidence.
    # Durable workers capture and validate their exact SQL inputs independently.
    with _lock:wake_listeners=tuple(_wake_listeners)
    for callback in wake_listeners:
        try:callback(None)
        except Exception as exc:failure(__name__, 'scanner_commit_wake_listener', exc)
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
