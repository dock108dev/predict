"""Resumable current traversal receipts; no append-only response history."""
from hashlib import sha256
import json
from uuid import uuid4

from psycopg.types.json import Jsonb
from app.storage.store import connect


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
                db.execute('INSERT INTO current_acquisition_query '
                           '(source,query_key,generation,request) VALUES (%s,%s,%s,%s)',
                           (self.source, key, self.generation, Jsonb(request)))
            else:
                self.generation = row['generation']
            pages = [r['receipt'] for r in db.execute(
                'SELECT receipt FROM current_acquisition_page WHERE source=%s '
                'AND query_key=%s ORDER BY position', (self.source, key))]
        return key, pages

    def page(self, key, index, receipt, complete):
        with connect() as db, db.transaction():
            db.execute('INSERT INTO current_acquisition_page VALUES (%s,%s,%s,%s) '
                       'ON CONFLICT (source,query_key,position) DO UPDATE SET receipt=EXCLUDED.receipt',
                       (self.source, key, index, Jsonb(receipt)))
            if complete:
                db.execute('UPDATE current_acquisition_query SET completed_at=now() '
                           'WHERE source=%s AND query_key=%s', (self.source, key))

    def finish(self):
        # Publication succeeded. The next pass obtains fresh boundaries; retain
        # this census until its replacement query begins, not an update archive.
        with connect() as db:
            db.execute('UPDATE current_acquisition_query SET generation=%s WHERE source=%s',
                       ('published', self.source))
        self.generation = None

    def begin(self):
        with connect() as db:
            db.execute("DELETE FROM current_acquisition_query WHERE source=%s AND generation='published'",
                       (self.source,))


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
            with db.cursor() as cur:
                cur.executemany('UPDATE current_acquisition_image SET disposition=%s '
                    'WHERE source=%s AND event_id=%s AND market_id=%s AND received_at=%s '
                    'AND disposition IS DISTINCT FROM %s',
                    [(disposition,source,b['raw']['ref']['event_id'],b['raw']['ref']['market_id'],b['raw']['received_at'],disposition) for b in books])
            return
        # The current image only moves forward. An already superseded receipt
        # cannot become eligible again, so avoid serializing its complete depth.
        from datetime import datetime
        prior={(r['event_id'],r['market_id']):r for r in db.execute(
            'SELECT i.event_id,i.market_id,i.received_at,i.disposition FROM current_acquisition_image i '
            'JOIN unnest(%s::text[],%s::text[]) AS wanted(event_id,market_id) '
            'ON i.event_id=wanted.event_id AND i.market_id=wanted.market_id WHERE i.source=%s',
            ([b['raw']['ref']['event_id'] for b in books],[b['raw']['ref']['market_id'] for b in books],source))}
        def eligible(book):
            old=prior.get((book['raw']['ref']['event_id'],book['raw']['ref']['market_id']))
            if old is None:return True
            at=datetime.fromisoformat(book['raw']['received_at'].replace('Z','+00:00'))
            return old['received_at']<at or not ensure_only and old['received_at']==at and (disposition!='pending' or old['disposition']=='pending')
        books=[b for b in books if eligible(b)]
        with db.cursor() as cur:
            cur.executemany('INSERT INTO current_acquisition_image (source,event_id,market_id,received_at,disposition,image,runtime_id,connection_generation,census_generation) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) '
                'ON CONFLICT (source,event_id,market_id) DO UPDATE SET '
                'received_at=EXCLUDED.received_at,disposition=EXCLUDED.disposition,image=EXCLUDED.image, '
                'runtime_id=CASE WHEN current_acquisition_image.received_at=EXCLUDED.received_at THEN COALESCE(EXCLUDED.runtime_id,current_acquisition_image.runtime_id) ELSE EXCLUDED.runtime_id END, '
                'connection_generation=CASE WHEN current_acquisition_image.received_at=EXCLUDED.received_at THEN COALESCE(EXCLUDED.connection_generation,current_acquisition_image.connection_generation) ELSE EXCLUDED.connection_generation END, '
                'census_generation=CASE WHEN current_acquisition_image.received_at=EXCLUDED.received_at THEN COALESCE(EXCLUDED.census_generation,current_acquisition_image.census_generation) ELSE EXCLUDED.census_generation END '
                'WHERE current_acquisition_image.received_at<EXCLUDED.received_at OR '
                '(current_acquisition_image.received_at=EXCLUDED.received_at AND '
                "(EXCLUDED.disposition<>'pending' OR current_acquisition_image.disposition='pending') AND "
                +('false' if ensure_only else 'true')+")",
                [(source,b['raw']['ref']['event_id'],b['raw']['ref']['market_id'],
                  b['raw']['received_at'],disposition,Jsonb(b),*(contexts or {}).get(b['raw']['ref']['market_id'],(None,None,None))) for b in books])


def save_census(source, events, markets, parsed):
    """Commit the independent complete metadata roster, including unparsed rows."""
    from .current_sink import utc
    at, generation = utc(), str(uuid4())
    parents = {e['id']: e for e in events}
    with connect() as db, db.transaction():
        with db.cursor() as cur:
            cur.executemany('INSERT INTO current_acquisition_market '
                '(source,event_id,market_id,sport,family,generation,observed_at,withdrawn,disposition,metadata) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,false,%s,%s) '
                'ON CONFLICT (source,event_id,market_id) DO UPDATE SET '
                'sport=EXCLUDED.sport,family=EXCLUDED.family,generation=EXCLUDED.generation,'
                'observed_at=EXCLUDED.observed_at,withdrawn=false,absent_since=NULL,missing_passes=0,'
                'disposition=EXCLUDED.disposition,metadata=EXCLUDED.metadata',
                [(source,m['event_id'],m['id'],parents[m['event_id']]['competition'],m['market_type'],
                  generation,at,'subscribed' if m['id'] in parsed else 'not_subscribed_parser_or_eligibility',
                  Jsonb(m['_native'])) for m in markets])
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
        db.execute("DELETE FROM current_acquisition_image i WHERE received_at<now()-interval '2 days' AND NOT EXISTS "
                   '(SELECT 1 FROM current_acquisition_market m WHERE m.source=i.source AND '
                   'm.event_id=i.event_id AND m.market_id=i.market_id AND NOT m.withdrawn)')

    return generation


def read_page(reference):
    with connect() as db:
        row=db.execute('SELECT receipt FROM current_acquisition_page WHERE source=%s AND query_key=%s AND position=%s',
                       (reference['source'],reference['query_key'],reference['position'])).fetchone()
    if row is None:
        raise ValueError('current_checkpoint_page_unavailable')
    return row['receipt']


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
        db.execute('INSERT INTO current_acquisition_failure '
            '(source,received_at,generation,stage,disposition,body_sha256,wire_bytes,body) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
            (source,received_at,generation,stage,'unusable_not_math_eligible',sha256(raw).hexdigest(),len(raw),raw))
        db.execute("DELETE FROM current_acquisition_failure WHERE received_at<now()-interval '1 day'")
        db.execute('DELETE FROM current_acquisition_failure WHERE source=%s AND id NOT IN '
            '(SELECT id FROM current_acquisition_failure WHERE source=%s ORDER BY id DESC LIMIT 64)',(source,source))
