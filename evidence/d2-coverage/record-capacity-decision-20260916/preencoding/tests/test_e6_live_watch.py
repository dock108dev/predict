import asyncio
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.dashboard.e6_live import Owner,package,verify_all,validate_saved,configuration
from app.dashboard import e6_real
from tests.test_e6_transport import IntegrationTests

class LiveLoop(IntegrationTests):
    async def test_controlled_recovery_and_manual_stop(self):
        self.s['reference_enabled']=False;self.s['duration']=8;self.s['prediction']['connections']=3
        self.s['discovery_cadence']=8;self.s['stale_seconds']=5
        o=Owner(self.tmp.name,spec_factory=lambda:deepcopy(self.s),endpoints=self.endpoints)
        await o.start();self.owner=o.session
        with self.assertRaises(ValueError):await o.start()
        for _ in range(500):
            if o.session.producers['kalshi'].budget.connections==2 and o.session.health['kalshi']=='connected':break
            await asyncio.sleep(.01)
        await o.interrupt()
        self.assertEqual(o.session.health['kalshi'],'disconnected')
        with self.assertRaises(ValueError):await o.interrupt()
        for _ in range(500):
            if o.session.producers['kalshi'].budget.connections==3 and o.session.health['kalshi']=='connected':break
            await asyncio.sleep(.01)
        self.assertEqual(o.session.producers['kalshi'].budget.connections,3)
        self.assertEqual(o.session.health['kalshi'],'connected')
        await o.stop();self.assertEqual(o.session.state,'stopping');await o.finalizer
        self.assertIsNone(o.error)
        self.assertEqual(o.session.reason,'manual_stop');self.assertEqual(o.session.delivered,o.session.persisted)
        self.assertTrue(all(p.stream.closed for p in o.session.producers.values()))
        restarted=Owner(self.tmp.name)
        self.assertIsNone(restarted.session);self.assertFalse(restarted.active())
        with self.assertRaises(ValueError):await restarted.start()
        folder=Path(self.tmp.name)/o.session.sid
        with patch('app.dashboard.e6_real.validate_mapping'),patch('app.dashboard.e6_live.package',return_value={'exact':True}):
            self.assertEqual(validate_saved(folder),{'exact':True})
            with (folder/'observations.jsonl').open('ab') as f:f.write(b' ')
            with self.assertRaises(ValueError):validate_saved(folder)

class HttpOwnership(unittest.IsolatedAsyncioTestCase):
    async def test_browser_disconnect_and_idle_startup(self):
        from aiohttp.test_utils import TestServer
        from aiohttp import ClientSession
        from app.dashboard.e6_live import create_app
        with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credential lookup')):
            o=Owner(tmp)
            server=TestServer(create_app(owner=o));await server.start_server()
            try:
                url=str(server.make_url('/')).rstrip('/')
                async with ClientSession() as browser:
                    response=await browser.get(url+'/api/status');self.assertEqual((await response.json())['state'],'idle')
                    self.assertEqual((await browser.post(url+'/api/start')).status,403)
                # Server and session owner outlive a browser's HTTP connection.
                async with ClientSession() as reopened:
                    response=await reopened.get(url+'/api/status');self.assertEqual((await response.json())['state'],'idle')
                self.assertIsNone(o.session)
            finally:await server.close()

class Projection(unittest.TestCase):
    def test_current_health_and_quiet_freshness(self):
        saved=e6_real.reopen(e6_real.ROOT/e6_real.JOURNAL);rows=saved['rows'];spec=rows[0]['spec']
        rows=rows[:next(i for i,r in enumerate(rows) if r['type']=='source_health' and r['state']=='disconnected')]
        p=package(rows,spec,'chain',live=True,now=rows[-1]['observed_at'])
        self.assertTrue(all(c['book'] for c in p['timeline'][0]['cards']))
        now=(datetime.fromisoformat(rows[-1]['observed_at'])+timedelta(seconds=31)).isoformat()
        p=package(rows,spec,'chain',live=True,now=now)
        for c in p['timeline'][0]['cards']:
            self.assertEqual(c['connection'],'connected');self.assertIsNone(c['book']);self.assertTrue(c['receipt_stale'])
        rows.append(dict(type='source_health',source='kalshi',state='disconnected',observed_at=rows[-1]['observed_at'],ingress_id='disconnect'))
        p=package(rows,spec,'chain',live=True,now=rows[-1]['observed_at'])
        self.assertIsNone(p['timeline'][0]['cards'][0]['book']);self.assertIsNotNone(p['timeline'][0]['cards'][1]['book'])
    def test_idle_no_credentials_or_network(self):
        with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credential read')),patch('aiohttp.ClientSession',side_effect=AssertionError('provider request')):
            o=Owner(tmp);self.assertEqual(o.status()['state'],'idle');self.assertIsNone(o.session)
