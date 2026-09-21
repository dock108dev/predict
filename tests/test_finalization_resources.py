"""Offline only: independent writes, saved-sized serialization and real mock lifecycle."""
import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from app.collection.finalization import write_supplement, RECEIPT_BYTES, RECEIPT_NAME
from app.collection.segmented import SegmentedJournal
from app.collection.supervised import NAME, PROFILE
from app.collection.supervised_live import Control
from tests.segmented_collector_fixture import Fixture


class Writes:
    """Observe successful payload writes independently of application counters."""
    def __init__(self): self.bytes = 0; self.by_path = {}; self.open = Path.open
    def __call__(self, path, *args, **kwargs):
        handle = self.open(path, *args, **kwargs)
        observer = self
        class Observed:
            def __getattr__(self, name): return getattr(handle, name)
            def __enter__(self): return self
            def __exit__(self, *args): return handle.__exit__(*args)
            def __iter__(self): return iter(handle)
            def write(self, body):
                n = handle.write(body)
                size = len(body[:n].encode()) if isinstance(body, str) else n
                observer.bytes += size
                observer.by_path[str(path)] = observer.by_path.get(str(path), 0) + size
                return n
        return Observed()


class Receipt(unittest.TestCase):
    def test_saved_sized_report_independent_writes_and_post_write_sample(self):
        saved = json.loads(Path('evidence/supervised-5m-live-20260916/attempt/validation.json').read_text())
        with tempfile.TemporaryDirectory() as t:
            out=Path(t); writes=Writes()
            with patch.object(Path, 'open', lambda p,*a,**kw:writes(p,*a,**kw)):
                h=SegmentedJournal(out/'history',label='offline telemetry verification',output_root=out,profile_name=NAME)
                for n in range(3):
                    h.save(dict(type='synthetic',number=n)); h.rotate()
                h.finalizing=True; h.finish(cleanup_complete=True)
                def sampled():
                    self.assertEqual(json.loads((out/'validation.json').read_text()),saved)
                    self.assertFalse((out/RECEIPT_NAME).exists())
                    return 123456789
                now=time.monotonic()
                with patch('app.collection.finalization.rss',side_effect=sampled):
                    result=write_supplement(out,h,saved,started=now-3,closed=now-1)
                self.assertEqual(result['post_report_write_process_high_water_bytes'],123456789)
                self.assertEqual(result['cumulative_application_file_write_bytes'],writes.bytes)
                self.assertEqual(result['final_retained_output_bytes'],sum(p.stat().st_size for p in out.rglob('*') if p.is_file()))
                self.assertEqual(result['history_manifest_write_bytes'],writes.by_path[str(out/'history'/'manifest.pending')])
                self.assertGreater(result['replaced_history_manifest_bytes'],0)
                self.assertEqual((out/RECEIPT_NAME).stat().st_size,RECEIPT_BYTES)
                self.assertEqual(json.loads((out/RECEIPT_NAME).read_text()),result)
                self.assertEqual(result['status'],'complete')
                self.assertGreaterEqual(result['finalization_through_report_seconds'],1)
                self.assertGreater(result['supplemental_serialization_write_seconds'],0)
                with self.assertRaises(FileExistsError):write_supplement(out,h,saved,started=now,closed=now)

    def test_deadline_and_post_write_memory_failure_retained(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t); h=SegmentedJournal(out/'history',label='synthetic',output_root=out,profile_name=NAME)
            h.finalizing=True;h.finish(cleanup_complete=True)
            now=time.monotonic()
            with patch('app.collection.finalization.rss',return_value=PROFILE['rss']):
                r=write_supplement(out,h,{},started=now-400,closed=now-301)
            self.assertEqual(r['status'],'failed')
            self.assertFalse(r['checks']['rss_cap']);self.assertFalse(r['checks']['finalization_deadline'])
            self.assertTrue((out/RECEIPT_NAME).exists())

    def test_report_write_failure_does_not_publish_success_receipt(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t);h=SegmentedJournal(out/'history',label='synthetic',output_root=out,profile_name=NAME)
            h.finalizing=True;h.finish(cleanup_complete=True)
            with patch('app.collection.finalization.os.fsync',side_effect=OSError('synthetic fsync failure')):
                with self.assertRaisesRegex(OSError,'synthetic fsync failure'):
                    write_supplement(out,h,{},started=time.monotonic(),closed=time.monotonic())
            self.assertTrue((out/'validation.json').exists())
            self.assertFalse((out/RECEIPT_NAME).exists())

    def test_cumulative_write_limit_prevents_report_write(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t);h=SegmentedJournal(out/'history',label='synthetic',output_root=out,profile_name=NAME)
            h.finalizing=True;h.finish(cleanup_complete=True)
            h.manifest_write_bytes=PROFILE['write_bytes']
            with self.assertRaisesRegex(ValueError,'write_cap'):
                write_supplement(out,h,{},started=time.monotonic(),closed=time.monotonic())
            self.assertFalse((out/'validation.json').exists())


class Lifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_control_report_after_stop_drain_refresh_and_exact_replay(self):
        writes=Writes()
        with tempfile.TemporaryDirectory() as t, patch.object(Path, 'open', lambda p,*a,**kw:writes(p,*a,**kw)), patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials forbidden')):
            f=Fixture();o=await f.start(t,duration=300,profile_name=NAME)
            try:
                s=o.session;c=Control(o,'offline synthetic candidate')
                await f.busy(120)
                await s.discovery.discover(force=True)
                await f.wait(lambda:all(p.applied_generation==2 for p in s.producers.values()))
                await c.stop();await c.finalize()
                r=json.loads((o.pilot_output/RECEIPT_NAME).read_text())
                self.assertEqual(c.final_result['outcome'],'complete')
                self.assertEqual(r['status'],'complete');self.assertEqual(s.reason,'manual_stop')
                self.assertTrue(c.finished.is_set());self.assertIsNone(o.owner_lock)
                self.assertEqual(s.queue.qsize(),0);self.assertEqual(s.delivered,s.persisted)
                report=json.loads((o.pilot_output/'validation.json').read_text())
                self.assertTrue(report['all_group_tasks_done']);self.assertTrue(report['all_streams_closed'])
                replay=json.loads((s.output/'replay.json').read_text())
                self.assertEqual(replay['sequence_sha256'],f.sequence.hexdigest())
                self.assertEqual(replay['counts']['prediction_book'],f.books)
                self.assertEqual(replay['published_generations'],[1,2])
                self.assertEqual(r['final_retained_output_bytes'],sum(p.stat().st_size for p in o.pilot_output.rglob('*') if p.is_file()))
                actual_writes=sum(n for p,n in writes.by_path.items() if Path(p).is_relative_to(o.pilot_output))
                self.assertEqual(r['cumulative_application_file_write_bytes'],actual_writes)
                self.assertGreaterEqual(r['report_write_finished_elapsed'],report['result_prepared_elapsed'])
                self.assertGreaterEqual(c.final_result['receipt_write_finished_elapsed'],r['measurement_finished_elapsed'])
                with self.assertRaisesRegex(ValueError,'consumed'):await o.start(duration=300)
            finally:await f.close()
