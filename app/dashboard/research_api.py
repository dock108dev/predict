"""Passive catalog snapshots and exact-revision export for personal research."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from aiohttp import web

from app.collection.runtime_status import read_runtime
from app.comparison.reference_scope import PROVIDER, public_scope
from app.storage import research_catalog as catalog
from app.storage.store import connect, encoded
from .local_security import HEADERS, PublicRequestError
from .raw_price_api import RawReads

CATALOG_READ_CAPACITY = 4
# The existing browser deadline is 15s and a SQL statement can consume 10s.
# Wait within that allowance without admitting more concurrent read owners.
CATALOG_ADMISSION_WAIT_SECONDS = 4


class CatalogReads(RawReads):
    def _frame(self, query):
        self.cleanup()
        if query.get('release'):
            self.close(query['release'])
        filters = {key: query[key] for key in catalog.READ_FILTERS if query.get(key)}
        filters.setdefault('reference_scope', 'selected')
        if filters['reference_scope'] != 'all':
            filters.setdefault('provider', PROVIDER)
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
                db.execute("SET LOCAL jit='off'")
                frame = dict(db=db, filters=filters, expires=monotonic()+120,
                    at=db.execute('SELECT transaction_timestamp() at').fetchone()['at'].isoformat(),
                    owner=read_runtime(db), counts=None, game_counts=None)
                from app.comparison.fee_mode import read as read_fee_mode
                frame['fee_mode'] = read_fee_mode(db)
                token = uuid4().hex
                self.frames[token] = frame
            except BaseException:
                db.close()
                raise
        return token, frame

    def read(self, query):
        with self.lock:
            token, frame = self._frame(query)
            with self.snapshot_read(token):
                filters = dict(frame['filters'])
                filters.update({key: query[key] for key in catalog.SCOPED_SELECTIONS if query.get(key)})
                if query.get('game_id'):
                    filters.pop('calculation_status', None)
                offset, limit = int(query.get('offset', 0)), int(query.get('limit', 50))
                rows = [catalog.entry(frame['db'], row, frame['owner']) for row in
                    catalog.headers(frame['db'], filters, offset=offset, limit=limit)]
                if filters != frame['filters']:
                    counts = catalog.counts(frame['db'], filters)
                else:
                    if frame['counts'] is None:
                        frame['counts'] = catalog.counts(frame['db'], filters)
                    counts = frame['counts']
                total = counts['records']
                game = catalog.games(frame['db'], filters, limit=1) if query.get('game_id') else []
                return dict(schema='predict-research-catalog-1', token=token, captured_at=frame['at'],
                    read_at=datetime.now(timezone.utc).isoformat(), counts=counts,
                    rows=rows, total=total, offset=offset, game=game[0] if game else None,
                    next_offset=offset+len(rows) if offset+len(rows)<total else None,
                    provider_requests=0, scheduled_calculations=0,
                    reference_scope=public_scope(), fee_mode=frame['fee_mode'],
                    population='Latest stored source observations; frozen first-observation/T−10 captures are separate. '
                        'Received prices remain visible independently of fees, matching and EV.')

    def games(self, query):
        with self.lock:
            token, frame = self._frame(query)
            with self.snapshot_read(token):
                filters = dict(frame['filters'])
                filters.update({key: query[key] for key in catalog.SCOPED_SELECTIONS if query.get(key)})
                if filters != frame['filters']:
                    counts = catalog.game_counts(frame['db'], filters)
                else:
                    if frame['game_counts'] is None:
                        frame['game_counts'] = catalog.game_counts(frame['db'], filters)
                    counts = frame['game_counts']
                offset, limit = int(query.get('offset', 0)), int(query.get('limit', 50))
                rows = catalog.games(frame['db'], filters, offset=offset, limit=limit)
                total = counts['games']
                return dict(schema='predict-data-games-1', token=token, captured_at=frame['at'],
                    read_at=datetime.now(timezone.utc).isoformat(), counts=counts,
                    rows=rows, total=total, offset=offset,
                    next_offset=offset+len(rows) if offset+len(rows)<total else None,
                    provider_requests=0, scheduled_calculations=0,
                    reference_scope=public_scope(), fee_mode=frame['fee_mode'],
                    population='Canonical games and separately identified source-local events. '
                        'Retained checkpoint games remain inspectable after current observations expire.')

    def detail(self, query):
        with self.lock:
            self.cleanup()
            frame = self.frames.get(query['token'])
            if not frame:
                raise PublicRequestError('Catalog snapshot expired; refresh data.')
            with self.snapshot_read(query['token']):
                filters = dict(frame['filters'])
                if query.get('game_id'):
                    filters.pop('calculation_status', None)
                    filters['game_id'] = query['game_id']
                rows = catalog.headers(frame['db'], filters, entry_id=query['id'], limit=1)
                if not rows:
                    raise PublicRequestError('Unknown captured catalog record.')
                value = catalog.entry(frame['db'], rows[0], frame['owner'], detail=True)
                if value['revision'] != query['revision']:
                    raise PublicRequestError('Catalog revision differs from captured input.')
                return dict(value, captured_at=frame['at'])


def mount(app):
    reads = CatalogReads(connect)
    gate = asyncio.Semaphore(CATALOG_READ_CAPACITY)

    @asynccontextmanager
    async def admission():
        try:
            await asyncio.wait_for(gate.acquire(), timeout=CATALOG_ADMISSION_WAIT_SECONDS)
        except TimeoutError:
            raise web.HTTPServiceUnavailable(reason='Stored data reads are busy. Retry shortly.',
                headers={'Retry-After': '1'}) from None
        try:
            yield
        finally:
            gate.release()

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
        allowed = set((*catalog.READ_FILTERS, *catalog.SCOPED_SELECTIONS, 'token', 'release', 'offset', 'limit'))
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
        if query.get('date'):
            from datetime import date
            try:
                if date.fromisoformat(query['date']).isoformat() != query['date']:
                    raise ValueError()
            except ValueError:
                raise PublicRequestError('Invalid game date; use YYYY-MM-DD.') from None
        if query.get('calculation_status') not in (None, '', 'positive', 'negative', 'zero', 'unavailable', 'reference_only'):
            raise PublicRequestError('Unknown calculation status.')
        if query.get('reference_scope') not in (None, '', 'selected', 'all'):
            raise PublicRequestError('Unknown reference scope.')
        if query.get('provider') not in (None, '', PROVIDER) and query.get('reference_scope') != 'all':
            raise PublicRequestError('Other source records require explicit historical selection.')
        if detail and not all(query.get(key) for key in ('token', 'id', 'revision')):
            raise PublicRequestError('Captured catalog identity required.')

    async def page(request):
        validate(request.query)
        async with admission():
            value = await joined(reads.read, dict(request.query))
        return web.json_response(value, headers=HEADERS)

    async def games(request):
        validate(request.query)
        async with admission():
            value = await joined(reads.games, dict(request.query))
        return web.json_response(value, headers=HEADERS)

    async def game(request):
        if not request.query.get('game_id'):
            raise PublicRequestError('A captured game identity is required.')
        return await page(request)

    async def detail(request):
        validate(request.query, detail=True)
        async with admission():
            value = await joined(reads.detail, dict(request.query))
        return web.json_response(value, headers=HEADERS)

    async def export(request):
        validate(request.query, detail=True)
        async with admission():
            value = await joined(reads.detail, dict(request.query))
        return web.Response(text=json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n',
            content_type='application/json', headers={**HEADERS,
                'Content-Disposition': 'attachment; filename="predict-research-record.json"'})

    async def release(request):
        if set(request.query) != {'token'}:
            raise PublicRequestError('Catalog token required.')
        async with admission():
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
        async with admission():
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
            from app.research.records import list_cohorts, detail, evaluate, export_cohort, status as retention_status
            from app.storage.store import stamp
            with connect() as db, db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                db.execute("SET LOCAL statement_timeout='10s'")
                if exporting:
                    return encoded(export_cohort(db, request.query['id']))
                retention = retention_status(db)
                if request.query.get('id'):
                    if request.query.get('as_of'):
                        return dict(evaluation=evaluate(db, request.query['id'],
                            as_of=stamp(request.query['as_of'])), research_retention=retention, provider_requests=0)
                    return dict(detail(db, request.query['id']), research_retention=retention)
                return dict(cohorts=list_cohorts(db), research_retention=retention, provider_requests=0)
        async with admission():
            value = await joined(work)
        if exporting:
            return web.Response(body=value, content_type='application/json', headers={**HEADERS,
                'Content-Disposition': 'attachment; filename="predict-research-cohort.json"'})
        from .pipeline import serial
        return web.json_response(serial(value), headers=HEADERS)

    async def experiment(request):
        query = dict(request.query)
        if set(query)-{'id', 'revision', 'export', 'include_context', 'limit', 'offset'} or any(
                len(value) > 256 for value in query.values()):
            raise PublicRequestError('Invalid checkpoint experiment selection.')
        if query.get('export') not in (None, '1') or query.get('include_context') not in (None, '1'):
            raise PublicRequestError('Invalid checkpoint experiment view.')
        identity, revision = query.get('id'), query.get('revision')
        exporting = query.get('export') == '1'
        if bool(identity) != bool(revision) or exporting and not identity:
            raise PublicRequestError('A captured game ID and revision are required.')
        if revision and (len(revision) != 64 or any(char not in '0123456789abcdef' for char in revision)):
            raise PublicRequestError('Invalid captured game revision.')
        try:
            limit, offset = int(query.get('limit', 50)), int(query.get('offset', 0))
            if not 1 <= limit <= 100 or not 0 <= offset <= 2147483647:
                raise ValueError()
        except ValueError:
            raise PublicRequestError('Invalid checkpoint experiment page.') from None
        if identity and any(key in query for key in ('include_context', 'limit', 'offset')):
            raise PublicRequestError('Context filtering applies to the game list.')

        def work():
            from app.research import experiment as owner
            with connect() as db:
                db.execute("SET statement_timeout='10s'")
                # Detail/export own their repeatable-read boundary. Nesting
                # them would make PostgreSQL reject SET TRANSACTION in a savepoint.
                if exporting:
                    return encoded(owner.export_game(db, identity, revision=revision))
                if identity:
                    return owner.detail(db, identity, revision=revision)
                with db.transaction():
                    db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    return owner.catalog(db, include_context=query.get('include_context') == '1', limit=limit, offset=offset)

        try:
            async with admission():
                value = await joined(work)
        except ValueError as exc:
            if str(exc) == 'experiment_revision_changed':
                return web.json_response(dict(error='Checkpoint evidence changed; refresh comparisons before opening this game.',
                    refresh_required=True, provider_requests=0), status=409, headers=HEADERS)
            if str(exc) in ('experiment_game_unknown', 'experiment_unknown_game'):
                raise PublicRequestError('Unknown tracked experiment game.') from None
            raise
        if exporting:
            return web.Response(body=value, content_type='application/json', headers={**HEADERS,
                'Content-Disposition': 'attachment; filename="predict-early-late-game.json"'})
        from .pipeline import serial
        return web.json_response(serial(value), headers=HEADERS)

    app.router.add_get('/api/research/games', games)
    app.router.add_get('/api/research/game', game)
    app.router.add_get('/api/research/catalog', page)
    app.router.add_get('/api/research/input', detail)
    app.router.add_get('/api/research/export', export)
    app.router.add_delete('/api/research/read', release)
    app.router.add_get('/api/research/coverage', coverage)
    app.router.add_get('/api/research/cohorts', cohorts)
    app.router.add_get('/api/research/experiment', experiment)
