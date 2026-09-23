"""Synthetic MLB/NHL expected results; no actual source qualification."""
import unittest,json
from copy import deepcopy
from app.dashboard.session_projection import SessionProjection
from app.resolution import core
from tests.test_b5_nfl_resolution import wrappers,alter
from tests.test_b5_mlb_lines import fixture as baseball
from tests.test_b5_nhl_lines import fixture as hockey


def fixture(sport='MLB',family='spread',**kw):
    rows=(baseball if sport=='MLB' else hockey)(family=family,**kw);p=SessionProjection()
    for row in rows:p.apply(row)
    s=p.snapshot();return rows,s,s['games'][0],rows[1]['inventory']['kalshi']['events'][0]


def rec(s,g,e,kind='sporting',minute=0,supersedes=(),**changes):
    at=f'2026-10-15T03:{minute:02}:00Z'
    p=dict(target=core.target(s,g,e),source='SYNTHETIC-result',source_event_id='fixture-game',period='full_game',status='final',source_at=at,published_at=at,supersedes=list(supersedes),revision_type='score_correction' if supersedes else 'original',result_basis='on_field_period_score',home_score=5,away_score=2)
    if e['competition']=='MLB':p.update(score_scope='full_game_including_extra_innings',score_representation='official_cumulative_runs',completion='nine_inning_format_completed_with_applicable_extra_innings',pitcher_conditions='action',scheduled_innings=9,final_inning=9,final_half='top',game_ended='home_lead_bottom_unneeded',resume_status='not_suspended')
    else:p.update(score_scope='full_game',completion='three_periods_and_applicable_overtime_shootout',regulation_periods_completed=3,score_basis='official_final_including_shootout_award',decision='regulation',winner='home')
    if kind=='venue':
        c=next(k for k in g['sides'] if k.startswith('kalshi:yes:'));p.update(source='kalshi',source_event_id=g['sources']['kalshi']['event_id'],contract=c,native={**g['sources']['kalshi'],'outcome_id':g['sides'][c]['native_id']},status='pending',payout=None)
    p.update(changes)
    return core.record(kind,json.dumps({'annotation':p}),url='https://example.invalid/synthetic',path=['annotation'],received_at=at,evidence_mode='synthetic')


def view(s,g,records,at='2026-10-16T00:00:00Z'):return core.resolve(wrappers(records),s,g,at,dict(quantity='100',scenario='cent'))

class Results(unittest.TestCase):
    def test_all_lines_independent_thresholds(self):
        for sport in ['MLB','NHL']:
            for family in ['spread','total']:
                _,s,g,e=fixture(sport,family,line='-3' if family=='spread' else '7')
                for h in [4,5,6]:
                    v=view(s,g,[rec(s,g,e,home_score=h)])
                    self.assertEqual(v['sporting']['state'],'final')
                    for x in v['venues']:
                        side=g['sides'][x['contract']];value=h-2 if family=='spread' else h+2;threshold=3 if family=='spread' else 7
                        truth={'gt':value>threshold,'ge':value>=threshold,'lt':value<threshold,'le':value<=threshold}[side['operator']]
                        self.assertEqual(x['expected']['payout']['value'],str(int(truth)))
    def test_baseball_status_pitcher_completion(self):
        _,s,g,e=fixture();r=rec(s,g,e)
        for change in [dict(pitcher_conditions='listed'),dict(pitcher_conditions=None),dict(completion='official_after_five'),dict(final_inning=7),dict(resume_status=None),dict(home_score=2),dict(score_representation='regulation_plus_extra')]:
            self.assertEqual(view(s,g,[alter(r,**change)])['sporting']['state'],'unsupported')
        resumed=alter(r,resume_status='resumed_completed',resumed_game_id=e['game_id'],resumed_at='2026-10-14T00:00:00Z');self.assertEqual(view(s,g,[resumed])['sporting']['state'],'final')
        self.assertEqual(view(s,g,[alter(resumed,resumed_game_id='another')])['sporting']['state'],'unsupported')
        for n in [10,14]:self.assertEqual(view(s,g,[alter(r,final_inning=n)])['sporting']['state'],'final')
    def test_hockey_shootout_counted_once(self):
        _,s,g,e=fixture('NHL','total',line='5');r=rec(s,g,e,home_score=2,away_score=2,decision='shootout',score_basis='on_ice_regulation_and_overtime')
        a=view(s,g,[r]);b=view(s,g,[alter(r,home_score=3,score_basis='official_final_including_shootout_award')])
        self.assertEqual(a['sporting']['state'],'final');self.assertEqual([v['expected']['payout'] for v in a['venues']],[v['expected']['payout'] for v in b['venues']])
        for change in [dict(home_score=3),dict(score_basis=None),dict(winner=None),dict(score_basis='shootout_attempt_goals'),dict(score_scope='regulation_only')]:self.assertEqual(view(s,g,[alter(r,**change)])['sporting']['state'],'unsupported')
    def test_corrections_identity_future_and_separate_venue(self):
        for sport in ['MLB','NHL']:
            _,s,g,e=fixture(sport);a=rec(s,g,e);b=rec(s,g,e,minute=1,home_score=6);c=rec(s,g,e,minute=2,home_score=4,supersedes=[a['id'],b['id']]);venue=rec(s,g,e,'venue')
            self.assertEqual(view(s,g,[a,b,venue])['sporting']['state'],'conflicting')
            v=view(s,g,[a,b,c,venue]);self.assertEqual(v['sporting']['state'],'corrected');self.assertTrue(any(x['observed']['state']=='pending' for x in v['venues']))
            self.assertEqual(view(s,g,[a,b,c],'2026-10-15T03:00:00Z')['sporting']['state'],'final')
            t=deepcopy(a['payload']['target']);t['event']['game_id']='different';self.assertEqual(len(view(s,g,[alter(a,target=t)])['unbound']),1)
            admin=rec(s,g,e,minute=3,supersedes=[c['id']],status='administrative_change',revision_type='administrative_change');v=view(s,g,[a,b,c,admin,venue]);self.assertTrue(all(x['expected']['payout'] is None for x in v['venues']))
    def test_full_game_winner_and_legacy_binding(self):
        from tests.test_b5_mlb import fixture as mlb_winner
        from tests.test_b5_nhl import fixture as nhl_winner
        for sport,make in [('MLB',mlb_winner),('NHL',nhl_winner)]:
            rows=make()
            if sport=='NHL':
                # Explicit newly prepared catalog evidence; old fixtures stay immutable.
                for cat in rows[1]['inventory'].values():
                    for e in cat.get('events',[]):e.update(game_id='SYNTHETIC-reviewed-hockey-game',original_start=e['scheduled_start'],schedule_status='scheduled')
            p=SessionProjection()
            for row in rows:p.apply(row)
            s=p.snapshot();g=s['games'][0];e=rows[1]['inventory'][next(iter(g['sources']))]['events'][0];v=view(s,g,[rec(s,g,e)])
            self.assertEqual(v['sporting']['state'],'final');self.assertTrue(all(x['expected']['payout'] for x in v['venues']))
        rows=nhl_winner();p=SessionProjection()
        for row in rows:p.apply(row)
        s=p.snapshot();g=s['games'][0];e=deepcopy(rows[1]['inventory']['kalshi']['events'][0]);e.update(game_id='ANNOTATION-CANNOT-BACKFILL',original_start=e['scheduled_start'],schedule_status='scheduled');self.assertEqual(len(view(s,g,[rec(s,g,e)])['unbound']),1)
    def test_shortened_official_winner_does_not_settle_lines(self):
        from tests.test_b5_mlb import fixture as winner
        rows=winner();p=SessionProjection()
        for row in rows:p.apply(row)
        s=p.snapshot();g=s['games'][0];e=rows[1]['inventory'][next(iter(g['sources']))]['events'][0];r=rec(s,g,e,status='shortened',league_declared_final=True);v=view(s,g,[r]);self.assertEqual(v['sporting']['state'],'shortened');self.assertTrue(all(x['expected']['payout'] for x in v['venues']))
        _,s,g,e=fixture();v=view(s,g,[rec(s,g,e,status='shortened',league_declared_final=True)]);self.assertTrue(all(x['expected']['payout'] is None for x in v['venues']))
        self.assertEqual(view(s,g,[rec(s,g,e,status='shortened')])['sporting']['state'],'unsupported')
