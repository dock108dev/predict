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

    async def test_capture_plan_avoids_jit_without_changing_session_policy(self):
        from app.storage import coverage_latest
        await self.owner.close()
        capture_sql=lambda: coverage_latest._PUBLICATION_SQL
        original_totals=coverage_latest._stream_capture_totals
        plans=[]
        with self.connect() as db:
            db.execute('SET jit=on')
            db.execute('SET jit_above_cost=0')
            def planned_capture(connection):
                query=capture_sql()
                plan=db.execute('EXPLAIN (FORMAT JSON) '+query).fetchone()['QUERY PLAN'][0]
                plans.append(('JIT' in plan,db.execute('SHOW jit').fetchone()['jit']))
                return original_totals(connection)
            with patch.object(coverage_latest,'_stream_capture_totals',side_effect=planned_capture):
                result=reconcile(db)
            self.assertTrue(result['published'])
            self.assertEqual(len(plans),1)
            self.assertEqual(plans[0],(False,'off'))
            self.assertEqual(db.execute('SHOW jit').fetchone()['jit'],'on')
            # The same connection still permits compilation outside the capture.
            outside=db.execute('EXPLAIN (FORMAT JSON) '+capture_sql()).fetchone()['QUERY PLAN'][0]
            available=db.execute('SELECT pg_jit_available() AS available').fetchone()['available']
            self.assertEqual('JIT' in outside,available)

    async def test_shutdown_during_real_capture_first_fetch(self):
        from threading import Event
        from psycopg import ServerCursor
        from app.storage.latest_board import LatestBoardOwner
        await self.owner.close()
        owner=LatestBoardOwner(self.service)
        self.addAsyncCleanup(owner.close)
        fetching=Event()
        fetch=ServerCursor.__next__
        def first_fetch(cursor):
            fetching.set()
            return fetch(cursor)
        with patch.object(ServerCursor,'__next__',first_fetch):
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

    async def test_read_exposes_publication_failure_without_inventing_measurements(self):
        await self.owner.close()
        from app.collection.runtime_status import read_runtime
        with self.connect() as db:
            db.execute('TRUNCATE coverage_latest')
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

    async def test_c2_capture_mixed_frozen_refs_and_duplicate_boards_fit_without_count_inflation(self):
        from app.storage.coverage_latest import _capture_size, _PUBLICATION_SQL, _PUBLICATION_CAPTURE_SQL, _publication_rows, _OFFER_SQL, _captured_offers
        from app.dashboard.comparison_board import expand_odds
        from psycopg.types.json import Jsonb
        cases,calls,baseline=await self.matrix()
        before_calls=deepcopy(calls)
        await self.owner.close()
        with self.connect() as db:
            rows=db.execute('SELECT * FROM latest_board ORDER BY game_key').fetchall()
            # Older expanded and C1 compact publications coexist. Repeated game
            # contexts must not multiply native observations or underlying pairs.
            encodings=set()
            for index,row in enumerate(rows):
                facts=row['facts'];board=facts['boards']['odds']
                encodings.update('refs' if q.get('current_comparison',{}).get('input_refs') else 'frozen'
                    for q in board['prices'])
                if index%2==0:
                    expand_odds(board);board.pop('comparison_input_encoding',None)
                for price in board['prices']:
                    price.setdefault('selection',{})['period_boundary']='unused-display-boundary-'*120
                    price.setdefault('observation_display',{})['unused_display_audit']='x'*3000
                db.execute('UPDATE latest_board SET facts=%s WHERE game_key=%s',(Jsonb(facts),row['game_key']))
                if index%3==0:
                    literal={'quote_id','quote_revision','field_refs'}
                    names=sorted({k for q in board['prices'] for k in q if k not in literal} |
                                 {k for q in board['prices'] for k in q.get('field_refs',{})})
                    board['price_key_pool']=names
                    board['prices']=[{k if k in literal else str(names.index(k)):
                        ({str(names.index(n)):v for n,v in value.items()} if k=='field_refs' else value)
                        for k,value in q.items()} for q in board['prices']]
                    db.execute('UPDATE latest_board SET facts=%s WHERE game_key=%s',(Jsonb(facts),row['game_key']))
                for copy in range(15):
                    db.execute('INSERT INTO latest_board SELECT %s,dependency_revision,economic_revision,calculated_at,%s FROM latest_board WHERE game_key=%s',
                        (row['game_key']+'-duplicate-'+str(copy),Jsonb(facts),row['game_key']))
            self.assertIn('refs',encodings)
            plain=db.execute(_PUBLICATION_SQL+' ORDER BY game_key').fetchall()
            compact=db.execute(_PUBLICATION_CAPTURE_SQL).fetchone()['capture']
            self.assertEqual(list(_publication_rows(compact,db)),plain)
            self.assertEqual(_captured_offers(compact),db.execute(_OFFER_SQL+' ORDER BY c.id').fetchall())
            del plain,compact
            size=_capture_size(db)
            # One complete game is the streaming boundary. The old all-games
            # representation is larger; exact admission and one-byte refusal
            # must preserve the previous publication.
            old_total=db.execute('SELECT octet_length(capture::text) n FROM ('+_PUBLICATION_CAPTURE_SQL+') p').fetchone()['n']
            streamed=db.execute("SELECT octet_length((capture-'rows')::text)+COALESCE((SELECT max(octet_length(r::text)) FROM jsonb_array_elements(capture->'rows') r),0) n FROM ("+_PUBLICATION_CAPTURE_SQL+") p").fetchone()['n']
            self.assertGreater(old_total,streamed)
            prior=db.execute('SELECT revision FROM coverage_latest').fetchone()
            from app.storage.coverage_latest import _stream_capture_totals
            streamed_size=max(int(r['largest']) for r in _stream_capture_totals(db))
            with patch('app.storage.coverage_latest.MAX_CAPTURE_BYTES',streamed_size-1):
                with self.assertRaisesRegex(ValueError,'coverage_capture_capacity'):reconcile(db)
            self.assertEqual(db.execute('SELECT revision FROM coverage_latest').fetchone(),prior)
            report=os.environ.get('PREDICT_CI_REPORT_ROOT')
            if report:Path(report,'c2-capture-bytes.json').write_text(json.dumps(dict(projected_input_bytes=size))+'\n')
            self.assertLess(size,8*1024*1024)
            # This is an encoding-equivalence check, not an elapsed-time test.
            # Keep the authored capture instant and heartbeat fixed while the
            # intentionally enlarged SQL fixture is prepared synchronously.
            instant=baseline['captured_at']
            with patch('app.collection.runtime_status.clock',return_value=stamp(instant)):
                self.state.write(self.service)
            result=reconcile(db,at=instant)
            value=read(db,at=instant)
            self.assertTrue(result['published'])
            for key in ('retained_observations','supported_comparison_observations','underlying_pairs',
                    'signed_comparison_directions','eligible_current_pairs','published_current_pairs'):
                self.assertEqual(value['global_totals'][key],baseline['global_totals'][key],key)
            self.assertNotIn('unused-display-boundary-',json.dumps(value))
            self.assertNotIn('unused_display_audit',json.dumps(value))
            original={tuple(e['source'].values()):e['times'] for c in baseline['cells'] for e in c['examples']}
            after={tuple(e['source'].values()):e['times'] for c in value['cells'] for e in c['examples']}
            self.assertEqual(original,after)
            metrics=db.execute("SELECT facts->'work_metrics' m FROM coverage_latest").fetchone()['m']
            self.assertLessEqual(metrics['reserved_work_bytes'],128*1024*1024)
            # Necessary facts cannot be silently dropped to force a fit.
            db.execute("UPDATE current_offer SET facts=jsonb_set(facts,'{source,necessary_identity_extension}',to_jsonb(repeat('z',150000)))")
            # A repeated extension now compresses losslessly; the expanded
            # memory or final output guard must still refuse it before publish.
            prior=db.execute('SELECT revision FROM coverage_latest').fetchone()
            with self.assertRaisesRegex(ValueError,'coverage_(capture|memory|publication)_capacity'):reconcile(db)
            self.assertEqual(db.execute('SELECT revision FROM coverage_latest').fetchone(),prior)
            db.execute("UPDATE current_offer SET facts=facts#-'{source,necessary_identity_extension}'")
            # A Coverage refusal is optional: the ordinary source publication
            # still advances a healthy original input through its own owner.
            records=CurrentRowStore(db).capture(include_depth=False)['records']
            selected=deepcopy(next(r for r in records if r['quote']['venue']=='kalshi'
                and r['event']['competition']=='NFL' and r['market_identity']['family']=='moneyline'
                and r['quote']['source']['native_side']=='yes'))
            clock=datetime.now(timezone.utc)+timedelta(seconds=1)
            selected['quote']['original']['value']='0.4900'
            selected['quote']['original']['native_value']=('0.5100' if
                selected['quote']['original'].get('transformation')=='one_minus_native_bid' else '0.4900')
            selected['quote']['times'].update(source_at=clock.isoformat(),received_at=clock.isoformat())
            CurrentRowStore(db).upsert_records([selected],now=clock.isoformat())
            self.state.write(self.service)
            from app.storage.latest_board import reconcile as publish_prices
            with patch('app.storage.coverage_latest.reconcile',side_effect=ValueError('coverage_capture_capacity')):
                self.assertTrue(publish_prices(db,at=clock.isoformat(),observations_only=True)['published'])
            prices=[q for row in db.execute(_PUBLICATION_SQL).fetchall() for q in row['prices']]
            self.assertTrue(any(q['source']==selected['quote']['source'] and q['original']['value']=='0.4900'
                and q['times']['source_at']==clock.isoformat() for q in prices),
                dict(selected=selected['quote'],candidates=[q for q in prices if q['source']==selected['quote']['source']],
                    errors=db.execute("SELECT facts->'observation_errors' errors FROM latest_board_status").fetchone()))
        self.assertEqual(calls,before_calls)

    async def test_c2_failed_board_withdraws_only_its_display_authority(self):
        from psycopg.types.json import Jsonb
        cases,calls,baseline=await self.matrix()
        await self.owner.close()
        with self.connect() as db:
            row=db.execute('SELECT game_key FROM latest_board ORDER BY game_key LIMIT 1').fetchone()
            db.execute("UPDATE latest_board_status SET facts=jsonb_set(facts,'{observation_errors}',%s)",
                (Jsonb([dict(game_key=row['game_key'],reason='board_compact_response_capacity')]),))
            reconcile(db);value=read(db)
        self.assertEqual(value['global_totals']['retained_observations'],72)
        self.assertLess(value['global_totals']['displayed_observations'],baseline['global_totals']['displayed_observations'])
        self.assertGreater(value['global_totals']['displayed_observations'],0)
        self.assertGreater(value['global_totals']['pending_observations'],0)
