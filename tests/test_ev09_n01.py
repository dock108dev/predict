"""Authentic retained replay; failure mutations and matching vectors are authored."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
from functools import lru_cache
from pathlib import Path
import json
import unittest
from app.comparison.combined_inputs import build, calculate, validate
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.comparison.estimated_ev import evaluate
from app.comparison.estimated_pair import Leg, evaluate as pair
from app.comparison.benchmark import TwoWayBenchmark
from app.comparison.current_dependencies import instant
from app.comparison.occurrence_matching import OccurrenceResolver
from app.comparison.event_links import EventLinks
from app.dashboard.current_contract import quotes_of
from tests.test_ev02_occurrence import rows, AT as MATCH_AT

AT='2026-10-14T01:15:09.650084+00:00'
SELECTED=('the_odds_api','855f58fad5f0f14b239f4f63df27998b')
def envelopes():return json.loads((Path(__file__).parent/'fixtures/ev09-n01-envelopes.json').read_text())
@lru_cache(maxsize=1)
def retained():
    b=build(envelopes(),at=AT,selected=SELECTED)[0]
    return b,calculate(b,DEFAULT_POLICY)
def entries(state):return [(e,g,q) for e in state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)]

class NativeOccurrence(unittest.TestCase):
    def test_authentic_required_numeric_inputs_and_pair(self):
        b,s=retained();self.assertEqual(len(b['members']),3);self.assertEqual(len(s['events']),1)
        for venue in ('kalshi','polymarket_us'):
            self.assertTrue(any(q['calculations']['funded_estimate']['financial_metrics']['buffered_ev_usd'] is not None for _,_,q in entries(s) if q['venue']==venue))
        p=next(p for p in s['events'][0]['funded_pairs'] if p['model_available'] and {x['native_key'][0] for x in p['legs']}=={'novig','kalshi'})
        self.assertIsNone(p['financial_metrics']['net_modeled_ev_usd']);self.assertIsNotNone(p['financial_metrics']['conditional_buffered_ev_usd'])
        self.assertLess(F(p['buffered_decisive_minimum_usd']),0);self.assertEqual(F(p['buffer_usd']),F(p['deployed_capital_usd'])/200)
        self.assertFalse(p['classification']['main_positive_eligible'])
    def test_roundtrip_replay_originals(self):
        b,s=retained();self.assertEqual(validate(json.loads(json.dumps(b))),b);self.assertEqual(calculate(b,DEFAULT_POLICY),s)
        self.assertEqual(TwoWayBenchmark.from_dict(b['benchmark']).to_dict(),b['benchmark'])
        originals={r['id']:r for r in envelopes()}
        for r in b['envelopes']:self.assertEqual(r,originals[r['id']])
        self.assertTrue(all(q['id'] for _,_,q in entries(s)))
    def test_no_short_and_declared_grid(self):
        _,s=retained();_,_,no=next(r for r in entries(s) if r[2]['venue']=='kalshi' and r[2]['source']['native_side']=='no')
        self.assertEqual(no['binding']['selection']['predicate'],'not_win');self.assertEqual(no['native_contract']['predicate']['predicate'],'not_win')
        r=no['calculations']['funded_estimate'];self.assertEqual(F(r['states']['tie']['receipt_usd']),F(r['native_quantity'])/2)
        _,_,short=next(r for r in entries(s) if r[2]['source']['native_side']=='Short')
        self.assertEqual(short['source']['native_outcome_id'],'2309611');self.assertIn('estimate_short_collateral_unresolved',short['calculations']['funded_estimate']['reasons'])
        for _,_,q in entries(s):
            r=q['calculations']['funded_estimate']
            if q['venue'] in ('kalshi','polymarket_us') and r['model_available']:
                self.assertEqual(F(r['native_quantity'])%F('.01'),0);self.assertFalse(r['funding']['actual_fill_support'])
                self.assertIn('actual minimum/increment unqualified',r['grid']['qualification'])
    def test_tie_and_exception_windows(self):
        b,s=retained();p=next(p for p in s['events'][0]['funded_pairs'] if p['model_available'] and {x['native_key'][0] for x in p['legs']}=={'novig','kalshi'})
        self.assertGreater(len(p['states']),4);self.assertTrue(any(v is None for v in p['probabilities'].values()))
        self.assertIn('48 hours',json.dumps(b['records']));self.assertIn('two weeks',json.dumps(b['records']))
    def test_alternative_books_no_substitution(self):
        for venue in ('novig','prophetx'):
            b=build(envelopes(),at=AT,selected=SELECTED,benchmark_venue=venue)[0]
            self.assertTrue(all(r['selection']['native']['venue']==venue for r in b['benchmark']['outcomes']))
            self.assertEqual(len(b['benchmark_originals']['source_originals']),2)
            self.assertNotEqual(b['input_version'],retained()[0]['input_version'])
            with self.assertRaisesRegex(ValueError,'policy_conflict'):calculate(b,DEFAULT_POLICY)
            e,g,q=next(r for r in entries(retained()[1]) if r[2]['venue']=='kalshi')
            r=evaluate(q,retained()[1]['comparison_profiles'],at=instant(AT),event=e,group=g,policy=replace(DEFAULT_POLICY,benchmark_venue=venue),benchmark=b['benchmark'])
            self.assertIsNotNone(r['financial_metrics']['buffered_ev_usd'])
    def test_expired_future_and_model_scope(self):
        _,s=retained();e,g,q=next(r for r in entries(s) if r[2]['venue']=='kalshi')
        for at in ('2026-10-14T02:00:00Z','2026-10-17T00:00:00Z'):
            r=evaluate(q,s['comparison_profiles'],at=instant(at),event=e,group=g)
            self.assertFalse(r['ranking_eligible']);self.assertIsNone(r['financial_metrics']['buffered_ev_usd'])
        q=deepcopy(q);q['times']['source_at']='2026-10-15T00:00:00Z'
        self.assertFalse(evaluate(q,s['comparison_profiles'],at=instant(AT),event=e,group=g)['model_available'])
    def test_hash_and_bundle_tamper(self):
        records=envelopes();records[0]['record']['value']['sport']='NHL'
        with self.assertRaisesRegex(ValueError,'envelope_hash_conflict'):build(records,at=AT)
        b=deepcopy(retained()[0]);b['game_key']='combined:authored-wrong-game'
        with self.assertRaisesRegex(ValueError,'occurrence_clock_binding_conflict'):validate(b)
        b=deepcopy(retained()[0]);b['records'][0]['quote']['original']['value']='9'
        with self.assertRaisesRegex(ValueError,'input_identity_conflict'):validate(b)
    def test_member_policy_dependencies(self):
        _,s=retained();e,g,q=next(r for r in entries(s) if r[2]['venue']=='kalshi');p=s['comparison_profiles']
        a=evaluate(q,p,at=instant(AT),event=e,group=g);b=evaluate(q,p,at=instant(AT),event=e,group=g,policy=replace(DEFAULT_POLICY,capital_ceiling_usd='500'))
        self.assertNotEqual(a['revision'],b['revision']);q=deepcopy(q);q['revision']+=1
        self.assertNotEqual(a['dependency_revision'],evaluate(q,p,at=instant(AT),event=e,group=g)['dependency_revision'])
    def test_local_failure_isolation(self):
        _,s=retained();e,g,q=next(r for r in entries(s) if r[2]['source']['native_side']=='Short');bad=None
        with self.assertRaisesRegex(ValueError,'short_collateral_unresolved'):Leg(q,g,s['comparison_profiles'],e,instant(AT))
        healthy=[Leg(q,g,s['comparison_profiles'],e,instant(AT)) for e,g,q in entries(s) if q['venue']=='novig']
        self.assertTrue(pair(healthy)['model_available'])
    def resolve(self,r):return OccurrenceResolver(links=EventLinks()).resolve(r,clock=MATCH_AT)
    def test_three_members_partial_context(self):
        a=rows('the_odds_api','a',venue='novig',binary=False);b=rows('polymarket_us','b',shared={'sportradar':'g'});c=rows('kalshi','c')
        for r in a:r['event']['season']=r['event']['stage']=r['market_identity']['season']=r['market_identity']['stage']='unverified'
        self.assertEqual(len({r['quote']['occurrence_match']['occurrence_id'] for r in self.resolve(a+b+c)}),1)
    def test_repeated_role_reversal_and_fallback(self):
        a=rows();b=rows('polymarket_us','b');c=rows('polymarket_us','c')
        self.assertEqual(self.resolve(a+b+c)[0]['quote']['occurrence_match']['status'],'unresolved')
        for r in b:r['event']['home'],r['event']['away']=r['event']['away'],r['event']['home']
        resolved=self.resolve(a+b);self.assertNotEqual(resolved[0]['market_identity']['event'],resolved[-1]['market_identity']['event'])
    def test_shared_id_contradiction(self):
        a=rows(shared={'sportradar':'g'});b=rows('polymarket_us','b',shared={'sportradar':'g'})
        for r in b:r['event']['season']='2027'
        self.assertTrue(all(r['quote']['occurrence_match']['status']=='unresolved' for r in self.resolve(a+b)))
