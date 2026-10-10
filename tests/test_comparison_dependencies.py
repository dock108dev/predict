"""D10 authored revision/expiry tests; no acquisition or owner state."""
from copy import deepcopy
from datetime import timedelta
import json
import unittest

from app.comparison.current_dependencies import KINDS, VERSION, profile, digest, eligibility
from app.dashboard.current_contract import packed, serialize, stamp, validate_snapshot
from app.dashboard.current_state import CurrentStore
from tests.current_fixture import InjectedTestProvider
from tests.test_current_incremental import catalog, AT


def inputs():
    raw = catalog(2)
    for event in raw['events']:
        for group in event['groups']:
            for outcome in group['outcomes']:
                for quote in outcome['quotes'].values():
                    quote.pop('comparison_input_status', None)
    profiles = dict(raw.get('comparison_profiles', {}))
    refs = {}
    for kind in KINDS:
        payload = {'version': 'authored-' + kind + '-1'}
        if kind == 'reference':
            payload['source_at'] = [AT, AT]
        key, value = profile(kind, payload)
        profiles[key] = value
        refs[kind] = key
    raw['comparison_profiles'] = profiles
    q = raw['events'][0]['groups'][0]['outcomes'][0]['quotes']['novig']
    q['comparison_input_refs'] = dict(version=VERSION, refs=refs, phase='pregame')
    return raw


def selected(raw):
    return raw['events'][0]['groups'][0]['outcomes'][0]['quotes']['novig']


class CurrentDependencies(unittest.TestCase):
    def test_each_dependency_invalidates_once_without_unrelated_work(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                raw = inputs()
                store = CurrentStore(InjectedTestProvider(raw), monotonic=lambda: 0)
                prior = store._state['events'][1]['groups'][0]['outcomes'][0]['quotes']['novig']['calculations']['arbitrage']
                changed = deepcopy(raw)
                changed['state_revision'] = 2
                q = selected(changed)
                old = changed['comparison_profiles'][q['comparison_input_refs']['refs'][kind]]
                key, value = profile(kind, dict(old['payload'], authored_revision='2'))
                changed['comparison_profiles'][key] = value
                q['comparison_input_refs']['refs'][kind] = key
                self.assertTrue(store.commit(changed))
                self.assertEqual(store.projection_metrics, dict(projected_groups=1, reused_groups=5))
                self.assertIs(prior, store._state['events'][1]['groups'][0]['outcomes'][0]['quotes']['novig']['calculations']['arbitrage'])
                self.assertEqual(store.encoded_snapshot(), packed(serialize(changed, allow_synthetic=True)))
                self.assertFalse(store.commit(changed))

    def test_expiry_and_original_price_age_invalidate_without_packets(self):
        ticks = [0]
        raw = inputs()
        q = selected(raw)
        old_key = q['comparison_input_refs']['refs']['fee']
        key, value = profile('fee', raw['comparison_profiles'][old_key]['payload'],
                             expires_at=(stamp(AT) + timedelta(seconds=10)).isoformat())
        raw['comparison_profiles'][key] = value
        q['comparison_input_refs']['refs']['fee'] = key
        store = CurrentStore(InjectedTestProvider(raw), monotonic=lambda: ticks[0])
        before = store.snapshot()
        self.assertEqual(selected(before)['comparison_dependency_reasons'], [])
        ticks[0] = 10
        after = store.snapshot()
        self.assertEqual(selected(after)['comparison_dependency_reasons'], ['fee_inputs_expired'])
        self.assertEqual(store.projection_metrics, dict(projected_groups=1, reused_groups=5))
        delta = json.loads(store.encoded_changes(raw['runtime_id'], 1))
        self.assertEqual(len(delta['events']), 1)
        self.assertEqual(selected(before)['comparison_dependency_reasons'], [])
        ticks[0] = 901
        self.assertIn('source_price_expired', selected(store.snapshot())['comparison_dependency_reasons'])
        validate_snapshot(store.snapshot(), allow_synthetic=True)

    def test_corrupt_or_private_profiles_reject_atomically(self):
        raw = inputs()
        store = CurrentStore(InjectedTestProvider(raw), monotonic=lambda: 0)
        before = store.encoded_snapshot()
        for mutation in ('hash', 'private', 'missing', 'kind', 'float'):
            changed = deepcopy(raw)
            changed['state_revision'] = 2
            q = selected(changed)
            key = q['comparison_input_refs']['refs']['fee']
            value = changed['comparison_profiles'][key]
            if mutation == 'hash':
                value['payload']['version'] = 'tampered'
            elif mutation == 'missing':
                del changed['comparison_profiles'][key]
            else:
                if mutation == 'private':value['payload']['positions'] = {'private': '1'}
                if mutation == 'float':value['payload']['rate'] = 0.1
                if mutation == 'kind':value['kind'] = 'payout'
                new_key = digest(value)
                changed['comparison_profiles'][new_key] = value
                q['comparison_input_refs']['refs']['fee'] = new_key
                del changed['comparison_profiles'][key]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                store.commit(changed)
            self.assertEqual(store.encoded_snapshot(), before)

    def test_full_incremental_retirement_and_old_cursor_recovery(self):
        raw = inputs()
        store = CurrentStore(InjectedTestProvider(raw), monotonic=lambda: 0)
        before = store.snapshot()
        changed = deepcopy(raw)
        changed['state_revision'] = 2
        removed = changed['events'].pop()['id']
        store.commit(changed)
        delta = json.loads(store.encoded_changes(raw['runtime_id'], 1))
        events = {e['id']: e for e in before['events']}
        for eid in delta['removed_events']:events.pop(eid)
        for event in delta['events']:events[event['id']] = event
        merged = dict(delta['snapshot'], events=sorted(events.values(), key=lambda e: (e['start_at'], e['id'])))
        self.assertEqual(delta['removed_events'], [removed])
        self.assertEqual(packed(merged), store.encoded_snapshot())
        self.assertEqual(json.loads(store.encoded_changes('old', 1))['schema'], 'predict-current-1')
        self.assertEqual(json.loads(store.encoded_changes(raw['runtime_id'], 3))['schema'], 'predict-current-1')

    def test_future_source_clock_cannot_gain_authority_by_waiting(self):
        raw = inputs()
        q = selected(raw)
        q['times']['source_at'] = (stamp(AT) + timedelta(seconds=1)).isoformat()
        self.assertIn('source_clock_future', eligibility(q, raw['comparison_profiles'], stamp(AT) + timedelta(seconds=3)))
        q['times']['source_at'] = None
        self.assertIn('source_clock_unknown', eligibility(q, raw['comparison_profiles'], stamp(AT)))
