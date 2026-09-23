"""SYNTHETIC NHL annotations; no native venue or forecast qualification."""
from copy import deepcopy
from hashlib import sha256
from decimal import Decimal
import json
import unittest
from unittest.mock import patch
from tests import test_b5_score_lines as shared
from app.normalization import nhl_lines
from app.normalization.score_lines import descriptor,market_partitions,payout
from app.dashboard import product_view
from app.reference.product import receipt,at_cutoff
from app.reference.score_lines import score_distribution

basketball_fixture=shared.fixture

def fixture(competition='NHL',family='spread',line='-3',equality='predicate',stage='regular_season',home='NYR',away='BOS'):
    from app.normalization.registry import Registry
    registry=Registry.load()
    rows=basketball_fixture('NBA',family,line,equality)
    for source,cat in rows[1]['inventory'].items():
        e=cat['events'][0];m=cat['markets'][0];r=m['score_review'];d=r['descriptor']
        start='2026-10-14T23:00:00+00:00' if stage=='regular_season' else '2027-05-14T23:00:00+00:00'
        e.update(competition='NHL',sport='ice_hockey',season='2026-2027',stage=stage,
            home='NHL:'+home,away='NHL:'+away,
            participants={registry.entities['NHL:'+cid]['name']:'NHL:'+cid for cid in (home,away)},
            game_id='SYNTHETIC-NHL-game-1',
            original_start=start,scheduled_start=start,schedule_status='scheduled',
            title='SYNTHETIC NHL '+registry.entities['NHL:'+home]['name']+' / '+registry.entities['NHL:'+away]['name'])
        d.update(participant=e['home'] if family=='spread' else 'combined',unit='goals',regulation='three_20_minute_periods',
            overtime_format=nhl_lines.OT[stage],settlement_score=nhl_lines.SCORE[stage],
            input_score_basis='official_final_including_shootout_award',
            normal_completion='three_periods_and_applicable_overtime_shootout',tied_score='evaluate_score_predicate_exceptions_separate')
        series='KXNHL'+('SPREAD' if family=='spread' else 'TOTAL');r['series_id']=series;d['series_id']=series if source=='kalshi' else None
        if source=='kalshi':r['fee_basis'].update(series_id=series,fee_type='quadratic',multiplier='1')
        r['terms']={k:'unknown' for k in nhl_lines.TERM_FIELDS}
        r['terms'].update(completion='SYNTHETIC completed regulation and applicable NHL overtime/shootout; score award counted once',settlement_fee='none')
        c=dict(domain='home_margin' if family=='spread' else 'combined_score',threshold=format(-Decimal(line) if family=='spread' else Decimal(line),'f'));sides=[]
        for side in d['outcomes']:
            label=(d['participant']+' '+line if family=='spread' else 'Total '+line)+' '+side['native_label']
            sides.append(dict(side,participant=label,predicate='score',threshold=c['threshold'],domain=c['domain'],label=label))
        m.update(subject=d['participant'],product_outcomes=sides)
        r.update(event_binding=nhl_lines.event_key(e),event_paths={k:['SYNTHETIC_nhl_event',k] for k in nhl_lines.EVENT_FIELDS})
        meta=next(v['market'] for v in rows if v['type']=='market_selected' and v['source']==source)
        native={'evidence_label':'SYNTHETIC NHL review annotation; hypothetical prices and rules, not native qualification','SYNTHETIC_nhl_event':{k:e[k] for k in nhl_lines.EVENT_FIELDS}};meta['raw']['json_text']=json.dumps(native)
        shared.reseal(rows,source)
    return rows


def reference(game,rows=None,at='2026-09-16T12:00:00+00:00'):
    rows=fixture(stage=game['product_identity']['stage']) if rows is None else rows
    e=deepcopy(rows[1]['inventory']['kalshi']['events'][0])
    # The reference retains exact NHL game, stage and settlement-score identity.
    side=next(v for k,v in game['sides'].items() if k.startswith('kalshi:yes:'))
    binding=dict(market_identity=game['product_identity'],participant=side['participant'],source_event_id='SYNTHETIC-nhl-partition-model')
    ids={p['id'] for p in market_partitions(game['product_identity'])}
    probs={'below':'.3','equal':'.1','above':'.6'} if 'equal' in ids else {'below':'.4','above':'.6'}
    if 'below' not in ids:probs={'equal':'.1','above':'.9'}
    body=json.dumps(dict(binding,event=e,value_kind='score_partition_probability',conditional_on='completed_full_game_exact_reviewed_nhl_settlement_score',settlement_score=game['product_identity']['rules']['settlement_score'],probabilities=probs))
    r=receipt(body,provider='synthetic_partition',url='https://fixture.invalid/SYNTHETIC-nhl-partitions',received_at=at,mode='synthetic')
    return score_distribution(r,binding,source_at='2026-09-15T12:00:00+00:00',model_version='SYNTHETIC partition table; not a forecast')


class NHLSharedChecks(shared.ScoreLines):
    """Run the unchanged partition/economics oracles against NHL inputs as well."""
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(shared,'fixture',fixture).start()
        patch.object(shared,'reference',reference).start()


class HockeySpecific(unittest.TestCase):
    def test_game_identity_stage_reschedule_repeated_opponents(self):
        rows=fixture();e=rows[1]['inventory']['kalshi']['events'][0]
        aliases=deepcopy(e);aliases['participants']={'NYR':'NHL:NYR','Boston Bruins':'NHL:BOS'}
        self.assertEqual(nhl_lines.event_key(e),nhl_lines.event_key(aliases))
        other=deepcopy(e);other.update(id='next',game_id='next',scheduled_start='2026-10-15T23:00:00Z',original_start='2026-10-15T23:00:00Z')
        self.assertNotEqual(nhl_lines.event_key(e),nhl_lines.event_key(other))
        inv={'kalshi':{'events':[e,other],'markets':[{'event_id':v['id'],'market_type':'spread'} for v in (e,other)]}}
        self.assertFalse(nhl_lines.inventory_gaps(inv))
        other['original_start']=e['original_start'];other['schedule_status']='rescheduled'
        self.assertTrue(nhl_lines.inventory_gaps(inv))
        for change in [dict(game_id='other'),dict(game_id=None),dict(original_start=None),dict(season='2025-2026'),dict(stage='playoffs'),dict(competition='AHL'),dict(schedule_status='suspended'),dict(participants={'New York':'NHL:NYR','Boston Bruins':'NHL:BOS'})]:
            r=fixture();r[1]['inventory']['kalshi']['events'][0].update(change)
            self.assertFalse(shared.projection(r).snapshot()['games'],change)
        r=fixture()
        for source,cat in r[1]['inventory'].items():
            ev=cat['events'][0];ev.update(scheduled_start='2026-10-15T23:00:00Z',schedule_status='rescheduled')
            cat['markets'][0]['score_review']['event_binding']=nhl_lines.event_key(ev)
            meta=next(v['market'] for v in r if v['type']=='market_selected' and v['source']==source)
            native=json.loads(meta['raw']['json_text']);native['SYNTHETIC_nhl_event']={k:ev[k] for k in nhl_lines.EVENT_FIELDS};meta['raw']['json_text']=json.dumps(native);shared.reseal(r,source)
        self.assertEqual(len(shared.projection(r).snapshot()['games']),1)
        self.assertEqual(len(shared.projection(fixture(stage='playoffs')).snapshot()['games']),1)

    def test_numeric_shootout_mapping_and_double_count_refusal(self):
        rows=fixture();e=rows[1]['inventory']['kalshi']['events'][0];d=deepcopy(rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor'])
        for winner,want in [('home',{'home':4,'away':3}),('away',{'home':3,'away':4})]:
            d['input_score_basis']='on_ice_regulation_and_overtime'
            obs=dict(home=3,away=3,decision='shootout',winner=winner,score_basis=d['input_score_basis']);before=deepcopy(obs)
            result=nhl_lines.settlement_score(e,d,obs)
            self.assertEqual(obs,before);self.assertEqual(result['settlement'],want)
            self.assertEqual(sum(result['adjustment'].values()),1)
            # Official score already carries the award: zero further adjustment.
            d['input_score_basis']='official_final_including_shootout_award'
            official=dict(want,decision='shootout',winner=winner,score_basis=d['input_score_basis'])
            mapped=nhl_lines.settlement_score(e,d,official)
            self.assertEqual(mapped['settlement'],want);self.assertEqual(sum(mapped['adjustment'].values()),0)
        d['input_score_basis']='on_ice_regulation_and_overtime'
        for obs in [dict(home=4,away=3,decision='shootout',winner='home',score_basis=d['input_score_basis']),dict(home=3,away=3,decision='shootout',winner='unknown',score_basis=d['input_score_basis']),dict(home=3,away=3,decision='shootout',winner='home',score_basis='shootout_attempts')]:
            with self.assertRaises(ValueError):nhl_lines.settlement_score(e,d,obs)
        with self.assertRaises(ValueError):nhl_lines.settlement_score(e,d,result)
        play=fixture(stage='playoffs');pe=play[1]['inventory']['kalshi']['events'][0];pd=play[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor']
        with self.assertRaises(ValueError):nhl_lines.settlement_score(pe,pd,dict(home=4,away=3,decision='shootout',winner='home',score_basis=pd['input_score_basis']))
        mapped=nhl_lines.settlement_score(pe,pd,dict(home=4,away=3,decision='overtime',winner='home',score_basis=pd['input_score_basis']))
        self.assertEqual(mapped['adjustment'],{'home':0,'away':0})
        # Independent line truth: 3-3 on ice, home shootout winner => 4-3, total 7.
        side=dict(operator='gt',threshold='6.5',equality='predicate',refund_fees='retained')
        self.assertEqual(payout(side,dict(representative='6')),'0');self.assertEqual(payout(side,dict(representative='7')),'1')
        side['threshold']='1.5';self.assertEqual(payout(side,dict(representative='1')),'0')

    def test_scope_score_convention_and_exception_limits(self):
        for field,value in [('unit','points'),('regulation','two_20_minute_halves'),('period','regulation'),('period','period_1'),('family','series'),('family','futures'),('participant','team_total'),('overtime','excluded'),('overtime_format','unknown'),('settlement_score','all_shootout_attempt_goals'),('settlement_score','unknown'),('input_score_basis','unknown'),('normal_completion','official_shortened'),('tied_score','impossible')]:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor'][field]=value;shared.reseal(rows,'kalshi')
            self.assertFalse(shared.projection(rows).snapshot()['games'],field)
        for term in nhl_lines.TERM_FIELDS:
            rows=fixture();del rows[1]['inventory']['kalshi']['markets'][0]['score_review']['terms'][term];shared.reseal(rows,'kalshi')
            self.assertFalse(shared.projection(rows).snapshot()['games'],term)
        rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor']['input_score_basis']='on_ice_regulation_and_overtime';shared.reseal(rows,'kalshi')
        self.assertEqual(len(shared.projection(rows).snapshot()['games']),1) # Same resulting scoring convention, different explicit input representation.
        s=shared.projection(fixture(line='0')).snapshot();g=s['games'][0]
        self.assertEqual([p['id'] for p in market_partitions(g['product_identity'])],['below','equal','above'])
        result=product_view.calculate(s,g,dict(probability='.6'));self.assertIsNone(result['ev']['expected_profit'])
        self.assertTrue(all(c['worst_case_all_outcomes'] is None for c in result['candidates']))
        for term in ['shortened_game','suspension','resumed_game','postponement','cancellation','tie','refund']:
            self.assertEqual(result['candidates'][0]['settlement']['exceptions']['kalshi'][term],'unknown')
        self.assertIn('shootout: one winner goal, counted once',g['title'])

    def test_line_fees_and_explicit_probability_scoring(self):
        rows=fixture();s=shared.projection(rows).snapshot();g=s['games'][0];r=reference(g,rows)
        self.assertEqual(at_cutoff([r],s['last_update'])[0]['availability'],'available')
        for changes in [dict(value_kind='expected_goals'),dict(value_kind='projected_score'),dict(value_kind='moneyline_probability'),dict(value_kind='rating'),dict(settlement_score='on_ice_goals_only'),dict(conditional_on='completed_full_game_including_overtime'),dict(probabilities={'above':'.6','below':'.4'})]:
            body=json.loads(r['receipt']['body']);body.update(changes)
            rr=receipt(json.dumps(body),provider='synthetic_partition',url=r['receipt']['url'],received_at=r['received_at'],mode='synthetic')
            with self.assertRaises(ValueError):score_distribution(rr,r['binding'])
        with self.assertRaises(ValueError):receipt(r['receipt']['body'],provider='synthetic_partition',url=r['receipt']['url'],received_at=r['received_at'],mode='observation')
        forged=dict(r);forged.pop('schema_version');self.assertEqual(at_cutoff([forged],s['last_update'])[0]['availability'],'unsupported')
        rows[1]['inventory']['kalshi']['markets'][0]['score_review']['fee_basis']['series_id']='KXNHLGAME';shared.reseal(rows,'kalshi')
        s=shared.projection(rows).snapshot();result=product_view.calculate(s,s['games'][0],{})
        self.assertTrue(all(c['profit'] is None for c in result['candidates']))


class HockeyStopAPI(shared.ScoreStopAPI):
    def setUp(self):
        from tests import b5_score_lines_preview,b5_nhl_lines_preview
        self.addCleanup(patch.stopall)
        patch.object(b5_score_lines_preview,'owner',b5_nhl_lines_preview.owner).start()
