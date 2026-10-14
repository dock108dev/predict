"""Shared catch-up budget and legacy-path preservation without live SQL."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from app.collection.current_database import catch_up_segments


class SegmentCatchup(unittest.TestCase):
    def test_shared_budget_and_ordered_backlog(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[Path(folder)/name for name in ('observations.jsonl','observations-000001.jsonl','observations-000002.jsonl')]
            for p in paths:p.write_bytes(b'x'*10)
            cursors={str(paths[0].resolve()):10};calls=[]
            class Store:
                def catch_up(self,path,records):
                    calls.append((path.name,records))
                    n=min(records,(10-cursors.get(str(path.resolve()),0))//2)
                    cursors[str(path.resolve())]=cursors.get(str(path.resolve()),0)+n*2
                    return {path.name} if n else set(),n
                def execute(self,query,params):
                    offset=cursors.get(params[0]);return SimpleNamespace(fetchone=lambda:None if offset is None else {'byte_offset':offset})
            store=Store();store.db=store
            keys,n,backlog=catch_up_segments(store,SimpleNamespace(paths=lambda:tuple(paths)),8)
            self.assertEqual(n,8);self.assertEqual(backlog,4)
            self.assertEqual(calls,[('observations.jsonl',8),('observations-000001.jsonl',8),('observations-000002.jsonl',3)])
            self.assertEqual(keys,{paths[1].name,paths[2].name})
            calls.clear();self.assertEqual(catch_up_segments(store,SimpleNamespace(paths=lambda:tuple(paths)),8)[1:],(2,0))
            self.assertEqual(catch_up_segments(store,SimpleNamespace(paths=lambda:tuple(paths)),8)[1:],(0,0))

    def test_legacy_checkpoint_is_never_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'observations.jsonl';p.write_bytes(b'complete\n')
            db=SimpleNamespace(execute=lambda *a:SimpleNamespace(fetchone=lambda:{'byte_offset':p.stat().st_size}))
            store=SimpleNamespace(db=db,catch_up=lambda path,records:(set(),0))
            self.assertEqual(catch_up_segments(store,SimpleNamespace(path=p)),(set(),0,0))

    def test_truncation_is_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'observations.jsonl';p.write_bytes(b'')
            db=SimpleNamespace(execute=lambda *a:SimpleNamespace(fetchone=lambda:{'byte_offset':12}))
            store=SimpleNamespace(db=db,catch_up=lambda path,records:(set(),0))
            with self.assertRaisesRegex(ValueError,'journal_truncated'):
                catch_up_segments(store,SimpleNamespace(paths=lambda:(p,)))
