"""SYNTHETIC NFL annotations; no native venue or forecast qualification."""
from copy import deepcopy
from hashlib import sha256
from decimal import Decimal
import json
import unittest
from unittest.mock import patch
from tests import test_b5_score_lines as shared
from app.normalization import nfl_lines
from app.normalization.score_lines import descriptor,market_partitions,payout
from app.dashboard import product_view
from app.reference.product import receipt,at_cutoff
from app.reference.score_lines import score_distribution

basketball_fixture=shared.fixture

def fixture(competition='NFL',family='spread',line='-3',equality='predicate',stage='regular_season'):
    rows=basketball_fixture('NBA',family,line,equality)
    for source,cat in rows[1]['inventory'].items():
        e=cat['events'][0];m=cat['markets'][0];r=m['score_review'];d=r['descriptor']
        start='2026-10-04T17:00:00+00:00' if stage=='regular_season' else '2027-01-17T18:00:00+00:00'
        e.update(competition='NFL',sport='american_football',season='2026',stage=stage,home='NFL:BUF',away='NFL:DET',participants={'Buffalo Bills':'NFL:BUF','Detroit Lions':'NFL:DET'},game_id='SYNTHETIC-NFL-game-1',original_start=start,scheduled_start=start,schedule_status='scheduled',title='SYNTHETIC NFL Buffalo Bills / Detroit Lions')
        d.update(participant=e['home'] if family=='spread' else 'combined',regulation='four_15_minute_quarters',overtime_format=nfl_lines.OVERTIME[stage],tied_score='evaluate_actual_score_predicate',normal_completion='all_regulation_and_applicable_overtime')
        series='KXNFL'+('SPREAD' if family=='spread' else 'TOTAL');r['series_id']=series;d['series_id']=series if source=='kalshi' else None
        if source=='kalshi':r['fee_basis'].update(series_id=series,fee_type='quadratic_with_maker_fees',multiplier='1')
        r['terms'].update(completion='SYNTHETIC all NFL regulation and applicable overtime completed',shortened_game='unknown',abandonment='unknown',forfeit='unknown',venue_change='unknown')
        c=descriptor(e,d);sides=[]
        for side in d['outcomes']:
            label=(d['participant']+' '+line if family=='spread' else 'Total '+line)+' '+side['native_label']
            sides.append(dict(side,participant=label,predicate='score',threshold=c['threshold'],domain=c['domain'],label=label))
        m.update(subject=d['participant'],product_outcomes=sides)
        r.update(event_binding=nfl_lines.event_key(e),event_paths={k:['SYNTHETIC_nfl_event',k] for k in nfl_lines.EVENT_FIELDS})
        meta=next(v['market'] for v in rows if v['type']=='market_selected' and v['source']==source)
        native={'evidence_label':'SYNTHETIC NFL review annotation; hypothetical prices and rules, not native qualification','SYNTHETIC_nfl_event':{k:e[k] for k in nfl_lines.EVENT_FIELDS}};meta['raw']['json_text']=json.dumps(native)
        shared.reseal(rows,source)
    return rows


def reference(game,rows=None,at='2026-09-16T12:00:00+00:00'):
    rows=fixture(stage=game['product_identity']['stage']) if rows is None else rows
    e=rows[1]['inventory']['kalshi']['events'][0]
    side=next(v for k,v in game['sides'].items() if k.startswith('kalshi:yes:'))
    binding=dict(market_identity=game['product_identity'],participant=side['participant'],source_event_id='SYNTHETIC-nfl-partition-model')
    ids={p['id'] for p in market_partitions(game['product_identity'])}
    probs={'below':'.3','equal':'.1','above':'.6'} if 'equal' in ids else {'below':'.4','above':'.6'}
    if 'below' not in ids:probs={'equal':'.1','above':'.9'}
    body=json.dumps(dict(binding,event=e,value_kind='score_partition_probability',conditional_on='completed_full_game_including_overtime',probabilities=probs))
    r=receipt(body,provider='espn_fpi',url='https://www.espn.com/SYNTHETIC-nfl-fixture',received_at=at,mode='synthetic')
    return score_distribution(r,binding,source_at='2026-09-15T12:00:00+00:00',model_version='SYNTHETIC partition table; not a forecast')


class NFLSharedChecks(shared.ScoreLines):
    """Run the unchanged partition/economics oracles against NFL inputs as well."""
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(shared,'fixture',fixture).start()
        patch.object(shared,'reference',reference).start()


class NFLSpecific(unittest.TestCase):
    def test_alias_identity_and_conflicts(self):
        from app.normalization.registry import Registry
        reg=Registry.load()
        self.assertEqual(reg.resolve('team','Buffalo Bills',league='NFL').canonical_id,'NFL:BUF')
        e=fixture()[1]['inventory']['kalshi']['events'][0];a=nfl_lines.event_key(e)
        for changes in [dict(season='2025'),dict(competition='NCAAF'),dict(stage='preseason'),dict(scheduled_start='2026-10-04T17:00:00'),dict(game_id=''),dict(home='NFL:DET')]:
            with self.assertRaises(ValueError):nfl_lines.event_key(dict(e,**changes))
        b=dict(e,scheduled_start='2026-10-05T17:00:00Z',schedule_status='rescheduled')
        self.assertNotEqual(nfl_lines.event_key(b),a)
        for field,value in [('stage','postseason'),('season','2025'),('game_id','other'),('scheduled_start','2026-10-05T17:00:00Z')]:
            rows=fixture();rows[1]['inventory']['kalshi']['events'][0][field]=value
            s=shared.projection(rows).snapshot();self.assertFalse(s['games']);self.assertTrue(any(c['reason'] for c in s['market_catalog']))
        # A later matchup has its own game ID and both reviewed starts.
        later=dict(e,game_id='SYNTHETIC-NFL-game-2',scheduled_start='2026-11-04T17:00:00Z',original_start='2026-11-04T17:00:00Z')
        self.assertNotEqual(nfl_lines.event_key(later),a)

    def test_tie_and_zero_independent_payouts(self):
        for stage,expected in [('regular_season',['below','equal','above']),('postseason',['below','above'])]:
            s=shared.projection(fixture(line='0',stage=stage)).snapshot();g=s['games'][0]
            ps=market_partitions(g['product_identity']);self.assertEqual([p['id'] for p in ps],expected)
            r=product_view.calculate(s,g,{})
            self.assertEqual([p['id'] for p in r['score_partitions']],expected)
            if stage=='regular_season':
                for side in g['sides'].values():self.assertEqual(payout(side,ps[1]),'0' if side['operator']=='gt' else '1')
                self.assertIsNone(product_view.calculate(s,g,dict(probability='.6'))['ev']['expected_profit'])
            else:
                self.assertIsNotNone(product_view.calculate(s,g,dict(probability='.6'))['ev']['expected_profit'])
                bad=product_view.calculate(s,g,dict(probability={'below':'.4','equal':'.1','above':'.5'}))
                self.assertIsNone(bad['ev']['expected_profit'])
        # Tied regular-season score is margin zero, not an automatic push at +3.
        g=shared.projection(fixture(line='-3')).snapshot()['games'][0]
        for side in g['sides'].values():self.assertEqual(payout(side,dict(representative='0')),'0' if side['operator']=='gt' else '1')

    def test_rules_scope_and_binding_rejection(self):
        for field,value in [('overtime_format','unknown'),('tied_score','void'),('normal_completion','unknown'),('overtime','excluded'),('unit','yards'),('regulation','four_12_minute_quarters'),('period','quarter_1'),('family','futures'),('participant','team_total')]:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor'][field]=value;shared.reseal(rows,'kalshi')
            self.assertFalse(shared.projection(rows).snapshot()['games'],field)
        for field in nfl_lines.TERM_FIELDS:
            rows=fixture();del rows[1]['inventory']['kalshi']['markets'][0]['score_review']['terms'][field];shared.reseal(rows,'kalshi')
            self.assertFalse(shared.projection(rows).snapshot()['games'],field)
        rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor']['overtime_format']=nfl_lines.OVERTIME['postseason'];shared.reseal(rows,'kalshi')
        self.assertFalse(shared.projection(rows).snapshot()['games'])

    def test_reference_rejects_substitutes_and_future(self):
        rows=fixture();s=shared.projection(rows).snapshot();g=s['games'][0];r=reference(g,rows)
        self.assertEqual(at_cutoff([r],s['last_update'])[0]['availability'],'available')
        for change in [dict(value_kind='moneyline_probability'),dict(value_kind='projected_score'),dict(value_kind='expected_margin'),dict(value_kind='ranking'),dict(probabilities={'below':'.4','above':'.6'}),dict(source_event_id='wrong')]:
            body=json.loads(r['receipt']['body']);body.update(change)
            rr=receipt(json.dumps(body),provider='espn_fpi',url=r['receipt']['url'],received_at=r['received_at'],mode='synthetic')
            with self.assertRaises(ValueError):score_distribution(rr,r['binding'])
        legacy=dict(r,parser='legacy',value_kind='probability',value='.6');self.assertFalse(product_view.usable(legacy))
        forged=dict(r);forged.pop('schema_version');self.assertFalse(product_view.usable(forged))
        self.assertEqual(at_cutoff([forged],s['last_update'])[0]['availability'],'unsupported')
        future=reference(g,rows,at='2026-10-05T18:00:00Z')
        self.assertFalse(at_cutoff([future],s['last_update']))
        self.assertNotEqual(at_cutoff([future],'2026-10-06T18:00:00Z')[0]['availability'],'available')

    def test_total_truth_and_unknown_size(self):
        for line,truth in [('44',['0','0','1']),('44.5',['0','1'])]:
            s=shared.projection(fixture(family='total',line=line)).snapshot();g=s['games'][0]
            side=next(v for v in g['sides'].values() if v['operator']=='gt')
            self.assertEqual([payout(side,p) for p in market_partitions(g['product_identity'])],truth)
        from app.opportunities.board import contracts
        from app.opportunities.score_lines import evaluate
        cs=contracts(s['points'][g['id']],g)
        for c in cs.values():c.update(top_size=None,visible_size=None,levels=[],warnings=['Unknown native size'])
        with patch('app.opportunities.score_lines.contracts',return_value=cs):
            r=evaluate(s['points'][g['id']],s['rows_by_game'][g['id']],'1','cent',None,next(iter(g['sides'])),g)
        self.assertTrue(all(c['profit'] is None for c in r['candidates']))


class NFLStopAPI(shared.ScoreStopAPI):
    def setUp(self):
        from tests import b5_score_lines_preview,b5_nfl_lines_preview
        self.addCleanup(patch.stopall)
        patch.object(b5_score_lines_preview,'owner',b5_nfl_lines_preview.owner).start()
