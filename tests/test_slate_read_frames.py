"""Authored detached-read lifecycle and revocation; no SQL or provider traffic."""
from copy import deepcopy
from contextlib import nullcontext
from dataclasses import replace
from datetime import timedelta
from unittest import TestCase
from unittest.mock import MagicMock, patch

from app.comparison.estimated_policy import DEFAULT_POLICY
from app.storage import latest_board
from app.storage.slate_reads import CapturedReads
from app.storage.store import encoded, hashed
from tests.test_current_board_reads import latest_frame


def authored_frame(count=60, revision='first-publication'):
    frame=latest_frame();template=next(iter(frame['rows'].values()))
    # Lifecycle coverage needs many small games, with one retained native price
    # each. The existing busy-game fixture deliberately contains much more data.
    from app.dashboard.comparison_board import expand_odds
    expand_odds(template['facts']['boards']['odds'])
    native=next(q for q in template['facts']['boards']['odds']['prices'] if q['venue']=='kalshi')
    template['facts']['boards']['odds']['prices']=[native]
    template['facts']['boards']['odds']['rows']=[]
    template['facts']['boards']={'odds':template['facts']['boards']['odds']}
    game=frame['status']['games'][0]
    frame['status']['games']=[];frame['rows']={};frame['read_revision']=revision
    for i in range(count):
        key=f'authored-game-{i:03}'
        frame['status']['games'].append(dict(deepcopy(game),game_key=key))
        row=deepcopy(template);row['game_key']=key
        for board in row['facts']['boards'].values():board['game_key']=key
        frame['rows'][key]=row
    return frame


class CapturedSlateReads(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template=authored_frame()

    def setUp(self):
        self.now=0
        self.frames=CapturedReads(clock=lambda:self.now,resource_bytes=lambda:0)
        self.frame=deepcopy(self.template)
        self.authority=hashed([self.frame['read_authority'],False])
        self.snapshot=patch.object(latest_board,'snapshot',side_effect=lambda *a,**k:deepcopy(self.frame)).start()
        self.check=patch.object(latest_board,'slate_authority',side_effect=lambda *a,**k:self.authority).start()
        self.finance=patch.object(latest_board,'calculate_current',side_effect=AssertionError('No request calculation')).start()
        self.addCleanup(patch.stopall)
        self.db=MagicMock()

    def read(self, **options):
        kwargs=dict(view='odds',filter='all',limit=50,read_frames=self.frames)
        kwargs.update(options)
        return latest_board.slate(self.db,kwargs.pop('policy',DEFAULT_POLICY),**kwargs)[0]

    def continuation(self, first, **options):
        kwargs=dict(offset=50,read_token=first['read_token'],expected_revision=first['read_revision'])
        kwargs.update(options)
        return self.read(**kwargs)

    def test_publications_and_books_cannot_change_a_captured_read(self):
        first=self.read();captured=encoded(self.frame)
        self.frame['read_revision']='later-publication'
        new=deepcopy(self.frame['status']['games'][0]);new['game_key']='new-game'
        self.frame['status']['games'].append(new)
        for row in self.frame['rows'].values():
            row['facts']['boards']['odds']['prices'][0]['original']['value']='0.99'
        replay=self.continuation(first,offset=0)
        self.assertEqual(replay['boards'],first['boards'])
        last=self.continuation(first)
        self.assertEqual(len(first['boards'])+len(last['boards']),60)
        self.assertEqual(len({board['game_key'] for board in first['boards']+last['boards']}),60)
        self.assertEqual(first['read_at'],last['read_at'])
        self.assertEqual(first['as_of'],last['as_of'])
        self.assertEqual(first['read_token'],last['read_token'])
        self.assertEqual(first['games'],last['games'])
        self.assertNotIn('new-game',{g['game_key'] for g in last['games']})
        self.assertEqual(self.snapshot.call_count,1)
        fresh=self.read()
        self.assertEqual(len(fresh['games']),61)
        self.assertNotEqual(fresh['read_token'],first['read_token'])
        self.assertNotEqual(fresh['read_revision'],first['read_revision'])
        self.assertEqual(fresh['boards'][0]['prices'][0]['original']['value'],'0.99')
        self.assertNotEqual(encoded(self.frame),captured)
        self.db.execute.assert_not_called()
        self.finance.assert_not_called()

    def test_crossed_contexts_and_revision_are_explicit(self):
        first=self.read()
        for change in (dict(view='ev'),dict(filter='positive'),dict(limit=25),
                       dict(policy=replace(DEFAULT_POLICY,capital_ceiling_usd='500')),
                       dict(expected_revision='other-frame'),dict(expected_revision=None)):
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'current_slate_read_context_changed'):
                self.continuation(first,**change)
        self.assertEqual(len(self.frames.frames),1)

    def test_continuations_require_tokens_and_unknown_tokens_expire(self):
        with self.assertRaisesRegex(ValueError,'current_slate_read_token_required'):
            self.read(offset=50)
        self.snapshot.assert_not_called()
        with self.assertRaisesRegex(ValueError,'current_slate_read_expired'):
            self.read(offset=50,read_token='unknown',expected_revision='unknown')
        self.snapshot.assert_not_called()

    def test_epoch_runtime_stop_and_authority_loss_revoke(self):
        for change in ('epoch','runtime-replacement','stop','source-unavailable','control-stop-recovered'):
            with self.subTest(change=change):
                self.authority=hashed([self.frame['read_authority'],False])
                first=self.read();self.authority=change
                with self.assertRaisesRegex(ValueError,'current_slate_read_authority_changed'):
                    self.continuation(first)
                self.assertEqual(len(self.frames.frames),0)
                self.assertEqual(self.frames.retained_bytes,0)

    def test_authority_is_rechecked_after_the_first_capture(self):
        self.authority='withdrawn-during-render'
        with self.assertRaisesRegex(ValueError,'current_slate_read_authority_changed'):
            self.read()
        self.assertEqual(self.frames.retained_bytes,0)

    def test_expiry_and_abandoned_read_cleanup_are_bounded(self):
        first=self.read();self.assertGreater(self.frames.retained_bytes,0)
        self.now=30
        with self.assertRaisesRegex(ValueError,'current_slate_read_expired'):
            self.continuation(first)
        self.assertEqual(self.frames.retained_bytes,0)
        fresh=self.read();self.assertNotEqual(fresh['read_token'],first['read_token'])
        self.now=61;self.frames.cleanup()
        self.assertEqual(len(self.frames.frames),0)
        self.assertEqual(self.frames.retained_bytes,0)

    def test_page_expiring_during_render_is_refused_and_released(self):
        def expire(*args,**kwargs):
            self.now=30
            return self.authority
        self.check.side_effect=expire
        with self.assertRaisesRegex(ValueError,'current_slate_read_expired'):
            self.read()
        self.assertEqual(self.frames.retained_bytes,0)

    def assert_completed_cache(self):
        # Completed pages retain bounded selected-input evidence, not boards.
        self.assertGreater(self.frames.retained_bytes,0)
        self.assertLessEqual(self.frames.retained_bytes,self.frames.maximum_bytes)
        for frame in self.frames.frames.values():
            self.assertEqual(frame.context,'completed')
            for record in frame.records:
                row=self.frames.decode(record)['row']
                self.assertNotIn('boards',row['facts'])
                self.assertNotIn('_boards_text',row)
        self.now=31;self.frames.cleanup()
        self.assertEqual(self.frames.retained_bytes,0)

    def test_concurrent_tabs_get_independent_frames_and_oldest_eviction(self):
        pages=[self.read() for _ in range(5)]
        self.assertEqual(len({p['read_token'] for p in pages}),5)
        self.assertEqual(len(self.frames.frames),4)
        self.assertLessEqual(self.frames.retained_bytes,self.frames.maximum_bytes)
        with self.assertRaisesRegex(ValueError,'current_slate_read_expired'):
            self.continuation(pages[0])
        self.continuation(pages[1])
        self.assertEqual(len(self.frames.frames),4)
        for first in pages[2:]:self.continuation(first)
        self.assert_completed_cache()

    def test_byte_capacity_refuses_and_fresh_read_can_recover(self):
        self.frames.maximum_bytes=4096
        with self.assertRaisesRegex(ValueError,'current_slate_read_capacity'):
            self.read()
        self.assertEqual(self.frames.retained_bytes,0)
        self.frames.maximum_bytes=64*1024*1024
        first=self.read();self.continuation(first)
        self.assert_completed_cache()

    def test_byte_pressure_evicts_older_frames_without_duplicate_per_page_copies(self):
        first=self.read();size=self.frames.retained_bytes
        self.frames.maximum_bytes=size+100
        second=self.read()
        self.assertEqual(len(self.frames.frames),1)
        self.assertEqual(self.frames.retained_bytes,size)
        with self.assertRaisesRegex(ValueError,'current_slate_read_expired'):
            self.continuation(first)
        self.continuation(second,offset=0)
        self.assertEqual(self.frames.retained_bytes,size)
        self.continuation(second)
        self.assert_completed_cache()

    def test_process_guard_refuses_before_snapshot_or_page_allocation(self):
        self.frames.resource_bytes=lambda:768*1024*1024
        with self.assertRaisesRegex(ValueError,'current_slate_read_capacity'):
            self.read()
        self.snapshot.assert_not_called()
        self.frames.resource_bytes=lambda:0
        first=self.read()
        self.frames.resource_bytes=lambda:768*1024*1024
        with self.assertRaisesRegex(ValueError,'current_slate_read_capacity'):
            self.continuation(first)

    def test_total_read_capacity_is_not_increased(self):
        self.frames.maximum_read_bytes=1
        with self.assertRaisesRegex(ValueError,'current_slate_read_capacity'):
            self.read()
        self.assertEqual(self.frames.retained_bytes,0)

    def test_captured_original_prices_clocks_and_read_assessment_are_immutable(self):
        first=self.read();q=first['boards'][0]['prices'][0]
        original=deepcopy(q['original']);times=deepcopy(q['times'])
        assessment=deepcopy(q['observation_display'])
        self.now=10
        replay=self.continuation(first,offset=0)
        again=replay['boards'][0]['prices'][0]
        self.assertEqual(again['original'],original)
        self.assertEqual(again['times'],times)
        self.assertEqual(again['observation_display'],assessment)
        self.assertEqual(replay['read_at'],first['read_at'])
        # Consumers age these exact original timestamps against their own clock;
        # a token/page/heartbeat never substitutes a newer observation time.
        self.assertEqual(replay['read_expires_at'],first['read_expires_at'])


class SlateAuthority(TestCase):
    def test_receipt_and_reason_changes_are_not_authority(self):
        owner=dict(runtime_id='owner',healthy=True,active=True,config={},states={})
        a=latest_board._slate_authority('epoch',owner,{'kalshi':dict(state='connected',received_at='one',reason='one')},'control')
        b=latest_board._slate_authority('epoch',dict(owner,revision=40,heartbeat_at='later'),{'kalshi':dict(state='connected',received_at='two',reason='two')},'control')
        self.assertEqual(a,b)
        for change in (dict(epoch='reset'),dict(owner=dict(owner,runtime_id='replacement')),
                       dict(owner=dict(owner,active=False)),dict(states={'kalshi':dict(state='unavailable')}),
                       dict(control='stop-and-recover')):
            kwargs=dict(epoch='epoch',owner=owner,states={'kalshi':dict(state='connected')},control='control');kwargs.update(change)
            with self.subTest(change=change):self.assertNotEqual(a,latest_board._slate_authority(**kwargs))


class SlateCaptureClock(TestCase):
    def test_heartbeat_committed_after_entry_is_healthy_in_captured_snapshot(self):
        from tests.test_data_runtime_unit import AT, runtime_row
        early=AT.isoformat();read_at=(AT+timedelta(seconds=2)).isoformat()
        row=runtime_row(heartbeat_at=AT+timedelta(seconds=1))
        for guarded in (False,True):
            for explicit_at in (None,early):
                with self.subTest(guarded=guarded,explicit_at=explicit_at):
                    established=False
                    def execute(statement,*args):
                        nonlocal established
                        cursor=MagicMock()
                        if statement.startswith('SET TRANSACTION'):return cursor
                        if statement.startswith('SELECT COALESCE'):
                            established=True;cursor.fetchone.return_value=dict(byte_count=0)
                        elif statement.startswith('SELECT facts FROM latest_board_status'):
                            established=True;cursor.fetchone.return_value=dict(facts=dict(version='predict-latest-board-3',
                                games=[],epoch='epoch',policy=DEFAULT_POLICY.to_dict()))
                        elif statement.startswith('SELECT * FROM data_runtime'):
                            cursor.fetchone.return_value=row
                        elif statement.startswith(('SELECT * FROM latest_board','SELECT venue,state FROM current_source_status')):
                            cursor.fetchall.return_value=[]
                        else:raise AssertionError('Unexpected authored SQL '+statement)
                        return cursor
                    db=MagicMock();db.transaction.side_effect=lambda:nullcontext();db.execute.side_effect=execute
                    with patch.object(latest_board,'utc',side_effect=lambda:read_at if established else early),\
                         patch.object(latest_board,'marker',return_value='marker'),\
                         patch.object(latest_board,'_control_barrier',return_value=None),\
                         patch.object(latest_board.publication,'capture',return_value=dict(epoch='epoch')):
                        frame=latest_board.snapshot(db,at=explicit_at,resource_guard=(lambda size:None) if guarded else None)
                    self.assertEqual(frame['at'],early if explicit_at else read_at)
                    self.assertEqual(frame['owner']['healthy'],explicit_at is None)
                    self.assertEqual(frame['source_states']['kalshi']['source_at'],row['source_status']['kalshi']['source_at'])
                    self.assertEqual(frame['owner']['heartbeat_at'],(AT+timedelta(seconds=1)).isoformat())
