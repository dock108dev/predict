"""SYNTHETIC MLB annotations; no native venue or forecast qualification."""
from copy import deepcopy
from hashlib import sha256
from decimal import Decimal
import json
import unittest
from unittest.mock import patch
from tests import test_score_lines as shared
from app.normalization import mlb_lines
from app.normalization.score_lines import descriptor,market_partitions,payout
from app.dashboard import product_view
from app.reference.product import receipt,at_cutoff
from app.reference.score_lines import score_distribution

basketball_fixture=shared.fixture

def fixture(competition='MLB',family='spread',line='-3',equality='predicate',stage='regular_season',home='NYY',away='BOS',game_number=1):
    from app.normalization.registry import Registry
    registry=Registry.load()
    rows=basketball_fixture('NBA',family,line,equality)
    for source,cat in rows[1]['inventory'].items():
        e=cat['events'][0];m=cat['markets'][0];r=m['score_review'];d=r['descriptor']
        start='2026-10-04T17:00:00+00:00'
        e.update(competition='MLB',sport='baseball',season='2026',stage=stage,
            home='MLB:'+home,away='MLB:'+away,
            participants={registry.entities['MLB:'+cid]['name']:'MLB:'+cid for cid in (home,away)},
            game_id='SYNTHETIC-MLB-game-'+str(game_number),game_number=game_number,
            original_start=start,scheduled_start=start,schedule_status='scheduled',
            title='SYNTHETIC MLB '+registry.entities['MLB:'+home]['name']+' / '+registry.entities['MLB:'+away]['name'])
        d.update(participant=e['home'] if family=='spread' else 'combined',unit='runs',regulation='nine_scheduled_innings',
            **mlb_lines.SEMANTICS,completion_scope='normal_completed_game_only')
        series='KXMLB'+('SPREAD' if family=='spread' else 'TOTAL');r['series_id']=series;d['series_id']=series if source=='kalshi' else None
        if source=='kalshi':r['fee_basis'].update(series_id=series,fee_type='quadratic_with_maker_fees',multiplier='1')
        r['terms']={k:'unknown' for k in mlb_lines.TERM_FIELDS}
        r['terms'].update(completion='SYNTHETIC normal completed nine-inning format including all extra-inning runs; ordinary home-leading final half exemption',settlement_fee='none')
        c=dict(domain='home_margin' if family=='spread' else 'combined_score',threshold=format(-Decimal(line) if family=='spread' else Decimal(line),'f'));sides=[]
        for side in d['outcomes']:
            label=(d['participant']+' '+line if family=='spread' else 'Total '+line)+' '+side['native_label']
            sides.append(dict(side,participant=label,predicate='score',threshold=c['threshold'],domain=c['domain'],label=label))
        m.update(subject=d['participant'],product_outcomes=sides)
        r.update(event_binding=mlb_lines.event_key(e),event_paths={k:['SYNTHETIC_mlb_event',k] for k in mlb_lines.EVENT_FIELDS})
        meta=next(v['market'] for v in rows if v['type']=='market_selected' and v['source']==source)
        native={'evidence_label':'SYNTHETIC MLB review annotation; hypothetical prices and rules, not native qualification','SYNTHETIC_mlb_event':{k:e[k] for k in mlb_lines.EVENT_FIELDS}};meta['raw']['json_text']=json.dumps(native)
        shared.reseal(rows,source)
    return rows


def reference(game,rows=None,at='2026-09-16T12:00:00+00:00'):
    rows=fixture(stage=game['product_identity']['stage']) if rows is None else rows
    e=deepcopy(rows[1]['inventory']['kalshi']['events'][0])
    # The reference retains exact MLB game and doubleheader identity.
    side=next(v for k,v in game['sides'].items() if k.startswith('kalshi:yes:'))
    binding=dict(market_identity=game['product_identity'],participant=side['participant'],source_event_id='SYNTHETIC-mlb-partition-model')
    ids={p['id'] for p in market_partitions(game['product_identity'])}
    probs={'below':'.3','equal':'.1','above':'.6'} if 'equal' in ids else {'below':'.4','above':'.6'}
    if 'below' not in ids:probs={'equal':'.1','above':'.9'}
    body=json.dumps(dict(binding,event=e,value_kind='score_partition_probability',conditional_on='completed_full_game_including_extra_innings_action',probabilities=probs))
    r=receipt(body,provider='fangraphs',url='https://www.fangraphs.com/SYNTHETIC-mlb-fixture',received_at=at,mode='synthetic')
    return score_distribution(r,binding,source_at='2026-09-15T12:00:00+00:00',model_version='SYNTHETIC partition table; not a forecast')


class MLBSharedChecks(shared.ScoreLines):
    """Run the unchanged partition/economics oracles against MLB inputs as well."""
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(shared,'fixture',fixture).start()
        patch.object(shared,'reference',reference).start()


class BaseballSpecific(unittest.TestCase):
    def test_game_identity_doubleheaders_reschedules_and_aliases(self):
        from app.normalization.mlb import inventory_gaps
        rows=fixture();e=rows[1]['inventory']['kalshi']['events'][0]
        aliases=deepcopy(e);aliases['participants']={'NY Yankees':'MLB:NYY','Boston Red Sox':'MLB:BOS'}
        self.assertEqual(mlb_lines.event_key(e),mlb_lines.event_key(aliases))
        second=deepcopy(e);second.update(id=e['id']+'-2',game_id='SYNTHETIC-MLB-game-2',game_number=2)
        inv={'kalshi':{'events':[e,second]}}
        self.assertFalse(inventory_gaps(inv))
        repeated=deepcopy(second);repeated.update(game_number=1,scheduled_start='2026-10-05T17:00:00Z',original_start='2026-10-05T17:00:00Z')
        self.assertNotEqual(mlb_lines.event_key(e),mlb_lines.event_key(repeated))
        self.assertFalse(inventory_gaps({'kalshi':{'events':[e,repeated]}}))
        second['game_number']=1
        self.assertTrue(inventory_gaps(inv))
        for change in [dict(game_number=2),dict(game_id='other'),dict(season='2025'),dict(stage='playoffs'),dict(scheduled_start='2026-10-05T17:00:00Z'),dict(competition='NPB'),dict(schedule_status='suspended'),dict(participants={'New York':'MLB:NYY','Boston Red Sox':'MLB:BOS'})]:
            r=fixture();r[1]['inventory']['kalshi']['events'][0].update(change)
            self.assertFalse(shared.projection(r).snapshot()['games'],change)
        # Explicit reschedule lineage may match only after both retained reviews agree.
        r=fixture()
        for source,cat in r[1]['inventory'].items():
            ev=cat['events'][0];ev.update(scheduled_start='2026-10-05T17:00:00Z',schedule_status='rescheduled')
            review=cat['markets'][0]['score_review'];review['event_binding']=mlb_lines.event_key(ev)
            meta=next(v['market'] for v in r if v['type']=='market_selected' and v['source']==source)
            native=json.loads(meta['raw']['json_text']);native['SYNTHETIC_mlb_event']={k:ev[k] for k in mlb_lines.EVENT_FIELDS};meta['raw']['json_text']=json.dumps(native);shared.reseal(r,source)
        self.assertEqual(len(shared.projection(r).snapshot()['games']),1)
        r[1]['inventory']['kalshi']['events'][0]['original_start']='2026-10-03T17:00:00Z'
        self.assertFalse(shared.projection(r).snapshot()['games'])

    def test_explicit_baseball_scope_and_exception_limits(self):
        for field,value in [('unit','points'),('regulation','seven_innings'),('period','first_five'),('period','regulation'),('period','inning_9'),('family','series'),('family','futures'),('participant','team_total'),('extra_innings','excluded'),('extra_innings','unknown'),('pitcher_conditions','listed_pitchers'),('pitcher_conditions','unknown'),('normal_completion','moneyline_official_after_five'),('completion_scope','shortened_game'),('tied_score','impossible')]:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor'][field]=value;shared.reseal(rows,'kalshi')
            self.assertFalse(shared.projection(rows).snapshot()['games'],field)
        for term in mlb_lines.TERM_FIELDS:
            rows=fixture();del rows[1]['inventory']['kalshi']['markets'][0]['score_review']['terms'][term];shared.reseal(rows,'kalshi')
            self.assertFalse(shared.projection(rows).snapshot()['games'],term)
        s=shared.projection(fixture(line='0')).snapshot();g=s['games'][0]
        self.assertEqual([p['id'] for p in market_partitions(g['product_identity'])],['below','equal','above'])
        result=product_view.calculate(s,g,dict(probability='.6'))
        self.assertIsNone(result['ev']['expected_profit'])
        self.assertTrue(all(c['worst_case_all_outcomes'] is None for c in result['candidates']))
        for term in ['shortened_game','suspension','resumed_game','postponement','cancellation','tie','refund']:
            self.assertEqual(result['candidates'][0]['settlement']['exceptions']['kalshi'][term],'unknown')
        self.assertEqual(g['product_identity']['rules']['unit'],'runs')
        self.assertIn('action · game 1',g['title'])

    def test_line_specific_fees_and_independent_baseball_score_table(self):
        # Retained MLB line multiplier is .5; fixture default 1 is a labeled what-if.
        rows=fixture(line='-1.5');r=rows[1]['inventory']['kalshi']['markets'][0]['score_review']
        r['fee_basis'].update(multiplier='0.5',fee_type='quadratic');shared.reseal(rows,'kalshi')
        s=shared.projection(rows).snapshot();g=s['games'][0];key=next(k for k in g['sides'] if k.startswith('kalshi:yes:'))
        result=product_view.calculate(s,g,dict(contract=key,quantity='10',probability='.6'))
        # 10 * .68 cost, ceil(.07 * .5 * 10 * .68 * .32 * 100)/100 = .08.
        self.assertEqual(Decimal(result['ev']['leg']['fee']),Decimal('.08'))
        self.assertEqual(Decimal(result['ev']['expected_profit']),Decimal('-.88'))
        r['fee_basis']['series_id']='KXMLBGAME';shared.reseal(rows,'kalshi')
        s=shared.projection(rows).snapshot();result=product_view.calculate(s,s['games'][0],{})
        self.assertTrue(all(c['profit'] is None for c in result['candidates']))
        # Independent final-score truth table: extras count, a tie is not discarded.
        side=dict(threshold='1',operator='gt',equality='predicate',refund_fees='retained')
        for home,away,want in [(4,3,'0'),(5,3,'1'),(3,4,'0'),(3,3,'0')]:
            self.assertEqual(payout(side,dict(representative=str(home-away))),want)
        side.update(threshold='8.5')
        for runs,want in [('8','0'),('9','1'),('10','1')]:self.assertEqual(payout(side,dict(representative=runs)),want)

    def test_exact_line_probability_not_score_or_winner(self):
        rows=fixture();s=shared.projection(rows).snapshot();r=reference(s['games'][0],rows)
        self.assertEqual(at_cutoff([r],s['last_update'])[0]['availability'],'available')
        for changes in [dict(value_kind='predicted_runs'),dict(value_kind='projected_score'),dict(value_kind='moneyline_probability'),dict(value_kind='season_probability'),dict(conditional_on='completed_full_game_including_overtime'),dict(probabilities={'above':'.6','below':'.4'})]:
            body=json.loads(r['receipt']['body']);body.update(changes)
            rr=receipt(json.dumps(body),provider='fangraphs',url=r['receipt']['url'],received_at=r['received_at'],mode='synthetic')
            with self.assertRaises(ValueError):score_distribution(rr,r['binding'])
        body=json.loads(r['receipt']['body']);body['event']['game_number']=2
        rr=receipt(json.dumps(body),provider='fangraphs',url=r['receipt']['url'],received_at=r['received_at'],mode='synthetic')
        with self.assertRaises(ValueError):score_distribution(rr,r['binding'])


class BaseballStopAPI(shared.ScoreStopAPI):
    def setUp(self):
        from tests import score_lines_preview,mlb_lines_preview
        self.addCleanup(patch.stopall)
        patch.object(score_lines_preview,'owner',mlb_lines_preview.owner).start()
