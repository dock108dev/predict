"""Shared disposable SQL setup and authored board assertions; no test collection."""
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
import os
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql

from app.collection.current_policy import DEFAULT
from app.collection.runtime_status import RuntimeState
from app.storage.store import Store, stamp
from app.storage.payload_codec import payload_row
from app.storage.current_rows import CurrentRowStore
from app.storage import latest_board as latest
from app.comparison.estimated_policy import DEFAULT_POLICY
from tests.test_ev09_n01 import AT, SELECTED, envelopes
from tests.test_d03_current_rows import fixture_records
from tests.test_current_board_reads import context, frame

SOCKET=os.environ.get('DA_TEST_PGSOCKET')


@lru_cache(maxsize=1)
def two_games():
    all_records=fixture_records();catalog=context(frame(all_records),at=AT).catalog()['games']
    first=next(g for g in catalog if list(SELECTED) in g['members'])
    def rows(game):
        members={tuple(m) for m in game['members']}
        return [r for r in all_records if (r['quote']['source']['provider'],r['quote']['source']['native_event_id']) in members]
    second=next(g for g in catalog if g!=first and len(rows(g))>=6)
    return deepcopy((first,second,rows(first)+rows(second)))


def native_key(q):
    return tuple([q['venue'],*[q['source'][k] for k in ('native_event_id','native_market_id','native_outcome_id','native_side')]])


class LatestBoardFixture(IsolatedAsyncioTestCase):
    @classmethod
    def connect(cls,name=None):
        assert str(SOCKET).startswith('/tmp/predict-pg-'),'Disposable cluster only'
        return psycopg.connect(host=SOCKET,port=55432,user='prediction_arb',dbname=name or cls.name,
            autocommit=True,row_factory=payload_row,connect_timeout=5)

    @classmethod
    def setUpClass(cls):
        cls.name='prediction_arb_latest_board_'+uuid4().hex[:10]
        with cls.connect('prediction_arb') as db:
            assert str(db.execute('show data_directory').fetchone()['data_directory']).startswith('/tmp/predict-pg-')
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        with cls.connect() as db:Store(db).migrate()

    @classmethod
    def tearDownClass(cls):
        with cls.connect('prediction_arb') as db:
            db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))

    async def asyncSetUp(self):
        # Deterministic admission in this multi-test fixture process. Installed
        # RSS/reservations are measured separately; test-runner retained arenas
        # are not the data owner's resident baseline.
        from app.collection.background_work import BackgroundWork
        admission=patch('app.collection.background_work.BACKGROUND',BackgroundWork(sampler=lambda:64*1024*1024))
        admission.start();self.addCleanup(admission.stop)
        self.at=stamp(AT)
        for target in ('app.collection.runtime_client.load','app.storage.latest_board.load','app.dashboard.comparison_board_api.load'):
            change=patch(target,return_value=deepcopy(DEFAULT) if target.endswith('runtime_client.load') else DEFAULT_POLICY)
            change.start();self.addCleanup(change.stop)
        for target,callback in (
            ('app.collection.runtime_status.clock',lambda:self.at),
            ('app.storage.current_rows.utc',lambda:self.at.isoformat()),
            ('app.storage.latest_board.utc',lambda:self.at.isoformat()),
            ('app.storage.comparison_board.utc',lambda:self.at.isoformat()),
            ('app.dashboard.comparison_board_api.utc',lambda:self.at.isoformat()),
        ):
            change=patch(target,side_effect=callback);change.start();self.addCleanup(change.stop)
        self.first,self.second,self.records=deepcopy(two_games())
        self.service=SimpleNamespace(runtime_id='fixture-'+uuid4().hex,config=deepcopy(DEFAULT),
            states={v:dict(state='available') for v in ('kalshi','polymarket_us','novig','prophetx','pinnacle')},
            dispatch=True,background_calculations=dict(board='running'),
            status=lambda:dict(issues=[],exclusions=[],database=dict(state='available')))
        self.state=RuntimeState(self.connect)
        with self.connect() as db:
            db.execute('TRUNCATE current_event CASCADE')
            db.execute('TRUNCATE current_source_status,current_refresh_scope,data_runtime,data_runtime_command,latest_board,latest_board_status')
        self.state.write(self.service)
        self.admit(self.records)

    def admit(self,records):
        with self.connect() as db:
            CurrentRowStore(db).upsert_records(records,now=self.at.isoformat())
            members={(r['quote']['source']['provider'],r['quote']['source']['native_event_id']) for r in records}
            books=[o['book'] for e in envelopes() if e['record']['kind']=='admitted_books'
                for o in e['record']['value']['observations']
                if (e['record']['source'],o['book']['raw']['ref']['event_id']) in members]
            if books:CurrentRowStore(db).replace_native_books(books)

    def reconcile(self):
        with self.connect() as db:
            result=latest.reconcile(db,at=self.at.isoformat())
            # Surface the actual source-frame exception rather than allowing
            # an opaque observation_invalid to hide a normalization regression.
            for error in result.get('errors',[]):
                if error['reason']=='observation_invalid':
                    latest.read_context(db,at=self.at.isoformat()).observation_bundles(game=error['game_key'])
            return result

    def rows(self):
        with self.connect() as db:return {r['game_key']:r for r in db.execute('SELECT * FROM latest_board').fetchall()}

    def snapshot(self):
        with self.connect() as db:return latest.snapshot(db,at=self.at.isoformat())

    def changed_first(self):
        self.at+=timedelta(seconds=1);self.state.write(self.service)
        r=deepcopy(next(r for r in self.records if r['quote']['venue']=='novig' and
            (r['quote']['source']['provider'],r['quote']['source']['native_event_id'])==SELECTED))
        r['quote']['original']['value']='2.91'
        if 'native_value' in r['quote']['original']:r['quote']['original']['native_value']='2.91'
        r['quote']['times'].update(source_at=self.at.isoformat(),received_at=self.at.isoformat())
        if 'provider_clocks' in r['quote']:r['quote']['provider_clocks'].update(book=self.at.isoformat(),market=self.at.isoformat())
        self.admit([r]);return r

    def fresh_sources(self,records=None):
        """Author source observations at the fixture instant, not read clocks."""
        records=deepcopy(self.records if records is None else records)
        for record in records:
            record['quote']['times'].update(source_at=self.at.isoformat(),received_at=self.at.isoformat())
            # This helper explicitly authors a known provider quote clock; the
            # general source path also retains genuine unknown-clock rows.
            if record['quote']['times']['source_time_kind']=='unknown':
                record['quote']['times']['source_time_kind']='provider_quote'
            record['quote'].get('provider_clocks',{}).update(book=self.at.isoformat(),market=self.at.isoformat())
        self.admit(records)

    def assert_source_frame(self, board, *, current=True):
        """Compare compact observations with admitted SQL facts, not finance."""
        with self.connect() as db:
            records=CurrentRowStore(db).capture()['records']
        members={tuple(m) for g in self.snapshot()['status']['games'] if g['game_key']==board['game_key'] for m in g['members']}
        expected={native_key(r['quote']):r['quote'] for r in records
            if r['quote']['venue']!='pinnacle' and (r['quote']['source']['provider'],r['quote']['source']['native_event_id']) in members}
        self.assertTrue(expected)
        self.assertEqual({native_key(q) for q in board['prices']},set(expected))
        for q in board['prices']:
            original=expected[native_key(q)]
            self.assertEqual(q['source'],original['source'])
            self.assertEqual(q['original'],original['original'])
            self.assertEqual(q['times'],original['times'])
            self.assertTrue(q['quote_id']);self.assertTrue(q['quote_revision'])
            self.assertTrue(q['inputs_identity']['context_id'])
            self.assertIn('common_odds',q)
            self.assertTrue(q['observation_revision'])
            if board['view']=='odds':
                observed=q['observed_depth'];depth=original.get('depth')
                self.assertEqual(observed['available'],bool(depth))
                self.assertEqual(observed['levels'],(depth or [])[:8])
                self.assertEqual(observed['total_levels'],None if depth is None else len(depth))
                self.assertEqual(observed['quantity_units'],original['original']['quantity_units'])
                self.assertEqual(observed['price_units'],original['original']['units'])
                self.assertEqual(q.get('provider_clocks'),original.get('provider_clocks'))
                # The bounded board carries confirmation identity and clocks;
                # the full audit remains in the exact Original inputs response.
                if original.get('book_confirmation'):
                    self.assertTrue(q.get('book_confirmation'))
                    self.assertEqual(q['book_confirmation'],{k:original['book_confirmation'][k] for k in q['book_confirmation']})
                else:self.assertIsNone(q.get('book_confirmation'))
            else:
                # Financial boards retain exact scalar inputs and reference
                # them from rows; Odds-only book audit copies are omitted.
                self.assertNotIn('observed_depth',q)
            if current:self.assertEqual(q['freshness']['status'],'current',q['freshness'])
        return expected
