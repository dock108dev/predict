"""Labeled hypothetical H1 annotations; independent payout oracles, no qualification."""
import json
import unittest
from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch
from tests import test_score_lines as shared
from tests.test_nfl_lines import fixture as full_fixture
from app.normalization import nfl_first_half as h1
from app.normalization.score_lines import descriptor,market_partitions,payout
from app.dashboard import product_view
from app.reference.product import receipt,at_cutoff
from app.reference.score_lines import score_distribution


def rebuild(rows,source):
    c=rows[1]['inventory'][source];e=c['events'][0];m=c['markets'][0];d=m['score_review']['descriptor'];canon=descriptor(e,d)
    sides=[]
    for side in d['outcomes']:
        op=side['operator']
        if d['family'] in ('moneyline','spread') and d['participant']==e['away']:op={'gt':'lt','ge':'le','lt':'gt','le':'ge'}[op]
        label=(d['participant']+' '+d['line'] if d['family']=='spread' else d['participant']+' First half winner' if d['family']=='moneyline' else 'Total '+d['line'])+' '+side['native_label']
        sides.append(dict(side,participant=label,predicate='score',operator=op,threshold=canon['threshold'],domain=canon['domain'],label=label))
    m.update(market_type=d['family'],period=d['period'],subject=d['participant'],line=d['line'],product_outcomes=sides)
    shared.reseal(rows,source)


def fixture(competition='NFL',family='spread',line='-3',equality='predicate',stage='regular_season'):
    rows=full_fixture('NFL','spread' if family=='moneyline' else family,'0' if family=='moneyline' else line,equality,stage)
    for source,c in rows[1]['inventory'].items():
        e=c['events'][0];r=c['markets'][0]['score_review'];d=r['descriptor']
        d.update(family=family,period='first_half',line=None if family=='moneyline' else line,offered='pregame',regulation='first_two_15_minute_quarters',overtime='excluded',overtime_format='not_applicable',normal_completion=h1.COMPLETION,settlement_score='first_half_only')
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
    r=receipt(json.dumps(dict(binding,event=e,value_kind='score_partition_probability',conditional_on='completed_first_half_only',probabilities=probs)),provider='espn_fpi',url='https://www.espn.com/SYNTHETIC-first-half',received_at=at,mode='synthetic')
    return score_distribution(r,binding,source_at='2026-09-15T12:00:00+00:00',model_version='SYNTHETIC H1 partition table; not a forecast')


class SharedChecks(shared.ScoreLines):
    def setUp(self):
        self.addCleanup(patch.stopall);patch.object(shared,'fixture',fixture).start();patch.object(shared,'reference',reference).start()


class FirstHalf(unittest.TestCase):
    def test_winner_tie_and_uncovered_pair(self):
        for stage in ('regular_season','postseason'):
            s=shared.projection(fixture(family='moneyline',stage=stage)).snapshot();g=s['games'][0]
            self.assertIsNone(g['product_identity']['line']);self.assertEqual(g['product_identity']['period'],'first_half')
            parts=market_partitions(g['product_identity']);self.assertEqual([p['id'] for p in parts],['below','equal','above'])
            for side in g['sides'].values():self.assertEqual([payout(side,p) for p in parts],['0','0','1'] if side['operator']=='gt' else ['1','1','0'])
            r=product_view.calculate(s,g,{});self.assertIsNone(r['ev']['expected_profit'])
            self.assertTrue(any(c['profit'] is not None for c in r['candidates']))
            # Bind US team-win to the opposite team. Both positive wins now lose at tie.
            rows=fixture(family='moneyline',stage=stage);c=rows[1]['inventory']['polymarket_us'];c['markets'][0]['score_review']['descriptor']['participant']=c['events'][0]['away'];rebuild(rows,'polymarket_us')
            s=shared.projection(rows).snapshot();self.assertEqual(len(s['games']),1)
            r=product_view.calculate(s,s['games'][0],{})
            both=next(c for c in r['candidates'] if all(l['score_predicate']['operator'] in ('gt','lt') for l in c['legs']))
            self.assertLess(Decimal(both['profit']),0);self.assertEqual(Decimal(both['normal_cashflows']['equal']),-Decimal(both['cash']))
            self.assertIsNone(both['worst_case_all_outcomes'])

    def test_dnb_refund_and_three_way_unsupported(self):
        s=shared.projection(fixture(family='moneyline',equality='stake_refund')).snapshot();g=s['games'][0]
        r=product_view.calculate(s,g,dict(probability={'below':'.3','equal':'.1','above':'.6'}))
        for c in r['candidates']:
            if c['profit'] is not None:self.assertEqual(Decimal(c['normal_cashflows']['equal']),-Decimal(c['fees']))
        for change in [dict(winner_structure='three_way'),dict(winner_structure='unknown'),dict(line='0')]:
            rows=fixture(family='moneyline');rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor'].update(change);shared.reseal(rows,'kalshi')
            snap=shared.projection(rows).snapshot();self.assertFalse(snap['games']);self.assertTrue(any(c['reason'] for c in snap['market_catalog']))
        rows=fixture(family='moneyline',equality='stake_refund')
        for side in rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor']['outcomes']:side['refund_fees']='returned'
        rebuild(rows,'kalshi');s=shared.projection(rows).snapshot();self.assertTrue(all(c['profit'] is None for c in product_view.calculate(s,s['games'][0],{})['candidates']))

    def test_first_half_score_isolation(self):
        for family,line,want in [('moneyline',None,'-3'),('spread','-3','-3'),('total','20.5','17')]:
            g=shared.projection(fixture(family=family,line=line)).snapshot()['games'][0];i=g['product_identity']
            obs=dict(period='first_half',complete=True,event=i['event'],home=7,away=10,second_half={'home':45,'away':0},overtime={'home':6,'away':0})
            self.assertEqual(h1.score_value(i,obs),want)
            obs.update(second_half={'home':0,'away':99},overtime={'home':0,'away':99});self.assertEqual(h1.score_value(i,obs),want)
            for field,value in [('period','full_game'),('complete',False),('event',[]),('home',None)]:
                with self.assertRaises(ValueError):h1.score_value(i,dict(obs,**{field:value}))

    def test_scope_and_rules(self):
        for family in ('moneyline','spread','total'):
            for field,value in [('period','full_game'),('period','second_half'),('period','quarter_1'),('offered','in_play'),('overtime','included'),('normal_completion','unknown'),('settlement_score','final_game'),('tied_score','unknown')]:
                rows=fixture(family=family,line='20.5' if family=='total' else '-3');rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor'][field]=value;shared.reseal(rows,'kalshi')
                self.assertFalse(shared.projection(rows).snapshot()['games'],(family,field,value))
            for field in h1.TERM_FIELDS:
                rows=fixture(family=family,line='20.5' if family=='total' else '-3');del rows[1]['inventory']['kalshi']['markets'][0]['score_review']['terms'][field];shared.reseal(rows,'kalshi');self.assertFalse(shared.projection(rows).snapshot()['games'])
        a=shared.projection(fixture()).snapshot()['games'][0];b=shared.projection(full_fixture()).snapshot()['games'][0];self.assertNotEqual(a['id'],b['id'])

    def test_probability_period_and_timing(self):
        for family,line in [('moneyline',None),('spread','-3'),('total','20.5')]:
            rows=fixture(family=family,line=line);s=shared.projection(rows).snapshot();g=s['games'][0];r=reference(g,rows)
            self.assertEqual(at_cutoff([r],s['last_update'])[0]['availability'],'available')
            for change in [dict(conditional_on='completed_full_game_including_overtime'),dict(value_kind='ranking'),dict(value_kind='projected_score'),dict(probabilities={'above':'.6'}),dict(source_event_id='wrong')]:
                body=json.loads(r['receipt']['body']);body.update(change);rr=receipt(json.dumps(body),provider='espn_fpi',url=r['receipt']['url'],received_at=r['received_at'],mode='synthetic')
                with self.assertRaises(ValueError):score_distribution(rr,r['binding'])
            self.assertFalse(product_view.usable(dict(r,parser='legacy')))
            future=reference(g,rows,at='2026-10-05T18:00:00Z');self.assertFalse(at_cutoff([future],s['last_update']))
            self.assertNotEqual(at_cutoff([future],'2026-10-06T18:00:00Z')[0]['availability'],'available')


class Filters(unittest.TestCase):
    def test_all_families_and_period_isolation(self):
        from tests.nfl_first_half_preview import combined_fixture
        s=shared.projection(combined_fixture()).snapshot();self.assertEqual(len(s['games']),4,s['market_catalog'])
        for period,family,count in [('first_half','',12),('full_game','',4),('second_half','',0),('first_half','moneyline',4),('first_half','spread',4),('first_half','total',4)]:
            rows=product_view.dashboard(s,dict(period=period,family=family),{});self.assertEqual(len(rows),count)
            self.assertTrue(all(r['market_identity']['period']==period for r in rows))
        self.assertTrue(any('three-way' in (r.get('reason') or '') for r in s['market_catalog']))


class StopAPI(shared.ScoreStopAPI):
    def setUp(self):
        from tests import score_lines_preview,nfl_first_half_preview
        self.addCleanup(patch.stopall);patch.object(score_lines_preview,'owner',nfl_first_half_preview.owner).start()
