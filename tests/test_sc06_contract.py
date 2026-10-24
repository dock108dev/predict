"""Independent summary HTTP and publication-seam checks; no SQL/providers."""
import asyncio
from contextlib import ExitStack, nullcontext
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from threading import Event
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.comparison.scanner_projection import Projection
from app.comparison.scanner_summaries import SummaryWorker, SummaryStore, observation
from app.dashboard.scanner_api import Scanner, mount
from tests.test_sc02_projection import frame, fake
from tests.test_ev09_n01 import AT
from tests.test_sc06_summaries import clock, fact, snapshot

ROOT = Path(__file__).resolve().parents[1]


class Publications(TestCase):
    def test_summary_observes_unfiltered_publication_without_read_polling(self):
        with tempfile.TemporaryDirectory(prefix='predict-sc06-seam-') as folder:
            worker = SummaryWorker(Path(folder) / 'episodes.sc06')
            self.addCleanup(worker.close)
            p = Projection(clock=lambda: AT, evaluator=fake)
            p.summary_observer = worker.offer
            f, x = frame(3)
            p.ingest(f, x)
            while p.pending:
                p.drain()
            self.assertTrue(worker.flush())
            result = worker.read(at=AT)
            self.assertEqual(result['counts']['observed_episodes'], 3)
            self.assertEqual(result['counts']['left_censored'], 3)
            before = (p.evaluations, p.publication, len(worker.store.records))
            for _ in range(20):
                p.view(limit=1)
                worker.read(at=AT)
            self.assertEqual(before, (p.evaluations, p.publication, len(worker.store.records)))
            detached = observation(p, 'evaluated')
            original = deepcopy(detached)
            next(iter(p.rows.values()))['metric']['value'] = '999'
            self.assertEqual(detached, original)
            self.assertNotIn('inputs', detached)
            self.assertNotIn('profiles', detached)
            self.assertNotIn('allocation', detached['rows'][0])
            p.stop()
            self.assertTrue(worker.flush())
            self.assertEqual(worker.read(at=AT)['state'], 'stopped')


class RunnerBoundaries(TestCase):
    """A source-unchanged tick must still revisit temporal authority."""
    def worker(self):
        self.now = 0
        provider = SimpleNamespace(closed=False, closing=False, dispatch=True)
        with patch('app.comparison.scanner_summaries.SummaryWorker'):
            worker = Scanner(provider, clock=lambda: clock(self.now))
        worker.projection = Mock(stopped=False, lock=nullcontext(), generation=1,
                                 capture_revision='authored-revision', pending={})
        worker._probe = Mock(return_value=('unchanged-source', 'authored-policy'))
        return worker

    def capture(self, boundary):
        return (dict(instruments=[dict(expires_at=clock(20))]), {},
                dict(current_rows_revision='authored-revision', revalidate_at=clock(boundary)), 1)

    def test_unchanged_source_recaptures_at_inactive_registry_boundary(self):
        worker = self.worker()
        worker._capture = Mock(side_effect=[self.capture(5), self.capture(10)])
        worker.once()
        self.assertEqual(worker.deadline, clock(5))
        self.now = 4
        worker.once()
        self.assertEqual(worker._capture.call_count, 1)
        self.now = 5
        worker.once()
        self.assertEqual(worker._capture.call_count, 2)
        self.assertEqual(worker.deadline, clock(10))
        self.assertEqual(worker.projection.ingest.call_count, 2)

    def test_reconciled_capture_updates_temporal_deadline_before_publication(self):
        worker = self.worker()
        worker._probe.side_effect = [('first', 'policy'), ('changed', 'policy'), ('changed', 'policy')]
        worker._capture = Mock(side_effect=[self.capture(10), self.capture(3)])
        worker.once()
        self.assertEqual(worker._capture.call_count, 2)
        self.assertEqual(worker.deadline, clock(3))
        self.assertIsNone(worker.marker)
        worker.projection.publish.assert_not_called()


class ContinuationProof(TestCase):
    """Skip redundant work only between fresh, post-drain authority proofs."""
    def setUp(self):
        self.now = AT
        self.provider = SimpleNamespace(closed=False, closing=False, dispatch=True)
        with patch('app.comparison.scanner_summaries.SummaryWorker'):
            self.worker = Scanner(self.provider, clock=lambda: self.now)
        self.projection = self.worker.projection
        self.projection.evaluator = fake
        self.frame, self.inputs = frame(64)
        self.worker._capture = Mock(side_effect=lambda: (deepcopy(self.frame), deepcopy(self.inputs),
            dict(current_rows_revision='authored-current-row-revision'), 1))
        self.worker._probe = Mock(return_value=('verified-marker', self.projection.policy))

    def test_pending_continuations_skip_preprobe_but_require_each_fresh_postprobe(self):
        self.worker.once()
        self.assertEqual(self.worker._probe.call_count, 2)
        self.assertTrue(self.projection.pending)
        for expected_calls in (3, 4):
            self.worker.once()
            self.assertEqual(self.worker._probe.call_count, expected_calls)
        self.assertEqual(self.worker._capture.call_count, 1)
        self.assertGreater(self.projection.evaluations, 0)

    def test_unannounced_current_authority_change_reconciles_before_new_publication(self):
        self.worker.once()
        self.assertTrue(self.projection.rows)
        self.frame['input_revision'] = 'new-current-input'
        self.frame['revision'] = 'new-current-readiness'
        for value in self.inputs.values():
            value['quote']['original']['value'] = '0'
        self.worker._probe.return_value = ('unannounced-sql-registry-status-or-authority-change', self.projection.policy)
        with patch.object(self.projection, 'publish', wraps=self.projection.publish) as publish:
            self.worker.once()
            publish.assert_not_called()
        self.assertEqual(self.worker._capture.call_count, 2)
        self.assertEqual(self.projection.rows, {})
        self.assertEqual(self.projection.receipts, {})
        self.assertIsNone(self.worker.continuation)

    def test_postprobe_failure_cannot_publish_and_retry_requires_fresh_preprobe(self):
        self.worker.once()
        before = deepcopy(self.projection.rows)
        self.worker._probe.side_effect = RuntimeError('authored current proof failure')
        with patch.object(self.projection, 'publish', wraps=self.projection.publish) as publish:
            with self.assertRaisesRegex(RuntimeError, 'current proof failure'):
                self.worker.once()
            publish.assert_not_called()
        self.assertEqual(self.projection.rows, before)
        self.assertIsNone(self.worker.continuation)
        self.worker._probe.side_effect = None
        self.worker._probe.reset_mock()
        self.worker.once()
        self.assertEqual(self.worker._probe.call_count, 2)

    def test_deadline_generation_and_capture_revision_invalidate_continuation(self):
        self.worker.once()
        for mutation in ('deadline', 'generation', 'capture_revision'):
            with self.subTest(mutation=mutation):
                self.assertTrue(self.projection.pending)
                if mutation == 'deadline':self.worker.deadline = self.now
                elif mutation == 'generation':self.projection.generation += 1
                else:self.projection.capture_revision = 'externally-replaced-capture'
                self.worker._probe.reset_mock()
                self.worker.once()
                self.assertEqual(self.worker._probe.call_count, 2)

    def test_stop_consumes_no_more_finance_and_cannot_republish_pending_rows(self):
        self.worker.once()
        before = self.projection.evaluations
        self.provider.dispatch = False
        self.worker._probe.reset_mock()
        self.worker.once()
        self.worker._probe.assert_not_called()
        self.assertEqual(self.projection.evaluations, before)
        self.assertTrue(self.projection.stopped)
        self.assertEqual(self.projection.rows, {})
        self.assertIsNone(self.worker.continuation)

    def test_stop_during_last_evaluation_withdraws_without_publication(self):
        from app.comparison.scanner_projection import MAX_WORK_PER_TURN
        calls = 0
        def stops_on_last(*args, **kwargs):
            nonlocal calls
            calls += 1
            value = fake(*args, **kwargs)
            if calls == MAX_WORK_PER_TURN:self.provider.dispatch = False
            return value
        self.projection.evaluator = stops_on_last
        with patch.object(self.projection, 'publish', wraps=self.projection.publish) as publish:
            self.worker.once()
            publish.assert_not_called()
        self.assertEqual(calls, MAX_WORK_PER_TURN)
        self.assertTrue(self.projection.stopped)
        self.assertEqual(self.projection.rows, {})
        self.assertEqual(self.projection.receipts, {})
        self.assertIsNone(self.worker.continuation)

    def test_stop_during_postproof_withdraws_without_publication(self):
        probes = 0
        def stops_on_post():
            nonlocal probes
            probes += 1
            if probes == 2:self.provider.dispatch = False
            return 'verified-marker', self.projection.policy
        self.worker._probe.side_effect = stops_on_post
        with patch.object(self.projection, 'publish', wraps=self.projection.publish) as publish:
            self.worker.once()
            publish.assert_not_called()
        self.assertEqual(probes, 2)
        self.assertTrue(self.projection.stopped)
        self.assertEqual(self.projection.rows, {})
        self.assertEqual(self.projection.receipts, {})
        self.assertIsNone(self.worker.continuation)

    def test_idle_fresh_unchanged_probe_preserves_publication_and_original_receipts(self):
        while self.projection.pending or self.worker.marker is None:self.worker.once()
        before=(self.projection.publication,deepcopy(self.projection.rows),deepcopy(self.projection.receipts))
        self.worker._probe.reset_mock()
        with patch.object(self.projection,'drain',wraps=self.projection.drain) as drain, \
                patch.object(self.projection,'publish',wraps=self.projection.publish) as publish, \
                patch.object(self.projection,'expire',wraps=self.projection.expire) as expire:
            self.worker.once()
            drain.assert_not_called();publish.assert_not_called();expire.assert_called_once()
        self.assertEqual(self.worker._probe.call_count,1)
        self.assertEqual((self.projection.publication,self.projection.rows,self.projection.receipts),before)

    def test_stop_during_preproof_cannot_capture_drain_or_publish(self):
        self.worker.once()
        self.worker.continuation=None
        def stops_in_preproof():
            self.provider.dispatch=False
            return 'verified-marker',self.projection.policy
        self.worker._probe.side_effect=stops_in_preproof
        self.worker._capture.reset_mock()
        with patch.object(self.projection,'drain',wraps=self.projection.drain) as drain, \
                patch.object(self.projection,'publish',wraps=self.projection.publish) as publish:
            self.worker.once()
            drain.assert_not_called();publish.assert_not_called()
        self.worker._capture.assert_not_called()
        self.assertTrue(self.projection.stopped)
        self.assertEqual(self.projection.rows,{})
        self.assertEqual(self.projection.receipts,{})
        self.assertIsNone(self.worker.continuation)

    def test_stop_during_initial_or_reconciled_capture_cannot_ingest(self):
        for reconciled in (False, True):
            with self.subTest(reconciled=reconciled):
                if reconciled:
                    self.setUp()
                    self.worker.once()
                    self.assertTrue(self.projection.rows)
                    self.worker._probe.return_value = ('changed-authority', self.projection.policy)
                def stops_during_capture():
                    self.provider.dispatch = False
                    return deepcopy(self.frame), deepcopy(self.inputs), dict(current_rows_revision='authored-revision'), 1
                self.worker._capture.side_effect = stops_during_capture
                with patch.object(self.projection, 'ingest', wraps=self.projection.ingest) as ingest:
                    self.worker.once()
                    ingest.assert_not_called()
                self.assertTrue(self.projection.stopped)
                self.assertEqual(self.projection.rows, {})
                self.assertEqual(self.projection.receipts, {})
                self.assertIsNone(self.worker.continuation)


class ReadinessUniverseBounds(TestCase):
    """Selected captures share the ordinary full executable-universe bound."""
    def groups(self, count, *, venue='kalshi'):
        return [[dict(event=dict(scheduled_start=clock(20)), quote=dict(venue=venue,
            source=dict(provider=venue, native_event_id=f'authored-{index}', native_market_id=f'market-{index}'),
            times=dict(source_at=clock(), received_at=clock())))] for index in range(count)]

    def capture(self, groups, *, members=None, selection=None):
        from app.collection.current_policy import DEFAULT, GRANT
        from app.storage import scanner_readiness
        class Database:
            def transaction(self):return nullcontext()
            def execute(self, statement, args=()):return SimpleNamespace(fetchall=lambda: [])
        context = SimpleNamespace(prepared=dict(groups=groups), engine='authored-engine', epoch='authored-epoch')
        frame = dict(records=[], epoch='authored-epoch', revision='authored-revision', source_status={})
        prepared = dict(instruments=[], failures=[], references={}, financial_inputs={}, input_bytes=0)
        with ExitStack() as stack:
            stack.enter_context(patch('app.storage.scanner_publication.current_revision',return_value=dict(epoch='authored',current_rows_revision='authored')))
            stack.enter_context(patch('app.storage.latest_board.capture_batches',return_value=[['authored-event']]))
            stack.enter_context(patch.object(scanner_readiness, 'ReadContext', return_value=context))
            stack.enter_context(patch.object(scanner_readiness.CurrentRowStore, 'capture', return_value=frame))
            stack.enter_context(patch('app.storage.scanner_preparation.PreparationCache.registry', return_value=('authored-registry', None)))
            producer = stack.enter_context(patch.object(scanner_readiness, '_prepare_group', return_value=prepared))
            models = stack.enter_context(patch.object(scanner_readiness, 'instrument', side_effect=AssertionError('admission invoked model owner')))
            try:
                value = scanner_readiness.capture(Database(), config=DEFAULT, authority=GRANT,
                    at=clock(), members=members, selection=selection)
            finally:
                self.producer_calls = producer.call_count
                models.assert_not_called()
        return value

    def test_501_executable_groups_fail_before_preparation_even_for_selected_members(self):
        groups = self.groups(501)
        for members in (None, (('kalshi', 'authored-0'),)):
            with self.subTest(members=members), self.assertRaisesRegex(ValueError, '^board_catalog_capacity$'):
                self.capture(groups, members=members)
            self.assertEqual(self.producer_calls, 0)

    def test_exact500_plus_reference_only_groups_retain_original_admission(self):
        result = self.capture(self.groups(500) + self.groups(4, venue='pinnacle'))
        self.assertEqual(self.producer_calls, 500)
        self.assertEqual(result[0]['provider_requests'], 0)

    def test_unsupported_scope_still_enforces_complete_catalog_bound(self):
        from app.comparison.scanner_readiness import Selection
        with self.assertRaisesRegex(ValueError, '^board_catalog_capacity$'):
            self.capture(self.groups(501), selection=Selection(markets=('total',)))
        self.assertEqual(self.producer_calls, 0)


class AuthoredOriginals(TestCase):
    def test_varied_authored_originals_match_native_identity_and_depth(self):
        from tests.sc06_fixture import records
        values = records(3, at=clock())
        self.assertEqual(len(values), 6)
        for row in values:
            original = row['quote']['original']
            self.assertEqual(original['transformation'], 'identity')
            self.assertEqual(original['native_value'], original['value'])
            self.assertEqual(original['native_units'], original['units'])
            self.assertEqual(row['quote']['depth'][0]['price'], original['value'])


class TemporalEconomics(TestCase):
    def test_scheduled_fee_activates_exactly_without_renewing_originals(self):
        from datetime import timedelta
        from fractions import Fraction
        from app.comparison.current_dependencies import digest
        from app.comparison.estimated_consumer import consume
        from app.comparison.readiness_inputs import instrument
        from app.comparison.scanner_finance import dependencies
        from app.comparison.estimated_policy import DEFAULT_POLICY
        from tests.test_ev04_content import AT as fee_at, case, value

        boundary = fee_at + timedelta(seconds=5)
        q, _, _, _ = case('kalshi')
        metadata = dict(balance_precision='0.01', series_id='authored-schedule',
            kalshi_metadata=dict(source='authored:sc06-scheduled-fee', series_id='authored-schedule',
                event_id=q['source']['native_event_id'], event_history_complete=True,
                series_changes=[dict(scheduled_ts=fee_at.isoformat(), fee_type='quadratic', fee_multiplier='1'),
                    dict(scheduled_ts=boundary.isoformat(), fee_type='quadratic', fee_multiplier='2')],
                event_changes=[]))
        q, profiles, context, _ = case('kalshi', metadata=metadata)
        before_inputs = deepcopy((q, profiles))
        book = dict(source_at=q['times']['source_at'], received_at=q['times']['received_at'],
            sync='synchronized', state='active', quantity_unit='contracts')
        event = dict(context['event'], stage='regular_season')
        rows = [instrument(q, profiles, event, context['group'], at=at.isoformat(),
            source_status=dict(state='available'), authorized=True, book=book)
            for at in (fee_at, boundary - timedelta(microseconds=1), boundary)]
        detached = dict(quote=q, profiles=profiles, event=event, group=context['group'])
        pair = dict(legs=['authored-selected'])
        revisions = [dependencies(pair, {'authored-selected': row}, {'authored-selected': detached},
            DEFAULT_POLICY, 'authored-engine') for row in rows]
        self.assertEqual(revisions[0], revisions[1])
        self.assertNotEqual(revisions[1], revisions[2])
        self.assertEqual(rows[0]['clocks'], rows[2]['clocks'])
        fees = [Fraction(value(consume(q, profiles, at=at, native_quantity='100'), 'fee', 'net_entry_fee_usd'))
            for at in (fee_at, boundary - timedelta(microseconds=1), boundary)]
        self.assertEqual(fees, [Fraction('1.75'), Fraction('1.75'), Fraction('3.5')])
        self.assertEqual(digest((q, profiles)), digest(before_inputs))


class HTTP(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='predict-sc06-http-')
        self.path = Path(self.folder.name) / 'episodes.sc06'
        self.worker = SummaryWorker(self.path)
        self.app = web.Application()
        self.provider = SimpleNamespace(closed=False, closing=False, dispatch=True)
        with patch('app.comparison.scanner_summaries.SummaryWorker', return_value=self.worker):
            self.scanner = mount(self.app, self.provider)
        self.scanner.clock = clock
        self.scanner.start = lambda: (_ for _ in ()).throw(AssertionError('summary read started scanner'))
        self.scanner._probe = lambda: (_ for _ in ()).throw(AssertionError('summary read probed SQL'))
        self.scanner._capture = lambda: (_ for _ in ()).throw(AssertionError('summary read captured inputs'))
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.worker.close()
        self.folder.cleanup()

    async def test_versioned_bounded_reads_filters_and_unknown_scope_do_no_work(self):
        self.worker.offer(snapshot([fact()]))
        self.assertTrue(self.worker.flush())
        count = len(self.worker.store.records)
        publication = self.scanner.projection.publication
        for query in ('', '?minimum_edge=20', '?category=conditional_hedge', '?leagues=NBA'):
            response = await self.client.get('/api/scanner/summaries' + query)
            value = await response.json()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(value['version'], 'predict-opportunity-summaries-1')
            self.assertEqual(value['provider_requests'], 0)
            self.assertEqual(value['financial_evaluations'], 0)
            self.assertLessEqual(len(await response.read()), value['bounds']['response_bytes'])
            if query == '?leagues=NBA':
                self.assertFalse(value['coverage']['complete'])
                self.assertIsNone(value['coverage']['checked_zero'])
        self.assertEqual(count, len(self.worker.store.records))
        self.assertEqual(publication, self.scanner.projection.publication)
        for query in ('limit=100', 'offset=1', 'amount=40', 'category=incorrect', 'minimum_size=-1', 'minimum_edge=NaN'):
            self.assertEqual((await self.client.get('/api/scanner/summaries?' + query)).status, 400)

    async def test_http_read_capacity_retains_one_outstanding_read(self):
        entered, release = Event(), Event()
        original = self.worker.read
        def paused(**kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('authored read was not released')
            return original(**kwargs)
        with patch.object(self.worker, 'read', paused):
            pending = asyncio.create_task(self.client.get('/api/scanner/summaries'))
            self.assertTrue(await asyncio.to_thread(entered.wait, 5))
            try:
                blocked = await self.client.get('/api/scanner/summaries')
                self.assertEqual(blocked.status, 503)
                self.assertEqual((await blocked.json())['error'], 'summary_read_capacity')
            finally:
                release.set()
            self.assertEqual((await pending).status, 200)


class ShippedContract(TestCase):
    def test_schema_examples_and_runtime_response_field_inventory(self):
        schema_path = ROOT / 'docs/contracts/predict-opportunity-summaries-1.schema.json'
        schema = json.loads(schema_path.read_text())
        examples = ROOT / 'docs/examples/opportunity-summaries-1'
        files = sorted(examples.glob('*.json'))
        self.assertGreaterEqual(len(files), 4)
        for path in files:
            value = json.loads(path.read_text())
            self.assertEqual(set(value), set(schema['required']), path.name)
            self.assertEqual(value['version'], 'predict-opportunity-summaries-1')
            self.assertEqual(value['provider_requests'], 0)
            self.assertEqual(value['financial_evaluations'], 0)
            self.assertLessEqual(len(json.dumps(value).encode()), value['bounds']['response_bytes'])
        with tempfile.TemporaryDirectory(prefix='predict-sc06-shape-') as folder:
            store = SummaryStore(Path(folder) / 'episodes.sc06')
            self.addCleanup(store.close)
            store.observe(snapshot([fact()]))
            self.assertEqual(set(store.read(at=clock())), set(schema['required']))
