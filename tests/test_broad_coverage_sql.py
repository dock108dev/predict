"""Full authored ingress matrix to ordinary retained Coverage in disposable SQL."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.collection.current_native import NativeWorker
from app.collection.runtime_client import RuntimeClient
from app.dashboard.comparison_board_api import mount
from app.storage.coverage_latest import read, reconcile
from app.storage.current_rows import CurrentRowStore
from app.storage.store import stamp
from tests import test_latest_board_sql as sql_fixtures
from tests import test_multisport_pipeline_sql as pipeline_fixtures
from tests.multisport_fixtures import SPORTS, FAMILIES, source_case, fake_discovery, current_book


@skipUnless(sql_fixtures.SOCKET,'Explicit disposable broad-coverage PostgreSQL lane required')
class BroadCoverageSQL(IsolatedAsyncioTestCase):
    connect=classmethod(sql_fixtures.LatestBoardSQL.connect.__func__)
    setUpClass=classmethod(sql_fixtures.LatestBoardSQL.setUpClass.__func__)
    tearDownClass=classmethod(sql_fixtures.LatestBoardSQL.tearDownClass.__func__)
    async def asyncSetUp(self):
        await pipeline_fixtures.AutomaticMultisportSQL.asyncSetUp(self)
        # Use the inline worker with this fixture's patched SQL connector.
        # A child interpreter cannot inherit the class-specific database patch.
        from app.collection.coverage_worker import MAX_PROCESS_BYTES
        self.service.config['rss_bytes']=MAX_PROCESS_BYTES
        await self.owner.close()
        self.enterContext(patch('app.collection.current_policy.load',return_value=self.config))
        with self.connect() as db:
            db.execute('TRUNCATE comparison_publication')
            db.execute("INSERT INTO comparison_publication(kind,id,generation,facts) VALUES('live','',0,'{}')")

    async def test_complete_component_partitions_match_whole_snapshot_counts(self):
        from app.storage import coverage_partitions
        await self.matrix()
        await self.owner.close()
        original=coverage_partitions.partitions
        with self.connect() as db:
            with patch.object(coverage_partitions,'partitions',side_effect=lambda db, **kw:original(db,maximum_offers=32768,**kw)):
                self.assertTrue(reconcile(db)['published'])
                whole=db.execute("SELECT facts FROM comparison_publication WHERE kind='coverage'").fetchone()['facts']
            with patch.object(coverage_partitions,'partitions',side_effect=lambda db, **kw:original(db,maximum_offers=1,**kw)):
                self.assertTrue(reconcile(db)['published'])
                divided=db.execute("SELECT facts FROM comparison_publication WHERE kind='coverage'").fetchone()['facts']
        self.assertGreater(divided['work_metrics']['partitions'],1)
        self.assertEqual(whole['global_totals'],divided['global_totals'])
        def counts(value):
            return {c['id']:(c['counts'],{r['code']:(r['count'],r['primary_count']) for r in c['reasons']}) for c in value['cells']}
        self.assertEqual(counts(whole),counts(divided))

    async def test_capture_plan_avoids_jit_without_changing_session_policy(self):
        from app.storage import coverage_latest
        await self.owner.close()
        original_totals=coverage_latest._stream_capture_totals
        plans=[]
        with self.connect() as db:
            db.execute('SET jit=on')
            db.execute('SET jit_above_cost=0')
            def planned_capture(connection,*args):
                plan=db.execute('EXPLAIN (FORMAT JSON) '+coverage_latest._OFFER_SQL,args).fetchone()['QUERY PLAN'][0]
                plans.append(('JIT' in plan,db.execute('SHOW jit').fetchone()['jit']))
                return original_totals(connection,*args)
            with patch.object(coverage_latest,'_stream_capture_totals',side_effect=planned_capture):
                result=reconcile(db)
            self.assertTrue(result['published'])
            self.assertTrue(plans)
            self.assertTrue(all(plan == (False,'off') for plan in plans))
            self.assertEqual(db.execute('SHOW jit').fetchone()['jit'],'on')
            # The same connection still permits compilation outside the capture.
            outside=db.execute('EXPLAIN (FORMAT JSON) SELECT sum(n) FROM generate_series(1,1000) AS x(n)').fetchone()['QUERY PLAN'][0]
            available=db.execute('SELECT pg_jit_available() AS available').fetchone()['available']
            self.assertEqual('JIT' in outside,available)

    async def test_shutdown_during_real_capture_first_fetch(self):
        from threading import Event
        from app.storage import coverage_latest
        from app.storage.latest_board import LatestBoardOwner
        await self.owner.close()
        owner=LatestBoardOwner(self.service)
        self.addAsyncCleanup(owner.close)
        fetching=Event()
        fetch=coverage_latest._stream_capture_totals
        def first_fetch(db,*args):
            fetching.set()
            return fetch(db,*args)
        with patch.object(coverage_latest,'_stream_capture_totals',first_fetch):
            owner.coverage_task=asyncio.create_task(owner.run_coverage())
            async with asyncio.timeout(5):
                while not fetching.is_set():await asyncio.sleep(.01)
            # Let the real query enter execution, including compilation when
            # enabled. Fast captures may already finish before Stop arrives.
            await asyncio.sleep(.25)
            await owner.close()
        self.assertTrue(owner.coverage_task.done())
        self.assertEqual(owner.connections,set())
        from app.collection.background_work import BACKGROUND
        self.assertNotIn('coverage',BACKGROUND.active)

    async def matrix(self):
        # Runtime, observation, estimate and Coverage owners precede every event.
        self.service.status=lambda:dict(issues=[],exclusions=[],database=dict(state='available'),
            coverage=self.service.coverage.snapshot())
        cases=[];workers={v:NativeWorker(self.service,v) for v in ('kalshi','polymarket_us')}
        calls={v:fake_discovery(w,cases) for v,w in workers.items()}
        for worker in workers.values():
            self.addAsyncCleanup(worker.close)
            await worker.discover()
        token=uuid4().hex[:8]
        cases.extend(source_case(sport,family,token+sport+family,clock=datetime.now(timezone.utc))
            for sport in SPORTS for family in FAMILIES)
        for venue,worker in workers.items():
            await worker.discover()
            self.assertEqual(len(worker.markets),18,(venue,worker.findings))
            for case in cases:self.service.book(venue,current_book(case,venue,price='0.48' if venue=='kalshi' else '0.53'))
        self.state.write(self.service)
        from app.storage import ordinary_publication as live
        with self.connect() as db:
            for _ in range(5):
                result = live.turn(db)
                if result['remaining_components'] == 0:
                    break
            self.assertTrue(reconcile(db)['published'])
            value=read(db)
        self.assertEqual(value['global_totals']['retained_observations'],72,(self.owner.observation_error,self.owner.coverage_error))
        self.assertEqual(value['global_totals']['supported_comparison_observations'],60,
            (self.owner.observation_error,self.owner.coverage_error,[(c['id'],c['counts'],c['reasons']) for c in value['cells'] if c['counts']['retained_observations']]))
        return cases,calls,value

    async def client(self):
        app=web.Application();mount(app,RuntimeClient(connector=self.connect))
        client=TestClient(TestServer(app));await client.start_server();self.addAsyncCleanup(client.close)
        return client

    async def test_full_matrix_background_publication_api_and_zero_dispatch_reads(self):
        cases,calls,value=await self.matrix()
        self.assertEqual(value['global_totals']['underlying_pairs'],30)
        self.assertEqual(value['global_totals']['signed_comparison_directions'],60)
        self.assertEqual(value['global_totals']['displayed_comparison_directions'],60)
        self.assertEqual(value['global_totals']['displayed_current_comparison_directions'],60)
        self.assertEqual(value['global_totals']['matched_occurrences'],18)
        self.assertEqual(value['global_totals']['current_observations'],72)
        self.assertEqual(value['global_totals']['current_comparison_observations'],60)
        self.assertAlmostEqual(value['ratios']['supported_peer']['value'],60/72)
        self.assertEqual(len(cases),18)
        from app.dashboard.current_contract import stamp
        self.assertGreaterEqual(stamp(value['publication_at']),stamp(value['captured_at']))
        client=await self.client();before=deepcopy(calls)
        with patch('app.collection.current_native.NativeWorker.get',side_effect=AssertionError('provider from retained read')):
            response=await client.get('/api/coverage')
            self.assertEqual(response.status,200,await response.text())
            all_cells=await response.json()
            with self.connect() as db:
                self.assertEqual(all_cells['display_result_id'], db.execute(
                    "SELECT result_id FROM comparison_publication WHERE kind='live'").fetchone()['result_id'])
            for sport in SPORTS:
                response=await client.get('/api/coverage',params=dict(league=sport,venue='kalshi',market='total',period='full_game'))
                self.assertEqual(response.status,200,await response.text())
                scoped=await response.json()
                self.assertEqual(scoped['global_totals']['retained_observations'],72)
                self.assertEqual(scoped['filtered_totals']['retained_observations'],2)
                self.assertEqual(scoped['filtered_totals']['underlying_pairs'],2)
                self.assertEqual(scoped['filtered_totals']['displayed_comparison_directions'],2)
                self.assertEqual(scoped['filtered_totals']['displayed_current_comparison_directions'],2)
                self.assertEqual(scoped['provider_requests'],0)
                self.assertEqual(scoped['read_revision'],all_cells['read_revision'])
                self.assertTrue(scoped['cells'][0]['examples'])
        self.assertEqual(calls,before)
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) n FROM comparison_publication WHERE kind='coverage'").fetchone()['n'],1)
            original=CurrentRowStore(db).capture(include_depth=False)['records']
            # A metric capture in a later clock window ages the original source
            # prices without rewriting any source facts or manufacturing refresh.
            await self.owner.close()
            later=(datetime.now(timezone.utc)+timedelta(minutes=16)).isoformat()
            # An expired runtime heartbeat is a distinct material publication
            # revocation, not merely source-clock aging. Keep that fail-closed
            # behavior before isolating the original-price age transition.
            reconcile(db,at=later)
            withdrawn=read(db,at=later)
            self.assertEqual(withdrawn['global_totals']['displayed_current_comparison_directions'],0)
            self.assertEqual(withdrawn['global_totals']['current_observations'],0)
            self.assertEqual(original,CurrentRowStore(db).capture(include_depth=False)['records'])
            # This authored owner heartbeat renews no native quote/receipt clock.
            with patch('app.collection.runtime_status.clock',return_value=stamp(later)):
                self.state.write(self.service)
            reconcile(db,at=later)
            aged=read(db,at=later)
            after=CurrentRowStore(db).capture(include_depth=False)['records']
        self.assertEqual(original,after)
        self.assertEqual(aged['global_totals']['current_observations'],0)
        self.assertEqual(aged['global_totals']['last_known_observations'],72)
        self.assertEqual(aged['global_totals']['current_comparison_observations'],0)
        self.assertEqual(aged['global_totals']['displayed_comparison_directions'],60)
        self.assertEqual(aged['global_totals']['displayed_current_comparison_directions'],0)
        self.assertEqual(aged['global_totals']['supported_comparison_observations'],60)

    async def test_absent_publication_is_unmeasured_and_read_only(self):
        await self.owner.close()
        with self.connect() as db:
            db.execute("DELETE FROM comparison_publication WHERE kind='coverage'")
            pending=read(db)
            self.assertEqual(db.execute("SELECT count(*) n FROM comparison_publication WHERE kind='coverage'").fetchone()['n'],0)
        self.assertEqual(pending['publication_state'],'pending')
        self.assertIsNone(pending['captured_at'])
        self.assertIsNone(pending['global_totals']['retained_observations'])
        self.assertIsNone(pending['cells'][0]['counts']['retained_observations'])
        self.assertIsNone(pending['cells'][0]['ratios']['supported_peer']['value'])

    async def test_read_exposes_publication_failure_without_inventing_measurements(self):
        await self.owner.close()
        from app.collection.runtime_status import read_runtime
        with self.connect() as db:
            db.execute("DELETE FROM comparison_publication WHERE kind='coverage'")
            owner = read_runtime(db)
            owner['calculations'] = dict(coverage='unavailable', coverage_error='background_coverage_unavailable')
            with patch('app.collection.runtime_status.read_runtime', return_value=owner):
                value = read(db)
        self.assertEqual(value['publication_error'], 'background_coverage_unavailable')
        self.assertEqual(value['publication_worker_state'], 'unavailable')
        self.assertEqual(value['publication_state'], 'pending')
        self.assertIsNone(value['global_totals']['retained_observations'])
        self.assertEqual(value['provider_requests'], 0)

    async def test_changed_source_input_waits_for_publication_with_exact_original(self):
        cases,calls,value=await self.matrix()
        await self.owner.close()
        with self.connect() as db:
            records=CurrentRowStore(db).capture(include_depth=False)['records']
            selected=deepcopy(next(r for r in records if r['event']['competition']=='NBA' and
                r['quote']['venue']=='kalshi' and r['market_identity']['family']=='total'))
            selected['quote']['original']['value']='0.4900'
            new_clock=datetime.now(timezone.utc)+timedelta(seconds=1)
            selected['quote']['times'].update(source_at=new_clock.isoformat(),received_at=new_clock.isoformat())
            CurrentRowStore(db).upsert_records([selected],now=new_clock.isoformat())
            reconcile(db,at=new_clock.isoformat())
            changed=read(db,at=new_clock.isoformat())
        cell=next(c for c in changed['cells'] if c['id']=='NBA|kalshi|total|full_game')
        reasons={r['code']:r for r in cell['reasons']}
        self.assertGreaterEqual(reasons['waiting_for_publication']['count'],1)
        example=next(e for e in reasons['waiting_for_publication']['examples'] if e['original']['value']=='0.4900')
        self.assertEqual(example['times']['source_at'],new_clock.isoformat())
        self.assertEqual(changed['global_totals']['retained_observations'],72)
        self.assertGreater(changed['global_totals']['supported_comparison_observations'],0)
        self.assertEqual(changed['provider_requests'],0)

    async def test_coverage_refuses_over_capacity_and_keeps_last_cohort(self):
        from app.storage import coverage_latest

        await self.matrix()
        with self.connect() as db:
            prior=db.execute("SELECT revision FROM comparison_publication WHERE kind='coverage'").fetchone()
            with patch.object(coverage_latest,'MAX_CAPTURE_BYTES',1):
                with self.assertRaisesRegex(ValueError,'coverage_capture_capacity'):
                    reconcile(db)
            self.assertEqual(db.execute("SELECT revision FROM comparison_publication WHERE kind='coverage'").fetchone(),prior)

    async def test_head_membership_controls_display_cohort(self):
        _, _, baseline = await self.matrix()
        with self.connect() as db:
            head = db.execute("SELECT result_id FROM comparison_publication WHERE kind='live'").fetchone()['result_id']
            db.execute("DELETE FROM comparison_result_reference WHERE kind='member' AND (holder,result_id) IN "
                       "(SELECT holder,result_id FROM comparison_result_reference WHERE kind='member' AND holder=%s ORDER BY result_id LIMIT 1)", (head,))
            self.assertTrue(reconcile(db)['published'])
            value = read(db)
        self.assertEqual(value['global_totals']['retained_observations'],72)
        self.assertLess(value['global_totals']['displayed_observations'], baseline['global_totals']['displayed_observations'])
        self.assertGreater(value['global_totals']['displayed_observations'],0)
        self.assertGreater(value['global_totals']['pending_observations'],0)

    async def test_raw_result_reads_the_published_member_and_its_own_clocks(self):
        from app.storage import ordinary_evidence, raw_calculations

        await self.matrix()
        with self.connect() as db, db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            index = ordinary_evidence.members(db)
            pairs = ((entry, row) for group in index.values() for entry in group
                     for row in ordinary_evidence.read_member(db, entry)['rows']
                     if row['venue'] == 'polymarket_us' and row['source'].get('quote_side') == 'buy'
                     and row['original'].get('transformation') != 'one_minus_native_bid')
            entry, row = next(pairs)
            source = row['source']
            book = dict(provider=source['provider'],venue=row['venue'], event_id=source['native_event_id'],
                        market_id=source['native_market_id'],revision='selected-raw-image')
            observation = dict(outcome_id=source['native_outcome_id'],side='asks',
                               native_side=source['native_side'])
            result = raw_calculations.read(db, book, observation)
            self.assertGreater(result['total'], 0)
            selected = next(r for r in result['results'] if r['view'] == 'ev')
            self.assertEqual(selected['result_id'], entry['member_id'])
            self.assertEqual(selected['captured_inputs'][0]['times'], row['times'])
            self.assertEqual(selected['captured_inputs'][0]['original'], row['original'])
            self.assertFalse(selected['current_eligibility'])
