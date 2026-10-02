import json
from pathlib import Path
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from tests.test_source_session import settings,UnifiedFixture
from app.collection.source_session import validate
from app.collection.native_approval import validate_approval,digest
from app.collection.venue_access import ENDPOINTS
from tests.test_native_integration import configuration

class Boundaries(unittest.TestCase):
    def test_launcher_missing_inputs_fails_before_network_or_credentials(self):
        from app.collection import integrated_acquisition as entry
        from app.collection.native_approval import implementation
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);out=p/'unused-attempt'
            (p/'identity.json').write_text(json.dumps({'implementation_sha256':digest(implementation())}))
            (p/'attempt.json').write_text(json.dumps({'output':str(out)}))
            with patch.object(entry,'PACKAGE',p),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
                with self.assertRaises(FileNotFoundError):entry.prepared()
            self.assertFalse(out.exists())

    def test_cycle_policy(self):
        for n in (0,4,True,'3'):
            with self.assertRaises(ValueError):validate(settings(max_cycles=n))
        self.assertEqual(validate(settings(max_cycles=3))['max_cycles'],3)
    def test_prebound_quota_and_window_cannot_bypass_start_checks(self):
        s=configuration();s['mode']='real';s['source_session']=settings(max_cycles=3)
        s['native_sources']['novig']=dict(state='disabled',selected=False)
        now=datetime.now(timezone.utc)
        s.update(start_after=(now-timedelta(minutes=1)).isoformat(),start_before=(now+timedelta(minutes=5)).isoformat(),scheduled_start=(now+timedelta(days=1)).isoformat())
        ep={**ENDPOINTS,'aggregate':'https://api.the-odds-api.com'}
        with tempfile.TemporaryDirectory() as root,patch('app.collection.native_approval.implementation',return_value={'fixture':'digest'}):
            path=Path(root)/'approval.json'
            def approve(v):path.write_text(json.dumps(dict(approved=True,spec_sha256=digest(v),implementation_sha256=digest({'fixture':'digest'}),output=str(Path(root).resolve()))))
            approve(s);validate_approval(s,ep,path,root)
            for change in ('stale','future','early'):
                v=deepcopy(s)
                if change=='early':v['start_after']=(now+timedelta(minutes=1)).isoformat()
                else:v['source_session']['quota_observed_at']=(now+timedelta(seconds=120 if change=='future' else -120)).isoformat()
                approve(v)
                with self.assertRaises(ValueError):validate_approval(v,ep,path,root,consume=True)
                self.assertFalse((Path(root)/'b3-attempt.json').exists())
    def test_export_reservation_precedes_write(self):
        from app.dashboard.coverage_owner import save_json
        with tempfile.TemporaryDirectory() as root,patch('app.dashboard.coverage_owner.LIMITS',{'output_bytes':32}):
            target=Path(root)/'report.json'
            with self.assertRaises(ValueError):save_json(target,{'x':'x'*64})
            self.assertFalse(target.exists())
            save_json(target,{'x':1})

class Cycles(unittest.IsolatedAsyncioTestCase):
    async def test_empty_scope_is_not_repeated_or_removed_from_coverage(self):
        from aiohttp import web
        class Empty(UnifiedFixture):
            async def rest(self, req):
                if req.path.startswith('/v4/'):
                    self.odds_calls.append(req.path)
                    return web.json_response([],headers={'x-requests-used':'0','x-requests-remaining':'100','x-requests-last':'0'})
                return await super().rest(req)
        with tempfile.TemporaryDirectory() as root:
            f=Empty();o=await f.boot(root)
            try:
                await f.start_route(settings(max_cycles=3));await f.native_images()
                await f.wait(lambda:o.session.aggregate.health=='completed')
                self.assertEqual(len(f.odds_calls),1)
                self.assertEqual(len(o.current_snapshot()['aggregate_coverage']),63)
                await f.stop_route();self.assertIsNone(o.error)
            finally:await f.close()

    async def test_cap_does_not_restart_or_stop_native_peer(self):
        with tempfile.TemporaryDirectory() as root:
            f=UnifiedFixture()
            with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
                o=await f.boot(root)
                try:
                    await f.start_route(settings(max_cycles=1));await f.native_images()
                    await f.wait(lambda:o.session.aggregate.health=='completed')
                    self.assertEqual(len(f.odds_calls),2);self.assertEqual(o.session.state,'running')
                    await f.send(f.active()[0]);await f.stop_route();self.assertIsNone(o.error)
                finally:await f.close()
