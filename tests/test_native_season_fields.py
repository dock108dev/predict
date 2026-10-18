"""Synthetic controls for the exact flat form observed in ordinary NBA bytes."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest

from app.collection.admission_enrichment import enrich_game
from tests.multisport_fixtures import SPORTS, FAMILIES, source_case, fake_discovery
from tests.test_current_multisport_ingress import worker


def event(facts, **extra):
    return dict(id='unseen-native-game', source='kalshi', competition='NBA',
        participants={}, observed_identity_facts=deepcopy(facts), **extra)


class NativeSeasonFacts(unittest.TestCase):
    def test_known_flat_tokens_use_exact_year_without_cross_year_inference(self):
        for token, stage in (('REG', 'regular_season'), ('PRE', 'preseason'), ('POST', 'playoffs')):
            with self.subTest(token=token):
                raw = event([dict(season_type=token, season_year=2026)])
                result = enrich_game(raw)
                self.assertEqual((result['season'], result['stage']), ('2026', stage))
                self.assertEqual(result['observed_identity_facts'], raw['observed_identity_facts'])
                self.assertNotIn('identity_conflicts', result)

    def test_nested_declared_name_and_matching_flat_witness_remain_explicit(self):
        for year in (2026, 2027):
            with self.subTest(year=year):
                raw = event([dict(season=dict(name='2026-2027', year=year, type='REG'),
                    season_type='REG', season_year=year)])
                result = enrich_game(raw)
                self.assertEqual((result['season'], result['stage']), ('2026-2027', 'regular_season'))
                self.assertEqual(result['observed_identity_facts'], raw['observed_identity_facts'])

    def test_conflicting_shapes_or_duplicate_witnesses_cannot_silently_win(self):
        failures = [
            [dict(season=dict(year=2026, type='REG'), season_year=2027, season_type='REG')],
            [dict(season=dict(year=2026, type='REG'), season_year=2026, season_type='POST')],
            [dict(season_year=2026, season_type='REG'), dict(season_year=2027, season_type='REG')],
            [dict(season_year=2026, season_type='PRE'), dict(season_year=2026, season_type='REG')],
            [dict(season=dict(name='2026-2027', year=2026, type='REG')),
             dict(season=dict(name='2025-2026', year=2026, type='REG'))],
            [dict(season=dict(name='2027', year=2026, type='REG'))],
            [dict(season=dict(name='2027-2028', year=2026, type='REG'))],
            [dict(season=dict(name='2027-2026', year=2026, type='REG'))],
        ]
        for facts in failures:
            with self.subTest(facts=facts):
                result = enrich_game(event(facts))
                self.assertTrue(result['identity_conflicts'])
                self.assertNotIn('season', result); self.assertNotIn('stage', result)
                self.assertEqual(result['observed_identity_facts'], facts)

    def test_explicit_unknown_type_beside_known_witness_stays_blocked(self):
        for kind in (None, 'UNKNOWN_SOURCE_ENUM', 'regular_season', {}, [], True, 1):
            for shape in ('same_fact', 'separate_fact'):
                with self.subTest(kind=kind, shape=shape):
                    facts = [dict(season=dict(year=2026, type='REG'))]
                    if shape == 'same_fact':facts[0].update(season_year=2026, season_type=kind)
                    else:facts.append(dict(season_year=2026, season_type=kind))
                    result = enrich_game(event(facts))
                    self.assertTrue(result['identity_conflicts'])
                    self.assertNotIn('season', result); self.assertNotIn('stage', result)
                    self.assertEqual(result['observed_identity_facts'], facts)

    def test_year_types_unknown_tokens_and_missing_facts_are_never_guessed(self):
        for year in ('2026', 2026.0, True, {}, []):
            with self.subTest(year=year):
                result = enrich_game(event([dict(season_type='REG', season_year=year)]))
                self.assertTrue(result['identity_conflicts'])
                self.assertNotIn('season', result); self.assertNotIn('stage', result)
        for facts in ([dict(season_type='UNKNOWN_SOURCE_ENUM', season_year=2026)],
                      [dict(season_type='REG')], [dict(season_year=2026)],
                      [dict(season_type=None, season_year=None)], []):
            with self.subTest(facts=facts):
                result = enrich_game(event(facts))
                self.assertNotIn('season', result); self.assertNotIn('stage', result)
                self.assertEqual(result['observed_identity_facts'], facts)

    def test_existing_explicit_context_conflict_stays_blocked(self):
        result = enrich_game(event([dict(season_type='REG', season_year=2026)],
            season='2025', stage='regular_season'))
        self.assertTrue(result['conflicting_duplicate'])


class NativeSeasonAdmission(unittest.IsolatedAsyncioTestCase):
    async def test_all_six_leagues_three_families_accept_later_unseen_flat_form(self):
        for sport in SPORTS:
            for family in FAMILIES:
                with self.subTest(sport=sport, family=family):
                    native, published = worker('kalshi', [sport], [family])
                    cases = []; fake_discovery(native, cases)
                    await native.discover()
                    self.assertFalse(native.markets)
                    case = source_case(sport, family, 'later-flat-'+sport+'-'+family)
                    detail = case['milestone']['details']
                    detail.pop('season'); detail.update(season_year=2026, season_type='REG')
                    cases.append(case)
                    await native.discover()
                    catalog = published[-1]; observed = catalog['events'][0]
                    binding = catalog['markets'][0]['v1_raw_binding']
                    self.assertEqual((observed['season'], observed['stage']), ('2026', 'regular_season'))
                    self.assertEqual(binding['status'], 'BOUND_RAW_PREDICATE', binding['blockers'])
                    self.assertEqual(len(native.markets), 1)
                    facts = observed['observed_identity_facts'][0]
                    self.assertEqual((facts['season_year'], facts['season_type']), (2026, 'REG'))
                    self.assertNotIn('season', facts)
                    self.assertIn('UNSEEN-', observed['id'])
                    # Existing ordinary ingress reaches a retained own-source
                    # price, with no per-event registry or nullable schema path.
                    from app.comparison.combined_native import normalize
                    from tests.multisport_fixtures import current_book
                    at = datetime.now(timezone.utc).isoformat()
                    catalog_record = dict(id='synthetic-catalog', record=dict(source='kalshi', value=dict(inventory=catalog)))
                    books = [dict(id='synthetic-book', record=dict(retained_at=at,
                        value=dict(observations=[dict(type='prediction_book', source='kalshi',
                            observed_at=at, book=current_book(case, 'kalshi'))])))]
                    rows, excluded = normalize(catalog_record, books, at=at, include_missing=True)
                    self.assertEqual(excluded, []); self.assertEqual(len(rows), 2)
                    self.assertEqual({r['event']['season'] for r in rows}, {'2026'})

    async def test_disagreeing_current_source_fields_block_actual_binding(self):
        native, published = worker('kalshi', ['NBA'], ['moneyline'])
        case = source_case('NBA', 'moneyline', 'flat-conflict')
        case['milestone']['details'].update(season_year=2027, season_type='REG')
        fake_discovery(native, [case]); await native.discover()
        binding = published[-1]['markets'][0]['v1_raw_binding']
        self.assertEqual(binding['status'], 'IDENTITY_BLOCKED')
        self.assertTrue(any('Explicit native season fields conflict' in reason for reason in binding['blockers']))


if __name__ == '__main__':
    unittest.main()
