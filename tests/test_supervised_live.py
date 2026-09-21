import asyncio
from copy import deepcopy
import fcntl
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.collection.supervised import NAME, PROFILE
from app.collection.supervised_live import validate_live, validate_live_endpoints, Control
from app.collection.venue_access import ENDPOINTS, REFERENCES
from app.collection.continuous import ContinuousSession
from app.collection.run_spec import preflight
from app.dashboard.coverage_owner import CoverageOwner, spec


def live_spec():
    value=spec();value.update(mode='real',reference_enabled=False,supervised_profile=NAME,duration=300,discovery_cadence=120)
    value['prediction'].update(messages=PROFILE['group_messages'],session_bytes=PROFILE['body_bytes'],discovery_requests=PROFILE['requests'])
    return value


class Boundary(unittest.TestCase):
    def test_explicit_selection_and_real_journal(self):
        value=live_spec()
        self.assertFalse(preflight(value)['valid'])
        self.assertTrue(preflight(value,supervised_live=True)['valid'])
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):ContinuousSession(value,t,ENDPOINTS)
            output=Path(t)/'session';output.mkdir()
            s=ContinuousSession(value,output,ENDPOINTS,supervised_live=True)
            self.assertFalse(s.mock_segmented);self.assertTrue(s.segmented_history)
            self.assertEqual(s.ingress_record_limit,65536)
            s.journal=s.open_journal()
            self.assertEqual(s.journal.history.label,'real supervised venue observations')
            s.journal.history.abort()
        self.assertEqual(spec()['duration'],180)

    def test_endpoint_and_credential_boundary(self):
        value=live_spec();validate_live(value,ENDPOINTS)
        for venue in ENDPOINTS:
            for kind in ('rest','ws'):
                changed=deepcopy(ENDPOINTS);changed[venue][kind]+='/redirect'
                with self.assertRaises(ValueError):validate_live(value,changed)
            changed=deepcopy(value);changed['sources'][venue]['credential_reference']='wrong'
            with self.assertRaises(ValueError):validate_live(changed,ENDPOINTS)
        for credentials in ({},{'kalshi':object(),'polymarket_us':object()}):
            with self.assertRaises(ValueError):validate_live(value,ENDPOINTS,credentials,require_credentials=True)
        with self.assertRaises(ValueError):validate_live(value,ENDPOINTS,require_credentials=True)
        for key,val in [('duration',240),('discovery_cadence',60),('mode','mock'),('reference_enabled',True)]:
            with self.assertRaises(ValueError):validate_live(dict(value,**{key:val}),ENDPOINTS)

    def test_mock_cannot_receive_live_destinations_or_credentials(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):ContinuousSession(live_spec(),t,ENDPOINTS,mock_segmented=True)
            with self.assertRaises(ValueError):ContinuousSession(live_spec(),t,ENDPOINTS,mock_segmented=True,supervised_live=True)
            with self.assertRaises(ValueError):CoverageOwner(t,pilot_output=Path(t)/'p',profile_name=NAME,supervised_live=True,mock_segmented=True,endpoints=ENDPOINTS)


class Controls(unittest.IsolatedAsyncioTestCase):
    async def test_shared_owner_lock_precedes_credentials_and_attempt(self):
        with tempfile.TemporaryDirectory() as t,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credential access forbidden')):
            root=Path(t);shared=root/'shared';shared.mkdir()
            with patch('app.dashboard.coverage_owner.OUTPUT',shared):
                o=CoverageOwner(root/'saved',pilot_output=root/'attempt',profile_name=NAME,supervised_live=True,endpoints=ENDPOINTS)
                with (shared/'collector.lock').open('a') as lock:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    with self.assertRaisesRegex(ValueError,'Another collector'):await o.start(duration=300)
                self.assertIsNone(o.owner_lock);self.assertFalse((root/'attempt'/'attempt.json').exists())

    async def test_consumed_attempt_and_start_validation(self):
        with tempfile.TemporaryDirectory() as t,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credential access forbidden')):
            root=Path(t);o=CoverageOwner(root/'saved',pilot_output=root/'attempt',profile_name=NAME,supervised_live=True,endpoints=ENDPOINTS)
            (root/'attempt'/'attempt.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'consumed'):await o.start(duration=300)
            s=ContinuousSession(live_spec(),root/'session',ENDPOINTS,supervised_live=True)
            s.spec['sources']['kalshi']['credential_reference']='wrong'
            with self.assertRaises(ValueError):await s.start()

    async def test_explicit_stop_closes_intake_synchronously(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);o=CoverageOwner(root/'saved',pilot_output=root/'attempt',profile_name=NAME,supervised_live=True,endpoints=ENDPOINTS)
            s=ContinuousSession(live_spec(),root/'session',ENDPOINTS,supervised_live=True)
            from app.collection.continuous import Discovery
            s.discovery=Discovery(s);s.started_monotonic=__import__('time').monotonic()
            o.session=s;o.finalizer=asyncio.create_task(asyncio.sleep(10))
            c=Control(o,'test');result=await c.stop()
            self.assertTrue(result['intake_closed']);self.assertTrue(s.stop_event.is_set());self.assertEqual(s.reason,'manual_stop')
            o.finalizer.cancel();await asyncio.gather(o.finalizer,return_exceptions=True)
