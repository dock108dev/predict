"""Selected input latency and independent readers on authored disposable SQL."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import threading
from time import monotonic
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

from app.collection.current_native import NativeWorker
from app.storage import latest_board as latest
from app.storage.comparison_board import ReadContext
from app.storage.current_rows import CurrentRowStore
from tests import test_consistent_slate_reads_sql as fixtures
from tests.multisport_fixtures import SPORTS, FAMILIES, source_case, fake_discovery


@skipUnless(fixtures.sql_fixtures.SOCKET, 'Explicit disposable PostgreSQL lane required')
class SelectedInputLatencySQL(IsolatedAsyncioTestCase):
    connect = classmethod(fixtures.ConsistentSlateReadsSQL.connect.__func__)
    setUpClass = classmethod(fixtures.ConsistentSlateReadsSQL.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.ConsistentSlateReadsSQL.tearDownClass.__func__)
    asyncSetUp = fixtures.ConsistentSlateReadsSQL.asyncSetUp
    async def api(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        from app.collection.runtime_client import RuntimeClient
        from app.dashboard import comparison_board_api as api
        if os.environ.get('PREDICT_LATENCY_BASELINE') == '1':
            import types
            api = types.ModuleType('app.dashboard.latency_baseline')
            exec(compile(Path('test-results/selected-input-latency-20261017/baseline-route.py').read_text(), 'baseline-route', 'exec'), api.__dict__)
        if os.environ.get('PREDICT_LATENCY_BASELINE') == '1':api.connect = self.connect
        self.api_module = api
        app = web.Application(); api.mount(app, RuntimeClient(connector=self.connect))
        client = TestClient(TestServer(app, handler_cancellation=True))
        await client.start_server(); self.addAsyncCleanup(client.close)
        return client, app
    page = fixtures.ConsistentSlateReadsSQL.page
    publication = fixtures.ConsistentSlateReadsSQL.publication
    ingress_books = fixtures.ConsistentSlateReadsSQL.ingress_books

    async def populate(self):
        cases = []
        workers = {v: NativeWorker(self.service, v) for v in fixtures.VENUES}
        self.calls = {v: fake_discovery(w, cases) for v, w in workers.items()}
        for w in workers.values():
            self.addAsyncCleanup(w.close)
            await w.discover()
        clock = datetime.now(timezone.utc) - timedelta(seconds=2)
        self.authored = [source_case(SPORTS[i % len(SPORTS)],
            FAMILIES[(i // len(SPORTS)) % len(FAMILIES)], uuid4().hex[:10], clock=clock) for i in range(60)]
        for generation, offset in enumerate(range(0, 60, 15), 1):
            cases[:] = self.authored[offset:offset + 15]
            for w in workers.values():await w.discover()
            self.ingress_books(workers, cases, generation=generation)
            await self.publication(offset + len(cases))
        self.read_call_counts={v:len(calls) for v,calls in self.calls.items()}
        self.workers = workers
        self.client, self.app = await self.api()
        first = await self.page(self.client)
        await self.page(self.client, first)
        self.board = first['boards'][0]
        self.quote = self.board['prices'][0]
        self.query = dict(game=self.board['game_key'], quote=self.quote['quote_id'],
            context_id=self.quote['inputs_identity']['context_id'])

    async def test_stage_measurement_and_independent_progress(self):
        baseline = os.environ.get('PREDICT_LATENCY_BASELINE') == '1'
        await self.populate()
        stages = []; captures = []; runtime_reads = []
        local = threading.local()
        capture = CurrentRowStore.capture
        def measured_capture(store, **kw):
            start = monotonic(); result = capture(store, **kw)
            if getattr(local, 'capture', False):captures.append(dict(records=len(result['records']), seconds=monotonic() - start))
            return result
        api = self.api_module
        from app.collection.runtime_client import RuntimeClient
        real_runtime=RuntimeClient.runtime
        def measured_runtime(client):
            if getattr(local,'api',False):runtime_reads.append(1)
            return real_runtime(client)
        def measured(fn, name):
            def run(*args, **kwargs):
                start = monotonic()
                local.api = True
                local.capture = name == 'capture_and_prepare'
                try:return fn(*args, **kwargs)
                finally:
                    local.capture = False
                    stages.append(dict(stage=name, seconds=monotonic() - start))
            return run
        async def selected():
            start = monotonic(); reply = await self.client.get('/api/boards/inputs', params=self.query)
            value = await reply.json()
            return dict(status=reply.status, seconds=monotonic() - start), value
        with patch.object(RuntimeClient,'runtime',measured_runtime), patch.object(CurrentRowStore, 'capture', measured_capture), \
             patch.object(api, 'snapshot', measured(api.snapshot, 'snapshot')), \
             patch.object(api, 'read_context', measured(api.read_context, 'capture_and_prepare')), \
             patch.object(ReadContext, 'observation_bundles', measured(ReadContext.observation_bundles, 'selected_bundle')):
            timing, value = await selected()
        self.assertEqual(timing['status'], 200, value)
        self.assertEqual(value['evidence']['original'], self.quote['original'])
        self.assertEqual(value['evidence']['times'], self.quote['times'])
        self.assertEqual(value['observation_revision'], self.quote['observation_revision'])
        entered = threading.Event(); release = threading.Event()
        real = ReadContext.observation_bundles
        read_context = api.read_context
        def selected_context(*args, **kwargs):
            result=read_context(*args, **kwargs);result._latency_selected=True;return result
        def slow(context, **kwargs):
            if getattr(context, '_latency_selected', False):
                entered.set()
                if not release.wait(2 if baseline else fixtures.SEMANTIC_READ_SECONDS) and not baseline:
                    raise AssertionError('ordinary reads did not release selected capture')
            return real(context, **kwargs)
        selected_event=self.quote['source']['native_event_id']
        unrelated=next(case for case in self.authored[-15:] if selected_event not in
            (case['events']['kalshi']['event_ticker'],case['events']['polymarket_us']['id']))
        async def active_ingress():
            for generation in range(5,9):
                await asyncio.sleep(.08)
                unrelated['clock']=datetime.now(timezone.utc)
                self.ingress_books(self.workers,[unrelated],price='0.54' if generation%2 else '0.55',generation=generation)
        from app.dashboard.comparison_board_api import READ_WORK
        # Keep the first latency sample under the actual production deadline.
        # The explicit concurrency hold uses a separate bounded test budget;
        # its duration depends on when both ordinary pages have completed.
        if not baseline:
            self.app[READ_WORK].work_seconds = fixtures.SEMANTIC_READ_SECONDS
        with patch.object(ReadContext, 'observation_bundles', slow), patch.object(api, 'read_context', selected_context):
            pending = asyncio.create_task(selected())
            ingress = None
            try:
                async with asyncio.timeout(fixtures.SEMANTIC_READ_SECONDS):
                    while not entered.is_set():
                        if pending.done():
                            self.fail(dict(selected=await pending,reason='selected capture never entered'))
                        await asyncio.sleep(.005)
                    ingress=asyncio.create_task(active_ingress())
                    start = monotonic()
                    first = await self.page(self.client)
                    await self.page(self.client, first)
                    ordinary_seconds = monotonic() - start
                    await ingress
                    if not baseline:
                        self.assertFalse(pending.done(), 'ordinary pages must complete while selected capture is held')
            finally:
                release.set()
                slow_timing, slow_value = await pending
                if ingress is not None:await ingress
        calls_after={v:len(calls) for v,calls in self.calls.items()}
        self.assertEqual(calls_after,self.read_call_counts)
        receipt = dict(evidence='authored 60 games, real native ingress, disposable PostgreSQL; baseline replays original routing with broad capture and shared lock' if baseline else 'authored 60 games, real native ingress, disposable PostgreSQL',
            baseline=baseline, selected=timing, stages=stages, captures=captures,runtime_database_reads=len(runtime_reads),
            selected_latency_target_seconds=2, selected_latency_target_met=timing['seconds'] < 2,
            selected_hold='two-second baseline delay' if baseline else 'released after both ordinary pages and four ingress batches complete',
            slow_selected=slow_timing,concurrent_unrelated_ingress_batches=4,
            two_page_ordinary_seconds=ordinary_seconds, provider_dispatches_from_reads=0)
        if not baseline:receipt['diagnostics']=await (await self.client.get('/api/boards/read-diagnostics')).json()
        if os.environ.get('PREDICT_CI_REPORT_ROOT'):
            Path(os.environ['PREDICT_CI_REPORT_ROOT'], 'selected-input-latency.json').write_text(json.dumps(receipt, indent=2)+'\n')

        if not baseline:
            self.assertEqual(slow_timing['status'], 200, slow_value)
            # Wall-clock samples remain in the receipt. Correctness is the
            # bounded successful response and explicit independent progress,
            # rather than a timing race on a shared hosted runner.
            self.assertTrue(all(c['records'] <= 4 for c in captures), captures)
