"""Provider-local observations stay distinct while shared context is unknown."""
from copy import deepcopy
from unittest import TestCase

from app.comparison.event_links import EventLinks, provider_key
from app.comparison.occurrence_matching import OccurrenceResolver
from tests.test_ev02_occurrence import AT, rows


def missing_context(provider, native, *, season=True, stage=True):
    record = rows(provider, native, shared={'sportradar': 'shared-observed-id'})[0]
    for field, missing in (('season', season), ('stage', stage)):
        if missing:
            record['event'][field] = None
            record['market_identity'][field] = None
    return record


class SourceLocalOccurrence(TestCase):
    def test_shared_id_does_not_join_two_missing_context_observations(self):
        records = [missing_context('kalshi', 'same-native-id'),
                   missing_context('polymarket_us', 'same-native-id')]
        before = deepcopy(records)
        output = OccurrenceResolver(links=EventLinks()).resolve(records, clock=AT)
        self.assertEqual(records, before)
        for row in output:
            self.assertEqual(row['quote']['occurrence_match']['status'], 'unresolved')
            self.assertEqual(row['event_scope']['policy'], 'native-event-unverified-2')
            self.assertFalse(row['verified'])
            self.assertEqual(row['market_identity']['event'],
                             provider_key(row['quote']['source']['provider'], row['event']))
            self.assertIsNone(row['event']['season'])
            self.assertIsNone(row['event']['stage'])
        self.assertNotEqual(output[0]['market_identity']['event'], output[1]['market_identity']['event'])

    def test_complete_peer_does_not_supply_own_missing_context(self):
        records = [missing_context('kalshi', 'missing-season', stage=False),
                   rows('polymarket_us', 'complete', shared={'sportradar': 'shared-observed-id'})[0]]
        output = OccurrenceResolver(links=EventLinks()).resolve(records, clock=AT)
        self.assertEqual(output[0]['quote']['occurrence_match']['status'], 'unresolved')
        self.assertIsNone(output[0]['event']['season'])
        self.assertEqual(output[1]['quote']['occurrence_match']['status'], 'matched')
        self.assertEqual(len(output[1]['quote']['occurrence_match']['members']), 1)

    def test_remembered_join_cannot_restore_lost_context(self):
        resolver = OccurrenceResolver(links=EventLinks())
        complete = [rows(v, v, shared={'sportradar': 'shared-observed-id'})[0]
                    for v in ('kalshi', 'polymarket_us')]
        self.assertTrue(all(r['quote']['occurrence_match']['status'] == 'matched'
                            for r in resolver.resolve(complete, clock=AT)))
        incomplete = [missing_context(v, v) for v in ('kalshi', 'polymarket_us')]
        output = resolver.resolve(incomplete, clock=AT)
        self.assertTrue(all(r['quote']['occurrence_match']['status'] == 'unresolved' for r in output))
        self.assertEqual(resolver.members, {})
        for source, result in zip(incomplete, output):
            self.assertEqual(source['quote']['source'], result['quote']['source'])
            self.assertEqual(source['quote']['original'], result['quote']['original'])
            self.assertEqual(source['quote']['times'], result['quote']['times'])

    def test_other_missing_occurrence_context_is_not_a_shared_match(self):
        record = rows('kalshi', 'incomplete-occurrence', shared={'sportradar': 'shared-observed-id'})[0]
        record['comparison_source_metadata'] = dict(comparison_admission=dict(
            supported=False, reason='comparison_context_missing', missing_fields=['game_number', 'original_start']))
        output = OccurrenceResolver(links=EventLinks()).resolve([record], clock=AT)[0]
        self.assertEqual(output['quote']['occurrence_match']['status'], 'unresolved')
        self.assertEqual(output['event_scope']['policy'], 'native-event-unverified-2')
        self.assertFalse(output['verified'])
