"""Resumable current traversal receipts; no append-only response history."""
from hashlib import sha256
import json
from uuid import uuid4

from psycopg.types.json import Jsonb
from app.storage.store import connect
from app.storage.recovery_codec import freeze,thaw
from app.storage import native_market_metadata


class Checkpoint:
    def __init__(self, source, scope):
        self.source = source
        self.scope = sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
        self.generation = None

    def query(self, path, params):
        request = dict(path=path, params=params, scope=self.scope)
        key = sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        with connect() as db, db.transaction():
            row = db.execute(
                'SELECT generation FROM current_acquisition_query WHERE source=%s '
                'AND query_key=%s', (self.source, key)).fetchone()
            if row is None:
                self.generation = self.generation or str(uuid4())
                db.execute("INSERT INTO acquisition_receipt "
                           "(kind,source,scope,query_generation,payload,started_at) VALUES ('query',%s,%s,%s,%s,now())",
                           (self.source, key, self.generation, Jsonb(request)))
            else:
                self.generation = row['generation']
            pages = [thaw(r['receipt']) for r in db.execute(
                'SELECT receipt FROM current_acquisition_page WHERE source=%s '
                'AND query_key=%s ORDER BY position', (self.source, key))]
        return key, pages

    def completed_details(self):
        """Only this active traversal's exact, unparameterized event queries."""
        with connect() as db:
            return {r['path'] for r in db.execute(
                "SELECT request->>'path' AS path FROM current_acquisition_query "
                "WHERE source=%s AND request->>'scope'=%s AND request->'params'='{}'::jsonb "
                "AND request->>'path' LIKE '/v1/events/%%' AND completed_at IS NOT NULL "
                "AND generation<>'published'", (self.source, self.scope))}

    def page(self, key, index, receipt, complete):
        with connect() as db, db.transaction():
            db.execute("INSERT INTO acquisition_receipt (kind,source,scope,position,payload) "
                       "VALUES ('page',%s,%s,%s,%s) ON CONFLICT (kind,source,scope,event_id,position) "
                       "DO UPDATE SET payload=EXCLUDED.payload WHERE acquisition_receipt.payload IS DISTINCT FROM EXCLUDED.payload",
                       (self.source, key, index, Jsonb(freeze(receipt))))
            if complete:
                db.execute("UPDATE acquisition_receipt SET completed_at=now() "
                           "WHERE kind='query' AND source=%s AND scope=%s", (self.source, key))

    def finish(self):
        # Publication succeeded. The next pass obtains fresh boundaries; retain
        # this census until its replacement query begins, not an update archive.
        with connect() as db:
            db.execute("UPDATE acquisition_receipt SET query_generation=%s WHERE kind='query' AND source=%s",
                       ('published', self.source))
        self.generation = None

    def begin(self):
        with connect() as db:
            db.execute("DELETE FROM acquisition_receipt WHERE kind='query' AND source=%s AND query_generation='published'",
                       (self.source,))

    def listing_start(self, proposed):
        """Resume one fixed lower bound until this complete census publishes."""
        with connect() as db:
            values={r['start'] for r in db.execute(
                "SELECT request->'params'->>'startTimeMin' AS start FROM current_acquisition_query "
                "WHERE source=%s AND request->>'scope'=%s AND request->>'path'='/v1/events' "
                "AND generation<>'published' AND request->'params' ? 'startTimeMin'",(self.source,self.scope))}
        if len(values)>1:raise ValueError('conflicting_listing_windows')
        return next(iter(values)) if values else proposed


def image_parts(book):
    # SQL NULL means absent; JSON null and empty arrays/strings are evidence.
    header=dict(book,raw=dict(book['raw']))
    depth=Jsonb(header.pop('outcomes')) if 'outcomes' in header else None
    wire=Jsonb(header['raw'].pop('json_text')) if 'json_text' in header['raw'] else None
    return Jsonb(header),depth,wire


def save_images(source, books, disposition, contexts=None, *, known_persisted=False, ensure_only=False):
    if ensure_only and (disposition!='pending' or contexts is not None):
        raise ValueError('invalid_image_ensure')
    # Raw and derived writers overlap. Acquire exact image rows in one order
    # while stable sorting preserves receipt order for duplicate identities.
    books=sorted(books,key=lambda b:(b['raw']['ref']['event_id'],b['raw']['ref']['market_id']))
    if not books:return
    with connect() as db, db.transaction():
        if known_persisted:
            if disposition not in ('admitted','rejected') or contexts is not None:
                raise ValueError('invalid_persisted_image_disposition')
            # Lock in the same identity order as the raw writer. One statement
            # marks exact persisted receipts without resending any book payload.
            db.execute("""WITH wanted AS MATERIALIZED (
                SELECT DISTINCT * FROM unnest(%s::text[],%s::text[],%s::timestamptz[]) w(event_id,market_id,received_at)
                ORDER BY event_id,market_id,received_at),
              locked AS MATERIALIZED (
                SELECT found.* FROM wanted w CROSS JOIN LATERAL (
                  SELECT i.source,i.event_id,i.market_id,i.received_at FROM current_acquisition_image_parts i
                  WHERE i.source=%s AND i.event_id=w.event_id AND i.market_id=w.market_id
                    AND i.received_at=w.received_at AND i.disposition IS DISTINCT FROM %s
                  LIMIT 1 FOR UPDATE OF i) found)
              UPDATE current_acquisition_image_parts i SET disposition=%s FROM locked l
              WHERE (i.source,i.event_id,i.market_id,i.received_at)=(l.source,l.event_id,l.market_id,l.received_at)""",
                ([b['raw']['ref']['event_id'] for b in books],[b['raw']['ref']['market_id'] for b in books],
                 [b['raw']['received_at'] for b in books],source,disposition,disposition))
            return
        # The current image only moves forward. An already superseded receipt
        # cannot become eligible again, so avoid serializing its complete depth.
        from datetime import datetime
        prior={(r['event_id'],r['market_id']):r for r in db.execute(
            'SELECT i.* FROM unnest(%s::text[],%s::text[]) AS wanted(event_id,market_id) '
            'CROSS JOIN LATERAL (SELECT event_id,market_id,received_at,disposition FROM current_acquisition_image_parts '
            'WHERE event_id=wanted.event_id AND market_id=wanted.market_id AND source=%s LIMIT 1) i',
            ([b['raw']['ref']['event_id'] for b in books],[b['raw']['ref']['market_id'] for b in books],source))}
        def eligible(book):
            old=prior.get((book['raw']['ref']['event_id'],book['raw']['ref']['market_id']))
            if old is None:return True
            at=datetime.fromisoformat(book['raw']['received_at'].replace('Z','+00:00'))
            return old['received_at']<at or not ensure_only and old['received_at']==at
        books=[b for b in books if eligible(b)]
        with db.cursor() as cur:
            cur.executemany('INSERT INTO current_acquisition_image_parts (source,event_id,market_id,received_at,disposition,image,depth_payload,wire_payload,runtime_id,connection_generation,census_generation) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) '
                'ON CONFLICT (source,event_id,market_id) DO UPDATE SET '
                "received_at=EXCLUDED.received_at,disposition=CASE WHEN current_acquisition_image_parts.received_at=EXCLUDED.received_at AND EXCLUDED.disposition='pending' THEN current_acquisition_image_parts.disposition ELSE EXCLUDED.disposition END, "
                'image=CASE WHEN current_acquisition_image_parts.image=EXCLUDED.image THEN current_acquisition_image_parts.image ELSE EXCLUDED.image END, '
                'depth_payload=CASE WHEN current_acquisition_image_parts.depth_payload IS NOT DISTINCT FROM EXCLUDED.depth_payload THEN current_acquisition_image_parts.depth_payload ELSE EXCLUDED.depth_payload END, '
                'wire_payload=CASE WHEN current_acquisition_image_parts.wire_payload IS NOT DISTINCT FROM EXCLUDED.wire_payload THEN current_acquisition_image_parts.wire_payload ELSE EXCLUDED.wire_payload END, '
                'runtime_id=CASE WHEN current_acquisition_image_parts.received_at=EXCLUDED.received_at THEN COALESCE(EXCLUDED.runtime_id,current_acquisition_image_parts.runtime_id) ELSE EXCLUDED.runtime_id END, '
                'connection_generation=CASE WHEN current_acquisition_image_parts.received_at=EXCLUDED.received_at THEN COALESCE(EXCLUDED.connection_generation,current_acquisition_image_parts.connection_generation) ELSE EXCLUDED.connection_generation END, '
                'census_generation=CASE WHEN current_acquisition_image_parts.received_at=EXCLUDED.received_at THEN COALESCE(EXCLUDED.census_generation,current_acquisition_image_parts.census_generation) ELSE EXCLUDED.census_generation END '
                'WHERE current_acquisition_image_parts.received_at<EXCLUDED.received_at OR '
                '(current_acquisition_image_parts.received_at=EXCLUDED.received_at AND '
                "(EXCLUDED.disposition<>'pending' OR current_acquisition_image_parts.disposition='pending' OR "
                "(current_acquisition_image_parts.image=EXCLUDED.image AND current_acquisition_image_parts.depth_payload IS NOT DISTINCT FROM EXCLUDED.depth_payload AND current_acquisition_image_parts.wire_payload IS NOT DISTINCT FROM EXCLUDED.wire_payload)) AND "
                +('false' if ensure_only else 'true')+") AND ("
                "(EXCLUDED.disposition<>'pending' AND current_acquisition_image_parts.disposition IS DISTINCT FROM EXCLUDED.disposition) OR "
                'current_acquisition_image_parts.image IS DISTINCT FROM EXCLUDED.image OR '
                'current_acquisition_image_parts.depth_payload IS DISTINCT FROM EXCLUDED.depth_payload OR '
                'current_acquisition_image_parts.wire_payload IS DISTINCT FROM EXCLUDED.wire_payload OR '
                '(EXCLUDED.runtime_id IS NOT NULL AND current_acquisition_image_parts.runtime_id IS DISTINCT FROM EXCLUDED.runtime_id) OR '
                '(EXCLUDED.connection_generation IS NOT NULL AND current_acquisition_image_parts.connection_generation IS DISTINCT FROM EXCLUDED.connection_generation) OR '
                '(EXCLUDED.census_generation IS NOT NULL AND current_acquisition_image_parts.census_generation IS DISTINCT FROM EXCLUDED.census_generation))',
                [(source,b['raw']['ref']['event_id'],b['raw']['ref']['market_id'],
                  b['raw']['received_at'],disposition,*image_parts(b),*(contexts or {}).get(b['raw']['ref']['market_id'],(None,None,None))) for b in books])


def save_census(source, events, markets, parsed):
    """Commit the independent complete metadata roster, including unparsed rows."""
    from .current_sink import utc
    at, generation = utc(), str(uuid4())
    parents = {e['id']: e for e in events}
    with connect() as db, db.transaction():
        native_market_metadata.hold(db)
        with db.cursor() as cur:
            size = native_market_metadata.MAX_BATCH_ROWS
            for offset in range(0, len(markets), size):
                bodies, jobs = {}, []
                for market in markets[offset:offset + size]:
                    body = market['_native']
                    ref = native_market_metadata.body_id(body)
                    bodies[ref] = body
                    event = parents[market['event_id']]
                    disposition = 'subscribed' if market['id'] in parsed else 'not_subscribed_parser_or_eligibility'
                    jobs.append((source, market['event_id'], market['id'], event['competition'], market['market_type'],
                                 generation, at, disposition, Jsonb(native_market_metadata.split_census(body)), ref))
                native_market_metadata.put(db, bodies)
                cur.executemany('INSERT INTO current_acquisition_market '
                    '(source,event_id,market_id,sport,family,generation,observed_at,withdrawn,disposition,metadata,metadata_id) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,false,%s,%s,%s) '
                    'ON CONFLICT (source,event_id,market_id) DO UPDATE SET '
                    'sport=EXCLUDED.sport,family=EXCLUDED.family,generation=EXCLUDED.generation,'
                    'observed_at=EXCLUDED.observed_at,withdrawn=false,absent_since=NULL,missing_passes=0,'
                    'disposition=EXCLUDED.disposition,metadata=EXCLUDED.metadata,metadata_id=EXCLUDED.metadata_id',
                    jobs)
        db.execute('UPDATE current_acquisition_market SET disposition=%s, '
                   'absent_since=COALESCE(absent_since,%s),missing_passes=missing_passes+1 '
                   'WHERE source=%s AND generation<>%s AND NOT withdrawn',
                   ('suspected_absent',at,source,generation))
        # Only explicit terminal source metadata can confirm withdrawal. Repeated
        # moving passes cannot strengthen absence into authoritative evidence.
        db.execute("UPDATE current_acquisition_market SET withdrawn=true,disposition='confirmed_closed' "
                   "WHERE source=%s AND generation=%s AND (metadata->'closed'='true'::jsonb "
                   "OR metadata->>'status' IN ('closed','settled','finalized'))", (source,generation))
        # Current evidence plus a short withdrawal inspection window, not history.
        db.execute("DELETE FROM current_acquisition_market WHERE withdrawn AND observed_at<now()-interval '2 days'")
        db.execute("DELETE FROM current_acquisition_image_parts i WHERE received_at<now()-interval '2 days' AND NOT EXISTS "
                   '(SELECT 1 FROM current_acquisition_market m WHERE m.source=i.source AND '
                   'm.event_id=i.event_id AND m.market_id=i.market_id AND NOT m.withdrawn)')

    return generation


def read_page(reference):
    with connect() as db:
        row=db.execute('SELECT receipt FROM current_acquisition_page WHERE source=%s AND query_key=%s AND position=%s',
                       (reference['source'],reference['query_key'],reference['position'])).fetchone()
    if row is None:
        raise ValueError('current_checkpoint_page_unavailable')
    return thaw(row['receipt'])


async def owned_thread(fn, *args, **kwargs):
    """Cancellation joins the current bounded operation before releasing ownership."""
    from app.owned_work import joined_thread
    return await joined_thread(__name__, 'owned_thread_after_cancellation', fn, *args, **kwargs)


def save_failure(source, raw, received_at, generation, stage):
    """Credential-checked untrusted bytes, opaque and bounded to 64/source/day."""
    if source not in ('kalshi','polymarket_us') or stage not in ('decode','reconstruct','confirm','queue'):
        raise ValueError('raw_failure_context_invalid')
    if not isinstance(raw,bytes) or len(raw)>256*1024:
        raise ValueError('raw_failure_size_invalid')
    with connect() as db, db.transaction():
        db.execute("INSERT INTO acquisition_receipt "
            "(kind,scope,position,source,received_at,failure_generation,failure_stage,disposition,receipt_sha256,wire_bytes,wire_body) "
            "VALUES ('failure','',nextval('acquisition_failure_id'),%s,%s,%s,%s,%s,%s,%s,%s)",
            (source,received_at,generation,stage,'unusable_not_math_eligible',sha256(raw).hexdigest(),len(raw),raw))
        db.execute("DELETE FROM acquisition_receipt WHERE kind='failure' AND received_at<now()-interval '1 day'")
        db.execute("DELETE FROM acquisition_receipt WHERE kind='failure' AND source=%s AND position NOT IN "
            "(SELECT position FROM acquisition_receipt WHERE kind='failure' AND source=%s ORDER BY position DESC LIMIT 64)",
            (source,source))
