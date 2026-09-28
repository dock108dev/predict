"""Actual localhost Stop/finalization under injected monitor storage failure."""
import asyncio
import json
from pathlib import Path
import unittest
from scripts.supervise_comparison import Evidence,LocalApp,Supervisor
from tests import test_two_source_qualification as fixture

class FailureStop(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.ProductTests.asyncSetUp
    asyncTearDown=fixture.ProductTests.asyncTearDown
    fixture_rest=fixture.ProductTests.fixture_rest

    async def test_disk_failure_stops_real_local_app_and_reopens_exactly(self):
        p=self.root/'observer';e=Evidence(p);original=e.save;armed=False
        def save(name,value):
            if armed and name=='status-samples.json':raise OSError('injected observer storage loss')
            original(name,value)
        e.save=save
        app=LocalApp(str(self.client.make_url('/')).rstrip('/'))
        attempt=self.s['two_source_qualification']['attempt_id']
        monitor=Supervisor(app,self.o.pilot_output,attempt,e,announce=lambda *a,**k:None)
        task=asyncio.create_task(asyncio.to_thread(monitor.run,sleep=lambda _:__import__('time').sleep(.05)))
        for _ in range(100):
            if (p/'monitor-ready.json').exists():break
            await asyncio.sleep(.01)
        self.assertTrue((p/'monitor-ready.json').exists())
        origin=str(self.client.make_url('/')).rstrip('/')
        base=self.o.session_factory
        class MarkedSession(base):
            async def start(session):
                (self.o.pilot_output/'b3-attempt.json').write_text(json.dumps(dict(attempt_id=attempt,started_monotonic=__import__('time').monotonic(),mode='synthetic')))
                return await super().start()
        self.o.session_factory=MarkedSession
        response=await self.client.post('/api/start',json={'duration':90},headers={'Origin':origin})
        self.assertEqual(response.status,200)
        self.observe()
        await self.f.wait(lambda:len(self.f.active())==2)
        await self.f.images();await self.o.session.queue.join()
        armed=True
        with self.assertRaisesRegex(OSError,'storage loss'):await asyncio.wait_for(task,10)
        await self.o.finalizer
        status=self.o.status()
        self.assertFalse(status['active']);self.assertTrue(status['cleanup_complete']);self.assertEqual(status['stop_reason'],'manual_stop')
        self.assertFalse(self.f.active());self.assertFalse(self.o.session.emit('session',dict(type='after_stop')))
        record=json.loads((p/'safety-stop.json').read_text())
        self.assertIn('NOT manual Stop',record['kind']);self.assertEqual(len(record['attempts']),1)
        from app.collection.two_source_audit import verify
        audit=verify(self.o.session.output)
        self.assertTrue(audit['exact_snapshot']);self.assertTrue(audit['exact_calculations']);self.assertTrue(audit['exact_native_replay'])

    observe=fixture.ProductTests.observe

if __name__=='__main__':unittest.main()
