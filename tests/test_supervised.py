import json
from itertools import zip_longest
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from app.collection.supervised import NAME, PROFILE, ExactIdentities, RateBudget, Samples
from app.collection.segmented import SegmentedJournal, SegmentedReader, iter_journal, POLICY
from app.collection.native_replay import GroupedNativeVerifier
from app.collection.odds_http import BudgetStop
from app.dashboard.coverage_owner import CoverageOwner, spec
from app.collection.continuous import ContinuousSession
from app.collection.run_spec import preflight
from tests.test_journal_efficiency import ORIGINAL

class Retained(unittest.TestCase):
    def test_original_exact_with_bounded_native_state(self):
        with tempfile.TemporaryDirectory() as t:
            j=SegmentedJournal(Path(t)/'history',label='retained exactness',profile_name=NAME)
            for i,(row,_) in enumerate(iter_journal(ORIGINAL)):
                if i==174:j.rotate()
                j.save(row)
            j.finalizing=True;j.finish(cleanup_complete=True)
            v=GroupedNativeVerifier(NAME);ids=ExactIdentities(Path(t)/'identities');n=0
            for a,b in zip_longest((r for r,_ in iter_journal(ORIGINAL)),SegmentedReader(j.folder).rows()):
                self.assertEqual(a,b);v.feed(b);n+=1
                if 'ingress_id' in b:ids.add(b['ingress_id'])
            self.assertEqual(ids.finish(),1914);self.assertEqual(n,1915)
            result=v.result()
            self.assertEqual(sum(sum(g['exact_native_books'].values()) for g in result.values()),575)
            self.assertTrue(all(g['exact_packets'] for g in result.values()))
            for group in v.groups.values():
                for engine in group.engines.values():
                    self.assertEqual(len(getattr(engine,'frames',[])),0)
                    self.assertEqual(len(getattr(engine,'responses',[])),0)

class Bounds(unittest.TestCase):
    def test_accounting_temporaries_released_without_cyclic_gc(self):
        import gc
        from sys import getsizeof
        from app.dashboard.bounds import retained_bytes
        payload=[{'value':str(i)} for i in range(1000)]
        expected=getsizeof(payload)+sum(getsizeof(x)+getsizeof(x['value']) for x in payload)+getsizeof('value')
        gc.collect();gc.disable()
        try:
            for _ in range(20):self.assertEqual(retained_bytes(payload),expected)
            # The closure can await GC, but its scratch identity set must be empty.
            scratch=[o for o in gc.get_objects() if isinstance(o,set) and id(payload) in o]
            self.assertEqual(scratch,[])
        finally:gc.enable();gc.collect()

    def test_policy_opt_in_and_legacy_defaults(self):
        self.assertEqual(POLICY['logical'],4096)
        with self.assertRaises(TypeError):PROFILE['logical']=1
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):CoverageOwner(t,profile_name=NAME)
            value=spec();self.assertEqual(value['duration'],180);self.assertEqual(value['prediction']['messages'],600)
            value.update(supervised_profile=NAME)
            self.assertFalse(preflight(value)['valid'])

    def test_exact_identity_duplicate_across_chunks(self):
        with tempfile.TemporaryDirectory() as t:
            ids=ExactIdentities(Path(t)/'ids');first=str(uuid4())
            ids.add(first)
            for _ in range(4095):ids.add(str(uuid4()))
            ids.add(first)
            self.assertLessEqual(len(ids.chunk),4096)
            with self.assertRaisesRegex(ValueError,'duplicate'):ids.finish()

    def test_new_history_and_rate_boundaries(self):
        row=dict(type='sample',ingress_id=str(uuid4()),data='x')
        with tempfile.TemporaryDirectory() as t:
            j=SegmentedJournal(Path(t)/'h',label='boundary',profile_name=NAME)
            try:
                with self.assertRaises(BudgetStop):j.save(dict(row,data='x'*(1024**2)))
                j.expanded=PROFILE['expanded_ingress']
                with self.assertRaises(BudgetStop):j.save(row)
                j.expanded=0;j.logical=PROFILE['logical']
                with self.assertRaises(BudgetStop):j.save(row)
                j.logical=0;j.encoded=PROFILE['encoded_ingress']
                with self.assertRaises(BudgetStop):j.save(row)
            finally:j.abort()
        rate=RateBudget();rate.frame_count=PROFILE['frames']
        with self.assertRaises(BudgetStop):rate.admit(1,1,True)
        with patch('app.collection.supervised.time.monotonic',return_value=1):
            rate=RateBudget()
            for _ in range(256):rate.admit(1,1,True)
            with self.assertRaises(BudgetStop):rate.admit(1,1,True)
            rate=RateBudget()
            with self.assertRaises(BudgetStop):rate.admit(8*1024**2+1,1)
            with self.assertRaises(BudgetStop):rate.admit(1,32*1024**2+1)

    def test_segment_rotation_preserves_session_budget(self):
        with tempfile.TemporaryDirectory() as t:
            j=SegmentedJournal(Path(t)/'h',label='rotation',profile_name=NAME)
            for i in range(2050):j.save(dict(type='sample',index=i))
            self.assertEqual(j.logical,2050);self.assertEqual(len(j.segments),2)
            j.finalizing=True;j.save(dict(type='session_finished'));j.finish(cleanup_complete=True)
            self.assertEqual(len(list(SegmentedReader(j.folder).rows())),2051)

    def test_samples_and_disk_reserve(self):
        samples=Samples()
        for i in range(1000):samples.append(i)
        self.assertEqual(len(samples),128);self.assertEqual(samples.total,1000)
        with tempfile.TemporaryDirectory() as t:
            j=SegmentedJournal(Path(t)/'h',label='disk',profile_name=NAME)
            try:
                with patch('app.collection.segmented.shutil.disk_usage') as disk:
                    disk.return_value.free=PROFILE['disk_floor']-1
                    with self.assertRaises(BudgetStop):j._guard()
                with patch.object(j,'disk_bytes',return_value=PROFILE['output']-PROFILE['finalization_reserve']):
                    with self.assertRaises(BudgetStop):j._guard(1)
            finally:j.abort()
