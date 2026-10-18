"""SC06 disposable PostgreSQL smoke for the real authored financial workload."""
from tempfile import TemporaryDirectory
from pathlib import Path
from datetime import timedelta
from unittest import IsolatedAsyncioTestCase, TestCase

from app.storage.current_rows import prepare, CurrentRowStore
from app.storage.scanner_publication import transaction
from app.dashboard.scanner_api import Scanner
from tests import test_sc02_sql as sql
from tests.sc06_fixture import records, native_books, AuthoredAdapters, Clock
from tests.test_sc03_finance import AT


class DepthUnits(TestCase):
    def test_authored_identity_does_not_transplant_retained_confirmation(self):
        from copy import deepcopy
        from tests.test_d03_current_rows import fixture_records
        authored = records(1)[0]
        self.assertNotIn('book_confirmation', authored['quote'])
        self.assertEqual(authored['quote']['times']['source_at'], AT.isoformat())
        prepare(authored)
        retained = next(row for row in fixture_records()
                        if row['quote']['venue'] == authored['quote']['venue'])
        authored['quote']['book_confirmation'] = deepcopy(retained['quote']['book_confirmation'])
        with self.assertRaisesRegex(ValueError, 'Confirmation market mismatch'):
            prepare(authored)

    def test_stake_depth_keeps_decimal_odds_and_native_bounds(self):
        stake=records(2)[2];self.assertGreater(float(stake['quote']['depth'][0]['price']),1)
        self.assertEqual(prepare(stake)['depth'],stake['quote']['depth'])
        native=records(1)[0];native['quote']['depth'][0]['price']='1.01'
        with self.assertRaisesRegex(ValueError,'depth_value'):prepare(native)
        for value in ('NaN','Infinity','-1'):
            stake['quote']['depth'][0]['price']=value
            with self.assertRaises((ValueError,ArithmeticError)):prepare(stake)


class FullFinanceSQL(IsolatedAsyncioTestCase):
    connect=classmethod(sql.SQL.connect.__func__)
    @classmethod
    def setUpClass(cls):
        if not sql.SOCKET:raise RuntimeError('Verified disposable SC06 PostgreSQL required; no skip qualifies SQL')
        sql.SQL.setUpClass.__func__(cls)
    tearDownClass=classmethod(sql.SQL.tearDownClass.__func__)
    provider=sql.SQL.provider

    async def test_sql_current_rows_real_finance_three_varied_events(self):
        clock=Clock();rows=records(3,at=clock());seen=[]
        from app.storage.scanner_publication import subscribe
        close=subscribe(seen.append)
        with TemporaryDirectory(prefix='sc06-summary-') as directory:
            worker=Scanner(self.provider(),connector=self.connect,clock=clock,summary_path=Path(directory)/'summary')
            try:
                with self.connect() as db:
                    db.execute('TRUNCATE current_event CASCADE')
                    with transaction(db):
                        store=CurrentRowStore(db);store.upsert_records(rows);store.replace_native_books(native_books(rows))
                self.assertTrue(seen)
                with AuthoredAdapters():
                    worker.once()
                    frame=worker.projection.frame
                    self.assertEqual(len(frame['instruments']),6,frame['failed_occurrences'])
                    self.assertEqual(len(frame['pairs']),3,[(i['venue'],i['occurrence_id'],i['direction'],i['overtime']) for i in frame['instruments']])
                    self.assertTrue(all(p['input_check']['state']=='ready' for p in frame['pairs']),[(i['checks']) for i in frame['instruments']])
                    self.assertTrue(all(worker.projection.inputs[i['id']]['quote'].get('depth') for i in frame['instruments']))
                    while worker.projection.pending:worker.once()
                self.assertEqual(worker.projection.evaluations,3,worker.projection.errors)
                self.assertFalse(worker.projection.errors)
                self.assertGreaterEqual(len(worker.projection.rows),2)
                self.assertEqual(worker.projection.view()['provider_requests'],0)
                from app.comparison.scanner_tickets import Tickets, selector
                from app.comparison.scanner_destinations import Destinations
                from tests.test_sc03_tickets import catalog, CLIENT
                native_row=next(r for r in worker.projection.rows.values() if set(r['venues'])=={'kalshi','polymarket_us'})
                def fresh():
                    frame,inputs,_,_=worker._capture()
                    return frame,inputs
                tickets=Tickets(worker.projection,fresh=fresh,allow_authored=True,clock=clock,
                    destinations=Destinations(catalog(worker.projection.frame['instruments'])))
                try:
                    with AuthoredAdapters():
                        ticket=await tickets.command(dict(operation='select',client_id=CLIENT,sequence=1,selection=selector(worker.projection,native_row)))
                    self.assertTrue(ticket['ready_for_manual_action'],ticket)
                    self.assertIsNotNone(ticket['selected_frame']['causal']['sql_post_commit_observation'])
                    self.assertGreater(__import__('fractions').Fraction(ticket['selected_frame']['result']['funding']['net_upfront_fee_usd']),0)
                finally:await tickets.close()

                from app.storage.scanner_readiness import capture
                with AuthoredAdapters():
                    with self.connect() as db:
                        expired,_,_=capture(db,config=worker.provider.config,authority=worker.provider.config['authority'],at=(AT+timedelta(seconds=60)).isoformat(),source_status=worker.provider.states)
                        native=[i for i in expired['instruments'] if i['venue'] in ('kalshi','polymarket_us')]
                        self.assertTrue(native)
                        self.assertTrue(all(i['checks']['execution']['state']!='ready' for i in native))
                        db.execute('DELETE FROM current_depth')
                        no_depth,_,_=capture(db,config=worker.provider.config,authority=worker.provider.config['authority'],at=clock(),source_status=worker.provider.states)
                        ordinary=[i for i in no_depth['instruments'] if i['venue'] in ('novig','prophetx')]
                        self.assertTrue(ordinary)
                        self.assertTrue(all('observed_depth_missing' in i['checks']['execution']['reason_codes'] for i in ordinary))
            finally:await worker.close();close()
