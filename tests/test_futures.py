"""Synthetic championship fields; no collected markets or forecasts."""
import json,unittest
from copy import deepcopy
from decimal import Decimal
from tests.test_score_lines import fixture as base,reseal
from tests.test_periods import snapshot
from tests.test_diamond_ice_resolution import rec,view
from app.normalization import futures
from app.dashboard import product_view
from app.reference.product import receipt
from app.reference.score_lines import score_distribution


def fixture(category='league_champion',overlap=False,unknown=False):
    rows=base('NBA','spread','0')
    for source,cat in rows[1]['inventory'].items():
        e=cat['events'][0];m=cat['markets'][0];r=m['score_review'];d=r['descriptor']
        field=['NBA:BOS','NBA:LAL','NBA:NYK'];states=[dict(id='champion-'+cid,winners=[cid]) for cid in field]
        if overlap:states.append(dict(id='shared',winners=field[:2]))
        if unknown:states.append(dict(id='no_award',winners=[]))
        e.update(horizon_start='2026-09-01T00:00:00Z',stage='championship',championship_id='SYNTHETIC-NBA-'+category,category=category,horizon='2026-2027 championship',field=field,states=states,field_structure='overlapping' if overlap else 'mutually_exclusive',gender='men',division=None,conference_id='SYNTHETIC-EAST' if category=='conference_champion' else None,scheduled_start='2027-07-01T00:00:00Z',title='SYNTHETIC NBA championship field')
        d.update(family='futures',period='season',line=None,participant=field[0],category=category,horizon=e['horizon'],settlement_model='shared_cent_floor',state_space='explicit_exhaustive',contract_document='https://kalshi-public-docs.s3.amazonaws.com/contract_terms/ACHIEVEMENTS.pdf')
        for n,side in enumerate(d['outcomes']):
            affirmative=side['native_label'].lower() in ('yes','long')
            side['role']='achievement' if affirmative else 'not_achievement'
            side['payouts']={}
            for state in states:
                yes=None if not state['winners'] else (Decimal(1)/len(state['winners'])).quantize(Decimal('.01'),rounding='ROUND_DOWN') if field[0] in state['winners'] else Decimal(0)
                side['payouts'][state['id']]=None if yes is None else str(yes if affirmative else 1-yes)
        m.update(market_type='futures',period='season',line=None,subject=field[0],category=category,horizon=e['horizon'])
        m['product_outcomes']=[dict(side,participant=field[0]+' '+side['native_label'],predicate='score',operator='state',threshold=None,domain='championship_states',label=field[0]+' '+side['native_label']) for side in d['outcomes']]
        r.update(event_binding=futures.event_key(e),event_paths={k:['SYNTHETIC_future_event',k] for k in futures.EVENT_FIELDS},series_id='SYNTHETIC-NBA-CHAMPION')
        d['series_id']=r['series_id'] if source=='kalshi' else None
        if source=='kalshi':r['fee_basis']['series_id']=r['series_id']
        r['terms']={k:'unknown' for k in futures.TERM_FIELDS};r['terms'].update(completion='official_championship_awarded',award_basis='declared_by_governing_body',settlement_fee='none')
        meta=next(v['market'] for v in rows if v['type']=='market_selected' and v['source']==source);meta['raw']['json_text']=json.dumps({'SYNTHETIC_future_event':{k:e[k] for k in futures.EVENT_FIELDS}});reseal(rows,source)
    return rows

class Futures(unittest.TestCase):
    def test_all_states_and_exact_probability(self):
        for overlap in [False,True]:
            rows=fixture(overlap=overlap);s=snapshot(rows);self.assertEqual(len(s['games']),1,str([(m['source_id'],m['reason']) for m in s['market_catalog']]));g=s['games'][0]
            r=product_view.calculate(s,g,dict(probability='.6'));self.assertIsNone(r['ev']['expected_profit'])
            ids=[v['id'] for v in r['score_partitions']];dist={k:('0.4' if n==0 else '0.3') if len(ids)==3 else '0.25' for n,k in enumerate(ids)};r=product_view.calculate(s,g,dict(probability=dist));self.assertIsNotNone(r['ev']['expected_profit'])
            leg=r['ev']['leg'];want=sum(Decimal(dist[k])*Decimal(leg['cashflows'][k]['net_cashflow']) for k in ids);self.assertEqual(Decimal(r['ev']['expected_profit']),want)
    def test_horizon_conflict_unknown_outcome_pending_and_correction(self):
        rows=fixture(unknown=True);s=snapshot(rows);g=s['games'][0];self.assertTrue(all(c['profit'] is None for c in product_view.calculate(s,g,{})['candidates']))
        e=rows[1]['inventory']['kalshi']['events'][0];a=rec(s,g,e,period='season',status='pending');b=rec(s,g,e,minute=1,supersedes=[a['id']],period='season',completion='official_championship_awarded',award_basis='declared_by_governing_body',winning_state=e['states'][0]['id'])
        self.assertEqual(view(s,g,[a])['sporting']['state'],'pending');v=view(s,g,[a,b]);self.assertEqual(v['sporting']['state'],'corrected');self.assertIsNotNone(v['venues'][0]['expected']['payout'])
        rows[1]['inventory']['kalshi']['markets'][0]['horizon']='2027-2028 championship';self.assertEqual(snapshot(rows)['games'],[])

    def test_reference_identity_not_game_probability_or_rating(self):
        rows=fixture();s=snapshot(rows);g=s['games'][0];e=rows[1]['inventory']['kalshi']['events'][0];side=next(iter(g['sides'].values()));binding=dict(market_identity=g['product_identity'],participant=side['participant'],source_event_id='SYNTHETIC-field-forecast')
        raw=dict(binding,event=e,value_kind='score_partition_probability',conditional_on='explicit_championship_states',probabilities={v['id']:p for v,p in zip(e['states'],['.4','.3','.3'])})
        def make(data):return score_distribution(receipt(json.dumps(data),provider='synthetic_partition',url='https://example.invalid/explicit-championship',received_at='2026-09-16T12:00:00Z',mode='synthetic'),binding,source_at='2026-09-16T11:59:00Z',model_version='SYNTHETIC explicit distribution')
        self.assertEqual(make(raw)['value']['champion-NBA:BOS'],'0.4')
        for change in [dict(value_kind='rating'),dict(conditional_on='game_win'),dict(probabilities={'champion-NBA:BOS':'.4'}),dict(horizon='wrong')]:
            data=deepcopy(raw)
            if 'horizon' in change:data['market_identity']['horizon']='wrong'
            else:data.update(change)
            with self.assertRaises(ValueError):make(data)
    def test_native_yes_no_orientation_and_observed_settlement(self):
        rows=fixture(overlap=True);s=snapshot(rows);g=s['games'][0];e=rows[1]['inventory']['kalshi']['events'][0];d=rows[1]['inventory']['kalshi']['markets'][0]['score_review']['descriptor']
        from app.normalization.futures import descriptor
        for state,yes_value in [('champion-NBA:BOS','1'),('champion-NBA:LAL','0'),('shared','0.5')]:
            r=rec(s,g,e,period='season',completion='official_championship_awarded',award_basis='declared_by_governing_body',winning_state=state);v=view(s,g,[r])
            yes=next(x for x in v['venues'] if x['contract'].startswith('kalshi:yes:'));no=next(x for x in v['venues'] if x['contract'].startswith('kalshi:no:'))
            self.assertEqual(Decimal(yes['expected']['payout']['value']),Decimal(yes_value));self.assertEqual(Decimal(no['expected']['payout']['value']),1-Decimal(yes_value))
        d=deepcopy(d);d['outcomes'][0]['role']='not_achievement' if d['outcomes'][0]['role']=='achievement' else 'achievement'
        with self.assertRaisesRegex(ValueError,'orientation'):descriptor(e,d)
