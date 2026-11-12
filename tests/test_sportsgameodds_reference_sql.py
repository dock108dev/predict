"""Disposable database tests; no provider requests or installed-state writes."""
import json
from pathlib import Path
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch
from uuid import uuid4

from psycopg import sql
from psycopg.types.json import Jsonb

from app.collection.sportsgameodds_adapter import parse_page
from app.collection.sportsgameodds_current_rows import current_rows
from app.storage.current_rows import CurrentRowStore
from app.storage.sportsgameodds_reference import prepare_page, read_event, upsert_rows
from app.storage.store import Store, connect
from tests.latest_board_fixture import SOCKET
from tests.test_sportsgameodds_adapter import AT, response


def test_batch_archives_only_replaced_returned_revisions():
    raw = response()
    raw['data'][0]['eventID'] = 'batch'
    books = raw['data'][0]['odds']['points-home-game-sp-home']['byBookmaker']
    for name in ('changed', 'expiry_only', 'unchanged', 'new'):
        books[name] = deepcopy(books['book'])
    del books['book']
    rows = prepare_page(parse_page(json.dumps(raw).encode(), AT))
    by_book = {row['bookmaker_id']: row for row in rows}
    previous = [dict(by_book['changed'], revision='old'), by_book['expiry_only'], by_book['unchanged']]
    accepted = [by_book[name] for name in ('changed', 'expiry_only', 'new')]
    lock, retained, count, write = Mock(), Mock(), Mock(), Mock()
    retained.fetchall.return_value = previous
    count.fetchone.return_value = {'n': len(previous)}
    write.fetchall.return_value = [{k: row[k] for k in ('id', 'revision')} for row in accepted]
    db = Mock()
    db.execute.side_effect = [lock, retained, count, write]

    with patch('app.storage.sportsgameodds_reference.archive_revisions') as archive:
        assert upsert_rows(db, rows) == len(accepted)
        archive.assert_called_once_with(db, 'reference', previous[:1])
    statement, params = db.execute.call_args.args
    assert 'jsonb_to_recordset' in statement and params[0].obj == rows


@unittest.skipUnless(SOCKET, 'Explicit disposable PostgreSQL lane required')
class SportsGameOddsReferenceSQL(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.storage.store import ROOT
        root = Path(ROOT).resolve()
        assert root.parent == Path('/tmp').resolve() and root.name.startswith('predict-pg-'), 'Disposable cluster only'
        assert (root / '.local' / 'pgsocket').resolve() == Path(SOCKET).resolve(), 'Disposable socket only'
        cls.name = 'prediction_arb_sgo_' + uuid4().hex[:10]
        with connect() as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        cls.db = connect(cls.name)
        Store(cls.db).migrate()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        with connect() as db:
            db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))

    def setUp(self):
        self.db.execute('DELETE FROM current_sgo_event_frame')
        self.db.execute('DELETE FROM current_sgo_reference')
        self.db.execute('DELETE FROM current_offer')
        self.db.execute('DELETE FROM current_contract')
        self.db.execute('DELETE FROM current_event')
        self.db.execute('DELETE FROM data_runtime')
        self.db.execute('''INSERT INTO data_runtime
            (runtime_id,owner_pid,started_at,heartbeat_at,state,config,source_status,dispatch,status,fingerprint,paused_sources,global_stopped)
            VALUES ('protected',1,now(),now(),'stopped',%s,%s,false,%s,'keep',%s,true)''',
            (Jsonb({}), Jsonb({}), Jsonb({}), Jsonb(['kalshi'])))

    def page(self, *, source='2026-11-10T19:59:00Z', received=AT, available=True, odds='-110', event_id='event'):
        data = response()
        event = data['data'][0]
        event['eventID'] = event_id
        odd = event['odds']['points-home-game-sp-home']
        book = odd['byBookmaker'].pop('book')
        book.update(lastUpdatedAt=source, available=available, odds=odds)
        odd['byBookmaker']['novig'] = book
        odd['byBookmaker']['fanduel'] = deepcopy(book)
        return parse_page(json.dumps(data).encode(), received)

    def test_atomic_capture_ordering_and_partial_traversal(self):
        page = self.page()
        reference_rows = prepare_page(page)
        product_rows, _ = current_rows(page, page.receipt_sha256)
        self.assertEqual(len(reference_rows), 2)
        self.assertEqual(len(product_rows), 1)
        with self.assertRaisesRegex(RuntimeError, 'rollback'):
            with self.db.transaction():
                upsert_rows(self.db, reference_rows)
                CurrentRowStore(self.db).upsert_records(product_rows, now=AT)
                raise RuntimeError('rollback')
        self.assertEqual(self.db.execute('SELECT count(*) AS n FROM current_sgo_reference').fetchone()['n'], 0)
        self.assertEqual(self.db.execute('SELECT count(*) AS n FROM current_offer').fetchone()['n'], 0)
        with self.db.transaction():
            self.assertEqual(upsert_rows(self.db, reference_rows), 2)
            CurrentRowStore(self.db).upsert_records(product_rows, now=AT)
        records = read_event(self.db, 'event')
        self.assertEqual({row['facts']['venue'] for row in records}, {'novig', 'fanduel'})
        self.assertTrue(all(row['facts']['opposing_odd_id'] == 'points-away-game-sp-away' for row in records))
        # A partial page lacking a book never withdraws the prior book.
        partial = [r for r in reference_rows if r['bookmaker_id'] == 'novig']
        with self.db.transaction():
            self.assertEqual(upsert_rows(self.db, partial), 0)
        self.assertEqual(len(read_event(self.db, 'event')), 2)
        older = prepare_page(self.page(source='2026-11-10T19:58:00Z', received='2026-11-10T20:01:00Z', odds='+150'))
        with self.db.transaction():
            self.assertEqual(upsert_rows(self.db, older), 0)
        self.assertEqual({r['facts']['price_american'] for r in read_event(self.db, 'event')}, {'-110'})
        conflict = prepare_page(self.page(received='2026-11-10T20:01:00Z', odds='+150'))
        with self.db.transaction():
            self.assertEqual(upsert_rows(self.db, conflict), 0)
        self.assertEqual({r['facts']['price_american'] for r in read_event(self.db, 'event')}, {'-110'})
        unavailable = prepare_page(self.page(received='2026-11-10T20:01:00Z', available=False))
        with self.db.transaction():
            self.assertEqual(upsert_rows(self.db, unavailable), 2)
        self.assertTrue(all(not r['facts']['available'] for r in read_event(self.db, 'event')))
        same_clock_reopen = prepare_page(self.page(received='2026-11-10T20:02:00Z'))
        with self.db.transaction():
            self.assertEqual(upsert_rows(self.db, same_clock_reopen), 0)
        self.assertTrue(all(not r['facts']['available'] for r in read_event(self.db, 'event')))
        with self.assertRaisesRegex(ValueError, 'capacity'):
            read_event(self.db, 'event', limit=1)
        protected = self.db.execute('SELECT runtime_id,paused_sources,global_stopped FROM data_runtime').fetchone()
        self.assertEqual(protected, {'runtime_id': 'protected', 'paused_sources': ['kalshi'], 'global_stopped': True})

    def test_retention_capacity_and_unavailable_current_facts(self):
        from unittest.mock import patch
        from app.storage.sportsgameodds_reference import prune

        page = self.page(available=False)
        rows = prepare_page(page)
        with self.db.transaction():
            upsert_rows(self.db, rows)
            self.assertEqual(prune(self.db, at='2026-11-24T20:59:59Z'), 0)
        self.assertEqual(len(read_event(self.db, 'event')), 2)
        # Capacity fails closed; it never discards a current row to make room.
        other = response()
        other['data'][0]['eventID'] = 'event-2'
        other_page = parse_page(json.dumps(other).encode(), AT)
        with patch('app.storage.sportsgameodds_reference.MAX_CURRENT_ROWS', 2):
            with self.assertRaisesRegex(ValueError, 'storage capacity'):
                with self.db.transaction():
                    upsert_rows(self.db, prepare_page(other_page))
        self.assertEqual(len(read_event(self.db, 'event')), 2)
        with self.db.transaction():
            self.assertEqual(prune(self.db, at='2026-11-24T21:00:01Z', limit=1), 1)
            self.assertEqual(prune(self.db, at='2026-11-24T21:00:01Z'), 1)
        protected = self.db.execute('SELECT runtime_id,paused_sources,global_stopped FROM data_runtime').fetchone()
        self.assertEqual(protected, {'runtime_id': 'protected', 'paused_sources': ['kalshi'], 'global_stopped': True})

    def test_recent_unchanged_observation_extends_retention_without_refreshing_source(self):
        page = self.page(available=False)
        with self.db.transaction():
            upsert_rows(self.db, prepare_page(page))
        later = self.page(available=False, received='2026-11-24T20:30:00Z')
        with self.db.transaction():
            self.assertEqual(upsert_rows(self.db, prepare_page(later)), 2)
        facts = [r['facts'] for r in read_event(self.db, 'event')]
        self.assertTrue(all(f['received_at'] == AT and f['source_at'] == '2026-11-10T19:59:00Z' for f in facts))
        from app.storage.sportsgameodds_reference import prune
        with self.db.transaction():
            self.assertEqual(prune(self.db, at='2026-11-24T21:00:01Z'), 0)

    def test_event_frame_binds_unchanged_and_changed_sides_without_refreshing_clock(self):
        from app.storage.sportsgameodds_reference import prepare_frames, read_event_frame, read_history, upsert_frames
        event_id = 'mixed-reference-batch'
        first = self.page(event_id=event_id)
        first_rows = prepare_page(first)
        first_frames = prepare_frames(first, first_rows)
        with self.assertRaisesRegex(RuntimeError, 'rollback'):
            with self.db.transaction():
                upsert_rows(self.db, first_rows)
                upsert_frames(self.db, first_frames)
                raise RuntimeError('rollback')
        self.assertIsNone(read_event_frame(self.db, event_id))
        with self.db.transaction():
            upsert_rows(self.db, first_rows)
            upsert_frames(self.db, first_frames)
        old = {r['facts']['venue']: r for r in read_event(self.db, event_id)}
        data = response()
        event = data['data'][0]
        event['eventID'] = event_id
        odd = event['odds']['points-home-game-sp-home']
        base = odd['byBookmaker'].pop('book')
        odd['byBookmaker']['novig'] = deepcopy(base)
        source_at = '2026-11-10T20:00:30.123456Z'
        odd['byBookmaker']['fanduel'] = dict(base, odds='+150', lastUpdatedAt=source_at)
        odd['byBookmaker']['pinnacle'] = deepcopy(base)
        second = parse_page(json.dumps(data).encode(), '2026-11-10T20:01:00Z')
        second_rows = prepare_page(second)
        second_frames = prepare_frames(second, second_rows)
        with self.assertRaisesRegex(RuntimeError, 'rollback'):
            with self.db.transaction():
                self.assertEqual(upsert_rows(self.db, second_rows), 2)
                self.assertEqual(upsert_frames(self.db, second_frames), 1)
                self.assertEqual(len(read_history(self.db, event_id)), 2)
                raise RuntimeError('rollback current facts, frame and archived witnesses')
        self.assertEqual({r['facts']['venue']: r for r in read_event(self.db, event_id)}, old)
        self.assertEqual(read_event_frame(self.db, event_id)['facts']['receipt_sha256'], first.receipt_sha256)
        self.assertEqual(read_history(self.db, event_id), [])
        with self.db.transaction():
            self.assertEqual(upsert_rows(self.db, second_rows), 2)
            self.assertEqual(upsert_frames(self.db, second_frames), 1)
        current = {r['facts']['venue']: r for r in read_event(self.db, event_id)}
        frame = read_event_frame(self.db, event_id)['facts']
        self.assertEqual(frame['receipt_sha256'], second.receipt_sha256)
        self.assertEqual(frame['received_at'], '2026-11-10T20:01:00Z')
        self.assertEqual({tuple(pair) for pair in frame['members']}, {(r['id'], r['revision']) for r in current.values()})
        self.assertEqual(current['novig']['facts']['received_at'], old['novig']['facts']['received_at'])
        self.assertEqual(current['novig']['facts']['source_at'], old['novig']['facts']['source_at'])
        self.assertEqual(current['fanduel']['facts']['source_at'], source_at)
        self.assertEqual(current['fanduel']['facts']['price_american'], '+150')
        self.assertEqual(current['pinnacle']['facts']['received_at'], frame['received_at'])
        archived = {r['kind']: r['facts'] for r in read_history(self.db, event_id)}
        self.assertEqual(archived, {'frame': first_frames[0]['facts'], 'reference': old['fanduel']['facts']})
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            prepare_frames(second, second_rows[:1])

    def test_frame_retention_and_capacity_preserve_controls(self):
        from unittest.mock import patch
        from app.storage.sportsgameodds_reference import prepare_frames, prune_frames, read_event_frame, upsert_frames
        page = self.page(available=False)
        frames = prepare_frames(page, prepare_page(page))
        with patch('app.storage.sportsgameodds_reference.MAX_FRAME_TOTAL_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'storage capacity'):
                with self.db.transaction():
                    upsert_frames(self.db, frames)
        with self.db.transaction():
            upsert_frames(self.db, frames)
            self.assertEqual(prune_frames(self.db, at='2026-11-24T20:59:59Z'), 0)
        self.assertIsNotNone(read_event_frame(self.db, 'event'))
        other = response()
        other['data'][0]['eventID'] = 'event-2'
        other_page = parse_page(json.dumps(other).encode(), AT)
        with patch('app.storage.sportsgameodds_reference.MAX_FRAMES', 1):
            with self.assertRaisesRegex(ValueError, 'storage capacity'):
                with self.db.transaction():
                    upsert_frames(self.db, prepare_frames(other_page, prepare_page(other_page)))
        with self.db.transaction():
            self.assertEqual(prune_frames(self.db, at='2026-11-24T21:00:01Z'), 1)
        self.assertIsNone(read_event_frame(self.db, 'event'))
        protected = self.db.execute('SELECT runtime_id,paused_sources,global_stopped FROM data_runtime').fetchone()
        self.assertEqual(protected, {'runtime_id': 'protected', 'paused_sources': ['kalshi'], 'global_stopped': True})
