"""Passive catalog snapshots and exact-revision export for personal research."""

import asyncio
import json
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from aiohttp import web

from app.collection.runtime_status import read_runtime
from app.storage import research_catalog as catalog
from app.storage.store import connect, encoded
from .local_security import HEADERS, PublicRequestError
from .raw_price_api import RawReads


class CatalogReads(RawReads):
    def read(self, query):
        with self.lock:
            self.cleanup()
            if query.get('release'):
                self.close(query['release'])
            filters = {key: query[key] for key in (*catalog.FILTERS, 'search', 'calculation_status', 'max_age_minutes') if query.get(key)}
            token = query.get('token')
            if token:
                frame = self.frames.get(token)
                if not frame or frame['filters'] != filters:
                    raise PublicRequestError('Catalog snapshot expired or filters changed; refresh data.')
            else:
                if len(self.frames) >= 8:
                    raise PublicRequestError('Catalog read capacity reached; close another view.')
                db = self.connector()
                try:
                    db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    db.execute("SET LOCAL idle_in_transaction_session_timeout='125s'")
                    db.execute("SET LOCAL statement_timeout='10s'")
                    frame = dict(db=db, filters=filters, expires=monotonic()+120,
                        at=db.execute('SELECT transaction_timestamp() at').fetchone()['at'].isoformat(),
                        owner=read_runtime(db), counts=catalog.counts(db, filters))
                    token = uuid4().hex
                    self.frames[token] = frame
                except BaseException:
                    db.close()
                    raise
            with self.snapshot_read(token):
                offset, limit = int(query.get('offset', 0)), int(query.get('limit', 50))
                rows = [catalog.entry(frame['db'], row, frame['owner']) for row in
                    catalog.headers(frame['db'], filters, offset=offset, limit=limit)]
                total = frame['counts']['records']
                return dict(schema='predict-research-catalog-1', token=token, captured_at=frame['at'],
                    read_at=datetime.now(timezone.utc).isoformat(), counts=frame['counts'],
                    rows=rows, total=total, offset=offset,
                    next_offset=offset+len(rows) if offset+len(rows)<total else None,
                    provider_requests=0, scheduled_calculations=0,
                    population='Received current source records, independent of fees, matching and EV. '
                        'Retained withdrawn/stale rows remain inspectable. Historical archive is separate.')

    def detail(self, query):
        with self.lock:
            self.cleanup()
            frame = self.frames.get(query['token'])
            if not frame:
                raise PublicRequestError('Catalog snapshot expired; refresh data.')
            with self.snapshot_read(query['token']):
                rows = catalog.headers(frame['db'], frame['filters'], entry_id=query['id'], limit=1)
                if not rows:
                    raise PublicRequestError('Unknown captured catalog record.')
                value = catalog.entry(frame['db'], rows[0], frame['owner'], detail=True)
                if value['revision'] != query['revision']:
                    raise PublicRequestError('Catalog revision differs from captured input.')
                return dict(value, captured_at=frame['at'])


def mount(app):
    reads = CatalogReads(connect)
    gate = asyncio.Semaphore(4)

    async def joined(fn, *args):
        from app.owned_work import joined_thread
        return await joined_thread(__name__, 'catalog_read_after_cancellation', fn, *args)

    async def life(_):
        async def cleanup():
            while True:
                await asyncio.sleep(5)
                await joined(reads.cleanup)
        task = asyncio.create_task(cleanup())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            await joined(reads.close)
    app.cleanup_ctx.append(life)

    def validate(query, *, detail=False):
        allowed = set((*catalog.FILTERS, 'search', 'calculation_status', 'max_age_minutes',
            'token', 'release', 'offset', 'limit'))
        if detail:
            allowed |= {'id', 'revision'}
        if set(query)-allowed or any(len(value)>1024 for value in query.values()):
            raise PublicRequestError('Invalid catalog filters.')
        try:
            if not 0 <= int(query.get('offset', 0)) <= 2147483647 or not 1 <= int(query.get('limit', 50)) <= 100:
                raise ValueError()
            if query.get('max_age_minutes') and not 1 <= int(query['max_age_minutes']) <= 525600:
                raise ValueError()
        except ValueError:
            raise PublicRequestError('Invalid catalog page or source age.') from None
        if query.get('calculation_status') not in (None, '', 'positive', 'negative', 'zero', 'unavailable'):
            raise PublicRequestError('Unknown calculation status.')
        if detail and not all(query.get(key) for key in ('token', 'id', 'revision')):
            raise PublicRequestError('Captured catalog identity required.')

    async def page(request):
        validate(request.query)
        if gate.locked():
            raise web.HTTPTooManyRequests()
        async with gate:
            value = await joined(reads.read, dict(request.query))
        return web.json_response(value, headers=HEADERS)

    async def detail(request):
        validate(request.query, detail=True)
        if gate.locked():
            raise web.HTTPTooManyRequests()
        async with gate:
            value = await joined(reads.detail, dict(request.query))
        return web.json_response(value, headers=HEADERS)

    async def export(request):
        validate(request.query, detail=True)
        if gate.locked():
            raise web.HTTPTooManyRequests()
        async with gate:
            value = await joined(reads.detail, dict(request.query))
        return web.Response(text=json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n',
            content_type='application/json', headers={**HEADERS,
                'Content-Disposition': 'attachment; filename="predict-research-record.json"'})

    async def release(request):
        if set(request.query) != {'token'}:
            raise PublicRequestError('Catalog token required.')
        async with gate:
            await joined(reads.close, request.query['token'])
        return web.json_response(dict(released=True, provider_requests=0))

    async def coverage(request):
        if request.query:
            raise PublicRequestError('Coverage takes no filters.')
        def work():
            from app.storage.research_coverage import report
            from app.collection.original_receipts import status
            with connect() as db, db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                db.execute("SET LOCAL statement_timeout='10s'")
                return dict(coverage=report(db), original_responses=status(), provider_requests=0)
        async with gate:
            value = await joined(work)
        from .pipeline import serial
        return web.json_response(serial(value), headers=HEADERS)

    async def cohorts(request):
        if set(request.query)-{'id', 'as_of', 'export'}:
            raise PublicRequestError('Invalid research cohort selection.')
        exporting = request.query.get('export') == '1'
        if request.query.get('export') not in (None, '1') or exporting and (
                not request.query.get('id') or request.query.get('as_of')):
            raise PublicRequestError('A frozen-evidence export requires one cohort ID.')
        def work():
            from app.research.records import list_cohorts, detail, evaluate, export_cohort
            from app.storage.store import stamp
            with connect() as db, db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                db.execute("SET LOCAL statement_timeout='10s'")
                if exporting:
                    return encoded(export_cohort(db, request.query['id']))
                if request.query.get('id'):
                    if request.query.get('as_of'):
                        return dict(evaluation=evaluate(db, request.query['id'],
                            as_of=stamp(request.query['as_of'])), provider_requests=0)
                    return detail(db, request.query['id'])
                return dict(cohorts=list_cohorts(db), provider_requests=0)
        async with gate:
            value = await joined(work)
        if exporting:
            return web.Response(body=value, content_type='application/json', headers={**HEADERS,
                'Content-Disposition': 'attachment; filename="predict-research-cohort.json"'})
        from .pipeline import serial
        return web.json_response(serial(value), headers=HEADERS)

    app.router.add_get('/api/research/catalog', page)
    app.router.add_get('/api/research/input', detail)
    app.router.add_get('/api/research/export', export)
    app.router.add_delete('/api/research/read', release)
    app.router.add_get('/api/research/coverage', coverage)
    app.router.add_get('/api/research/cohorts', cohorts)
