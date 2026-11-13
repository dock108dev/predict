"""Bounded, read-only inspection of the local project PostgreSQL database."""

import asyncio
from contextlib import contextmanager

from aiohttp import web
from psycopg import errors, sql
from psycopg.rows import dict_row, tuple_row

from app.storage.store import connect
from .local_security import PublicRequestError

KINDS = ('r', 'p', 'v', 'm', 'S', 'f')
PAGE_SIZE = 25
CELL_CHUNK = 16_000
MAX_OFFSET = 9_007_199_254_740_991
SCHEMAS = """n.nspname <> 'information_schema' AND left(n.nspname, 3) <> 'pg_'
             AND has_schema_privilege(n.oid, 'USAGE')"""
RELATIONS = """
    SELECT n.nspname AS schema, c.relname AS name, c.oid, c.relkind AS kind,
           c.relispartition AS partition,
           has_table_privilege(c.oid, 'SELECT') AS readable
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
"""


@contextmanager
def inspection(connector):
    with connector() as db, db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        db.execute('SET LOCAL search_path = pg_catalog')
        db.execute("SET LOCAL statement_timeout = '2500ms'")
        db.execute("SET LOCAL lock_timeout = '500ms'")
        db.execute("SET LOCAL temp_file_limit = '32MB'")
        # Inspect stored values, including payload encodings, without the app's
        # implicit payload decoder or JS number conversion.
        db.row_factory = dict_row
        yield db


def catalog(db):
    schemas = db.execute(
        'SELECT nspname AS name FROM pg_namespace n WHERE ' + SCHEMAS + ' ORDER BY 1'
    ).fetchall()
    relations = db.execute(
        RELATIONS + ' WHERE ' + SCHEMAS + ' AND c.relkind = ANY(%s) ORDER BY 1, 2',
        (list(KINDS),),
    ).fetchall()
    for relation in relations:
        relation.pop('oid')
        relation['readable'] &= relation['kind'] != 'f'
    return dict(database=db.info.dbname, schemas=[s['name'] for s in schemas],
                relations=relations)


def relation_for(db, schema, name):
    relation = db.execute(
        RELATIONS + ' WHERE ' + SCHEMAS
        + ' AND c.relkind = ANY(%s) AND n.nspname = %s AND c.relname = %s',
        (list(KINDS), schema, name),
    ).fetchone()
    if not relation:
        raise web.HTTPNotFound(reason='Database object was not found.')
    return relation


def columns_for(db, oid):
    return db.execute("""
        SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type,
               NOT a.attnotnull AS nullable, pg_get_expr(d.adbin, d.adrelid) AS expression,
               a.attidentity AS identity, a.attgenerated AS generated,
               col_description(a.attrelid, a.attnum) AS comment
        FROM pg_attribute a LEFT JOIN pg_attrdef d
          ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum
    """, (oid,)).fetchall()


def structure(db, relation):
    oid = relation['oid']
    details = db.execute("""
        SELECT obj_description(c.oid, 'pg_class') AS comment,
               CASE WHEN c.relkind IN ('v', 'm') THEN pg_get_viewdef(c.oid, true) END AS view_sql,
               pg_get_partkeydef(c.oid) AS partition_key,
               pg_get_expr(c.relpartbound, c.oid, true) AS partition_bound
        FROM pg_class c WHERE c.oid = %s
    """, (oid,)).fetchone()
    details['parents'] = db.execute("""
        SELECT n.nspname AS schema, c.relname AS name
        FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhparent
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE i.inhrelid = %s ORDER BY i.inhseqno
    """, (oid,)).fetchall()
    details['constraints'] = db.execute("""
        SELECT conname AS name, pg_get_constraintdef(oid, true) AS definition
        FROM pg_constraint WHERE conrelid = %s ORDER BY conname
    """, (oid,)).fetchall()
    details['indexes'] = db.execute("""
        SELECT c.relname AS name, pg_get_indexdef(c.oid) AS definition
        FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
        WHERE i.indrelid = %s ORDER BY c.relname
    """, (oid,)).fetchall()
    details['columns'] = columns_for(db, oid)
    return details


def primary_key(db, oid):
    return [row['name'] for row in db.execute("""
        SELECT a.attname AS name
        FROM pg_index i CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, pos)
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
        WHERE i.indrelid = %s AND i.indisprimary AND i.indisvalid AND k.pos <= i.indnkeyatts
        ORDER BY k.pos
    """, (oid,))]


def row_query(relation, projection, key):
    order = (sql.SQL(' ORDER BY {}').format(sql.SQL(', ').join(
        sql.Identifier(column) for column in key)) if key else sql.SQL(''))
    return sql.SQL('SELECT {} FROM {}{} LIMIT %s OFFSET %s').format(
        projection, sql.Identifier(relation['schema'], relation['name']), order)


def require_rows(relation):
    if relation['kind'] == 'f':
        raise PublicRequestError('Foreign table rows are unavailable in the local browser.')
    if not relation['readable']:
        raise web.HTTPForbidden(reason='PostgreSQL does not allow reading these rows.')


def page(db, relation, offset):
    require_rows(relation)
    oid = relation['oid']
    names = [c['name'] for c in columns_for(db, oid)]
    key = primary_key(db, oid)
    # Cap result size before libpq or the browser sees it. Cast individual
    # values to text to preserve precision and distinguish NULL from "NULL".
    preview = max(16, min(512, 12_000 // max(1, len(names))))
    limit = min(PAGE_SIZE, max(1, 500 // max(1, len(names))))
    projection = sql.SQL(', ').join(
        sql.SQL('left({}::text, {})').format(sql.Identifier(name), sql.Literal(preview + 1))
        for name in names
    ) or sql.SQL('1')
    with db.cursor(row_factory=tuple_row) as cur:
        rows = cur.execute(row_query(relation, projection, key), (limit + 1, offset)).fetchall()
    return dict(columns=names, rows=[[
        None if value is None else dict(text=value[:preview], more=len(value) > preview)
        for value in row
    ] if names else [] for row in rows[:limit]], primary_key=key, offset=offset,
        next_offset=offset + limit if len(rows) > limit and offset + limit <= MAX_OFFSET else None,
        previous_offset=max(0, offset - limit) if offset else None)


def cell(db, relation, offset, column, start):
    require_rows(relation)
    if column not in {c['name'] for c in columns_for(db, relation['oid'])}:
        raise web.HTTPNotFound(reason='Database column was not found.')
    # PostgreSQL substring uses 1-based int4 positions; large values are
    # inspectable in bounded chunks. The row position is read live each time.
    projection = sql.SQL('substring({0}::text FROM %s FOR %s) AS value, md5({0}::text) AS fingerprint').format(
        sql.Identifier(column))
    query = row_query(relation, projection, primary_key(db, relation['oid']))
    row = db.execute(query, (start + 1, CELL_CHUNK + 1, 1, offset)).fetchone()
    if row is None:
        raise web.HTTPNotFound(reason='Row no longer exists at that position.')
    value = row['value']
    return dict(text=None if value is None else value[:CELL_CHUNK], start=start,
                fingerprint=row['fingerprint'], previous_start=max(0, start - CELL_CHUNK) if start else None,
                next_start=start + CELL_CHUNK if value is not None and len(value) > CELL_CHUNK else None)


def number(query, name, maximum=MAX_OFFSET):
    value = query.get(name, '0')
    if not 1 <= len(value) <= 16 or not value.isascii() or not value.isdecimal() or int(value) > maximum:
        raise PublicRequestError(f'Invalid {name}.')
    return int(value)


def mount(app, connector=None):
    connector = connector or connect
    active = None

    def read(view, query):
        fields = {
            'catalog': set(), 'structure': {'schema', 'name'},
            'rows': {'schema', 'name', 'offset'},
            'cell': {'schema', 'name', 'offset', 'column', 'start'},
        }[view]
        if query.keys() - fields or any(not 0 < len(query.get(field, '').encode()) <= 63
                                       or '\x00' in query[field]
                                       for field in fields & {'schema', 'name', 'column'}):
            raise PublicRequestError('Invalid database selection.')
        offset = number(query, 'offset')
        start = number(query, 'start', 1_073_741_824)
        with inspection(connector) as db:
            if view == 'catalog':
                return catalog(db)
            relation = relation_for(db, query['schema'], query['name'])
            if view == 'structure':
                return structure(db, relation)
            if view == 'rows':
                return page(db, relation, offset)
            return cell(db, relation, offset, query['column'], start)

    async def handle(request):
        nonlocal active
        # Keep the one database slot occupied until the worker really returns,
        # even if a browser disconnects or switches tables mid-query.
        if active is not None and not active.done():
            raise web.HTTPTooManyRequests(reason='A database read is in progress. Try again shortly.',
                                          headers={'Retry-After': '1'})
        active = asyncio.create_task(asyncio.to_thread(read, request.match_info['view'], dict(request.query)))
        active.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        try:
            result = await asyncio.shield(active)
        except (errors.QueryCanceled, errors.LockNotAvailable, errors.ConfigurationLimitExceeded):
            raise web.HTTPServiceUnavailable(reason='Database read exceeded its time or work limit. Try again.') from None
        except (errors.UndefinedTable, errors.UndefinedColumn):
            raise web.HTTPNotFound(reason='Database structure changed. Refresh the catalog.') from None
        return web.json_response(result)

    app.router.add_get('/api/admin/database/{view:catalog|structure|rows|cell}', handle, allow_head=False)
