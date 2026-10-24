"""Bounded UI retention and source scheduling; no providers or owner data."""
from unittest import TestCase
from app.storage.slate_reads import CapturedReads
from app.storage.store import encoded
from app.storage.latest_board import prioritize_sources


class SelectedFrameCache(TestCase):
    def test_completed_frame_survives_and_lease_does_not_edit_evidence(self):
        now=[0.0]
        reads=CapturedReads(clock=lambda:now[0],resource_bytes=lambda:0)
        row={'facts':{'source_at':'2026-10-23T23:00:00Z','confirmation_at':'2026-10-23T23:00:05Z'}}
        frame=reads.capture({},[encoded(dict(game_key='game',row=row))],context='ev',authority='owner')
        reads.account(frame,offset=0,limit=1,size=100,complete=True)
        now[0]=29
        value,token=reads.selection(frame.token,'game')
        self.assertEqual(value,row)
        now[0]=58
        self.assertEqual(reads.selection(token,'game')[0],row)
        now[0]=89
        with self.assertRaisesRegex(ValueError,'current_slate_read_expired'):reads.selection(token,'game')

    def test_display_lease_keeps_visible_evidence_without_renewing_clocks(self):
        now=[0.0];reads=CapturedReads(clock=lambda:now[0],resource_bytes=lambda:0)
        row={'facts':{'source_at':'2026-10-23T23:00:00Z'}}
        frame=reads.capture({},[encoded(dict(game_key='game',row=row))],context='odds',authority='owner')
        reads.account(frame,offset=0,limit=1,size=100,complete=True)
        now[0]=29;reads.lease(frame.token)
        for _ in range(4):reads.capture({},[],context='odds',authority='owner')
        now[0]=50
        self.assertEqual(reads.selection(frame.token,'game')[0],row)
        now[0]=90
        with self.assertRaisesRegex(ValueError,'current_slate_read_expired'):reads.lease(frame.token)

    def test_eviction_and_wrong_game_remain_explicit(self):
        reads=CapturedReads(resource_bytes=lambda:0)
        first=reads.capture({},[encoded(dict(game_key='game',row={}))],context='ev',authority='owner')
        with self.assertRaisesRegex(ValueError,'current_selection_removed'):reads.selection(first.token,'other')
        for _ in range(4):reads.capture({},[],context='odds',authority='owner')
        self.assertEqual(len(reads.frames),4)
        with self.assertRaisesRegex(ValueError,'current_slate_read_expired'):reads.selection(first.token,'game')

    def test_one_fresh_component_precedes_ordinary_rotation_without_splitting(self):
        class DB:
            def execute(self,query):
                self.rows=([dict(event_id='busy',receipt='2026-10-23T23:00:10Z'),dict(event_id='quiet',receipt='2026-10-23T22:50:00Z')]
                    if 'current_offer' in query else [dict(members=['busy','peer'],published_at='2026-10-23T22:59:00Z')])
                return self
            def fetchall(self):return self.rows
        batches=[['quiet'],['busy','peer'],['another']]
        self.assertEqual(prioritize_sources(DB(),batches,'2026-10-23T23:00:20Z'),[['busy','peer'],['quiet'],['another']])
        self.assertEqual(prioritize_sources(DB(),batches,'2026-10-23T23:01:00Z'),batches)
