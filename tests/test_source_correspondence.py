"""Isolated source-join controls over retained books; never real paired coverage."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.dashboard.session_projection import stable
from app.dashboard.price_comparison import comparisons
from app.dashboard.opportunity_history import observations
from app.reference.aggregate import bind, VERSION
from app.reference.odds_bindings import normalize_event
from app.reference.product import time
from app.reference.source_correspondence import augment, POLICY
from tests.test_native_book_comparison import project, rows, watch
from tests.test_source_session import settings


def fixture(*, correspondence=True, skew=0, home='New Mexico State Aggies', schedule=None, receipt_at=None):
    source = native_prefix()
    p = project(source); at = p.last
    schedule = schedule or p.snapshot()['games'][0]['scheduled_start']
    config = settings(correspondence_policy=POLICY) if correspondence else settings()
    config['scopes'] = [dict(sport='NCAAF', markets=['h2h'], event_ids=[])]
    config['stale_seconds'] = 15
    from app.dashboard.native_reviews import DIRECTORY
    review = json.loads((DIRECTORY / 'retained-wku-nmsu-v1.json').read_text())
    review.update(evidence_mode='synthetic', review_id='ISOLATED-CORRESPONDENCE-NATIVE')
    review['applicability']['end'] = schedule
    review.pop('sha256'); review['sha256'] = stable(review)
    source[0] = deepcopy(source[0]); source[0]['spec'].update(mode='mock', source_session=config,
                                                          native_review_records=[review])
    for row in source:
        if row['type'] == 'market_selected':
            row['market']['raw']['kind'] = 'synthetic'
        elif row['type'] == 'prediction_book':
            row['book']['raw']['kind'] = 'synthetic'
    p = project(source)
    stamp = receipt_at or (time(at) + timedelta(seconds=skew)).isoformat()
    body = dict(id='ISOLATED-CORRESPONDENCE', sport_key='americanfootball_ncaaf',
        commence_time=schedule, home_team=home, away_team='Western Kentucky Hilltoppers',
        bookmakers=[dict(key=b, markets=[dict(key='h2h', last_update=stamp,
            outcomes=[dict(name=home, price='2.0'), dict(name='Western Kentucky Hilltoppers', price='2.2')])])
            for b in ('novig', 'prophetx', 'pinnacle', 'draftkings', 'betmgm')])
    records = bind(normalize_event(json.dumps(body).encode(), 'NCAAF', stamp))
    row = dict(type='aggregate_snapshot', session_id=p.sid, source='the_odds_api',
        observed_at=max(time(stamp),time(at)).isoformat(), sport='NCAAF', event_id=body['id'], received_at=stamp,
        processing_at=stamp, response_sha256=records[0]['response'], version=VERSION, records=records)
    p.apply(row)
    return p, row, config


def native_prefix():
    source = rows()
    end = max(i for i, row in enumerate(source) if row['type'] == 'prediction_book')
    return source[:end + 1]


class Correspondence(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'app.collection.venue_access.load_credentials'):
            guard = patch(target, side_effect=AssertionError('No real acquisition'))
            guard.start(); self.addCleanup(guard.stop)

    def test_opt_in_same_session_raw_outcome_join_and_reference_isolation(self):
        p, _, _ = fixture(); snapshot = p.snapshot()
        mixed = [r for r in comparisons(snapshot, {}) if r.get('cross_source')]
        self.assertEqual(len(mixed), 4, snapshot['cross_source_mapping'])
        self.assertEqual({l['venue'] for r in mixed for l in r['legs']}, {'kalshi', 'novig', 'prophetx'})
        self.assertIn('5-second alignment', str(snapshot['cross_source_mapping']['exclusions']))
        for row in mixed:
            self.assertIsNone(row['net']); self.assertIsNone(row['ev'])
            self.assertTrue(row['aggregated']); self.assertFalse(row['timing']['synchronized'])
            self.assertLessEqual(Decimal(row['timing']['receipt_skew_seconds']), 5)
            self.assertTrue(all(l['entry']['upper'] is None for l in row['legs']))
            agg = next(l for l in row['legs'] if l['venue'] in ('novig', 'prophetx'))
            self.assertFalse(agg['levels']); self.assertIsNone(agg['top_size'])
            self.assertIn('different cashflow', row['raw_comparison_units'])
        self.assertTrue([r for r in comparisons(snapshot, {}) if r.get('native_raw')])
        self.assertTrue([r for r in comparisons(snapshot, {}) if r.get('aggregated') and not r.get('cross_source')])
        self.assertTrue(snapshot['references'])

    def test_disabled_policy_leaves_existing_projection_without_mixed_games(self):
        p, _, _ = fixture(correspondence=False); snapshot = p.snapshot()
        self.assertNotIn('source_correspondence_comparisons', snapshot)
        self.assertFalse(any(r.get('cross_source') for r in comparisons(snapshot, {})))

    def test_one_native_book_joins_without_requiring_the_other_native(self):
        p, _, _ = fixture()
        for key in list(p.books):
            if key[0]=='polymarket_us':
                p.books.pop(key)
        s = p.snapshot()
        self.assertFalse(any(r.get('native_raw') for r in comparisons(s, {})))
        mixed = s['source_correspondence_comparisons']
        self.assertEqual(len(mixed), 4, s['cross_source_mapping'])
        self.assertEqual({l['venue'] for r in mixed for l in r['legs']}, {'kalshi','novig','prophetx'})
        self.assertTrue(all(r['source_correspondence']['native_review_sha256'] in s['native_comparison_review']['records'] for r in mixed))

    def test_native_replacement_closure_and_current_connection_invalidate_each_source(self):
        for condition in ('metadata','closure','connection'):
            with self.subTest(condition=condition):
                p, _, _ = fixture()
                if condition=='metadata':
                    p.inventory['kalshi']['markets'][0]['native_metadata']['title']='Changed native listing'
                elif condition=='closure':
                    for key in p.books:
                        if key[0]=='kalshi':p.books[key]['book']['state']='closed'
                else:
                    for key in p.health:
                        if key[0]=='kalshi':p.health[key]['state']='resynchronization_required'
                s=p.snapshot(now=p.last,mode='current',state='current')
                self.assertFalse(s['source_correspondence_comparisons'])
                self.assertTrue(s['aggregate_comparisons'])

    def test_us_only_uses_native_open_enum_and_shared_short_purchase_conversion(self):
        initial,_,_=fixture()
        received=next(v['book']['raw']['received_at'] for k,v in initial.books.items() if k[0]=='polymarket_us')
        p,_,_=fixture(receipt_at=received)
        for key in list(p.books):
            if key[0]=='kalshi':p.books.pop(key)
        s=p.snapshot(); mixed=s['source_correspondence_comparisons']
        self.assertEqual(len(mixed),4,s['cross_source_mapping'])
        self.assertEqual({l['venue'] for r in mixed for l in r['legs']},{'polymarket_us','novig','prophetx'})
        raw_book=next(v['book'] for k,v in p.books.items() if k[0]=='polymarket_us')
        short_seen=False
        for r in mixed:
            native=next(l for l in r['legs'] if l['venue']=='polymarket_us')
            self.assertTrue(native['levels'])
            if native['native_outcome']['native_direction']=='short':
                short_seen=True
                self.assertEqual(Decimal(native['ask']),1-max(Decimal(x['price']['value']) for x in raw_book['outcomes'][0]['bids']['levels']))
            self.assertFalse(r['timing']['synchronized'])
        self.assertTrue(short_seen)

    def test_two_provider_event_ids_with_same_geometry_are_ambiguous(self):
        p, aggregate, _ = fixture()
        duplicate = deepcopy(aggregate)
        duplicate['event_id']='SECOND-ISOLATED-EVENT'
        records=duplicate['records']
        # Bind a genuinely distinct provider event, rather than alter a mapped digest.
        duplicate['records']=bind([dict(r['original'],source_event_id=duplicate['event_id']) for r in records])
        p.apply(duplicate)
        s=p.snapshot()
        self.assertFalse(s['source_correspondence_comparisons'])
        self.assertIn('Ambiguous source-specific',str(s['cross_source_mapping']))

    def test_skew_unknown_canonical_or_changed_schedule_keeps_provider_local_rows(self):
        for kwargs in (dict(skew=6), dict(home='ISOLATED UNMAPPED PARTICIPANT'),
                       dict(schedule='2026-10-03T00:00:00Z')):
            with self.subTest(kwargs=kwargs):
                p, _, _ = fixture(**kwargs); s = p.snapshot()
                self.assertFalse(s['source_correspondence_comparisons'])
                self.assertTrue(s['aggregate_comparisons'])
                self.assertTrue(s['cross_source_mapping']['exclusions'])

    def test_clock_only_change_updates_ages_and_invalidates_pregame(self):
        p, _, _ = fixture(); initial = p.snapshot(); at = p.last
        later = p.snapshot(now=(time(at) + timedelta(seconds=20)).isoformat(), mode='current', state='current')
        self.assertTrue(later['source_correspondence_comparisons'])
        self.assertTrue(all(not r['timing']['receipt_limits_pass'] for r in later['source_correspondence_comparisons']))
        self.assertTrue(all(Decimal(l['age_seconds']) >= 20 for r in later['source_correspondence_comparisons'] for l in r['legs']))
        kickoff = initial['games'][0]['scheduled_start']
        closed = p.snapshot(now=kickoff, mode='current', state='current')
        self.assertFalse(closed['source_correspondence_comparisons'])
        self.assertIn('invalid after scheduled start', str(closed['cross_source_mapping']))

    def test_mixed_watch_observations_are_excluded_and_bind_revision(self):
        p, _, _ = fixture(); s = p.snapshot()
        for metric in ('raw_gap', 'arb_return', 'ev'):
            values = observations(s, watch(metric))
            mixed = [r for r in values if r.get('basis', {}).get('source_correspondence')]
            self.assertEqual(len(mixed), 4)
            self.assertTrue(all(not r['qualifies'] and r['size'] is None for r in mixed))
            self.assertTrue(all('source_correspondence' in r['basis'] for r in mixed))

    def test_ordinary_journal_reopening_preserves_mixed_binding_and_outputs(self):
        from app.collection.transport_session import ObservationJournal
        from app.dashboard.session_history import load
        p, aggregate, config = fixture(); source = native_prefix(); source[0] = deepcopy(source[0])
        source[0]['spec'] = deepcopy(p.spec)
        for row in source:
            if row['type'] == 'market_selected':
                row['market']['raw']['kind'] = 'synthetic'
            elif row['type'] == 'prediction_book':
                row['book']['raw']['kind'] = 'synthetic'
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / p.sid; folder.mkdir(); journal = ObservationJournal(folder / (p.sid + '.jsonl'))
            for row in source:
                journal.save(row)
            journal.save(aggregate); journal.close()
            expected = p.snapshot(); reopened = load(folder)
            self.assertEqual(comparisons(expected, {}), comparisons(reopened, {}))
            self.assertEqual(expected['cross_source_mapping'], reopened['cross_source_mapping'])
            self.assertEqual(load(folder), reopened)

    def test_validated_line_predicates_preserve_home_orientation_and_strict_equality(self):
        from app.reference.source_correspondence import _aggregate_predicate
        record = dict(identity={'family':'spread','period':'first_half'},
            original={'point':'-3','outcome':'Home'}, participant='NFL:BUF')
        roles = dict(home_team='NFL:BUF', away_team='NFL:DET')
        review = dict(normalized_event=dict(home='NFL:BUF', away='NFL:DET'))
        self.assertEqual(_aggregate_predicate(record, roles, review), ('home_margin','NFL:BUF','NFL:DET','3','gt'))
        record['participant'] = 'NFL:DET'; record['original']['point'] = '3'
        self.assertEqual(_aggregate_predicate(record, roles, review), ('home_margin','NFL:BUF','NFL:DET','3','lt'))
        with self.assertRaisesRegex(ValueError, 'home/away'):
            _aggregate_predicate(record, dict(home_team='NFL:DET',away_team='NFL:BUF'), review)
