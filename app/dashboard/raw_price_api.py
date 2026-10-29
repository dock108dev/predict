"""Bounded local raw reads with coherent PostgreSQL snapshot pagination."""
import asyncio
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import RLock
from time import monotonic
from uuid import uuid4
from aiohttp import web
from app.storage.store import connect
from app.storage import raw_prices
from app.collection.runtime_status import read_runtime
from .local_security import PublicRequestError, HEADERS


class RawReads:
    """At most eight read-only snapshots, 120 seconds each; no universe cache."""
    def __init__(self,connector=connect):
        self.connector=connector;self.frames={};self.lock=RLock()

    def close(self,token=None):
        with self.lock:
            first=None
            for key in list(self.frames):
                if token is None or token==key:
                    try:self.frames.pop(key)['db'].close()
                    except Exception as exc:
                        from app.diagnostics import failure
                        failure(__name__,'raw_snapshot_close',exc)
                        first=first or exc
            if first is not None:raise first

    def cleanup(self):
        with self.lock:
            expired=[key for key,value in self.frames.items() if value['expires']<=monotonic()]
            first=None
            for key in expired:
                try:self.close(key)
                except Exception as exc:first=first or exc
            if first is not None:raise first

    @contextmanager
    def snapshot_read(self,token):
        try:yield
        except PublicRequestError:
            # A stale selection or malformed identity does not abort SQL.
            raise
        except BaseException:
            # Never reuse an aborted transaction or retain an undisclosed token.
            try:self.close(token)
            except Exception:pass  # close logs; preserve the original read failure.
            raise

    def read(self,q):
        with self.lock:
            self.cleanup()
            if q.get('release'):self.close(q['release'])
            filters={k:q[k] for k in (*raw_prices.FILTERS,'search','state') if q.get(k)}
            offset=int(q.get('offset',0));limit=int(q.get('limit',50));token=q.get('token')
            if token:
                frame=self.frames.get(token)
                if not frame or frame['filters']!=filters:raise PublicRequestError('Raw page expired or filters changed; refresh prices')
            else:
                if len(self.frames)>=8:raise PublicRequestError('Raw read capacity reached; close or refresh another raw view')
                db=self.connector()
                try:
                    db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    db.execute("SET LOCAL idle_in_transaction_session_timeout='125s'")
                    db.execute("SET LOCAL statement_timeout='10s'")
                    at=db.execute('SELECT transaction_timestamp() at').fetchone()['at'].isoformat()
                    captured_owner=read_runtime(db)
                    frame=dict(db=db,filters=filters,expires=monotonic()+120,at=at,owner=captured_owner,total=raw_prices.total(db,filters,captured_owner))
                    token=uuid4().hex;self.frames[token]=frame
                except BaseException:
                    try:db.close()
                    except Exception as exc:
                        from app.diagnostics import failure
                        failure(__name__,'raw_snapshot_close',exc)
                    raise
            with self.snapshot_read(token):
                # Authority is always live, including while paging a captured frame.
                with self.connector() as live:owner=read_runtime(live)
                rows=[raw_prices.book(frame['db'],r,owner) for r in raw_prices.headers(frame['db'],filters,offset,limit,frame['owner'])]
                end=offset+len(rows)
                return dict(schema='predict-raw-prices-1',token=token,captured_at=frame['at'],
                    read_at=datetime.now(timezone.utc).isoformat(),expires_in_seconds=max(0,frame['expires']-monotonic()),
                    total_books=frame['total'],offset=offset,books=rows,
                    next_offset=end if end<frame['total'] else None,provider_requests=0,
                    offered_denominator='unknown',financial_independent=True,
                    sources={v:raw_prices.source_information(owner,v) for v in sorted({b['venue'] for b in rows})})

    def detail(self,q):
        with self.lock:
            self.cleanup();frame=self.frames.get(q['token'])
            if not frame:raise PublicRequestError('Captured inputs expired; refresh prices')
            with self.snapshot_read(q['token']):
                identity={k:q[k] for k in ('kind','venue','sport','event_id','market_id')}
                with self.connector() as live:owner=read_runtime(live)
                row=frame['db'].execute('SELECT * FROM ('+raw_prices.HEADER+') h WHERE kind=%s AND venue=%s AND sport=%s AND event_id=%s AND market_id=%s',tuple(identity[k] for k in ('kind','venue','sport','event_id','market_id'))).fetchone()
                if row is None:raise PublicRequestError('Unknown captured input')
                value=raw_prices.book(frame['db'],row,owner)
                if value['revision']!=q['revision']:raise PublicRequestError('Input revision changed')
                if q.get('outcome') and identity['kind']=='native':
                    value['depth_page']=raw_prices.depth_page(frame['db'],identity,q['outcome'],q['side'],int(q.get('offset',0)),100)
                if identity['kind']=='native':
                    wire=frame['db'].execute("SELECT image->'raw'->>'json_text' wire FROM current_acquisition_image WHERE source=%s AND event_id=%s AND market_id=%s",(identity['venue'],identity['event_id'],identity['market_id'])).fetchone()
                    value['native_wire']=wire['wire'] if wire else None
                value.update(provider_requests=0,captured_at=frame['at'],source_status=raw_prices.source_information(owner,identity['venue']))
                return value


def mount(app):
    reads=RawReads(connect);gate=asyncio.Semaphore(4)
    async def life(_):
        async def cleanup():
            while True:
                await asyncio.sleep(5)
                await joined(reads.cleanup)
        task=asyncio.create_task(cleanup())
        yield
        task.cancel()
        try:
            try:await task
            except asyncio.CancelledError:pass
        finally:await joined(reads.close)
    app.cleanup_ctx.append(life)

    def validate(q,detail=False):
        allowed=set((*raw_prices.FILTERS,'search','state','offset','limit','token','release'))
        if detail:allowed|={'kind','market_id','revision','outcome','side'}
        if set(q)-allowed or any(len(v)>512 for v in q.values()):raise PublicRequestError('Invalid raw filters')
        try:
            if not 0<=int(q.get('offset',0))<=2147483647 or not 1<=int(q.get('limit',50))<=100:raise ValueError()
        except ValueError:raise PublicRequestError('Invalid raw page') from None
        if detail and not all(q.get(k) for k in ('token','kind','venue','sport','event_id','market_id','revision')):raise PublicRequestError('Captured identity required')

    async def joined(fn,*args):
        from app.owned_work import joined_thread
        return await joined_thread(__name__, 'raw_read_after_cancellation', fn, *args)

    async def page(req):
        validate(req.query)
        if gate.locked():raise web.HTTPTooManyRequests()
        async with gate:value=await joined(reads.read,dict(req.query))
        return web.json_response(value)

    async def detail(req):
        validate(req.query,True)
        if gate.locked():raise web.HTTPTooManyRequests()
        async with gate:value=await joined(reads.detail,dict(req.query))
        return web.json_response(value)

    async def export(req):
        # One server-side cursor, one coherent transaction. Backpressure bounds
        # memory; disconnect/finally closes the snapshot. No provider dependency.
        if req.query:raise PublicRequestError('Export includes the complete received universe')
        if gate.locked():raise web.HTTPTooManyRequests()
        async with gate:
            db=None
            def open_connection():
                nonlocal db
                db=connect()
            try:
                await joined(open_connection)
                await joined(db.execute,'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
                await joined(db.execute,"SET LOCAL statement_timeout='10s'")
                await joined(db.execute,"SET LOCAL idle_in_transaction_session_timeout='125s'")
                owner=await joined(read_runtime,db)
                response=web.StreamResponse(headers={**HEADERS,'Content-Type':'application/x-ndjson','Content-Disposition':'attachment; filename="predict-original-inputs.ndjson"'})
                await response.prepare(req)
                cursor=db.cursor(name='raw_export')
                await joined(cursor.execute,raw_prices.HEADER+' ORDER BY venue,event_id,market_id,kind,sport')
                count=0;units=0
                while True:
                    rows=await joined(cursor.fetchmany,50)
                    if not rows:break
                    for row in rows:
                        value=await joined(raw_prices.book,db,row,owner)
                        count+=1;units+=sum(o['price'] is not None for o in value['observations'])
                        await response.write((json.dumps(value,separators=(',',':'))+'\n').encode())
                        if row['kind']=='native':
                            wire=await joined(lambda: db.execute("SELECT image->'raw'->>'json_text' wire FROM current_acquisition_image WHERE source=%s AND event_id=%s AND market_id=%s",(row['venue'],row['event_id'],row['market_id'])).fetchone())
                            await response.write((json.dumps(dict(book_id=value['id'],native_wire=wire['wire']))+'\n').encode())
                            for o in value['observations']:
                                offset=0
                                while offset is not None and o['levels']:
                                    depth=await joined(raw_prices.depth_page,db,row,o['outcome_id'],o['side'],offset,100)
                                    await response.write((json.dumps(dict(book_id=value['id'],observation_id=o['id'],depth_offset=offset,depth=depth),separators=(',',':'))+'\n').encode())
                                    offset=depth['next_offset']
                failures=await joined(lambda: db.execute('SELECT id,source,received_at,stage,disposition,body_sha256,wire_bytes,body FROM current_acquisition_failure ORDER BY id').fetchall())
                for item in failures:
                    item['body']=bytes(item['body']).decode('utf-8',errors='replace');item['received_at']=item['received_at'].isoformat()
                    await response.write((json.dumps(dict(unqualified_frame=item))+'\n').encode())
                await response.write((json.dumps(dict(export_complete=True,books=count,price_units=units,provider_requests=0))+'\n').encode())
                await response.write_eof();return response
            finally:
                if db is not None:await joined(db.close)

    async def calculations(req):
        validate(req.query,True)
        if not req.query.get('outcome') or not req.query.get('side'):raise PublicRequestError('Exact native observation required')
        def read():
            from app.storage.raw_calculations import read as captured_results
            book=reads.detail(dict(req.query))
            observation=next((o for o in book['observations'] if o['outcome_id']==req.query['outcome'] and o['side']==req.query['side']),None)
            if observation is None:raise PublicRequestError('Unknown observation')
            with connect() as db,db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                return captured_results(db,book,observation,int(req.query.get('offset',0)))
        if gate.locked():raise web.HTTPTooManyRequests()
        async with gate:value=await joined(read)
        return web.json_response(value)

    app.router.add_get('/api/raw/calculations',calculations)
    async def failures(req):
        if set(req.query)-{'id'}:raise PublicRequestError('Invalid failure selection')
        def read():
            with connect() as db:
                if req.query.get('id'):
                    row=db.execute('SELECT id,source,received_at,stage,disposition,body_sha256,wire_bytes,body FROM current_acquisition_failure WHERE id=%s',(int(req.query['id']),)).fetchone()
                    if row:
                        row['body']=bytes(row['body']).decode('utf-8',errors='replace')
                        row['received_at']=row['received_at'].isoformat()
                    return dict(failure=row,provider_requests=0)
                rows=db.execute('SELECT id,source,received_at,stage,disposition,body_sha256,wire_bytes FROM current_acquisition_failure ORDER BY id DESC').fetchall()
                for row in rows:row['received_at']=row['received_at'].isoformat()
                return dict(failures=rows,retention='Up to 64 credential-checked frames per source for one day; not an offered-price denominator',provider_requests=0)
        if gate.locked():raise web.HTTPTooManyRequests()
        async with gate:value=await joined(read)
        return web.json_response(value)

    async def release(req):
        if set(req.query)!={'token'}:raise PublicRequestError('Raw read token required')
        if gate.locked():raise web.HTTPTooManyRequests()
        async with gate:await joined(reads.close,req.query['token'])
        return web.json_response(dict(released=True,provider_requests=0))

    app.router.add_delete('/api/raw/read',release)
    app.router.add_get('/api/raw/failures',failures)
    app.router.add_get('/api/raw/prices',page)
    app.router.add_get('/api/raw/inputs',detail)
    app.router.add_get('/api/raw/export',export)
