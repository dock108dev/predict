"""Disposable reproduction of global fanout, status noise and slow estimates."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase, skipUnless
from unittest.mock import patch
import asyncio
import threading

from app.storage import latest_board as latest
from tests import test_latest_board_sql as fixtures


class PublicationDependencyIdentity(TestCase):
    def frame(self):
        event=dict(id='event',revision='event-revision',pair=['NFL',['NFL:HOU','NFL:JAX']],
            start='2026-10-18T13:30:00+00:00',shared=[],participants={'NFL:JAX':'NFL:JAX'})
        def offer(cid,venue,predicate='win',event_id='event'):
            return dict(id=cid,event_id=event_id,venue=venue,native_market_id=cid,contract_revision='contract-1',
                offer_revision='offer-1',source_at='2026-10-17T15:00:00+00:00',received_at='2026-10-17T15:00:01+00:00',
                contract=dict(selection=dict(participant='NFL:JAX',predicate=predicate,signed_line=None),
                    market_identity=dict(family='moneyline',period='full_game')),scoring_dependency='scoped-1')
        own=offer('selected','kalshi');peer=offer('peer','polymarket_us');opposite=offer('opposite','polymarket_us','not_win')
        return dict(events={'event':event},offers={r['id']:r for r in (own,peer,opposite)},by_event={'event':[own,peer,opposite]},
            books={},states={},neighborhoods={},candidate_sets={})

    def test_scoped_registry_dependencies_track_own_and_unresolved_same_predicate_peers(self):
        from app.storage import observation_publication as publication
        frame=self.frame();selector=dict(events=['event'],occurrences=[],shared=[])
        selection=publication.selection(frame,frame['offers']['selected'])
        own=publication.own(frame,'selected');peers=publication.candidates(frame,selector,selection,[])
        # Opposing native predicates remain independent even if a review changes.
        other=deepcopy(frame);other['offers']['opposite']['scoring_dependency']='changed-opposite';other['candidate_sets']={}
        self.assertEqual(publication.own(other,'selected'),own)
        self.assertEqual(publication.candidates(other,selector,selection,[]),peers)
        # An unresolved same-predicate candidate needs the registry identity too:
        # changing terms may make it eligible without changing its numeric price.
        changed=deepcopy(frame);changed['offers']['peer']['scoring_dependency']='changed-peer';changed['candidate_sets']={}
        self.assertEqual(publication.own(changed,'selected'),own)
        self.assertNotEqual(publication.candidates(changed,selector,selection,[]),peers)
        changed['offers']['selected']['scoring_dependency']='changed-own'
        self.assertNotEqual(publication.own(changed,'selected'),own)

    def test_native_registry_data_is_not_a_global_observation_code_dependency(self):
        from app.storage.current_games import observation_binding
        before=observation_binding();read=Path.read_bytes
        def changed(path):
            value=read(path)
            return value+b'authored unrelated data edit' if 'native-scoring-scope' in path.parts else value
        with patch.object(Path,'read_bytes',changed):self.assertEqual(observation_binding(),before)

    def test_native_admission_code_changes_revoke_observation_authority(self):
        from app.storage.current_games import observation_binding
        before=observation_binding();read=Path.read_bytes
        for name in ('coverage.py','admission_enrichment.py','v1_comparison.py','current_sink.py'):
            with self.subTest(admission=name):
                def changed(path):
                    value=read(path)
                    return value+b'authored admission change' if path.parent.name=='collection' and path.name==name else value
                with patch.object(Path,'read_bytes',changed):
                    self.assertNotEqual(observation_binding(),before)

    def test_explicit_other_occurrence_between_same_teams_cannot_invalidate(self):
        from app.storage import observation_publication as publication
        frame=self.frame();frame['events']['event']['shared']=[['sportradar','game-one']]
        another=deepcopy(frame['events']['event'])
        another.update(id='rematch',revision='other-1',shared=[['sportradar','game-two']])
        frame['events']['rematch']=another
        selector=dict(events=['event'],occurrences=[[another['pair'],another['start']]],shared=[['sportradar','game-one']])
        before=publication.neighborhood(frame,selector)
        self.assertEqual([r[0] for r in before],['event'])
        frame['events']['rematch']['revision']='other-2';frame['neighborhoods']={}
        self.assertEqual(publication.neighborhood(frame,selector),before)

    def neutral_spread_frame(self):
        frame=self.frame();selected=frame['offers']['selected'];peer=frame['offers']['peer']
        frame['offers']={r['id']:r for r in (selected,peer)}
        frame['events']={};frame['by_event']={}
        for offer,eid,home,away in ((selected,'event','NFL:JAX','NFL:HOU'),
                                   (peer,'peer-event','NFL:HOU','NFL:JAX')):
            facts=dict(id=eid,competition='NFL',home=home,away=away,neutral_venue=True,
                participants={'Jacksonville':'NFL:JAX','Houston':'NFL:HOU'})
            frame['events'][eid]=dict(id=eid,provider=offer['venue'],native_event_id=eid,revision='event-1',
                facts=facts,pair=['NFL',['NFL:HOU','NFL:JAX']],start='2026-10-18T13:30:00+00:00',
                shared=[['sportradar','one-game']],participants={'NFL:JAX':'NFL:JAX','NFL:HOU':'NFL:HOU'})
            offer.update(event_id=eid,native_outcome_id='yes',native_side='yes')
            offer['contract']=dict(selection=dict(participant='NFL:JAX',predicate='cover',signed_line='-3.5'),
                market_identity=dict(family='spread',period='full_game'),
                comparison_source_metadata=dict(same_outcome=dict(
                    predicate=dict(domain='home_margin',operator='gt' if home=='NFL:JAX' else 'lt',
                        threshold='3.5' if home=='NFL:JAX' else '-3.5',subject_id=None),
                    equality=dict(treatment='not_feasible',payout=None,refund_fees='not_applicable',unknown_reason=None),
                    scoring=dict(overtime='unknown'))))
            frame['by_event'][eid]=[offer]
        return frame

    def test_neutral_reversed_role_scope_correction_invalidates_possible_peer(self):
        from app.storage import observation_publication as publication
        frame=self.neutral_spread_frame();original=deepcopy(frame)
        selected=publication.selection(frame,frame['offers']['selected'])
        peer=publication.selection(frame,frame['offers']['peer'])
        self.assertNotEqual(selected['condition'],peer['condition'])
        self.assertTrue(publication._same_candidate(selected,peer))
        self.assertEqual(frame,original)  # Original roles, line and predicate survive.
        selector=dict(events=['event'],occurrences=[[frame['events']['event']['pair'],frame['events']['event']['start']]],
            shared=[['sportradar','one-game']])
        before=publication.candidates(frame,selector,selected,[])  # Peer scope is not supported yet.
        changed=deepcopy(frame);changed['candidate_sets']={}
        changed['offers']['peer']['scoring_dependency']='new-supported-scope-rule'
        self.assertNotEqual(publication.candidates(changed,selector,selected,[]),before)

    def test_neutral_candidate_keeps_explicit_roles_predicate_and_rematch_boundaries(self):
        from app.storage import observation_publication as publication
        frame=self.neutral_spread_frame()
        selected=publication.selection(frame,frame['offers']['selected'])
        nonneutral=deepcopy(frame);nonneutral['events']['peer-event']['facts']['neutral_venue']=False
        self.assertFalse(publication._same_candidate(selected,publication.selection(nonneutral,nonneutral['offers']['peer'])))
        opposite=deepcopy(frame);facts=opposite['offers']['peer']['contract']
        facts['selection'].update(participant='NFL:HOU',signed_line='3.5')
        facts['comparison_source_metadata']['same_outcome']['predicate'].update(operator='gt')
        self.assertFalse(publication._same_candidate(selected,publication.selection(opposite,opposite['offers']['peer'])))
        selector=dict(events=['event'],occurrences=[[frame['events']['event']['pair'],frame['events']['event']['start']]],
            shared=[['sportradar','one-game']])
        before=publication.candidates(frame,selector,selected,[])
        rematch=deepcopy(frame['events']['peer-event']);rematch.update(id='rematch',shared=[['sportradar','another-game']])
        frame['events']['rematch']=rematch
        offer=deepcopy(frame['offers']['peer']);offer.update(id='rematch-peer',event_id='rematch',scoring_dependency='other-rule')
        frame['offers'][offer['id']]=offer;frame['by_event']['rematch']=[offer]
        frame['candidate_sets']={};frame['neighborhoods']={}
        self.assertEqual(publication.candidates(frame,selector,selected,[]),before)


@skipUnless(fixtures.SOCKET,'Explicit maintained disposable DA PostgreSQL lane required')
class PublicationRepairSQL(IsolatedAsyncioTestCase):
    async def test_source_live_planning_keeps_complete_components_and_clocks(self):
        self.fresh_sources()
        with self.connect() as db:
            before=latest.capture_batches(db)
            planned=latest.prioritize_sources(db,before,self.at.isoformat())
            self.assertEqual(set(map(tuple,before)),set(map(tuple,planned)))
            with patch.object(latest,'capture_reservation',wraps=latest.capture_reservation) as reserve:
                result=latest.reconcile(db,at=self.at.isoformat(),observations_only=True,admission={})
        self.assertTrue(result['published'],result)
        # One planning reservation plus pre-admission and snapshot recheck per
        # processed component; no unused all-catalog packing size scans.
        self.assertLessEqual(reserve.call_count,1+2*len(result['batches']))
        self.assertEqual([b['events'] for b in result['batches']],list(map(len,planned)))

    async def test_estimate_planning_turn_reaches_real_work_with_coverage_waiting(self):
        from app.collection.background_work import BackgroundWork
        self.fresh_sources()
        work=BackgroundWork(sampler=lambda:64*1024*1024)
        original=latest.capture_batches
        def plan(db):
            with work.claim('coverage',32*1024*1024) as queued:self.assertFalse(queued)
            return original(db)
        with patch('app.collection.background_work.BACKGROUND',work),patch.object(latest,'capture_batches',side_effect=plan):
            with self.connect() as db:result=latest.reconcile(db,at=self.at.isoformat(),admission={})
        self.assertGreater(result['computed'],0,result)
        self.assertTrue(result['published'],result)
        self.assertEqual(work.snapshot()['reserved_bytes'],0)

    connect=classmethod(fixtures.LatestBoardSQL.connect.__func__)
    setUpClass=classmethod(fixtures.LatestBoardSQL.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.LatestBoardSQL.tearDownClass.__func__)
    asyncSetUp=fixtures.LatestBoardSQL.asyncSetUp
    admit=fixtures.LatestBoardSQL.admit
    reconcile=fixtures.LatestBoardSQL.reconcile
    rows=fixtures.LatestBoardSQL.rows
    snapshot=fixtures.LatestBoardSQL.snapshot
    changed_first=fixtures.LatestBoardSQL.changed_first
    fresh_sources=fixtures.LatestBoardSQL.fresh_sources

    async def test_scoped_reservation_counts_prior_optional_boards(self):
        from app.storage.store import hashed
        ids=[hashed(member) for member in self.first['members']]
        with self.connect() as db:
            before=latest.capture_reservation(db,event_ids=ids)
            latest.reconcile(db,at=self.at.isoformat())
            size=db.execute("SELECT octet_length(facts::text) n FROM latest_board WHERE game_key=%s",(self.first['game_key'],)).fetchone()['n']
            after=latest.capture_reservation(db,event_ids=ids)
        self.assertGreaterEqual(after-before,size*8-1024*1024)
        self.assertGreater(after,before)

    async def test_new_peer_after_planning_requires_capacity_before_decoding(self):
        from app.storage.store import hashed,encoded
        members=[tuple(member) for member in self.first['members']]
        def own(member):
            return [r for r in self.records if (r['quote']['source']['provider'],r['quote']['source']['native_event_id'])==member]
        peer=max(members,key=lambda member:len(encoded(own(member))))
        with self.connect() as db:
            db.execute('DELETE FROM current_event WHERE id=%s',(hashed(peer),))
            ids=next(group for group in latest.capture_batches(db) if hashed(next(m for m in members if m!=peer)) in group)
            reserved=latest.capture_reservation(db,observations_only=True,event_ids=ids)
        self.admit(own(peer))
        with self.connect() as db,patch.object(latest,'read_context',side_effect=AssertionError('changed capture decoded before admission')):
            result=latest._reconcile(db,at=self.at.isoformat(),observations_only=True,event_ids=ids,reservation_bytes=reserved)
        self.assertEqual(result['reason'],'background_capture_changed')
        self.assertFalse(self.rows())
        with self.connect() as db:
            self.assertTrue(latest.reconcile(db,at=self.at.isoformat(),observations_only=True)['published'])
        board=latest.board(self.snapshot(),self.first['game_key'],view='odds',filter='all')
        fixtures.LatestBoardSQL.assert_source_frame(self,board)

    async def test_whole_capture_refuses_but_complete_peer_batches_publish_and_withdraw(self):
        from app.collection.background_work import BackgroundWork
        from app.storage.store import hashed
        records=deepcopy(self.records);second={tuple(m) for m in self.second['members']}
        for record in records:
            source=record['quote']['source']
            if (source['provider'],source['native_event_id']) in second:
                record.setdefault('comparison_source_metadata',{})['original_wording']={'rules':'authored neighboring game '+('x'*32768)}
        self.fresh_sources(records)
        with self.connect() as db:
            groups=latest.capture_batches(db)
            sizes=[latest.capture_reservation(db,observations_only=True,event_ids=ids) for ids in groups]
            whole=latest.capture_reservation(db,observations_only=True)
        self.assertGreater(len(groups),1)
        bound=max(sizes)+1024
        self.assertGreater(whole,bound)
        work=BackgroundWork(sampler=lambda:64*1024*1024,source_runway_bytes=bound)
        with work.claim('observations',whole,source=True) as refused:
            self.assertFalse(refused);self.assertEqual(refused.reason,'background_source_capacity')
        original=latest.read_context;captures=[]
        def selected(db,**kwargs):
            ids=kwargs['event_ids'];captures.append(set(ids))
            return original(db,**kwargs)
        with patch('app.collection.background_work.BACKGROUND',work),patch.object(latest,'read_context',side_effect=selected):
            with self.connect() as db:result=latest.reconcile(db,at=self.at.isoformat(),observations_only=True)
        self.assertTrue(result['published'],result)
        self.assertEqual(set(self.rows()),{self.first['game_key'],self.second['game_key']})
        for game in (self.first,self.second):
            members={hashed(member) for member in game['members']}
            self.assertTrue(any(members<=ids for ids in captures))
            board=latest.board(self.snapshot(),game['game_key'],view='odds',filter='all')
            fixtures.LatestBoardSQL.assert_source_frame(self,board)
            self.assertIsNone(board['calculated_at'])
        # A later authoritative withdrawal retires only that occurrence. Its
        # valid neighbor keeps exact original clocks and native identities.
        second=self.rows()[self.second['game_key']]['facts']['boards']['odds']['prices']
        first_ids=[hashed(member) for member in self.first['members']]
        with self.connect() as db:
            db.execute('DELETE FROM current_event WHERE id=ANY(%s)',(first_ids,))
            latest.reconcile(db,at=self.at.isoformat(),observations_only=True)
        self.assertNotIn(self.first['game_key'],set(self.rows()))
        self.assertNotIn(self.first['game_key'],{g['game_key'] for g in self.snapshot()['status']['games']})
        self.assertEqual(self.rows()[self.second['game_key']]['facts']['boards']['odds']['prices'],second)
        self.service.dispatch=False;self.state.write(self.service)
        stopped=latest.board(self.snapshot(),self.second['game_key'],view='odds',filter='all')
        self.assertTrue(stopped['prices'])
        self.assertTrue(all(q['freshness']['status']=='historical' for q in stopped['prices']))
        self.assertIn('updates_stopped',stopped['background_reasons'])

    async def test_oversized_component_cannot_block_valid_neighbor(self):
        from app.collection.background_work import BackgroundWork
        from app.storage.store import hashed
        self.fresh_sources()
        members={tuple(m) for m in self.first['members']};records=deepcopy(self.records)
        for record in records:
            q=record['quote']
            if (q['source']['provider'],q['source']['native_event_id']) in members:
                record.setdefault('comparison_source_metadata',{})['original_wording']={'rules':'authored oversized game '*2048}
        self.admit(records)
        with self.connect() as db:
            groups=latest.capture_batches(db)
            good=next(ids for ids in groups if hashed(self.second['members'][0]) in ids)
            bound=max(latest.capture_reservation(db,observations_only=True,event_ids=good),
                latest.capture_reservation(db,observations_only=True,event_ids=[]))+1024
        work=BackgroundWork(sampler=lambda:64*1024*1024,source_runway_bytes=bound)
        with patch('app.collection.background_work.BACKGROUND',work):
            with self.connect() as db:result=latest.reconcile(db,at=self.at.isoformat(),observations_only=True)
        self.assertTrue(result['published'],result)
        self.assertTrue(any(b['reason']=='background_source_capacity' for b in result['batches']))
        self.assertIn(self.second['game_key'],self.rows())
        self.assertNotIn(self.first['game_key'],set(self.rows()))
        self.assertTrue(latest.board(self.snapshot(),self.second['game_key'],view='odds',filter='all')['prices'])

    async def test_unrelated_game_update_preserves_published_game(self):
        self.fresh_sources();self.reconcile()
        before=latest.board(self.snapshot(),self.second['game_key'],view='odds',filter='all')
        self.changed_first()
        after=latest.board(self.snapshot(),self.second['game_key'],view='odds',filter='all')
        self.assertTrue(all(q['observation_display']['state']=='current' for q in after['prices']))
        self.assertEqual([(q['original'],q['times']) for q in before['prices']],[(q['original'],q['times']) for q in after['prices']])
        changed=latest.board(self.snapshot(),self.first['game_key'],view='odds',filter='all')
        self.assertTrue(any(q['observation_display']['state']=='pending' for q in changed['prices']))
        self.assertTrue(any(q['observation_display']['state']=='current' for q in changed['prices']))
        # Candidate changes withdraw comparisons even when an observation itself
        # is unchanged. Its own original clocks remain inspectable.
        self.assertTrue(any('current_dependencies_changed' in q.get('gross_comparison',{}).get('reason_codes',[])
                            for q in changed['prices'] if q.get('gross_comparison',{}).get('available')))

    async def test_routine_source_status_clocks_do_not_revoke_prices(self):
        self.fresh_sources();self.reconcile()
        before=self.snapshot()['status']['runtime']
        self.at+=timedelta(seconds=1)
        self.service.states['kalshi'].update(source_at=self.at.isoformat(),received_at=self.at.isoformat(),last_update_at=self.at.isoformat())
        self.state.write(self.service)
        with self.connect() as db:
            from app.storage.current_rows import CurrentRowStore
            CurrentRowStore(db).upsert_records([],now=self.at.isoformat(),source_status=deepcopy(self.service.states))
        frame=self.snapshot()
        self.assertNotIn('runtime_authority_changed',frame['observation_reasons'])
        self.assertEqual(latest.runtime_identity(frame['owner']),before)
        for game in (self.first,self.second):
            board=latest.board(frame,game['game_key'],view='odds',filter='all')
            self.assertTrue(all(q['observation_display']['state']=='current' for q in board['prices']))

    async def test_observations_commit_before_optional_discovery_and_estimates(self):
        self.fresh_sources();real=latest.discover;seen=[]
        def delayed(*args,**kwargs):
            # An independent connection proves an actual committed publication
            # exists while the slow optional stage has not returned.
            frame=self.snapshot()
            self.assertEqual(set(frame['rows']),{self.first['game_key'],self.second['game_key']})
            for game in (self.first,self.second):
                odds=latest.board(frame,game['game_key'],view='odds',filter='all')
                from app.dashboard.comparison_board import expand_price_fields
                expand_price_fields(odds)
                self.assertTrue(all(q['observation_display']['state']=='current' for q in odds['prices']))
            seen.append(True)
            return real(*args,**kwargs)
        with patch.object(latest,'discover',side_effect=delayed):result=self.reconcile()
        self.assertTrue(seen);self.assertTrue(result['published'])

    async def test_candidate_add_remove_and_source_health_invalidate_immediately(self):
        self.fresh_sources();self.reconcile();key=self.first['game_key']
        before=latest.board(self.snapshot(),key,view='odds',filter='all')
        candidate=deepcopy(next(r for r in self.records if r['quote']['venue']=='novig'
            and [r['quote']['source']['provider'],r['quote']['source']['native_event_id']] in self.first['members']))
        candidate['quote']['source']['native_market_id']+='-new-candidate'
        self.admit([candidate])
        added=latest.board(self.snapshot(),key,view='odds',filter='all')
        self.assertTrue(all(q['observation_display']['state']=='current' for q in added['prices']))
        self.assertIn('current_dependencies_changed',added['comparison_reasons'])
        with self.connect() as db:
            from app.storage.current_rows import contract_id
            db.execute('DELETE FROM current_contract WHERE id=%s',(contract_id(candidate),))
        restored=latest.board(self.snapshot(),key,view='odds',filter='all')
        self.assertEqual(restored['comparison_reasons'],[])
        failure=dict(state='unavailable',reason_code='fixture_failure',reason='Fixture source failure')
        with self.connect() as db:
            from app.storage.current_rows import CurrentRowStore
            CurrentRowStore(db).upsert_records([],now=self.at.isoformat(),source_status=dict(kalshi=failure))
        failed=latest.board(self.snapshot(),key,view='odds',filter='all')
        self.assertTrue(all(q['observation_display']['state']=='last_known' for q in failed['prices'] if q['venue']=='kalshi'))
        self.assertTrue(all(q['observation_display']['state']=='current' for q in failed['prices'] if q['venue']!='kalshi'))
        self.assertEqual([(q['original'],q['times']) for q in before['prices']],[(q['original'],q['times']) for q in failed['prices']])

    async def test_source_owner_keeps_publishing_while_estimate_owner_is_blocked(self):
        self.fresh_sources();self.reconcile();self.changed_first()
        entered=threading.Event();release=threading.Event();real=latest.calculate_current
        def slow(*args,**kwargs):
            entered.set()
            if not release.wait(8):raise AssertionError('Fixture slow-stage deadline')
            return real(*args,**kwargs)
        owner=latest.LatestBoardOwner(self.service)
        with patch.object(latest,'connect',side_effect=self.connect),patch.object(latest,'calculate_current',side_effect=slow):
            await owner.start()
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait,3))
                changed=self.changed_first();found=False
                for _ in range(35):
                    odds=latest.board(self.snapshot(),self.first['game_key'],view='odds',filter='all')
                    found=any(q['source']==changed['quote']['source'] and q['times']['source_at']==changed['quote']['times']['source_at']
                              and q['observation_display']['state']=='current' for q in odds['prices'])
                    if found:break
                    await asyncio.sleep(0.1)
                self.assertTrue(found,'An optional blocked estimate prevented independent source publication')
                self.assertFalse(release.is_set())
            finally:
                release.set();await owner.close()

    async def test_opposite_outcome_change_keeps_unaffected_comparison(self):
        self.fresh_sources();self.reconcile();key=self.first['game_key']
        changed=self.changed_first();participant=changed['selection']['participant']
        odds=latest.board(self.snapshot(),key,view='odds',filter='all')
        unaffected=[q for q in odds['prices'] if q['selection']['participant']!=participant and q.get('gross_comparison',{}).get('available')]
        self.assertTrue(unaffected)
        self.assertTrue(all('current_dependencies_changed' not in q['gross_comparison']['reason_codes'] for q in unaffected))

    async def test_optional_worker_failure_preserves_sources_source_worker_failure_revokes(self):
        self.fresh_sources();self.reconcile();key=self.first['game_key']
        self.service.background_calculations=dict(board='unavailable',observations='running');self.state.write(self.service)
        healthy=latest.board(self.snapshot(),key,view='odds',filter='all')
        self.assertTrue(all(q['observation_display']['state']=='current' for q in healthy['prices']))
        self.service.background_calculations['observations']='unavailable';self.state.write(self.service)
        failed=latest.board(self.snapshot(),key,view='odds',filter='all')
        self.assertIn('background_observations_unavailable',failed['observation_reasons'])
        self.assertFalse(any(q['observation_display']['state']=='current' for q in failed['prices']))

    async def test_temporal_source_reselection_cannot_be_overwritten_by_older_estimate(self):
        self.fresh_sources();key=self.first['game_key']
        future=deepcopy(next(r for r in self.records if r['quote']['venue']=='novig'
            and [r['quote']['source']['provider'],r['quote']['source']['native_event_id']] in self.first['members']))
        future['quote']['original']['value']='10.0'
        if 'native_value' in future['quote']['original']:future['quote']['original']['native_value']='10.0'
        clock=(self.at+timedelta(seconds=2)).isoformat()
        future['quote']['times'].update(source_at=clock,received_at=clock)
        future['quote'].get('provider_clocks',{}).update(book=clock,market=clock)
        self.admit([future]);self.reconcile();old=list(self.rows().values())
        with self.connect() as db:
            proof=latest.marker(db);owner=latest.runtime(db,at=self.at.isoformat())
            status=db.execute('SELECT facts FROM latest_board_status').fetchone()['facts']
        self.at+=timedelta(seconds=3);self.state.write(self.service)
        with patch.object(latest,'discover',side_effect=AssertionError('Optional stage forbidden for source-only temporal publication')):
            with self.connect() as db:result=latest.reconcile(db,at=self.at.isoformat(),observations_only=True)
        self.assertTrue(result['published'])
        refreshed=latest.board(self.snapshot(),key,view='odds',filter='all')
        selected=[q for q in refreshed['prices'] if q['venue']!='novig' and q['selection']['participant']==future['selection']['participant']
                  and q.get('current_comparison',{}).get('comparison_venue')=='novig']
        self.assertTrue(selected)
        self.assertTrue(all(q['current_comparison']['display_status']=='current' for q in selected))
        with self.connect() as db:self.assertFalse(latest.publish(db,captured_marker=proof,captured_runtime=owner,status=status,rows=old))
        still=latest.board(self.snapshot(),key,view='odds',filter='all')
        self.assertEqual(refreshed['prices'],still['prices'])

    async def test_incompatible_scope_price_is_irrelevant_but_scope_change_invalidates(self):
        from app.comparison.native_scoring_scope import attach
        self.fresh_sources();key=self.first['game_key']
        native=deepcopy(next(r for r in self.records if r['quote']['venue']=='kalshi'
            and r['selection']['predicate']=='win'
            and [r['quote']['source']['provider'],r['quote']['source']['native_event_id']] in self.first['members']))
        # The general resolver now supports this retained native class. Author
        # a coherent two-sided source exception, rather than treating its old
        # registry absence as incompatible scope. Explicit tie-to-NO treatment
        # gives the same normal winner predicate as the retained sportsbook
        # peers; overtime alone keeps these authored native inputs separate.
        market=native['quote']['source']['native_market_id']
        authored=[deepcopy(r) for r in self.records if r['quote']['venue']=='kalshi'
            and r['quote']['source']['native_market_id']==market]
        def scope(value):
            text='Authored source exception. Overtime is '+value+'. If the game ends in a tie, the market resolves to No.'
            for row in authored:
                metadata=row['comparison_source_metadata']
                for field in ('scoring_scope','same_outcome'):metadata.pop(field,None)
                metadata['rules_secondary']=text;metadata['overtime']=value
                metadata['original_wording']['rules_secondary']=text
                metadata['native_terms']['rules_secondary']=text
                metadata['combined_native_binding']['original_terms']['rules_secondary']=text
                row['comparison_scope']=dict(overtime=value)
                row.update(attach(row,at=self.at.isoformat()))
                self.assertEqual(row['comparison_source_metadata']['scoring_scope']['status'],'supported')
                self.assertEqual(row['comparison_scope']['overtime'],value)
                self.assertEqual(row['comparison_source_metadata']['same_outcome']['equality']['treatment'],'predicate')
        for row in authored:row['quote']['times'].update(source_at=self.at.isoformat(),received_at=self.at.isoformat())
        scope('excluded');self.admit(authored);self.reconcile()
        native=next(r for r in authored if r['selection']['predicate']=='win')
        participant=native['selection']['participant'];self.at+=timedelta(seconds=1);self.state.write(self.service)
        native['quote']['original']['value']='0.19'
        if 'native_value' in native['quote']['original']:native['quote']['original']['native_value']='0.19'
        native['quote']['times'].update(source_at=self.at.isoformat(),received_at=self.at.isoformat())
        self.admit([native])
        unrelated=latest.board(self.snapshot(),key,view='odds',filter='all')
        supported=[q for q in unrelated['prices'] if q['venue']!='kalshi' and q['selection']['participant']==participant
                   and q.get('gross_comparison',{}).get('available')]
        self.assertTrue(supported)
        self.assertTrue(all('current_dependencies_changed' not in q['gross_comparison']['reason_codes'] for q in supported))
        observed=next(q for q in unrelated['prices'] if q['source']==native['quote']['source'])
        self.assertTrue(observed['same_outcome']['supported'])
        self.assertTrue(all(q['same_outcome']['key']!=observed['same_outcome']['key'] for q in supported))
        # A metadata change can admit the previously unresolved candidate, even
        # with unchanged numeric price/source clocks. It must invalidate at once.
        original=deepcopy(native['quote']);scope('included');self.admit(authored)
        self.assertEqual(native['quote'],original)
        pending=latest.board(self.snapshot(),key,view='odds',filter='all')
        self.assertTrue(all('current_dependencies_changed' in q['gross_comparison']['reason_codes'] for q in pending['prices']
            if q['quote_id'] in {q['quote_id'] for q in supported}))

    async def test_native_registry_dependency_is_scoped_to_exact_target_and_peer_candidates(self):
        from app.comparison import native_scoring_scope as scope
        from app.storage.current_rows import contract_id
        from app.storage.store import hashed
        self.fresh_sources();self.reconcile()
        original_frame=self.snapshot()
        before=latest.board(original_frame,self.second['game_key'],view='odds',filter='all')
        before_affected=latest.board(original_frame,self.first['game_key'],view='odds',filter='all')
        target=next(r for r in self.records if r['quote']['venue']=='kalshi'
            and r['selection']['predicate']=='win'
            and [r['quote']['source']['provider'],r['quote']['source']['native_event_id']] in self.first['members'])
        q=target['quote'];source=q['source']
        key=(source['provider'],source['native_event_id'],source['native_market_id'],source['native_outcome_id'],source.get('native_side',''))
        real=scope.publication_dependencies
        def changed(keys,contexts=None):
            return [hashed([prior,'authored_changed_target_terms']) if native==key else prior
                for native,prior in zip(keys,real(keys,contexts=contexts))]
        with patch.object(scope,'publication_dependencies',side_effect=changed):
            frame=self.snapshot()
            self.assertNotEqual(frame['read_revision'],original_frame['read_revision'])
            # No ingress, routine clock change or global engine change wakes
            # this owner. The scoped dependency must bypass its unchanged path.
            with self.connect() as db:
                result=latest.reconcile(db,at=self.at.isoformat(),observations_only=True)
            self.assertTrue(result['published'])
            refreshed=self.snapshot()
            current=latest.board(refreshed,self.first['game_key'],view='odds',filter='all')
            self.assertTrue(all(row['observation_display']['state']=='current' for row in current['prices']))
        affected=latest.board(frame,self.first['game_key'],view='odds',filter='all')
        from app.dashboard.comparison_board import expand_price_fields
        expand_price_fields(affected)
        own=[row for row in affected['prices'] if row['source']==source]
        self.assertTrue(own)
        self.assertTrue(all(row['observation_display']['state']=='pending' for row in own))
        # An unresolved native target is still a candidate. New supported terms
        # must withdraw its opposite-source selection until background matching.
        candidates=[row for row in affected['prices'] if row['venue']!='kalshi'
            and row['selection']['participant']==target['selection']['participant']
            and row['selection']['predicate']==target['selection']['predicate']]
        self.assertTrue(candidates)
        self.assertTrue(all('current_dependencies_changed' in frame['dependency_reasons'][self.first['game_key']]['comparisons'].get(
            contract_id(dict(quote=row)),[]) for row in candidates))
        unchanged=latest.board(frame,self.second['game_key'],view='odds',filter='all')
        self.assertTrue(all(row['observation_display']['state']=='current' for row in unchanged['prices']))
        self.assertEqual(before['prices'],unchanged['prices'])
        self.assertEqual([(row['original'],row['times']) for row in own],
            [(row['original'],row['times']) for row in before_affected['prices'] if row['source']==source])

    async def test_shared_native_rule_dependency_only_withdraws_applicable_game(self):
        from app.comparison import native_scoring_scope as scope
        from app.storage.store import hashed
        self.fresh_sources();self.reconcile()
        native=next(r for r in self.records if r['quote']['venue']=='kalshi'
            and [r['quote']['source']['provider'],r['quote']['source']['native_event_id']] in self.first['members'])
        event=native['quote']['source']['native_event_id'];real=scope.publication_dependencies
        def changed(keys,contexts=None):
            return [hashed([prior,'authored_changed_governing_rule']) if key[:2]==('kalshi',event) else prior
                for key,prior in zip(keys,real(keys,contexts=contexts))]
        with patch.object(scope,'publication_dependencies',side_effect=changed):frame=self.snapshot()
        affected=latest.board(frame,self.first['game_key'],view='odds',filter='all')
        from app.dashboard.comparison_board import expand_price_fields
        expand_price_fields(affected)
        applicable=[row for row in affected['prices'] if row['venue']=='kalshi' and row['source']['native_event_id']==event]
        unaffected=[row for row in affected['prices'] if not (row['venue']=='kalshi' and row['source']['native_event_id']==event)]
        self.assertTrue(applicable)
        self.assertTrue(any(row['venue']=='kalshi' for row in unaffected))  # Other native family event aliases survive.
        self.assertTrue(all(row['observation_display']['state']=='pending' for row in applicable))
        self.assertTrue(all(row['observation_display']['state']=='current' for row in unaffected))
        self.assertIn('current_dependencies_changed',affected['comparison_reasons'])
        other=latest.board(frame,self.second['game_key'],view='odds',filter='all')
        self.assertEqual(other['observation_reasons'],[])
        self.assertEqual(other['comparison_reasons'],[])
        self.assertTrue(all(row['observation_display']['state']=='current' for row in other['prices']))

    async def test_source_publication_ignores_optional_engine_and_worker_state_changes(self):
        self.fresh_sources()
        with self.connect() as db:
            result=latest.reconcile(db,at=self.at.isoformat(),observations_only=True)
            self.assertTrue(result['published'])
            proof=latest.marker(db);owner=latest.runtime(db,at=self.at.isoformat())
            status=db.execute('SELECT facts FROM latest_board_status').fetchone()['facts']
        rows=list(self.rows().values())
        self.assertTrue(status['observation_only'])
        self.service.background_calculations=dict(board='unavailable',observations='running');self.state.write(self.service)
        with patch.object(latest,'engine_binding',return_value='authored_optional_engine_change'):
            with self.connect() as db:
                self.assertTrue(latest.publish(db,captured_marker=proof,captured_runtime=owner,status=status,rows=rows))
            frame=self.snapshot()
        for game in (self.first,self.second):
            odds=latest.board(frame,game['game_key'],view='odds',filter='all')
            from app.dashboard.comparison_board import expand_price_fields
            expand_price_fields(odds)
            self.assertTrue(all(row['observation_display']['state']=='current' for row in odds['prices']))

    async def test_observation_code_change_republishes_unchanged_sources_despite_new_global_status(self):
        from psycopg.types.json import Jsonb
        self.fresh_sources();self.reconcile();original=self.rows()
        key=self.first['game_key'];old=deepcopy(original[key])
        with patch.object(latest,'observation_binding',return_value='authored-new-observation-code'):
            # Another game may have updated the global status already. That
            # status cannot certify the algorithm used by each retained row.
            with self.connect() as db:
                status=db.execute('SELECT facts FROM latest_board_status').fetchone()['facts']
                status['observation_binding']='authored-new-observation-code'
                db.execute('UPDATE latest_board_status SET facts=%s',(Jsonb(status),))
            pending=self.snapshot()
            self.assertNotIn('matching_binding_changed',pending['observation_reasons'])
            self.assertIn('matching_binding_changed',pending['dependency_reasons'][key]['all'])
            self.assertTrue(all(row['observation_display']['state']=='pending'
                for row in latest.board(pending,key,view='odds',filter='all')['prices']))
            with self.connect() as db:
                result=latest.reconcile(db,at=self.at.isoformat(),observations_only=True)
            self.assertTrue(result['published'])
            refreshed=self.snapshot();current=latest.board(refreshed,key,view='odds',filter='all')
            self.assertTrue(all(row['observation_display']['state']=='current' for row in current['prices']))
            self.assertEqual(self.rows()[key]['facts']['observation_binding'],'authored-new-observation-code')
            before=original[key]['facts']['boards']['odds']['prices']
            self.assertEqual([(row['source'],row['original'],row['times']) for row in current['prices']],
                [(row['source'],row['original'],row['times']) for row in before])
            # A delayed owner cannot label its older row with the new status.
            with self.connect() as db:
                proof=latest.marker(db);owner=latest.runtime(db,at=self.at.isoformat())
                status=db.execute('SELECT facts FROM latest_board_status').fetchone()['facts']
                self.assertFalse(latest.publish(db,captured_marker=proof,captured_runtime=owner,status=status,rows=[old]))

    async def test_legacy_row_without_observation_binding_rebuilds_only_that_game(self):
        from psycopg.types.json import Jsonb
        self.fresh_sources();self.reconcile();original=self.rows();key=self.first['game_key']
        legacy=deepcopy(original[key]['facts']);legacy.pop('observation_binding')
        for row in legacy['boards']['odds']['prices']:
            row['current_comparison']['reason']='authored stale diagnostic'
        with self.connect() as db:
            db.execute('UPDATE latest_board SET facts=%s WHERE game_key=%s',(Jsonb(legacy),key))
        frame=self.snapshot()
        self.assertIn('matching_binding_changed',frame['dependency_reasons'][key]['all'])
        self.assertEqual(frame['dependency_reasons'][self.second['game_key']]['all'],[])
        with self.connect() as db:
            result=latest.reconcile(db,at=self.at.isoformat(),observations_only=True)
        self.assertTrue(result['published']);self.assertEqual(result['reused'],1)
        updated=self.rows()
        self.assertEqual(updated[self.second['game_key']],original[self.second['game_key']])
        self.assertEqual(updated[key]['facts']['observation_binding'],latest.observation_binding())
        self.assertTrue(all(row['current_comparison']['reason']!='authored stale diagnostic'
            for row in updated[key]['facts']['boards']['odds']['prices']))
