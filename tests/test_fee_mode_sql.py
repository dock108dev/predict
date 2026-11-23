"""Default zero-fee calculations and durable opt-in invalidation in disposable SQL."""

from copy import deepcopy
from fractions import Fraction as F
from unittest import skipUnless
from unittest.mock import patch

from app.comparison import fee_mode
from app.fees import pricing
from app.storage import current_pregame as board
from app.storage.store import stamp
from tests.latest_board_fixture import SOCKET
from tests.pregame_fixture import AT, PregameFixture, page
from tests.test_fee_pricing import rule


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class FeeModeSQL(PregameFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        routes = patch.object(board, 'configured_routes', return_value={venue:'sportsgameodds'
            for venue in ('kalshi', 'polymarket_us', 'novig', 'prophetx')})
        routes.start()
        self.addCleanup(routes.stop)
        with self.connect() as db:
            db.execute('DELETE FROM public.public_fee_schedule WHERE venue=%s', (fee_mode.KEY,))

    def process(self, db):
        with patch('app.storage.current_rows.utc', return_value=AT):
            return board.process(db, at=stamp(AT))

    def source_data(self):
        data = page()
        for odd in data['data'][0]['odds'].values():
            for book in ('kalshi', 'polymarket', 'novig'):
                odd['byBookmaker'][book] = deepcopy(odd['byBookmaker']['prophetx'])
        return data

    async def test_missing_flag_defaults_off_and_missing_fee_evidence_does_not_block_math(self):
        with self.connect() as db:
            self.assertFalse(fee_mode.read(db)['enabled'])
            self.ingest(db, self.source_data())
            with patch.object(board, 'reviews', side_effect=AssertionError('fee_reviews_read_while_off')), \
                    patch.object(board.product_schedules, 'read_all', side_effect=AssertionError('fee_products_read_while_off')), \
                    patch.object(board, 'account_identity', side_effect=AssertionError('account_read_while_off')):
                outcome = self.process(db)
            self.assertTrue(outcome)
            rows = db.execute('SELECT venue,payload FROM current_pregame_calculation WHERE payload IS NOT NULL').fetchall()
            self.assertTrue(rows, dict(outcome=outcome, reasons=list(db.execute('SELECT venue,reason FROM current_pregame_calculation'))))
            self.assertTrue(any(row['venue']=='polymarket_us' for row in rows))
            for row in rows:
                self.assertFalse(row['payload']['fee_mode']['enabled'])
                self.assertEqual(row['payload']['fee']['entry_usd'], '0')
                self.assertEqual(row['payload']['fee']['reserve_usd'], '0')
                self.assertIsNotNone(row['payload']['raw']['net_ev'])

    async def test_toggle_rebuilds_current_math_preserves_source_inputs_and_keeps_fee_rules(self):
        with self.connect() as db:
            pricing.write(db, 'kalshi', [rule('kalshi')])
            existing_rule = deepcopy(pricing.read(db)['kalshi'])
            self.ingest(db, self.source_data())
            self.process(db)
            original = db.execute("SELECT payload FROM current_pregame_calculation WHERE venue='kalshi' AND payload IS NOT NULL ORDER BY contract_id LIMIT 1").fetchone()['payload']
            quotes = list(db.execute('SELECT * FROM current_offer_storage ORDER BY contract_id'))
            old_revision = db.execute('SELECT revision FROM current_pregame_revision WHERE singleton').fetchone()['revision']
            enabled = fee_mode.set_enabled(db, True)
            self.assertTrue(enabled['enabled'])
            self.assertGreater(enabled['queued_events'], 0)
            self.assertGreater(db.execute('SELECT revision FROM current_pregame_revision WHERE singleton').fetchone()['revision'], old_revision)
            self.assertTrue(fee_mode.read(db)['enabled'])
            self.process(db)
            included = db.execute('SELECT payload FROM current_pregame_calculation WHERE contract_id=%s', (original['id'],)).fetchone()['payload']
            self.assertTrue(included['fee_mode']['enabled'])
            self.assertGreater(F(included['fee']['entry_usd']), 0)
            self.assertLess(F(included['raw']['net_ev']), F(original['raw']['net_ev']))
            self.assertEqual(included['posted'], original['posted'])
            self.assertEqual(included['times'], original['times'])
            disabled = fee_mode.set_enabled(db, False)
            self.assertFalse(disabled['enabled'])
            self.assertNotEqual(disabled['revision'], original['fee_mode']['revision'])
            self.process(db)
            restored = db.execute('SELECT payload FROM current_pregame_calculation WHERE contract_id=%s', (original['id'],)).fetchone()['payload']
            self.assertEqual(restored['raw'], original['raw'])
            self.assertNotEqual(restored['input_revision'], original['input_revision'])
            self.assertEqual(quotes, list(db.execute('SELECT * FROM current_offer_storage ORDER BY contract_id')))
            self.assertEqual(existing_rule, pricing.read(db)['kalshi'])
            self.assertEqual(fee_mode.set_enabled(db, False)['queued_events'], 0)
