"""Atomic SGO page admission against a disposable PostgreSQL cluster."""
import asyncio
import json
from copy import deepcopy
from threading import Event
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from psycopg import sql
from psycopg.types.json import Jsonb

from app.collection.current_database import DatabaseIngressSink
from app.collection.current_policy import DEFAULT
from app.collection.sportsgameodds_adapter import parse_page
from app.collection.sportsgameodds_current_rows import current_rows
from app.storage.sportsgameodds_reference import prepare_page, prepare_frames, upsert_rows, upsert_frames
from app.storage.current_rows import prepare
from app.storage.store import Store
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.test_sportsgameodds_adapter import parse, response
from tests.test_ev09_n01 import AT


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class SportsGameOddsAtomicIngress(LatestBoardFixture):
    async def test_upgrade_links_exact_legacy_value_and_preserves_each_receipt(self):
        from uuid import uuid4

        name = 'prediction_arb_sgo_upgrade_' + uuid4().hex[:8]
        raw = response()
        odd = raw['data'][0]['odds']['points-home-game-sp-home']
        odd['byBookmaker']['novig'] = odd['byBookmaker'].pop('book')
        page = parse(raw)
        reference, = prepare_page(page)
        records, _ = current_rows(page, page.receipt_sha256)
        record, = records
        record['quote']['times']['received_at'] = '2026-11-10T20:00:05Z'
        record['quote']['provenance']['sha256'] = 'a' * 64
        original = prepare(record)
        with self.connect('prediction_arb') as control:
            control.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            try:
                with self.connect(name) as db:
                    Store(db).migrate(through='077_sgo_live_ev_delivery.sql')
                    db.execute('INSERT INTO current_sgo_reference VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                        (*[reference[k] for k in ('id','event_id','bookmaker_id','source_order','received_order','expires_at','revision')],
                         Jsonb(reference['facts'])))
                    db.execute('INSERT INTO current_event VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                        (original['event_id'],'sportsgameodds',record['event']['id'],record['event']['competition'],
                         record['event']['scheduled_start'],original['expires_order'],Jsonb(original['event']),original['event_revision']))
                    source = original['source']
                    db.execute('INSERT INTO current_contract VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                        (original['contract_id'],original['event_id'],original['venue'],source['native_market_id'],
                         source['native_outcome_id'],source['native_side'],Jsonb(original['contract']),original['contract_revision']))
                    q = original['quote']
                    db.execute('INSERT INTO current_offer VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                        (original['contract_id'],q['original']['value'],q['original']['units'],q['original']['quantity_units'],
                         original['source_at'],original['source_order'],original['received_at'],
                         original['received_order'],Jsonb(q),original['revision']))
                    before = db.execute('SELECT * FROM current_offer').fetchone()
                    refs = db.execute('SELECT * FROM current_sgo_reference').fetchall()
                    Store(db).migrate(through='078_sgo_quote_authority.sql')
                    assert db.execute('SELECT * FROM current_offer').fetchone() == before
                    assert db.execute('SELECT * FROM current_sgo_reference').fetchall() == refs
                    physical = db.execute('SELECT price_value,facts,sgo_quote_id,sgo_quote_revision FROM current_offer_storage').fetchone()
                    assert physical['price_value'] is None and 'value' not in physical['facts']['original']
                    assert (physical['sgo_quote_id'],physical['sgo_quote_revision']) == (reference['id'],reference['revision'])
                    assert before['facts']['provenance']['sha256'] != refs[0]['facts']['receipt_sha256']
            finally:
                control.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))

    async def test_live_ev_write_clock_requires_fresh_prices_at_seal(self):
        from datetime import timedelta

        from app.storage.delivery_clocks import published, recent, sgo_admitted

        with self.connect() as db, db.transaction(force_rollback=True):
            at = db.execute('SELECT clock_timestamp() at').fetchone()['at']
            received = at.isoformat()
            sgo_admitted(db, {'NHL', 'NBA'}, received)
            published(db, [('sportsgameodds', league, received) for league in ('NHL', 'NBA')],
                      live_sportsbook=[('NHL', received, (at + timedelta(minutes=1)).isoformat()),
                                       ('NBA', received, (at - timedelta(seconds=1)).isoformat())])
            rows = {row['league']: row for row in recent(db) if row['received_at'] == received}
            assert rows['NBA']['first_publication_write_at']
            assert rows['NBA']['first_live_sportsbook_write_at'] is None
            assert rows['NHL']['first_live_sportsbook_write_at']

    async def test_history_rotates_oldest_at_capacity(self):
        from app.storage.sportsgameodds_reference import archive_revisions
        from app.storage.store import encoded
        def row(n):
            return dict(id=str(n), event_id='rotation-fixture', revision=str(n), facts={'n': n})
        with self.connect() as db, patch('app.storage.sportsgameodds_reference.HISTORY_BYTES', 2 * len(encoded({'n': 1}))):
            with db.transaction():
                archive_revisions(db, 'reference', [row(1)])
                archive_revisions(db, 'reference', [row(2)])
                archive_revisions(db, 'reference', [row(3)])
            self.assertEqual([r['identity'] for r in db.execute(
                "SELECT identity FROM current_sgo_history WHERE event_id='rotation-fixture' ORDER BY identity").fetchall()], ['2', '3'])
            self.assertEqual(db.execute('SELECT evicted_capacity FROM current_sgo_history_state').fetchone()['evicted_capacity'], 1)
            with patch('app.collection.current_storage_policy.sql_usage', return_value=2 * 1024**3):
                with db.transaction():
                    archive_revisions(db, 'reference', [row(4)])
            self.assertEqual(db.execute("SELECT count(*) n FROM current_sgo_history WHERE event_id='rotation-fixture'").fetchone()['n'], 2)
            self.assertEqual(db.execute('SELECT skipped_runway FROM current_sgo_history_state').fetchone()['skipped_runway'], 1)
            db.execute("DELETE FROM current_sgo_history WHERE event_id='rotation-fixture'")

    async def test_bounded_history_records_revisions_and_prunes_only_history(self):
        import json
        from datetime import datetime, timedelta, timezone
        from app.collection.sportsgameodds_adapter import parse_page
        from app.storage.sportsgameodds_reference import prune_history, read_history, prune, prune_frames
        first = response()
        old = parse(first)
        second = deepcopy(first)
        book = second['data'][0]['odds']['points-home-game-sp-home']['byBookmaker']['book']
        book.update(odds='+100', lastUpdatedAt='2026-11-10T20:00:30Z')
        new = parse_page(json.dumps(second).encode(), '2026-11-10T20:01:00Z')
        with self.connect() as db:
            upsert_rows(db, prepare_page(old))
            upsert_frames(db, prepare_frames(old, prepare_page(old)))
            with db.transaction():
                upsert_rows(db, prepare_page(new))
                upsert_frames(db, prepare_frames(new, prepare_page(new)))
            history = db.execute('SELECT kind,facts FROM current_sgo_history ORDER BY kind').fetchall()
            self.assertEqual([r['kind'] for r in history], ['frame', 'reference'])
            self.assertEqual(history[1]['facts']['price_american'], '-110')
            self.assertEqual(db.execute('SELECT facts FROM current_sgo_reference').fetchone()['facts']['price_american'], '+100')
            # An undersized budget omits history without damaging the current row.
            book.update(odds='+105', lastUpdatedAt='2026-11-10T20:01:30Z')
            third = parse_page(json.dumps(second).encode(), '2026-11-10T20:02:00Z')
            with patch('app.storage.sportsgameodds_reference.HISTORY_BYTES', 0):
                upsert_rows(db, prepare_page(third))
            self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_history').fetchone()['n'], 2)
            self.assertEqual(db.execute('SELECT facts FROM current_sgo_reference').fetchone()['facts']['price_american'], '+105')
        with self.connect() as db:
            self.assertEqual(len(read_history(db, 'event')), 2)
            state = db.execute('SELECT * FROM current_sgo_history_state').fetchone()
            self.assertEqual(state['recorded'], 2)
            self.assertEqual(state['skipped_capacity'], 1)
            future = datetime.now(timezone.utc) + timedelta(days=8)
            self.assertEqual(prune_history(db, at=future.isoformat()), 2)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_reference').fetchone()['n'], 1)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_event_frame').fetchone()['n'], 1)
            later = (datetime.now(timezone.utc) + timedelta(days=60)).isoformat()
            self.assertEqual(prune(db, at=later), 1)
            self.assertEqual(prune_frames(db, at=later), 1)
            self.assertEqual(len(read_history(db, 'event')), 2)
            db.execute('DELETE FROM current_sgo_history')

    async def test_restart_restores_live_frame_without_a_projected_event(self):
        from datetime import datetime, timezone
        from app.collection.sportsgameodds_worker import retained_schedule
        raw = response()
        raw['data'][0]['eventID'] = 'recovery-event'
        raw['data'][0]['status'].update(started=True, live=True)
        page = parse(raw)
        with self.connect() as db:
            upsert_frames(db, prepare_frames(page, prepare_page(page)))
            self.assertEqual(db.execute("SELECT count(*) n FROM current_event WHERE provider='sportsgameodds'").fetchone()['n'], 0)
        with patch('app.storage.store.connect', side_effect=self.connect):
            events, truncated = retained_schedule(['NBA'], datetime(2026, 11, 10, 20, tzinfo=timezone.utc), 10)
        self.assertFalse(truncated)
        self.assertEqual(events['recovery-event']['phase'], 'live')
        self.assertEqual(events['recovery-event']['received_at'], page.events[0]['received_at'])

    async def test_old_provider_hold_does_not_mark_sgo_venues_held(self):
        from app.storage import ordinary_publication as live
        from app.collection.runtime_status import read_runtime
        with self.connect() as db:
            owner = read_runtime(db)
            owner['config']['aggregate_provider'] = 'sportsgameodds'
            owner['paused_sources'] = ['the_odds_api']
            owner.setdefault('status', {})['quota'] = {'blocking_reason': 'recovery_credential_changed'}
            with patch('app.collection.runtime_status.read_runtime', return_value=owner):
                _, states = live.authority(db)
            self.assertEqual(states['novig']['state'], 'available')
            self.assertNotEqual(states['novig'].get('reason_code'), 'recovery_credential_changed')
            self.assertNotEqual(states['pinnacle'].get('reason_code'), 'native_available')

    async def test_page_atomicity_unchanged_rows_and_controls(self):
        raw = response()
        book = raw['data'][0]['odds']['points-home-game-sp-home']['byBookmaker'].pop('book')
        raw['data'][0]['odds']['points-home-game-sp-home']['byBookmaker']['novig'] = book
        raw['data'].append(dict(deepcopy(raw['data'][0]), eventID='college-event', leagueID='NCAAB'))
        page = parse(raw)
        records, _ = current_rows(page, page.receipt_sha256)
        references = prepare_page(page)
        self.assertTrue(records and references)
        row = dict(type='current_aggregate_records',source='sportsgameodds',sport='NBA',
                   records=records,sgo_reference_rows=references,sgo_event_frames=prepare_frames(page,references),receipt_sha256=page.receipt_sha256,
                   event_scopes={event['event_id']:event['league'] for event in page.events},
                   complete_venues=[],received_at=page.events[0]['received_at'])
        sink = DatabaseIngressSink(SimpleNamespace(provider=self.service), DEFAULT)
        from app.collection.current_database import validate_sgo_page
        validate_sgo_page(row)
        mismatch = deepcopy(row)
        mismatch['sgo_reference_rows'][0]['facts']['receipt_sha256'] = 'f'*64
        with self.assertRaises(ValueError): validate_sgo_page(mismatch)
        mismatch = deepcopy(row)
        mismatch['sgo_reference_rows'][0]['facts']['received_at'] = '2026-11-10T21:00:00Z'
        with self.assertRaises(ValueError): validate_sgo_page(mismatch)
        mismatch = deepcopy(row)
        mismatch['sgo_event_frames'][0]['facts']['members'] = []
        with self.assertRaises(ValueError): validate_sgo_page(mismatch)
        mismatch = deepcopy(row)
        mismatch['records'][0]['quote']['source']['native_event_id'] = 'other'
        with self.assertRaises(ValueError): validate_sgo_page(mismatch)
        mismatch = deepcopy(row)
        mismatch['records'][0]['quote']['original']['value'] = '+125'
        with self.assertRaisesRegex(ValueError, 'sgo_offer_source_quote_mismatch'): validate_sgo_page(mismatch)
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
        self.assertNotIn('recent_sgo_preparations', sink.metrics)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_reference').fetchone()['n'], 0)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_event_frame').fetchone()['n'], 0)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_delivery_clock').fetchone()['n'], 0)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_offer').fetchone()['n'], before)
        with patch('app.collection.current_database.connect',side_effect=self.connect), \
             patch('app.collection.current_database.utc',return_value=AT):
            sink.prepare(row,self.service.states,Event())
            sample, = sink.metrics['recent_sgo_preparations']
            self.assertEqual(sample['received_at'], row['received_at'])
            self.assertEqual(sample['leagues'], ['NBA', 'NCAAB'])
            self.assertEqual(sample['reference_rows'], len(references))
            self.assertEqual(sample['event_frames'], 2)
            for key in ('sgo_reference', 'sgo_frames', 'sql_admission'):
                self.assertGreaterEqual(sample['timings'][key], 0)
            with self.connect() as db:
                first = db.execute('SELECT id,xmin::text AS version FROM sgo_quote_revision ORDER BY id,revision').fetchall()
                self.assertEqual(db.execute("SELECT state FROM current_source_status WHERE venue='sportsgameodds'").fetchone()['state']['state'], 'available')
                native_before = db.execute("SELECT venue,state FROM current_source_status WHERE venue IN ('kalshi','polymarket_us') ORDER BY venue").fetchall()
                offers = db.execute('SELECT count(*) n FROM current_offer').fetchone()['n']
                self.assertGreater(offers,before)
                self.assertEqual(len(first),len(references))
                self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_event_frame').fetchone()['n'],2)
                clocks = db.execute('SELECT * FROM current_sgo_delivery_clock ORDER BY league').fetchall()
                self.assertEqual([clock['league'] for clock in clocks], ['NBA', 'NCAAB'])
                admitted_at = clocks[0]['admitted_at']
                self.assertIsNotNone(admitted_at)
                self.assertEqual(clocks[1]['admitted_at'], admitted_at)
                self.assertTrue(all(clock['first_publication_write_at'] is None for clock in clocks))
                from app.storage.delivery_clocks import captured, published, receipts
                offers_at = [dict(league=r['event']['competition'], source=r['quote']['source'], times=r['quote']['times']) for r in records]
                captured(db, offers_at, admitted_at)
                published(db, receipts(offers_at))
                for delivered in db.execute('SELECT * FROM current_sgo_delivery_clock').fetchall():
                    self.assertEqual(delivered['first_recorded_capture_at'], admitted_at)
                    self.assertGreaterEqual(delivered['first_publication_write_at'], admitted_at)
            sink.prepare(row,self.service.states,Event())
            with self.connect() as db:
                self.assertEqual(db.execute('SELECT id,xmin::text AS version FROM sgo_quote_revision ORDER BY id,revision').fetchall(),first)
                self.assertEqual(db.execute('SELECT count(*) n FROM current_offer').fetchone()['n'],offers)
                links = db.execute('''SELECT o.price_value,o.facts#>>'{original,value}' AS inline_value,
                    o.sgo_quote_id,q.facts->>'price_american' AS source_price
                    FROM current_offer_storage o JOIN sgo_quote_revision q
                    ON (q.id,q.revision)=(o.sgo_quote_id,o.sgo_quote_revision) ORDER BY q.id''').fetchall()
                self.assertEqual(len(links), len(records))
                self.assertTrue(all(r['price_value'] is None and r['inline_value'] is None for r in links))
                self.assertEqual({r['source_price'] for r in links}, {'-110'})
                self.assertEqual(db.execute('SELECT amount FROM protected_test_hold').fetchone()['amount'],34)
                db.execute('UPDATE data_runtime SET paused_sources=%s WHERE singleton=true',(Jsonb(['sportsgameodds']),))
            with self.assertRaises(asyncio.CancelledError):
                sink.prepare(row,self.service.states,Event())
            stopped=dict(type='sgo_status',source='sportsgameodds',state='stopped',reason_code='sgo_paused',reason='Paused')
            sink.prepare(stopped,self.service.states,Event())
            self.assertEqual(len(sink.metrics['recent_sgo_preparations']), 2)
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
            self.assertEqual(db.execute('SELECT id,xmin::text AS version FROM sgo_quote_revision ORDER BY id,revision').fetchall(),first)
            self.assertEqual(db.execute('SELECT amount FROM protected_test_hold').fetchone()['amount'],34)

    async def test_offer_and_reference_can_keep_different_revisions_without_duplicating_price(self):
        raw = response()
        event_id = 'divergent-source-offer'
        raw['data'][0]['eventID'] = event_id
        odd = raw['data'][0]['odds']['points-home-game-sp-home']
        book = odd['byBookmaker'].pop('book')
        odd['byBookmaker']['novig'] = book
        sink = DatabaseIngressSink(SimpleNamespace(provider=self.service), DEFAULT)

        def admit(received):
            page = parse_page(json.dumps(raw).encode(), received)
            records, _ = current_rows(page, page.receipt_sha256)
            references = prepare_page(page)
            sink.prepare(dict(type='current_aggregate_records',source='sportsgameodds',sport='NBA',
                records=records,sgo_reference_rows=references,sgo_event_frames=prepare_frames(page,references),
                receipt_sha256=page.receipt_sha256,event_scopes={event_id:'NBA'},complete_venues=[],received_at=received),
                self.service.states, Event())
            return page.receipt_sha256

        with self.connect() as db, db.transaction(force_rollback=True):
            # Run both pages through the real nested ingress transaction and
            # roll the fixture back as a unit, including delivery counters.
            from contextlib import nullcontext
            with (
                patch('app.collection.current_database.connect', side_effect=lambda: nullcontext(db)),
                patch('app.collection.current_database.utc', return_value=AT),
            ):
                reference_receipt = admit('2026-11-10T20:00:00Z')
                # The offer owner accepts a later receipt with the same known source
                # time. The reference owner conservatively keeps the earlier value.
                book['odds'] = '+105'
                offer_receipt = admit('2026-11-10T20:01:00Z')
            state = db.execute('''SELECT o.price_value,q.price_value AS displayed,
                q.facts#>>'{provenance,sha256}' AS offer_receipt,
                r.facts->>'price_american' AS reference,r.facts->>'receipt_sha256' AS reference_receipt
                FROM current_offer_storage o JOIN current_offer q USING (contract_id)
                JOIN current_sgo_reference r ON r.id=o.sgo_quote_id WHERE r.event_id=%s''',(event_id,)).fetchone()
            self.assertEqual(state,dict(price_value=None,displayed='+105',offer_receipt=offer_receipt,
                                        reference='-110',reference_receipt=reference_receipt))
            from app.storage.sportsgameodds_reference import prune
            prune(db, at='2026-11-11T12:00:00Z')
            self.assertEqual(db.execute("SELECT count(*) n FROM sgo_quote_revision WHERE NOT is_current AND event_id=%s",
                                        (event_id,)).fetchone()['n'], 1)

    async def test_switch_marks_old_aggregate_historical_but_preserves_native(self):
        from copy import deepcopy
        from app.storage import ordinary_publication as live
        from app.collection.runtime_status import read_runtime
        with self.connect() as db, \
             patch('app.collection.current_policy.load', return_value=DEFAULT), \
             patch('app.storage.ordinary_publication.utc', return_value=self.at.isoformat()), \
             patch('app.storage.comparison_snapshot.utc', return_value=self.at.isoformat()):
            publication = live.turn(db)
            self.assertTrue(publication['published'], publication)
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
