"""Retained candidate diagnostics are independent of binding and calculations."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction
import json
from pathlib import Path
import unittest

from app.collection.current_comparison_inputs import attach
from app.collection.current_aggregate_admission import admit
from app.collection.current_benchmark import attach as benchmark
from app.comparison.event_links import reviewed_links
from app.comparison.reference_gap import assessment, registry
from app.dashboard.current_contract import quotes_of, serialize, stamp

ROOT=Path(__file__).resolve().parents[1]


def raw():
    return json.loads((ROOT/'app/fixtures/comparison-retained-native-v1.json').read_text())['snapshot']


def selected(snapshot):
    return next(q for e in snapshot['events'] for g in e['groups'] for o in g['outcomes']
        for q in quotes_of(o) if q['source']['native_market_id']=='1083081')


class ReferenceGapTests(unittest.TestCase):
    def test_exact_original_attachment_survives_profiles_and_api_without_reference(self):
        snapshot=raw();q=selected(snapshot);before=deepcopy(q)
        snapshot['comparison_profiles']=attach(snapshot)
        diagnostic=q['comparison_input_status']['reference']['retained_candidate']
        self.assertEqual(diagnostic['candidate_provider_event_id'],'21b26266f3d78af02eb672e606275d95')
        self.assertEqual(diagnostic['status'],'candidate_only_occurrence_edge_unqualified')
        self.assertFalse(diagnostic['current_reference_qualified'])
        self.assertFalse(diagnostic['original_quote_reference_qualified'])
        for key in ('source','original','times','revision','sharp_reference'):
            self.assertEqual(q.get(key),before.get(key))
        self.assertEqual(q['original']['value'],'0.2350');self.assertEqual(q['revision'],9)
        self.assertIsNone(q['comparison_input_refs']['refs']['reference'])
        self.assertIsNone(q['comparison_input_refs']['refs']['probability'])
        api=serialize(snapshot);published=selected(api)
        self.assertEqual(published['comparison_input_status']['reference']['retained_candidate'],diagnostic)
        self.assertFalse(published['calculations']['net_ev']['eligible'])
        self.assertFalse(published['calculations']['conservative']['eligible'])
        self.assertFalse(any(g['comparison_pairs'] for e in api['events'] for g in e['groups']))

    def test_both_retained_observations_preserve_literal_prices_clocks_and_staleness(self):
        d=assessment(selected(raw()));old,new=d['retained_observations']
        self.assertEqual([x['price'] for x in old['outcomes']],['1.28','3.96'])
        self.assertEqual([x['price'] for x in new['outcomes']],['1.27','4.0'])
        self.assertEqual(old['book_at'],'2026-10-08T03:08:49Z')
        self.assertEqual(new['market_at'],'2026-10-08T23:59:58Z')
        age=stamp(selected(raw())['times']['source_at'])-stamp(new['market_at'])
        self.assertGreater(age,timedelta(seconds=1800))
        weights=[1/Fraction(x['price']) for x in new['outcomes']]
        # Independent arithmetic is a dated candidate example, never selected EV.
        self.assertEqual(weights[1]/sum(weights),Fraction(127,527))
        self.assertIsNone(new['overtime_evidence'])
        self.assertEqual(reviewed_links().resolve('the_odds_api',d['candidate_provider_event_id'],
            'NFL','NFL:JAX','NFL:PHI',stamp(selected(raw())['times']['source_at']))[1],
            'provider_edge_expired_or_not_effective')

    def test_changed_event_side_role_period_observation_cannot_borrow_diagnostic(self):
        q=selected(raw())
        for key,value in [('native_event_id','other'),('native_outcome_id','2165647'),('native_side','Short')]:
            changed=deepcopy(q);changed['source'][key]=value;self.assertIsNone(assessment(changed))
        for key,value in [('participant','NFL:JAX'),('period_boundary','First half'),('predicate','not_win')]:
            changed=deepcopy(q);changed['binding']['selection'][key]=value;self.assertIsNone(assessment(changed))
        for section,key,value in [('original','value','0.2400'),('times','source_at','2026-10-09T04:00:00Z')]:
            changed=deepcopy(q);changed[section][key]=value;self.assertIsNone(assessment(changed))
        for row in registry()['records']:
            side=deepcopy(q);side['source'].update(dict(zip(('provider','native_event_id','native_market_id','native_outcome_id','native_side'),row['observation']['native_key'])))
            side['original']=deepcopy(row['observation']['original']);side['times'].update({k:row['observation'][k] for k in ('source_at','received_at')});side['binding']['selection']=deepcopy(row['selection'])
            self.assertEqual(assessment(side)['status'],'candidate_only_occurrence_edge_unqualified')
        q['sharp_reference']={'already':'qualified'};self.assertIsNone(assessment(q))

    def test_toronto_fixture_and_candidate_do_not_attach_to_selected_nfl(self):
        snapshot=raw();q=selected(snapshot);toronto=json.loads((ROOT/'app/fixtures/comparison-retained-aggregate-v1.json').read_text())
        refs=admit(json.dumps(toronto['replay']).encode(),toronto['sport'],toronto['received_at'],venue='pinnacle')
        attach(snapshot,reference_records=refs)
        self.assertIsNone(q.get('sharp_reference'));self.assertIsNone(q['comparison_input_refs']['refs']['reference'])
        # D08 ordinary benchmark rejects a different native occurrence/selection.
        qrecord=json.loads((ROOT/'app/fixtures/comparison-public-retail-v1.json').read_text())['normalized_record']
        benchmark([qrecord],refs);self.assertNotIn('sharp_reference',qrecord['quote'])
