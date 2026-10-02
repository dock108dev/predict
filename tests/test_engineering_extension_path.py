"""Whole fourth-session receipts through discovery and ordinary subscription admission."""
import asyncio
import json
from pathlib import Path
import tempfile
import shutil
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from app.collection.continuous import Discovery, Venue
from app.collection.source_session import AggregateWorker
from app.dashboard.session_history import verified
from app.dashboard.session_projection import SessionProjection, stamp
from tests.test_live_completion_bindings import FOURTH


class ExecutablePath(unittest.IsolatedAsyncioTestCase):
    async def test_actual_extension_journal_finalizes_with_bounded_fresh_replay(self):
        from app.dashboard.coverage_owner import CoverageOwner,LIMITS
        from app.collection.transport_session import reopen
        original=Path('evidence/LIVE-integrated-extension-7b2bf55f-74c4-4620-a7a1-81956097f431/e3bdde0b-d3bd-4309-8f0e-df35f2796fde/cd0deb36-99d1-49e7-a418-1a8dd3aa335c')
        report=json.loads((original/'report.json').read_text());saved=reopen(original/(original.name+'.jsonl'))
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)/original.name;folder.mkdir()
            for name in ('run-spec.json','aggregate-limits.json',original.name+'.jsonl'):shutil.copyfile(original/name,folder/name)
            task=asyncio.get_running_loop().create_future();task.set_result(None)
            session=SimpleNamespace(task=task,persistence_error=None,cleanup_errors=[],
                sid=report['session'],state=report['state'],reason=report['reason'],
                cleanup_complete=True,health=report['health'],snapshots=report['snapshots'],
                collection_seconds=report['collection_seconds'],
                journal=SimpleNamespace(path=folder/(original.name+'.jsonl'),bytes=32*1024*1024,expanded_bytes=32*1024*1024,previous=saved['sha256'],terminal_acknowledged=True),
                status_coverage=lambda:report['coverage'],resources=lambda:report['resources'],
                accounting=lambda:report['accounting'],spec=json.loads((folder/'run-spec.json').read_text()),
                discovery=SimpleNamespace(inventory=report['inventory'],status=lambda:report['discovery']),
                producers={v:SimpleNamespace(ever={k:set(ids) for k,ids in values.items()}) for v,values in report['ever_market_ids'].items()})
            owner=CoverageOwner.__new__(CoverageOwner);owner.segmented_history=False;owner.session=session;owner.owner_lock=None;owner.error=None
            with patch('app.dashboard.coverage_owner.rss',return_value=LIMITS['rss_bytes']-1):await owner.finish(folder)
            self.assertIsNone(owner.error)
            self.assertTrue((folder/'manifest.json').exists())
            resource=json.loads((folder/'replay-resources.json').read_text())
            self.assertLess(resource['sampled_peak_rss'],LIMITS['rss_bytes'])
            from app.dashboard.opportunity_history import retained_history_key
            key=retained_history_key(folder,[])
            self.assertEqual(key,retained_history_key(folder,[]))
            self.assertNotEqual(key,retained_history_key(folder,[dict(id='changed')]))
            with (folder/'aggregate-limits.json').open('a') as stream:stream.write(' ')
            with self.assertRaisesRegex(ValueError,'saved file changed'):retained_history_key(folder,[])
    async def test_whole_failure_receipts_discovery_renewal_subscription(self):
        rows=list(verified(FOURTH)['rows'])
        pages=[deepcopy(r) for r in rows if r['type']=='prediction_discovery_http']
        at=max(stamp(r['received_at']) for r in pages)+timedelta(microseconds=1)
        projection=SessionProjection();projection.apply(rows[0])
        for row in pages:projection.apply(row)
        emitted=[]
        def emit(source,row):
            value=dict(row,source=source,session_id=rows[0]['session_id'],observed_at=at.isoformat())
            emitted.append(value);projection.apply(value)
            return True
        session=SimpleNamespace(spec=deepcopy(rows[0]['spec']),sid=rows[0]['session_id'],
            projection=projection,emit=emit,profile=None,product_session=True,
            producers={},credentials={v:object() for v in ('kalshi','polymarket_us')},health={},stop_event=asyncio.Event())
        discovery=Discovery(session);session.discovery=discovery
        async def retained_venue(venue):
            discovery.pages.extend(deepcopy([p for p in pages if p['source']==venue]))
        async def admitted_run(producer,markets):
            admitted[producer.venue]=[m.raw.ref.market_id for m in markets]
        admitted={}
        with patch.object(discovery,'venue',side_effect=retained_venue),patch('app.collection.continuous.now',return_value=at),patch('app.collection.prediction_producer.PredictionProducer.run',admitted_run),patch('socket.socket.connect',side_effect=AssertionError('Offline replay network forbidden')):
            await discovery.discover()
            self.assertTrue(discovery.completed)
            reviews=[r for r in emitted if r['type']=='native_review']
            self.assertEqual(len(reviews),2)
            for venue in ('kalshi','polymarket_us'):
                selected=discovery.inventory[venue]['selection']['ids']
                self.assertTrue(selected)
                self.assertTrue(all(a['admitted'] for a in discovery.inventory[venue]['native_review_admission']))
                producer=Venue(session,venue);session.producers[venue]=producer
                await producer.reconcile()
                await asyncio.sleep(0)
                for group in producer.groups.values():await group['task']
                self.assertEqual(set(admitted[venue]),set(selected))

    async def test_approved_aggregate_handoff_and_shared_request_dummy_only(self):
        from tests.test_source_session import settings
        captured=[]
        session=SimpleNamespace(spec=dict(mode='real',source_session=settings()),native_authorized=True,
            endpoints={'aggregate':'https://api.the-odds-api.com'},stop_event=asyncio.Event(),
            emit=lambda source,row:captured.append((source,row)))
        async def response(http):
            self.assertEqual(http.target,dict(path='/v4/sports',params={}))
            return dict(complete=True,status=200,data=[])
        with patch.dict('os.environ',{'ODDS_API_KEY':''}),patch('app.collection.credential_handoff.existing_key',return_value='dummy-extension-test-key') as handoff,patch('app.collection.source_session.AggregateHTTP.request',response):
            worker=AggregateWorker(session)
            self.assertIsNone(worker.startup_error)
            await worker.request('/v4/sports',{})
            handoff.assert_called_once()
        session.native_authorized=False
        with patch('app.collection.credential_handoff.existing_key',side_effect=AssertionError('Must not load before Start')):
            with self.assertRaisesRegex(ValueError,'approval'):AggregateWorker(session)


class ExtensionBoundary(unittest.TestCase):
    def test_two_integrated_reservations_exact_totals_no_third_or_metadata(self):
        from app.collection import engineering_authorization as base
        from app.collection.engineering_extension import reserve,validate,gate
        from app.collection.venue_access import ENDPOINTS
        original=Path('evidence/source-engineering-extension-20260930-v1')
        with tempfile.TemporaryDirectory() as directory:
            package=Path(directory)/'source-engineering-extension-test';package.mkdir()
            master=json.loads((original/'master.json').read_text());master['output_root']=str((Path(directory)/'outputs').resolve())
            extension=json.loads((original/'extension.json').read_text());extension['extension_master_sha256']=base.digest(master)
            values={'master.json':master,'extension.json':extension,
                'extension-approval.json':dict(approved=True,extension_sha256=base.digest(extension)),
                'owner-approval.json':dict(approved=True,master_sha256=base.digest(master),policy_sha256=master['policy_sha256'],output_root=master['output_root'],validity_window=master['validity_window'])}
            for name,value in values.items():(package/name).write_text(json.dumps(value))
            spec=json.loads((original/'completion-run-template.json').read_text());endpoints={**ENDPOINTS,'aggregate':'https://api.the-odds-api.com'}
            with self.assertRaisesRegex(ValueError,'Integrated-only'):reserve(package,spec,endpoints,kind='metadata',reason='invalid',offline_regression_evidence=['dummy offline'])
            for i in range(2):
                result=reserve(package,spec,endpoints,reason='Offline boundary control',offline_regression_evidence=['dummy offline'])
                gate(result['approval_path'])
            _,rows=validate(package)
            self.assertEqual(rows[-1]['cumulative']['http_requests'],266)
            self.assertEqual(rows[-1]['cumulative']['aggregate_credits'],270)
            with self.assertRaisesRegex(ValueError,'consumed'):reserve(package,spec,endpoints,reason='invalid third',offline_regression_evidence=['dummy offline'])
            extension['limits']['sessions']=3;(package/'extension.json').write_text(json.dumps(extension))
            with self.assertRaisesRegex(ValueError,'narrower'):validate(package)
