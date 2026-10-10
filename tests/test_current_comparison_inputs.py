"""Portable replay of retained ordinary-source excerpts; no provider requests."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import unittest

from app.collection.current_aggregate_admission import admit
from app.collection.current_benchmark import attach as attach_benchmark
from app.collection.current_comparison_inputs import attach
from app.comparison.current_dependencies import references, eligibility, MAX_PROFILES, validate_profiles, profile
from app.dashboard.current_contract import stamp
from app.dashboard.current_normalized import catalog_from_normalized
from tests.current_fixture import fixture

FIXTURE=Path(__file__).parents[1]/'app/fixtures/comparison-source-bindings-retained-v1.json'


def raw_replay(*, core=False):
    retained=json.loads(FIXTURE.read_text())
    encoded=json.dumps(retained['events'],sort_keys=True,separators=(',',':')).encode()
    if sha256(encoded).hexdigest()!=retained['replay_sha256']:
        raise ValueError('Retained excerpt changed')
    records=[]
    for venue in ('novig','prophetx'):
        records.extend(admit(encoded,retained['sport'],retained['received_at'],venue=venue))
    sharp=admit(encoded,retained['sport'],retained['received_at'],venue='pinnacle')
    attach_benchmark(records,sharp)
    for r in records:r.pop('_instrument');r.pop('_fingerprint')
    envelope=fixture();envelope['clock_at']=retained['received_at'];envelope['projected_at']=retained['received_at']
    raw=catalog_from_normalized(envelope,records)
    if not core:
        raw['comparison_profiles']={}
        for e in raw['events']:
            for g in e['groups']:
                for o in g['outcomes']:
                    for q in o['quotes'].values():
                        q.pop('comparison_input_refs',None);q.pop('comparison_input_status',None)
    return raw,sharp


def selected(raw,venue='novig'):
    return next(q for e in raw['events'] for g in e['groups'] if g['market']=='winner'
        for o in g['outcomes'] if o['label']=='Toronto Maple Leafs' for q in o['quotes'].values()
        if q['venue']==venue)


class OrdinarySourceInputs(unittest.TestCase):
    def test_retained_admission_attaches_independent_facets_and_exact_originals(self):
        raw,sharp=raw_replay();before=deepcopy(selected(raw));profiles=attach(raw,reference_records=sharp)
        q=selected(raw);values=references(q,profiles)
        self.assertEqual(set(values),{'identity','reference','buffer','probability'})
        self.assertEqual(q['times'],before['times']);self.assertEqual(q['source'],before['source'])
        self.assertEqual(q['original'],before['original']);self.assertEqual(q['sharp_reference'],before['sharp_reference'])
        identity=values['identity']['payload']
        self.assertEqual(identity['selection']['native']['instrument_id'],'Toronto Maple Leafs')
        self.assertEqual(identity['selection']['predicate']['operator'],'lt')
        self.assertEqual(identity['selection']['scope']['overtime'],'unknown')
        ref=values['reference']['payload'];self.assertEqual(ref['original_odds'],['2.47','1.61'])
        self.assertEqual(len(ref['outcomes']),2)
        self.assertEqual([r['source_at'] for r in ref['outcomes']],ref['source_at'])
        self.assertEqual(len({r['source']['native_outcome_id'] for r in ref['outcomes']}),2)
        prob=values['probability']['payload']
        self.assertEqual(Fraction(prob['probabilities'][prob['selected']]),Fraction(161,408))
        self.assertEqual(prob['unknown_mass'],['exceptional','tie'])
        self.assertEqual(q['comparison_input_refs']['phase'],'unknown')
        self.assertEqual(q['comparison_input_status']['fee']['status'],'applicability_unresolved')
        self.assertEqual(q['comparison_input_status']['quantity']['reason'],'legal_minimum_increment_tick_unavailable')
        self.assertEqual(values['buffer']['payload']['ceiling_usd'],'100')
        validate_profiles(profiles)

    def test_missing_opposition_and_fee_do_not_erase_identity_or_policy(self):
        raw,sharp=raw_replay();q=selected(raw);q.pop('sharp_reference')
        profiles=attach(raw,reference_records=sharp[:1]);values=references(q,profiles)
        self.assertEqual(set(values),{'identity','buffer'})
        self.assertEqual(q['comparison_input_status']['reference']['reason'],'exact_pinnacle_opposition_unavailable')
        raw,sharp=raw_replay();profiles=attach(raw,reference_records=[]);q=selected(raw)
        self.assertEqual(q['comparison_input_status']['reference']['status'],'available_but_unbound')
        self.assertEqual(references(q,profiles)['reference']['payload']['original_odds'],['2.47','1.61'])

    def test_clock_expiry_and_revisions_use_originals(self):
        raw,sharp=raw_replay();profiles=attach(raw,reference_records=sharp);q=selected(raw)
        old=deepcopy(q['comparison_input_refs']);at=stamp(q['times']['received_at'])
        reasons=eligibility(q,profiles,at+timedelta(seconds=901))
        self.assertIn('source_phase_unknown',reasons)
        # Net clock expiry requires an independently established phase.
        q['comparison_input_refs']['phase']='pregame'
        self.assertIn('source_price_expired',eligibility(q,profiles,at+timedelta(seconds=901)))
        q['comparison_input_refs']['phase']='unknown'
        # Caller supplies the current registry on every latest snapshot.
        raw['comparison_profiles']=profiles
        self.assertEqual(attach(raw,reference_records=sharp),profiles)
        self.assertEqual(q['comparison_input_refs'],old)
        q['times']['source_at']='2026-10-08T23:52:46Z'
        # Fully bound core profiles remain immutable. Admission explicitly
        # removes a superseded missing facet before requesting a new fallback.
        q['comparison_input_refs']['refs']['identity']=None
        newer=attach(raw,reference_records=sharp)
        self.assertNotEqual(q['comparison_input_refs']['refs']['identity'],old['refs']['identity'])
        self.assertEqual(q['comparison_input_refs']['refs']['reference'],old['refs']['reference'])
        self.assertNotEqual(newer,profiles)

    def test_conflicting_attachment_is_local_and_healthy_quotes_survive(self):
        raw,sharp=raw_replay();bad=selected(raw);healthy=selected(raw,'prophetx')
        bad['binding']['selection']['participant']='conflicting-participant'
        profiles=attach(raw,reference_records=sharp)
        self.assertIsNone(bad['comparison_input_refs']['refs']['identity'])
        self.assertEqual(bad['comparison_input_status']['identity']['status'],'contradictory')
        self.assertIsNotNone(healthy['comparison_input_refs']['refs']['identity'])
        self.assertIn('buffer',references(bad,profiles))

    def test_bounded_latest_registry_defers_profiles_without_dropping_prices(self):
        raw,sharp=raw_replay();event=raw['events'][0];copies=[]
        for index in range(20):
            e=deepcopy(event);e['id']+=':'+str(index)
            # Keep each exact binding consistent with its copied source-local
            # event; this stress input is explicitly controlled, not evidence.
            for g in e['groups']:
                for o in g['outcomes']:
                    for q in o['quotes'].values():q['binding']['selection']['event_id']=e['id']
            copies.append(e)
        raw['events']=copies;count=sum(len(o['quotes']) for e in copies for g in e['groups'] for o in g['outcomes'])
        profiles=attach(raw,reference_records=sharp)
        self.assertLessEqual(len(profiles),MAX_PROFILES)
        self.assertEqual(sum(len(o['quotes']) for e in raw['events'] for g in e['groups'] for o in g['outcomes']),count)
        self.assertTrue(any(s['reason']=='comparison_profile_capacity_deferred'
            for e in copies for g in e['groups'] for o in g['outcomes'] for q in o['quotes'].values()
            for s in q['comparison_input_status'].values()))
        reachable={ref for e in copies for g in e['groups'] for o in g['outcomes']
            for q in o['quotes'].values() for ref in q['comparison_input_refs']['refs'].values() if ref is not None}
        self.assertEqual(set(profiles),reachable)
        self.assertEqual(attach({'events':[]}),{})

    def test_existing_core_profiles_and_statuses_are_preserved_partial_facets_merge(self):
        raw,sharp=raw_replay(core=True);q=selected(raw)
        refs=q['comparison_input_refs']['refs']
        core_key,core_value=profile('identity',{'version':'controlled-core-complete-identity-1'})
        raw['comparison_profiles'][core_key]=core_value;refs['identity']=core_key
        q['comparison_input_status']['identity']={'status':'available_and_bound','reason':'core_identity_bound'}
        preserved=deepcopy(q['comparison_input_status']['identity'])
        probability=refs['probability'];before=deepcopy(raw['comparison_profiles'][probability])
        profiles=attach(raw,reference_records=sharp)
        self.assertEqual(q['comparison_input_refs']['refs']['identity'],core_key)
        self.assertEqual(profiles[core_key],core_value)
        self.assertEqual(q['comparison_input_status']['identity'],preserved)
        self.assertEqual(q['comparison_input_refs']['refs']['probability'],probability)
        self.assertEqual(profiles[probability],before)
        self.assertIsNotNone(q['comparison_input_refs']['refs']['reference'])
        self.assertEqual(q['comparison_input_status']['reference']['status'],'available_and_bound')
        self.assertIsNone(q['comparison_input_refs']['refs']['fee'])
        validate_profiles(profiles)
        raw['comparison_profiles']=profiles
        complete_reference=q['comparison_input_refs']['refs']['reference']
        before_refs=deepcopy(q['comparison_input_refs'])
        before_status=deepcopy(q['comparison_input_status'])
        # A third attachment with fewer receipts cannot degrade the completed
        # reference, and no superseded partial profile stays in the latest map.
        self.assertEqual(attach(raw),profiles)
        self.assertEqual(q['comparison_input_refs'],before_refs)
        self.assertEqual(q['comparison_input_status'],before_status)
        self.assertEqual(q['comparison_input_refs']['refs']['reference'],complete_reference)
        reachable={ref for e in raw['events'] for g in e['groups'] for o in g['outcomes']
            for quote in o['quotes'].values() for ref in quote['comparison_input_refs']['refs'].values()
            if ref is not None}
        self.assertEqual(set(profiles),reachable)

    def test_retained_native_units_orientation_depth_and_clocks_survive(self):
        native=Path(__file__).parents[1]/'app/fixtures/comparison-retained-native-v1.json'
        raw=json.loads(native.read_text())['snapshot']
        before=deepcopy(raw);profiles=attach(raw)
        for event,prior_event in zip(raw['events'],before['events']):
            for group,prior_group in zip(event['groups'],prior_event['groups']):
                for outcome,prior_outcome in zip(group['outcomes'],prior_group['outcomes']):
                    for venue,q in outcome['quotes'].items():
                        prior=prior_outcome['quotes'][venue];values=references(q,profiles)
                        self.assertEqual(q['source'],prior['source'])
                        self.assertEqual(q['times'],prior['times'])
                        self.assertEqual(q['original'],prior['original'])
                        self.assertEqual(q.get('depth'),prior.get('depth'))
                        self.assertEqual(values['identity']['payload']['selection']['native']['side_id'],q['source']['native_side'])
                        self.assertEqual(q['comparison_input_status']['identity']['status'],'applicability_unresolved')
                        self.assertEqual(q['comparison_input_status']['depth']['levels'],len(prior['depth']))
                        self.assertIsNone(q['comparison_input_refs']['refs']['payout'])
                        self.assertIsNone(q['comparison_input_refs']['refs']['fee'])
                        self.assertIsNone(q['comparison_input_refs']['refs']['quantity'])
