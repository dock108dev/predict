import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
from app.dashboard.multi_game_server import create_app
from app.dashboard import session_history
from tests.segmented_collector_fixture import Fixture


class Product(unittest.IsolatedAsyncioTestCase):
    async def test_shared_collector_current_details_stop_saved_repeatable_both_formats(self):
        for segmented in (False,True):
            with self.subTest(segmented=segmented),tempfile.TemporaryDirectory() as t,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials forbidden')):
                f=Fixture();o=await f.start(t,product_mode=True,segmented=segmented)
                c=TestClient(TestServer(create_app(owner=o,sessions={})));await c.start_server()
                try:
                    async def get(path):
                        r=await c.get(path);data=await r.json();self.assertEqual(r.status,200,data);return data
                    d=await get('/api/dashboard');self.assertTrue(d['live']);self.assertTrue(d['rows'],d)
                    old=d['rows'][0];sid=d['capture'];before=d['durable_cursor']
                    await f.send(f.active()[0]);updated=await get('/api/dashboard')
                    self.assertNotEqual(before,updated['durable_cursor']);self.assertEqual([r['id'] for r in d['rows']],[r['id'] for r in updated['rows']])
                    from urllib.parse import urlencode
                    query=urlencode(dict(session=old['session'],hash=sid,cutoff=old['cutoff'],contract=old['legs'][0]['id']))
                    detail=await get('/api/calculate?'+query);self.assertTrue(detail['frozen_cutoff'])
                    with self.assertRaises(ValueError):await o.start()
                    await o.stop();saving=await get('/api/dashboard');self.assertEqual(saving['state'],'saving');self.assertFalse(saving['live']);self.assertFalse(saving['status']['start_available'])
                    await o.finalizer;self.assertIsNone(o.error)
                    admitted=o.session.delivered;self.assertFalse(o.session.emit('session',dict(type='after_stop_probe')));self.assertEqual(admitted,o.session.delivered)
                    saved=await get('/api/dashboard?capture='+sid);self.assertEqual(saved['state'],'saved');self.assertFalse(saved['live'])
                    reopened=await get('/api/calculate?'+query)
                    self.assertEqual(detail['candidates'],reopened['candidates'])
                    self.assertFalse((Path(t)/'pilot/attempt.json').exists())
                    self.assertTrue(o.status()['start_available'])
                    second=await o.start(duration=20);self.assertNotEqual(sid,second)
                    loading=await get('/api/dashboard');self.assertEqual(loading['capture'],second);self.assertEqual(loading['rows'],[])
                    await o.stop();await o.finalizer
                    # Restarting the owner leaves it idle and all saved inputs unchanged.
                    from app.dashboard.coverage_owner import CoverageOwner
                    restarted=CoverageOwner(Path(t)/'unused-saved',pilot_output=Path(t)/'pilot',endpoints=f.endpoints,product_mode=True,spec_factory=o.spec_factory,mock_segmented=segmented)
                    self.assertFalse(restarted.active());self.assertIsNone(restarted.session)
                    path=Path(t)/'pilot'/sid
                    self.assertEqual(session_history.load(path)['state'],'saved')
                    with (path/'report.json').open('a') as out:out.write(' ')
                    with self.assertRaises(ValueError):session_history.load(path)
                finally:await c.close();await f.close()
