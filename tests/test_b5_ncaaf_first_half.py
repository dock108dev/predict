"""Hypothetical college H1 reviews; no acquired listings or forecasts."""
import json,unittest
from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch
from tests import test_b5_score_lines as shared,test_b5_nfl_first_half as nfl
from tests.test_b5_ncaaf_lines import fixture as full_fixture
from app.normalization import ncaaf_first_half as h1
from app.normalization.score_lines import market_partitions
from app.dashboard import product_view


def fixture(competition='NCAAF',family='spread',line='-3',equality='predicate',stage='regular_season',home='ALA',away='MIAOH',site='neutral'):
    stage='playoffs' if stage=='postseason' else stage
    rows=full_fixture('NCAAF','spread' if family=='moneyline' else family,'0' if family=='moneyline' else line,equality,stage,home,away,site)
    for source,c in rows[1]['inventory'].items():
        e=c['events'][0];m=c['markets'][0];r=m['score_review'];d=r['descriptor']
        d.update(family=family,period='first_half',line=None if family=='moneyline' else line,offered='pregame',regulation='first_two_15_minute_quarters',overtime='excluded',overtime_format='not_applicable',overtime_scoring='excluded_from_first_half',tied_score='evaluate_actual_score_predicate',normal_completion=h1.COMPLETION,settlement_score='first_half_only')
        if family=='moneyline':d['winner_structure']='two_way_draw_no_bet' if equality=='stake_refund' else 'binary_team_win_not_win'
        r['terms']['completion']=h1.COMPLETION;r['series_id']=h1.SERIES[family];d['series_id']=h1.SERIES[family] if source=='kalshi' else None
        if source=='kalshi':r['fee_basis'].update(series_id=h1.SERIES[family],fee_type='quadratic')
        # Fixture assembly may deliberately contain unsupported FCS annotations.
        sides=[];threshold='0' if family=='moneyline' else str(-Decimal(line) if family=='spread' else Decimal(line))
        for side in d['outcomes']:
            label=(d['participant']+' '+line if family=='spread' else d['participant']+' First half winner' if family=='moneyline' else 'Total '+line)+' '+side['native_label']
            sides.append(dict(side,participant=label,predicate='score',threshold=threshold,domain='combined_score' if family=='total' else 'home_margin',label=label))
        m.update(market_type=family,period='first_half',line=d['line'],product_outcomes=sides)
        shared.reseal(rows,source)
    return rows

nfl_reference=nfl.reference

def reference(game,rows=None,at='2026-09-16T12:00:00+00:00'):
    return nfl_reference(game,rows=fixture(stage=game['product_identity']['stage']) if rows is None else rows,at=at)


class SharedChecks(shared.ScoreLines):
    def setUp(self):
        self.addCleanup(patch.stopall);patch.object(shared,'fixture',fixture).start();patch.object(shared,'reference',reference).start()


class FirstHalfChecks(nfl.FirstHalf):
    def setUp(self):
        self.addCleanup(patch.stopall)
        for name,value in [('fixture',fixture),('reference',reference),('full_fixture',full_fixture),('h1',h1)]:patch.object(nfl,name,value).start()


class CollegeChecks(unittest.TestCase):
    def test_schools_subdivisions_sites_and_fcs_gap(self):
        for home,away in [('ALA','MIAOH'),('NDSU','MIAFL'),('ALA','AAMU')]:
            s=shared.projection(fixture(home=home,away=away)).snapshot();self.assertEqual(len(s['games']),1,s['market_catalog']);self.assertIn('site: neutral',s['games'][0]['title']);self.assertNotIn('including college overtime',s['games'][0]['title'])
        for family,line in [('moneyline',None),('spread','-3'),('total','20.5')]:
            s=shared.projection(fixture(family=family,line=line,home='AAMU',away='SDAKST')).snapshot();self.assertFalse(s['games']);self.assertTrue(any('FCS-only' in (c['reason'] or '') for c in s['market_catalog']))
        for change in [dict(participants={'Miami':'NCAAF:MIAOH','ALA':'NCAAF:ALA'}),dict(season='2025'),dict(neutral_site=None),dict(subdivisions={'NCAAF:ALA':'FCS','NCAAF:MIAOH':'FBS'}),dict(game_id=''),dict(scheduled_start='2026-10-04T17:00:00')]:
            rows=fixture();rows[1]['inventory']['kalshi']['events'][0].update(change);self.assertFalse(shared.projection(rows).snapshot()['games'])
        for field,value in [('subdivision_scope',['FCS']),('overtime_scoring','official_final_points_including_all_extra_period_tries'),('series_id','KXNFL1HSPREAD')]:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor'][field]=value;shared.reseal(rows,'kalshi');self.assertFalse(shared.projection(rows).snapshot()['games'])
        a=shared.projection(fixture(site='neutral')).snapshot()['games'][0];b=shared.projection(fixture(site='unknown')).snapshot()['games'][0];self.assertNotEqual(a['id'],b['id'])
        from app.normalization.ncaaf import event_key
        e=fixture()[1]['inventory']['kalshi']['events'][0];rescheduled=dict(e,scheduled_start='2026-10-05T17:00:00Z',schedule_status='rescheduled');self.assertNotEqual(event_key(e),event_key(rescheduled))
        self.assertNotEqual(event_key(e),event_key(dict(e,game_id='separate-game')))

    def test_zero_h1_stays_tied_and_wrong_reference_site(self):
        for family in ['moneyline','spread']:
            s=shared.projection(fixture(family=family,line='0')).snapshot();g=s['games'][0];self.assertEqual([p['id'] for p in market_partitions(g['product_identity'])],['below','equal','above'])
            self.assertIsNone(product_view.calculate(s,g,dict(probability='.6'))['ev']['expected_profit'])
            r=reference(g);body=json.loads(r['receipt']['body']);body['event']['neutral_site']='home'
            from app.reference.product import receipt
            from app.reference.score_lines import score_distribution
            rr=receipt(json.dumps(body),provider='espn_fpi',url=r['receipt']['url'],received_at=r['received_at'],mode='synthetic')
            with self.assertRaises(ValueError):score_distribution(rr,r['binding'])


class Filters(unittest.TestCase):
    def test_all_families_periods_and_unsupported_fcs(self):
        from tests.b5_ncaaf_first_half_preview import combined_fixture
        s=shared.projection(combined_fixture()).snapshot();self.assertEqual(len(s['games']),4,s['market_catalog'])
        for period,family,count in [('first_half','',12),('full_game','',4),('second_half','',0),('first_half','moneyline',4),('first_half','spread',4),('first_half','total',4)]:self.assertEqual(len(product_view.dashboard(s,dict(period=period,family=family),{})),count)
        self.assertTrue(any('FCS-only' in (c['reason'] or '') for c in s['market_catalog']))


class StopAPI(shared.ScoreStopAPI):
    def setUp(self):
        from tests import b5_score_lines_preview,b5_ncaaf_first_half_preview
        self.addCleanup(patch.stopall);patch.object(b5_score_lines_preview,'owner',b5_ncaaf_first_half_preview.owner).start()
