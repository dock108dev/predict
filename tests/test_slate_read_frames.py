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
    def test_compact_owner_retains_complete_result_validation_authority(self):
        owner=dict(runtime_id='original-runtime',active=True,healthy=True,config={'scope':'retained'},
            paused_sources=['novig'],global_stopped=False,service_state='running',
            calculations={'observations':'running','board':'paused'},status={'large':'diagnostic'})
        compact=latest_board.captured_owner(owner)
        self.assertEqual(latest_board.runtime_identity(owner),latest_board.runtime_identity(compact))
        self.assertNotIn('status',compact)

    def test_serialized_result_list_preserves_runtime_and_control_validation(self):
        from app.storage.current_games import engine_binding, observation_binding
        frame=latest_frame();key=frame['status']['games'][0]['game_key']
        frame['status']['games']=[frame['status']['games'][0]];frame['rows']={key:frame['rows'][key]}
        owner=dict(runtime_id='captured-owner',active=True,healthy=True,config={'scope':'fixture'},
            paused_sources=[],global_stopped=False,service_state='running',calculations={'board':'running','observations':'running'})
        frame['owner']=owner
        frame['_source_binding']=observation_binding()
        frame['_engine_binding']=engine_binding()
        frame['_current_policy']=DEFAULT_POLICY.to_dict()
        selector=dict(events=[],occurrences=[],shared=[])
        child=deepcopy(frame['rows'][key]['facts'])
        child.update(publication_runtime=latest_board.runtime_identity(owner),authority_control='retained-control',
            publication_dependencies={'selector':selector},observation_binding=observation_binding(),
            context={'engine_binding':engine_binding(),'policy_revision':DEFAULT_POLICY.revision})
        frame['rows'][key]['facts'].update(result_units={'unit':dict(facts=child,generation_id='generation',calculated_at=frame['at'])},
            result_unit_inventory=[dict(id='unit',groups=[])],publication_dependencies={'selector':selector})
        frame['_dependencies']=dict(epoch='fixture',events={},offers={},books=[],selection_identities={},
            states={},active_events=[],control_barrier='retained-control')
        empty=lambda *a,**kw:dict(all=[],observations={},comparisons={})
        with patch.object(latest_board,'snapshot',side_effect=lambda *a,**kw:deepcopy(frame)), \
                patch('app.storage.observation_publication.neighborhood',return_value=[]), \
                patch('app.storage.observation_publication.reasons',side_effect=empty), \
                patch('app.storage.result_dependencies.reasons',side_effect=empty), \
                patch.object(latest_board,'inventory_state',return_value='current'):
            page=self.read(view='ev')
        self.assertFalse(page['errors'])
        self.assertEqual(page['boards'][0]['result_units'][0]['state'],'current')

    @classmethod
    def setUpClass(cls):
        cls.template=authored_frame()

    def setUp(self):
        self.now=0
        self.frames=CapturedReads(clock=lambda:self.now,ttl_seconds=30,resource_bytes=lambda:0)
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

    def test_catalog_shares_match_meaning_without_hiding_conflicts(self):
        game=self.frame['status']['games'][0]
        game['matches']=[dict(status='matched',conflicts=[],revision=str(i),method='provider') for i in range(100)]
        game['matches'].append(dict(status='unresolved',conflicts=['schedule'],revision='conflict',method='provider'))
        first=self.read();catalog=first['games'][0]
        self.assertEqual(catalog['match_count'],101)
        self.assertEqual(catalog['matches'],[dict(status='matched',conflicts=[],method='provider'),
            dict(status='unresolved',conflicts=['schedule'],method='provider')])
        self.assertEqual(self.continuation(first)['games'],first['games'])

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

    def test_forward_pages_renew_inactivity_without_changing_captured_clocks(self):
        first=self.read(limit=20)
        self.now=25
        middle=self.continuation(first,offset=20,limit=20)
        self.now=45
        replay=self.continuation(first,offset=20,limit=20)
        self.assertEqual(middle,replay)
        self.now=54
        last=self.continuation(first,offset=40,limit=20)
        self.assertTrue(last['coverage']['complete'])
        self.assertEqual(first['read_at'],last['read_at'])
        self.assertEqual(first['read_expires_at'],last['read_expires_at'])
        self.assertEqual(self.snapshot.call_count,1)

    def test_page_replay_does_not_renew_inactivity(self):
        first=self.read()
        self.now=25
        self.continuation(first,offset=0)
        self.now=30
        with self.assertRaisesRegex(ValueError,'current_slate_read_expired'):
            self.continuation(first)

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

    def test_concurrent_tabs_cannot_evict_active_traversals(self):
        pages=[self.read() for _ in range(4)]
        with self.assertRaisesRegex(ValueError,'current_slate_read_capacity'):
            self.read()
        self.assertEqual(len(self.frames.frames),4)
        for first in pages:self.continuation(first)
        self.assert_completed_cache()

    def test_byte_capacity_refuses_and_fresh_read_can_recover(self):
        self.frames.maximum_bytes=4096
        with self.assertRaisesRegex(ValueError,'current_slate_read_capacity'):
            self.read()
        self.assertEqual(self.frames.retained_bytes,0)
        self.frames.maximum_bytes=64*1024*1024
        first=self.read();self.continuation(first)
        self.assert_completed_cache()

    def test_byte_pressure_refuses_new_capture_preserving_active_pages(self):
        first=self.read();size=self.frames.retained_bytes
        self.frames.maximum_bytes=size+100
        with self.assertRaisesRegex(ValueError,'current_slate_read_capacity'):
            self.read()
        self.assertEqual(len(self.frames.frames),1)
        self.assertEqual(self.frames.retained_bytes,size)
        self.continuation(first,offset=0)
        self.assertEqual(self.frames.retained_bytes,size)
        self.continuation(first)
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

class DisplayedProtection(TestCase):
    def test_displayed_and_selected_survive_new_capture_capacity(self):
        from app.storage.slate_reads import CapturedReads
        from app.storage.store import encoded
        now=[0.0]
        reads=CapturedReads(clock=lambda:now[0],resource_bytes=lambda:0,maximum_frames=2)
        row=encoded(dict(game_key='g',row=dict(facts={})))
        displayed=reads.capture({},[row],context='completed',authority='a')
        reads.lease(displayed.token)
        _,selected=reads.selection(displayed.token,'g')
        with self.assertRaisesRegex(ValueError,'current_slate_read_capacity'):
            reads.capture({},[row],context='completed',authority='a')
        self.assertEqual(set(reads.frames),{displayed.token,selected})
        now[0]=100;reads.lease(selected)
        self.assertEqual(reads.frames[selected].context,'selected')
        now[0]=121;reads.cleanup()
        self.assertIn(selected,reads.frames)
        self.assertNotIn(displayed.token,reads.frames)
        now[0]=221;reads.cleanup()
        self.assertFalse(reads.frames)

    def test_completed_inline_packet_retains_originals_without_boards(self):
        import json
        reads=CapturedReads(resource_bytes=lambda:0)
        facts=dict(selected_frame='exact-original',boards={'ev':'parent'},
            result_units={'u':dict(facts=dict(selected_frame='exact-unit',boards={'ev':'large'}))})
        packet=reads.freeze(encoded(dict(game_key='g',_facts_text=json.dumps(facts),_board_text='large-board')))
        record=reads.join_record('g',packet,dict(proof='capture'))
        captured=reads.capture(dict(games=[dict(game_key='g')]),[record],context='paging',authority='a')
        reads.account(captured,offset=0,limit=1,size=1,complete=True)
        saved,token=reads.selection(captured.token,'g')
        self.assertNotIn('_board_text',saved)
        self.assertEqual(saved['facts']['boards'],{'ev':'parent'})
        self.assertEqual(saved['facts']['result_units']['u']['facts']['boards'],{'ev':'large'})
        self.assertEqual(saved['facts']['selected_frame'],'exact-original')
        self.assertEqual(saved['facts']['result_units']['u']['facts']['selected_frame'],'exact-unit')

    def test_replacement_shares_only_identical_facts_and_releases_last_reference(self):
        import json
        from hashlib import sha256
        reads=CapturedReads(resource_bytes=lambda:0,maximum_bytes=64000)
        exact=''.join(sha256(str(i).encode()).hexdigest() for i in range(600))
        def record(board, original=exact):
            packet=reads.freeze(encoded(dict(game_key='g',_facts_text=json.dumps(dict(selected_frame=original)),_board_text=board)))
            return reads.join_record('g',packet,{'captured':'proof'})
        first=reads.capture(dict(games=[dict(game_key='g')]),[record('old')],context='paging',authority='a')
        reads.account(first,offset=0,limit=1,size=1,complete=True);reads.lease(first.token)
        before=reads.retained_bytes
        replacement=reads.capture(dict(games=[dict(game_key='g')]),[record('new')],context='paging',authority='a')
        self.assertEqual(len(reads.blobs),1)
        self.assertLess(reads.retained_bytes-before,6000)
        reads.discard(first.token)
        row=reads.decode(replacement.records[0])['row']
        self.assertEqual(json.loads(row['_facts_text'])['selected_frame'],exact)
        self.assertEqual(row['_board_text'],'new')
        reads.discard(replacement.token)
        self.assertFalse(reads.blobs)
        self.assertEqual(reads.retained_bytes,0)
