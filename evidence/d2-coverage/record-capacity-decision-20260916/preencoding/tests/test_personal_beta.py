import asyncio,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
from tests.personal_beta_mock import owner,verify_local_replay
from app.dashboard.multi_game import MultiOwner,configuration
from app.dashboard.multi_game_server import create_app

class PersonalBeta(unittest.IsolatedAsyncioTestCase):
    async def test_two_starts_stop_saved_switch_and_restart(self):
        with patch('app.collection.native_replay.verify_native_saved',verify_local_replay),tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials forbidden')):
            out=Path(tmp);(out/'attempt.json').write_text('historical marker')
            o=owner(out);client=TestClient(TestServer(create_app(owner=o)))
            await client.start_server()
            try:
                origin=str(client.make_url('/')).rstrip('/')
                async def get(path):return await(await client.get(path)).json()
                async def start(n=2,duration=5):return await client.post('/api/start',json=dict(max_games=n,duration=duration),headers={'Origin':origin})
                baseline=await get('/api/dashboard');self.assertFalse(baseline['live'])
                for n in (0,7):self.assertEqual((await start(n)).status,422)
                self.assertEqual((await start(duration=181)).status,422)
                ids=[]
                for n in (2,3):
                    r=await start(n);self.assertEqual(r.status,200);ids.append((await r.json())['session'])
                    self.assertEqual((await start()).status,422)
                    waiting=await get('/api/dashboard');self.assertFalse(waiting['live']);self.assertTrue(waiting['status']['active'])
                    await asyncio.sleep(1)
                    live=await get('/api/dashboard');self.assertTrue(live['live']);self.assertEqual(live['coverage']['selected'],n)
                    await client.post('/api/stop',json={},headers={'Origin':origin});await o.finalizer
                    self.assertIsNone(o.error);self.assertEqual(o.session.reason,'manual_stop');self.assertTrue(o.status()['start_available'])
                self.assertNotEqual(*ids)
                for sid,n in zip(ids,(2,3)):
                    result=await get('/api/dashboard?capture='+sid);self.assertFalse(result['live']);self.assertEqual(result['coverage']['selected'],n)
                    self.assertEqual(len(result['rows']),n*3);self.assertTrue((out/sid/'run-record.json').exists())
                self.assertEqual((out/'attempt.json').read_text(),'historical marker')
                restarted=owner(out);self.assertFalse(restarted.active());self.assertTrue(restarted.status()['start_available']);self.assertEqual(len(restarted.saved()),2)
            finally:await client.close()
