"""Coherent SQL + ordinary HTTP replacement, without provider or queue work."""
import asyncio
from copy import deepcopy
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from tests.latest_board_fixture import LatestBoardFixture,SOCKET
from app.storage import comparison_snapshot as snapshot
from app.storage.current_rows import CurrentRowStore
from app.dashboard.snapshot_api import mount

@skipUnless(SOCKET,'Disposable PostgreSQL required')
class SnapshotSQL(LatestBoardFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        change=patch('app.storage.comparison_snapshot.utc',side_effect=lambda:self.at.isoformat())
        change.start();self.addCleanup(change.stop)
        with self.connect() as db:db.execute('TRUNCATE comparison_snapshot_result,comparison_snapshot CASCADE')

    async def test_mvcc_capture_concurrent_update_and_recalculation(self):
        original=CurrentRowStore.capture;changed=[]
        def interleaved(store,**kwargs):
            frame=original(store,**kwargs)
            if not changed:changed.append(self.changed_first())
            return frame
        with self.connect() as db:
            with patch.object(CurrentRowStore,'capture',interleaved):old=snapshot.replace(db,action='refresh')
            self.assertTrue(old['rows']);self.assertTrue(changed)
            q=changed[0]['quote'];selected=next(r for r in old['rows'] if r['source']==q['source'])
            self.assertNotEqual(selected['original']['value'],'2.91')
            opts=dict(old['assumptions'],scenario='decisive_only',sizing='hypothetical_fractional',fees={'novig':'0','prophetx':'0','kalshi':'0','polymarket_us':'0'})
            with patch('app.storage.comparison_snapshot.capture',side_effect=AssertionError('recalculation must not capture prices')):
                recalculated=snapshot.replace(db,action='recalculate',value=opts,expected=old['id'])
            self.assertEqual(recalculated['snapshot_id'],old['snapshot_id'])
            self.assertNotEqual(recalculated['assumptions']['revision'],old['assumptions']['revision'])
            fresh=snapshot.replace(db,action='refresh',expected=recalculated['id'])
            self.assertNotEqual(fresh['snapshot_id'],old['snapshot_id'])
            self.assertEqual(next(r for r in fresh['rows'] if r['source']==q['source'])['original']['value'],'2.91')
            self.assertEqual(snapshot.current(db,old['id']),old)
            with self.assertRaises(ValueError):snapshot.replace(db,action='recalculate',expected=old['id'])
            self.assertEqual(snapshot.current(db)['id'],fresh['id'])

    async def test_http_pages_details_same_revision_replacement_failure(self):
        import logging
        from app.dashboard.request_guard import dashboard_guard
        app = web.Application(middlewares=[dashboard_guard(None, logger=logging.getLogger(__name__))])
        mount(app)
        with patch('app.dashboard.snapshot_api.connect',self.connect):
            async with TestClient(TestServer(app)) as client:
                client.session.headers['Origin'] = str(client.make_url('/')).rstrip('/')
                response=await client.post('/api/comparison-snapshot',json={'action':'refresh'})
                self.assertEqual(response.status,200)
                first=await response.json();self.assertEqual(first['provider_requests'],0)
                self.assertGreater(first['counts']['observations'],0)
                self.assertEqual(first['counts']['gross_numeric'],0)
                for invalid in ('limit=0', 'offset=bad', 'view=bogus', 'metric=bogus'):
                    with patch.object(snapshot, 'replace', wraps=snapshot.replace) as replace:
                        failed = await client.post('/api/comparison-snapshot?' + invalid,
                                                   json={'action': 'refresh', 'expected': first['id']})
                        self.assertEqual(failed.status, 422)
                        replace.assert_not_called()
                latest = await (await client.get('/api/comparison-snapshot')).json()
                self.assertEqual(latest['id'], first['id'])
                row=first['rows'][0]
                path='/api/comparison-snapshot/details?result_id='+first['id']+'&id='+row['id']
                evidence=await (await client.get(path)).json()
                self.assertEqual(evidence['originals'][0]['original'],row['original'])
                opts=dict(first['assumptions'],amount='2000',scenario='decisive_only',sizing='hypothetical_fractional',fees={'novig':'0','prophetx':'0','kalshi':'0','polymarket_us':'0'})
                response=await client.post('/api/comparison-snapshot',json={'action':'recalculate','assumptions':opts,'expected':first['id']})
                revised=await response.json();self.assertEqual(response.status,200)
                self.assertEqual(first['snapshot_id'],revised['snapshot_id'])
                self.assertEqual(revised['counts']['net_numeric'],0)
                self.assertEqual(revised['assumptions']['amount'],'2000')
                for view in ('ev','odds','arbs'):
                    page=await (await client.get('/api/comparison-snapshot',params={'view':view,'result_id':revised['id'],'offset':'0','limit':'1'})).json()
                    self.assertEqual(page['assumptions'],revised['assumptions'])
                    self.assertEqual(page['snapshot_id'],first['snapshot_id'])
                self.changed_first()
                replacement=await (await client.post('/api/comparison-snapshot',json={'action':'refresh','expected':revised['id']})).json()
                self.assertNotEqual(replacement['snapshot_id'],first['snapshot_id'])
                self.assertEqual(await (await client.get(path)).json(),evidence)
                with patch('app.storage.comparison_snapshot.capture',side_effect=ValueError('authored capture failure')):
                    failed=await client.post('/api/comparison-snapshot',json={'action':'refresh','expected':replacement['id']})
                    self.assertGreaterEqual(failed.status,400)
                latest=await (await client.get('/api/comparison-snapshot')).json()
                self.assertEqual(latest['id'],replacement['id'])

    async def test_missing_or_incompatible_inputs_disable_only_dependent_metrics(self):
        with self.connect() as db:
            captured=snapshot.capture(db)
        a=snapshot.calculate(captured)
        self.assertGreater(a['counts']['gross_numeric'],0)
        self.assertEqual(a['counts']['net_numeric'],0)
        broken=deepcopy(captured)
        # Native finance is rebuilt from the retained reference witnesses, not
        # a cached derived binding. Remove the actual probability inputs.
        broken['references']=[]
        for q in broken['quotes']:
            q['same_outcome']['supported']=False
            q['reference']=None;q['benchmark_quote']=None
        b=snapshot.calculate(broken,dict(a['assumptions'],scenario='decisive_only',sizing='hypothetical_fractional',fees={'novig':'0'}))
        self.assertEqual(b['counts']['gross_numeric'],0)
        self.assertEqual(b['pairs'],[])
        self.assertEqual(len(a['rows']),len(b['rows']))

    async def test_unknown_ncaab_snapshot_http_keeps_original_admission(self):
        from tests.test_snapshot_identity import quote
        from app.storage.store import hashed
        inputs=dict(id='ncaab-fixed',captured_at=self.at.isoformat(),capture_seconds=0,
            quotes=[],games=[],references=[],sources={},issues=[])
        starts_at = (self.at + timedelta(minutes=1)).isoformat()
        for native in ('yes','no'):
            q=quote(native=native);r=q['original_record']
            r['event']['scheduled_start'] = starts_at
            q.update(quote_id=q['id'],venue='polymarket_us',game_title='Home / Away',start_at=starts_at,
                market={'market':'total','period':'full_game','line':'135.5'},
                original=r['quote']['original'],common_odds={'supported':True},binding={'verified':False},
                selection=r['selection'])
            inputs['quotes'].append(q)
        before=hashed(inputs)
        app=web.Application();mount(app)
        with patch('app.dashboard.snapshot_api.connect',self.connect),patch.object(snapshot,'capture',return_value=inputs):
            async with TestClient(TestServer(app)) as client:
                first=await (await client.post('/api/comparison-snapshot',json={'action':'refresh'})).json()
                self.assertEqual(first['counts']['unmatched'],0)
                settings=dict(first['assumptions'],scenario='decisive_only',sizing='hypothetical_fractional',fees={'polymarket_us':'0'})
                result=await (await client.post('/api/comparison-snapshot?view=arbs',json={'action':'recalculate','assumptions':settings})).json()
                self.assertEqual(result['total'],1)
                self.assertIsNotNone(result['rows'][0]['minimum_return_percent'])
                evidence=await (await client.get('/api/comparison-snapshot/details',params={'result_id':result['id'],'id':result['rows'][0]['id']})).json()
                self.assertEqual(evidence['originals'],inputs['quotes'])
                self.assertTrue(all(not q['binding']['verified'] for q in evidence['originals']))
        self.assertEqual(hashed(inputs),before)

    async def test_saved_snapshot_operation_and_read_share_pregame_cutoff(self):
        from tests.test_snapshot_benchmark import execution, inputs

        quote = execution()
        captured = dict(inputs([quote], []), captured_at=quote['start_at'])
        app = web.Application()
        mount(app)
        with patch('app.dashboard.snapshot_api.connect', self.connect), \
                patch.object(snapshot, 'capture', return_value=captured):
            async with TestClient(TestServer(app)) as client:
                response = await client.post('/api/comparison-snapshot', json={'action': 'refresh'})
                self.assertEqual(response.status, 200)
                posted = await response.json()
                response = await client.get('/api/comparison-snapshot', params={'result_id': posted['id']})
                self.assertEqual(response.status, 200)
                read = await response.json()
                self.assertEqual(posted['rows'], [])
                self.assertEqual(posted['counts']['observations'], 0)
                self.assertEqual(read['rows'], posted['rows'])
                self.assertEqual(read['counts'], posted['counts'])
        with self.connect() as db:
            saved = snapshot.current(db, posted['id'])
            self.assertEqual(len(saved['rows']), 1)
            self.assertEqual(saved['rows'][0]['start_at'], quote['start_at'])

    async def test_ncaab_http_prices_keep_reference_provenance_private(self):
        from tests.test_snapshot_benchmark import execution,references,inputs

        captured=inputs([execution()],references())
        app=web.Application();mount(app)
        with patch('app.dashboard.snapshot_api.connect', wraps=self.connect) as connect, \
                patch.object(snapshot, 'capture', return_value=captured):
            async with TestClient(TestServer(app)) as client:
                first=await (await client.post('/api/comparison-snapshot',json={'action':'refresh'})).json()
                self.assertEqual(first['counts']['gross_numeric'],0)
                row=first['rows'][0]
                self.assertIsNone(row['gross_return_percent'])
                self.assertIsNone(row['net_return_percent'])
                details='/api/comparison-snapshot/details?result_id='+first['id']+'&id='+row['id']
                connect.reset_mock()
                before=await (await client.get(details)).json()
                connect.assert_called_once()
                self.assertEqual(before['references'], [])
                self.assertEqual(before['row']['original'], row['original'])
                with self.connect() as db:
                    raw = db.execute('SELECT inputs FROM comparison_snapshot WHERE id=%s', (captured['id'],)).fetchone()
                    self.assertEqual(snapshot.unpack(raw['inputs'])['references'], captured['references'])
                settings=dict(first['assumptions'],scenario='decisive_only',sizing='hypothetical_fractional',fees={'polymarket_us':'0'})
                second=await (await client.post('/api/comparison-snapshot',json={'action':'recalculate','assumptions':settings})).json()
                self.assertIsNone(second['rows'][0]['net_return_percent'])
                self.assertEqual(await (await client.get(details)).json(),before)
                grid=await (await client.get('/api/comparison-snapshot?view=odds')).json()
                self.assertIsNone(grid['rows'][0]['quotes'][0]['reference_odds'])

    async def test_independent_retention_respects_heads_pins_and_inflight_readers(self):
        from app.storage.storage_maintenance import maintain
        with self.connect() as db,self.connect() as reader:
            for i in range(7):
                db.execute("""INSERT INTO comparison_snapshot VALUES (%s,now()+%s*interval '1 hour',
                    'original',now()-interval '1 hour')""",(str(i),i))
                db.execute("""INSERT INTO comparison_snapshot_result(id,snapshot_id,assumptions,result,lease_until)
                    VALUES (%s,%s,'{}','result',now()-interval '1 hour')""",(str(i),str(i)))
            db.execute("INSERT INTO comparison_publication(kind,id,result_id) VALUES('manual','','0')")
            db.execute("INSERT INTO comparison_result_reference(kind,holder,result_id) VALUES('review','1','1')")
            db.execute("UPDATE comparison_snapshot_result SET lease_until=now()+interval '1 hour' WHERE id='2'")
            with reader.transaction():
                reader.execute("UPDATE comparison_snapshot_result SET lease_until=now()+interval '1 hour' WHERE id='3'")
                maintain(db,compact=False)
            for table in ('comparison_snapshot_result','comparison_snapshot'):
                rows=db.execute(f'SELECT id FROM {table} ORDER BY id').fetchall()
                self.assertEqual([r['id'] for r in rows],list('012356'))
            db.execute("UPDATE comparison_snapshot_result SET lease_until=now()-interval '1 hour' WHERE id IN ('2','3')")
            with self.assertRaises(RuntimeError),db.transaction():
                snapshot.prune(db)
                raise RuntimeError('abort cleanup')
            self.assertTrue(db.execute("SELECT 1 FROM comparison_snapshot_result WHERE id='2'").fetchone())
            maintain(db,compact=False)
            self.assertEqual(db.execute('SELECT count(*) n FROM comparison_snapshot').fetchone()['n'],4)

    async def test_manual_read_rolls_back_both_leases_when_input_renewal_fails(self):
        from app.dashboard.request_guard import dashboard_guard

        def leases(db, result_id):
            return db.execute('''SELECT r.lease_until AS result_lease,s.lease_until AS input_lease
                FROM comparison_snapshot_result r JOIN comparison_snapshot s ON s.id=r.snapshot_id
                WHERE r.id=%s''', (result_id,)).fetchone()

        with self.connect() as db:
            prior = snapshot.replace(db, action='refresh')
            db.execute("UPDATE comparison_snapshot_result SET lease_until=now()-interval '1 minute' WHERE id=%s",
                       (prior['id'],))
            db.execute("UPDATE comparison_snapshot SET lease_until=now()-interval '1 minute' WHERE id=%s",
                       (prior['snapshot_id'],))
            before = leases(db, prior['id'])
            db.execute('''CREATE FUNCTION reject_input_renewal() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'fixture input renewal failure'; END $$;
                CREATE TRIGGER reject_input_renewal BEFORE UPDATE ON comparison_snapshot
                    FOR EACH ROW EXECUTE FUNCTION reject_input_renewal()''')
            try:
                app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
                mount(app)
                with patch('app.dashboard.snapshot_api.connect', self.connect):
                    async with TestClient(TestServer(app)) as client:
                        failed = await client.get('/api/comparison-snapshot')
                        self.assertEqual(failed.status, 503)
                        self.assertEqual(leases(db, prior['id']), before)
                        db.execute('DROP TRIGGER reject_input_renewal ON comparison_snapshot')
                        retried = await client.get('/api/comparison-snapshot')
                        self.assertEqual(retried.status, 200)
                        self.assertEqual((await retried.json())['id'], prior['id'])
                renewed = leases(db, prior['id'])
                self.assertGreater(renewed['result_lease'], before['result_lease'])
                self.assertEqual(renewed['result_lease'], renewed['input_lease'])
            finally:
                db.execute('DROP TRIGGER IF EXISTS reject_input_renewal ON comparison_snapshot')
                db.execute('DROP FUNCTION reject_input_renewal()')

    async def test_guarded_capture_retains_previous_head(self):
        with self.connect() as db:
            original=snapshot.replace(db,action='refresh')
            with patch('app.collection.current_storage_policy.SQL_BYTE_CAP',1),self.assertRaisesRegex(ValueError,'headroom'):
                snapshot.replace(db,action='refresh')
            self.assertEqual(snapshot.current(db),original)

    async def test_manual_read_renews_the_head_committed_during_pointer_lock(self):
        app = web.Application()
        mount(app)
        loop = asyncio.get_running_loop()
        reader_pid = loop.create_future()

        def connect_reader():
            db = self.connect()
            loop.call_soon_threadsafe(reader_pid.set_result, db.info.backend_pid)
            return db

        with self.connect() as writer, patch('app.dashboard.snapshot_api.connect', connect_reader):
            prior = snapshot.replace(writer, action='refresh')
            replacement = dict(prior, id='replacement-manual-head')
            async with TestClient(TestServer(app)) as client, asyncio.TaskGroup() as group:
                with writer.transaction():
                    snapshot.insert_result(writer, replacement, prior['snapshot_id'], snapshot.pack(replacement))
                    writer.execute("UPDATE comparison_snapshot_result SET lease_until=now()-interval '1 minute'"
                                   " WHERE id=%s", (replacement['id'],))
                    writer.execute("UPDATE comparison_publication SET result_id=%s WHERE kind='manual' AND id=''",
                                   (replacement['id'],))
                    request = group.create_task(client.get('/api/comparison-snapshot'))
                    async with asyncio.timeout(3):
                        pid = await reader_pid
                        while writer.info.backend_pid not in writer.execute(
                                'SELECT pg_blocking_pids(%s) AS blockers', (pid,)).fetchone()['blockers']:
                            await asyncio.sleep(0.01)
                response = await request
                self.assertEqual(response.status, 200)
                self.assertEqual((await response.json())['id'], replacement['id'])
            row = writer.execute('''SELECT r.lease_until=s.lease_until AND r.lease_until>now() AS renewed
                FROM comparison_snapshot_result r JOIN comparison_snapshot s ON s.id=r.snapshot_id
                WHERE r.id=%s''', (replacement['id'],)).fetchone()
            self.assertTrue(row['renewed'])

    async def test_selected_result_lease_capacity_uses_one_database_clock(self):
        with self.connect() as db, db.transaction(force_rollback=True):
            prior = snapshot.replace(db, action='refresh')
            for result_id in ('automatic-held', 'automatic-unleased'):
                result = dict(prior, id=result_id)
                snapshot.insert_result(db, result, prior['snapshot_id'], snapshot.pack(result), automatic=True)
            db.execute("""UPDATE comparison_snapshot_result SET lease_until=now()-interval '1 minute'
                WHERE automatic""")
            with patch.object(snapshot, 'EVIDENCE_LEASE_LIMIT', 1), \
                    patch.object(snapshot, 'utc', return_value='2000-01-01T00:00:00Z'):
                self.assertTrue(snapshot.renew_result_lease(db, 'automatic-held'))
                self.assertTrue(snapshot.renew_result_lease(db, 'automatic-held'))
                with self.assertRaisesRegex(snapshot.SnapshotOperationError, 'lease capacity reached'):
                    snapshot.current(db, 'automatic-unleased')
                state = db.execute('''SELECT lease_until<now() expired FROM comparison_snapshot_result
                    WHERE id='automatic-unleased' ''').fetchone()
                self.assertTrue(state['expired'])

                token = snapshot.retain_evidence(db, 'automatic-unleased')
                self.assertEqual(token['lease_seconds'], 7200)
                self.assertEqual(snapshot.retain_evidence(db, 'automatic-unleased', token['lease_id']), token)
                with self.assertRaisesRegex(snapshot.SnapshotOperationError, 'lease capacity reached'):
                    snapshot.retain_evidence(db, 'automatic-held')
                snapshot.release_evidence(db, token['lease_id'])
                self.assertFalse(db.execute('SELECT 1 FROM comparison_result_reference WHERE holder=%s',
                                            (token['lease_id'],)).fetchone())
