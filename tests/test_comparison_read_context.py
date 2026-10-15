"""One coherent typed current frame; selected guards and financial inputs stay exact."""
import base64
from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.collection.current_aggregate_admission import admit
from app.comparison.combined_inputs import build
from app.storage.comparison_board import ReadContext, discover, source_guard
from tests.test_current_board_reads import frame
from tests.test_ev09_n01 import retained, envelopes, AT, SELECTED


class ComparisonReadContext(TestCase):
    def setUp(self):
        self.frame = frame()
        self.store = SimpleNamespace(db=None)
        self.capture = patch('app.storage.current_rows.CurrentRowStore.capture',
                             side_effect=lambda **kwargs: deepcopy(self.frame)).start()
        self.addCleanup(patch.stopall)

    def context(self):
        return ReadContext(self.store, at=AT)

    def selected(self, context):
        return discover(self.store, context=context, selected=SELECTED)[0]

    def members(self, context):
        return next(b['members'] for b in context.catalog_bundles() if list(SELECTED) in b['members'])

    def test_slim_catalog_keeps_exact_occurrences_and_native_alternatives(self):
        context = self.context()
        with patch('app.comparison.source_inputs.produce', side_effect=AssertionError('catalog must not price')):
            actual = context.catalog()
        expected = self.selected(context)['state_inputs']['events'][0]
        game = next(g for g in actual['games'] if list(SELECTED) in g['members'])
        for key in ('title', 'start_at', 'participants'):
            self.assertEqual(game[key], expected[key])
        alternatives=sum(len(qs) for group in expected['groups'] for outcome in group['outcomes'] for qs in outcome.get('alternatives',{}).values())
        self.assertEqual(game['native_alternatives'], alternatives)
        self.assertEqual(self.capture.call_count, 1)
        self.capture.assert_called_once_with(include_depth=False)

    def test_selected_hydration_keeps_original_financial_inputs(self):
        context = self.context()
        context.catalog()
        selected = self.selected(context)
        again = discover(self.store, context=context, game=selected['game_key'])[0]
        self.assertEqual(selected, again)
        original = retained()[0]
        # Representation revisions change when archive locators are retired;
        # benchmark prices, native selection meaning and clocks remain exact.
        def meaning(value):
            if isinstance(value,dict):return {k:meaning(v) for k,v in value.items() if k!='revision'}
            if isinstance(value,list):return [meaning(v) for v in value]
            return value
        self.assertEqual(meaning(selected['benchmark']), meaning(original['benchmark']))
        originals = {tuple(sorted(r['quote']['source'].items())): r['quote']['original'] for r in original['records']}
        for record in selected['records']:
            self.assertEqual(record['quote']['original'], originals[tuple(sorted(record['quote']['source'].items()))])
        self.assertEqual(self.capture.call_count, 1)

    def test_uncached_selected_hydration_does_not_reread_sql(self):
        context = self.context()
        first = discover(self.store, context=context, selected=SELECTED, cache=False)
        second = discover(self.store, context=context, selected=SELECTED, cache=False)
        self.assertEqual(first, second)
        self.assertEqual(self.capture.call_count, 1)
        self.assertFalse(hasattr(context, '_bundles'))

    def test_one_context_resolves_once_and_guard_never_rediscovers(self):
        from app.comparison.occurrence_matching import OccurrenceResolver
        original = OccurrenceResolver.resolve
        calls = []
        def resolve(instance, records, **kwargs):
            calls.append(len(records))
            return original(instance, records, **kwargs)
        with patch.object(OccurrenceResolver, 'resolve', resolve):
            context = self.context()
            bundles = discover(self.store, context=context)
            for bundle in bundles:
                with patch('app.storage.comparison_board.discover', side_effect=AssertionError('no rediscovery')):
                    guard = source_guard(self.store, bundle['members'], context=context)
                    self.assertEqual(guard, source_guard(self.store, bundle['members'], context=context))
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.capture.call_count, 1)

    def test_removed_member_revokes_new_context_keeps_captured_frame(self):
        before = self.context()
        members = self.members(before)
        guard = before.guard(members)
        self.frame['records'] = [r for r in self.frame['records'] if r['quote']['venue'] != 'kalshi']
        self.assertNotEqual(self.context().guard(members), guard)
        self.assertEqual(before.guard(members), guard)

    def test_missing_reference_never_returns_from_original_envelopes(self):
        self.frame['records'] = [r for r in self.frame['records'] if r['quote']['venue'] != 'pinnacle']
        with patch('app.storage.current_games.GameStore.combined_read_capture', side_effect=AssertionError('no archive')):
            bundle = self.selected(self.context())
        self.assertIsNone(bundle['benchmark'])
        self.assertEqual(bundle['benchmark_reason'], 'selected_benchmark_two_originals_absent')
        self.assertNotIn('pinnacle', {r['quote']['venue'] for r in bundle['records']})

    def test_current_price_change_revokes_selected_guard(self):
        before = self.context()
        members = self.members(before)
        guard = before.guard(members)
        row = next(r for r in self.frame['records'] if r['quote']['venue'] == 'novig')
        row['quote']['original']['value'] = '9.99'
        self.assertNotEqual(self.context().guard(members), guard)
        self.assertEqual(before.guard(members), guard)

    def test_epoch_replacement_revokes_captured_identity(self):
        before = self.context()
        members = self.members(before)
        self.frame['epoch'] = 'authored-successor-epoch'
        self.assertNotEqual(before.guard(members), self.context().guard(members))

    def test_source_unavailable_changes_read_revision(self):
        before = self.context()
        self.frame['source_status'] = {'novig': {'state': 'unavailable'}}
        after = self.context()
        self.assertNotEqual(before.read_revision, after.read_revision)
        self.assertTrue(any(r['quote']['state'] == 'unavailable' for group in after.prepared['groups']
                            for r in group if r['quote']['venue'] == 'novig'))

    def test_legacy_bad_receipt_hash_is_still_refused(self):
        originals = deepcopy(envelopes())
        original = next(e for e in originals if e['record']['kind'] == 'aggregate_batch')
        original['record']['value']['body_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'envelope_hash_conflict'):
            build(originals, at=AT)

    def test_event_filter_preserves_full_original_receipt_and_clocks(self):
        original = next(e for e in envelopes() if e['record']['kind'] == 'aggregate_batch')['record']['value']
        body = base64.b64decode(original['body_b64'])
        rows = admit(body, 'NFL', original['received_at'], venue='novig')
        expected = [r for r in rows if r['quote']['source']['native_event_id'] == SELECTED[1]]
        self.assertEqual(admit(body, 'NFL', original['received_at'], venue='novig', event_ids=[SELECTED[1]]), expected)

    def test_caller_mutation_cannot_change_a_later_read(self):
        first = self.context()
        bundle = self.selected(first)
        expected = deepcopy(bundle)
        bundle['records'][0]['quote']['original']['value'] = 'changed by caller'
        self.assertEqual(self.selected(self.context()), expected)

    def test_nonwinner_changes_do_not_revoke_winner_guard(self):
        before = self.context()
        members = self.members(before)
        guard = before.guard(members)
        row = deepcopy(self.frame['records'][0])
        row['market_identity']['family'] = 'spread'
        self.frame['records'].append(row)
        row['quote']['original']['value'] = '9.99'
        self.assertEqual(self.context().guard(members), guard)

    def test_native_clock_and_predicate_changes_revoke_selected_guard(self):
        before = self.context()
        members = self.members(before)
        guard = before.guard(members)
        original = deepcopy(self.frame)
        for field in ('clock', 'predicate'):
            self.frame = deepcopy(original)
            row = next(r for r in self.frame['records'] if r['quote']['venue'] == 'kalshi')
            if field == 'clock':
                row['quote']['times']['source_at'] = '2026-10-14T01:15:10Z'
            else:
                row['selection']['predicate'] = 'lose'
            self.assertNotEqual(self.context().guard(members), guard)
