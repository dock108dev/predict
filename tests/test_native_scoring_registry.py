"""Read-only SQL replay and explicitly authored ingress/freshness controls.

The retained fixture keeps native prices/clocks. Authored book/clocks in tests
qualify deterministic behavior, never current ordinary coverage or acquisition.
"""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.comparison import native_scoring_scope as scope
from app.comparison.combined_native import normalize
from app.comparison.current_dependencies import digest
from app.collection.v1_comparison import _bind_v1
from app.dashboard.comparison_board import entries, gross_comparison, age_gross_comparison
from app.storage.comparison_board import ReadContext
from app.storage.store import stamp
from tests.test_current_occurrence import book

FIXTURE = Path(__file__).parent / 'fixtures/current-three-games-metadata-retained.json'
AT = '2026-10-17T17:15:00+00:00'


def records():
    return json.loads(FIXTURE.read_text())['records']


def key(row):
    source = row['quote']['source']
    return (row['quote']['venue'], *[source[k] for k in
        ('native_event_id', 'native_market_id', 'native_outcome_id', 'native_side')])


def winners():
    return [row for row in records() if row['selection']['predicate'] == 'win']


def context(rows=None):
    return ReadContext(SimpleNamespace(db=None), at=AT, frame=dict(epoch='authored-registry-replay',
        revision='retained-sql-fixture', records=records() if rows is None else rows))


class NativeScoringRegistry(TestCase):
    def test_all_six_existing_sql_outcomes_reproject_without_recollection(self):
        rows = records();before = deepcopy(rows)
        with patch('socket.socket.connect', side_effect=AssertionError('offline SQL replay')):
            bundles = context(rows).observation_bundles()
        self.assertEqual(len(bundles), 3)
        paired = set();directed = 0
        for bundle in bundles:
            state = bundle['state_inputs'];values = entries(state)
            for event, group, quote in values:
                if quote['binding']['selection']['predicate'] != 'win':
                    continue
                self.assertEqual(quote['native_contract']['scope']['overtime'], 'included')
                audit = quote['native_contract']['scope_evidence']
                self.assertEqual(audit['status'], 'supported')
                self.assertTrue(any(f['basis'] in ('source_type_rule','selected_source_description') for f in audit['evidence']))
                paired.add(quote['binding']['selection']['participant'])
                comparison = gross_comparison(quote, group, event, state, stamp(AT))
                self.assertTrue(comparison['available'])
                other = next(q for _,_,q in values if q['venue'] != quote['venue']
                    and q['binding']['selection']['participant'] == quote['binding']['selection']['participant']
                    and q['binding']['selection']['predicate'] == 'win')
                expected = (Fraction(other['original']['value']) - Fraction(quote['original']['value'])) * 100
                actual = Fraction(int(comparison['exact']['numerator']), int(comparison['exact']['denominator']))
                self.assertEqual(actual, expected)
                self.assertEqual(comparison['inputs'][0]['times'], quote['times'])
                self.assertEqual(comparison['inputs'][1]['native_side'], other['source']['native_side'])
                directed += 1
        self.assertEqual((len(paired), directed), (6, 12))
        self.assertEqual(rows, before)

    def test_every_native_binding_preserves_prices_predicates_descriptions_and_original_clocks(self):
        registry = scope.validate_registry(scope.registry())
        self.assertEqual(len(registry['governing_rules']), 1)
        for row in winners():
            with self.subTest(native=key(row)):
                before = deepcopy(row);value = scope.attach(row, at=AT)
                self.assertEqual(value['comparison_scope'], {'overtime': 'included'})
                for field in ('quote', 'selection', 'event', 'market_identity'):
                    self.assertEqual(value[field], before[field])
                self.assertEqual(value['comparison_source_metadata']['original_wording'],
                    before['comparison_source_metadata']['original_wording'])
                self.assertEqual(scope.attach(value, at=AT), value)
                self.assertEqual(row, before)
        self.assertEqual(len(winners()), 12)

    def test_future_ordinary_ingress_uses_same_generic_resolver_for_added_targets(self):
        for row in winners():
            if row['quote']['venue'] != 'kalshi' or row['selection']['participant'] == 'NFL:JAX':
                continue
            with self.subTest(participant=row['selection']['participant']):
                event = deepcopy(row['event'])
                event.update(identity='resolved', canonical_key=[event['scheduled_start'], sorted(event['participants'].values())],
                    _native=dict(series_ticker='KXNFLGAME'))
                metadata = row['comparison_source_metadata'];wording = deepcopy(metadata['original_wording'])
                market = dict(id=key(row)[2], event_id=event['id'], title=wording['title'],
                    market_type='moneyline', period='full_game',
                    terms=deepcopy(metadata['combined_native_binding']['original_terms']),
                    sides=[dict(id=s, role=s, label=wording['yes_sub_title']) for s in ('yes','no')], _native=wording)
                market['v1_raw_binding'] = _bind_v1(event, market, 'kalshi', revised=True)
                catalog = dict(id='authored-ingress', record=dict(source='kalshi',
                    value=dict(inventory=dict(events=[event], markets=[market]))))
                native_book = book('kalshi', market, AT)
                observation = dict(type='prediction_book', source='kalshi', observed_at=AT, book=native_book)
                books = [dict(id='authored-book', record=dict(retained_at=AT, value=dict(observations=[observation])))]
                with patch('socket.socket.connect', side_effect=AssertionError('authored ordinary ingress')):
                    values, excluded = normalize(catalog, books, at=AT)
                self.assertFalse(excluded)
                yes = next(r for r in values if r['quote']['source']['native_side'] == 'yes')
                no = next(r for r in values if r['quote']['source']['native_side'] == 'no')
                self.assertEqual(yes['comparison_scope']['overtime'], 'included')
                self.assertEqual(no['comparison_scope']['overtime'], 'included')
                self.assertEqual(yes['selection']['participant'], row['selection']['participant'])
                self.assertEqual(no['selection']['predicate'], 'not_win')
                self.assertEqual(yes['quote']['times']['source_at'], AT)
                self.assertEqual(yes['quote']['original']['value'], '.48')

    def test_changed_own_identity_terms_or_wording_fail_closed_per_native_input(self):
        for original in winners():
            for field in ('participant', 'predicate', 'schedule', 'home', 'season', 'stage', 'native_key',
                          'series', 'family', 'period', 'terms', 'wording', 'duplicate', 'source_roles', 'original_roles'):
                with self.subTest(native=key(original), changed=field):
                    row = deepcopy(original);meta = row['comparison_source_metadata']
                    if field in ('participant','predicate'):
                        row['selection'][field] = 'NFL:OTHER' if field == 'participant' else 'not_win'
                    elif field == 'schedule':row['event']['scheduled_start'] = '2026-10-19T17:00:00+00:00'
                    elif field in ('home','season','stage'):row['event'][field] = 'AUTHORED-CONFLICT'
                    elif field == 'native_key':meta['native_key'][-1] = 'AUTHORED-CONFLICT'
                    elif field == 'series':
                        if key(row)[0] == 'kalshi':meta['series_id'] = 'AUTHORED-CONFLICT'
                        else:meta['native_market_type'] = 'AUTHORED-CONFLICT'
                    elif field in ('family','period'):row['market_identity'][field] = 'AUTHORED-CONFLICT'
                    elif field == 'terms':meta['combined_native_binding']['original_terms']['description'] = 'AUTHORED-CONFLICT'
                    elif field == 'wording':meta['original_wording']['description'] = 'AUTHORED-CONFLICT'
                    elif field == 'duplicate':row['event']['conflicting_duplicate'] = True
                    elif field == 'source_roles':row['event']['source_participant_roles']['home'] = 'NFL:OTHER'
                    else:meta['combined_native_binding']['original_roles']['home'] = 'NFL:OTHER'
                    audit = scope.resolve(row, at=AT)
                    self.assertEqual(audit['status'], 'contradictory')
                    self.assertEqual(audit['overtime'], 'unknown')
                    self.assertEqual(row['quote'], original['quote'])

    def test_changed_us_quote_key_cannot_escape_registered_identity_through_literal(self):
        original = next(r for r in winners() if key(r)[0] == 'polymarket_us')
        for field in ('provider', 'native_event_id', 'native_market_id', 'native_outcome_id', 'native_side'):
            row = deepcopy(original);row['quote']['source'][field] = 'AUTHORED-MOVED'
            with self.subTest(field=field):
                self.assertEqual(scope.resolve(row, at=AT)['reason'], 'scope_rules_identity_conflict')
                self.assertEqual(scope.resolve(row, at=AT)['overtime'], 'unknown')
        # A consistent unregistered source keeps its own literal declaration;
        # this does not manufacture a registry outcome or opponent predicate.
        row = deepcopy(original)
        row['quote']['source']['native_market_id'] = 'AUTHORED-CONSISTENT'
        row['comparison_source_metadata']['native_key'][2] = 'AUTHORED-CONSISTENT'
        row['comparison_source_metadata']['public_retail_observation']['market_id'] = 'AUTHORED-CONSISTENT'
        self.assertEqual(scope.resolve(row, at=AT)['status'], 'supported')

    def test_missing_facts_are_unknown_and_do_not_raise_or_hide_observation(self):
        for field in ('terms', 'wording', 'home', 'schedule', 'native_key', 'period'):
            row = winners()[0];before = deepcopy(row['quote']);meta = row['comparison_source_metadata']
            if field == 'terms':meta['combined_native_binding']['original_terms'] = None
            elif field == 'wording':meta['original_wording'] = None
            elif field == 'home':row['event'].pop('home')
            elif field == 'schedule':row['event'].pop('scheduled_start')
            elif field == 'native_key':meta.pop('native_key')
            else:row['market_identity'].pop('period')
            with self.subTest(field=field):
                audit = scope.resolve(row, at=AT)
                self.assertEqual(audit['status'], 'unknown')
                self.assertEqual(audit['overtime'], 'unknown')
                self.assertEqual(row['quote'], before)

    def test_no_stays_named_team_not_win_and_conflicting_scope_stays_unknown(self):
        for row in records():
            if row['selection']['predicate'] == 'not_win':
                self.assertEqual(scope.resolve(row, at=AT)['overtime'], 'included')
                self.assertEqual(scope.attach(row, at=AT)['selection'], row['selection'])
        for row in winners():
            row['comparison_source_metadata'].pop('scoring_scope', None)
            row['comparison_scope']['overtime'] = 'excluded'
            self.assertEqual(scope.resolve(row, at=AT)['status'], 'contradictory')

    def test_generic_registry_validation_rejects_ambiguous_or_unbounded_data(self):
        original = scope.registry()
        for kind in ('duplicate_target', 'duplicate_key', 'hash', 'predicate', 'period', 'side', 'bound', 'path'):
            value = deepcopy(original)
            if kind == 'duplicate_target':value['targets'].append(deepcopy(value['targets'][0]))
            elif kind == 'duplicate_key':value['targets'][1]['bindings'][0]['native_key'] = value['targets'][0]['bindings'][0]['native_key']
            elif kind == 'hash':value['targets'][0]['bindings'][0]['terms']['sha256'] = '0'*64
            elif kind == 'predicate':value['targets'][0]['selection']['predicate'] = 'not_win'
            elif kind == 'period':value['targets'][0]['period'] = 'unknown'
            elif kind == 'side':value['targets'][0]['bindings'][0]['native_key'][-2:] = ['no','no']
            elif kind == 'bound':value['targets'] *= 6
            else:value['governing_rules']['kalshi-nfl-full-game']['path'] = '../external.pdf'
            with self.subTest(kind=kind), self.assertRaises((ValueError, KeyError)):
                scope.validate_registry(value)

    def test_retired_event_specific_admission_is_not_callable(self):
        for name in ('_registered_fact', '_publication_dependency', '_lookup',
                     '_evidence', 'publication_dependency', 'UNKNOWN_FAILURES'):
            with self.subTest(name=name):
                self.assertFalse(hasattr(scope, name))

    def test_ordinary_admission_never_reads_historical_event_targets(self):
        with patch.object(scope, 'registry', side_effect=AssertionError('No example event admission')):
            for row in winners():
                self.assertEqual(scope.resolve(row, at=AT)['status'], 'supported')

    def test_original_freshness_boundary_and_frozen_pair_cover_all_six(self):
        for bundle in context().observation_bundles():
            state = bundle['state_inputs']
            for _,_,quote in entries(state):
                quote['times'].update(source_at=AT, received_at=AT);quote['state'] = 'available'
            for event,group,quote in entries(state):
                if quote['binding']['selection']['predicate'] != 'win':continue
                with self.subTest(native=quote['source']):
                    at = stamp(AT)
                    captured = gross_comparison(quote, group, event, state, at, current_only=True)
                    self.assertEqual(captured['display_status'], 'current')
                    before = deepcopy(captured)
                    age_gross_comparison(captured, at + timedelta(seconds=30))
                    self.assertEqual(captured['display_status'], 'current')
                    self.assertTrue(gross_comparison(quote, group, event, state, at + timedelta(seconds=30), current_only=True)['available'])
                    self.assertFalse(gross_comparison(quote, group, event, state, at + timedelta(seconds=30, microseconds=1), current_only=True)['available'])
                    age_gross_comparison(captured, at + timedelta(seconds=30, microseconds=1))
                    self.assertEqual(captured['display_status'], 'last_known')
                    for actual, original in zip(captured['inputs'], before['inputs']):
                        for field in ('quote_id', 'native_side', 'original', 'times', 'selection'):
                            self.assertEqual(actual[field], original[field])
                    self.assertEqual(captured['exact'], before['exact'])


class NativeRegistryDependencies(TestCase):
    def test_real_source_rule_and_evidence_file_edits_refresh_cached_scope(self):
        original_root = scope.ROOT
        rules = scope.source_rules()
        paths = {'app/fixtures/native-scope-bindings-v1.json', 'app/fixtures/public-contracts-v1.json',
            'app/fixtures/native-scoring-scope/full-game-source-rules.json'}
        for rule in rules:
            evidence = rule.get('evidence') or {}
            if evidence.get('path'):paths.add(evidence['path'])
            pointer = evidence.get('pointer_evidence') or {}
            if pointer.get('path'):paths.add(pointer['path'])
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for path in paths:
                target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((original_root/path).read_bytes())
            with patch.object(scope,'ROOT',root):
                own = next(r for r in winners() if key(r)[0]=='kalshi')
                self.assertEqual(scope.resolve(own,at=AT)['overtime'],'included')
                before=scope.publication_dependencies([key(own)],[own])
                path=root/'app/fixtures/native-scoring-scope/full-game-source-rules.json'
                authored=json.loads(path.read_text())
                next(r for r in authored['rules'] if r['native_type']=='KXNFLGAME')['defaults']['overtime']='excluded'
                path.write_text(json.dumps(authored))
                self.assertEqual(scope.resolve(own,at=AT)['overtime'],'excluded')
                self.assertNotEqual(scope.publication_dependencies([key(own)],[own]),before)
                next(r for r in authored['rules'] if r['native_type']=='KXNFLGAME')['defaults']['overtime']='included'
                path.write_text(json.dumps(authored))
                evidence=root/'app/fixtures/native-scoring-scope/kalshi-football.pdf'
                evidence.write_bytes(evidence.read_bytes()+b'authored-evidence-change')
                self.assertEqual(scope.resolve(own,at=AT)['reason'],'scope_rules_evidence_unavailable')

    def test_historical_target_changes_cannot_change_current_dependencies(self):
        keys = [key(r) for r in winners()]
        before = scope.publication_dependencies(keys)
        value = scope.registry();value['targets'] = []
        with patch.object(scope, 'registry', return_value=value):
            self.assertEqual(scope.publication_dependencies(keys), before)

    def test_rule_scope_is_source_type_specific(self):
        rows = winners();keys = [key(r) for r in rows]
        before = scope.publication_dependencies(keys, rows)
        original = scope.source_rules()
        changed = deepcopy(original)
        next(r for r in changed if r['provider'] == 'polymarket_us' and r['league'] == 'NBA' and r['family'] == 'total')['overtime'] = 'excluded'
        with patch.object(scope, 'source_rules', return_value=changed):
            self.assertEqual(scope.publication_dependencies(keys, rows), before)
        changed = deepcopy(original)
        next(r for r in changed if r['provider'] == 'kalshi' and r['native_type'] == 'KXNFLGAME')['overtime'] = 'excluded'
        with patch.object(scope, 'source_rules', return_value=changed):
            after = scope.publication_dependencies(keys, rows)
        self.assertEqual({k for k,a,b in zip(keys,before,after) if a != b}, {k for k in keys if k[0] == 'kalshi'})

    def test_missing_shared_evidence_withholds_only_its_scoring_class(self):
        rows = winners();rules = scope.source_rules()
        changed = deepcopy(rules)
        selected = next(r for r in changed if r['provider'] == 'kalshi' and r['native_type'] == 'KXNFLGAME')
        selected.update(overtime='unknown', evidence_available=False)
        with patch.object(scope, 'source_rules', return_value=changed):
            for row in rows:
                audit = scope.resolve(row, at=AT)
                self.assertEqual(audit['status'], 'unknown' if key(row)[0] == 'kalshi' else 'supported')
                if key(row)[0] == 'kalshi':
                    self.assertEqual(audit['reason'], 'scope_rules_evidence_unavailable')
