"""Synthetic NBA records; no native source, venue or account qualification."""
import json,unittest
from copy import deepcopy
from unittest.mock import patch
from app.resolution import nba as resolution
from app.dashboard.session_projection import SessionProjection
from tests import test_b5_nfl_resolution as shared
from tests.test_b5_nba_first_half import fixture as half
from tests.test_b5_score_lines import fixture as full
from tests.test_b5_nba import fixture as winner

ASOF='2026-10-12T00:00:00+00:00'
PRE=shared.PRE

def fixture(family='spread',period='first_half',line='-3',equality='predicate'):
    rows=winner() if (family,period)==('moneyline','full_game') else (half if period=='first_half' else full)(family=family,line=line,equality=equality)
    p=SessionProjection()
    for row in rows:p.apply(row)
    s=p.snapshot();g=s['games'][0];e=rows[1]['inventory']['kalshi']['events'][0]
    return rows,s,g,e


def rec(s,g,e,kind='sporting',*,status=None,minute=0,supersedes=(),contract=None,home=50,away=50,**changes):
    at=f'2026-10-11T03:{minute:02}:00+00:00';period=g['product_identity']['period']
    p=dict(target=resolution.target(s,g,e),source='SYNTHETIC-NBA-sporting',source_event_id='SYNTHETIC-NBA-official-event',period=period,status=status or ('final' if kind=='sporting' else 'settled'),source_at=at,published_at=at,supersedes=list(supersedes))
    if kind=='sporting':
        h=period=='first_half';p.update(home_score=home,away_score=away,score_scope='first_half_end_of_second_quarter' if h else 'full_game_including_overtime',regulation_periods_completed=2 if h else 4,completion='first_two_quarters_definitively_completed' if h else 'all_regulation_and_applicable_overtime')
        if not h:p.update(overtime_complete=True,overtime_periods_completed=0)
    else:
        contract=contract or next(k for k in g['sides'] if k.startswith('kalshi:yes:'));source=contract.split(':')[0]
        p.update(source=source,source_event_id=g['sources'][source]['event_id'],contract=contract,native={**g['sources'][source],'outcome_id':g['sides'][contract]['native_id']},payout=None if p['status']=='pending' else dict(kind='fraction',value='0',fee_treatment='unknown'))
    p.update(changes)
    return resolution.record(kind,json.dumps({'SYNTHETIC_resolution':p}),url='https://example.invalid/SYNTHETIC-NBA-resolution',path=['SYNTHETIC_resolution'],received_at=at,evidence_mode='synthetic')

alter=shared.alter
wrappers=shared.wrappers

def view(s,g,records,at=ASOF):return resolution.resolve(wrappers(records),s,g,at,dict(quantity='100',scenario='cent'))

class NBA(shared.Linkage,shared.AdditionalChecks):
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
            self.assertEqual(view(s,g,[a,b,c],'2026-10-11T03:01:00Z')['sporting']['state'],'conflicting')
            self.assertEqual(view(s,g,[c])['sporting']['state'],'unsupported')

    def test_unknown_conflicting_and_future_times(self):
        _,s,g,e=fixture();r=rec(s,g,e)
        for change in [dict(source_at=None),dict(published_at=None),dict(source_at='2026-10-11T03:01:00Z'),dict(published_at='2026-10-11T03:01:00Z')]:self.assertEqual(view(s,g,[alter(r,**change)])['sporting']['state'],'unsupported')
        for key in ['source_at','published_at']:
            self.assertEqual(view(s,g,[alter(r,**{key:'2026-10-13T00:00:00Z'})])['sporting']['state'],'missing')
        rr=resolution.record('sporting',r['raw']['body'],url=r['raw']['url'],path=r['raw']['path'],received_at=None,evidence_mode='synthetic');self.assertEqual(view(s,g,[rr])['sporting']['state'],'unsupported')
        self.assertEqual(view(s,g,[r],PRE)['excluded_future_count'],1)

    def test_quarter_regulation_and_overtime_score_contracts(self):
        for period in ['first_half','full_game']:
            _,s,g,e=fixture(period=period);r=rec(s,g,e,home=110,away=100)
            for change in [dict(score_scope=None),dict(score_scope='regulation_only'),dict(score_scope='quarter_2'),dict(regulation_periods_completed=None),dict(regulation_periods_completed=3),dict(home_score=None),dict(completion='clock_zero_only')]:
                self.assertEqual(view(s,g,[alter(r,**change)])['sporting']['state'],'unsupported')
            if period=='full_game':
                for change in [dict(overtime_complete=None),dict(overtime_periods_completed=None),dict(overtime_periods_completed=True),dict(overtime_complete=False)]:self.assertEqual(view(s,g,[alter(r,**change)])['sporting']['state'],'unsupported')
                self.assertEqual(view(s,g,[alter(r,overtime_periods_completed=2)])['sporting']['state'],'final')
            else:
                a=view(s,g,[r]);b=view(s,g,[alter(r,regulation_score=[100,100],overtime_score=None,final_score=[111,120])])
                self.assertEqual([v['expected']['payout'] for v in a['venues']],[v['expected']['payout'] for v in b['venues']])

    def test_nba_identity_and_native_orientation(self):
        _,s,g,e=fixture('moneyline','full_game');r=rec(s,g,e,home=110,away=100)
        for change in [dict(competition='WNBA'),dict(competition='NCAAB'),dict(season='2025-2026'),dict(stage='playoffs'),dict(game_id='repeated-matchup'),dict(scheduled_start='2026-10-12T23:00:00Z',schedule_status='rescheduled'),dict(original_start=None),dict(home='NBA:NYK'),dict(participants={'Los Angeles':'NBA:BOS','NYK':'NBA:NYK'})]:
            t=deepcopy(r['payload']['target']);t['event'].update(change);self.assertEqual(len(view(s,g,[alter(r,target=t)])['unbound']),1)
        for names in [{'Boston Celtics':'NBA:BOS','New York Knicks':'NBA:NYK'},{'BOS':'NBA:BOS','NYK':'NBA:NYK'}]:
            t=deepcopy(r['payload']['target']);t['event']['participants']=names;self.assertEqual(view(s,g,[alter(r,target=t)])['sporting']['state'],'final')
        g['sides'][next(iter(g['sides']))]['participant']='unreviewed';self.assertEqual(len(view(s,g,[r])['unbound']),1)

    def test_shortened_final_void_do_not_imply_refund(self):
        _,s,g,e=fixture()
        for status in ['shortened','suspended','cancelled','void']:
            v=view(s,g,[rec(s,g,e,status=status)]);self.assertTrue(all(x['expected']['payout'] is None for x in v['venues']))
        v=view(s,g,[rec(s,g,e),rec(s,g,e,'venue',status='refund',payout=None)])
        self.assertIsNone(next(x for x in v['venues'] if x['observed']['selected'])['observed']['selected']['payload']['payout'])

    def test_version_and_cross_competition_resolution(self):
        _,s,g,e=fixture();r=rec(s,g,e);self.assertEqual(r['schema_version'],'nba-sport-result-1');self.assertEqual(view(s,g,[r])['version'],'nba-resolution-view-1')
        original=json.loads(r['raw']['body']);bad=deepcopy(r);bad['schema_version']='nfl-sport-result-1'
        with self.assertRaises(ValueError):resolution.validate(bad)
        self.assertEqual(json.loads(r['raw']['body']),original)

class Lifecycle(shared.Lifecycle):
    def setUp(self):
        from tests import b5_nfl_resolution_preview as preview
        from tests.b5_nba_resolution_preview import owner
        self.addCleanup(patch.stopall);patch.object(preview,'owner',owner).start()

class FullLifecycle(shared.Lifecycle):
    def setUp(self):
        from tests import b5_nfl_resolution_preview as preview
        from tests.b5_nba_resolution_preview import owner
        self.addCleanup(patch.stopall);patch.object(preview,'owner',lambda root:owner(root,'full_game')).start()

class IndependentPayouts(unittest.TestCase):
    def test_full_game_native_winner_and_totals(self):
        for home,away in [(110,100),(100,110)]:
            _,s,g,e=fixture('moneyline','full_game');v=view(s,g,[rec(s,g,e,home=home,away=away)])
            for x in v['venues']:
                side=g['sides'][x['contract']];wins=side['participant']==('Boston Celtics' if home>away else 'New York Knicks')
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
