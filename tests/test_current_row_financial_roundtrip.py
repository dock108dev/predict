"""Authentic retained facts through actual SQL, selected depth and financial owners."""
from unittest import TestCase
from uuid import uuid4
from psycopg import sql
from app.storage.store import connect, Store
from app.storage.current_rows import CurrentRowStore
from app.storage.current_games import GameStore
from app.storage.comparison_board import ReadContext, discover, calculate_current
from app.dashboard.comparison_board import entries
from app.comparison.estimated_policy import DEFAULT_POLICY
from tests.test_ev09_n01 import retained, envelopes, AT, SELECTED


def native_key(quote):
    return tuple([quote['venue'], *[quote['source'][k] for k in
                 ('native_event_id', 'native_market_id', 'native_outcome_id', 'native_side')]])


class CurrentRowFinancialRoundtrip(TestCase):
    def test_exact_authentic_single_pair_and_depth_survive_sql(self):
        name = 'prediction_arb_d03_roundtrip_' + uuid4().hex[:10]
        with connect() as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            with connect(name) as db:
                Store(db).migrate()
                original_bundle, expected = retained()
                rows = original_bundle['records']
                members = {tuple(m) for m in original_bundle['members']}
                books = [o['book'] for e in envelopes()
                         if e['record']['kind'] == 'admitted_books'
                         for o in e['record']['value']['observations']
                         if (e['record']['source'], o['book']['raw']['ref']['event_id']) in members]
                store = CurrentRowStore(db)
                with db.transaction():
                    store.upsert_records(rows)
                    store.replace_native_books(books)
                with db.transaction():
                    db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    context = ReadContext(GameStore(db), at=AT)
                    bundle = discover(context.store, context=context, selected=SELECTED)[0]
                actual = calculate_current(bundle, DEFAULT_POLICY, context=context)
                before = {native_key(q): q for _, _, q in entries(expected)}
                after = {native_key(q): q for _, _, q in entries(actual['state'])}
                self.assertEqual(set(before), set(after))
                for key, q in before.items():
                    self.assertEqual(q.get('depth'), after[key].get('depth'), key)
                    self.assertEqual(q['original'], after[key]['original'], key)
                    self.assertEqual(q['times']['source_at'], after[key]['times']['source_at'], key)
                    for field in ('financial_metrics', 'funding'):
                        self.assertEqual(q['calculations']['funded_estimate'].get(field),
                                         after[key]['calculations']['funded_estimate'].get(field), (key, field))
                def pairs(state):
                    quotes = {q['id']: native_key(q) for _, _, q in entries(state)}
                    scopes = {q['id']: (g['market'], g['period'], g['line'])
                              for _, g, q in entries(state)}
                    result = {}
                    for event in state['events']:
                        for p in event['funded_pairs']:
                            funding = dict(p['funding'], legs=[dict(leg, quote_id=quotes[leg['quote_id']],
                                           group_id=scopes[leg['quote_id']])
                                           for leg in p['funding']['legs']])
                            result[tuple(sorted(quotes[l['quote_id']] for l in p['legs']))] = (
                                p['financial_metrics'], funding)
                    return result
                before_pairs, after_pairs = pairs(expected), pairs(actual['state'])
                self.assertEqual(set(before_pairs), set(after_pairs))
                for key, (metrics, funding) in before_pairs.items():
                    actual_metrics, actual_funding = after_pairs[key]
                    self.assertEqual(metrics, actual_metrics, key)
                    # SQL source ordering does not change native leg identity.
                    funding = dict(funding, legs=sorted(funding['legs'], key=lambda leg: leg['quote_id']))
                    actual_funding = dict(actual_funding, legs=sorted(actual_funding['legs'], key=lambda leg: leg['quote_id']))
                    for field in funding:
                        if field == 'legs':
                            for prior_leg, current_leg in zip(funding[field], actual_funding[field], strict=True):
                                for component in prior_leg:
                                    self.assertEqual(prior_leg[component], current_leg[component], (key, component))
                            continue
                        self.assertEqual(funding[field], actual_funding[field], (key, field))
                for table in ('current_envelope', 'current_game_snapshot', 'current_game_result',
                              'current_calculation_attempt'):
                    self.assertEqual(db.execute(sql.SQL('SELECT count(*) n FROM {}').format(
                        sql.Identifier(table))).fetchone()['n'], 0)
        finally:
            with connect() as admin:
                admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
