from copy import deepcopy
from unittest import TestCase
from app.comparison.game_phase import price_phase
from app.dashboard.browse_sessions import BrowseSessions
from app.dashboard.trade_desk import page
from tests.test_trade_desk import quote,result


class LiveDataFollowup(TestCase):
    def test_presentation_identity_separation_preserves_control_and_fixture_identity(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        from app.collection.current_policy import candidate
        with TemporaryDirectory() as temp:
            root=Path(temp);static=root/'app/dashboard/opportunity_static';static.mkdir(parents=True)
            ui=static/'desk.js';ui.write_text('old')
            control=root/'app/control.py';control.write_text('old')
            fixture=root/'app/terms.html';fixture.write_text('old')
            with patch('app.collection.current_policy.ROOT',root):
                before=candidate()[0];ui.write_text('new');self.assertEqual(before,candidate()[0])
                control.write_text('new');self.assertNotEqual(before,candidate()[0])
                before=candidate()[0];fixture.write_text('new');self.assertNotEqual(before,candidate()[0])
    def test_native_event_state_preserves_explicit_source_lifecycle(self):
        from app.collection.admission_enrichment import enrich_game
        event=dict(source='polymarket_us',competition='NBA',participants={},_native=dict(gameId=1,
            live=False,ended=False,eventState=dict(gameId=1,live=True,ended=False,updatedAt='2026-11-07T17:00:00Z')))
        self.assertTrue(enrich_game(event)['status']['live'])
        event['_native']['eventState'].update(gameId=2)
        self.assertEqual(enrich_game(event)['status'],{'identity_conflict':True})
        self.assertEqual(price_phase(dict(enrich_game(event),scheduled_start='2026-11-08T00:00:00Z'),{},'2026-11-07T18:00:00Z')['reason'],'event_lifecycle_identity_conflict')
    def test_matchup_title_uses_participants_not_a_different_market_title(self):
        row=quote('one','kalshi');row['game_title']='Brown–Yale Total Points'
        data=result(row);data['games']=[dict(game_key='game',participants=[dict(id='b',name='Brown'),dict(id='y',name='Yale')])]
        g=page(data,{},('ev','conditional_return_percent',0,25))['rows'][0]
        self.assertEqual(g['game_title'],'Brown vs. Yale')
        self.assertEqual(g['market']['market'],'spread')
        self.assertEqual(g['source_titles'],['Brown–Yale Total Points'])
    def test_phase_requires_post_kickoff_market_clock_and_expires(self):
        event={'scheduled_start':'2026-11-07T17:00:00Z'}
        q={'source':{'provider':'the_odds_api'},'times':{'source_at':'2026-11-07T17:01:00Z','received_at':'2026-11-07T17:01:01Z'},'provider_clocks':{'market':'2026-11-07T17:01:00Z'}}
        self.assertEqual(price_phase(event,q,'2026-11-07T16:59:00Z')['state'],'scheduled')
        self.assertIsNone(price_phase(event,q,'2026-11-07T17:01:02Z')['reason'])
        self.assertEqual(price_phase(event,q,'2026-11-07T17:01:16Z')['reason'],'live_price_expired')
        old=deepcopy(q);old['provider_clocks']['market']='2026-11-07T16:59:00Z'
        self.assertEqual(price_phase(event,old,'2026-11-07T17:01:02Z')['state'],'unknown')
        q['source']['provider']='kalshi'
        self.assertEqual(price_phase(event,q,'2026-11-07T17:01:02Z')['state'],'unknown')
        for status,expected in [({'live':True},'live'),({'status':'suspended'},'suspended'),({'ended':True},'final')]:
            self.assertEqual(price_phase(dict(event,status=status),q,'2026-11-07T17:01:02Z')['state'],expected)

    def test_browse_membership_survives_insert_reorder_and_removal(self):
        clock=[0];sessions=BrowseSessions(clock=lambda:clock[0])
        groups=[dict(id=str(i),game_key='game',game_title='Game',start_at='date',score=i) for i in range(5)]
        first=sessions.page(groups,{},0,2);query={'browse_id':first['browse_id']}
        changed=[dict(groups[4],score=99),*groups[:3]]
        later=sessions.page(changed,query,2,2)
        self.assertEqual([g['id'] for g in later['rows']],['2','3'])
        self.assertTrue(later['rows'][1]['withdrawn'])
        self.assertEqual(sessions.page(changed,query,4,2)['rows'][0]['score'],99)
        self.assertEqual(sessions.page(changed,dict(query,search='other'),2,2)['state'],'page_changed')
        clock[0]=901
        self.assertEqual(sessions.page(changed,query,2,2)['state'],'page_changed')

    def test_time_window_and_unknown_fees(self):
        row=quote('one','kalshi',value='8');row['game_state']='scheduled'
        options=('ev','conditional_return_percent',0,25)
        # 01:00 UTC is 20:00 Eastern on the preceding date.
        self.assertEqual(page(result(row),dict(day='2026-11-07',timezone='America/New_York',time_from='12:00',time_to='17:00'),options)['total'],0)
        view=page(result(row),dict(day='2026-11-07',timezone='America/New_York',time_from='19:00',time_to='21:00'),options)
        self.assertIsNone(view['rows'][0]['score'])
        self.assertEqual(view['rows'][0]['offers'][0]['before_fee'],'8')
        self.assertIsNone(view['rows'][0]['offers'][0]['after_fee'])

    def test_active_browse_session_survives_other_first_page_reads(self):
        sessions=BrowseSessions();groups=[dict(id='a',game_key='g',game_title='G',start_at='s')]
        active=sessions.page(groups,{},0,1)['browse_id']
        for _ in range(40):
            self.assertEqual(sessions.page(groups,{'browse_id':active},0,1)['state'],'ready')
            sessions.page(groups,{},0,1)
        self.assertEqual(len(sessions.sessions),16)

class NativeLiveDiscovery(TestCase):
    def test_explicit_sporting_state_reopens_only_the_legacy_kickoff_gate(self):
        from app.collection.admission_enrichment import enrich_game
        from app.comparison.game_phase import sporting_phase
        base=dict(id='game',source='kalshi',competition='NBA',participants={},
            scheduled_start='2026-11-08T00:00:00Z',exclusion='kickoff_reached',
            observed_identity_facts=[dict(status='inprogress')])
        live=enrich_game(base)
        self.assertIsNone(live['exclusion'])
        self.assertEqual(base['exclusion'],'kickoff_reached')
        self.assertEqual(price_phase(live,{},'2026-11-08T00:01:00Z')['state'],'unknown')
        for status in ('scheduled','suspended','final','cancelled'):
            e=enrich_game(dict(base,observed_identity_facts=[dict(status=status)]))
            self.assertEqual(e['exclusion'],'kickoff_reached')
        self.assertEqual(enrich_game(dict(base,exclusion='native_competition_conflict'))['exclusion'],'native_competition_conflict')
        conflict=dict(base,status={'identity_conflict':True})
        self.assertEqual(enrich_game(conflict)['exclusion'],'kickoff_reached')
        us=dict(base,source='polymarket_us',observed_identity_facts=[],_native=dict(gameId=42,eventState=dict(gameId=42,live=True,ended=False)))
        self.assertIsNone(enrich_game(us)['exclusion'])
        us['_native']['eventState']['gameId']=43
        self.assertEqual(enrich_game(us)['exclusion'],'kickoff_reached')
