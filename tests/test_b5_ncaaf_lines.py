"""SYNTHETIC NCAAF annotations; no native venue or forecast qualification."""
from copy import deepcopy
from hashlib import sha256
from decimal import Decimal
import json
import unittest
from unittest.mock import patch
from tests import test_b5_score_lines as shared
from app.normalization import ncaaf_lines
from app.normalization.score_lines import descriptor,market_partitions,payout
from app.dashboard import product_view
from app.reference.product import receipt,at_cutoff
from app.reference.score_lines import score_distribution

basketball_fixture=shared.fixture

def fixture(competition='NCAAF',family='spread',line='-3',equality='predicate',stage='regular_season',home='ALA',away='MIAOH',site='neutral'):
    from app.normalization.registry import Registry
    registry=Registry.load()
    rows=basketball_fixture('NBA',family,line,equality)
    for source,cat in rows[1]['inventory'].items():
        e=cat['events'][0];m=cat['markets'][0];r=m['score_review'];d=r['descriptor']
        start='2026-10-04T17:00:00+00:00' if stage=='regular_season' else '2027-01-17T18:00:00+00:00'
        e.update(competition='NCAAF',sport='american_football',season='2026',stage=stage,
            home='NCAAF:'+home,away='NCAAF:'+away,
            participants={registry.entities['NCAAF:'+cid]['name']:'NCAAF:'+cid for cid in (home,away)},
            subdivisions={'NCAAF:'+cid:registry.entities['NCAAF:'+cid]['football_subdivisions']['2026']['value'] for cid in (home,away)},neutral_site=site,
            game_id='SYNTHETIC-NCAAF-game-1',original_start=start,scheduled_start=start,schedule_status='scheduled',title='SYNTHETIC NCAAF '+registry.entities['NCAAF:'+home]['name']+' / '+registry.entities['NCAAF:'+away]['name'])
        d.update(participant=e['home'] if family=='spread' else 'combined',regulation='four_15_minute_quarters',
            overtime_format=ncaaf_lines.OVERTIME,overtime_scoring=ncaaf_lines.SCORING,
            tied_score='exceptional_not_normal_completed_game',normal_completion='all_regulation_and_applicable_college_overtime',
            subdivision_scope=sorted(set(e['subdivisions'].values())))
        series='KXNCAAF'+('SPREAD' if family=='spread' else 'TOTAL');r['series_id']=series;d['series_id']=series if source=='kalshi' else None
        if source=='kalshi':r['fee_basis'].update(series_id=series,fee_type='quadratic_with_maker_fees',multiplier='1')
        r['terms'].update(completion='SYNTHETIC all NCAAF regulation and applicable overtime completed',shortened_game='unknown',abandonment='unknown',forfeit='unknown',venue_change='unknown')
        c=dict(domain='home_margin' if family=='spread' else 'combined_score',threshold=format(-Decimal(line) if family=='spread' else Decimal(line),'f'));sides=[]
        for side in d['outcomes']:
            label=(d['participant']+' '+line if family=='spread' else 'Total '+line)+' '+side['native_label']
            sides.append(dict(side,participant=label,predicate='score',threshold=c['threshold'],domain=c['domain'],label=label))
        m.update(subject=d['participant'],product_outcomes=sides)
        r.update(event_binding=ncaaf_lines.event_key(e),event_paths={k:['SYNTHETIC_ncaaf_event',k] for k in ncaaf_lines.EVENT_FIELDS})
        meta=next(v['market'] for v in rows if v['type']=='market_selected' and v['source']==source)
        native={'evidence_label':'SYNTHETIC NCAAF review annotation; hypothetical prices and rules, not native qualification','SYNTHETIC_ncaaf_event':{k:e[k] for k in ncaaf_lines.EVENT_FIELDS}};meta['raw']['json_text']=json.dumps(native)
        shared.reseal(rows,source)
    return rows


def reference(game,rows=None,at='2026-09-16T12:00:00+00:00'):
    rows=fixture(stage=game['product_identity']['stage']) if rows is None else rows
    e=deepcopy(rows[1]['inventory']['kalshi']['events'][0])
    # The reference retains exact school/site/subdivision identity.
    side=next(v for k,v in game['sides'].items() if k.startswith('kalshi:yes:'))
    binding=dict(market_identity=game['product_identity'],participant=side['participant'],source_event_id='SYNTHETIC-ncaaf-partition-model')
    ids={p['id'] for p in market_partitions(game['product_identity'])}
    probs={'below':'.3','equal':'.1','above':'.6'} if 'equal' in ids else {'below':'.4','above':'.6'}
    if 'below' not in ids:probs={'equal':'.1','above':'.9'}
    body=json.dumps(dict(binding,event=e,value_kind='score_partition_probability',conditional_on='completed_full_game_including_overtime',probabilities=probs))
    r=receipt(body,provider='espn_fpi',url='https://www.espn.com/SYNTHETIC-ncaaf-fixture',received_at=at,mode='synthetic')
    return score_distribution(r,binding,source_at='2026-09-15T12:00:00+00:00',model_version='SYNTHETIC partition table; not a forecast')


class NCAAFSharedChecks(shared.ScoreLines):
    """Run the unchanged partition/economics oracles against NCAAF inputs as well."""
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.object(shared,'fixture',fixture).start()
        patch.object(shared,'reference',reference).start()


class CollegeSpecific(unittest.TestCase):
    def test_school_subdivision_site_and_missing_fcs_contract(self):
        for home,away in [('ALA','MIAOH'),('NDSU','MIAFL'),('ALA','AAMU')]:
            s=shared.projection(fixture(home=home,away=away)).snapshot()
            self.assertEqual(len(s['games']),1,s['market_catalog'])
            self.assertIn('site: neutral',s['games'][0]['title'])
        rows=fixture(home='AAMU',away='SDAKST');s=shared.projection(rows).snapshot()
        self.assertFalse(s['games']);self.assertTrue(any('FCS-only' in str(r['reason']) for r in s['market_catalog']))
        for change in [dict(participants={'Miami':'NCAAF:MIAOH','ALA':'NCAAF:ALA'}),dict(season='2025'),dict(neutral_site=None),dict(subdivisions={'NCAAF:ALA':'FCS','NCAAF:MIAOH':'FBS'})]:
            rows=fixture();rows[1]['inventory']['kalshi']['events'][0].update(change)
            self.assertFalse(shared.projection(rows).snapshot()['games'])
        a=shared.projection(fixture(site='neutral')).snapshot()['games'][0]
        b=shared.projection(fixture(site='unknown')).snapshot()['games'][0]
        self.assertNotEqual(a['id'],b['id']);self.assertIn('site: unknown',b['title'])

    def test_college_overtime_scope_and_zero(self):
        s=shared.projection(fixture(line='0')).snapshot();g=s['games'][0]
        self.assertEqual([p['id'] for p in market_partitions(g['product_identity'])],['below','above'])
        result=product_view.calculate(s,g,dict(probability='.6'))
        self.assertIsNotNone(result['ev']['expected_profit'])
        for field,value in [('overtime_format','2026_regular_max_one_10_minute_period'),('overtime_scoring','exclude_tries'),('tied_score','fraction-0.50'),('normal_completion','unknown'),('subdivision_scope',['FCS']),('period','half_1'),('overtime','excluded'),('participant','team_total'),('unit','touchdowns')]:
            rows=fixture();rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor'][field]=value;shared.reseal(rows,'kalshi')
            self.assertFalse(shared.projection(rows).snapshot()['games'],field)
        for term in ncaaf_lines.TERM_FIELDS:
            rows=fixture();del rows[1]['inventory']['kalshi']['markets'][0]['score_review']['terms'][term];shared.reseal(rows,'kalshi')
            self.assertFalse(shared.projection(rows).snapshot()['games'],term)
        # Two-point extra-period tries change the official final score, not its unit.
        side=dict(threshold='50',operator='gt',equality='predicate',refund_fees='retained')
        self.assertEqual(payout(side,dict(representative='50')),'0')
        self.assertEqual(payout(side,dict(representative='52')),'1')

    def test_native_rules_fee_and_exception_unknowns(self):
        for field,value in [('series_id','KXNFLSPREAD'),('series_id','KXNCAAFCSGAME')]:
            rows=fixture();r=rows[1]['inventory']['kalshi']['markets'][0]['score_review'];r[field]=value;r['descriptor'][field]=value;shared.reseal(rows,'kalshi')
            self.assertFalse(shared.projection(rows).snapshot()['games'])
        rows=fixture();s=shared.projection(rows).snapshot();g=s['games'][0];r=product_view.calculate(s,g,{})
        self.assertTrue(any(c['profit'] is not None for c in r['candidates']))
        self.assertTrue(all(c['worst_case_all_outcomes'] is None for c in r['candidates']))
        self.assertEqual(r['candidates'][0]['settlement']['exceptions']['kalshi']['shortened_game'],'unknown')
        rows[1]['inventory']['kalshi']['markets'][0]['score_review']['fee_basis']['series_id']='KXNFLSPREAD';shared.reseal(rows,'kalshi')
        s=shared.projection(rows).snapshot();r=product_view.calculate(s,s['games'][0],{})
        self.assertTrue(all(c['profit'] is None for c in r['candidates']))

    def test_reference_binding_and_kind(self):
        rows=fixture();s=shared.projection(rows).snapshot();g=s['games'][0];r=reference(g,rows)
        self.assertEqual(at_cutoff([r],s['last_update'])[0]['availability'],'available')
        self.assertIn('College-football',r['dependency'])
        for change in [dict(value_kind='moneyline_probability'),dict(value_kind='projected_score'),dict(value_kind='expected_margin'),dict(value_kind='ranking'),dict(probabilities={'below':'.4','above':'.6'})]:
            body=json.loads(r['receipt']['body']);body.update(change)
            rr=receipt(json.dumps(body),provider='espn_fpi',url=r['receipt']['url'],received_at=r['received_at'],mode='synthetic')
            with self.assertRaises(ValueError):score_distribution(rr,r['binding'])
        body=json.loads(r['receipt']['body']);body['event']['neutral_site']='home'
        rr=receipt(json.dumps(body),provider='espn_fpi',url=r['receipt']['url'],received_at=r['received_at'],mode='synthetic')
        with self.assertRaises(ValueError):score_distribution(rr,r['binding'])
        forged=dict(r);forged.pop('schema_version')
        self.assertEqual(at_cutoff([forged],s['last_update'])[0]['availability'],'unsupported')
        self.assertFalse(product_view.usable(forged))


class CollegeStopAPI(shared.ScoreStopAPI):
    def setUp(self):
        from tests import b5_score_lines_preview,b5_ncaaf_lines_preview
        self.addCleanup(patch.stopall)
        patch.object(b5_score_lines_preview,'owner',b5_ncaaf_lines_preview.owner).start()
