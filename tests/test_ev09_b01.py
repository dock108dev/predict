"""B01 authentic read values and explicitly authored local failure/scheduling cases."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from fractions import Fraction as F
from unittest.mock import patch
import unittest
from tests.test_ev09_n01 import retained, entries as originals, AT
from app.dashboard.comparison_board import response, age, entries, details, benchmark
from app.comparison.benchmark import TwoWayBenchmark
from app.comparison.current_dependencies import instant
from app.storage.comparison_board import catalog
from app.comparison.estimated_policy import DEFAULT_POLICY


def value():
    from tests.test_current_board_reads import context,bundle
    from app.storage.comparison_board import calculate_current
    c=context();b=bundle(c)
    return calculate_current(b,DEFAULT_POLICY,context=c,details=True)


class BoardReadModel(unittest.TestCase):
    def board(self,view,filter='all',v=None,b=None,**kw):
        from tests.test_current_board_reads import context,bundle
        return response(b or bundle(context()),v or value(),DEFAULT_POLICY,view=view,filter=filter,at=AT,**kw)
    def test_authentic_canonical_catalog_and_alternatives(self):
        b,s=retained();c=catalog([b]);self.assertEqual(len(c['games']),1);self.assertEqual(len(c['games'][0]['members']),3)
        odds=self.board('odds');self.assertEqual(len(odds['rows']),len(originals(s)));self.assertEqual(odds['benchmark']['venue'],'pinnacle')
        self.assertEqual({r['decimal_odds'] for r in odds['benchmark']['originals']},{'1.72','2.23'})
        self.assertEqual(F(odds['benchmark']['fair'][0]['decisive_probability']),F(172,395))
        self.assertEqual({r['native_side'] for r in odds['rows'] if r['venue']=='kalshi'},{'yes','no'})
        self.assertTrue(all(r['original'] for r in odds['rows']));self.assertTrue(all('financial_metrics' not in r for r in odds['rows']))
    def test_benchmark_display_and_evaluation_share_exact_authority(self):
        b=retained()[0];reference=TwoWayBenchmark.from_dict(b['benchmark'])
        with patch.object(TwoWayBenchmark,'fair_probabilities',autospec=True,return_value=reference.fair_probabilities()) as weights, \
             patch.object(TwoWayBenchmark,'clock_status',autospec=True,return_value='current') as clocks:
            shown=benchmark(b,AT)
            selected=reference.outcomes[0].selection
            weight=reference.weight(selected,at=instant(AT),venue=reference.venue,method=reference.method)
        self.assertEqual(weights.call_count,2);self.assertEqual(clocks.call_count,2)
        fair={r['participant']:F(r['decisive_probability']) for r in shown['fair']}
        self.assertEqual(sum(fair.values()),1);self.assertEqual(fair[selected.event.home_id],weight)
        self.assertEqual(benchmark(b,'2026-10-17T00:00:00Z')['freshness'],'historical')
        for status in ('unknown','future','expired'):
            with patch.object(TwoWayBenchmark,'clock_status',return_value=status):
                self.assertEqual(benchmark(b,AT)['freshness'],'historical')
                with self.assertRaisesRegex(ValueError,'benchmark_'):
                    reference.weight(selected,at=instant(AT),venue=reference.venue,method=reference.method)
    def test_benchmark_refuses_corrupt_or_crossed_originals_without_substitution(self):
        for malformed in ({}, {'outcomes':[None]}, 'unsupported'):
            b=dict(retained()[0],benchmark=malformed)
            shown=benchmark(b,AT)
            self.assertFalse(shown['available']);self.assertEqual(shown['fair'],[])
            self.assertIn('benchmark_',shown['reason'])
        b=deepcopy(retained()[0]);b['benchmark']['outcomes'][0]['decimal_odds']='1.99'
        self.assertEqual(benchmark(b,AT)['reason'],'benchmark_original_odds_association_conflict')
        b=deepcopy(retained()[0]);b['benchmark_venue']='novig'
        self.assertIn('selected_benchmark_missing',benchmark(b,AT)['reason'])
        b['benchmark']=None
        shown=benchmark(b,AT);self.assertEqual(shown['freshness'],'unavailable');self.assertEqual(shown['fair'],[])
    def test_benchmark_original_clock_boundaries_are_shared(self):
        b=retained()[0];reference=TwoWayBenchmark.from_dict(b['benchmark']);selected=reference.outcomes[0].selection
        source=instant(reference.outcomes[0].source_at)
        for offset,status in ((1800,'current'),(1801,'expired')):
            at=source+timedelta(seconds=offset)
            self.assertEqual(reference.clock_status(at),status)
            self.assertEqual(benchmark(b,at.isoformat())['freshness'],'current' if status=='current' else 'historical')
        for changes,status in (({'book_at':None,'market_at':None},'unknown'),
                               ({'book_at':AT,'market_at':AT,'received_at':(instant(AT)-timedelta(seconds=1)).isoformat()},'future')):
            changed=replace(reference,outcomes=tuple(replace(row,**changes) for row in reference.outcomes))
            bundle=dict(b,benchmark=changed.to_dict())
            self.assertEqual(changed.clock_status(instant(AT)),status)
            self.assertEqual(benchmark(bundle,AT)['freshness'],'historical')
            with self.assertRaisesRegex(ValueError,'benchmark_'):
                changed.weight(selected,at=instant(AT),venue=changed.venue,method=changed.method)
    def test_original_to_response_details_financial_trace(self):
        v=value();ev=self.board('ev',v=v);arbs=self.board('arbs',v=v)
        self.assertEqual(len(ev['rows']),len(originals(v['state'])))
        venues={q['id']:q['venue'] for _,_,q in entries(v['state'])}
        self.assertEqual(len(arbs['rows']),sum(len({venues[leg['quote_id']] for leg in pair['legs']})==2 for event in v['state']['events'] for pair in event['funded_pairs']))
        for r in ev['rows']:
            d=details(v,quote=r['quote_id'],at=AT);s=d['quote']['calculations']['funded_estimate']
            for field in ('funding','classification','model_versions'):self.assertEqual(r[field],s[field])
            self.assertEqual(r['original'],d['quote']['original'])
            for field,val in s.get('financial_metrics',{}).items():self.assertEqual(r['financial_metrics'][field],val)
        p=next(r for r in arbs['rows'] if {l['venue'] for l in r['legs']}=={'novig','kalshi'})
        self.assertIsNone(p['financial_metrics']['net_modeled_ev_usd']);self.assertIsNotNone(p['financial_metrics']['conditional_buffered_ev_usd'])
        self.assertEqual(F(p['buffer_usd']),F(p['funding']['deployed_usd'])/200)
    def test_negatives_and_empty_positive_lists(self):
        self.assertEqual(self.board('arbs','positive')['rows'],[]);self.assertEqual(self.board('arbs','positive')['availability']['outcome'],'partial')
        self.assertEqual(self.board('arbs','positive')['empty_reason'],'Some comparisons unavailable; no current positive result')
        self.assertTrue(any(F(r['financial_metrics']['buffered_ev_usd'])<0 for r in self.board('ev')['rows'] if r.get('financial_metrics',{}).get('buffered_ev_usd')))
    def test_authored_mixed_age_preserves_independent_pairs(self):
        v=value();e,g,q=next(x for x in entries(v['state']) if x[2]['venue']=='kalshi')
        q['times']['source_at']='2026-10-14T00:00:00+00:00'
        aged=age(v,at=AT);self.assertEqual(aged['status'],'mixed')
        qs={q['id']:q for _,_,q in entries(aged['state'])}
        self.assertEqual(qs[q['id']]['saved_status'],'historical')
        healthy=next(q for q in qs.values() if q['venue']=='novig');self.assertEqual(healthy['saved_status'],'current')
        for p in aged['state']['events'][0]['funded_pairs']:
            self.assertEqual(p['freshness']['status'],'historical' if q['id'] in {l['quote_id'] for l in p['legs']} else 'current')
    def test_authored_pending_member_change_removal_is_local(self):
        v=value();current=deepcopy(v['state']);e,g,q=next(x for x in entries(current) if x[2]['venue']=='kalshi')
        q['original']['value']='0.49'
        aged=age(v,at=AT,current=current)
        changed=next(r for _,_,r in entries(aged['state']) if r['id']==q['id']);self.assertEqual(changed['saved_status'],'historical')
        self.assertTrue(all(r['saved_status']=='current' for _,_,r in entries(aged['state']) if r['id']!=q['id']))
        # Removing a saved leg keeps its original price/result as historical.
        current['events'][0]['groups']=[g for g in current['events'][0]['groups'] if not any(r['id']==q['id'] for o in g['outcomes'] for r in __import__('app.dashboard.current_contract',fromlist=['quotes_of']).quotes_of(o))]
        aged=age(v,at=AT,current=current);self.assertTrue(any('dependency_changed_or_removed' in r['calculations']['funded_estimate']['freshness']['reasons'] for _,_,r in entries(aged['state'])))
    def test_profile_reference_kickoff_and_stop_withdraw_authority(self):
        v=value();before=deepcopy(v);future=age(v,at='2026-10-17T00:00:00Z');self.assertEqual(future['status'],'historical');self.assertEqual(future['as_of'],AT)
        stopped=age(v,at=AT,stopped=True)
        self.assertTrue(all(not q['calculations']['funded_estimate'].get('classification',{}).get('main_positive_eligible') for _,_,q in entries(stopped['state'])))
        self.assertEqual(age(v,at='2026-10-14T01:50:00Z')['status'],'historical')
        self.assertEqual(before,v)
