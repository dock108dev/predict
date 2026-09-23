"""Synthetic NCAAB records; no native source, venue or account qualification."""
import json,unittest
from copy import deepcopy
from unittest.mock import patch
from app.resolution import ncaab as resolution
from app.dashboard.session_projection import SessionProjection
from tests import test_b5_nfl_resolution as shared
from tests.test_b5_ncaab_first_half import fixture as half
from tests.test_b5_score_lines import fixture as shared_full

def full(**kw):return shared_full('NCAAB',**kw)
from tests.test_b5_ncaab import fixture as winner

ASOF='2026-11-12T00:00:00+00:00'
PRE=shared.PRE

def fixture(family='spread',period='first_half',line='-3',equality='predicate'):
    rows=winner() if (family,period)==('moneyline','full_game') else (half if period=='first_half' else full)(family=family,line=line,equality=equality)
    p=SessionProjection()
    for row in rows:p.apply(row)
    s=p.snapshot();g=s['games'][0];e=rows[1]['inventory']['kalshi']['events'][0]
    return rows,s,g,e


def rec(s,g,e,kind='sporting',*,status=None,minute=0,supersedes=(),contract=None,home=50,away=50,**changes):
    at=f'2026-11-11T03:{minute:02}:00+00:00';period=g['product_identity']['period']
    p=dict(target=resolution.target(s,g,e),source='SYNTHETIC-NCAAB-sporting',source_event_id='SYNTHETIC-NCAAB-official-event',period=period,status=status or ('final' if kind=='sporting' else 'settled'),source_at=at,published_at=at,supersedes=list(supersedes))
    if kind=='sporting':
        h=period=='first_half';p.update(home_score=home,away_score=away,score_scope='first_20_minute_half' if h else 'full_game_including_overtime',period_format='first_20_minute_half' if h else 'two_20_minute_halves',score_representation='official_period_points' if h else resolution.SCORING,result_basis='on_field_period_score',revision_type='score_correction' if supersedes else 'original',regulation_periods_completed=1 if h else 2,completion=resolution.COMPLETION if h else 'all_regulation_and_applicable_overtime')
        if not h:p.update(extra_periods_complete=True,extra_periods_completed=0,overtime_format=resolution.OVERTIME)
    else:
        contract=contract or next(k for k in g['sides'] if k.startswith('kalshi:yes:'));source=contract.split(':')[0]
        p.update(source=source,source_event_id=g['sources'][source]['event_id'],contract=contract,native={**g['sources'][source],'outcome_id':g['sides'][contract]['native_id']},payout=None if p['status']=='pending' else dict(kind='fraction',value='0',fee_treatment='unknown'))
    p.update(changes)
    return resolution.record(kind,json.dumps({'SYNTHETIC_resolution':p}),url='https://example.invalid/SYNTHETIC-NCAAB-resolution',path=['SYNTHETIC_resolution'],received_at=at,evidence_mode='synthetic')

alter=shared.alter
wrappers=shared.wrappers

def view(s,g,records,at=ASOF):return resolution.resolve(wrappers(records),s,g,at,dict(quantity='100',scenario='cent'))

class NCAAB(shared.Linkage,shared.AdditionalChecks):
    def setUp(self):
        self.addCleanup(patch.stopall)
        for name,value in [('fixture',fixture),('rec',rec),('view',view),('ASOF',ASOF)]:patch.object(shared,name,value).start()

    def test_winner_ties_both_periods(self):
        _,s,g,e=fixture('moneyline');v=view(s,g,[rec(s,g,e)])
        yes=next(x for x in v['venues'] if x['contract'].startswith('kalshi:yes:'));self.assertEqual(yes['expected']['payout']['value'],'1')
        _,s,g,e=fixture('moneyline','full_game');v=view(s,g,[rec(s,g,e)])
        self.assertEqual(v['sporting']['state'],'unsupported');self.assertTrue(all(x['expected']['payout'] is None for x in v['venues']))

    def test_corrections_supersede_branches_without_deleting(self):
        for period in ['full_game','first_half']:
            _,s,g,e=fixture(period=period);a=rec(s,g,e,home=53);b=rec(s,g,e,minute=1,home=54);c=rec(s,g,e,minute=2,home=48,supersedes=[a['id'],b['id']]);v=view(s,g,[c,b,a])
            self.assertEqual(v['sporting']['state'],'corrected');self.assertEqual(len(v['sporting']['records']),3);self.assertEqual(sum(x['correction_state']=='superseded' for x in v['sporting']['records']),2)
            self.assertEqual(view(s,g,[a,b,c],'2026-11-11T03:01:00Z')['sporting']['state'],'conflicting')
            self.assertEqual(view(s,g,[c])['sporting']['state'],'unsupported')

    def test_unknown_conflicting_and_future_times(self):
        _,s,g,e=fixture();r=rec(s,g,e)
        for change in [dict(source_at=None),dict(published_at=None),dict(source_at='2026-11-11T03:01:00Z'),dict(published_at='2026-11-11T03:01:00Z')]:self.assertEqual(view(s,g,[alter(r,**change)])['sporting']['state'],'unsupported')
        for key in ['source_at','published_at']:
            self.assertEqual(view(s,g,[alter(r,**{key:'2026-11-13T00:00:00Z'})])['sporting']['state'],'missing')
        rr=resolution.record('sporting',r['raw']['body'],url=r['raw']['url'],path=r['raw']['path'],received_at=None,evidence_mode='synthetic');self.assertEqual(view(s,g,[rr])['sporting']['state'],'unsupported')
        self.assertEqual(view(s,g,[r],PRE)['excluded_future_count'],1)

    def test_quarter_regulation_and_overtime_score_contracts(self):
        for period in ['first_half','full_game']:
            _,s,g,e=fixture(period=period);r=rec(s,g,e,home=110,away=100)
            for change in [dict(score_scope=None),dict(score_scope='regulation_only'),dict(score_scope='quarter_2'),dict(regulation_periods_completed=None),dict(regulation_periods_completed=3),dict(home_score=None),dict(completion='clock_zero_only')]:
                self.assertEqual(view(s,g,[alter(r,**change)])['sporting']['state'],'unsupported')
            if period=='full_game':
                for change in [dict(extra_periods_complete=None),dict(extra_periods_completed=None),dict(extra_periods_completed=True),dict(extra_periods_complete=False)]:self.assertEqual(view(s,g,[alter(r,**change)])['sporting']['state'],'unsupported')
                self.assertEqual(view(s,g,[alter(r,extra_periods_completed=2)])['sporting']['state'],'final')
            else:
                a=view(s,g,[r]);b=view(s,g,[alter(r,regulation_score=[100,100],overtime_score=None,final_score=[111,120])])
                self.assertEqual([v['expected']['payout'] for v in a['venues']],[v['expected']['payout'] for v in b['venues']])

    def test_ncaab_identity_and_native_orientation(self):
        _,s,g,e=fixture('moneyline','full_game');r=rec(s,g,e,home=110,away=100)
        for change in [dict(competition='NFL'),dict(competition='NBA'),dict(season='2025'),dict(stage='playoffs'),dict(game_id='repeated-matchup'),dict(scheduled_start='2026-11-12T23:00:00Z',schedule_status='rescheduled'),dict(original_start=None),dict(neutral_site='home'),dict(schools={}),dict(gender='women'),dict(division='II'),dict(competition_id='NCAA:W:D1'),dict(round='different'),dict(tournament_id='different'),dict(home='NCAAB:M:D1:AAMU'),dict(participants={'Miami':'NCAAB:M:D1:ALA','AAMU':'NCAAB:M:D1:AAMU'})]:
            t=deepcopy(r['payload']['target']);t['event'].update(change);self.assertEqual(len(view(s,g,[alter(r,target=t)])['unbound']),1)
        for names in [{'Alabama Crimson Tide':'NCAAB:M:D1:ALA','Alabama A&M Bulldogs':'NCAAB:M:D1:AAMU'},{'ALA':'NCAAB:M:D1:ALA','AAMU':'NCAAB:M:D1:AAMU'}]:
            t=deepcopy(r['payload']['target']);t['event']['participants']=names;self.assertEqual(view(s,g,[alter(r,target=t)])['sporting']['state'],'final')
        g['sides'][next(iter(g['sides']))]['participant']='unreviewed';self.assertEqual(len(view(s,g,[r])['unbound']),1)

    def test_shortened_final_void_do_not_imply_refund(self):
        _,s,g,e=fixture()
        for status in ['shortened','suspended','cancelled','void']:
            v=view(s,g,[rec(s,g,e,status=status)]);self.assertTrue(all(x['expected']['payout'] is None for x in v['venues']))
        v=view(s,g,[rec(s,g,e),rec(s,g,e,'venue',status='refund',payout=None)])
        self.assertIsNone(next(x for x in v['venues'] if x['observed']['selected'])['observed']['selected']['payload']['payout'])

    def test_version_and_cross_competition_resolution(self):
        _,s,g,e=fixture();r=rec(s,g,e);self.assertEqual(r['schema_version'],'ncaab-sport-result-1');self.assertEqual(view(s,g,[r])['version'],'ncaab-resolution-view-1')
        original=json.loads(r['raw']['body']);bad=deepcopy(r);bad['schema_version']='nfl-sport-result-1'
        with self.assertRaises(ValueError):resolution.validate(bad)
        self.assertEqual(json.loads(r['raw']['body']),original)

class Lifecycle(shared.Lifecycle):
    def setUp(self):
        from tests import b5_nfl_resolution_preview as preview
        from tests.b5_ncaab_resolution_preview import owner
        self.addCleanup(patch.stopall);patch.object(preview,'owner',owner).start()

class FullLifecycle(shared.Lifecycle):
    def setUp(self):
        from tests import b5_nfl_resolution_preview as preview
        from tests.b5_ncaab_resolution_preview import owner
        self.addCleanup(patch.stopall);patch.object(preview,'owner',lambda root:owner(root,'full_game')).start()

class IndependentPayouts(unittest.TestCase):
    def test_full_game_native_winner_and_totals(self):
        for home,away in [(110,100),(100,110)]:
            _,s,g,e=fixture('moneyline','full_game');v=view(s,g,[rec(s,g,e,home=home,away=away)])
            for x in v['venues']:
                side=g['sides'][x['contract']];wins=side['participant']==('Alabama Crimson Tide' if home>away else 'Alabama A&M Bulldogs')
                if side['predicate']=='not_win':wins=not wins
                self.assertEqual(x['expected']['payout'],dict(kind='fraction',value='1' if wins else '0'))
        for period in ['first_half','full_game']:
            for equality in ['predicate','stake_refund']:
                _,s,g,e=fixture('total',period,'103',equality);v=view(s,g,[rec(s,g,e,home=53,away=50)])
                for x in v['venues']:
                    side=g['sides'][x['contract']];pay=x['expected']['payout']
                    if equality=='stake_refund':self.assertEqual(pay,dict(kind='stake_refund',value=None))
                    else:self.assertEqual(pay,dict(kind='fraction',value='1' if side['operator'] in ('ge','le') else '0'))

    def test_unknown_refund_fees_and_fractional_structures_do_not_expand(self):
        from tests.test_b5_nfl_first_half import rebuild
        for equality in ['unknown','stake_refund']:
            rows,_,_,e=fixture('spread','first_half','-3',equality)
            if equality=='stake_refund':
                for source,c in rows[1]['inventory'].items():
                    for outcome in c['markets'][0]['score_review']['descriptor']['outcomes']:outcome['refund_fees']='unknown'
                    rebuild(rows,source)
            p=SessionProjection()
            for row in rows:p.apply(row)
            s=p.snapshot();g=s['games'][0];v=view(s,g,[rec(s,g,e,home=53,away=50)])
            self.assertTrue(all(x['expected']['payout'] is None for x in v['venues']))


class CollegeSpecific(unittest.TestCase):
    def test_four_schools_and_tournament_identity(self):
        from app.normalization.registry import Registry
        from app.normalization.ncaab import event_key
        reg=Registry.load();self.assertEqual(resolution.SCHOOLS,{k for k,v in reg.entities.items() if v.get('league')=='NCAAB'})
        for away in ['AAMU','MIAFL','MIAOH']:
            for stage in ['regular_season','in_season_tournament','conference_tournament','ncaa_tournament','other_postseason_tournament']:
                rows=half(family='moneyline',away=away,stage=stage);p=SessionProjection()
                for row in rows:p.apply(row)
                s=p.snapshot();g=s['games'][0];e=rows[1]['inventory']['kalshi']['events'][0];r=rec(s,g,e)
                self.assertEqual(view(s,g,[r])['sporting']['state'],'final')
                for change in [dict(round='different-round'),dict(tournament_id='different-tournament'),dict(schools={}),dict(period_structure='four_10_minute_quarters')]:
                    t=deepcopy(r['payload']['target']);t['event'].update(change);self.assertEqual(len(view(s,g,[alter(r,target=t)])['unbound']),1)
        for alias in ['Miami','USC','SDSU','Bulldogs']:
            self.assertIsNone(reg.resolve('team',alias,league='NCAAB').canonical_id)
        e=fixture()[3]
        for change in [dict(gender='women'),dict(division='III'),dict(season='2025-2026')]:
            with self.assertRaises(ValueError):event_key(dict(e,**change))

    def test_twenty_minute_half_and_overtime_not_double_counted(self):
        _,s,g,e=fixture('moneyline');r=rec(s,g,e)
        for change in [dict(completion='first_two_quarters_definitively_completed'),dict(period_format='first_two_12_minute_quarters'),dict(regulation_periods_completed=2),dict(score_scope='first_half_end_of_second_quarter')]:
            self.assertEqual(view(s,g,[alter(r,**change)])['sporting']['state'],'unsupported')
        for family,line in [('spread','-2'),('total','158')]:
            _,s,g,e=fixture(family,'full_game',line);r=rec(s,g,e,home=80,away=78,extra_periods_completed=2)
            a=view(s,g,[r]);b=view(s,g,[alter(r,regulation_score=[60,60],extra_period_points=[20,18])])
            self.assertEqual(a['sporting']['state'],'final')
            for x,y in zip(a['venues'],b['venues']):self.assertEqual(x['expected']['payout'],y['expected']['payout'])
            for change in [dict(score_representation='final_plus_overtime'),dict(score_representation=None),dict(overtime_format='NBA_quarters'),dict(extra_periods_completed=None),dict(result_basis='vacated_result'),dict(score_scope='regulation_only')]:
                self.assertEqual(view(s,g,[alter(r,**change)])['sporting']['state'],'unsupported')

    def test_administrative_changes_and_venue_revisions_are_independent(self):
        _,s,g,e=fixture('moneyline');a=rec(s,g,e,home=37,away=34);venue=rec(s,g,e,'venue',status='pending')
        admin=rec(s,g,e,status='administrative_change',minute=1,supersedes=[a['id']],revision_type='administrative_change',administrative_action='vacated',result_basis='administrative_record',home=0,away=1)
        v=view(s,g,[a,venue,admin]);self.assertEqual(v['sporting']['state'],'corrected');self.assertEqual(v['sporting']['selected']['payload']['administrative_action'],'vacated');self.assertTrue(all(x['expected']['payout'] is None for x in v['venues']))
        self.assertEqual(next(x for x in v['venues'] if x['observed']['selected'])['observed']['selected'],venue)
        self.assertEqual(view(s,g,[a,venue,admin],'2026-11-11T03:00:00Z')['sporting']['selected']['id'],a['id'])
        self.assertEqual(view(s,g,[alter(admin,status='final')])['sporting']['state'],'unsupported')
        corrected=rec(s,g,e,home=30,away=34,minute=2,supersedes=[a['id']]);settled=rec(s,g,e,'venue',minute=3,supersedes=[venue['id']])
        v=view(s,g,[a,venue,corrected,settled]);self.assertEqual(v['sporting']['selected'],corrected);self.assertEqual(next(x for x in v['venues'] if x['observed']['selected'])['observed']['selected'],settled)
        self.assertEqual(len(next(x for x in v['venues'] if x['observed']['selected'])['observed']['records']),2)
        for change in [dict(revision_type=None),dict(revision_type='original')]:self.assertEqual(view(s,g,[alter(corrected,**change)])['sporting']['state'],'unsupported')
