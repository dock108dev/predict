"""Captured bytes have no current financial authority; Stop owns transport."""
import asyncio
import json
import unittest
import weakref
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from app.dashboard.current_state import CurrentStore, CURRENT_KEY, SelectionError
from app.dashboard.current_response import CurrentResponse
from app.dashboard.current_encoded import EncodedDelivery
from app.dashboard.current_contract import snapshot_inputs, packed
from tests.current_fixture import InjectedTestProvider, fixture
from tests.test_current_state import owner
from app.dashboard.multi_game_server import create_app


class Delivery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tick=[0];self.store=CurrentStore(InjectedTestProvider(),monotonic=lambda:self.tick[0])
    async def asyncTearDown(self):await self.store.close()

    async def test_ordinary_update_and_expiry_finish_exact_immutable_envelope(self):
        for cause in ('update','expiry'):
            pool=self.store.encoded_bodies;epoch=self.store._calculation_epoch
            value={'rows':['é'*40000]*4,'runtime_id':self.store._state['runtime_id']}
            body=pool.encode(value)
            reader=EncodedDelivery(body,{'request_generation':'9'},**self.store.delivery_guards(epoch))
            parts=[]
            class Writer:
                async def write(inner,block):
                    parts.append(block)
                    if len(parts)==1:
                        if cause=='update':
                            raw=snapshot_inputs(self.store._state);raw['state_revision']+=1;self.store.commit(raw)
                        else:self.tick[0]=901;self.store.economic_valid(epoch)
            await reader.write(Writer())
            decoded=json.loads(b''.join(parts));self.assertEqual(decoded,dict(value,request_generation='9'))
            self.assertFalse(self.store.economic_valid(epoch));self.assertFalse(pool.readers);self.assertTrue(body.closed)

    async def test_supersession_before_headers_is_complete_structured_refusal(self):
        app=create_app(owner=owner(),sessions={},current_provider=InjectedTestProvider())
        @web.middleware
        async def supersede(request,handler):
            response=await handler(request)
            if request.path=='/api/current':
                store=app[CURRENT_KEY];raw=snapshot_inputs(store._state);raw['state_revision']+=1;store.commit(raw)
            return response
        app.middlewares.append(supersede)
        async with TestClient(TestServer(app)) as client:
            response=await client.get('/api/current');body=await response.read()
            self.assertEqual(response.status,409);self.assertEqual(len(body),response.content_length)
            self.assertEqual(json.loads(body)['error'],'capture_superseded')
            self.assertIsNotNone(response.headers.get('X-Predict-Epoch'))
            self.assertFalse(app[CURRENT_KEY].encoded_bodies.readers)

    async def test_stop_during_captured_delivery_releases_work(self):
        pool=self.store.encoded_bodies;body=pool.encode({'rows':['x'*40000]*8})
        reader=pool.payload(body,adopt=True,**self.store.delivery_guards(self.store._calculation_epoch))
        parts=[]
        class Writer:
            async def write(inner,block):
                parts.append(block);await self.store.close()
        with self.assertRaises((ConnectionResetError,ValueError)):await reader.write(Writer())
        self.assertEqual(len(parts),1);self.assertFalse(pool.readers);self.assertFalse(pool.owners)

    async def test_cache_does_not_retain_prior_graph_or_close_active_reader(self):
        class Marker:pass
        marker=Marker();ref=weakref.ref(marker);self.store._state['_retention_probe']=marker
        body=self.store.comparison_body(('policy',),lambda:self.store.encoded_bodies.encode({'large':['x'*20000]*8}))
        reader=self.store.encoded_bodies.payload(body)
        del marker
        self.store._state=dict(self.store._state)
        self.store._state.pop('_retention_probe')
        self.assertIsNone(ref(),'cache should own sealed bytes and scalar identity only')
        raw=snapshot_inputs(self.store._state);raw['state_revision']+=1;self.store.commit(raw)
        self.assertIsNone(self.store._comparison_body_cache)
        self.assertFalse(body.closed,'active reader retains its immutable bytes')
        class Writer:
            async def write(inner,block):pass
        await reader.write(Writer());self.assertTrue(body.closed)
        self.assertEqual(self.store.encoded_bodies.metrics['created'],self.store.encoded_bodies.metrics['released'])

    async def test_repeated_admission_delivery_and_disconnect_has_finite_owners(self):
        for i in range(12):
            reader=self.store.encoded_transport_snapshot()
            raw=snapshot_inputs(self.store._state);raw['state_revision']+=1;self.store.commit(raw)
            class Writer:
                async def write(inner,block):raise ConnectionResetError('disconnected client')
            with self.assertRaises(ConnectionResetError):await reader.write(Writer())
            self.assertFalse(self.store.encoded_bodies.readers);self.assertFalse(self.store.encoded_bodies.owners)

    async def test_selected_game_read_preserves_original_financial_and_clock_identity(self):
        state=self.store._state;event=state['events'][0]
        reader=self.store.encoded_transport_snapshot(league=event['league'],search=event['title'])
        value=json.loads(await reader.as_bytes());reader.release()
        self.assertEqual(value['events'],[event]);self.assertEqual(value['clock_at'],state['clock_at'])
        self.assertEqual(value['runtime_id'],state['runtime_id']);self.assertEqual(value['estimate_policy'],state['estimate_policy'])
        self.assertEqual(value['state_revision'],state['state_revision'])
        empty=self.store.encoded_transport_snapshot(search='not an observed game')
        self.assertEqual(json.loads(await empty.as_bytes())['events'],[]);empty.release()
        self.assertEqual(self.store._state,state,'read scope cannot admit or drop source inputs')
