"""Controlled service/scheduler/store checks. All response bytes are fictional."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
from app.collection.current_aggregate import AggregateScheduler,PARAMS
from app.collection.current_policy import DEFAULT
from app.collection.current_quota import QuotaLedger,QuotaStop
from app.collection.current_service import CurrentService
from app.collection.current_sink import LatestStateSink,utc
from app.collection.local_ownership import LocalOwnership
from app.dashboard.current_state import CurrentStore,SelectionError
from app.dashboard.multi_game_server import create_app
from tests.test_current_quota import WINDOW,AT,quota
from tests.test_current_service import FakeWorker,native_fixture
from tests.test_current_state import owner,request


def body(sport='MLB',books=('novig','prophetx'), *,at='2026-10-03T00:00:00Z',price='2.5000'):
    event=dict(id='CONTROLLED-event',sport_key={'MLB':'baseball_mlb','NFL':'americanfootball_nfl'}[sport],
        home_team='CONTROLLED HOME',away_team='CONTROLLED AWAY',commence_time='2026-10-10T12:00:00Z',bookmakers=[])
    for book in books:
        markets=[]
        for market in ('h2h','spreads','totals'):
            names=['Over','Under'] if market=='totals' else [event['home_team'],event['away_team']]
            outcomes=[dict(name=n,price=price if book=='novig' else '2.0') for n in names]
            if market!='h2h':
                for i,o in enumerate(outcomes):o['point']=('3.5' if i==0 else '-3.5') if market=='spreads' else '47.5'
            markets.append(dict(key=market,last_update=at,outcomes=outcomes))
        if book=='prophetx':
            for m in markets:m['outcomes'].reverse()
        event['bookmakers'].append(dict(key=book,last_update=at,markets=markets))
    return json.dumps([event]).encode()


class Wire:
    def __init__(self):self.calls=[];self.closed=False;self.used=20;self.paid_body=body();self.hold=None;self.error=None;self.headers=None
    async def request(self,req,key):
        self.calls.append(deepcopy(req))
        if self.hold:await self.hold.wait()
        if self.error:raise self.error
        bootstrap=req['path']=='/v4/sports'
        if not bootstrap:self.used+=3
        payload=json.dumps([dict(key='baseball_mlb',active=True,has_outrights=False),dict(key='americanfootball_nfl',active=True,has_outrights=False)]).encode() if bootstrap else self.paid_body
        return dict(status=200,headers=self.headers or quota(self.used,0 if bootstrap else 3),body=payload,received_at=utc())
    async def close(self):self.closed=True


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.service=CurrentService(config=dict(DEFAULT,sports=['MLB']),directory=self.root/'service',ownership=LocalOwnership(self.root/'owner'),worker_factory=FakeWorker)
        self.store=CurrentStore(self.service);self.service.store=self.store
        self.service.sink=LatestStateSink(self.store,self.service.initial_state());self.service.ownership.acquire(self.service.runtime_id)
        self.service.dispatch=True;self.service.deadline=__import__('time').monotonic()+300;self.service.digest='CONTROLLED-candidate'
        self.q=QuotaLedger(self.root/'quota');self.wire=Wire()
        from app.collection.current_schedule import schedule
        fixed=datetime.now(timezone.utc).replace(hour=14,minute=0,second=0,microsecond=0).isoformat()
        self.schedule_patch=patch('app.collection.current_schedule.schedule',side_effect=lambda at:schedule(fixed))
        self.schedule_patch.start()
        now=datetime.now(timezone.utc)
        self.window=dict(WINDOW,starts_at=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat(),
            ends_at=(now.replace(day=28)+timedelta(days=4)).replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat())
        self.scheduler=AggregateScheduler(self.service,ledger=self.q,transport=self.wire,key_loader=lambda:'CONTROLLED-dummy-key',window_loader=lambda:self.window)
    async def asyncTearDown(self):self.schedule_patch.stop();await self.scheduler.close();await self.store.close();self.service.ownership.release();self.temp.cleanup()
    async def test_running_app_without_tabs_dispatches(self):
        await self.scheduler.step()
        self.assertEqual(len(self.wire.calls),2);self.assertEqual(self.q.snapshot()['used'],23)
    async def test_inactive_supported_sport_is_checked_and_empty_response_retires_quotes(self):
        self.service.config['aggregate_sports']=['MLB','NFL']
        self.service.sink.commit(dict(type='current_aggregate',sport='MLB',body=body(),received_at=utc()),self.service.states)
        original=self.wire.request
        async def request_all(req,key):
            response=await original(req,key)
            if req['path']=='/v4/sports':
                response['body']=json.dumps([dict(key='americanfootball_nfl',active=True,has_outrights=False)]).encode()
            elif req['path']=='/v4/sports/baseball_mlb/odds':
                self.wire.used-=3
                response.update(body=b'[]',headers=quota(self.wire.used,0))
            else:response['body']=body('NFL')
            return response
        self.wire.request=request_all
        await self.scheduler.step()
        self.assertEqual([r['path'] for r in self.wire.calls],['/v4/sports','/v4/sports/baseball_mlb/odds','/v4/sports/americanfootball_nfl/odds'])
        self.assertEqual(self.q.snapshot()['used'],23)
        self.assertEqual(self.service.sink.aggregate_records['MLB'],[])
        self.assertEqual(self.scheduler.metrics['active_scope'],['NFL'])
        self.assertEqual(self.scheduler.metrics['selected_scope'],['MLB','NFL'])
        self.assertEqual(self.service.config['sports'],['MLB'])
    async def test_persisted_bootstrap_delay_keeps_scheduler_waiting(self):
        self.store.subscribers.add(asyncio.Queue(maxsize=1))
        from app.collection.current_quota import QuotaStop
        calls=0
        async def delayed_then_stop():
            nonlocal calls
            calls+=1
            if calls==1:raise QuotaStop('bootstrap_budget_delayed')
            self.scheduler.closed=True
        async def yield_only(seconds):pass
        with patch.object(self.scheduler,'step',side_effect=delayed_then_stop),patch('app.collection.current_aggregate.asyncio.sleep',side_effect=yield_only):
            await self.scheduler.run()
        self.assertEqual(calls,2)
        self.assertEqual(self.service.states['novig']['state'],'budget_delayed')
        self.assertEqual(self.wire.calls,[])
    async def test_shared_sport_scope_delivery_native_isolation_and_reopen(self):
        self.store.subscribers.add(asyncio.Queue(maxsize=1))
        cat,book=native_fixture();self.service.catalog('kalshi',cat);self.service.book('kalshi',book)
        await self.scheduler.step()
        self.assertEqual(len(self.wire.calls),2);self.assertEqual(self.wire.calls[1]['params'],PARAMS)
        self.assertIn('baseball_mlb/odds',self.wire.calls[1]['path'])
        state=self.store.snapshot();quotes=self.store.index(state)
        self.assertEqual(len(quotes),14);self.assertEqual(len(state['events']),2)
        self.assertEqual(len([e for e in state['events'] if e['league']=='MLB'][0]['groups']),3)
        aggregate=[x['quote'] for x in quotes.values() if x['quote']['venue']=='novig']
        self.assertTrue(all(q['original']['value']=='2.5000' and q['display']['supported'] for q in aggregate))
        self.assertTrue(all(not q['comparison']['eligible'] and q['age_seconds'] is not None for q in aggregate))
        self.assertTrue(all(q['calculations']['raw_difference']['eligible'] for q in aggregate))
        self.assertTrue(all(not q['comparison']['contexts']['novig+prophetx']['cue'] for q in aggregate))
        await self.scheduler.step();self.assertEqual(len(self.wire.calls),2)
        newer=AggregateScheduler(self.service,ledger=QuotaLedger(self.root/'quota'),transport=Wire(),key_loader=lambda:'CONTROLLED',window_loader=lambda:self.window)
        await newer.step();self.assertEqual(newer.transport.calls,[])
        await newer.close();self.assertEqual(self.q.snapshot()['used'],23)
    async def test_missing_reset_bootstrap_only_then_native_continues(self):
        self.store.subscribers.add(asyncio.Queue(maxsize=1));self.scheduler.window_loader=lambda:None
        with self.assertRaisesRegex(QuotaStop,'reset_window_unknown'):await self.scheduler.step()
        self.assertEqual(len(self.wire.calls),1);self.assertEqual(self.q.snapshot()['used'],20)
        cat,book=native_fixture();self.service.catalog('kalshi',cat);self.service.book('kalshi',book)
        self.assertEqual(len(self.store.index(self.store.snapshot())),2);self.assertTrue(self.service.dispatch)
    async def test_cancellation_after_dispatch_keeps_reservation(self):
        self.store.subscribers.add(asyncio.Queue(maxsize=1));await self.scheduler.step()
        # Deliberately target an independently affordable future slot in a controlled ledger.
        self.q.transact(lambda v,at:v.update(next_due_at=None))
        self.wire.hold=asyncio.Event()
        task=asyncio.create_task(self.scheduler.dispatch(dict(path='/v4/sports/baseball_mlb/odds',params=PARAMS),3))
        await asyncio.sleep(.01);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(self.q.snapshot()['reserved'],3)
        with self.assertRaisesRegex(QuotaStop,'ambiguous'):await self.scheduler.dispatch(dict(path='/v4/sports/baseball_mlb/odds',params=PARAMS),3)
    async def test_revocation_before_wire_and_persistence_failure(self):
        self.store.subscribers.add(asyncio.Queue(maxsize=1));self.q.bind_window(self.window)
        self.scheduler.key_loader=lambda:setattr(self.service,'dispatch',False) or 'CONTROLLED'
        with self.assertRaisesRegex(QuotaStop,'revoked'):await self.scheduler.step()
        self.assertEqual(self.wire.calls,[])
        self.assertEqual(self.q.snapshot()['attempts'],1)
    async def test_clock_jump_and_no_retry_after_failure(self):
        self.store.subscribers.add(asyncio.Queue(maxsize=1))
        self.scheduler.wall-=1000
        with self.assertRaisesRegex(QuotaStop,'clock_jump'):await self.scheduler.step()
        self.assertEqual(self.wire.calls,[])
    async def test_http_failure_retains_uncertainty_no_retry(self):
        self.store.subscribers.add(asyncio.Queue(maxsize=1));self.wire.error=TimeoutError('CONTROLLED-secret')
        with self.assertRaisesRegex(QuotaStop,'transport_uncertain'):await self.scheduler.step()
        self.assertEqual(len(self.wire.calls),1)
        with self.assertRaises(QuotaStop):await self.scheduler.step()
        self.assertEqual(len(self.wire.calls),1);self.assertNotIn('CONTROLLED-secret',str(self.q.snapshot()))


class AggregateAdmission(SchedulerTests):
    async def admit(self,raw,at=None):
        self.service.sink.commit(dict(type='current_aggregate',sport='MLB',body=raw,received_at=at or utc()),self.service.states)
    async def test_new_receipt_evidence_updates_revision_without_refreshing_same_price(self):
        await self.admit(body())
        before={q['id']:q for q in (x['quote'] for x in self.store.index(self.store.snapshot()).values())}
        payload=json.loads(body())
        payload[0]['bookmakers'][0]['last_update']='2026-10-03T00:01:00Z'
        updated=json.dumps(payload).encode()
        await self.admit(updated)
        after={q['id']:q for q in (x['quote'] for x in self.store.index(self.store.snapshot()).values())}
        for identity,q in after.items():
            self.assertEqual(q['revision'],before[identity]['revision']+1)
            self.assertNotEqual(q['binding']['evidence'],before[identity]['binding']['evidence'])
            self.assertEqual(q['times'],before[identity]['times'])
        await self.admit(updated)
        for x in self.store.index(self.store.snapshot()).values():
            self.assertEqual(x['quote']['revision'],after[x['quote']['id']]['revision'])
        await self.admit(body(at='2026-10-03T00:02:00Z'))
        for x in self.store.index(self.store.snapshot()).values():
            self.assertEqual(x['quote']['times']['source_at'],'2026-10-03T00:02:00Z')
    async def test_original_book_and_market_clock_meaning_survives_admission(self):
        raw=json.loads(body())
        for book in raw[0]['bookmakers']:book['last_update']='2026-10-02T23:59:00Z'
        await self.admit(json.dumps(raw).encode())
        for record in self.store.index(self.store.snapshot()).values():
            quote=record['quote']
            self.assertEqual(quote['times']['source_at'],'2026-10-03T00:00:00Z')
            self.assertIn('2026-10-02T23:59:00Z',quote['observation_time_evidence'])
            self.assertIn('2026-10-03T00:00:00Z',quote['observation_time_evidence'])
            self.assertIn('selected basis: market',quote['observation_time_evidence'])
    async def test_independent_venue_malformed_last_valid_and_atomic_native_merge(self):
        cat,book=native_fixture();self.service.catalog('kalshi',cat);self.service.book('kalshi',book)
        await self.admit(body());before=self.store.snapshot();held=self.store.create(request(self.store))
        raw=json.loads(body(price='2.6'));raw[0]['bookmakers'][1]['markets'][0]['outcomes'].pop()
        await self.admit(json.dumps(raw).encode())
        values=[x['quote'] for x in self.store.index(self.store.snapshot()).values()]
        self.assertEqual({q['original']['value'] for q in values if q['venue']=='prophetx'},{'2.0'})
        self.assertEqual({q['original']['value'] for q in values if q['venue']=='novig'},{'2.6'})
        self.assertEqual(len([q for q in values if q['venue']=='kalshi']),2)
        self.assertEqual(self.store.get(held['selection_id'])['review'],held['review'])
        seq=self.service.sink.sequence
        with self.assertRaises(ValueError):await self.admit(b'{}')
        self.assertEqual(self.service.sink.sequence,seq)
    async def test_stale_response_retirement_and_source_regression(self):
        await self.admit(body());first=self.service.sink.aggregate_receipts['MLB']
        with self.assertRaisesRegex(ValueError,'Stale'):await self.admit(body(price='3.0'),first)
        with self.assertRaisesRegex(ValueError,'regressed'):await self.admit(body(at='2026-10-02T12:00:00Z',price='3.0'))
        await self.admit(b'[]');self.assertEqual(self.store.snapshot()['events'],[])
        with self.assertRaisesRegex(ValueError,'Stale'):await self.admit(body(),first)
    async def test_single_venue_admitted_without_counterpart(self):
        await self.admit(body(books=('novig',)))
        self.assertEqual(len(self.store.index(self.store.snapshot())),6)
        self.assertEqual({x['quote']['venue'] for x in self.store.index(self.store.snapshot()).values()},{'novig'})
        self.service.states['prophetx']=dict(state='not_offered',reason_code='aggregate_offering_unobserved',reason='CONTROLLED absent',next_due_at=None)
        self.scheduler.state('budget_delayed','aggregate_budget_delayed','CONTROLLED paced')
        self.assertEqual(self.service.states['prophetx']['state'],'not_offered')


class BrowserLifecycle(unittest.IsolatedAsyncioTestCase):
    @patch('app.collection.current_aggregate.now',return_value='2026-10-07T14:00:00+00:00')
    async def test_two_tabs_one_scheduler_admin_pause_and_safe_shutdown(self,_clock):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);wire=Wire();q=QuotaLedger(root/'quota')
            def factory(s):return AggregateScheduler(s,ledger=q,transport=wire,key_loader=lambda:'CONTROLLED',window_loader=lambda:None)
            service=CurrentService(directory=root/'service',ownership=LocalOwnership(root/'owner'),worker_factory=FakeWorker,aggregate_factory=factory)
            async with TestClient(TestServer(create_app(owner=owner(),sessions={},current_provider=service))) as c:
                a=await c.get('/api/current/updates');b=await c.get('/api/current/updates')
                await a.content.readline();await b.content.readline();await asyncio.sleep(1.1)
                for i in range(3):await c.get('/api/current');await c.get('/');await c.get('/admin')
                self.assertEqual(len(wire.calls),1);self.assertEqual(service.status()['odds_api_requests'],1)
                origin=str(c.make_url('/')).rstrip('/')
                result=await c.post('/api/admin/current',json=dict(action='pause',source='the_odds_api'),headers={'Origin':origin})
                self.assertEqual(result.status,200);self.assertFalse(service.workers['kalshi'].closed);self.assertTrue(wire.closed)
                a.close();b.close()
            self.assertTrue(service.cleanup_complete);self.assertIsNone(service.ownership.file)

class RestartScheduler(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=SchedulerTests.asyncSetUp
    asyncTearDown=SchedulerTests.asyncTearDown
    async def test_evidenced_restart_holds_paid_until_free_receipt(self):
        at=[datetime.now(timezone.utc)-timedelta(days=1)];mono=[100.0]
        boot=[dict(id='CONTROLLED-old',started_at=(at[0]-timedelta(seconds=100)).isoformat(),uptime=100)]
        self.q=QuotaLedger(self.root/'restart',clock=lambda:at[0].isoformat(),monotonic=lambda:mono[0],boot_loader=lambda:deepcopy(boot[0]))
        self.scheduler.ledger=self.q;self.q.bind_window(self.window)
        a=self.q.reserve(self.service.ownership,'c',{},0,bootstrap=True);self.q.dispatched(a,self.service.ownership);self.q.reconcile(a,quota(20))
        at[0]=datetime.now(timezone.utc);mono[0]=60;boot[0]=dict(id='CONTROLLED-new',started_at=(at[0]-timedelta(seconds=60)).isoformat(),uptime=60)
        self.store.subscribers.add(asyncio.Queue(maxsize=1));self.wire.hold=asyncio.Event()
        task=asyncio.create_task(self.scheduler.step())
        for _ in range(50):
            if self.wire.calls:break
            await asyncio.sleep(.005)
        self.assertEqual(len(self.wire.calls),1);self.assertEqual(self.wire.calls[0]['path'],'/v4/sports')
        self.assertEqual(self.q.snapshot()['accounting_epoch']['state'],'awaiting_bootstrap')
        with self.assertRaisesRegex(QuotaStop,'refresh_required'):self.q.reserve(self.service.ownership,'c',{},3)
        self.wire.hold.set();await task
        self.assertEqual(len(self.wire.calls),2);self.assertEqual(self.scheduler.metrics['batches'],1)
        self.assertEqual(self.q.snapshot()['accounting_epoch']['state'],'current')
        self.assertEqual(self.q.snapshot()['used'],23);self.assertEqual(self.q.snapshot()['reserved'],0)
        await self.scheduler.step();self.assertEqual(len(self.wire.calls),2)
    async def test_failed_cleanup_never_loads_credentials_or_transport(self):
        self.store.subscribers.add(asyncio.Queue(maxsize=1));self.service.cleanup_errors=['CONTROLLED-unclosed-client']
        with patch.object(self.scheduler,'key_loader',side_effect=AssertionError('credentials')):
            with self.assertRaisesRegex(QuotaStop,'cleanup'):await self.scheduler.step()
        self.assertEqual(self.wire.calls,[]);self.assertEqual(self.q.snapshot()['attempts'],0)

class PinnacleDelivery(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=SchedulerTests.asyncSetUp
    asyncTearDown=SchedulerTests.asyncTearDown
    async def test_reference_refresh_is_atomic_and_preserves_comparison_prices(self):
        self.wire.paid_body=body(books=('novig','prophetx','pinnacle'),at=utc())
        scheduler=self.scheduler
        await scheduler.step()
        await scheduler.refresh(['MLB'],'CONTROLLED-pinnacle-one')
        quotes=[q for x in self.store.index(self.store.snapshot()).values() for q in [x['quote']]]
        self.assertTrue(any(q['calculations']['ev']['eligible'] for q in quotes))
        self.assertTrue(all(q['venue']!='pinnacle' for q in quotes))
        prior={q['id']:q['revision'] for q in quotes}
        self.wire.paid_body=body(books=('novig','prophetx','pinnacle'),at=utc(),price='2.7')
        await scheduler.refresh(['MLB'],'CONTROLLED-pinnacle-two')
        quotes=[x['quote'] for x in self.store.index(self.store.snapshot()).values()]
        self.assertTrue(all(q['revision']>prior[q['id']] for q in quotes))
        self.assertTrue(any(q['calculations']['ev']['eligible'] for q in quotes))

        prior={q['id']:(q['revision'],q['original']) for q in quotes}
        response=json.loads(self.wire.paid_body)
        for book in response[0]['bookmakers']:
            if book['key']=='pinnacle':
                for market in book['markets']:market['outcomes'][0]['price']='3.0'
        self.wire.paid_body=json.dumps(response).encode()
        await scheduler.refresh(['MLB'],'CONTROLLED-pinnacle-three')
        quotes=[x['quote'] for x in self.store.index(self.store.snapshot()).values()]
        self.assertTrue(all(q['original']==prior[q['id']][1] and q['revision']>prior[q['id']][0] for q in quotes))
