"""Hypothetical NBA H1 annotations; actual listings and forecasts remain unqualified."""
import json,unittest
from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch
from tests import test_score_lines as shared,test_nfl_first_half as nfl
from tests.test_score_lines import fixture as full_fixture
from tests.test_nfl_first_half import rebuild
from app.normalization import nba_first_half as h1
from app.normalization.score_lines import market_partitions
from app.dashboard import product_view
from app.reference.product import receipt,at_cutoff
from app.reference.score_lines import score_distribution

def fixture(competition='NBA',family='spread',line='-3',equality='predicate',stage='regular_season'):
    stage='playoffs' if stage=='postseason' else stage
    rows=full_fixture('NBA','spread' if family=='moneyline' else family,'0' if family=='moneyline' else line,equality)
    for source,c in rows[1]['inventory'].items():
        e=c['events'][0];e['stage']=stage
        from app.normalization.nba import event_key
        r=c['markets'][0]['score_review'];d=r['descriptor']
        r['event_binding']=event_key(e);e['canonical_key']=event_key(e)
        meta=next(x['market'] for x in rows if x['type']=='market_selected' and x['source']==source)
        raw=json.loads(meta['raw']['json_text']);raw['synthetic_nba_event']={k:e[k] for k in h1.EVENT_FIELDS};meta['raw']['json_text']=json.dumps(raw)
        for field in h1.TERM_FIELDS:r['terms'].setdefault(field,'unknown')
        d.update(family=family,period='first_half',line=None if family=='moneyline' else line,offered='pregame',regulation='first_two_12_minute_quarters',overtime='excluded',overtime_format='not_applicable',tied_score='evaluate_actual_score_predicate',normal_completion=h1.COMPLETION,settlement_score='first_half_only')
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
            future=reference(g,rows,at='2026-10-11T18:00:00Z');self.assertFalse(at_cutoff([future],s['last_update']))
            self.assertNotEqual(at_cutoff([future],'2026-10-12T18:00:00Z')[0]['availability'],'available')

class NBAChecks(unittest.TestCase):
    def test_identity_stages_repeated_games_and_reschedules(self):
        from app.normalization.nba import event_key
        for stage in ['regular_season','playoffs','play_in','nba_cup']:
            s=shared.projection(fixture(family='moneyline',stage=stage)).snapshot();self.assertEqual(len(s['games']),1)
            self.assertEqual([p['id'] for p in market_partitions(s['games'][0]['product_identity'])],['below','equal','above'])
            self.assertIn('end of second quarter',s['games'][0]['title']);self.assertNotIn('including overtime',s['games'][0]['title'])
        e=fixture()[1]['inventory']['kalshi']['events'][0];key=event_key(e)
        for change in [dict(game_id='repeated-matchup'),dict(stage='nba_cup'),dict(scheduled_start='2026-10-11T23:00:00Z',schedule_status='rescheduled')]:self.assertNotEqual(key,event_key(dict(e,**change)))
        for change in [dict(competition='WNBA'),dict(competition='NCAAB'),dict(season='2025-2026'),dict(stage='summer_league'),dict(schedule_status='rescheduled'),dict(scheduled_start='2026-10-10T23:00:00'),dict(game_id=''),dict(participants={'Los Angeles':'NBA:BOS','NYK':'NBA:NYK'})]:
            rows=fixture();rows[1]['inventory']['kalshi']['events'][0].update(change);self.assertFalse(shared.projection(rows).snapshot()['games'])
        alias=dict(e,participants={'Boston Celtics':'NBA:BOS','New York Knicks':'NBA:NYK'});self.assertEqual(key,event_key(alias))

    def test_no_football_or_generic_period_or_fractional_rule_inheritance(self):
        for family,line in [('moneyline',None),('spread','-3'),('total','110.5')]:
            for change in [dict(regulation='first_two_15_minute_quarters'),dict(regulation='two_20_minute_halves'),dict(period=1),dict(period='quarter_2'),dict(normal_completion='clock_zero_only'),dict(series_id='KXNFL1H'),dict(offered='halftime')]:
                rows=fixture(family=family,line=line);rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor'].update(change);shared.reseal(rows,'kalshi');self.assertFalse(shared.projection(rows).snapshot()['games'])
        for structure in ['fractional_tie_0.50','achievement_shared_winners','three_way','unknown']:
            rows=fixture(family='moneyline');rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor']['winner_structure']=structure;shared.reseal(rows,'kalshi');self.assertFalse(shared.projection(rows).snapshot()['games'])
        for field in ['abandonment','shortened_game','refund','forfeit','venue_change']:
            rows=fixture();del rows[1]['inventory']['kalshi']['markets'][0]['score_review']['terms'][field];shared.reseal(rows,'kalshi');self.assertFalse(shared.projection(rows).snapshot()['games'])

class Filters(unittest.TestCase):
    def test_three_families_filter_and_unknown_winner(self):
        from tests.nba_first_half_preview import combined_fixture
        s=shared.projection(combined_fixture()).snapshot();self.assertEqual(len(s['games']),4,s['market_catalog'])
        for period,family,count in [('first_half','',12),('full_game','',4),('second_half','',0),('first_half','moneyline',4),('first_half','spread',4),('first_half','total',4)]:self.assertEqual(len(product_view.dashboard(s,dict(period=period,family=family),{})),count)
        self.assertTrue(any('structure unknown or unsupported' in (c['reason'] or '') for c in s['market_catalog']))

class StopAPI(shared.ScoreStopAPI):
    def setUp(self):
        from tests import score_lines_preview,nba_first_half_preview
        self.addCleanup(patch.stopall);patch.object(score_lines_preview,'owner',nba_first_half_preview.owner).start()
