"""Hypothetical NCAAB H1 annotations; actual listings and forecasts remain unqualified."""
import json,unittest
from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch
from tests import test_score_lines as shared,test_nfl_first_half as nfl
from tests.test_score_lines import fixture as shared_full_fixture

def full_fixture(competition="NCAAB", *args, **kwargs):
    return shared_full_fixture("NCAAB", *args, **kwargs)
from tests.test_nfl_first_half import rebuild
from app.normalization import ncaab_first_half as h1
from app.normalization.score_lines import market_partitions
from app.dashboard import product_view
from app.reference.product import receipt,at_cutoff
from app.reference.score_lines import score_distribution

def fixture(competition='NCAAB',family='spread',line='-3',equality='predicate',stage='regular_season',home='ALA',away='AAMU',site='neutral'):
    stage='ncaa_tournament' if stage=='postseason' else stage
    rows=full_fixture('NCAAB','spread' if family=='moneyline' else family,'0' if family=='moneyline' else line,equality)
    for source,c in rows[1]['inventory'].items():
        e=c['events'][0];e.update(stage=stage,home='NCAAB:M:D1:'+home,away='NCAAB:M:D1:'+away,participants={{'MIAFL':'Miami (FL)','MIAOH':'Miami (OH)'}.get(home,home):'NCAAB:M:D1:'+home,{'MIAFL':'Miami (FL)','MIAOH':'Miami (OH)'}.get(away,away):'NCAAB:M:D1:'+away},schools={'NCAAB:M:D1:'+home:'school:'+home,'NCAAB:M:D1:'+away:'school:'+away},neutral_site=site,tournament_id='not_applicable' if stage=='regular_season' else 'SYNTHETIC-tournament',round='not_applicable' if stage=='regular_season' else 'SYNTHETIC-round')
        from app.normalization.ncaab import event_key
        r=c['markets'][0]['score_review'];d=r['descriptor']
        if family!='total':d['participant']=e['home']
        r['event_binding']=event_key(e);e['canonical_key']=event_key(e)
        meta=next(x['market'] for x in rows if x['type']=='market_selected' and x['source']==source)
        raw=json.loads(meta['raw']['json_text']);raw['synthetic_ncaab_event']={k:e[k] for k in h1.EVENT_FIELDS};meta['raw']['json_text']=json.dumps(raw)
        for field in h1.TERM_FIELDS:r['terms'].setdefault(field,'unknown')
        d.update(family=family,period='first_half',line=None if family=='moneyline' else line,offered='pregame',regulation='first_20_minute_half',overtime='excluded',overtime_format='not_applicable',tied_score='evaluate_actual_score_predicate',normal_completion=h1.COMPLETION,settlement_score='first_half_only')
        if family=='moneyline':d['winner_structure']='two_way_draw_no_bet' if equality=='stake_refund' else 'binary_team_win_not_win'
        r['terms']['completion']=h1.COMPLETION
        r['series_id']=h1.SERIES[family];d['series_id']=h1.SERIES[family] if source=='kalshi' else None
        if source=='kalshi':r['fee_basis'].update(series_id=h1.SERIES[family],fee_type='quadratic')
        rebuild(rows,source)
    return rows


def reference(game,rows=None,at='2026-09-16T12:00:00+00:00'):
    rows=fixture(stage=game['product_identity']['stage']) if rows is None else rows
    e=rows[1]['inventory']['kalshi']['events'][0];side=next(v for k,v in game['sides'].items() if k.startswith('kalshi:yes:'))
    binding=dict(market_identity=game['product_identity'],participant=side['participant'],source_event_id='SYNTHETIC-first-half-partition')
    ids={p['id'] for p in market_partitions(game['product_identity'])};probs={'below':'.3','equal':'.1','above':'.6'} if 'equal' in ids else {'below':'.4','above':'.6'}
    if 'below' not in ids:probs={'equal':'.1','above':'.9'}
    r=receipt(json.dumps(dict(binding,event=e,value_kind='score_partition_probability',conditional_on='completed_first_half_only',probabilities=probs)),provider='espn_bpi',url='https://www.espn.com/SYNTHETIC-first-half',received_at=at,mode='synthetic')
    return score_distribution(r,binding,source_at='2026-09-15T12:00:00+00:00',model_version='SYNTHETIC H1 partition table; not a forecast')


class SharedChecks(shared.ScoreLines):
    def setUp(self):
        self.addCleanup(patch.stopall);patch.object(shared,'fixture',fixture).start();patch.object(shared,'reference',reference).start()

class FirstHalfChecks(nfl.FirstHalf):
    def setUp(self):
        self.addCleanup(patch.stopall)
        for name,value in [('fixture',fixture),('reference',reference),('full_fixture',full_fixture),('h1',h1)]:patch.object(nfl,name,value).start()

    def test_probability_period_and_timing(self):
        for family,line in [('moneyline',None),('spread','-3'),('total','20.5')]:
            rows=fixture(family=family,line=line);s=shared.projection(rows).snapshot();g=s['games'][0];r=reference(g,rows)
            self.assertEqual(at_cutoff([r],s['last_update'])[0]['availability'],'available')
            for change in [dict(conditional_on='completed_full_game_including_overtime'),dict(value_kind='ranking'),dict(value_kind='projected_score'),dict(probabilities={'above':'.6'}),dict(source_event_id='wrong')]:
                body=json.loads(r['receipt']['body']);body.update(change);rr=receipt(json.dumps(body),provider='espn_bpi',url=r['receipt']['url'],received_at=r['received_at'],mode='synthetic')
                with self.assertRaises(ValueError):score_distribution(rr,r['binding'])
            self.assertFalse(product_view.usable(dict(r,parser='legacy')))
            future=reference(g,rows,at='2026-11-11T23:30:00Z');self.assertFalse(at_cutoff([future],s['last_update']))
            self.assertNotEqual(at_cutoff([future],'2026-11-12T23:30:00Z')[0]['availability'],'available')

class CollegeChecks(unittest.TestCase):
    def test_bounded_schools_gender_division_and_sites(self):
        from app.normalization.ncaab import event_key
        for home,away in [('ALA','AAMU'),('MIAFL','MIAOH'),('MIAOH','ALA')]:
            for site in ['neutral','home','unknown']:
                snap=shared.projection(fixture(home=home,away=away,site=site)).snapshot();self.assertEqual(len(snap['games']),1,snap['market_catalog'])
                self.assertIn('first 20-minute half',snap['games'][0]['title']);self.assertIn('site: '+site,snap['games'][0]['title']);self.assertNotIn('second quarter',snap['games'][0]['title']);self.assertNotIn('+ overtime',snap['games'][0]['title'])
        for change in [dict(gender='women'),dict(division='II'),dict(competition_id='NCAA:W:D1'),dict(competition='NBA'),dict(season='2025-2026'),dict(neutral_site=None),dict(period_structure='four_10_minute_quarters'),dict(participants={'Miami':'NCAAB:M:D1:ALA','AAMU':'NCAAB:M:D1:AAMU'}),dict(schools={}),dict(home='NCAAB:M:D1:DUKE')]:
            rows=fixture();rows[1]['inventory']['kalshi']['events'][0].update(change);self.assertFalse(shared.projection(rows).snapshot()['games'])
        with self.assertRaises(ValueError):fixture(home='DUKE')
        e=fixture()[1]['inventory']['kalshi']['events'][0];key=event_key(e)
        self.assertEqual(key,event_key(dict(e,participants={'Alabama':'NCAAB:M:D1:ALA','Alabama A&M':'NCAAB:M:D1:AAMU'})))
        for change in [dict(game_id='repeated-game'),dict(neutral_site='unknown'),dict(scheduled_start='2026-11-12T23:00:00Z',schedule_status='rescheduled')]:self.assertNotEqual(key,event_key(dict(e,**change)))
        for change in [dict(scheduled_start='2026-11-10T23:00:00'),dict(schedule_status='rescheduled'),dict(stage='ncaa_tournament'),dict(game_id='')]:
            with self.assertRaises(ValueError):event_key(dict(e,**change))

    def test_tournament_round_and_first_half_ties(self):
        from app.normalization.ncaab import event_key
        for stage in ['regular_season','in_season_tournament','conference_tournament','ncaa_tournament','other_postseason_tournament']:
            rows=fixture(family='moneyline',stage=stage);snap=shared.projection(rows).snapshot();self.assertEqual(len(snap['games']),1)
            self.assertEqual([p['id'] for p in market_partitions(snap['games'][0]['product_identity'])],['below','equal','above'])
            if stage!='regular_season':
                e=rows[1]['inventory']['kalshi']['events'][0];self.assertNotEqual(event_key(e),event_key(dict(e,round='SYNTHETIC-round-2')))
                with self.assertRaises(ValueError):event_key(dict(e,tournament_id='unknown'))
        rows=fixture();rows[1]['inventory']['kalshi']['events'][0]['scheduled_start']='2026-11-12T23:00:00Z';self.assertFalse(shared.projection(rows).snapshot()['games'])

    def test_no_quarter_or_fractional_rule_inheritance(self):
        for family,line in [('moneyline',None),('spread','-3'),('total','70.5')]:
            for change in [dict(regulation='first_two_12_minute_quarters'),dict(regulation='first_two_15_minute_quarters'),dict(period=1),dict(period='quarter_2'),dict(normal_completion='first_two_quarters_definitively_completed'),dict(series_id='KXNBA1HWINNER'),dict(offered='halftime')]:
                rows=fixture(family=family,line=line);rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor'].update(change);shared.reseal(rows,'kalshi');self.assertFalse(shared.projection(rows).snapshot()['games'])
        for structure in ['fractional_tie_0.50','achievement_shared_winners','three_way','unknown']:
            rows=fixture(family='moneyline');rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor']['winner_structure']=structure;shared.reseal(rows,'kalshi');self.assertFalse(shared.projection(rows).snapshot()['games'])
        for field in h1.TERM_FIELDS:
            rows=fixture();del rows[1]['inventory']['kalshi']['markets'][0]['score_review']['terms'][field];shared.reseal(rows,'kalshi');self.assertFalse(shared.projection(rows).snapshot()['games'])
        rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['score_review']['terms']['completion']='first_two_quarters_definitively_completed';shared.reseal(rows,'kalshi');self.assertFalse(shared.projection(rows).snapshot()['games'])

    def test_exact_reference_college_context(self):
        rows=fixture();g=shared.projection(rows).snapshot()['games'][0];r=reference(g,rows)
        for field,value in [('gender','women'),('division','II'),('neutral_site','home'),('round','different'),('game_id','wrong'),('period_structure','four_12_minute_quarters')]:
            body=json.loads(r['receipt']['body']);body['event'][field]=value;rr=receipt(json.dumps(body),provider='espn_bpi',url=r['receipt']['url'],received_at=r['received_at'],mode='synthetic')
            with self.assertRaises(ValueError):score_distribution(rr,r['binding'])

class Filters(unittest.TestCase):
    def test_three_families_filter_and_unknown_winner(self):
        from tests.ncaab_first_half_preview import combined_fixture
        s=shared.projection(combined_fixture()).snapshot();self.assertEqual(len(s['games']),4,s['market_catalog'])
        for period,family,count in [('first_half','',12),('full_game','',4),('second_half','',0),('first_half','moneyline',4),('first_half','spread',4),('first_half','total',4)]:self.assertEqual(len(product_view.dashboard(s,dict(period=period,family=family),{})),count)
        self.assertTrue(any('structure unknown or unsupported' in (c['reason'] or '') for c in s['market_catalog']))

class StopAPI(shared.ScoreStopAPI):
    def setUp(self):
        from tests import score_lines_preview,ncaab_first_half_preview
        self.addCleanup(patch.stopall);patch.object(score_lines_preview,'owner',ncaab_first_half_preview.owner).start()
