"""Atomic SGO page admission against a disposable PostgreSQL cluster."""
import asyncio
from copy import deepcopy
from threading import Event
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from psycopg.types.json import Jsonb

from app.collection.current_database import DatabaseIngressSink
from app.collection.current_policy import DEFAULT
from app.collection.sportsgameodds_current_rows import current_rows
from app.storage.sportsgameodds_reference import prepare_page, prepare_frames, upsert_rows, upsert_frames
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.test_sportsgameodds_adapter import parse, response
from tests.test_ev09_n01 import AT


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class SportsGameOddsAtomicIngress(LatestBoardFixture):
    async def test_page_atomicity_unchanged_rows_and_controls(self):
        raw = response()
        book = raw['data'][0]['odds']['points-home-game-sp-home']['byBookmaker'].pop('book')
        raw['data'][0]['odds']['points-home-game-sp-home']['byBookmaker']['novig'] = book
        page = parse(raw)
        records, _ = current_rows(page, page.receipt_sha256)
        references = prepare_page(page)
        self.assertTrue(records and references)
        row = dict(type='current_aggregate_records',source='sportsgameodds',sport='NBA',
                   records=records,sgo_reference_rows=references,sgo_event_frames=prepare_frames(page,references),receipt_sha256=page.receipt_sha256,
                   event_scopes={page.events[0]['event_id']:page.events[0]['league']},
                   complete_venues=[],received_at=page.events[0]['received_at'])
        sink = DatabaseIngressSink(SimpleNamespace(provider=self.service), DEFAULT)
        from app.collection.current_database import validate_sgo_page
        validate_sgo_page(row)
        mismatch = deepcopy(row)
        mismatch['sgo_reference_rows'][0]['facts']['receipt_sha256'] = 'f'*64
        with self.assertRaises(ValueError): validate_sgo_page(mismatch)
        mismatch = deepcopy(row)
        mismatch['sgo_event_frames'][0]['facts']['members'] = []
        with self.assertRaises(ValueError): validate_sgo_page(mismatch)
        mismatch = deepcopy(row)
        mismatch['records'][0]['quote']['source']['native_event_id'] = 'other'
        with self.assertRaises(ValueError): validate_sgo_page(mismatch)
        with self.connect() as db:
            db.execute('CREATE TABLE protected_test_hold (amount integer)')
            db.execute('INSERT INTO protected_test_hold VALUES (34)')
            before = db.execute('SELECT count(*) n FROM current_offer').fetchone()['n']
        def fail_after_frame(db, frames):
            upsert_frames(db, frames)
            raise RuntimeError('fixture failure after frame insert')
        with patch('app.collection.current_database.connect',side_effect=self.connect), \
             patch('app.collection.current_database.utc',return_value=AT), \
             patch('app.storage.sportsgameodds_reference.upsert_frames',side_effect=fail_after_frame):
            with self.assertRaises(RuntimeError):
                sink.prepare(row,self.service.states,Event())
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_reference').fetchone()['n'], 0)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_event_frame').fetchone()['n'], 0)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_offer').fetchone()['n'], before)
        with patch('app.collection.current_database.connect',side_effect=self.connect), \
             patch('app.collection.current_database.utc',return_value=AT):
            sink.prepare(row,self.service.states,Event())
            with self.connect() as db:
                first = db.execute('SELECT id,xmin::text AS version FROM current_sgo_reference').fetchall()
                self.assertEqual(db.execute("SELECT state FROM current_source_status WHERE venue='sportsgameodds'").fetchone()['state']['state'], 'available')
                native_before = db.execute("SELECT venue,state FROM current_source_status WHERE venue IN ('kalshi','polymarket_us') ORDER BY venue").fetchall()
                offers = db.execute('SELECT count(*) n FROM current_offer').fetchone()['n']
                self.assertGreater(offers,before)
                self.assertEqual(len(first),len(references))
                self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_event_frame').fetchone()['n'],1)
            sink.prepare(row,self.service.states,Event())
            with self.connect() as db:
                self.assertEqual(db.execute('SELECT id,xmin::text AS version FROM current_sgo_reference').fetchall(),first)
                self.assertEqual(db.execute('SELECT count(*) n FROM current_offer').fetchone()['n'],offers)
                self.assertEqual(db.execute('SELECT amount FROM protected_test_hold').fetchone()['amount'],34)
                db.execute('UPDATE data_runtime SET paused_sources=%s WHERE singleton=true',(Jsonb(['sportsgameodds']),))
            with self.assertRaises(asyncio.CancelledError):
                sink.prepare(row,self.service.states,Event())
            stopped=dict(type='sgo_status',source='sportsgameodds',state='stopped',reason_code='sgo_paused',reason='Paused')
            sink.prepare(stopped,self.service.states,Event())
            with self.connect() as db:
                self.assertEqual(db.execute("SELECT state FROM current_source_status WHERE venue='sportsgameodds'").fetchone()['state']['state'], 'stopped')
                self.assertEqual(db.execute("SELECT venue,state FROM current_source_status WHERE venue IN ('kalshi','polymarket_us') ORDER BY venue").fetchall(),native_before)
                db.execute('UPDATE data_runtime SET paused_sources=%s,global_stopped=true WHERE singleton=true',(Jsonb([]),))
            with self.assertRaises(asyncio.CancelledError):
                sink.prepare(row,self.service.states,Event())
            revoked=Event();revoked.set()
            with self.assertRaises(asyncio.CancelledError):
                sink.prepare(row,self.service.states,revoked)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT id,xmin::text AS version FROM current_sgo_reference').fetchall(),first)
            self.assertEqual(db.execute('SELECT amount FROM protected_test_hold').fetchone()['amount'],34)

    async def test_switch_marks_old_aggregate_historical_but_preserves_native(self):
        from copy import deepcopy
        from app.storage import ordinary_publication as live
        from app.collection.runtime_status import read_runtime
        with self.connect() as db, \
             patch('app.collection.current_policy.load', return_value=DEFAULT):
            live.turn(db)
            from app.storage import comparison_snapshot as snapshots
            head = live.status(db)
            result = snapshots.unpack(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s', (head['result_id'],)).fetchone()['result'],db=db)
            current = live.dependencies(db)
            owner = read_runtime(db)
            states = {v: {'state':'available'} for v in ('novig','prophetx','kalshi','polymarket_us','pinnacle','sportsgameodds')}
            policy = live.policy_identity()
            old = live.project(result,current,owner,states,at=self.at,policy=policy,epoch=result['publication']['epoch'])
            changed = deepcopy(owner)
            changed['config']['aggregate_provider'] = 'sportsgameodds'
            switched = live.project(result,current,changed,states,at=self.at,policy=policy,epoch=result['publication']['epoch'])
            before = {r['id']:r for r in old['rows']}
            aggregate = [r for r in switched['rows'] if r.get('source',{}).get('provider') == 'the_odds_api']
            native = [r for r in switched['rows'] if r.get('source',{}).get('provider') in ('kalshi','polymarket_us')]
            self.assertTrue(aggregate and native)
            self.assertTrue(all(not r['price_current'] and 'aggregate_provider_replaced' in r['price_reasons'] for r in aggregate))
            self.assertTrue(all(r['price_current'] == before[r['id']]['price_current'] for r in native))
            self.assertTrue(all(r['original'] == before[r['id']]['original'] and r['current_authority']['references'] == before[r['id']]['current_authority']['references'] for r in switched['rows']))
            from app.storage import latest_board, raw_prices
            context = latest_board.read_context(db, at=self.at.isoformat(), owner=changed)
            latest_records = [r for group in context.prepared['groups'] for r in group]
            providers = {r['quote']['source']['provider'] for r in latest_records}
            self.assertNotIn('the_odds_api', providers)
            self.assertTrue({'kalshi','polymarket_us'} & providers)
            self.assertEqual(raw_prices.status({'kind':'featured','venue':'novig'}, changed), 'last_known')
            self.assertTrue(any(r['quote']['source']['provider']=='the_odds_api' for r in self.records))
            # Native offers remain available; a legacy reference may no longer
            # make a financial result current after changing providers.
            for row in native:
                refs = row['current_authority']['references']
                if refs and any(r.get('provider','the_odds_api') == 'the_odds_api' for r in refs):
                    self.assertFalse((row.get('reference_calculation') or {}).get('available',False))
