import asyncio
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from app.collection.two_source_policy import specification,POLICY
from app.collection.two_source import QualificationOwner,QualificationSession,choose_event
from app.collection.run_spec import preflight
from app.collection.native_approval import validate_approval,digest
from app.collection.venue_access import ENDPOINTS
from app.dashboard.two_source_preview import check_package,supervise
from tests.segmented_collector_fixture import Fixture


def spec(mode='mock'):
    at=datetime.now(timezone.utc)
    return specification((at-timedelta(minutes=1)).isoformat(),(at+timedelta(minutes=14)).isoformat(),str(uuid4()),mode)


class PolicyTests(unittest.TestCase):
    def test_no_fabricated_event_identity_and_every_scope_change_rejected(self):
        s=spec('real');self.assertTrue(preflight(s)['valid'],preflight(s))
        self.assertNotIn('scheduled_start',s);self.assertNotIn('participants',s)
        for change in (lambda c:c.update(duration=91),lambda c:c['native_sources']['novig'].update(state='enabled'),lambda c:c['two_source_qualification'].update(event_pages=3),lambda c:c['sources']['kalshi'].update(credential_reference='elsewhere'),lambda c:c.update(reference_enabled=True)):
            c=deepcopy(s);change(c);self.assertFalse(preflight(c)['valid'])
        from app.collection.continuous import ContinuousSession
        with self.assertRaisesRegex(ValueError,'isolated qualification'):ContinuousSession(spec(),'unused',ENDPOINTS)

    def test_approval_window_identity_and_one_use_before_any_access(self):
        s=spec('real')
        with tempfile.TemporaryDirectory() as t,patch('app.collection.native_approval.implementation',return_value={'candidate':'hash'}):
            p=Path(t)/'approval.json';a=dict(approved=False,spec_sha256=digest(s),implementation_sha256=digest({'candidate':'hash'}),output=str(Path(t).resolve()));p.write_text(json.dumps(a))
            with self.assertRaises(ValueError):validate_approval(s,ENDPOINTS,p,t)
            a['approved']=True;p.write_text(json.dumps(a));validate_approval(s,ENDPOINTS,p,t,consume=True)
            marker=json.loads((Path(t)/'b3-attempt.json').read_text());self.assertEqual(marker['attempt_id'],s['two_source_qualification']['attempt_id']);self.assertGreater(marker['started_monotonic'],0)
            with self.assertRaisesRegex(ValueError,'consumed'):validate_approval(s,ENDPOINTS,p,t)
        future=deepcopy(s);future['start_after']=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat();future['start_before']=(datetime.fromisoformat(future['start_after'])+timedelta(minutes=15)).isoformat()
        with tempfile.TemporaryDirectory() as t,patch('app.collection.native_approval.implementation',return_value={'candidate':'hash'}):
            p=Path(t)/'approval.json';p.write_text(json.dumps(dict(approved=True,spec_sha256=digest(future),implementation_sha256=digest({'candidate':'hash'}),output=str(Path(t).resolve()))))
            with self.assertRaisesRegex(ValueError,'window'):validate_approval(future,ENDPOINTS,p,t,consume=True)
            self.assertFalse((Path(t)/'b3-attempt.json').exists())

    def test_supervisor_kills_stalled_collection_but_not_closed_sources(self):
        class Process:
            returncode=None;killed=False
            def poll(self):return self.returncode
            def kill(self):self.killed=True;self.returncode=-9
            def wait(self):return self.returncode
        s=spec('real')
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);p.joinpath('b3-attempt.json').write_text(json.dumps(dict(started_monotonic=10,attempt_id='id')))
            child=Process();self.assertEqual(supervise(child,p,s,clock=lambda:100),1);self.assertTrue(child.killed)
            p.joinpath('network-closed.json').write_text(json.dumps(dict(attempt_id='id',monotonic=99)))
            child=Process()
            def finish(_):child.returncode=0
            self.assertEqual(supervise(child,p,s,clock=lambda:101,sleep=finish),0);self.assertFalse(child.killed)

    def test_launcher_refuses_unapproved_package_before_access(self):
        with tempfile.TemporaryDirectory() as t, patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('forbidden')):
            with self.assertRaisesRegex(ValueError,'approval pending'):check_package(spec('real'),{'approved':False},t)

    def test_unreadable_attempt_marker_fails_closed(self):
        class Process:
            returncode=None
            def poll(self):return self.returncode
            def kill(self):self.returncode=-9
            def wait(self):return self.returncode
        with tempfile.TemporaryDirectory() as t:
            Path(t,'b3-attempt.json').write_text('{')
            ticks=iter([0,0,2]);child=Process()
            self.assertEqual(supervise(child,t,spec('real'),clock=lambda:next(ticks),sleep=lambda _:None),1)
            self.assertEqual(child.returncode,-9)

    def test_actual_consumed_attempt_stays_closed_without_access(self):
        root=Path('evidence/b6-two-source-prep-20260923/package-early')
        s=json.loads((root/'run-spec.json').read_text())
        # Check the retained consumed marker in this checkout, never an owner's
        # absolute output path or a live approval from another machine.
        output=Path('evidence/b6-two-source-live-20260923-6020c325-584b-44c7-9fa2-be5567568dbd')
        self.assertTrue((output/'b3-attempt.json').is_file())
        with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('forbidden')):
            with self.assertRaisesRegex(ValueError,'consumed'):check_package(s,{},output)
            with self.assertRaisesRegex(ValueError,'consumed'):validate_approval(s,ENDPOINTS,None,output,consume=True)

    def test_retained_real_event_filter_and_future_rejection(self):
        from app.collection.two_source import individual_game
        import base64
        old=Path('evidence/e6/prediction-only/real-20260915-discovery6/discovery.jsonl')
        rows=[json.loads(x)['row'] for x in old.read_text().splitlines()]
        pages=[r for r in rows if r.get('source')=='polymarket_us' and r.get('path')=='/v1/events']
        self.assertTrue(pages)
        for p in pages:
            self.assertIn('sportsMarketTypes=football_team_full_game_winner',p['params'])
            for e in json.loads(base64.b64decode(p['body_b64']))['events']:self.assertTrue(individual_game({'_native':e}))
        from app.collection.transport_session import reopen
        folder=Path('evidence/b6-two-source-live-20260923-6020c325-584b-44c7-9fa2-be5567568dbd')
        rows=reopen(next(folder.glob('*/*.jsonl')))['rows']
        for p in rows:
            if p.get('source')=='polymarket_us' and p.get('path')=='/v1/events':
                for e in json.loads(base64.b64decode(p['body_b64']))['events']:self.assertFalse(individual_game({'_native':e}))

    def test_real_scope_violation_is_not_a_collection_pass(self):
        from app.collection.two_source_audit import verify
        folder=Path('evidence/b6-two-source-corrected-72967ba6-7b2f-419c-9ecd-16283c9868bf/72967ba6-7b2f-419c-9ecd-16283c9868bf')
        result=verify(folder)
        self.assertEqual(result['state'],'FAIL');self.assertEqual(result['scope']['state'],'FAIL')
        self.assertEqual(len(result['scope']['observed']['polymarket_us']),10)
        self.assertEqual(len(result['scope']['expected']['polymarket_us']),1)
        self.assertTrue(result['exact_native_replay'])

    def test_exact_event_selection_rejects_ambiguous_changed_schedule_and_margin(self):
        at=datetime.now(timezone.utc);start=(at+timedelta(hours=1)).isoformat()
        def event(i):return dict(id=i,competition='NFL',identity='resolved',exclusion=None,scheduled_start=start,canonical_key=[start,['NFL:BUF','NFL:DET']],participants={'Buffalo':'NFL:BUF','Detroit':'NFL:DET'})
        cats={v:dict(events=[event(v)],markets=[]) for v in ('kalshi','polymarket_us')}
        self.assertEqual(choose_event(cats,at)['participants'],['NFL:BUF','NFL:DET'])
        cats['kalshi']['events'].append(event('duplicate'))
        with self.assertRaises(Exception):choose_event(cats,at)
        cats['kalshi']['events'].pop();cats['polymarket_us']['events'][0]['canonical_key'][0]='changed'
        with self.assertRaises(Exception):choose_event(cats,at)
        cats['polymarket_us']['events'][0]=event('polymarket_us')
        with self.assertRaises(Exception):choose_event(cats,at+timedelta(minutes=58))


class ProductTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.f=Fixture(kalshi_markets=3)
        feeds=web.Application();feeds.router.add_get('/ws',self.f.ws);feeds.router.add_get('/{path:.*}',self.fixture_rest)
        self.f.server=TestServer(feeds);await self.f.server.start_server();url=str(self.f.server.make_url('/')).rstrip('/')
        self.f.endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
        self.s=spec();self.o=QualificationOwner(self.root/'legacy',pilot_output=self.root/'run',product_mode=True,endpoints=self.f.endpoints,spec_factory=lambda:self.s,session_factory=QualificationSession);self.f.owner=self.o
        from app.dashboard.multi_game_server import create_app
        self.client=TestClient(TestServer(create_app(owner=self.o,sessions={})));await self.client.start_server()
        self.guards=[patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('no credentials')),patch('app.collection.native_product.load_native_secret',side_effect=AssertionError('no credentials'))]
        for guard in self.guards:guard.start()

    async def fixture_rest(self,request):
        if request.path=='/v1/events' and hasattr(self,'us_pages'):
            self.f.rest_calls.append((request.path,dict(request.query)))
            self.assertEqual(request.query['sportsMarketTypes'],'football_team_full_game_winner')
            self.assertGreater(datetime.fromisoformat(request.query['startTimeMin']),datetime.now(timezone.utc))
            return web.json_response(dict(events=self.us_pages[int(request.query['offset'])//5]))
        return await self.f.rest(request)

    def game(self):
        from tests.segmented_collector_fixture import pe
        e=pe('p');e.update(gameId=1,startTime=self.f.schedule,markets=[self.f.us_market('p0')]);return e

    def future(self,i):
        e=self.game();e.update(id='future'+str(i),gameId=0,title='Division winner')
        e['markets'][0].update(id='fm'+str(i),slug='fm'+str(i),sportsMarketType='football_division_winner')
        return e

    async def stopped_discovery(self,reason):
        await self.o.start();await asyncio.wait_for(self.o.session.task,5);await self.o.finalizer
        self.assertFalse(self.f.connections);self.assertEqual(self.o.session.reason,reason)
        self.assertEqual(self.o.session.discovery.refresh['reason'],reason)
        self.assertIsNone(self.o.error);self.assertTrue(self.o.session.cleanup_complete)
        before=len(self.f.rest_calls)
        with self.assertRaisesRegex(Exception,reason):await self.o.session.discovery.discover()
        self.assertEqual(len(self.f.rest_calls),before)
        from app.collection.two_source_audit import verify
        self.assertTrue(verify(self.o.session.output)['exact_snapshot'])
        from app.dashboard.session_history import load
        saved=load(self.o.session.output)
        self.assertTrue(all(x['state']=='discovery_failed' for x in saved['sources'] if x['source_id'] in ('kalshi','polymarket_us')))

    async def test_futures_only_short_results_no_subscriptions(self):
        self.us_pages=[[self.future(0)]]
        await self.stopped_discovery('no_compatible_shared_pregame_event')

    async def test_full_futures_pages_stop_at_exhaustion(self):
        self.us_pages=[[self.future(i) for i in range(5)],[self.future(i) for i in range(5,10)]]
        await self.stopped_discovery('event_page_limit_without_shared_game')
        self.assertEqual([q['offset'] for path,q in self.f.rest_calls if path=='/v1/events'],['0','5'])

    async def test_mixed_pages_match_only_native_individual_game(self):
        self.us_pages=[[self.future(i) for i in range(5)],[self.future(5),self.game()]]
        await self.o.start();self.observe();await self.f.wait(lambda:len(self.f.active())==2);await self.f.images()
        self.assertEqual(self.o.session.selected_event['polymarket_us'],'p')
        self.assertEqual(self.o.session.discovery.traversals['polymarket_us/events']['state'],'exhausted')
        await self.o.stop();await self.o.finalizer
        from app.collection.two_source_audit import verify
        self.assertEqual(verify(self.o.session.output)['collection'],'PASS')

    async def test_individual_games_with_changed_schedule_do_not_match(self):
        e=self.game();e['startTime']=(datetime.now(timezone.utc)+timedelta(days=4)).isoformat();self.us_pages=[[e]]
        await self.stopped_discovery('no_compatible_shared_pregame_event')

    async def test_repeated_page_ids_fail_closed(self):
        page=[self.future(i) for i in range(5)];self.us_pages=[page,page]
        await self.stopped_discovery('duplicate_or_missing_catalog_identity')

    async def asyncTearDown(self):
        await self.client.close();await self.f.close()
        for guard in self.guards:guard.stop()
        self.temp.cleanup()

    def observe(self):
        save=self.o.session.journal.save
        def observed(row):
            save(row);self.f.books+=row['type']=='prediction_book';self.f.changed.set()
        self.o.session.journal.save=observed

    async def test_ordinary_start_bounded_selection_unknown_fees_stop_and_fresh_replay(self):
        status=await (await self.client.get('/api/status')).json();self.assertEqual(status['fixed_duration'],90);self.assertFalse(self.f.rest_calls)
        origin=str(self.client.make_url('/')).rstrip('/')
        response=await self.client.post('/api/start',json={'duration':90},headers={'Origin':origin});self.assertEqual(response.status,200,await response.text())
        self.observe()
        await self.f.wait(lambda:len(self.f.active())==2)
        await self.f.images();await self.o.session.queue.join()
        selection=self.o.session.selected_event
        self.assertEqual(selection['markets']['kalshi'],['k0','k1']);self.assertEqual(selection['markets']['polymarket_us'],['p0'])
        self.assertTrue(all(int(q.get('limit','5'))==5 for path,q in self.f.rest_calls if path.endswith(('/events','/markets'))))
        board=await (await self.client.get('/api/dashboard?scenario=cent')).json();self.assertTrue(board['fee_scenario_locked'])
        self.assertTrue(board['rows']);self.assertTrue(all(r['profit'] is None for r in board['rows']))
        for route in ('references','resolutions'):
            r=await self.client.post('/api/'+route,json=[],headers={'Origin':origin});self.assertEqual(r.status,422)
        r=await self.client.post('/api/stop',json={},headers={'Origin':origin});self.assertEqual(r.status,200)
        await self.o.finalizer;self.assertIsNone(self.o.error);self.assertFalse(self.f.active())
        with self.assertRaisesRegex(ValueError,'consumed'):await self.o.start()
        from app.collection.two_source_audit import verify
        audit=verify(self.o.session.output);self.assertEqual(audit['collection'],'PASS');self.assertTrue(audit['exact_calculations']);self.assertEqual(audit['comparisons']['qualified'],0)
        proc=await asyncio.create_subprocess_exec(__import__('sys').executable,'-m','app.collection.two_source_audit',str(self.o.session.output),'--report',str(self.root/'fresh.json'),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        out,err=await proc.communicate();self.assertEqual(proc.returncode,0,err.decode());self.assertTrue(json.loads((self.root/'fresh.json').read_text())['exact_native_replay'])

    async def test_source_terminal_stops_entire_qualification(self):
        await self.o.start();self.observe();await self.f.wait(lambda:len(self.f.active())==2);await self.f.images()
        group=next(iter(self.o.session.producers['kalshi'].groups.values()))
        group['task'].cancel()
        await asyncio.wait_for(self.o.session.task,3);await self.o.finalizer
        self.assertEqual(self.o.session.reason,'qualification_source_ended_kalshi')
        self.assertFalse(self.f.active());self.assertTrue(self.o.session.cleanup_complete)

    async def test_multiple_valid_embedded_games_subscribe_only_exact_selection(self):
        selected=self.game();other=self.game();other.update(id='other',gameId=2,startTime=(datetime.now(timezone.utc)+timedelta(days=4)).isoformat())
        other['markets']=[self.f.us_market('other-market')];other['markets'][0]['gameStartTime']=other['startTime']
        self.us_pages=[[selected,other]]
        await self.o.start();self.observe();await self.f.wait(lambda:len(self.f.active())==2);await self.f.images()
        us=next(c for c in self.f.active() if c['venue']=='polymarket_us')
        self.assertEqual(us['command']['subscribe']['marketSlugs'],['p0'])
        self.assertEqual(self.o.session.producers['kalshi'].selected,['k0','k1'])
        self.assertEqual(self.o.session.producers['polymarket_us'].selected,['p0'])
        await self.o.stop();await self.o.finalizer
        from app.collection.two_source_audit import verify
        self.assertEqual(verify(self.o.session.output)['scope']['state'],'PASS')

    async def test_outgoing_command_guard_stops_before_dispatch(self):
        await self.o.start();self.observe();await self.f.wait(lambda:len(self.f.active())==2)
        from app.collection.odds_http import BudgetStop
        with self.assertRaises(BudgetStop):
            self.o.session.emit('polymarket_us',dict(type='prediction_command',body=json.dumps({'subscribe':{'marketSlugs':['not-selected']}})))
        await self.o.session.task;await self.o.finalizer
        self.assertEqual(self.o.session.reason,'qualification_subscription_scope_violation')
        self.assertFalse(self.f.active())

    async def test_unsolicited_frame_stops_before_book_admission_and_reopens(self):
        await self.o.start();self.observe();await self.f.wait(lambda:len(self.f.active())==2);await self.f.images()
        us=next(c for c in self.f.active() if c['venue']=='polymarket_us')
        await us['socket'].send_json(dict(requestId=us['command']['subscribe']['requestId'],subscriptionType='SUBSCRIPTION_TYPE_MARKET_DATA',marketData=dict(marketSlug='extra',bids=[],offers=[])))
        await asyncio.wait_for(self.o.session.task,5);await self.o.finalizer
        self.assertEqual(self.o.session.reason,'qualification_admission_scope_violation')
        self.assertNotIn('extra',self.o.session.producers['polymarket_us'].records)
        from app.collection.transport_session import reopen
        rows=reopen(self.o.session.output/(self.o.session.sid+'.jsonl'))['rows']
        rejected=[r for r in rows if r['type']=='qualification_scope_violation']
        self.assertEqual(rejected[0]['reason'],'unsolicited_market')
        self.assertEqual(rejected[0]['direction'],'incoming')
        self.assertTrue(all(r['book']['raw']['ref']['market_id']!='extra' for r in rows if r['type']=='prediction_book'))
        from app.collection.two_source_audit import verify
        audit=verify(self.o.session.output)
        self.assertEqual(audit['scope']['state'],'FAIL');self.assertTrue(audit['exact_calculations']);self.assertTrue(audit['cleanup_complete'])
        self.assertFalse(self.f.active())

    async def reject_wire(self,venue,body,expected):
        await self.o.start();self.observe();await self.f.wait(lambda:len(self.f.active())==2);await self.f.images()
        c=next(c for c in self.f.active() if c['venue']==venue)
        await c['socket'].send_json(body)
        await asyncio.wait_for(self.o.session.task,5);await self.o.finalizer
        from app.collection.transport_session import reopen
        rows=reopen(self.o.session.output/(self.o.session.sid+'.jsonl'))['rows']
        rejected=[r for r in rows if r['type']=='qualification_scope_violation']
        self.assertEqual(rejected[0]['reason'],expected)
        for r in rows:
            if r['type']=='prediction_book':
                self.assertIn(r['book']['raw']['ref']['market_id'],['k0','k1'] if r['source']=='kalshi' else ['p0'])
        from app.collection.two_source_audit import verify
        audit=verify(self.o.session.output)
        self.assertTrue(audit['exact_snapshot']);self.assertTrue(audit['exact_calculations']);self.assertTrue(audit['cleanup_complete'])
        proc=await asyncio.create_subprocess_exec(__import__('sys').executable,'-m','app.collection.two_source_audit',str(self.o.session.output),'--report',str(self.root/'fresh-audit.json'),stdout=asyncio.subprocess.DEVNULL)
        self.assertEqual(await proc.wait(),0)
        self.assertEqual(json.loads((self.root/'fresh-audit.json').read_text())['scope']['state'],'FAIL')
        self.assertFalse(self.f.active())

    async def test_mixed_batch_rejected_atomically_before_calculations(self):
        await self.reject_wire('polymarket_us',[dict(marketData=dict(marketSlug='p0')),dict(marketData=dict(marketSlug='extra'))],'unsupported_batch_or_envelope')

    async def test_selected_only_batch_is_unsupported_not_partially_admitted(self):
        await self.reject_wire('polymarket_us',dict(marketData=[dict(marketSlug='p0')]),'unsupported_batch_or_envelope')

    async def test_unsolicited_kalshi_snapshot(self):
        await self.reject_wire('kalshi',dict(type='orderbook_snapshot',sid=1,seq=2,msg=dict(market_ticker='extra')),'unsolicited_market')

    async def test_unsolicited_kalshi_delta(self):
        await self.reject_wire('kalshi',dict(type='orderbook_delta',sid=1,seq=2,msg=dict(market_ticker='extra')),'unsolicited_market')

    async def test_wrong_event_book_rejected_before_venue_records(self):
        await self.o.start();self.observe();await self.f.wait(lambda:len(self.f.active())==2);await self.f.images()
        v=self.o.session.producers['polymarket_us'];g=next(iter(v.groups))
        before=deepcopy(v.records)
        from app.collection.odds_http import BudgetStop
        with self.assertRaises(BudgetStop):v.emit(g,'polymarket_us',dict(type='prediction_book',book=dict(raw=dict(ref=dict(market_id='p0',event_id='wrong')))))
        self.assertEqual(v.records,before)
        await self.o.session.task;await self.o.finalizer
        self.assertFalse(self.f.active())

    async def test_reconnect_preserves_exact_commands_and_legitimate_updates(self):
        await self.o.start();self.observe();await self.f.wait(lambda:len(self.f.active())==2);await self.f.images()
        us=next(c for c in self.f.active() if c['venue']=='polymarket_us')
        await us['socket'].close()
        await self.f.wait(lambda:len([c for c in self.f.connections if c['venue']=='polymarket_us'])==2)
        await self.f.wait(lambda:len(self.f.active())==2);await self.f.images();await self.f.images()
        for c in self.f.connections:
            ids=c['command']['subscribe']['marketSlugs'] if c['venue']=='polymarket_us' else c['command']['params']['market_tickers']
            self.assertEqual(set(ids),{'p0'} if c['venue']=='polymarket_us' else {'k0','k1'})
        await self.o.stop();await self.o.finalizer
        from app.collection.two_source_audit import verify
        self.assertEqual(verify(self.o.session.output)['scope']['state'],'PASS')

    async def test_no_shared_event_stops_without_subscription(self):
        self.f.schedule=(datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat()
        await self.o.start();await asyncio.wait_for(self.o.session.task,5);await self.o.finalizer
        self.assertFalse(self.f.connections);self.assertEqual(self.o.session.reason,'no_compatible_shared_pregame_event');self.assertTrue(self.o.session.cleanup_complete)

    async def test_expired_discovery_budget_and_active_deadline_stop(self):
        await self.o.start();self.observe();await self.f.wait(lambda:len(self.f.active())==2);await self.f.images()
        self.o.session.started_monotonic=__import__('time').monotonic()-89
        await asyncio.wait_for(self.o.session.task,3);await self.o.finalizer
        self.assertEqual(self.o.session.reason,'qualification_deadline');self.assertFalse(self.f.active())

    async def test_discovery_deadline_cancels_before_subscription(self):
        await self.o.start();self.o.session.started_monotonic-=31
        await asyncio.wait_for(self.o.session.task,3);await self.o.finalizer
        self.assertEqual(self.o.session.reason,'discovery_deadline');self.assertFalse(self.f.connections)

    async def test_oversized_catalog_stops_without_any_subscription(self):
        self.f.kalshi_markets=6
        await self.o.start();await asyncio.wait_for(self.o.session.task,5);await self.o.finalizer
        self.assertFalse(self.f.connections);self.assertTrue(self.o.session.cleanup_complete)
        self.assertEqual(self.o.session.reason,'catalog_page_scope_exceeded')

class TimingPackageTests(unittest.TestCase):
    def package(self,root):
        from app.collection.native_approval import implementation
        from hashlib import sha256
        p=Path(root)/'package';p.mkdir();s=spec('real');files=implementation()
        for name,value in [('run-spec.template.json',s),('candidate.json',dict(files=files)),('approval.draft.json',dict(approved=False,spec_sha256=digest(s),implementation_sha256=digest(files),output=str(Path(root)/'output')))]:
            (p/name).write_text(json.dumps(value))
        seal={f.name:sha256(f.read_bytes()).hexdigest() for f in p.iterdir()}
        (p/'seal.json').write_text(json.dumps(dict(files=seal,sha256=digest(seal))))
        return p,s

    def test_approved_on_demand_changes_only_times_and_cannot_rebind(self):
        from app.collection.two_source_package import activate
        with tempfile.TemporaryDirectory() as t:
            p,s=self.package(t);at=datetime.now(timezone.utc)
            result=activate(p,'now','Owner approved one immediate attempt',now=at)
            actual=json.loads((p/'activation/run-spec.json').read_text())
            self.assertEqual({k:v for k,v in s.items() if k not in ('start_after','start_before')},{k:v for k,v in actual.items() if k not in ('start_after','start_before')})
            self.assertEqual(result['start_after'],at.isoformat())
            self.assertTrue(json.loads((p/'activation/approval.json').read_text())['approved'])
            with self.assertRaises(FileExistsError):activate(p,'now','Another request',now=at)

    def test_future_choice_tamper_and_missing_approval_fail_closed(self):
        from app.collection.two_source_package import activate,verify
        with tempfile.TemporaryDirectory() as t:
            p,s=self.package(t)
            with self.assertRaises(ValueError):activate(p,'now','')
            future=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
            self.assertEqual(activate(p,future,'Owner approved this future start')['start_after'],future)
            (p/'run-spec.template.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'changed'):verify(p)

class AdmissionShapeTests(unittest.TestCase):
    def test_snapshots_updates_batches_and_wrong_event(self):
        import base64
        from app.collection.two_source_scope import violation
        selection=dict(kalshi='k',polymarket_us='p',markets=dict(kalshi=['k0'],polymarket_us=['p0']),subscription_ids=dict(kalshi=['k0'],polymarket_us=['slug']))
        def frame(v,c):return violation(v,dict(type='prediction_frame',body_b64=base64.b64encode(json.dumps(c).encode()).decode()),selection)
        for kind in ('orderbook_snapshot','orderbook_delta'):
            good=dict(type=kind,msg=dict(market_ticker='k0'))
            self.assertIsNone(frame('kalshi',good))
            self.assertEqual(frame('kalshi',dict(type=kind,msg=dict(market_ticker='extra'))),'unsolicited_market')
            self.assertEqual(frame('kalshi',[good,good]),'unsupported_batch_or_envelope')
        good=dict(marketData=dict(marketSlug='slug',bids=[],offers=[]))
        bad=dict(marketData=dict(marketSlug='extra'))
        self.assertIsNone(frame('polymarket_us',good))
        for batch in ([good,good],[good,bad],dict(marketData=[good,bad]),dict(updates=[good,bad])):
            self.assertEqual(frame('polymarket_us',batch),'unsupported_batch_or_envelope')
        for kind in ('market_selected','prediction_book'):
            row=dict(type=kind);row['market' if kind=='market_selected' else 'book']=dict(raw=dict(ref=dict(market_id='p0',event_id='wrong')))
            self.assertEqual(violation('polymarket_us',row,selection),'book_or_market_outside_frozen_selection')
