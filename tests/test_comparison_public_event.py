"""Authentic retained response with literal identity oracles; no source requests."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import unittest

from aiohttp.test_utils import AioHTTPTestCase
from app.comparison.event_evidence import strict_json
from app.comparison.public_event import extract, retained, registry, audit, validate
from app.comparison.public_retail import retained as retail
from app.comparison.current_dependencies import digest, instant, references
from app.collection.current_comparison_inputs import attach
from app.dashboard.current_contract import serialize, quotes_of, snapshot_inputs
from app.dashboard.current_normalized import catalog_from_normalized
from app.dashboard.current_state import CURRENT_KEY, CurrentStore
from app.dashboard.multi_game_server import create_app
from tests.current_fixture import fixture, InjectedTestProvider
from tests.test_current_state import owner

RAW = Path(__file__).resolve().parents[1] / 'app/fixtures/comparison-public-event-response-v1.json'


def receipt():
    value = retained()['provenance']
    return dict(status=200, eof=True, transport_complete=True, json_complete=True,
        wire_sha256=value['response_sha256'], decoded_sha256=value['decoded_sha256'],
        url=value['url'], started_at=value['request_started_at'], headers_at=value['headers_at'],
        finished_at=value['response_finished_at'], wire_bytes=value['wire_bytes'], decoded_bytes=value['decoded_bytes'])


def sealed(value):
    value['binding_version'] = digest({k: v for k, v in value.items() if k != 'binding_version'})
    return value


def state(value=None, at=None, short=False, event_enabled=True):
    value = retained() if value is None else value
    record = retail()['normalized_record']
    original = retail()['original_historical_observation']
    record['quote']['original'] = deepcopy(original['original'])
    record['quote']['times'].update(source_at=original['source_at'], received_at=original['received_at'], source_time_kind='provider_book')
    record['quote']['provenance']['sha256'] = original['provenance_sha256']
    if short:
        record['quote']['source'].update(native_outcome_id='2165647', native_side='Short')
        record['selection'].update(participant='NFL:JAX', label='Jacksonville Jaguars')
    envelope = fixture()
    envelope.update(mode='current', clock_at=at or value['effective_from'], projected_at=at or value['effective_from'])
    base = {'version': 'comparison-selected-applicability-1', 'records': []}
    return catalog_from_normalized(envelope, [record], selected_applicability=registry(base, value) if event_enabled else base)


def quote(raw):
    return next(q for e in raw['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o))


class PublicEventInputs(unittest.TestCase):
    def test_authentic_bytes_and_literal_selected_containment(self):
        self.assertEqual(RAW.stat().st_size, 3662490)
        self.assertEqual(hashlib.sha256(RAW.read_bytes()).hexdigest(), '10cbef8e6527a22bfb5d854671473847ba2e618bebff78fbb55ca177b911369b')
        graph = strict_json(RAW)
        self.assertEqual(len(graph['events']), 1)
        self.assertEqual(len(graph['events'][0]['markets']), 760)
        self.assertEqual(graph['events'][0]['markets'][459]['id'], '1083081')
        value = extract(graph, receipt())
        self.assertEqual(value, retained())
        self.assertEqual(value['occurrence']['game_id'], '19518')
        self.assertEqual(value['occurrence']['provider_game_id'], 'b635ddd1-4827-4593-ae8f-f41ae2f8914f')
        self.assertEqual(value['participant_roles'], {'away': 'NFL:PHI', 'home': 'NFL:JAX'})
        self.assertEqual(value['scope']['overtime'], 'included')
        self.assertFalse(value['occurrence']['replacement_field_present'])
        self.assertFalse(value['occurrence']['cross_source_qualified'])

    def test_broad_duplicate_wrong_event_or_market_refuses(self):
        for change in ('broad', 'wrong_event', 'duplicate_market', 'absent_market'):
            graph = strict_json(RAW)
            if change == 'broad': graph['events'].append(deepcopy(graph['events'][0]))
            elif change == 'wrong_event': graph['events'][0]['id'] = '129630'
            elif change == 'duplicate_market': graph['events'][0]['markets'].append(deepcopy(graph['events'][0]['markets'][459]))
            else: graph['events'][0]['markets'][459]['id'] = '1083082'
            with self.assertRaises(ValueError): extract(graph, receipt())

    def test_conflicting_side_attachment_and_roles_refuse(self):
        for field, number in [('marketId', 1083082), ('teamId', 62), ('long', False), ('id', '2165647')]:
            graph = strict_json(RAW);graph['events'][0]['markets'][459]['marketSides'][0][field] = number
            with self.assertRaises(ValueError): extract(graph, receipt())
        graph = strict_json(RAW)
        graph['events'][0]['markets'][459]['marketSides'][0]['team']['ordering'] = 'home'
        with self.assertRaisesRegex(ValueError, 'role_conflict'): extract(graph, receipt())

    def test_missing_role_preserves_membership_only(self):
        graph = strict_json(RAW)
        graph['events'][0]['markets'][459]['marketSides'][0]['team'].pop('ordering')
        value = extract(graph, receipt())
        self.assertTrue(value['membership'])
        self.assertFalse(value['occurrence']['source_local_qualified'])
        self.assertEqual(value['participant_roles'], {'home': 'NFL:JAX'})

    def test_replacement_and_missing_provider_are_independent_gaps(self):
        for change in ('replacement', 'provider'):
            graph = strict_json(RAW)
            if change == 'replacement': graph['events'][0]['rescheduledFromGameId'] = 19517
            else: graph['events'][0].pop('sportradarGameId')
            value = extract(graph, receipt())
            self.assertTrue(value['membership'])
            self.assertFalse(value['occurrence']['source_local_qualified'])

    def test_incomplete_transport_never_extracts(self):
        for field in ('eof', 'transport_complete', 'json_complete'):
            r = receipt();r[field] = False
            with self.assertRaisesRegex(ValueError, 'incomplete'): extract({}, r)

    def test_historical_quote_and_independent_financial_gaps(self):
        raw = state();q = quote(serialize(raw));inputs = references(q, raw['comparison_profiles'])
        self.assertEqual(q['original']['value'], '0.2350')
        self.assertEqual(q['times']['source_at'], '2026-10-09T03:55:16.261974+00:00')
        fact = inputs['identity']['payload']['public_event']
        self.assertEqual(fact['status'], 'available_and_bound')
        self.assertFalse(fact['historical_quote_applicability'])
        self.assertFalse(q['binding']['verified'])
        self.assertIsNone(q.get('sharp_reference'))
        self.assertFalse(q['calculations']['net_ev']['eligible'])
        baseline = quote(serialize(state(event_enabled=False)))
        for kind in ('payout', 'fee', 'quantity', 'reference'):
            self.assertEqual(q['comparison_input_refs']['refs'][kind], baseline['comparison_input_refs']['refs'][kind])
            self.assertNotEqual(q['comparison_input_status'][kind]['status'], 'available_and_bound')

    def test_long_short_sibling_isolation(self):
        long = quote(state());short = quote(state(short=True))
        lf = long['comparison_input_status']['identity']['public_event']
        sf = short['comparison_input_status']['identity']['public_event']
        self.assertEqual(lf['selected']['team_id'], '73')
        self.assertEqual(sf['selected']['team_id'], '62')
        self.assertEqual(sf['selected']['native_key'][-1], 'Short')
        self.assertNotEqual(long['comparison_input_refs']['refs']['identity'], short['comparison_input_refs']['refs']['identity'])
        crossed = deepcopy(long);crossed['source'].update(native_outcome_id='2165647', native_side='Short')
        self.assertEqual(audit(crossed, registry({'records': []}), instant(retained()['effective_from']))['status'], 'contradictory')

    def test_rematch_or_other_market_cannot_borrow(self):
        q = quote(state())
        for field, value in [('native_event_id', '129630'), ('native_market_id', '1083082'), ('native_outcome_id', '2165648')]:
            other = deepcopy(q);other['source'][field] = value
            self.assertIsNone(audit(other, registry({'records': []}), instant(retained()['effective_from'])))

    def test_role_conflict_not_label_or_schedule_join(self):
        q = quote(state())
        fact = audit(q, registry({'records': []}), instant(retained()['effective_from']), roles={'home': 'NFL:PHI', 'away': 'NFL:JAX'})
        self.assertEqual(fact['status'], 'contradictory')

    def test_observed_replacement_or_game_conflict_cannot_borrow(self):
        q = quote(state())
        for observed in ({'game_id': '19519'}, {'provider_game_id': 'different-occurrence'}, {'rescheduled_from_game_id': '19517'}):
            fact = audit(q, registry({'records': []}), instant(retained()['effective_from']), observed_occurrence=observed)
            self.assertEqual(fact['status'], 'contradictory')

    def test_before_interval_and_expired_never_backdate(self):
        value = retained()
        for at in (instant(value['effective_from']) - timedelta(microseconds=1), instant(value['effective_until'])):
            q = quote(state(at=at.isoformat()))
            self.assertEqual(q['comparison_input_status']['identity']['public_event']['status'], 'expired')
            self.assertEqual(q['times']['source_at'], '2026-10-09T03:55:16.261974+00:00')

    def test_metadata_revision_changes_dependency_not_quote(self):
        before = state();value = retained();value['scope']['description'] += ' Dated metadata review.';sealed(value)
        after = state(value)
        old = quote(before);new = quote(after)
        self.assertEqual(new['original'], old['original']);self.assertEqual(new['times'], old['times'])
        self.assertEqual(new['revision'], old['revision']);self.assertEqual(new['id'], old['id'])
        self.assertNotEqual(new['comparison_input_refs']['refs']['identity'], old['comparison_input_refs']['refs']['identity'])
        self.assertEqual(new['comparison_input_refs']['refs']['buffer'], old['comparison_input_refs']['refs']['buffer'])

    def test_reprojection_stable_and_healthy_sources_unchanged(self):
        from tests.comparison_retained_review import retained_inputs
        raw = retained_inputs(historical=True)
        others = {q['id']: deepcopy(q) for e in raw['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o) if q['venue'] != 'polymarket_us'}
        raw['comparison_profiles'] = attach(raw)
        current = {q['id']: q for e in raw['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o) if q['venue'] != 'polymarket_us'}
        self.assertEqual(current, others)
        first = state();old = deepcopy(first)
        first['comparison_profiles'] = attach(first, selected_applicability=registry({'version': 'comparison-selected-applicability-1', 'records': []}))
        self.assertEqual(quote(first)['comparison_input_refs'], quote(old)['comparison_input_refs'])

    def test_expiry_tick_invalidates_once_and_preserves_held_inputs(self):
        raw = state();ticks = [0]
        store = CurrentStore(InjectedTestProvider(raw), monotonic=lambda: ticks[0])
        old = store.snapshot();revision = old['state_revision'];q = quote(old)
        ticks[0] = 899;store.refresh_age()
        self.assertEqual(quote(store.snapshot())['comparison_input_status']['identity']['public_event']['status'], 'available_and_bound')
        ticks[0] = 900;store.refresh_age()
        new = store.snapshot()
        self.assertGreater(new['state_revision'], revision)
        self.assertEqual(quote(new)['comparison_input_status']['identity']['public_event']['status'], 'expired')
        self.assertEqual(q['comparison_input_status']['identity']['public_event']['status'], 'available_and_bound')
        self.assertEqual(quote(new)['times'], q['times']);self.assertEqual(quote(new)['revision'], q['revision'])
        next_revision = new['state_revision'];ticks[0] = 901;store.refresh_age()
        self.assertEqual(store.snapshot()['state_revision'], next_revision)

    def test_corrupt_binding_and_unproved_cross_source_reject(self):
        value = retained();value['occurrence']['game_id'] = '19519'
        with self.assertRaises(ValueError): validate(value)
        value = retained();value['occurrence']['cross_source_qualified'] = True;sealed(value)
        with self.assertRaisesRegex(ValueError, 'unproved'): validate(value)


class PublicEventRoutes(AioHTTPTestCase):
    async def get_application(self):
        self.raw = state()
        return create_app(owner=owner(), sessions={}, current_provider=InjectedTestProvider(self.raw))

    async def test_source_profile_same_revision_api_details(self):
        store = self.app[CURRENT_KEY];store.monotonic = lambda: 0;store._age_origin = 0
        current = await (await self.client.get('/api/current')).json()
        comparison = await (await self.client.get('/api/comparison')).json()
        self.assertEqual(current['state_revision'], comparison['state_revision'])
        self.assertEqual(current['runtime_id'], comparison['runtime_id'])
        q = quote(current)
        row = next(r for r in comparison['rows'] if r['quote']['source']['native_outcome_id'] == '2165646')
        self.assertEqual(row['quote']['comparison_input_status']['identity']['public_event'], q['comparison_input_status']['identity']['public_event'])
        self.assertEqual(q['original']['value'], '0.2350')
        self.assertEqual(q['times']['source_at'], '2026-10-09T03:55:16.261974+00:00')
        self.assertEqual((await self.client.get('/ev')).status, 200)
        self.assertFalse(row['net_ev']['eligible'])
        self.assertEqual(snapshot_inputs(current)['comparison_profiles'], self.raw['comparison_profiles'])
