"""SC03 disposable SQL capture/release + HTTP contract with authored finances.

Inherits verified separate-cluster setup only, not ordinary owner connections.
"""
from copy import deepcopy
from unittest import skipUnless, IsolatedAsyncioTestCase
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from app.comparison.scanner_tickets import selector
from app.dashboard.scanner_api import Scanner, mount
from tests import test_sc02_sql as parent
SOCKET=parent.SOCKET
from tests.test_sc02_projection import frame, fake
from tests.test_sc03_tickets import finance, catalog, CLIENT
from app.comparison.scanner_destinations import Destinations
from tests.test_ev09_n01 import AT


@skipUnless(SOCKET,'Explicit verified disposable SC02/SC03 SQL cluster required')
class TicketSQL(IsolatedAsyncioTestCase):
    connect=classmethod(parent.SQL.connect.__func__)
    setUpClass=classmethod(parent.SQL.setUpClass.__func__)
    tearDownClass=classmethod(parent.SQL.tearDownClass.__func__)
    provider=parent.SQL.provider

    async def test_targeted_capture_keeps_full500_occurrence_guard_before_member_filter(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from app.storage.current_rows import CurrentRowStore
        from app.storage.scanner_publication import transaction
        from app.storage.store import encoded
        from app.storage.scanner_preparation import is_immutable_fact
        from app.comparison.scanner_finance import dependencies
        from tests.sc06_fixture import records,native_books,AuthoredAdapters
        # Cache/identity assertions must not expire native inputs on a slower runner.
        # Expiry behavior is covered separately with explicit clock advances.
        from tests.test_sc03_finance import AT as finance_at
        clock=lambda: finance_at.isoformat();rows=records(500,at=clock())
        with TemporaryDirectory(prefix='predict-sc06-500-admission-') as directory:
            worker=Scanner(self.provider(),connector=self.connect,clock=clock,summary_path=Path(directory)/'summary')
            try:
                with self.connect() as db:
                    db.execute('TRUNCATE current_event CASCADE')
                    with transaction(db):
                        store=CurrentRowStore(db);store.upsert_records(rows);store.replace_native_books(native_books(rows))
                    decoded=CurrentRowStore(db).capture(include_depth=True)['records']
                    self.assertEqual(len(decoded),1000)
                    for row in decoded:
                        original=row['quote']['original']
                        self.assertEqual(original['transformation'],'identity')
                        self.assertEqual(original['native_value'],original['value'])
                        self.assertEqual(original['native_units'],original['units'])
                        self.assertEqual(row['quote']['depth'][0]['price'],original['value'])
                with AuthoredAdapters():
                    frame,inputs,metadata,elapsed=worker._capture()
                    self.assertEqual(len(frame['pairs']),500)
                    self.assertEqual(len(frame['instruments']),1000)
                    self.assertTrue(all(pair['input_check']['state']=='ready' for pair in frame['pairs']))
                    self.assertGreaterEqual(metadata['input_bytes_bound'],len(encoded(inputs)))
                    self.assertTrue(all(is_immutable_fact(i) for i in frame['instruments']))
                    self.assertTrue(all(is_immutable_fact(value) for value in inputs.values()))
                    selected=dict(inputs=deepcopy({key:inputs[key] for key in frame['pairs'][0]['legs']}))
                    worker._ingest_capture(frame,inputs,metadata,elapsed,worker.projection.policy)
                    with patch('app.comparison.scanner_projection.dependencies',wraps=dependencies) as owner:
                        again,again_inputs,again_metadata,again_ms=worker._capture()
                        worker._ingest_capture(again,again_inputs,again_metadata,again_ms,worker.projection.policy)
                        self.assertEqual(owner.call_count,0)
                    self.assertEqual(len(worker.projection._dependency_proofs),500)
                    selected_before=deepcopy({key:worker.projection.inputs[key] for key in selected['inputs']})
                    frame=inputs=None
                    fresh,fresh_inputs=worker._capture_selected(selected)
                    self.assertEqual(len(fresh['pairs']),1)
                    self.assertEqual(len(fresh['instruments']),2)
                    self.assertTrue(all(type(i) is dict for i in fresh['instruments']))
                    self.assertTrue(all(type(value) is dict for value in fresh_inputs.values()))
                    for value in fresh_inputs.values():
                        value['quote']['original']['value']='0'
                        value['profiles']['caller_mutation_probe']={'must_not_escape':True}
                    self.assertEqual({key:worker.projection.inputs[key] for key in selected['inputs']},selected_before)
                    _,fresh_again=worker._capture_selected(selected)
                    for value in fresh_again.values():
                        self.assertNotEqual(value['quote']['original']['value'],'0')
                        self.assertNotIn('caller_mutation_probe',value['profiles'])
                    self.assertEqual(worker.projection.evaluations,0)
                    extra=records(501,at=clock())[-2:]
                    with self.connect() as db:
                        with transaction(db):
                            store=CurrentRowStore(db);store.upsert_records(extra);store.replace_native_books(native_books(extra))
                    # Expanded scope must not reject the entire slate at game 501.
                    expanded,_,_,_=worker._capture()
                    self.assertEqual(len(expanded['pairs']),501)
                    worker._capture_selected(selected)
            finally:await worker.close()

    async def test_targeted_current_pair_proof_preserves_unrelated_continuity_and_rejects_changes(self):
        from contextlib import contextmanager
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from app.storage.current_rows import CurrentRowStore,contract_id
        from app.storage.scanner_publication import transaction
        from tests.sc06_fixture import records,native_books,AuthoredAdapters,Clock
        from app.storage import scanner_readiness
        clock=Clock();rows=records(9,at=clock());connections=[]
        @contextmanager
        def tracked():
            with self.connect() as db:
                connections.append(db)
                yield db
        with TemporaryDirectory(prefix='predict-targeted-ticket-') as directory:
            worker=Scanner(self.provider(),connector=tracked,clock=clock,summary_path=Path(directory)/'summary')
            worker.projection.clock=clock
            from app.comparison.scanner_tickets import Tickets
            tickets=Tickets(worker.projection,clock=clock)
            try:
                with self.connect() as db:
                    db.execute('TRUNCATE current_event CASCADE')
                    with transaction(db):
                        store=CurrentRowStore(db);store.upsert_records(rows);store.replace_native_books(native_books(rows))
                with AuthoredAdapters():
                    worker.once()
                    while worker.projection.pending:worker.once()
                    p=worker.projection
                    row=next(r for r in p.rows.values() if any(':sc06:000' in key[1] for key in [v['native_key'] for v in r['positions']]))
                    bound=selector(p,row);capture,reason=tickets._capture(bound)
                    self.assertIsNone(reason)
                    original_instruments=len(p.frame['instruments'])
                    selected_members={v['quote']['source']['native_event_id'] for v in capture['inputs'].values()}
                    observed=[];real=scanner_readiness.instrument
                    def checked(q,*args,**kwargs):
                        observed.append(q['source']['native_event_id'])
                        return real(q,*args,**kwargs)
                    before_connections=len(connections)
                    with patch.object(worker,'_capture',side_effect=AssertionError('selected proof rebuilt full scanner')):
                        with patch.object(scanner_readiness,'instrument',checked):
                            fresh=worker._capture_selected(capture)
                    self.assertEqual(len(connections)-before_connections,1)
                    self.assertTrue(all(db.closed for db in connections))
                    self.assertEqual(len(fresh[0]['instruments']),2)
                    self.assertEqual(len(fresh[0]['pairs']),1)
                    self.assertEqual(set(observed),selected_members)
                    self.assertEqual(len(p.frame['instruments']),original_instruments)
                    current,reason=tickets._capture(bound,snapshot=fresh)
                    self.assertIsNone(reason)
                    self.assertEqual(current['dependency_revision'],capture['dependency_revision'])
                    unrelated=deepcopy(rows[2]);unrelated['quote']['original'].update(value='3.1',native_value='3.1',native_units='decimal_odds',transformation='identity')
                    unrelated['quote']['depth'][0]['price']='3.1'
                    unrelated['quote']['times'].update(source_at=clock(),received_at=clock())
                    with self.connect() as db:
                        with transaction(db):CurrentRowStore(db).upsert_records([unrelated])
                    fresh=worker._capture_selected(capture)
                    current,reason=tickets._capture(bound,snapshot=fresh)
                    self.assertIsNone(reason)
                    self.assertEqual(current['dependency_revision'],capture['dependency_revision'])
                    # A newly committed peer outside the requested native IDs
                    # still participates in the fresh global occurrence proof.
                    from datetime import timedelta
                    from app.comparison.current_dependencies import instant
                    peer=deepcopy(rows[0]);peer['event']['id']+=':new-conflicting-peer'
                    peer['event']['scheduled_start']=(instant(peer['event']['scheduled_start'])+timedelta(hours=1)).isoformat()
                    peer['event']['season']='2027'
                    peer['market_identity']['season']='2027'
                    peer['market_identity']['scheduled_start']=peer['event']['scheduled_start']
                    for key in ('native_event_id','native_market_id','native_outcome_id'):
                        peer['quote']['source'][key]+=':new-conflicting-peer'
                    with self.connect() as db:
                        with transaction(db):CurrentRowStore(db).upsert_records([peer])
                    current,reason=tickets._capture(bound,snapshot=worker._capture_selected(capture))
                    self.assertTrue(current is None or current['dependency_revision'] != capture['dependency_revision'],
                        'new conflicting peer left exact selected proof unchanged')
                    with self.connect() as db:
                        with transaction(db):db.execute('DELETE FROM current_contract WHERE id=%s',(contract_id(peer),))
                    # Remove the now-empty event too: occurrence resolution
                    # intentionally reads all current event membership.
                    with self.connect() as db:
                        with transaction(db):db.execute('DELETE FROM current_event WHERE native_event_id=%s',(peer['quote']['source']['native_event_id'],))
                    current,reason=tickets._capture(bound,snapshot=worker._capture_selected(capture))
                    self.assertIsNone(reason)
                    self.assertEqual(current['dependency_revision'],capture['dependency_revision'])
                    changed=deepcopy(rows[0]);changed['quote']['original'].update(value='0.24',native_value='0.24',native_units='usd_per_contract',transformation='identity')
                    changed['quote']['depth'][0]['price']='0.24'
                    changed['quote']['times'].update(source_at=clock(),received_at=clock())
                    with self.connect() as db:
                        with transaction(db):
                            store=CurrentRowStore(db);store.upsert_records([changed]);store.replace_native_books(native_books([changed]))
                    current,reason=tickets._capture(bound,snapshot=worker._capture_selected(capture))
                    self.assertIsNone(reason)
                    self.assertNotEqual(current['dependency_revision'],capture['dependency_revision'])
                    with self.connect() as db:
                        with transaction(db):db.execute('DELETE FROM current_contract WHERE id=%s',(contract_id(changed),))
                    current,reason=tickets._capture(bound,snapshot=worker._capture_selected(capture))
                    self.assertIsNone(current);self.assertEqual(reason,'withdrawn')
            finally:
                await tickets.close();await worker.close()

    async def test_actual_sql_capture_connections_closed_before_selected_finance(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        from app.comparison.scanner_tickets import Tickets
        connections=[];captures=[]
        @contextmanager
        def tracked():
            with self.connect() as db:connections.append(db);yield db
        scanner=Scanner(self.provider(),connector=tracked,clock=lambda:AT)
        f,x=frame();p=scanner.projection;p.clock=lambda:AT;p.evaluator=fake
        p.ingest(f,x);p.drain()
        def fresh():
            # The SQL expiry filter must share the authored scanner clock.
            with patch('app.storage.current_rows.utc',return_value=AT):
                real,detached,meta,elapsed=scanner._capture()
            captures.append(dict(actual_revision=meta['current_rows_revision'],capture_ms=elapsed))
            self.assertTrue(all(db.closed for db in connections))
            self.assertTrue(real['instruments'])
            self.assertEqual(set(detached),{i['id'] for i in real['instruments']
                if all(i['checks'][purpose]['state']=='ready' for purpose in ('execution','contract'))})
            # Only readiness/inputs substitute authored supported data. SQL is real.
            return deepcopy(f),deepcopy(x)
        def selected(*a,**kw):
            fresh();self.assertTrue(all(db.closed for db in connections))
            self.assertFalse(p.lock._is_owned())
            return finance(*a,**kw)
        t=Tickets(p,allow_authored=True,calculate=selected,fresh=fresh,destinations=Destinations(catalog(f['instruments'])))
        try:
            r=await t.command(dict(operation='select',client_id=CLIENT,sequence=1,
                selection=selector(p,next(iter(p.rows.values())))))
            self.assertTrue(r['ready_for_manual_action']);self.assertGreaterEqual(len(captures),2)
            self.assertEqual(r['provider_requests'],0)
            self.assertIsNone(r['selected_frame']['causal']['sql_post_commit_observation'])
            with self.connect() as db:self.assertLess(db.execute('select pg_database_size(current_database()) n').fetchone()['n'],2*1024**3)
        finally:await t.close();await scanner.close()

    async def test_ticket_http_binding_commands_validation_stop_cleanup(self):
        app=web.Application();provider=self.provider();worker=mount(app,provider)
        worker.connector=self.connect;worker.clock=lambda:AT;p=worker.projection;p.clock=lambda:AT
        f,x=frame();p.evaluator=fake;p.ingest(f,x);p.drain()
        # Keep authored stable projection; real worker/capture covered separately.
        worker.start=lambda:None
        t=worker.tickets;t.allow_authored=True;t.calculate=finance;t.clock=lambda:AT;t.fresh=lambda:(f,x)
        t.destinations=Destinations(catalog(f['instruments']))
        client=TestClient(TestServer(app));await client.start_server()
        try:
            row=next(iter(p.rows.values()))
            q=dict(server_id=p.server_id,epoch=p.epoch,row_id=row['id'],
                dependency_revision=row['dependency_revision'],economic_revision=row['economic_revision'])
            response=await client.get('/api/scanner/ticket/binding',params=q)
            self.assertEqual(response.status,200);selection=(await response.json())['selection']
            response=await client.post('/api/scanner/ticket',json=dict(operation='select',client_id=CLIENT,sequence=1,selection=selection))
            self.assertEqual(response.status,200);r=await response.json();self.assertTrue(r['ready_for_manual_action'])
            response=await client.get('/api/scanner/ticket',params=dict(client_id=CLIENT,ticket_id=r['ticket_id']))
            self.assertEqual((await response.json())['state'],'unchanged')
            for change in ({'url':'https://evil.test'}, {'sequence':True}, {'amount':1000}, {'selection':dict(selection,epoch='obsolete')}):
                command=dict(operation='select',client_id=CLIENT,sequence=2,selection=selection);command.update(change)
                response=await client.post('/api/scanner/ticket',json=command);self.assertEqual(response.status,409)
            response=await client.post('/api/scanner/ticket',data='x'*4097,headers={'Content-Type':'application/json'})
            self.assertEqual(response.status,413)
            provider.dispatch=False
            response=await client.get('/api/scanner/ticket',params=dict(client_id=CLIENT,ticket_id=r['ticket_id']))
            self.assertEqual((await response.json())['state'],'stopped')
            response=await client.get('/api/scanner/ticket/binding',params=q);self.assertEqual(response.status,409)
        finally:await client.close()

    async def test_authored_ready_http_timing_with_actual_disposable_sql_capture(self):
        import json,os,math,resource,platform
        from pathlib import Path
        from time import perf_counter
        from tests.sc03_fixture import ready
        from tests.test_sc03_finance import AT as FINANCE_AT
        app=web.Application();worker=mount(app,self.provider());worker.connector=self.connect
        worker.clock=lambda:AT;worker.start=lambda:None
        t=worker.tickets;t.allow_authored=True;t.clock=lambda:FINANCE_AT.isoformat()
        original_capture=worker._capture;samples=[];witness=[]
        current={}
        def fresh():
            actual,detached,meta,ms=original_capture()
            witness.append(dict(actual_sql_revision=meta['current_rows_revision'],sql_capture_ms=ms,
                sql_instruments=len(actual['instruments']),sql_qualified_for_ticket=False))
            return current['frame'],current['inputs']
        t.fresh=fresh
        client=TestClient(TestServer(app));await client.start_server()
        try:
            for index in range(30):
                kind=('native','stake','mixed')[index%3]
                p,f,x,row=ready(kind=kind,amount='40' if index%2==0 else '500')
                current.update(frame=f,inputs=x)
                worker.projection=p;t.projection=p
                t.destinations=Destinations(catalog(f['instruments']))
                command=dict(operation='select',client_id=CLIENT,sequence=index+1,selection=selector(p,row))
                start=perf_counter();response=await client.post('/api/scanner/ticket',json=command)
                r=await response.json();elapsed=(perf_counter()-start)*1000
                self.assertEqual(response.status,200,r)
                self.assertTrue(r['ready_for_manual_action'],r.get('reason'))
                self.assertIsNone(r['selected_frame']['causal']['sql_post_commit_observation'])
                timings=r['timing']
                samples.append(dict(sample=index+1,kind=kind,requested=command.get('amount',p.policy.capital_ceiling_usd),
                    http_roundtrip_ms=elapsed,**timings,
                    queue_serialization_local_delivery_ms=max(0,elapsed-timings['total_backend_ms']),
                    response_bytes=len(await response.read()),sql_capture_ms=witness[-1]['sql_capture_ms']))
            ordered=sorted(s['http_roundtrip_ms'] for s in samples)
            result=dict(evidence_class='authored/local ready ticket and loopback HTTP; real disposable SQL capture with authored ready partition substitution; not current source/link/browser/installed qualification',
                samples=30,workload='one selected two-leg event at a time; 10 native, 10 stake, 10 mixed, alternating $40/$500; real financial allocator/fees/depth; actual fixture SQL current-row capture before publication',
                p95_ms=ordered[math.ceil(.95*len(ordered))-1],maximum_ms=max(ordered),
                p95_target_ms=1000,maximum_target_ms=2000,
                contributions={key:dict(p95=sorted(s[key] for s in samples)[28],maximum=max(s[key] for s in samples)) for key in
                    ('capture_ms','calculation_ms','validation_ms','sql_capture_ms','queue_serialization_local_delivery_ms')},
                machine=platform.machine(),system=platform.platform(),peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                provider_requests=0,full_finance_500_event_initialization=False,browser_rendering=False,
                measurements=samples,sql_witness=witness)
            if os.environ.get('PREDICT_CI_REPORT_ROOT'):
                (Path(os.environ['PREDICT_CI_REPORT_ROOT'])/'ticket-timing.json').write_text(json.dumps(result,indent=2)+'\n')
            self.assertLessEqual(result['p95_ms'],1000);self.assertLessEqual(result['maximum_ms'],2000)
        finally:await client.close()
