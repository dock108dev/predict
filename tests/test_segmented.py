"""D3a offline fixtures only; original journals/indexes are never rewritten."""
import asyncio
from itertools import zip_longest
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.collection.segmented import (SegmentedJournal, SegmentedReader, POLICY,
    iter_journal, recovery_index, reopen_recovery_index)
from app.collection.odds_http import BudgetStop
from app.dashboard.coverage_owner import OfflineHistoryOwner, replay_segmented
from tests.test_journal_efficiency import ORIGINAL


def row(i=0): return dict(type='sample', ingress_id=str(i), observed_at='fixed', price='0.123400')
def finish(j):
    j.save(dict(type='session_finished')); j.finish(cleanup_complete=True)


class Segments(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def new(self, name='run', **kw): return SegmentedJournal(self.root/name, label='synthetic offline test', **kw)

    def test_real_575_exact_across_metadata_and_stream_boundaries(self):
        j = self.new(); boundaries = []
        for i, (r, _) in enumerate(iter_journal(ORIGINAL)):
            # Stream commands depend on metadata across this boundary; subsequent
            # automatic boundaries split native frame/book pairs in busy traffic.
            if i == 174: j.rotate(); boundaries.append(i)
            j.save(r)
        j.finish(cleanup_complete=True)
        count = 0
        for old, new in zip_longest((r for r, _ in iter_journal(ORIGINAL)), SegmentedReader(j.folder).rows()):
            self.assertEqual(old, new); count += 1
        self.assertEqual(count,1915); self.assertEqual(j.logical,1914)
        self.assertEqual(len(j.segments),3)
        result = replay_segmented(j.folder)
        self.assertEqual(sum(sum(g['exact_native_books'].values()) for g in result.values()),575)
        self.assertTrue(all(g['exact_packets'] for g in result.values()))
        self.assertEqual(j.accounting()['physical_records'],1915+6)

    def test_rotation_never_resets_cumulative_counters(self):
        j = self.new()
        for i in range(4092): j.save(row(i))
        with self.assertRaises(BudgetStop): j.save(row(4092))
        self.assertEqual(j.logical,4092); self.assertEqual(len(j.segments),3)
        finish(j)
        self.assertEqual(len(j.segments),4)
        self.assertEqual(sum(1 for _ in SegmentedReader(j.folder).rows()),4093)

    def test_controls_and_terminal_fit_inside_segment_payload_limits(self):
        j=self.new()
        # Highly compressible rows exercise expanded rather than encoded rotation.
        for i in range(9): j.save(dict(type='sample', index=i, body='x'*(1024*1024)))
        finish(j)
        self.assertGreater(len(j.segments),1)
        for segment in j.segments:
            self.assertLess(segment['expanded_physical'],POLICY['segment_expanded'])
            self.assertLess(segment['bytes'],POLICY['segment_encoded'])
        self.assertEqual(sum(1 for _ in SegmentedReader(j.folder).rows()),10)

    def test_run_encoded_expanded_and_per_row_limits(self):
        j = self.new()
        j.encoded = POLICY['encoded_ingress']
        with self.assertRaises(BudgetStop): j.save(row())
        self.assertEqual(j.logical,0); j.abort()
        j = self.new('expanded')
        with self.assertRaises(BudgetStop): j.save(dict(type='sample',body='x'*(8*1024*1024)))
        j.abort()
        j = self.new('terminal')
        with self.assertRaises(BudgetStop): j.save(dict(type='session_finished',body='x'*65536))
        j.abort()

    def test_missing_reordered_corrupt_and_dependency_fail_closed(self):
        import shutil
        j=self.new(); j.save(row()); j.rotate(); j.save(row(1)); finish(j)
        for fault in ('missing','reorder','corrupt','dependency'):
            p=self.root/fault; shutil.copytree(j.folder,p)
            if fault=='missing': (p/'segment-0000.jsonl').unlink()
            elif fault=='reorder':
                m=json.loads((p/'manifest.json').read_text());m['segments'].reverse();(p/'manifest.json').write_text(json.dumps(m))
            elif fault=='corrupt':
                with (p/'segment-0001.jsonl').open('ab') as f:f.write(b'!')
            else:
                m=json.loads((p/'manifest.json').read_text());m['run']='different';(p/'manifest.json').write_text(json.dumps(m))
            with self.subTest(fault=fault),self.assertRaises((ValueError,FileNotFoundError)):
                next(SegmentedReader(p).rows())

    def test_every_rotation_publication_boundary_and_index_identity(self):
        stages=('seal_fsynced','segment_closed','manifest_written','manifest_fsynced',
            'manifest_replaced','manifest_directory_fsynced','header_fsynced','segment_directory_fsynced')
        for stage in stages:
            with self.subTest(stage=stage):
                j=self.new(stage);j.save(row())
                def fail(at):
                    if at==stage:raise OSError('injected interruption')
                j.fault=fail
                with self.assertRaises(OSError):j.rotate()
                j.abort()
                reader=SegmentedReader(j.folder); result=reader.inspect()
                self.assertEqual(result['state'],'interrupted')
                with self.assertRaises(ValueError):list(reader.rows())
                idx=self.root/(stage+'.index.json'); expected=recovery_index(j.folder,idx)
                self.assertEqual(reopen_recovery_index(idx),expected)
                p=j.folder/'segment-0000.jsonl'
                with p.open('ab') as f:f.write(b' ')
                with self.assertRaises(ValueError):reopen_recovery_index(idx)

    def test_partial_write_and_fsync_failure_are_not_acknowledgements(self):
        for fault in ('write','fsync'):
            j=self.new(fault); j.save(row())
            if fault=='write':
                original=j.active.file
                class Partial:
                    closed=False
                    def write(self,body):return original.write(body[:9])
                    def close(self): original.close();self.closed=True
                j.active.file=Partial()
                with self.assertRaises(OSError):j.save(row(1))
            else:
                with patch('app.collection.transport_session.os.fsync',side_effect=OSError('injected')):
                    with self.assertRaises(OSError):j.save(row(1))
            self.assertEqual(j.observations,1);self.assertTrue(j.failed);j.abort()
            info=SegmentedReader(j.folder).inspect()
            self.assertEqual(info['state'],'interrupted')
            self.assertEqual(info['tail']['excluded_trailing_bytes'],9 if fault=='write' else 0)

    def test_restart_and_active_writer_guards(self):
        j=self.new();j.save(row())
        with self.assertRaises(BlockingIOError):SegmentedReader(j.folder).inspect()
        with self.assertRaises(FileExistsError):self.new()
        j.abort();n=self.new('new-session');self.assertNotEqual(n.run,j.run);n.abort()

    def test_resource_guards(self):
        j=self.new()
        with patch('app.collection.segmented.rss',return_value=POLICY['rss']):
            with self.assertRaises(BudgetStop):j.save(row())
        with patch('app.collection.segmented.shutil.disk_usage') as disk:
            disk.return_value.free=POLICY['disk_floor']
            with self.assertRaises(BudgetStop):j.save(row())
        with patch.object(j,'disk_bytes',return_value=POLICY['output']):
            with self.assertRaises(BudgetStop):j.save(row())
        self.assertEqual(j.observations,0);j.abort()

    def test_incomplete_cleanup_and_post_terminal_refused(self):
        j=self.new();j.save(row());j.save(dict(type='session_finished'))
        with self.assertRaises(ValueError):j.save(row(1))
        j.finish(cleanup_complete=False)
        self.assertEqual(SegmentedReader(j.folder).inspect()['state'],'interrupted')
        with self.assertRaises(ValueError):list(SegmentedReader(j.folder).rows())


class Owner(unittest.IsolatedAsyncioTestCase):
    async def test_pending_queue_stop_and_both_feeds_tasks_finalize(self):
        with tempfile.TemporaryDirectory() as t:
            o=OfflineHistoryOwner(Path(t)/'run',label='synthetic Stop')
            class Feed:
                closed=False
                async def aclose(self):self.closed=True
            o.feeds={v:Feed() for v in ('kalshi','polymarket_us')}
            o.tasks=[asyncio.create_task(asyncio.Event().wait()) for _ in range(2)]
            for i in range(48):o.admit(row(i))
            with self.assertRaises(asyncio.QueueFull):o.admit(row(48))
            self.assertFalse(o.admit(row(49)))
            await o.stop();await o.stop()
            a=o.accounting()
            self.assertEqual((a['received'],a['accepted'],a['durable'],a['rejected']),(50,49,49,1))
            self.assertEqual((a['queue_pending'],a['queue_drained'],a['durable_not_queued']),(0,48,1))
            self.assertTrue(all(f.closed for f in o.feeds.values()));self.assertTrue(all(t.done() for t in o.tasks))
            self.assertEqual(SegmentedReader(o.journal.folder).inspect()['state'],'interrupted')

    async def test_terminal_finalization_and_cleanup_failure(self):
        for bad in (False,True):
            with tempfile.TemporaryDirectory() as t:
                o=OfflineHistoryOwner(Path(t)/'run',label='synthetic finish')
                class Feed:
                    async def aclose(self):
                        if bad:raise OSError('injected')
                o.feeds={'kalshi':Feed(),'polymarket_us':Feed()}
                o.admit(row());o.admit(dict(type='session_finished'));await o.stop()
                self.assertEqual(SegmentedReader(o.journal.folder).inspect()['state'],'interrupted' if bad else 'complete')
                self.assertEqual(o.accounting()['queue_pending'],0)

    async def test_storage_unresolved_and_queue_byte_accounting(self):
        with tempfile.TemporaryDirectory() as t:
            o=OfflineHistoryOwner(Path(t)/'run',label='synthetic unresolved')
            with patch.object(o.journal.active,'save',side_effect=OSError('injected')):
                with self.assertRaises(OSError):o.admit(row())
            await o.stop();self.assertEqual(o.accounting()['unresolved'],1)
        with tempfile.TemporaryDirectory() as t:
            o=OfflineHistoryOwner(Path(t)/'run',label='synthetic expanded queue')
            with self.assertRaises(asyncio.QueueFull):o.admit(dict(type='sample',body='x'*(4*1024*1024)))
            await o.stop();self.assertEqual(o.accounting()['durable_not_queued'],1)
            self.assertEqual(o.queue.high_items,0)


class SavedCalculations(unittest.TestCase):
    def test_saved_calculations_exact_after_segmented_reopening(self):
        from app.dashboard.multi_game import OUTPUT, saved_rows, project_game, default_point, game_calculation
        from tests.test_math_reconciliation import SID
        saved=saved_rows(OUTPUT/SID)
        games=next(r for r in saved['rows'] if r['type']=='multi_game_selection')['games']
        with tempfile.TemporaryDirectory() as t:
            j=SegmentedJournal(Path(t)/'run',label='retained saved calculation regression')
            for i,r in enumerate(saved['rows']):
                if i and i%100==0 and len(j.segments)<3:j.rotate()
                j.save(r)
            j.finish(cleanup_complete=True)
            for g in games:
                # Projection's existing per-game interface is unchanged. Only one
                # game's input subset is retained for comparison, never the run.
                def belongs(r):
                    if r.get('source') not in g['sources']:return True
                    v=r.get('book') or r.get('market')
                    if not v:return r['type'] not in ('prediction_frame','prediction_discovery_http')
                    return all(v['raw']['ref'][k]==g['sources'][r['source']][k] for k in ('event_id','market_id'))
                subset=[r for r in SegmentedReader(j.folder).rows() if belongs(r)]
                old_t,old_r=project_game(saved['rows'],g);new_t,new_r=project_game(subset,g)
                self.assertEqual(old_t,new_t);self.assertEqual(old_r,new_r)
                from datetime import datetime
                class FixedAssessmentClock(datetime):
                    @classmethod
                    def now(cls, tz=None): return cls.fromisoformat('2026-09-16T20:00:00+00:00')
                with patch('datetime.datetime', FixedAssessmentClock):
                    self.compare_calculations(old_t,old_r,new_t,new_r,g,game_calculation,default_point)

    def compare_calculations(self,old_t,old_r,new_t,new_r,g,game_calculation,default_point):
        for probability in (None,'0','0.2','0.4','1'):
            for contract in g['sides']:
                self.assertEqual(game_calculation(default_point(old_t),old_r,g,'100','cent',probability,contract),
                    game_calculation(default_point(new_t),new_r,g,'100','cent',probability,contract))

    def test_fresh_old_new_recovery_and_health_books(self):
        from tests.test_e6_recovery import crash
        from app.collection.transport_session import ObservationJournal,reopen
        from app.collection.journal_encoding import VERSION
        from app.collection.recovery import inspect,index,reopen_index
        from app.collection.native_replay import GroupedNativeVerifier
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=crash(root/'source','books');rows=reopen(source)['rows']
            for name,encoding in [('old',None),('new',VERSION)]:
                p=root/(name+'.jsonl');j=ObservationJournal(p,encoding=encoding)
                for r in rows:j.save(r)
                j.close();report,saved=inspect(p);self.assertEqual(saved['rows'],rows)
                idx=root/(name+'-index.json');expected=index(p,idx);self.assertEqual(reopen_index(idx)[0],expected)
                with p.open('ab') as f:f.write(b'{"row":')
                self.assertEqual(inspect(p)[0]['excluded_trailing_bytes'],7)
                with self.assertRaises(ValueError):reopen_index(idx)
            j=SegmentedJournal(root/'segments',label='fresh isolated recovery fixture')
            for i,r in enumerate(rows):
                if i in (15,25,35):j.rotate()
                j.save(r)
            j.finish(cleanup_complete=False)
            v=GroupedNativeVerifier()
            for r in SegmentedReader(j.folder).rows(allow_interrupted=True):v.feed(r)
            self.assertEqual(v.derived_health_books,report['replay']['derived_health_books'])
            self.assertEqual(sum(sum(g['exact_native_books'].values()) for g in v.result().values()),6)
            self.assertTrue(any(g['gaps'] for g in v.result().values()))


class CrashBoundaries(unittest.TestCase):
    def test_process_exit_at_every_rotation_boundary(self):
        import subprocess
        import sys
        stages=('seal_fsynced','segment_closed','manifest_written','manifest_fsynced',
            'manifest_replaced','manifest_directory_fsynced','header_fsynced','segment_directory_fsynced')
        with tempfile.TemporaryDirectory() as t:
            for stage in stages:
                folder=Path(t)/stage
                code='''
import os,sys
from app.collection.segmented import SegmentedJournal
j=SegmentedJournal(sys.argv[1],label='synthetic process interruption')
j.save(dict(type='sample',ingress_id='original',price='0.1200'))
def fault(at):
    if at==sys.argv[2]:os._exit(73)
j.fault=fault
j.rotate()
'''
                result=subprocess.run([sys.executable,'-c',code,str(folder),stage],capture_output=True)
                self.assertEqual(result.returncode,73,result.stderr)
                self.assertEqual(SegmentedReader(folder).inspect()['state'],'interrupted')
                with self.assertRaises(ValueError):list(SegmentedReader(folder).rows())

    def test_failed_finalization_never_reports_runtime_success(self):
        for stage in ('seal_fsynced','segment_closed','manifest_written','manifest_fsynced',
                      'manifest_replaced','manifest_directory_fsynced'):
            with tempfile.TemporaryDirectory() as t:
                j=SegmentedJournal(Path(t)/'run',label='synthetic finalization failure')
                j.save(row());j.save(dict(type='session_finished'))
                def fault(at):
                    if at==stage:raise OSError('injected')
                j.fault=fault
                with self.assertRaises(OSError):j.finish(cleanup_complete=True)
                self.assertTrue(j.failed);self.assertTrue(j.closed)
                # An OS-visible fully published terminal may verify after reopen;
                # this cannot establish that the failed writer acknowledged it.
                info=SegmentedReader(j.folder).inspect()
                self.assertIn(info['state'],('complete','interrupted'))

    def test_native_dependencies_and_clocks_fail_closed(self):
        from app.collection.native_replay import GroupedNativeVerifier
        for missing in ('market_selected','prediction_command','prediction_frame','session_started'):
            verifier=GroupedNativeVerifier()
            with self.subTest(missing=missing),self.assertRaises((ValueError,KeyError)):
                for r,_ in iter_journal(ORIGINAL):
                    if r['type']!=missing:verifier.feed(r)
        # The saved receipt clock is explicit input, not guessed from the frame;
        # changing packet clock while retaining the book is detected.
        verifier=GroupedNativeVerifier()
        with self.assertRaises(ValueError):
            for r,_ in iter_journal(ORIGINAL):
                if r['type']=='prediction_book':r['packets'][0]['raw_b64']=''
                verifier.feed(r)

    def test_recovery_device_identity_is_not_normalized(self):
        import app.collection.segmented as module
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);j=SegmentedJournal(root/'run',label='synthetic device drift')
            j.save(row());j.finish(cleanup_complete=False)
            idx=root/'index.json';recovery_index(j.folder,idx)
            original=module.signature
            with patch.object(module,'signature',side_effect=lambda st:dict(original(st),device=st.st_dev+1)):
                with self.assertRaises(ValueError):reopen_recovery_index(idx)
