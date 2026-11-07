"""Coherent SQL + ordinary HTTP replacement, without provider or queue work."""
from copy import deepcopy
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
        with self.connect() as db:db.execute('TRUNCATE comparison_snapshot_head,comparison_snapshot_result,comparison_snapshot CASCADE')

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
                self.assertGreater(first['counts']['gross_numeric'],0)
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
                self.assertGreater(revised['counts']['net_numeric'],0)
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
        for native in ('yes','no'):
            q=quote(native=native);r=q['original_record']
            q.update(quote_id=q['id'],venue='polymarket_us',game_title='Home / Away',start_at=self.at.isoformat(),
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

    async def test_ncaab_exact_benchmark_http_originals_and_revision(self):
        from tests.test_snapshot_benchmark import execution,references,inputs
        from fractions import Fraction
        captured=inputs([execution()],references())
        app=web.Application();mount(app)
        with patch('app.dashboard.snapshot_api.connect',self.connect),patch.object(snapshot,'capture',return_value=captured):
            async with TestClient(TestServer(app)) as client:
                first=await (await client.post('/api/comparison-snapshot',json={'action':'refresh'})).json()
                self.assertEqual(first['counts']['gross_numeric'],1)
                row=first['rows'][0]
                self.assertEqual(Fraction(row['gross_return_percent']),50)
                self.assertIsNone(row['net_return_percent'])
                details='/api/comparison-snapshot/details?result_id='+first['id']+'&id='+row['id']
                before=await (await client.get(details)).json()
                self.assertEqual({r['id'] for r in before['references']},set(row['snapshot_benchmark']['ids']))
                self.assertEqual(before['references'],captured['references'])
                settings=dict(first['assumptions'],scenario='decisive_only',sizing='hypothetical_fractional',fees={'polymarket_us':'0'})
                second=await (await client.post('/api/comparison-snapshot',json={'action':'recalculate','assumptions':settings})).json()
                self.assertEqual(Fraction(second['rows'][0]['net_return_percent']),Fraction('49.5'))
                self.assertEqual(await (await client.get(details)).json(),before)
                grid=await (await client.get('/api/comparison-snapshot?view=odds')).json()
                self.assertEqual(grid['rows'][0]['quotes'][0]['reference_odds']['role'],'reference_only')

    async def test_independent_retention_respects_heads_pins_and_inflight_readers(self):
        from app.storage.storage_maintenance import maintain
        with self.connect() as db,self.connect() as reader:
            for i in range(7):
                db.execute("""INSERT INTO comparison_snapshot VALUES (%s,now()+%s*interval '1 hour',
                    'original',now()-interval '1 hour')""",(str(i),i))
                db.execute("""INSERT INTO comparison_snapshot_result(id,snapshot_id,assumptions,result,lease_until)
                    VALUES (%s,%s,'{}','result',now()-interval '1 hour')""",(str(i),str(i)))
            db.execute("INSERT INTO comparison_snapshot_head VALUES(true,'0')")
            db.execute("INSERT INTO comparison_snapshot_review VALUES('1')")
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

    async def test_guarded_capture_retains_previous_head(self):
        with self.connect() as db:
            original=snapshot.replace(db,action='refresh')
            with patch('app.collection.current_storage_policy.SQL_BYTE_CAP',1),self.assertRaisesRegex(ValueError,'headroom'):
                snapshot.replace(db,action='refresh')
            self.assertEqual(snapshot.current(db),original)
