"""Store an exact native source market once across census and recovery."""

from hashlib import sha256
import json
from time import monotonic

from psycopg import sql
from psycopg.types.json import Jsonb

from .recovery_codec import freeze, thaw
from .store import encoded

LOCK = 120047
CENSUS = 'current_acquisition_market'
RECOVERY = 'current_native_market_recovery'
MAX_BATCH_ROWS = 256
MAX_BATCH_BYTES = 8 * 1024 * 1024
MAX_TURN_SECONDS = 1.0
_after = {}
_pruned_after = {}

# Used by generated display columns and the census's exact withdrawal check.
# Every other raw field is available through metadata_id.
CENSUS_FIELDS = frozenset((
    'title', 'line', 'floor_strike', 'event_ticker', 'sportsMarketType',
    'closed', 'status',
))

RECOVERY_ROWS = '''
    SELECT r.source,r.market_id,r.metadata,r.parsed,r.receipt_fields,b.body AS native_body
    FROM current_native_market_recovery r
    LEFT JOIN current_native_market_body b ON b.id=r.metadata_id
'''


def split_census(body):
    return {key: value for key, value in body.items() if key in CENSUS_FIELDS}


def body_id(body):
    return sha256(encoded(body)).digest()


def wire_layout(body):
    """Describe object key order so a compact adapter wire string is reversible."""
    if isinstance(body, dict):
        return list(body), {k: layout for k, v in body.items() if (layout := wire_layout(v)) is not None}
    if isinstance(body, list):
        layouts = {str(i): layout for i, v in enumerate(body) if (layout := wire_layout(v)) is not None}
        return layouts or None
    return None


def order_for_wire(body, layout):
    if isinstance(body, dict):
        keys, nested = layout
        if len(keys) != len(body) or set(keys) != body.keys():
            raise ValueError('native_metadata_wire_layout')
        return {k: order_for_wire(body[k], nested.get(k)) for k in keys}
    if isinstance(body, list) and layout is not None:
        return [order_for_wire(value, layout.get(str(i))) for i, value in enumerate(body)]
    return body


def hold(db):
    """Allow concurrent writers and exclude reclamation until FKs commit."""
    db.execute('SELECT pg_advisory_xact_lock_shared(%s)', (LOCK,))


def put(db, values):
    if not values:
        return
    existing = {bytes(row['id']) for row in db.execute(
        'SELECT id FROM current_native_market_body WHERE id=ANY(%s::bytea[])', (list(values),))}
    pending = [(key, encoded(values[key]).decode()) for key in sorted(values.keys() - existing)]
    if not pending:
        return
    with db.cursor() as cursor:
        cursor.executemany('INSERT INTO current_native_market_body (id,body) VALUES (%s,%s) ON CONFLICT DO NOTHING',
                           pending)


def census_body(db, source, event_id, market_id):
    row = db.execute('''SELECT b.body AS native_body, m.metadata
        FROM current_acquisition_market m LEFT JOIN current_native_market_body b ON b.id=m.metadata_id
        WHERE m.source=%s AND m.event_id=%s AND m.market_id=%s''',
        (source, event_id, market_id)).fetchone()
    if not row:
        return None
    return json.loads(row['native_body']) if row['native_body'] is not None else row['metadata']


def _legacy_batch(db, table, keys, checkpoint):
    key_tuple = sql.SQL(',').join(map(sql.Identifier, keys))
    # Choose the next bounded set of identities without materializing or
    # decompressing a full retained source catalog. Advance past locked rows
    # and wrap the cursor on the next turn.
    where = sql.SQL('WHERE metadata_id IS NULL')
    params = []
    if checkpoint is not None:
        where += sql.SQL(' AND ({})>({})').format(key_tuple, sql.SQL(',').join(sql.Placeholder() for _ in keys))
        params.extend(checkpoint)
    names = db.execute(sql.SQL('SELECT {} FROM {} {} ORDER BY {} LIMIT %s').format(
        key_tuple, sql.Identifier(table), where, key_tuple), (*params, MAX_BATCH_ROWS)).fetchall()
    if not names:
        return [], None
    identities = [tuple(row[key] for key in keys) for row in names]
    wanted = sql.SQL('SELECT * FROM unnest({})').format(
        sql.SQL(',').join(sql.SQL('%s::text[]') for _ in keys))
    size = sql.SQL('octet_length(metadata::text)')
    selected = sql.SQL('m.metadata')
    if table == RECOVERY:
        size += sql.SQL('+COALESCE(octet_length(parsed::text),0)+COALESCE(octet_length(receipt_fields::text),0)')
        selected += sql.SQL(',m.parsed,m.receipt_fields')
    rows = db.execute(sql.SQL("""
        WITH sized AS MATERIALIZED (
            SELECT {keys},{size} AS bytes FROM {table}
            WHERE ({keys}) IN ({wanted}) AND metadata_id IS NULL
        ), bounded AS (
            SELECT {keys},sum(bytes) OVER (ORDER BY {keys}) AS running
            FROM sized WHERE bytes<=%s
        )
        SELECT {keys},{selected} FROM {table} m JOIN bounded USING ({keys})
        WHERE running<=%s AND m.metadata_id IS NULL AND jsonb_typeof(m.metadata)='object'
        ORDER BY {keys} FOR UPDATE OF m SKIP LOCKED
    """).format(table=sql.Identifier(table), keys=key_tuple, wanted=wanted, size=size, selected=selected),
        (*map(list, zip(*identities)), MAX_BATCH_BYTES, MAX_BATCH_BYTES)).fetchall()
    return rows, identities[-1]


def convert(db):
    """Backfill old metadata incrementally without refreshing provider clocks."""
    from app.collection.current_storage_policy import SQL_BYTE_CAP, require_disk_space, sql_usage
    from .storage_maintenance import REWRITE_RUNWAY_BYTES
    from .store import ROOT
    from app.collection.native_recovery import market_value, parsed_value, storage_values

    if sql_usage(db) + 2 * MAX_BATCH_BYTES + REWRITE_RUNWAY_BYTES >= SQL_BYTE_CAP:
        return dict(converted=0, reason='native_metadata_headroom')
    require_disk_space(ROOT / '.local/postgres', append_bytes=2 * MAX_BATCH_BYTES)
    start = monotonic()
    converted = 0
    for table, keys in (
        (CENSUS, ('source', 'event_id', 'market_id')),
        (RECOVERY, ('source', 'market_id')),
    ):
        key = db.info.dbname, table
        with db.transaction():
            # Backfill locks legacy rows before it writes a body. Census and
            # recovery write the body before updating their rows. Do not
            # interleave those opposite lock orders during a native traversal.
            if not db.execute('SELECT pg_try_advisory_xact_lock(%s) AS held', (LOCK,)).fetchone()['held']:
                return dict(converted=converted, reason='native_metadata_writer_busy')
            rows, following = _legacy_batch(db, table, keys, _after.get(key))
            updates, bodies = [], {}
            for row in rows:
                market = (row['metadata'] if table == CENSUS
                          else market_value(row['metadata'],row['receipt_fields']))
                body = market if table == CENSUS else market.get('_native')
                if isinstance(body, dict):
                    ref = body_id(body)
                    bodies[ref] = body
                    identity = tuple(row[name] for name in keys)
                    if table == CENSUS:
                        updates.append((Jsonb(split_census(market)), ref, *identity))
                    else:
                        parsed = parsed_value(row['parsed'],row['receipt_fields'])
                        # Legacy non-market diagnostic values can be decoded as
                        # saved packets, but are not eligible for wire factoring.
                        if parsed is None or isinstance(parsed.get('raw'), dict):
                            slim, stored, fields = storage_values(market, parsed, shared_native=True)
                        else:
                            slim = freeze({k:v for k,v in thaw(row['metadata']).items() if k != '_native'})
                            stored, fields = row['parsed'], row['receipt_fields']
                        updates.append((Jsonb(slim), ref, Jsonb(stored) if stored is not None else None,
                                        Jsonb(fields) if fields is not None else None, *identity))
                if monotonic() - start >= MAX_TURN_SECONDS:
                    following = tuple(row[name] for name in keys)
                    break
            put(db, bodies)
            if updates:
                where = sql.SQL(' AND ').join(sql.SQL('{}=%s').format(sql.Identifier(name)) for name in keys)
                assignments = sql.SQL('metadata=%s,metadata_id=%s')
                if table == RECOVERY:
                    assignments += sql.SQL(',parsed=%s,receipt_fields=%s')
                with db.cursor() as cursor:
                    cursor.executemany(sql.SQL('UPDATE {} SET {} WHERE ').format(
                        sql.Identifier(table), assignments) + where, updates)
            converted += len(updates)
        if following is None:
            _after.pop(key, None)
        else:
            _after[key] = following
        if monotonic() - start >= MAX_TURN_SECONDS:
            break
    return dict(converted=converted)


def prune(db):
    """Reclaim a bounded group of immutable bodies when no current owner needs it."""
    key = db.info.dbname
    with db.transaction():
        if not db.execute('SELECT pg_try_advisory_xact_lock(%s) AS held', (LOCK,)).fetchone()['held']:
            return 0
        bound = _pruned_after.get(key, b'')
        rows = db.execute('''SELECT id FROM current_native_market_body
            WHERE id>%s ORDER BY id LIMIT %s''', (bound, 4 * MAX_BATCH_ROWS)).fetchall()
        if not rows:
            _pruned_after.pop(key, None)
            return 0
        ids = [row['id'] for row in rows]
        deleted = db.execute('''
            DELETE FROM current_native_market_body b
            WHERE b.id=ANY(%s::bytea[])
              AND NOT EXISTS (SELECT 1 FROM current_acquisition_market m WHERE m.metadata_id=b.id)
              AND NOT EXISTS (SELECT 1 FROM current_native_market_recovery r WHERE r.metadata_id=b.id)
        ''', (ids,)).rowcount
    _pruned_after[key] = bytes(ids[-1])
    return deleted
