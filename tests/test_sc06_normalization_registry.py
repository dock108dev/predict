"""Context-scoped registry reuse preserves authored/retained normalization meaning.

No database, provider, financial evaluation, model renewal or owner state writes.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.comparison.combined_inputs import build, prepare
from app.dashboard.current_normalized import NormalizationRegistries, catalog_from_normalized
from app.dashboard.current_state import unavailable
from app.storage.comparison_board import ReadContext
from tests.test_ev09_n01 import AT, envelopes


class RegistrySnapshots(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = prepare(envelopes(), at=AT)

    def context(self):
        records = [deepcopy(row) for rows in self.prepared['groups'] for row in rows]
        return ReadContext(SimpleNamespace(db=None), at=AT,
            frame=dict(epoch='authored-context', revision='same-source-facts', records=records,
                source_status={}, dependency_revisions={}, native_dependency_revisions={}))

    def test_snapshot_is_immutable_and_each_consumer_receives_detached_dictionaries(self):
        snapshot = NormalizationRegistries.load()
        before = snapshot.detached()
        rules, selected = snapshot.detached()
        rules['rules'].clear(); selected['records'].clear()
        self.assertEqual(snapshot.detached(), before)
        self.assertIsInstance(snapshot.source_rules, bytes)
        self.assertIsInstance(snapshot.selected_applicability, bytes)
        with self.assertRaises(FrozenInstanceError):
            snapshot.binding = 'caller mutation'

    def test_catalog_and_combined_inputs_equal_existing_default_owner_output(self):
        snapshot = NormalizationRegistries.load()
        for rows in self.prepared['groups']:
            executions = [deepcopy(row) for row in rows if row['quote']['venue'] != 'pinnacle']
            references = [deepcopy(row) for row in rows if row['quote']['venue'] == 'pinnacle']
            if not executions:
                continue
            raw = unavailable(); raw.update(clock_at=AT, projected_at=AT, state='available', runtime_id='authored-normalization')
            self.assertEqual(
                catalog_from_normalized(raw, executions, reference_records=references),
                catalog_from_normalized(raw, executions, reference_records=references, registries=snapshot))
            self.assertEqual(
                catalog_from_normalized(raw, executions, include_profiles=False),
                catalog_from_normalized(raw, executions, include_profiles=False, registries=snapshot))
        self.assertEqual(build([], at=AT, prepared=self.prepared),
            build([], at=AT, prepared=self.prepared, registries=snapshot))

    def test_one_selected_validation_per_context_across_catalog_and_multiple_bundles(self):
        from app.comparison.public_retail import registry
        context = self.context()
        with patch('app.comparison.public_retail.registry', wraps=registry) as validation:
            context.catalog_bundles()
            first = context.bundles()
            second = context.bundles()
            self.assertEqual(validation.call_count, 1)
        self.assertEqual(first, second)
        if first:
            first[0]['state_inputs']['comparison_profiles'].clear()
            self.assertEqual(context.bundles(), second)

    def test_new_context_reloads_and_validates_but_existing_snapshot_stays_exact(self):
        from app.comparison.public_retail import registry
        first = self.context()
        original = first.normalization_registries()
        original_rules = original.detached()[0]
        read_text = Path.read_text
        def changed(path, *args, **kwargs):
            value = read_text(path, *args, **kwargs)
            if path.name == 'comparison-source-rules-v1.json':
                parsed = json.loads(value); parsed['authored_context_marker'] = 'new-context-only'
                return json.dumps(parsed)
            return value
        with patch.object(Path, 'read_text', changed), patch('app.comparison.public_retail.registry', wraps=registry) as validation:
            self.assertIs(first.normalization_registries(), original)
            second = self.context().normalization_registries()
            self.assertEqual(validation.call_count, 1)
        self.assertNotEqual(second.binding, original.binding)
        self.assertEqual(original.detached()[0], original_rules)

    def test_selected_registry_validation_failure_is_never_cached_as_a_snapshot(self):
        context = self.context()
        with patch('app.comparison.public_retail.registry', side_effect=ValueError('authored invalid selected evidence')):
            with self.assertRaisesRegex(ValueError, 'invalid selected evidence'):
                context.normalization_registries()
        self.assertIsNone(context._normalization_registries)
        self.assertIsInstance(context.normalization_registries(), NormalizationRegistries)

    def test_snapshot_cannot_be_mixed_with_independent_override_inputs(self):
        raw = unavailable(); raw.update(clock_at=AT, projected_at=AT)
        snapshot = NormalizationRegistries.load()
        with self.assertRaisesRegex(ValueError, 'registry snapshot'):
            catalog_from_normalized(raw, [], registries=snapshot, source_rules={})
        with self.assertRaisesRegex(ValueError, 'registry snapshot'):
            catalog_from_normalized(raw, [], registries=snapshot, selected_applicability={})

    def test_context_record_shells_leave_raw_frame_and_nested_unknowns_detached(self):
        records = [deepcopy(row) for rows in self.prepared['groups'] for row in rows]
        first = records[0]
        first['quote']['future_facts'] = {'nested': ['雪', None, {'amount': '0.123456789'}]}
        first['event']['future_facts'] = {'nested': ['source event']}
        first['comparison_source_metadata'] = dict(combined_envelope_id='old-envelope',
            unknown={'nested': ['source metadata']}, combined_native_binding=dict(
                catalog_envelope_id='old-catalog', book_envelope_id='old-book',
                unknown={'nested': ['source native metadata']}))
        first['_instrument'] = {'old': True}; first['_fingerprint'] = 'old-locator'
        for kind in ('unsupported_market', 'unsupported_league', 'already_started'):
            excluded = deepcopy(first)
            if kind == 'unsupported_market':excluded['market_identity']['family'] = 'player_prop'
            elif kind == 'unsupported_league':excluded['event']['competition'] = 'unsupported_league'
            else:excluded['event']['scheduled_start'] = AT
            records.append(excluded)
        frame = dict(epoch='authored-shells', revision='unchanged-source-facts', records=records,
            source_status={first['quote']['venue']: dict(state='failed')},
            dependency_revisions={}, native_dependency_revisions={})
        before = deepcopy(frame)
        context = ReadContext(SimpleNamespace(db=None), at=AT, frame=frame)
        self.assertEqual(frame, before, 'temporary metadata/status edits cannot reach raw SQL facts')
        resolved = [row for rows in context.prepared['groups'] for row in rows]
        self.assertEqual(len(resolved), len(records) - 3)
        actual = next(row for row in resolved if row['quote']['source'] == first['quote']['source'])
        self.assertEqual(actual['quote']['state'], 'failed')
        self.assertEqual(actual['quote']['future_facts'], first['quote']['future_facts'])
        self.assertEqual(actual['event']['future_facts'], first['event']['future_facts'])
        self.assertNotIn('_instrument', actual); self.assertNotIn('_fingerprint', actual)
        metadata = actual['comparison_source_metadata']
        self.assertNotIn('combined_envelope_id', metadata)
        self.assertNotIn('catalog_envelope_id', metadata['combined_native_binding'])
        self.assertNotIn('book_envelope_id', metadata['combined_native_binding'])
        self.assertEqual(metadata['combined_native_binding']['unknown'],
            first['comparison_source_metadata']['combined_native_binding']['unknown'])
        actual['quote']['future_facts']['nested'].append('resolved mutation')
        actual['event']['future_facts']['nested'].append('resolved mutation')
        metadata['unknown']['nested'].append('resolved mutation')
        metadata['combined_native_binding']['unknown']['nested'].append('resolved mutation')
        self.assertEqual(frame, before)
        resolved_before = deepcopy(actual)
        first['quote']['future_facts']['nested'].append('raw mutation')
        first['event']['future_facts']['nested'].append('raw mutation')
        first['comparison_source_metadata']['unknown']['nested'].append('raw mutation')
        self.assertEqual(actual, resolved_before, 'resolver final output cannot borrow nested raw facts')

    def test_context_aggregate_metadata_edits_preserve_raw_nested_containers(self):
        records = [deepcopy(row) for rows in self.prepared['groups'] for row in rows
                   if row['quote']['source']['provider'] == 'the_odds_api']
        self.assertTrue(records)
        for row in records:
            row['comparison_scope'] = dict(overtime='unknown')
            row['comparison_source_metadata'] = dict(phase='unknown', unknown={'nested': ['original']})
        before = deepcopy(records)
        context = ReadContext(SimpleNamespace(db=None), at=AT,
            frame=dict(epoch='aggregate-shells', revision='same-source-facts', records=records,
                source_status={}, dependency_revisions={}, native_dependency_revisions={}))
        self.assertEqual(records, before)
        for rows in context.prepared['groups']:
            for row in rows:
                self.assertEqual(row['comparison_scope'], dict(overtime='included'))
                self.assertEqual(row['comparison_source_metadata']['phase'], 'pregame')
                row['comparison_source_metadata']['unknown']['nested'].append('consumer')
        self.assertEqual(records, before)

    def test_current_bundles_equal_ordinary_build_with_the_existing_current_guard(self):
        from app.comparison import combined_inputs
        context = self.context()
        expected = build([], at=AT, prepared=context.prepared, registries=context.normalization_registries())
        for value in expected:
            value['input_version'] = context.guard(value['members'])
            value['epoch'] = context.epoch
            value['representation'] = 'current typed event, exact native contracts, offers, depth and shared definitions; original source clocks retained'
            value['envelope_ids'] = []; value['envelopes'] = []
        original_hash = combined_inputs.hashed
        def no_overwritten_bundle_hash(value):
            if isinstance(value, dict) and 'state_inputs' in value and 'records' in value:
                raise AssertionError('current read computed the obsolete whole-bundle hash')
            return original_hash(value)
        with patch.object(combined_inputs, 'hashed', side_effect=no_overwritten_bundle_hash):
            actual = context.bundles()
        self.assertEqual(actual, sorted(expected, key=lambda value: value['game_key']))

    def test_public_build_keeps_exact_self_validating_identity_and_default_record_copies(self):
        from app.comparison.combined_inputs import validate
        before = deepcopy(self.prepared)
        values = build([], at=AT, prepared=self.prepared)
        self.assertTrue(values)
        for value in values:
            self.assertEqual(validate(value), value)
            self.assertTrue(value['records'])
        values[0]['records'][0]['quote']['times']['received_at'] = '2030-01-01T00:00:00Z'
        values[0]['records'][0]['event']['participants'].clear()
        values[0]['state_inputs']['comparison_profiles'].clear()
        self.assertEqual(self.prepared, before)
        again = build([], at=AT, prepared=self.prepared)
        self.assertEqual(validate(again[0]), again[0])

    def test_private_readiness_bundle_omits_only_unused_records_and_preserves_state_and_guard(self):
        context = self.context()
        before = deepcopy(context.prepared)
        checked = 0
        for rows in context.prepared['groups']:
            if not any(row['quote']['venue'] != 'pinnacle' for row in rows):continue
            ordinary = context.bundles(occurrence_rows=rows)
            compact = context.bundles(occurrence_rows=rows, _readiness_only=True)
            expected = deepcopy(ordinary)
            for value in expected:value['records'] = []
            self.assertEqual(compact, expected)
            self.assertEqual(compact[0]['input_version'], context.guard(compact[0]['members']))
            compact[0]['state_inputs']['comparison_profiles'].clear()
            self.assertEqual(context.prepared, before)
            self.assertEqual(context.bundles(occurrence_rows=rows), ordinary)
            checked += 1
        self.assertGreater(checked, 0)

    def test_private_readiness_requires_an_exact_current_occurrence_and_guard(self):
        context = self.context()
        with self.assertRaisesRegex(ValueError, '^board_readiness_occurrence_required$'):
            context.bundles(_readiness_only=True)
        with self.assertRaisesRegex(ValueError, '^combined_readiness_guard_required$'):
            build([], at=AT, prepared=self.prepared, _readiness_only=True)
        with self.assertRaisesRegex(ValueError, '^combined_current_guard_required$'):
            build([], at=AT, prepared=self.prepared, _current_guard='not a guard')
