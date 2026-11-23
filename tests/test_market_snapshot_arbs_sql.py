"""Arbitrage uses frozen scope membership even when working tables differ."""
from dataclasses import replace
from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from app.comparison import fee_mode
from app.research.ev_movement import build_snapshot
from app.storage import acquisition_snapshot as acquisition
from app.storage.market_snapshot_arbs import read
from app.storage.store import stamp
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.pregame_fixture import AT, page, parse
from tests.test_market_board_sql import SCOPE


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class SnapshotArbsSQL(LatestBoardFixture):
    async def asyncSetUp(self):
        with self.connect() as db:
            db.execute('TRUNCATE public.market_pull CASCADE')

    def capture(self, db, data=None):
        data = data or page()
        odds = list(data['data'][0]['odds'].values())
        for odd in odds:
            odd['byBookmaker']['novig'] = dict(odd['byBookmaker']['prophetx'], odds='+120')
        parsed = parse(data)
        params = dict(SCOPE,eventIDs=parsed.events[0]['event_id'])
        received_books = {book for odd in odds for book in odd['byBookmaker']}
        params['bookmakerID'] = ','.join(sorted(set(params['bookmakerID'].split(',')) | received_books))
        pull = acquisition.start(db, params, at=stamp(AT))
        parsed = replace(parsed,pull_id=pull,attempt_id='fixture-child',received_at=AT,request_scope=params)
        mode = fee_mode.state(False)
        context = SimpleNamespace(fee_mode=mode,
            price_routes={venue:'sportsgameodds' for venue in ('kalshi','polymarket_us','novig','prophetx')},
            fee=lambda record, at:fee_mode.zero_fee(record, mode))
        with patch('app.storage.current_pregame.CalculationContext',return_value=context):
            snapshot = build_snapshot(db,parsed,request_scope=params,dispatch_at=AT,known_at=AT)
        acquisition.publish(db,parsed,snapshot)
        return pull,params

    async def test_frozen_market_pair_has_same_pull_and_explicit_book_benchmark(self):
        with self.connect() as db:
            pull,_ = self.capture(db)
            result = read(db,{},at=stamp(AT))
            self.assertGreater(result['total'],0)
            self.assertEqual(result['provider_requests'],0)
            self.assertTrue(all(pair['pull_id']==pull for pair in result['rows']))
            self.assertTrue(all(pair['acquisition']['pull_id']==pull for pair in result['rows']))
            for pair in result['rows']:
                self.assertTrue(pair['legs'][0]['selection'])
                self.assertTrue(pair['legs'][1]['selection'])
                if pair['category']=='market_book':
                    self.assertFalse(pair['executable_legs'])
                    self.assertEqual(pair['category_label'],'Sportsbook reference comparison')
            markets = read(db,{'category':'market_market'},at=stamp(AT))
            self.assertGreater(markets['total'],0)
            self.assertTrue(all(pair['fee_mode']['enabled'] is False for pair in markets['rows']))

    async def test_new_failed_scope_suppresses_pairs_without_deleting_history(self):
        with self.connect() as db:
            older,params = self.capture(db)
            newer = acquisition.start(db,params,at=stamp(AT))
            acquisition.finish(db,newer,'failed',details={'reason':'fixture_failure'})
            self.assertEqual(read(db,{},at=stamp(AT))['total'],0)
            self.assertEqual(db.execute("SELECT count(*) n FROM public.market_pull_scope WHERE pull_id=%s AND snapshot IS NOT NULL",(older,)).fetchone()['n'],3)

    async def test_reference_index_skips_other_lines_but_retains_spread_polarity_guard(self):
        from app.storage.pregame_arbs import book_entry

        with self.connect() as db:
            pull,_ = self.capture(db)
            baseline = read(db,{},at=stamp(AT))
            snapshot = acquisition.read_snapshot(db,pull)
            template = next(reference for reference in snapshot['references']
                if reference['facts']['market']=='spread' and reference['facts']['side']=='home')
            for line in ('100.5','101.5','102.5'):
                unrelated = deepcopy(template)
                unrelated['facts'].update(line=line,fixture_unrelated_line=True)
                snapshot['references'].append(unrelated)
            wrong = deepcopy(template)
            wrong['facts'].update(line=str(-Fraction(wrong['facts']['line'])),
                venue='betmgm',price_american='+1000',fixture_wrong_polarity=True)
            snapshot['references'].append(wrong)
            with patch('app.storage.acquisition_snapshot.read_snapshot',return_value=snapshot), \
                    patch('app.storage.pregame_arbs.book_entry',wraps=book_entry) as normalize:
                indexed = read(db,{},at=stamp(AT))
            self.assertEqual(indexed,baseline)
            quotes = [call.args[0] for call in normalize.call_args_list]
            self.assertTrue(any(quote.get('fixture_wrong_polarity') for quote in quotes))
            self.assertFalse(any(quote.get('fixture_unrelated_line') for quote in quotes))
            self.assertFalse(any(leg['venue']=='betmgm' for pair in indexed['rows'] for leg in pair['legs']))
