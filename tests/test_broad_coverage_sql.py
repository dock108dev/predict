"""Full authored ingress matrix to ordinary retained Coverage in disposable SQL."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
import tracemalloc
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
        with self.connect() as db:db.execute('TRUNCATE coverage_latest')

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
        for _ in range(150):
            with self.connect() as db:value=read(db)
            if value['global_totals']['supported_comparison_observations']==60:break
            await asyncio.sleep(.1)
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
            self.assertEqual(db.execute('SELECT count(*) n FROM coverage_latest').fetchone()['n'],1)
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
            self.assertEqual(withdrawn['global_totals']['supported_comparison_observations'],0)
            self.assertGreater(withdrawn['global_totals']['pending_observations'],0)
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
            db.execute('TRUNCATE coverage_latest')
            pending=read(db)
            self.assertEqual(db.execute('SELECT count(*) n FROM coverage_latest').fetchone()['n'],0)
        self.assertEqual(pending['publication_state'],'pending')
        self.assertIsNone(pending['captured_at'])
        self.assertIsNone(pending['global_totals']['retained_observations'])
        self.assertIsNone(pending['cells'][0]['counts']['retained_observations'])
        self.assertIsNone(pending['cells'][0]['ratios']['supported_peer']['value'])

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

    async def test_compact_capture_preserves_dependencies_and_bounds_unused_publication_prose(self):
        from app.storage.coverage_latest import _publication_frame,_capture_size
        from app.storage import observation_publication as publication
        from app.storage.latest_board import source_states
        from app.collection.runtime_status import read_runtime
        from app.comparison.broad_coverage import native_key
        await self.matrix()
        await self.owner.close()
        with self.connect() as db:
            runtime=read_runtime(db)
            committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
            states=source_states(committed,runtime)
            compact,projected=_publication_frame(db,states)
            complete=publication.capture(db,states)
            for row in db.execute("SELECT facts->'publication_dependencies' d FROM latest_board").fetchall():
                self.assertEqual(publication.reasons(compact,row['d']),publication.reasons(complete,row['d']))
            originals={native_key(r['quote']):r for r in CurrentRowStore(db).capture(include_depth=False)['records']}
            self.assertEqual(len(projected),len(originals))
            for record in projected:
                before=originals[native_key(record['quote'])]
                self.assertEqual(record['quote']['original'],before['quote']['original'])
                self.assertEqual(record['quote']['times'],before['quote']['times'])
                self.assertEqual(record['market_identity'],before['market_identity'])
                self.assertEqual(record['event']['scheduled_start'],before['event']['scheduled_start'])
            # A large unused wording pool is a valid bounded compact-board
            # decoration. Coverage must neither fetch nor copy this material.
            before_size=_capture_size(db)
            db.execute("""UPDATE latest_board SET facts=jsonb_set(facts,'{boards,odds,native_wordings}',
                COALESCE(facts#>'{boards,odds,native_wordings}','[]'::jsonb)||
                jsonb_build_array(repeat('unused-coverage-prose-',50000)),true)""")
            retained=db.execute('SELECT sum(octet_length(facts::text)) n FROM latest_board').fetchone()['n']
            self.assertGreater(retained,18*1024*1024)
            self.assertEqual(_capture_size(db),before_size)
            # Do not let the test's full-frame reference fixtures contribute to
            # the compact worker's allocation measurement.
            del compact,complete,projected,originals
            tracemalloc.start();started=time.monotonic()
            try:
                result=reconcile(db)
                _,peak=tracemalloc.get_traced_memory()
            finally:tracemalloc.stop()
            self.assertTrue(result['published'],result)
            metrics=db.execute("SELECT facts->'work_metrics' m FROM coverage_latest").fetchone()['m']
            value=read(db)
        self.assertEqual(value['global_totals']['retained_observations'],72)
        self.assertEqual(value['global_totals']['supported_comparison_observations'],60)
        self.assertEqual(value['global_totals']['displayed_current_comparison_directions'],60)
        self.assertEqual(metrics['expanded_boards'],0)
        self.assertLess(peak,24*1024*1024)
        self.assertLess(metrics['projected_input_bytes'],2*1024*1024)
        self.assertNotIn('unused-coverage-prose-',json.dumps(value))
        report=os.environ.get('PREDICT_CI_REPORT_ROOT')
        if report:
            Path(report,'coverage-resource-sample.json').write_text(json.dumps(dict(
                retained_publication_bytes=int(retained),python_peak_allocated_bytes=peak,
                reconcile_seconds=time.monotonic()-started,**metrics),indent=2)+'\n')
