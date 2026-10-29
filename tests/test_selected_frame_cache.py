"""Bounded UI retention and source scheduling; no providers or owner data."""
from unittest import TestCase
from app.storage.slate_reads import CapturedReads
from app.storage.store import encoded
from app.storage.latest_board import prioritize_sources


class SelectedFrameCache(TestCase):
    def test_completed_frame_survives_and_lease_does_not_edit_evidence(self):
        now=[0.0]
        reads=CapturedReads(clock=lambda:now[0],resource_bytes=lambda:0,ttl_seconds=30)
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
        now=[0.0];reads=CapturedReads(clock=lambda:now[0],resource_bytes=lambda:0,ttl_seconds=30)
        row={'facts':{'source_at':'2026-10-23T23:00:00Z'}}
        frame=reads.capture({},[encoded(dict(game_key='game',row=row))],context='odds',authority='owner')
        reads.account(frame,offset=0,limit=1,size=100,complete=True)
        now[0]=29;reads.lease(frame.token)
        for _ in range(2):reads.capture({},[],context='odds',authority='owner')
        now[0]=50
        self.assertEqual(reads.selection(frame.token,'game')[0],row)
        now[0]=90
        with self.assertRaisesRegex(ValueError,'current_slate_read_expired'):reads.lease(frame.token)

    def test_details_pressure_retires_display_before_active_pagination(self):
        reads=CapturedReads(resource_bytes=lambda:0,maximum_frames=2)
        record=encoded(dict(game_key='game',row={'facts':{'source_at':'original'}}))
        displayed=reads.capture({},[record],context='ev',authority='owner')
        reads.account(displayed,offset=0,limit=1,size=100,complete=True)
        reads.lease(displayed.token)
        paging=reads.capture({},[record],context='ev',authority='owner')
        value,selected=reads.selection(displayed.token,'game')
        self.assertEqual(value['facts']['source_at'],'original')
        self.assertIs(reads.get(paging.token,context='ev'),paging)
        self.assertIn(selected,reads.frames)
        self.assertNotIn(displayed.token,reads.frames)
        self.assertEqual(reads.retained_bytes,sum(f.size for f in reads.frames.values()))

    def test_refused_newcomer_does_not_partially_evict_existing_evidence(self):
        reads=CapturedReads(resource_bytes=lambda:0)
        displayed=reads.capture({},[],context='completed',authority='owner')
        active=reads.capture({},[encoded(dict(payload='x'*10000))],context='ev',authority='owner')
        before=reads.retained_bytes;reads.maximum_bytes=before+100
        with self.assertRaisesRegex(ValueError,'current_slate_read_capacity'):
            reads.capture({},[encoded(dict(payload='y'*8000))],context='ev',authority='owner')
        self.assertEqual(reads.retained_bytes,before)
        self.assertEqual(set(reads.frames),{displayed.token,active.token})

    def test_open_selection_is_protected_and_close_releases_capacity(self):
        reads=CapturedReads(resource_bytes=lambda:0,maximum_frames=1)
        selected=reads.capture({},[],context='selected',authority='owner')
        with self.assertRaisesRegex(ValueError,'current_slate_read_capacity'):
            reads.capture({},[],context='ev',authority='owner')
        reads.discard(selected.token)
        reads.capture({},[],context='ev',authority='owner')
        self.assertEqual(len(reads.frames),1)

    def test_eviction_and_wrong_game_remain_explicit(self):
        reads=CapturedReads(resource_bytes=lambda:0)
        first=reads.capture({},[encoded(dict(game_key='game',row={}))],context='ev',authority='owner')
        with self.assertRaisesRegex(ValueError,'current_selection_removed'):reads.selection(first.token,'other')
        reads.account(first,offset=0,limit=1,size=100,complete=True)
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
