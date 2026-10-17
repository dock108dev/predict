"""Independent readiness-preparation reuse checks; no providers or owner SQL.

Class tests exercise a bounded detached-value cache. Capture tests below keep
the production readiness adapter and financial-input detachment path, replacing
only the database snapshot and resolved occurrence context with authored facts.
"""
from copy import copy, deepcopy
from contextlib import ExitStack, nullcontext
from datetime import timedelta
import json
import os
import operator
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from app.comparison.current_dependencies import digest, encoded, instant
from app.storage.scanner_preparation import PreparationCache, is_immutable_fact


AT = '2026-10-14T01:15:09.650084+00:00'


def clock(seconds=0):
    return (instant(AT) + timedelta(seconds=seconds)).isoformat()


class DetachedPreparationCache(TestCase):
    def put(self, cache, key='a', value=None, *, start=0, end=10):
        value = {'nested': {'facts': ['original']}} if value is None else value
        cache.put(key, value, at=clock(start), until=clock(end))
        return value

    def test_both_insertions_and_returns_are_detached(self):
        cache = PreparationCache()
        original = self.put(cache)
        original['nested']['facts'].append('caller mutation')
        first = cache.get('a', at=clock(1))
        self.assertEqual(first, {'nested': {'facts': ['original']}})
        first['nested']['facts'].append('returned mutation')
        self.assertEqual(cache.get('a', at=clock(2)), {'nested': {'facts': ['original']}})
        self.assertGreaterEqual(cache.stats()['hits'], 2)

    def test_validity_is_half_open_and_reversal_cannot_reuse_future_result(self):
        cache = PreparationCache()
        self.put(cache, start=5, end=10)
        self.assertIsNone(cache.get('a', at=clock(4)))
        # A denied backwards read may evict conservatively; refill to isolate
        # the inclusive-start / exclusive-expiry assertions.
        self.put(cache, start=5, end=10)
        self.assertIsNotNone(cache.get('a', at=clock(5)))
        self.assertIsNotNone(cache.get('a', at=clock(9)))
        self.assertIsNone(cache.get('a', at=clock(10)))
        self.assertIsNone(cache.get('a', at=clock(11)))
        self.assertGreaterEqual(cache.stats()['misses'], 3)

    def test_entry_limit_and_replacement_do_not_accumulate_history(self):
        cache = PreparationCache(max_entries=2, max_bytes=65536)
        self.put(cache, 'a'); self.put(cache, 'b'); self.put(cache, 'c')
        self.assertIsNone(cache.get('a', at=clock(1)))
        self.assertIsNotNone(cache.get('b', at=clock(1)))
        self.assertIsNotNone(cache.get('c', at=clock(1)))
        self.assertLessEqual(cache.stats()['entries'], 2)
        self.assertGreaterEqual(cache.stats()['evictions'], 1)
        before = cache.stats()['bytes']
        for _ in range(100):
            self.put(cache, 'c')
        self.assertEqual(cache.stats()['bytes'], before)
        self.assertEqual(cache.stats()['entries'], 2)

    def test_bytes_include_identity_and_temporal_metadata_and_oversize_is_refused(self):
        cache = PreparationCache(max_entries=10, max_bytes=1024)
        key = digest('authored-key')
        value = self.put(cache, key, {'facts': 'x' * 300})
        stats = cache.stats()
        self.assertGreaterEqual(stats['bytes'], len(encoded(value)) + len(key))
        for i in range(10):
            self.put(cache, digest(i), {'facts': str(i) * 300})
            self.assertLessEqual(cache.stats()['bytes'], 1024)
            self.assertLessEqual(cache.stats()['entries'], 10)
        try:
            self.put(cache, 'oversized', {'facts': 'x' * 4096})
        except ValueError:
            pass  # An explicit bounded refusal is also valid.
        self.assertIsNone(cache.get('oversized', at=clock(1)))
        self.assertLessEqual(cache.stats()['bytes'], 1024)

    def test_prune_and_clear_remove_retained_values(self):
        cache = PreparationCache()
        self.put(cache, 'a'); self.put(cache, 'b')
        cache.prune({'b'})
        self.assertIsNone(cache.get('a', at=clock(1)))
        self.assertIsNotNone(cache.get('b', at=clock(1)))
        self.assertEqual(cache.stats()['entries'], 1)
        cache.clear()
        self.assertEqual(cache.stats()['entries'], 0)
        self.assertEqual(cache.stats()['bytes'], 0)
        self.assertIsNone(cache.get('b', at=clock(1)))

    def test_invalid_lifetime_never_replaces_a_result_with_an_authorized_entry(self):
        cache = PreparationCache()
        self.assertFalse(cache.put('empty', {'ready': True}, at=clock(5), until=clock(5)))
        self.assertIsNone(cache.get('empty', at=clock(5)))
        self.assertFalse(cache.put('backwards', {'ready': True}, at=clock(5), until=clock(4)))
        self.assertIsNone(cache.get('backwards', at=clock(4)))


class ImmutablePreparationFacts(TestCase):
    def shared(self, value=None):
        value = {'nested': [{'unknown': ['original', None, False, 7, '雪']}]} if value is None else value
        cache = PreparationCache()
        self.assertTrue(cache.put('facts', value, at=clock(), until=clock(10)))
        return cache, cache.get_shared('facts', at=clock(1))

    def ordinary(self, value):
        if isinstance(value, dict):
            self.assertIs(type(value), dict)
            for child in value.values(): self.ordinary(child)
        elif isinstance(value, list):
            self.assertIs(type(value), list)
            for child in value: self.ordinary(child)

    def test_shared_identity_blocks_every_normal_dictionary_mutator(self):
        cache, shared = self.shared()
        self.assertIs(shared, cache.get_shared('facts', at=clock(2)))
        self.assertTrue(is_immutable_fact(shared)); self.assertTrue(is_immutable_fact(shared['nested'][0]))
        operations = {
            'setitem': lambda: operator.setitem(shared, 'new', 'bad'),
            'delitem': lambda: operator.delitem(shared, 'nested'),
            'update': lambda: shared.update(new='bad'),
            'clear': shared.clear,
            'pop': lambda: shared.pop('nested'),
            'popitem': shared.popitem,
            'setdefault': lambda: shared.setdefault('new', 'bad'),
            'existing_setdefault': lambda: shared.setdefault('nested', 'bad'),
            'ior': lambda: operator.ior(shared, {'new': 'bad'}),
            'reinitialize': lambda: shared.__init__({'bad': []}),
            'nested': lambda: shared['nested'][0].update(unknown='bad'),
        }
        before = encoded(shared)
        for name, operation in operations.items():
            with self.subTest(operation=name):
                with self.assertRaisesRegex(TypeError, 'immutable_readiness_fact'): operation()
                self.assertEqual(encoded(shared), before)

    def test_shared_identity_blocks_every_normal_list_and_slice_mutator(self):
        _, root = self.shared(); shared = root['nested'][0]['unknown']
        self.assertTrue(is_immutable_fact(shared))
        operations = {
            'setitem': lambda: operator.setitem(shared, 0, 'bad'),
            'setslice': lambda: operator.setitem(shared, slice(None), ['bad']),
            'delitem': lambda: operator.delitem(shared, 0),
            'delslice': lambda: operator.delitem(shared, slice(None)),
            'append': lambda: shared.append('bad'),
            'extend': lambda: shared.extend(['bad']),
            'insert': lambda: shared.insert(0, 'bad'),
            'pop': shared.pop,
            'remove': lambda: shared.remove('original'),
            'clear': shared.clear,
            'reverse': shared.reverse,
            'sort': shared.sort,
            'iadd': lambda: operator.iadd(shared, ['bad']),
            'imul': lambda: operator.imul(shared, 2),
            'reinitialize': lambda: shared.__init__(['bad']),
        }
        before = encoded(shared)
        for name, operation in operations.items():
            with self.subTest(operation=name):
                with self.assertRaisesRegex(TypeError, 'immutable_readiness_fact'): operation()
                self.assertEqual(encoded(shared), before)

    def test_put_get_deepcopy_and_copy_never_share_mutable_caller_state(self):
        original = {'unknown': [{'nested': ['original']}], 'empty': {}}
        cache, shared = self.shared(original)
        original['unknown'][0]['nested'].append('caller mutation')
        original['empty']['caller'] = True
        for detached in (cache.get('facts', at=clock(1)), deepcopy(shared), copy(shared), shared.copy()):
            self.ordinary(detached)
            self.assertEqual(detached, {'unknown': [{'nested': ['original']}], 'empty': {}})
            detached['unknown'][0]['nested'].append('returned mutation')
            detached['empty']['returned'] = True
            self.assertEqual(shared['unknown'][0]['nested'], ['original'])
            self.assertEqual(shared['empty'], {})
        detached_list = shared['unknown'].copy(); self.ordinary(detached_list)
        detached_list[0]['nested'].append('list-copy mutation')
        self.assertEqual(shared['unknown'][0]['nested'], ['original'])
        self.assertFalse(is_immutable_fact({})); self.assertFalse(is_immutable_fact([]))

    def test_exact_encoded_charge_retains_one_tree_and_refusal_releases_replaced_entry(self):
        value = {'quoted"\\\n雪': [{'unknown': '€'}], 'tuple': ('array',)}
        cache = PreparationCache(max_entries=2, max_bytes=1024)
        self.assertTrue(cache.put('facts', value, at=clock(), until=clock(10)))
        shared = cache.get_shared('facts', at=clock(1))
        self.assertEqual(cache.stats()['bytes'], len(encoded(dict(at=clock(), until=clock(10), value=value))) + len(b'facts'))
        self.assertIs(cache._entries['facts'][2], shared)
        self.assertEqual(cache.get('facts', at=clock(1))['tuple'], ['array'])
        self.assertTrue(all(not isinstance(part, bytes) for part in cache._entries['facts']))
        self.assertFalse(cache.put('facts', {'oversized': 'x' * 2048}, at=clock(), until=clock(10)))
        self.assertEqual(cache.stats()['entries'], 0); self.assertEqual(cache.stats()['bytes'], 0)
        self.assertIsNone(cache.get_shared('facts', at=clock(1)))

    def test_shared_reads_keep_lru_prune_clear_and_half_open_temporal_bounds(self):
        cache = PreparationCache(max_entries=2)
        for key in ('a', 'b'): cache.put(key, {'key': key}, at=clock(), until=clock(10))
        original = cache.get_shared('a', at=clock())
        cache.put('c', {'key': 'c'}, at=clock(), until=clock(10))
        self.assertIsNone(cache.get_shared('b', at=clock(1)))
        self.assertIs(cache.get_shared('a', at=clock(9)), original)
        self.assertIsNone(cache.get_shared('a', at=clock(10)))
        cache.prune({'c'}); self.assertEqual(cache.stats()['entries'], 1)
        cache.clear(); self.assertEqual(cache.stats()['bytes'], 0)
        self.assertIsNone(cache.get_shared('c', at=clock(1)))
        self.assertEqual(original, {'key': 'a'})  # A caller-held frozen fact stays safe after eviction.

    def test_nonstring_public_json_keys_keep_prior_normalization(self):
        cache, shared = self.shared({7: {'tuple': (None, False, 'same')}})
        self.assertEqual(shared, {'7': {'tuple': [None, False, 'same']}})
        self.ordinary(cache.get('facts', at=clock(1)))


class RegistryInvalidation(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='predict-sc06-registry-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.fixtures = self.root / 'app/fixtures'; self.fixtures.mkdir(parents=True)
        self.path = self.fixtures / 'selected.json'
        self.patch = patch('app.storage.scanner_preparation.__file__', str(self.root / 'app/storage/scanner_preparation.py'))
        self.patch.start(); self.addCleanup(self.patch.stop)

    def write(self, value):
        self.path.write_text(json.dumps(value))

    def test_inactive_nested_future_applicability_is_an_exact_cache_boundary(self):
        self.write(dict(records=[dict(not_attached_yet=True,
            nested=dict(effective_from=clock(5), effective_until=clock(10)))]))
        cache = PreparationCache()
        version, boundary = cache.registry(at=clock())
        self.assertEqual(boundary, clock(5))
        cache.put('facts', {'ready': True}, at=clock(), until=boundary)
        self.assertIsNotNone(cache.get('facts', at=clock(4)))
        self.assertIsNone(cache.get('facts', at=clock(5)))
        same, boundary = cache.registry(at=clock(5))
        self.assertEqual(same, version)
        self.assertEqual(boundary, clock(10))
        self.assertIsNone(cache.registry(at=clock(10))[1])

    def test_content_change_with_same_length_and_mtime_changes_registry_identity(self):
        self.write(dict(model='a', model_effective_from=clock(5), expires_at=clock(10)))
        cache = PreparationCache()
        first = cache.registry(at=clock())[0]
        stat = self.path.stat()
        self.write(dict(model='b', model_effective_from=clock(5), expires_at=clock(10)))
        os.utime(self.path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(self.path.stat().st_size, stat.st_size)
        self.assertNotEqual(cache.registry(at=clock())[0], first)
        self.path.unlink()
        self.assertNotEqual(cache.registry(at=clock())[0], first)

    def test_reduced_registry_file_byte_and_boundary_caps_fail_explicitly(self):
        cache = PreparationCache()
        self.write(dict(effective_from=clock(1), effective_to=clock(2), expires_at=clock(3)))
        with patch('app.storage.scanner_preparation.MAX_REGISTRY_BYTES', 8):
            with self.assertRaisesRegex(ValueError, 'registry_byte_capacity'):
                cache.registry(at=clock())
        with patch('app.storage.scanner_preparation.MAX_REGISTRY_BOUNDARIES', 2):
            with self.assertRaisesRegex(ValueError, 'registry_boundary_capacity'):
                cache.registry(at=clock())
        (self.fixtures / 'second.json').write_text('{}')
        with patch('app.storage.scanner_preparation.MAX_REGISTRY_FILES', 1):
            with self.assertRaisesRegex(ValueError, 'registry_file_capacity'):
                cache.registry(at=clock())


class ImmutableFinancialCompatibility(TestCase):
    def test_real_financial_owners_and_unknown_dependency_fields_match_mutable_inputs(self):
        from app.comparison.scanner_finance import evaluate, dependencies
        from app.comparison.estimated_policy import LEGACY_POLICY
        from tests.test_ev06_pairs import pair
        from tests.test_sc01_readiness import pair_rows
        for flat in ('0', '5'):
            with self.subTest(flat_entry_fee=flat):
                legs, _, _ = pair(prices=('0.2', '0.2'), flat=flat)
                inputs, instruments = {}, {}
                for index, (leg, instrument) in enumerate(zip(legs, pair_rows())):
                    key = str(index); quote = deepcopy(leg.q); at = leg.at.isoformat()
                    quote['times'].update(source_at=at, received_at=at, projected_at=at)
                    quote['depth'] = [dict(price='0.2', quantity='50')]
                    quote['comparison_input_refs']['refs']['reference'] = None
                    quote['comparison_input_refs']['refs']['probability'] = None
                    quote['sc06_unknown_owner_fact'] = {'quoted"\\\n雪': ['exact', None, False]}
                    inputs[key] = dict(quote=quote, profiles=deepcopy(leg.profiles),
                        event=deepcopy(leg.event), group=deepcopy(leg.group))
                    instrument['checks']['ev']['state'] = 'unsupported'; instruments[key] = instrument
                pair_value = dict(legs=['0', '1'])
                cache = PreparationCache()
                self.assertTrue(cache.put('financial', dict(inputs=inputs, instruments=instruments), at=at, until=(instant(at) + timedelta(seconds=30)).isoformat()))
                frozen = cache.get_shared('financial', at=at); before = encoded(frozen)
                expected = evaluate(pair_value, instruments, inputs, at=at, policy=LEGACY_POLICY)
                actual = evaluate(pair_value, frozen['instruments'], frozen['inputs'], at=at, policy=LEGACY_POLICY)
                self.assertTrue(expected['evaluated']); self.assertTrue(expected['rows'])
                self.assertEqual(actual, expected); self.assertEqual(encoded(frozen), before)
                original = dependencies(pair_value, instruments, inputs, LEGACY_POLICY, 'exact-engine')
                self.assertEqual(original, dependencies(pair_value, frozen['instruments'], frozen['inputs'], LEGACY_POLICY, 'exact-engine'))
                changed = cache.get('financial', at=at)
                changed['inputs']['0']['quote']['sc06_unknown_owner_fact']['quoted"\\\n雪'][0] = 'changed'
                self.assertNotEqual(original, dependencies(pair_value, changed['instruments'], changed['inputs'], LEGACY_POLICY, 'exact-engine'))


class ReadinessCaptureReuse(TestCase):
    """Independent current adapter checks with no real database connection.

    The context fake is already occurrence-resolved. It deliberately leaves
    whole-frame revision fixed, so exact record/header/status invalidations
    cannot accidentally pass by relying on a broad changing SQL revision.
    """
    def setUp(self):
        from tests.test_sc01_readiness import authored
        from app.collection.current_policy import DEFAULT, GRANT
        from app.comparison.readiness_inputs import instrument
        from app.comparison.scanner_readiness import Selection
        from app.storage import scanner_readiness
        self.q, self.profiles, self.event, self.group, book = authored()
        self.book = dict(book, venue=self.q['venue'],
            native_event_id=self.q['source']['native_event_id'],
            native_market_id=self.q['source']['native_market_id'], revision='same-native-revision')
        self.engine = 'authored-engine'
        self.epoch = 'authored-epoch'
        self.record_present = True
        self.match_revision = 'initial-occurrence-membership'
        self.config = deepcopy(DEFAULT); self.authority = GRANT
        self.selection = Selection(venues=(self.q['venue'],))
        self.status = {self.q['venue']: dict(state='available', reason_code='authored_ready')}
        self.cache = PreparationCache()
        self.calls = 0
        owner = self

        class Rows:
            def __init__(self, values): self.values = values
            def fetchall(self): return deepcopy(self.values)

        class Database:
            def transaction(self): return nullcontext()
            def execute(self, statement, args=()):
                if 'current_native_book' in statement:
                    return Rows([owner.book])
                if 'SELECT c.id' in statement:
                    return Rows([dict(id='authored-contract', venue=owner.q['venue'],
                        league='NFL', family='moneyline', period='full_game', offered=True)] if owner.record_present else [])
                if not statement.startswith('SET TRANSACTION'):
                    raise AssertionError('Unexpected SQL in authored read fake: ' + statement)
                return Rows([])

        class Context:
            def __init__(self, store, *, at, frame):
                self.store = store; self.at = at; self.engine = owner.engine
                self.epoch = frame['epoch']; self.revision = frame['revision']
                self.prepared = dict(at=at, originals={}, groups=[frame['records']] if frame['records'] else [], excluded=[])
                self.source_status = deepcopy(owner.status)
            def guard(self, members):
                return digest([owner.records(), owner.match_revision])
            def catalog_bundles(self):
                if not owner.record_present: return []
                return [dict(game_key='combined:' + owner.event['id'],
                    members=[[owner.q['source']['provider'], owner.q['source']['native_event_id']]],
                    input_version=self.guard(None), records=owner.records())]
            def bundles(self, **kwargs):
                owner.calls += 1
                group = {k: deepcopy(v) for k, v in owner.group.items() if k != 'outcomes'}
                group['outcomes'] = [dict(quotes={owner.q['venue']: deepcopy(owner.q)})]
                event = {k: deepcopy(v) for k, v in owner.event.items() if k not in ('groups', 'funded_pairs')}
                event['groups'] = [group]
                return [dict(state_inputs=dict(events=[event], comparison_profiles=deepcopy(owner.profiles)))]

        self.db = Database()
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(scanner_readiness, 'ReadContext', Context))
        self.stack.enter_context(patch.object(scanner_readiness.CurrentRowStore, 'capture', side_effect=lambda **kwargs: self.frame()))
        self.instrument = self.stack.enter_context(patch.object(scanner_readiness, 'instrument', wraps=instrument))
        self.stack.enter_context(patch('app.comparison.scanner_finance.evaluate', side_effect=AssertionError('No financial work in readiness capture')))
        self.stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('No provider/network in readiness capture')))

    def records(self):
        if not self.record_present: return []
        return [dict(quote=deepcopy(self.q),
            event=dict(competition=self.event['league'], scheduled_start=self.event['start_at']),
            market_identity=dict(period=self.group['period'], event=dict(occurrence_id=self.event['id'])),
            occurrence_match_revision=self.match_revision)]

    def frame(self):
        return dict(records=self.records(), epoch=self.epoch, revision='unchanged-whole-frame-revision',
            source_status=deepcopy(self.status), dependency_revisions={}, native_dependency_revisions={})

    def read(self, *, seconds=0, cache=True, shared=False):
        from app.storage.scanner_readiness import capture
        return capture(self.db, config=self.config, at=clock(seconds),
            selection=self.selection, authority=self.authority, source_status=self.status,
            cache=self.cache if cache else None, _shared_facts=shared)

    def test_private_capture_reuses_exact_immutable_facts_and_public_capture_thaws(self):
        self.event['sc06_unknown'] = {'quoted"\\\n雪': ['preserved', {'future_owner': None}]}
        first = self.read(shared=True); second = self.read(shared=True)
        self.assertEqual(self.calls, 1)
        self.assertIs(first[0]['instruments'][0], second[0]['instruments'][0])
        key = next(iter(first[1]))
        self.assertIs(first[1][key], second[1][key])
        self.assertTrue(is_immutable_fact(first[0]['instruments'][0]))
        self.assertTrue(is_immutable_fact(first[1][key]['event']['sc06_unknown']))
        self.assertEqual(first[2]['input_bytes_bound'], len(encoded(first[1])) + 1)
        with self.assertRaisesRegex(TypeError, 'immutable_readiness_fact'):
            first[1][key]['quote']['depth'][0]['quantity'] = '777'
        public = self.read(); uncached = self.read(cache=False)
        self.assertEqual(public[:2], first[:2]); self.assertEqual(uncached[:2], first[:2])
        ordinary = ImmutablePreparationFacts(methodName='runTest')
        ordinary.ordinary(public[0]); ordinary.ordinary(public[1])
        public[0]['instruments'][0]['predicate']['predicate'] = 'caller mutation'
        public[1][key]['event']['sc06_unknown']['quoted"\\\n雪'].append('caller mutation')
        self.assertEqual(self.read(shared=True)[:2], first[:2])
        self.assertEqual(self.calls, 2)

    def test_private_capture_capacity_refusal_and_no_cache_fallback_remain_complete(self):
        self.cache = PreparationCache(max_bytes=1)
        first = self.read(shared=True); second = self.read(shared=True)
        self.assertEqual(self.calls, 2); self.assertEqual(self.cache.stats()['entries'], 0)
        self.assertEqual(first[:2], second[:2]); self.assertTrue(first[1])
        self.assertTrue(all(is_immutable_fact(value) for value in first[1].values()))
        no_cache = self.read(cache=False, shared=True)
        self.assertEqual(no_cache[:2], first[:2]); self.assertEqual(self.calls, 3)

    def test_private_cache_expiry_and_authority_changes_still_rebuild_original_facts(self):
        first = self.read(shared=True)
        self.read(seconds=1, shared=True); self.assertEqual(self.calls, 1)
        expired = self.read(seconds=30, shared=True)
        self.assertEqual(self.calls, 2)
        old, current = first[0]['instruments'][0], expired[0]['instruments'][0]
        self.assertIn('source_price_expired', current['checks']['execution']['reason_codes'])
        self.assertEqual(current['clocks'], old['clocks'])
        self.assertIsNot(current, old)
        self.authority = None
        denied = self.read(seconds=30, shared=True)[0]['instruments'][0]
        self.assertEqual(self.calls, 3)
        self.assertIn('scope_not_authorized', denied['checks']['execution']['reason_codes'])

    def test_private_opt_in_refuses_nonboolean_flags_before_reading_sql(self):
        from app.storage.scanner_readiness import capture
        for value in (None, 0, 1, 'true', [], {}):
            with self.subTest(flag=value):
                with self.assertRaisesRegex(ValueError, '^readiness_shared_facts_invalid$'):
                    capture(self.db, config=self.config, at=clock(), _shared_facts=value)
        self.assertEqual(self.calls, 0)

    def test_unchanged_reuses_detached_preparation_and_matches_uncached_output(self):
        first = self.read(); self.assertEqual(self.calls, 1)
        second = self.read(); self.assertEqual(self.calls, 1)
        self.assertEqual(first[:2], second[:2])
        self.assertGreaterEqual(self.cache.stats()['hits'], 1)
        second[0]['instruments'][0]['predicate']['predicate'] = 'caller_mutation'
        detached = self.read(); self.assertEqual(detached[:2], first[:2])
        uncached = self.read(cache=False)
        self.assertEqual(uncached[:2], first[:2])
        self.assertEqual(self.calls, 2)

    def test_capture_byte_bound_covers_all_fields_on_miss_hit_and_uncached_reads(self):
        self.event['sc06_unknown'] = {'quoted"\\\n雪': ['preserved', '€', None, False]}
        values = [self.read(), self.read(), self.read(cache=False)]
        self.assertEqual(self.calls, 2)
        for _, inputs, metadata in values:
            with self.subTest(cache=metadata['preparation_cache']):
                self.assertTrue(inputs)
                self.assertEqual(metadata['input_bytes_bound'], len(encoded(inputs)) + 1)
                self.assertEqual(next(iter(inputs.values()))['event']['sc06_unknown'], self.event['sc06_unknown'])
        self.assertEqual(values[0][:2], values[1][:2])

    def test_empty_capture_byte_bound_includes_outer_object(self):
        self.record_present = False
        _, inputs, metadata = self.read()
        self.assertEqual(inputs, {})
        self.assertEqual(metadata['input_bytes_bound'], len(encoded(inputs)))

    def test_byte_bound_counts_escaped_instrument_keys_as_encoded_utf8(self):
        from app.comparison.readiness_inputs import instrument
        from app.storage import scanner_readiness
        key = 'sc06:"quoted\\\n雪'
        def escaped_key(*args, **kwargs):
            value = instrument(*args, **kwargs)
            value['id'] = key
            return value
        with patch.object(scanner_readiness, 'instrument', side_effect=escaped_key):
            _, inputs, metadata = self.read(cache=False)
        self.assertEqual(list(inputs), [key])
        self.assertEqual(metadata['input_bytes_bound'], len(encoded(inputs)) + 1)

    def test_input_key_overhead_is_guarded_at_the_capture_capacity_boundary(self):
        from app.storage import scanner_readiness
        from app.comparison.scanner_projection import MAX_INPUT_BYTES
        original = scanner_readiness._prepare_group
        for overflow in (0, 1):
            with self.subTest(overflow=overflow):
                def accounted_at_boundary(*args, **kwargs):
                    value = original(*args, **kwargs)
                    overhead = 2 + sum(len(encoded(key)) + 2 for key in value['financial_inputs'])
                    # Keep the already-counted value counter below the old
                    # limit. Only the complete object/key guard can refuse +1.
                    value['input_bytes'] = MAX_INPUT_BYTES - overhead + overflow
                    return value
                with patch.object(scanner_readiness, '_prepare_group', side_effect=accounted_at_boundary):
                    if overflow:
                        with self.assertRaisesRegex(RuntimeError, '^scanner_financial_capture_capacity$'):
                            self.read(cache=False)
                    else:
                        self.assertEqual(self.read(cache=False)[2]['input_bytes_bound'], MAX_INPUT_BYTES)

    def test_transferred_capture_does_not_alias_preparation_or_selected_capture(self):
        from app.comparison.scanner_projection import Projection
        from app.storage.scanner_readiness import capture
        first = self.read()
        expected = deepcopy(first[:2])
        projection = Projection(clock=lambda: AT)
        projection._ingest_capture(first[0], first[1], input_bytes_bound=first[2]['input_bytes_bound'])
        self.assertIs(projection.frame, first[0])
        self.assertIs(projection.inputs, first[1])
        projection.frame['instruments'][0]['predicate']['predicate'] = 'projection-owned mutation'
        next(iter(projection.inputs.values()))['quote']['depth'][0]['quantity'] = '777'
        self.assertEqual(self.read()[:2], expected)
        members = ((self.q['source']['provider'], self.q['source']['native_event_id']),)
        selected = capture(self.db, config=self.config, at=clock(), selection=self.selection,
            authority=self.authority, source_status=self.status,
            cache=PreparationCache(max_entries=32, max_bytes=4 * 1024 * 1024), members=members)
        self.assertEqual(selected[:2], expected)
        next(iter(selected[1].values()))['quote']['depth'][0]['quantity'] = '999'
        self.assertEqual(self.read()[:2], expected)

    def test_original_quote_expiry_at_equality_rechecks_without_clock_renewal(self):
        first = self.read(); old = first[0]['instruments'][0]
        self.assertEqual(old['checks']['execution']['state'], 'ready')
        self.read(seconds=1); self.assertEqual(self.calls, 1)
        expired = self.read(seconds=30)[0]['instruments'][0]
        self.assertEqual(self.calls, 2)
        self.assertIn('source_price_expired', expired['checks']['execution']['reason_codes'])
        self.assertEqual(expired['clocks']['source_at'], old['clocks']['source_at'])
        self.assertEqual(expired['clocks']['received_at'], old['clocks']['received_at'])

    def test_exact_receipt_only_book_header_invalidates_same_revision(self):
        self.read(); self.assertEqual(self.calls, 1)
        self.book['received_at'] = clock(1)
        result = self.read(seconds=1)[0]['instruments'][0]
        self.assertEqual(self.calls, 2)
        self.assertEqual(result['clocks']['book_received_at'], clock(1))
        self.assertEqual(result['clocks']['book_at'], AT)

    def test_authority_and_same_state_hold_reason_invalidate_immediately(self):
        self.read(); self.assertEqual(self.calls, 1)
        self.status[self.q['venue']]['reason_code'] = 'ambiguous_dispatch_unresolved'
        blocked = self.read()[0]['instruments'][0]
        self.assertEqual(self.calls, 2)
        self.assertIn('ambiguous_dispatch_unresolved', blocked['checks']['execution']['reason_codes'])
        self.authority = None
        unauthorized = self.read()[0]['instruments'][0]
        self.assertEqual(self.calls, 3)
        self.assertIn('scope_not_authorized', unauthorized['checks']['execution']['reason_codes'])

    def test_epoch_engine_and_resolved_occurrence_change_cannot_borrow_old_preparation(self):
        self.read()
        self.epoch = 'new-epoch'; self.read(); self.assertEqual(self.calls, 2)
        self.engine = 'changed-engine'; self.read(); self.assertEqual(self.calls, 3)
        self.match_revision = 'new-peer-made-occurrence-ambiguous'
        self.read(); self.assertEqual(self.calls, 4)

    def test_changed_depth_native_predicate_and_receipt_each_miss_same_whole_revision(self):
        self.read()
        self.q['depth'][0]['quantity'] = '1'
        self.read(); self.assertEqual(self.calls, 2)
        self.q['binding']['selection']['predicate'] = 'not_win'
        result = self.read()[0]['instruments'][0]
        self.assertEqual(self.calls, 3)
        self.assertNotEqual(result['checks']['contract']['state'], 'ready')
        self.q['times']['received_at'] = clock(1)
        result = self.read(seconds=1)[0]['instruments'][0]
        self.assertEqual(self.calls, 4)
        self.assertEqual(result['clocks']['received_at'], clock(1))

    def test_unused_status_churn_does_not_rebuild_and_removed_group_is_pruned(self):
        self.read()
        self.status['unused_test_source'] = dict(state='failed', reason_code='unrelated')
        self.read(); self.assertEqual(self.calls, 1)
        self.record_present = False
        result = self.read()
        self.assertEqual(result[0]['instruments'], [])
        self.assertEqual(self.cache.stats()['entries'], 0)

    def change_profile(self, kind, edit, *, expires_at=None):
        from app.comparison.current_dependencies import profile, references
        payload = deepcopy(references(self.q, self.profiles)[kind]['payload'])
        edit(payload)
        key, value = profile(kind, payload, expires_at=expires_at)
        self.profiles[key] = value
        self.q['comparison_input_refs']['refs'][kind] = key
        if kind in ('fee', 'payout'):
            recipe = self.q['comparison_input_status'][kind]['estimate_content']
            recipe['original_profile_ref'] = key
            recipe['id'] = digest({k: v for k, v in recipe.items() if k != 'id'})

    def test_nested_model_expiry_and_changed_grid_cannot_reuse_ready_facts(self):
        self.change_profile('quantity', lambda payload: None, expires_at=clock(5))
        first = self.read()
        self.assertEqual(first[0]['instruments'][0]['checks']['contract']['state'], 'ready')
        self.assertEqual(first[2]['revalidate_at'], clock(5))
        expired = self.read(seconds=5)[0]['instruments'][0]
        self.assertEqual(self.calls, 2)
        self.assertIn('quantity_expired', expired['checks']['contract']['reason_codes'])
        self.change_profile('quantity', lambda payload: payload['grid'].update(minimum_native='200'))
        changed = self.read(seconds=5)[0]['instruments'][0]
        self.assertEqual(self.calls, 3)
        self.assertIn('observed_depth_insufficient', changed['checks']['execution']['reason_codes'])

    def test_inactive_registry_start_caps_authority_and_rebuilds_at_equality(self):
        with tempfile.TemporaryDirectory(prefix='sc06-inactive-registry-') as folder:
            root = Path(folder)
            fixtures = root / 'app/fixtures'; fixtures.mkdir(parents=True)
            (fixtures / 'inactive.json').write_text(json.dumps(dict(records=[dict(effective_from=clock(5))])))
            with patch('app.storage.scanner_preparation.__file__', str(root / 'app/storage/scanner_preparation.py')):
                before = self.read()
                self.assertEqual(before[2]['revalidate_at'], clock(5))
                self.assertEqual(before[0]['instruments'][0]['expires_at'], clock(5))
                self.read(seconds=4); self.assertEqual(self.calls, 1)
                self.read(seconds=5); self.assertEqual(self.calls, 2)

    def test_scheduled_fee_boundary_revises_model_identity_without_a_new_quote(self):
        # Authored schedule marker exercises temporal identity only; this test
        # claims no financial fee result or real source qualification.
        def edit(payload):
            payload['engine_context']['kalshi_metadata'] = dict(
                series_changes=[dict(scheduled_ts=clock(5))], event_changes=[])
        self.change_profile('fee', edit)
        before = self.read()[0]['instruments'][0]
        self.assertEqual(before['expires_at'], clock(5))
        self.read(seconds=4); self.assertEqual(self.calls, 1)
        after = self.read(seconds=5)[0]['instruments'][0]
        self.assertEqual(self.calls, 2)
        self.assertNotEqual(before['model_versions'], after['model_versions'])
        self.assertEqual(before['clocks'], after['clocks'])

    def test_future_book_receipt_is_rechecked_when_its_original_instant_arrives(self):
        self.book['received_at'] = clock(5)
        before = self.read()[0]['instruments'][0]
        self.assertIn('book_clock_conflict', before['checks']['execution']['reason_codes'])
        self.assertEqual(before['expires_at'], clock(5))
        after = self.read(seconds=5)[0]['instruments'][0]
        self.assertEqual(self.calls, 2)
        self.assertEqual(after['checks']['execution']['state'], 'ready')
        self.assertEqual(after['clocks']['book_at'], AT)

    def test_future_at_receipt_never_ages_into_authority(self):
        self.q['times']['source_at'] = clock(5)
        self.q['provider_clocks'] = dict(book=clock(5), market=clock(5))
        self.book.update(source_at=clock(5), received_at=AT)
        for seconds in (0, 5, 6):
            with self.subTest(seconds=seconds):
                value = self.read(seconds=seconds)[0]['instruments'][0]
                self.assertIn('source_clock_conflict', value['checks']['execution']['reason_codes'])
                self.assertIn('book_clock_conflict', value['checks']['execution']['reason_codes'])

    def test_optional_reference_expiry_does_not_grant_or_remove_cashflow_readiness(self):
        from app.comparison.current_dependencies import references
        reference = references(self.q, self.profiles)['reference']['payload']
        expiry = min(instant(row[key]) for row in reference['outcomes'] for key in ('book_at', 'market_at')) + timedelta(seconds=1800)
        boundary = (expiry - instant(AT)).total_seconds()
        now = clock(boundary - 5)
        self.q['times'].update(source_at=now, received_at=now, projected_at=now)
        self.q['provider_clocks'] = dict(book=now, market=now)
        self.book.update(source_at=now, received_at=now)
        before = self.read(seconds=boundary - 5)[0]['instruments'][0]
        self.assertEqual(before['checks']['execution']['state'], 'ready')
        self.assertEqual(before['checks']['contract']['state'], 'ready')
        self.assertNotIn('reference_expired', before['checks']['ev']['reason_codes'])
        after = self.read(seconds=boundary)[0]['instruments'][0]
        self.assertEqual(self.calls, 2)
        self.assertEqual(after['checks']['execution']['state'], 'ready')
        self.assertEqual(after['checks']['contract']['state'], 'ready')
        self.assertIn('reference_expired', after['checks']['ev']['reason_codes'])
