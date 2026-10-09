import asyncio
from copy import deepcopy
from decimal import Decimal
import unittest
from unittest.mock import Mock, AsyncMock, patch
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer
from app.dashboard.current_state import CurrentStore, CurrentStateProvider, SelectionError, CURRENT_KEY
from app.dashboard.multi_game_server import create_app
from tests.current_fixture import fixture, InjectedTestProvider


def owner():
    o=Mock();o.session=None;o.active.return_value=False;o.saved.return_value=[];o.status.return_value={'active':False};o.close=AsyncMock();return o


def request(store,client='one',qid=None):
    r=store.snapshot();q=next(iter(store.index(r).values()))['quote'] if qid is None else store.index(r)[qid]['quote']
    return dict(schema=r['schema'],runtime_id=r['runtime_id'],state_revision=r['state_revision'],quote_id=q['id'],quote_revision=q['revision'],client_id=client)


class Leases(unittest.TestCase):
    def setUp(self):self.now=10;self.store=CurrentStore(InjectedTestProvider(),monotonic=lambda:self.now)
    def error(self,status,code,call):
        with self.assertRaises(SelectionError) as ctx:call()
        self.assertEqual(ctx.exception.status,status);self.assertEqual(ctx.exception.body['error'],code)
    def test_encoded_snapshot_does_not_clone_or_expose_mutable_state(self):
        from app.dashboard.current_contract import packed
        import json
        expected=packed(self.store.snapshot())
        with patch.object(self.store,'snapshot',side_effect=AssertionError('No full-board response copy')):
            encoded=self.store.encoded_snapshot()
        self.assertEqual(encoded,expected)
        decoded=json.loads(encoded);decoded['events'].clear()
        self.assertTrue(self.store.snapshot()['events'])

    def test_atomic_revision_validation_no_substitution(self):
        advertised=request(self.store);r=fixture(2);self.store.commit(r)
        self.error(409,'selection_changed',lambda:self.store.create(advertised));self.assertEqual(len(self.store.leases),0)
    def test_held_inputs_newer_get_does_not_mutate_failed_adoption(self):
        held=self.store.create(request(self.store));frozen=deepcopy(held['review']);old=request(self.store)
        self.store.commit(fixture(2));latest=self.store.get(held['selection_id']);self.assertEqual(latest['status'],'newer_available');self.assertEqual(latest['review'],frozen)
        self.error(409,'selection_changed',lambda:self.store.create(old));self.assertEqual(self.store.get(held['selection_id'])['review'],frozen)
        adopted=self.store.create(request(self.store));self.assertEqual(adopted['review']['quote']['revision'],2)
        self.error(410,'selection_expired',lambda:self.store.get(held['selection_id']))
    def test_ttl_release_restart_and_new_store(self):
        held=self.store.create(request(self.store));self.now+=299;self.assertGreater(self.store.get(held['selection_id'])['ttl_remaining'],0);self.now+=1
        self.error(410,'selection_expired',lambda:self.store.get(held['selection_id']))
        held=self.store.create(request(self.store));self.store.release(held['selection_id']);self.error(410,'selection_expired',lambda:self.store.get(held['selection_id']))
        held=self.store.create(request(self.store));r=fixture();r['runtime_id']='syn:restart';self.store.commit(r)
        self.error(410,'selection_expired',lambda:self.store.get(held['selection_id']))
        self.error(410,'selection_expired',lambda:CurrentStore(InjectedTestProvider()).get(held['selection_id']))
    def test_capacity_eight_no_eviction_and_one_per_client(self):
        leases=[self.store.create(request(self.store,str(n))) for n in range(8)]
        self.error(429,'selection_capacity',lambda:self.store.create(request(self.store,'ninth')))
        for lease in leases:self.assertEqual(self.store.get(lease['selection_id'])['status'],'held')
        new=self.store.create(request(self.store,'0'));self.assertEqual(len(self.store.leases),8)
        self.error(410,'selection_expired',lambda:self.store.get(leases[0]['selection_id']))
        self.store.release(new['selection_id']);self.store.create(request(self.store,'ninth'));self.assertEqual(len(self.store.leases),8)
    def test_byte_capacity_failed_replacement_preserves_previous(self):
        held=self.store.create(request(self.store));others=[self.store.create(request(self.store,str(n))) for n in range(7)]
        for lease in self.store.leases.values():lease['bytes']=400000
        self.error(429,'selection_capacity',lambda:self.store.create(request(self.store)))
        self.assertEqual(self.store.get(held['selection_id'])['status'],'held')
    def test_duplicate_out_of_order_runtime_and_heartbeats(self):
        self.assertFalse(self.store.commit(fixture()));self.store.commit(fixture(2));self.assertFalse(self.store.commit(fixture()))
        r=fixture(2);r['state_revision']=3;r['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']['original']['value']='.4'
        with self.assertRaises(ValueError):self.store.commit(r)
        self.assertEqual(self.store.snapshot()['state_revision'],2)
        r=fixture(2);r['state_revision']=3;self.store.commit(r);self.assertEqual(self.store.snapshot()['state_revision'],3)
        q=next(iter(self.store.index(self.store.snapshot()).values()))['quote'];self.assertEqual(q['revision'],2);self.assertEqual(q['age_seconds'],8)
    def test_source_time_repeat_and_malformed_commit_atomic(self):
        r=fixture();r['state_revision']=2;r['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']['times']['source_at']=r['clock_at']
        with self.assertRaises(ValueError):self.store.commit(r)
        self.assertEqual(self.store.snapshot()['state_revision'],1)
    def test_removed_quote_review_and_no_adoption(self):
        held=self.store.create(request(self.store));r=fixture();r['state_revision']=2;r['events']=[];self.store.commit(r)
        self.assertEqual(self.store.get(held['selection_id'])['status'],'newer_available');self.assertIsNone(self.store.get(held['selection_id'])['latest'])
    def test_closed_expires(self):
        held=self.store.create(request(self.store));asyncio.run(self.store.close());self.error(410,'selection_expired',lambda:self.store.get(held['selection_id']))


class Routes(AioHTTPTestCase):
    async def get_application(self):
        self.owner=owner();return create_app(owner=self.owner,sessions={},current_provider=InjectedTestProvider())
    def origin(self):return str(self.client.make_url('/')).rstrip('/')
    async def post(self,path,body):return await self.client.post(path,json=body,headers={'Origin':self.origin()})
    async def test_root_assets_admin_preview_and_current(self):
        for p in ['/','/admin','/admin/retained','/preview/u0','/current/assets/board.js','/current/assets/board.css','/current/assets/current.js']:
            r=await self.client.get(p);self.assertEqual(r.status,200,p);self.assertIn('Content-Security-Policy',r.headers)
        html=await (await self.client.get('/')).text();self.assertIn('/current/assets/current.js',html)
        for word in ['Start scan','Refresh','saved-scan','preview-tools','duration']:self.assertNotIn(word,html)
        r=await (await self.client.get('/api/current')).json();self.assertEqual(r['mode'],'synthetic');self.owner.start.assert_not_called()
        self.assertEqual((await self.client.get('/current/assets/../current_state.py')).status,404)
    async def test_selection_routes_what_if_release_and_security(self):
        store=self.app[CURRENT_KEY];r=await self.post('/api/selections',request(store));self.assertEqual(r.status,201);held=await r.json();sid=held['selection_id']
        a=dict(probability='.48',entry_cost='0',win_cost='0',loss_cost='0',quantity='1',acknowledge_conditional=True)
        r=await self.post('/api/selections/'+sid+'/what-if',a);self.assertEqual(r.status,200);self.assertEqual(Decimal((await r.json())['value']),0)
        self.assertEqual((await self.post('/api/selections/'+sid+'/what-if',{})).status,422)
        self.assertEqual((await self.post('/api/selections/'+sid+'/release',{})).status,200)
        self.assertEqual((await self.client.get('/api/selections/'+sid)).status,410)
        for h in [{'Host':'evil.test'},{'Origin':'http://evil.test'},{'Sec-Fetch-Site':'same-site'}]:
            self.assertEqual((await self.client.get('/api/current',headers=h)).status,403)
        self.assertEqual((await self.client.post('/api/selections',json=request(store))).status,403)
        self.assertEqual((await self.client.post('/api/selections',data='{"schema":1,"schema":2}',headers={'Origin':self.origin(),'Content-Type':'application/json'})).status,422)
        self.assertEqual((await self.client.post('/api/selections',data='x'*4097,headers={'Origin':self.origin(),'Content-Type':'application/json'})).status,413)
        self.assertEqual((await self.client.get('/api/current?league=NFL')).status,422)
    async def test_update_multiple_clients_coalescing_and_reconnect(self):
        store=self.app[CURRENT_KEY]
        a=await self.client.get('/api/current/updates');b=await self.client.get('/api/current/updates')
        for response in (a,b):self.assertIn(b'"state_revision":1',await response.content.readline());await response.content.readline()
        store.commit(fixture(2))
        for response in (a,b):self.assertIn(b'"state_revision":2',await asyncio.wait_for(response.content.readline(),2));await response.content.readline()
        a.close();b.close()
        c=await self.client.get('/api/current/updates');self.assertIn(b'"state_revision":2',await c.content.readline());c.close()
        queue=asyncio.Queue(maxsize=1);store.subscribers.add(queue)
        for n in range(3,10):r=fixture(2);r['state_revision']=n;store.commit(r)
        self.assertEqual(queue.qsize(),1);self.assertEqual(queue.get_nowait()['state_revision'],9);store.subscribers.discard(queue)
        self.owner.start.assert_not_called()
    async def test_stream_head_capacity(self):
        store=self.app[CURRENT_KEY]
        response=await self.client.head('/api/current/updates');self.assertEqual(response.status,200);self.assertEqual(len(store.subscribers),0)
        queues=[asyncio.Queue(maxsize=1) for _ in range(8)];store.subscribers.update(queues)
        self.assertEqual((await self.client.get('/api/current/updates')).status,429)
        store.subscribers.clear()
    async def test_default_provider_never_reads_archives(self):
        o=owner()
        with patch('app.dashboard.multi_game_server.load_sessions',side_effect=AssertionError('archive read')):
            async with TestClient(TestServer(create_app(owner=o))) as c:
                r=await (await c.get('/api/current')).json();self.assertEqual(r['mode'],'current');self.assertEqual(r['events'],[]);self.assertEqual(r['state'],'unavailable')
                self.assertEqual((await c.get('/')).status,200);o.start.assert_not_called()

class AgeAndBoundaries(unittest.TestCase):
    def test_source_age_ttl_and_heartbeat_have_separate_clocks(self):
        now=[0];raw=fixture()
        for e in raw['events']:
            for g in e['groups']:
                for o in g['outcomes']:
                    for q in o['quotes'].values():q['freshness_policy']['maximum_age_seconds']=20
        store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:now[0]);held=store.create(request(store));q=held['review']['quote'];self.assertTrue(q['comparison']['eligible'])
        now[0]=13;s=store.snapshot();latest=store.index(s)[q['id']]['quote'];self.assertEqual(latest['age_seconds'],21);self.assertTrue(latest['stale']);self.assertFalse(latest['comparison']['eligible']);self.assertEqual(latest['revision'],q['revision'])
        self.assertEqual(latest['times'],q['times']);self.assertEqual(store.get(held['selection_id'])['review'],held['review']);self.assertEqual(store.get(held['selection_id'])['ttl_remaining'],287)
        self.assertFalse(latest['calculations']['raw_difference']['eligible'])
    def test_dependent_new_unavailable_does_not_replace_held_review(self):
        store=CurrentStore(InjectedTestProvider());held=store.create(request(store));raw=fixture();raw['state_revision']=2
        q=raw['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi'];q['state']='unavailable';q['revision']=2;store.commit(raw)
        newer=store.get(held['selection_id']);self.assertEqual(newer['latest']['state'],'unavailable')
        with self.assertRaises(SelectionError) as error:store.create(request(store))
        self.assertEqual(error.exception.status,409);self.assertEqual(store.get(held['selection_id'])['review'],held['review'])

class SlowConsumer(AioHTTPTestCase):
    async def get_application(self):return create_app(owner=owner(),sessions={},current_provider=InjectedTestProvider())
    async def test_slow_write_deadline_releases_slot_and_head_does_not_subscribe(self):
        from aiohttp import web
        async def blocked_write(response,data):await asyncio.Event().wait()
        with patch('app.dashboard.current_state.STREAM_WRITE_SECONDS',.01),patch.object(web.StreamResponse,'write',blocked_write):
            response=await self.client.get('/api/current/updates')
            await asyncio.wait_for(response.read(),1)
        self.assertEqual(len(self.app[CURRENT_KEY].subscribers),0)
        self.assertEqual((await self.client.get('/api/current')).status,200)
