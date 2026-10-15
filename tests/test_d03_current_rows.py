"""Disposable SQL qualification of bounded current ownership, never acquisition."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
import unittest
from uuid import uuid4
from unittest.mock import patch
from types import SimpleNamespace
from psycopg import sql
from app.storage.store import connect,Store,hashed
from app.storage.current_rows import CurrentRowStore,contract_id,prepare
from app.comparison.combined_inputs import prepare as normalize
from tests.test_ev09_n01 import envelopes,AT


def fixture_records():
    """Authentic retained shape; old source/receipt timestamps remain unchanged."""
    return [r for group in normalize(envelopes(),at=AT)['groups'] for r in group]


def future_records(venue='novig'):
    rows=deepcopy([r for r in fixture_records() if r['quote']['venue']==venue][:2])
    start=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
    for r in rows:
        r['event']['scheduled_start']=r['market_identity']['scheduled_start']=start
        r['quote']['times']['source_at']='2026-10-15T12:00:00Z'
        r['quote']['times']['received_at']='2026-10-15T12:00:01Z'
    return rows


class CurrentRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name='prediction_arb_d03_ingress_'+uuid4().hex[:10]
        with connect() as db:db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        cls.db=connect(cls.name);Store(cls.db).migrate();cls.store=CurrentRowStore(cls.db)
    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        with connect() as db:db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))
    def setUp(self):
        self.db.execute('TRUNCATE current_event CASCADE');self.db.execute('TRUNCATE current_refresh_scope,current_source_status')
    def counts(self):
        return {t:self.db.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(sql.Identifier(t))).fetchone()['n'] for t in ('current_event','current_contract','current_offer','current_depth','current_envelope','current_game_snapshot','current_game_result')}
    def test_repeat_receipt_only_stable_and_no_archive(self):
        rows=future_records();self.store.upsert_records(rows);before=self.store.capture();counts=self.counts()
        for i in range(10):
            changed=deepcopy(rows)
            for r in changed:r['quote']['times']['received_at']=f'2026-10-15T12:01:{i:02d}Z';r['quote']['provenance']['sha256']=hashed(i)
            self.store.upsert_records(changed)
        after=self.store.capture();self.assertEqual(before['revision'],after['revision']);self.assertEqual(counts,self.counts())
        self.assertTrue(all(r['quote']['times']['source_at']=='2026-10-15T12:00:00Z' for r in after['records']))
        self.assertEqual(counts['current_envelope']+counts['current_game_snapshot']+counts['current_game_result'],0)
    def test_price_and_contract_changes_replace(self):
        rows=future_records();self.store.upsert_records(rows);before=self.store.capture();changed=deepcopy(rows)
        changed[0]['quote']['times'].update(source_at='2026-10-15T12:02:00Z',received_at='2026-10-15T12:02:01Z')
        changed[0]['quote']['original']['value']='2.345'
        changed[0]['selection']['label']='Changed exact contract label'
        self.store.upsert_records(changed);after=self.store.capture()
        self.assertNotEqual(before['revision'],after['revision']);self.assertEqual(len(after['records']),2)
        self.assertEqual(self.counts()['current_offer'],2)
    def test_older_and_unknown_source_cannot_replace_known(self):
        rows=future_records();self.store.upsert_records(rows);before=self.store.capture()
        for source in ('2026-10-15T11:00:00Z',None):
            changed=deepcopy(rows);changed[0]['quote']['times'].update(source_at=source,received_at='2026-10-15T12:10:00Z');changed[0]['quote']['original']['value']='9'
            self.store.upsert_records(changed);self.assertEqual(before['revision'],self.store.capture()['revision'])
    def test_partial_one_side_authoritative_and_stale_removal(self):
        rows=future_records();self.store.upsert_records(rows)
        scope=dict(venue='novig',competition='NFL',native_event_id=rows[0]['event']['id'],received_at='2026-10-15T12:01:00Z',source_at='2026-10-15T12:00:00Z')
        self.store.upsert_records(rows[:1],scopes=[scope]);self.assertEqual(len(self.store.records()),2)
        self.store.upsert_records(rows[:1],scopes=[scope],authoritative=True);self.assertEqual(len(self.store.records()),1)
        self.store.upsert_records(rows);self.assertEqual(len(self.store.records()),2)
        old=dict(scope,received_at='2026-10-15T11:00:00Z',source_at='2026-10-15T11:00:00Z')
        self.store.upsert_records([],scopes=[old],authoritative=True);self.assertEqual(len(self.store.records()),2)
    def test_expiry_cascades_and_first_use_empty(self):
        self.assertEqual(self.store.records(),[]);rows=future_records();self.store.upsert_records(rows)
        self.store.expire(now='2030-01-01T00:00:00Z');self.assertEqual(self.store.records(),[])
        self.assertEqual(self.counts()['current_contract'],0)
    def test_exact_shared_native_depth_bid_change_and_missing_side(self):
        native=future_records('polymarket_us');self.store.upsert_records(native)
        target=native[0]['quote']['source'];book=deepcopy(next(o['book'] for e in envelopes() if e['record']['kind']=='admitted_books' for o in e['record']['value']['observations'] if o['book']['raw']['ref']['market_id']==target['native_market_id']))
        book['raw'].update(exchange_at='2026-10-15T12:00:00Z',received_at='2026-10-15T12:00:01Z')
        self.store.replace_native_books([book]);before=self.store.capture()
        self.assertTrue(any(r['quote'].get('depth') for r in before['records']))
        count=self.db.execute('SELECT count(*) AS n FROM current_native_depth').fetchone()['n']
        self.store.replace_native_books([book]);self.assertEqual(count,self.db.execute('SELECT count(*) AS n FROM current_native_depth').fetchone()['n'])
        changed=deepcopy(book);changed['raw'].update(exchange_at='2026-10-15T12:01:00Z',received_at='2026-10-15T12:01:01Z')
        ladder=next(o['bids'] for o in changed['outcomes'] if o['bids'] and o['bids']['levels'])
        ladder['levels'][0]['quantity']['value']='123.4500'
        self.store.replace_native_books([changed]);self.assertNotEqual(before['revision'],self.store.capture()['revision'])
        changed['outcomes'][0]['asks']=None;changed['raw']['received_at']='2026-10-15T12:01:02Z';self.store.replace_native_books([changed])
        status=self.db.execute('SELECT outcomes FROM current_native_book').fetchone()['outcomes']
        self.assertFalse(status[0]['asks'])
    def test_equal_clock_price_conflict_is_atomic(self):
        rows=future_records();self.store.upsert_records(rows);before=self.store.capture()
        changed=deepcopy(rows);changed[0]['quote']['original']['value']='3.99'
        with self.assertRaisesRegex(ValueError,'equal_clock_price_conflict'):self.store.upsert_records(changed)
        self.assertEqual(before,self.store.capture())

    def test_direct_sink_native_and_aggregate_are_atomic_without_archives(self):
        from app.collection.current_database import DatabaseIngressSink
        from app.collection.current_policy import DEFAULT
        from app.dashboard.current_state import unavailable
        from app.collection.current_aggregate_admission import admit
        import base64
        raw=unavailable();store=SimpleNamespace(_state=raw,commit=lambda value:setattr(store,'_state',value))
        sink=DatabaseIngressSink(store,DEFAULT);states=raw['source_status']
        source='polymarket_us';cats={}
        cat=next(e['record']['value']['inventory'] for e in envelopes() if e['record']['kind']=='catalog' and e['record']['source']==source)
        cats[source]=cat
        header=dict(source=source,session_id='d03-synthetic-offline',observed_at=AT)
        def owner_connect():return connect(self.name)
        with patch('app.collection.current_database.connect',owner_connect):
            sink.commit(dict(header,type='coverage_inventory',inventory=cats,generation=1,previous_generation=None),states)
            observation=deepcopy(next(o for e in envelopes() if e['record']['kind']=='admitted_books' and e['record']['source']==source for o in e['record']['value']['observations']))
            sink.commit(dict(observation,**header),states)
            native=self.store.records();self.assertTrue(any(r['quote'].get('depth') for r in native))
            one_sided=deepcopy(observation);one_sided['book']['outcomes'][0]['asks']=None
            one_sided['book']['raw'].update(exchange_at='2026-10-15T12:10:00Z',received_at='2026-10-15T12:10:01Z')
            sink.commit(dict(one_sided,**header),states)
            self.assertGreater(self.counts()['current_contract'],self.counts()['current_offer'])
            aggregate=next(e['record']['value'] for e in envelopes() if e['record']['kind']=='aggregate_batch')
            body=base64.b64decode(aggregate['body_b64']);records=admit(body,'NFL',aggregate['received_at'],venue='novig')
            sink.commit(dict(type='current_aggregate_records',source='the_odds_api',sport='NFL',records=records,received_at=aggregate['received_at'],complete_venues=['novig']),states)
        self.assertEqual(self.counts()['current_envelope']+self.counts()['current_game_snapshot']+self.counts()['current_game_result'],0)
        self.assertTrue(any(r['quote']['venue']=='novig' for r in self.store.records()))
        before=sink.sequence
        with patch('app.collection.current_database.connect',side_effect=OSError('authored-sql-unavailable')):
            with self.assertRaisesRegex(OSError,'authored-sql'):sink.commit(dict(type='source_health',source=source,state='error',observed_at=AT),states)
        self.assertEqual(sink.sequence,before);self.assertIn('authored-sql',sink.error)
        self.assertFalse(hasattr(sink,'pending'))

    def test_scheduler_admitted_handoff_reaches_current_sql_without_raw_fallback(self):
        import json
        from app.collection.current_database import DatabaseIngressSink
        from app.collection.current_policy import DEFAULT
        from app.dashboard.current_state import unavailable
        from tests.test_d03_aggregate_frame import ordinary_scheduler
        from tests.test_current_aggregate import body
        raw=unavailable();state=SimpleNamespace(_state=raw)
        state.commit=lambda value:setattr(state,'_state',value)
        sink=DatabaseIngressSink(state,DEFAULT)
        scheduler,_,_=ordinary_scheduler();scheduler.service.sink=sink
        payload=json.loads(body('NFL',books=('novig','prophetx','pinnacle')))
        payload[0]['commence_time']=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
        received='2026-10-15T12:00:01Z'
        with patch('app.collection.current_database.connect',lambda:connect(self.name)):
            scheduler.admit_response(dict(body=json.dumps(payload).encode(),received_at=received),'NFL')
        records=self.store.records()
        self.assertEqual({r['quote']['venue'] for r in records},{'novig','prophetx','pinnacle'})
        self.assertTrue(all(r['quote']['times']['received_at']==received for r in records))
        self.assertTrue(all(r['quote']['times']['source_at']=='2026-10-03T00:00:00Z' for r in records))
        self.assertEqual(sink.sequence,1)
        self.assertEqual(self.counts()['current_envelope']+self.counts()['current_game_snapshot']+self.counts()['current_game_result'],0)

    def test_pipeline_restart_cannot_import_old_diagnostics_or_journal(self):
        from app.collection.current_database import DatabasePipeline
        from app.collection.current_policy import DEFAULT
        import asyncio
        def denied():raise AssertionError('retired archive path invoked')
        service=SimpleNamespace(config=DEFAULT,journal=SimpleNamespace(paths=denied),retained_directory=SimpleNamespace(glob=denied))
        pipeline=DatabasePipeline(service)
        with patch('app.collection.current_database.connect',lambda:connect(self.name)):
            asyncio.run(pipeline.start());pipeline.tick()
        self.assertEqual(self.counts()['current_envelope'],0)
        self.assertEqual(self.counts()['current_game_result'],0)

    def test_catalog_repeatable_read_does_not_block_concurrent_writer(self):
        from concurrent.futures import ThreadPoolExecutor
        from app.storage.current_games import GameStore
        from app.storage.comparison_board import ReadContext
        rows=future_records();self.store.upsert_records(rows)
        changed=deepcopy(rows);changed[0]['quote']['original']['value']='2.987'
        changed[0]['quote']['times'].update(source_at='2026-10-15T12:03:00Z',received_at='2026-10-15T12:03:01Z')
        def write_current():
            with connect(self.name) as writer:
                writer.execute('SET lock_timeout=1000')
                return CurrentRowStore(writer).upsert_records(changed)
        with self.db.transaction():
            self.db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            context=ReadContext(GameStore(self.db));context.catalog_bundles()
            before=self.store.capture(include_depth=False)
            with ThreadPoolExecutor(max_workers=1) as workers:
                self.assertEqual(workers.submit(write_current).result(timeout=3),1)
            # The held read frame remains coherent after the writer commits.
            self.assertEqual(before,self.store.capture(include_depth=False))
        self.assertNotEqual(before['revision'],self.store.capture(include_depth=False)['revision'])

    def test_reopen_changes_runtime_epoch_without_changing_prices_or_clocks(self):
        from app.collection.current_database import DatabasePipeline
        from app.collection.current_policy import DEFAULT
        import asyncio
        self.store.upsert_records(future_records());before=self.store.capture();counts=self.counts()
        service=SimpleNamespace(config=DEFAULT)
        async def reopen():
            pipeline=DatabasePipeline(service)
            await pipeline.start()
            epoch=self.store.capture()['epoch']
            self.assertTrue(await pipeline.close())
            return epoch
        with patch('app.collection.current_database.connect',lambda:connect(self.name)):
            first=asyncio.run(reopen());second=asyncio.run(reopen())
        after=self.store.capture()
        self.assertEqual(len({before['epoch'],first,second}),3)
        self.assertEqual(before['records'],after['records'])
        self.assertEqual(before['source_status'],after['source_status'])
        self.assertEqual(counts,self.counts())

    def test_failed_runtime_start_is_visible_and_preserves_epoch(self):
        from app.collection.current_database import DatabasePipeline
        from app.collection.current_policy import DEFAULT
        import asyncio
        before=self.store.capture()['epoch'];pipeline=DatabasePipeline(SimpleNamespace(config=DEFAULT))
        with patch('app.collection.current_database.connect',side_effect=OSError('authored-start-sql-unavailable')):
            with self.assertRaisesRegex(OSError,'authored-start-sql'):asyncio.run(pipeline.start())
        self.assertIn('authored-start-sql',pipeline.error)
        self.assertEqual(before,self.store.capture()['epoch'])
        self.assertIsNone(pipeline.task)

    def test_projection_clock_preserved_and_old_missing_clock_is_unknown(self):
        from app.storage.current_rows import contract_id
        rows=future_records();rows[0]['quote']['times']['projected_at']='2026-10-15T12:00:05Z'
        self.store.upsert_records(rows)
        by_id={contract_id(r):r for r in self.store.records()}
        self.assertEqual(by_id[contract_id(rows[0])]['quote']['times']['projected_at'],'2026-10-15T12:00:05Z')
        self.db.execute("UPDATE current_offer SET facts=jsonb_set(facts,'{times}',(facts->'times')-'projected_at') WHERE contract_id=%s",(contract_id(rows[0]),))
        by_id={contract_id(r):r for r in self.store.records()}
        self.assertIsNone(by_id[contract_id(rows[0])]['quote']['times']['projected_at'])
        self.assertEqual(by_id[contract_id(rows[0])]['quote']['times']['source_at'],rows[0]['quote']['times']['source_at'])
        self.assertEqual(by_id[contract_id(rows[0])]['quote']['times']['received_at'],rows[0]['quote']['times']['received_at'])

    def test_source_contract_fields_no_envelopes_or_occurrence_graph(self):
        row=fixture_records()[0];p=prepare(row)
        self.assertNotIn('occurrence_match',p['quote']);self.assertNotIn('_native',p['event'])
        self.assertNotIn('combined_envelope_id',p['contract'].get('comparison_source_metadata',{}))

if __name__=='__main__':unittest.main()
