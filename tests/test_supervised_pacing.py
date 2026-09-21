import asyncio
import time
import unittest
from types import SimpleNamespace
from aiohttp import web
from aiohttp.test_utils import TestServer
from app.collection.continuous import REST
from app.collection.prediction_producer import PredictionBudget
from app.collection.odds_http import BudgetStop
from app.collection.supervised import PROFILE

TIMESTAMPS=[]
RETRY_EVENTS=[]
class Pacing(unittest.IsolatedAsyncioTestCase):
    async def test_timing_retry_stop_deadline(self):
        async def handler(req):
            n=1+sum(x['path']==req.path for x in TIMESTAMPS)
            status=429 if req.match_info['kind'] in ('retry','cancel-retry','deadline-retry') and n==1 else 200
            TIMESTAMPS.append(dict(venue=req.match_info['venue'],path=req.path,at=time.monotonic(),status=status))
            return web.json_response({},status=status)
        app=web.Application();app.router.add_get('/{venue}/{kind}',handler)
        server=TestServer(app);await server.start_server();url=str(server.make_url('/')).rstrip('/')
        limits=dict(discovery_requests=128,dollars_per_discovery_request='0',dollar_cap_per_source='0',frame_bytes=1048576,session_bytes=64*1048576)
        clients=[]
        try:
            for venue in ('kalshi','polymarket_us'):
                receipts=[];entered=asyncio.Event()
                c=REST(url,limits,receipts.append,5,PredictionBudget(limits));clients.append(c)
                c.pacing_venue=venue
                c.session=SimpleNamespace(profile=PROFILE,started_monotonic=time.monotonic(),spec={'duration':25},stop_event=asyncio.Event(),request_stop=lambda r:None)
                if venue=='kalshi':c.account_limits({'read':{'refill_rate':10,'bucket_capacity':100}},{'default_cost':7,'endpoint_costs':[]})
                original_wait=c.bounded_wait
                async def observed_wait(delay):
                    # These clients pace at .7/.5; only the actual retry branch
                    # requests 1 second. Receipt comes from transport completion.
                    if delay==1:
                        self.assertEqual(receipts[-1]['status'],429)
                        self.assertTrue(receipts[-1]['complete'])
                        RETRY_EVENTS.append(dict(venue=venue,path=receipts[-1]['path'],status=429,entered_at=time.monotonic()))
                        entered.set()
                    await original_wait(delay)
                c.bounded_wait=observed_wait
                await c.get(url+'/'+venue+'/ok');await c.get(url+'/'+venue+'/ok');await c.get(url+'/'+venue+'/retry')
                ts=[x['at'] for x in TIMESTAMPS if x['venue']==venue]
                interval=.7 if venue=='kalshi' else .5
                self.assertGreaterEqual(min(b-a for a,b in zip(ts,ts[1:])),interval-.01)
                self.assertGreaterEqual(ts[-1]-ts[-2],1+interval-.01)
                count=len(TIMESTAMPS);task=asyncio.create_task(c.get(url+'/'+venue+'/cancel'))
                await asyncio.sleep(.05);c.session.stop_event.set()
                with self.assertRaises(asyncio.CancelledError):await task
                self.assertEqual(len(TIMESTAMPS),count)
                c.session.stop_event.clear();entered.clear()
                task=asyncio.create_task(c.get(url+'/'+venue+'/cancel-retry'))
                await asyncio.wait_for(entered.wait(),3)
                self.assertEqual(receipts[-1]['path'],'/'+venue+'/cancel-retry')
                self.assertFalse(task.done())
                RETRY_EVENTS[-1]['stop_at']=time.monotonic();c.session.stop_event.set()
                with self.assertRaises(asyncio.CancelledError):await task
                RETRY_EVENTS[-1]['cancelled_at']=time.monotonic()
                self.assertEqual(len(TIMESTAMPS),count+1)
                count=len(TIMESTAMPS)
                c.session.stop_event.clear();c.session.spec['duration']=time.monotonic()-c.session.started_monotonic+.05
                with self.assertRaisesRegex(BudgetStop,'deadline'):await c.get(url+'/'+venue+'/deadline')
                self.assertEqual(len(TIMESTAMPS),count)
                c.session.spec['duration']=time.monotonic()-c.session.started_monotonic+interval+.2
                entered.clear();task=asyncio.create_task(c.get(url+'/'+venue+'/deadline-retry'))
                await asyncio.wait_for(entered.wait(),3)
                self.assertEqual(receipts[-1]['path'],'/'+venue+'/deadline-retry')
                with self.assertRaisesRegex(BudgetStop,'deadline'):await task
                RETRY_EVENTS[-1]['deadline_at']=time.monotonic()
                self.assertEqual(len(TIMESTAMPS),count+1)
        finally:
            for c in clients:await c.aclose()
            await server.close()
