"""Storage-only verification; local mocks and disposable journals."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.collection.transport_session import ObservationJournal,TransportSession,StorageFailure,reopen
from app.collection.recovery import inspect
from app.dashboard.e6_live import Owner,create_app
from tests.test_e6_transport import spec
from tests.e6_storage_faults import FaultFile,FsyncFault

class Accounting(unittest.TestCase):
    def test_independent_fault_checkpoints(self):
        for mode in ('disk_full','short','partial','flush','fsync'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                s=spec();s['reference_enabled']=False
                o=TransportSession(s,d,{})
                o.journal=ObservationJournal(Path(d)/'observations.jsonl')
                o.emit('session',dict(type='session_started',spec=s,provenance='local mock storage fault'))
                o.set_health('kalshi','awaiting_snapshot')
                self.assertEqual(o.queue.qsize(),2)
                before=o.journal.path.read_bytes();offset=len(before)
                o.journal.file=FaultFile(o.journal.file,mode)
                fs=FsyncFault(o.journal.file.fileno())
                with patch('os.fsync',fs if mode=='fsync' else __import__('os').fsync):
                    with self.assertRaises(StorageFailure):o.set_health('polymarket_us','awaiting_snapshot')
                    o.request_stop('manual_stop');o.request_stop('duration_or_kickoff_cutoff')
                    o.emit('kalshi',dict(type='native_stream_finished'))
                a=o.accounting()
                self.assertEqual({k:a[k] for k in ('received','accepted','write_attempted','durably_acknowledged','rejected','unresolved')},
                                 dict(received=4,accepted=3,write_attempted=3,durably_acknowledged=2,rejected=1,unresolved=1))
                self.assertEqual(a['confirmed_byte_offset'],offset)
                self.assertEqual(a['queue_pending'],2);self.assertEqual(a['queue_drained'],0)
                self.assertEqual(o.reason,'storage_failure');self.assertTrue(all(h=='ineligible' for h in o.health.values()))
                o.journal.close();after=o.journal.path.read_bytes()
                self.assertEqual(after[:offset],before)
                report,saved=inspect(o.journal.path)
                self.assertEqual(report['counts']['ingress'],3 if mode in ('flush','fsync') else 2)
                self.assertEqual(report['excluded_trailing_bytes'],23 if mode in ('short','partial') else 0)
                self.assertEqual(o.journal.path.read_bytes(),after)
                # Recovered visible rows do not establish the runtime fsync outcome.
                self.assertIsNone(report['accounting']['delivered'])
    def test_all_writes_fail_report_is_optional(self):
        with tempfile.TemporaryDirectory() as d:
            s=spec();s['reference_enabled']=False;o=TransportSession(s,d,{})
            o.journal=ObservationJournal(Path(d)/'empty.jsonl');o.journal.file=FaultFile(o.journal.file,'disk_full')
            with self.assertRaises(StorageFailure):o.emit('session',dict(type='session_started',spec=s,provenance='local mock storage fault'))
            with patch('app.dashboard.e6_live.save_json',side_effect=OSError('secret must not escape')):o.report_failure()
            o.journal.close();self.assertEqual(o.failure_report,'unavailable')
            self.assertEqual(o.accounting()['durably_acknowledged'],0)
            self.assertEqual(o.accounting()['unresolved'],1)
            self.assertNotIn('secret',o.persistence_error)
            with self.assertRaises(ValueError):inspect(o.journal.path)

class FailureAPI(unittest.IsolatedAsyncioTestCase):
    async def test_surviving_api_without_journal_read_or_restart(self):
        from aiohttp.test_utils import TestClient,TestServer
        with tempfile.TemporaryDirectory() as d:
            owner=Owner(d);s=spec();s['reference_enabled']=False
            o=TransportSession(s,d,{});owner.session=o
            o.storage_failed('fsync');o.state='failed';o.cleanup_complete=True
            o.counts.update(received=4,accepted=3,write_attempted=3,durably_acknowledged=2,rejected=1)
            (Path(d)/'attempt.json').write_text('{"session":"consumed-test-guard"}')
            before=(Path(d)/'attempt.json').read_bytes()
            with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials')),patch('app.dashboard.e6_live.reopen',side_effect=AssertionError('broken journal read')):
                async with TestClient(TestServer(create_app(owner=owner))) as client:
                    response=await client.get('/api/status');body=await response.json()
                    self.assertEqual(response.status,200);self.assertEqual(body['state'],'failed')
                    self.assertFalse(body['usable']);self.assertIsNone(body['view'])
                    self.assertFalse(body['start_available']);self.assertEqual(body['storage_accounting']['unresolved'],1)
                    self.assertIn('fsync',body['error'])
            self.assertEqual((Path(d)/'attempt.json').read_bytes(),before)

class Finalization(unittest.IsolatedAsyncioTestCase):
    async def test_manifest_fsync_failure_is_not_completed(self):
        from app.dashboard import e6_live
        with tempfile.TemporaryDirectory() as d:
            s=spec();s['reference_enabled']=False;o=TransportSession(s,d,{})
            folder=Path(d)/o.sid;folder.mkdir();o.output=folder
            e6_live.save_json(folder/'run-spec.json',s)
            o.journal=ObservationJournal(folder/(o.sid+'.jsonl'))
            o.emit('session',dict(type='session_started',spec=s,provenance='local mock'))
            o.journal.save(dict(type='session_finished',session_id=o.sid,observed_at=__import__('app.collection.odds_http',fromlist=['utc']).utc(),reason='manual_stop',health=o.health,delivered=1,persisted=0,economics=None))
            o.journal.close();o.state='stopped';o.cleanup_complete=True
            o.task=asyncio.create_task(asyncio.sleep(0));owner=Owner(d);owner.session=o
            original=e6_live.save_json
            def save(path,value):
                if path.name=='manifest.pending.json':
                    with patch('os.fsync',side_effect=OSError('injected')):return original(path,value)
                return original(path,value)
            with patch.object(e6_live,'save_json',save):await owner.finish(folder)
            self.assertEqual(o.state,'failed');self.assertTrue(o.journal.terminal_acknowledged)
            self.assertFalse((folder/'manifest.json').exists());self.assertEqual(owner.saved(),[])
            self.assertTrue(json.loads((folder/'manifest.pending.json').read_text()))
            report,_=inspect(folder/'observations.jsonl')
            self.assertEqual(report['status'],'interrupted_finalization')
            self.assertEqual(o.accounting()['unresolved'],0)
    async def test_startup_storage_failure_closes_resources(self):
        from unittest.mock import AsyncMock,MagicMock
        with tempfile.TemporaryDirectory() as d:
            s=spec();s['reference_enabled']=False
            endpoints={v:dict(rest='http://127.0.0.1:1',ws='ws://127.0.0.1:1') for v in ('kalshi','polymarket_us')}
            producer=MagicMock();producer.aclose=AsyncMock()
            with patch('app.collection.transport_session.PredictionProducer',return_value=producer),patch('app.collection.transport_session.ObservationJournal',side_effect=OSError('injected open')):
                o=TransportSession(s,d,endpoints)
                with self.assertRaises(OSError):await o.start()
            self.assertEqual(producer.aclose.await_count,2)
            self.assertEqual(o.state,'failed');self.assertIsNone(o.task)
            self.assertEqual(o.accounting()['received'],0)
            self.assertTrue(o.cleanup_complete)
    def test_terminal_fsync_visible_is_not_acknowledged(self):
        from app.collection.odds_http import utc
        with tempfile.TemporaryDirectory() as d:
            s=spec();s['reference_enabled']=False;o=TransportSession(s,d,{})
            o.journal=ObservationJournal(Path(d)/'journal.jsonl')
            o.emit('session',dict(type='session_started',spec=s,provenance='local mock'))
            with patch('os.fsync',side_effect=OSError('injected')):
                with self.assertRaises(StorageFailure):o.journal.save(dict(type='session_finished',session_id=o.sid,observed_at=utc(),reason='manual_stop',health=o.health,delivered=1,persisted=0,economics=None))
            o.journal.close();self.assertFalse(o.journal.terminal_acknowledged)
            self.assertEqual(o.accounting()['journal_unresolved'],1)
            report,_=inspect(o.journal.path)
            self.assertEqual(report['status'],'interrupted_finalization')
            self.assertEqual(report['accounting']['delivered'],1)
            self.assertNotIn('terminal_acknowledged',report) # Never reconstruct an unpersisted receipt.
    async def test_first_record_and_report_both_fail_runtime_survives(self):
        from unittest.mock import AsyncMock,MagicMock
        with tempfile.TemporaryDirectory() as d:
            s=spec();s['reference_enabled']=False
            endpoints={v:dict(rest='http://127.0.0.1:1',ws='ws://127.0.0.1:1') for v in ('kalshi','polymarket_us')}
            producer=MagicMock();producer.aclose=AsyncMock()
            def failing(path):
                j=ObservationJournal(path);j.file=FaultFile(j.file,'disk_full');return j
            with patch('app.collection.transport_session.PredictionProducer',return_value=producer),patch('app.collection.transport_session.ObservationJournal',side_effect=failing),patch('app.dashboard.e6_live.save_json',side_effect=OSError('all writes fail')):
                o=TransportSession(s,d,endpoints)
                with self.assertRaises(StorageFailure):await o.start()
            self.assertEqual(o.state,'failed');self.assertEqual(o.failure_report,'unavailable')
            self.assertTrue(o.journal.file.closed);self.assertEqual(o.journal.path.read_bytes(),b'')
            owner=Owner(d);owner.session=o;body=owner.status()
            self.assertIn('durability',body['error']);self.assertFalse(body['usable'])
            a=body['storage_accounting']
            self.assertEqual({k:a[k] for k in ('received','accepted','write_attempted','durably_acknowledged','rejected','unresolved')},dict(received=1,accepted=1,write_attempted=1,durably_acknowledged=0,rejected=0,unresolved=1))
            self.assertEqual(producer.aclose.await_count,2)
