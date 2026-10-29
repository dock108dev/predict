"""Disposable SQL qualification of bounded current ownership, never acquisition."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
import unittest
from uuid import uuid4
from unittest.mock import patch
from types import SimpleNamespace
from psycopg import sql
from psycopg.errors import CheckViolation
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
        r['quote'].pop('book_confirmation',None)  # Authored original-clock ordering, no renewed confirmation.
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

    def test_large_native_batch_drains_writes_before_scope_read_barrier(self):
        original=future_records('kalshi')[0];rows=[];scopes=[]
        for i in range(512):
            row=deepcopy(original);source=row['quote']['source']
            source['native_market_id']=f'CONTROLLED-large-{i}'
            rows.append(row)
            scopes.append(dict(venue='kalshi',competition=row['event']['competition'],
                native_event_id=source['native_event_id'],native_market_id=source['native_market_id'],
                **{k:row['quote']['times'][k] for k in ('source_at','received_at')}))
        for _ in range(2):
            self.store.upsert_records(rows,scopes=scopes,authoritative=True)
            self.assertEqual(self.counts()['current_offer'],512)
        self.store.upsert_records([],scopes=[scopes[0]],authoritative=True)
        self.assertEqual(self.counts()['current_offer'],511)
        self.assertIsNone(self.db.execute('SELECT 1 FROM current_offer WHERE contract_id=%s',
            (contract_id(rows[0]),)).fetchone())

    def test_native_receipt_clock_updates_without_rewriting_unchanged_contract(self):
        rows=future_records('kalshi')
        for row in rows:
            row['comparison_source_metadata']['observed_at']=row['quote']['times']['received_at']
            row['comparison_source_metadata'].setdefault('combined_native_binding',{'version':'authored'})
        self.store.upsert_records(rows)
        before={r['id']:(r['revision'],r['position']) for r in self.db.execute('SELECT id,revision,ctid::text position FROM current_contract').fetchall()}
        later=deepcopy(rows)
        for row in later:
            row['quote']['times']['received_at']='2026-10-15T12:00:02Z'
            row['comparison_source_metadata']['observed_at']='2026-10-15T12:00:02Z'
        self.store.upsert_records(later)
        after={r['id']:(r['revision'],r['position']) for r in self.db.execute('SELECT id,revision,ctid::text position FROM current_contract').fetchall()}
        self.assertEqual(before,after)
        captured=self.store.capture(include_depth=False)['records']
        self.assertTrue(captured)
        for row in captured:
            self.assertEqual(row['comparison_source_metadata']['observed_at'],'2026-10-15T12:00:02Z')
            self.assertNotIn('observed_at_from_quote_receipt',row['comparison_source_metadata'])
        separate=deepcopy(later[0]);separate['comparison_source_metadata']['observed_at']='2026-10-15T11:30:00Z'
        self.assertEqual(prepare(separate)['contract']['comparison_source_metadata']['observed_at'],'2026-10-15T11:30:00Z')
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
        book.pop('book_confirmation',None)
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

    def test_ordered_duplicate_contract_reads_accepted_receipt_and_source_updates(self):
        row=future_records()[0]
        receipt=deepcopy(row);receipt['quote']['times']['received_at']='2026-10-15T12:01:00Z'
        older_receipt=deepcopy(row);older_receipt['quote']['times']['received_at']='2026-10-15T12:00:30Z';older_receipt['quote']['original']['value']='8.01'
        newer=deepcopy(row);newer['quote']['times'].update(source_at='2026-10-15T12:02:00Z',received_at='2026-10-15T12:02:01Z');newer['quote']['original']['value']='3.21'
        older=deepcopy(row);older['quote']['times'].update(source_at='2026-10-15T12:01:00Z',received_at='2026-10-15T12:03:01Z');older['quote']['original']['value']='8.02'
        unknown=deepcopy(row);unknown['quote']['times'].update(source_at=None,received_at='2026-10-15T12:04:01Z');unknown['quote']['original']['value']='8.03'
        self.assertEqual(self.store.upsert_records([row,receipt,older_receipt,newer,older,unknown]),2)
        saved=self.store.records()[0]['quote']
        self.assertEqual(saved['original']['value'],'3.21')
        self.assertEqual(saved['times']['source_at'],'2026-10-15T12:02:00Z')
        self.assertEqual(saved['times']['received_at'],'2026-10-15T12:02:01Z')

    def test_ordered_missing_then_older_readd_sees_deleted_offer_and_replaces_depth(self):
        row=future_records()[0];row['quote']['depth']=[dict(price='2.1',quantity='7')]
        self.store.upsert_records([row])
        missing=deepcopy(row);missing['offer_missing']=True
        missing['quote']['times'].update(source_at='2026-10-15T12:10:00Z',received_at='2026-10-15T12:10:01Z')
        readd=deepcopy(row);readd['quote']['original']['value']='2.5';readd['quote']['depth']=[dict(price='2.5',quantity='9')]
        self.assertEqual(self.store.upsert_records([missing,readd]),2)
        saved=self.store.records()[0]['quote']
        self.assertEqual(saved['original']['value'],'2.5')
        self.assertEqual(saved['times']['received_at'],row['quote']['times']['received_at'])
        self.assertEqual(saved['depth'],[dict(price='2.5',quantity='9')])
        self.assertEqual(self.counts()['current_contract'],1)

    def test_shared_event_facts_follow_accepted_input_order(self):
        first,second=future_records();first['event']['title']='First accepted event';second['event']['title']='Last accepted event'
        rejected=deepcopy(first);rejected['event']['title']='Rejected older event'
        rejected['quote']['times'].update(source_at='2026-10-15T11:00:00Z',received_at='2026-10-15T12:10:00Z')
        self.store.upsert_records([first,second,rejected])
        self.assertEqual({r['event']['title'] for r in self.store.records()},{'Last accepted event'})

    def test_later_equal_clock_conflict_rolls_back_prior_queued_updates(self):
        rows=future_records();self.store.upsert_records(rows);before=self.store.capture()
        prior=deepcopy(rows[1]);prior['quote']['times'].update(source_at='2026-10-15T12:02:00Z',received_at='2026-10-15T12:02:01Z');prior['quote']['original']['value']='2.88'
        conflict=deepcopy(rows[0]);conflict['quote']['original']['value']='3.99'
        with self.assertRaisesRegex(ValueError,'equal_clock_price_conflict'):self.store.upsert_records([prior,conflict])
        self.assertEqual(before,self.store.capture())

    def test_overlapping_scopes_preserve_all_incoming_ids_and_order_guards(self):
        first,second=future_records();third=deepcopy(first);third['quote']['source']['native_outcome_id']='authored-third-outcome'
        self.store.upsert_records([first,second,third])
        stale=deepcopy(first);stale['quote']['times'].update(source_at='2026-10-15T11:00:00Z',received_at='2026-10-15T12:10:01Z');stale['quote']['original']['value']='9'
        missing=deepcopy(second);missing['offer_missing']=True;missing['quote']['times'].update(source_at='2026-10-15T12:03:00Z',received_at='2026-10-15T12:03:01Z')
        broad=dict(venue='novig',competition='NFL',source_at='2026-10-15T12:05:00Z',received_at='2026-10-15T12:05:01Z')
        narrow=dict(broad,native_event_id=first['quote']['source']['native_event_id'],source_at='2026-10-15T12:06:00Z',received_at='2026-10-15T12:06:01Z')
        older=dict(broad,source_at='2026-10-15T12:04:00Z',received_at='2026-10-15T12:04:01Z')
        self.assertEqual(self.store.upsert_records([stale,missing],scopes=[broad,narrow,older],authoritative=True,now='2026-10-15T12:10:01Z'),2)
        self.assertEqual(self.counts()['current_contract'],2);self.assertEqual(self.counts()['current_offer'],1)
        saved=self.store.records()[0]
        self.assertEqual(contract_id(saved),contract_id(first));self.assertEqual(saved['quote']['original'],first['quote']['original'])
        guard=self.db.execute('SELECT source_order,received_order FROM current_refresh_scope WHERE scope=%s',(hashed(dict(venue='novig',competition='NFL')),)).fetchone()
        from app.storage.store import exact_time
        self.assertEqual(guard['source_order'],exact_time(broad['source_at']));self.assertEqual(guard['received_order'],exact_time(broad['received_at']))

    def native_book(self,rows):
        target=rows[0]['quote']['source']
        book=deepcopy(next(o['book'] for e in envelopes() if e['record']['kind']=='admitted_books' for o in e['record']['value']['observations'] if o['book']['raw']['ref']['market_id']==target['native_market_id']))
        book.pop('book_confirmation',None)
        book['raw'].update(exchange_at='2026-10-15T12:00:00Z',received_at='2026-10-15T12:00:01Z')
        return book

    def test_one_native_level_update_preserves_all_other_physical_rows(self):
        rows=future_records('polymarket_us');self.store.upsert_records(rows);book=self.native_book(rows)
        ladder=next(o['asks'] for o in book['outcomes'] if o['asks'] and o['asks']['levels'])
        ladder['levels']=[deepcopy(ladder['levels'][0]) for _ in range(3)]
        for i,level in enumerate(ladder['levels']):level['price']['value']=str((i+1)/10)
        self.store.replace_native_books([book])
        def tuples():
            return {(r['native_outcome_id'],r['side'],r['level']):r['tuple_id'] for r in
                self.db.execute('SELECT ctid::text AS tuple_id,* FROM current_native_depth')}
        before=tuples();ladder['levels'][1]['quantity']['value']='777'
        book['raw'].update(exchange_at='2026-10-15T12:01:00Z',received_at='2026-10-15T12:01:01Z')
        self.store.replace_native_books([book]);after=tuples()
        self.assertEqual(set(before),set(after))
        self.assertEqual(sum(before[k]!=after[k] for k in before),1)
        ladder['levels'].pop()
        book['raw'].update(exchange_at='2026-10-15T12:02:00Z',received_at='2026-10-15T12:02:01Z')
        self.store.replace_native_books([book]);shorter=tuples()
        self.assertEqual(len(shorter),len(after)-1)
        self.assertTrue(all(after[k]==shorter[k] for k in shorter))

    def test_new_source_clock_keeps_identical_depth_rows_but_changes_revision(self):
        rows=future_records('polymarket_us');self.store.upsert_records(rows);book=self.native_book(rows)
        self.store.replace_native_books([book])
        before=self.store.capture()['revision']
        def depth():
            return self.db.execute('SELECT ctid::text AS tuple_id,* FROM current_native_depth ORDER BY native_outcome_id,side,level').fetchall()
        stored=depth();self.assertTrue(stored)
        newer=deepcopy(book);newer['raw'].update(exchange_at='2026-10-15T12:01:00Z',received_at='2026-10-15T12:01:01Z')
        self.store.replace_native_books([newer])
        self.assertEqual(stored,depth())
        self.assertNotEqual(before,self.store.capture()['revision'])
        self.assertEqual(self.db.execute('SELECT source_at FROM current_native_book').fetchone()['source_at'],newer['raw']['exchange_at'])
        # Existing migrated headers have no depth hash: first observation rebuilds
        # and proves contents; the following identical observation is stable.
        self.db.execute('UPDATE current_native_book SET depth_revision=NULL')
        self.store.replace_native_books([newer]);rebuilt=depth()
        self.assertEqual(stored,rebuilt)
        self.store.replace_native_books([newer]);self.assertEqual(rebuilt,depth())

    def test_native_ordered_receipt_only_older_unknown_and_conflict_rollback(self):
        rows=future_records('polymarket_us');self.store.upsert_records(rows);book=self.native_book(rows)
        self.store.replace_native_books([book]);before=self.store.capture()
        receipt=deepcopy(book);receipt['raw']['received_at']='2026-10-15T12:01:00Z'
        older=deepcopy(book);older['raw'].update(exchange_at='2026-10-15T11:00:00Z',received_at='2026-10-15T12:02:00Z')
        unknown=deepcopy(book);unknown['raw'].update(exchange_at=None,received_at='2026-10-15T12:03:00Z')
        self.store.replace_native_books([receipt,older,unknown]);self.assertEqual(before['revision'],self.store.capture()['revision'])
        saved=self.db.execute('SELECT received_at FROM current_native_book').fetchone()
        self.assertEqual(saved['received_at'],receipt['raw']['received_at'])
        valid=deepcopy(receipt);valid['raw']['received_at']='2026-10-15T12:04:00Z'
        conflict=deepcopy(valid);next(o['asks'] for o in conflict['outcomes'] if o['asks'] and o['asks']['levels'])['levels'][0]['quantity']['value']='123.45'
        stable=self.store.capture()
        with self.assertRaisesRegex(ValueError,'equal_clock_book_conflict'):self.store.replace_native_books([valid,conflict])
        self.assertEqual(stable,self.store.capture())
        self.assertEqual(self.db.execute('SELECT received_at FROM current_native_book').fetchone()['received_at'],receipt['raw']['received_at'])

    def test_native_withdraw_then_older_readd_preserves_event_and_current_order(self):
        rows=future_records('polymarket_us');self.store.upsert_records(rows);book=self.native_book(rows);self.store.replace_native_books([book])
        closed=deepcopy(book);closed['state']='closed';closed['raw'].update(exchange_at='2026-10-15T12:10:00Z',received_at='2026-10-15T12:10:01Z')
        readd=deepcopy(book);readd['raw'].update(exchange_at='2026-10-15T11:00:00Z',received_at='2026-10-15T11:00:01Z')
        self.store.replace_native_books([closed,readd])
        self.assertEqual(self.counts()['current_offer'],0);self.assertEqual(self.counts()['current_event'],1)
        self.assertEqual(self.db.execute('SELECT source_at FROM current_native_book').fetchone()['source_at'],readd['raw']['exchange_at'])
        self.store.upsert_records(rows)
        self.assertEqual(len(self.store.records()),2);self.assertTrue(any(r['quote'].get('depth') for r in self.store.records()))

    def test_batched_native_depth_preserves_every_level_and_clock(self):
        from decimal import Decimal
        rows=future_records('polymarket_us');self.store.upsert_records(rows)
        book=self.native_book(rows)
        outcome=next(o for o in book['outcomes'] if o['asks'] and o['asks']['levels'])
        seed=outcome['asks']['levels'][0]
        levels=[]
        for i in range(260):
            level=deepcopy(seed);level['price']['value']=str(Decimal(i+1)/1000)
            level['quantity']['value']=str(i+1);levels.append(level)
        outcome['asks']['levels']=levels
        self.store.replace_native_books([book])
        saved=self.db.execute("SELECT price_value,quantity_value FROM current_native_depth WHERE native_outcome_id=%s AND side='asks' ORDER BY level",(outcome['outcome_id'],)).fetchall()
        self.assertEqual([(r['price_value'],r['quantity_value']) for r in saved],
                         [(r['price']['value'],r['quantity']['value']) for r in levels])
        raw=self.db.execute('SELECT source_at,received_at FROM current_native_book').fetchone()
        self.assertEqual((raw['source_at'],raw['received_at']),(book['raw']['exchange_at'],book['raw']['received_at']))

    def test_late_native_sql_error_rolls_back_before_publication(self):
        from app.storage.scanner_publication import subscribe,transaction
        rows=future_records('polymarket_us');self.store.upsert_records(rows);book=self.native_book(rows);self.store.replace_native_books([book])
        before=self.store.capture();events=[];close=subscribe(events.append)
        changed=deepcopy(book);changed['raw'].update(exchange_at='2026-10-15T12:10:00Z',received_at='2026-10-15T12:10:01Z')
        ladder=next(o['asks'] for o in changed['outcomes'] if o['asks'] and o['asks']['levels'])
        level=deepcopy(ladder['levels'][0]);ladder['levels']=[deepcopy(level) for _ in range(260)];ladder['levels'][-1]['quantity']['value']='123.456789'
        self.db.execute("ALTER TABLE current_native_depth ADD CONSTRAINT authored_pipeline_late_failure CHECK(quantity_value<>'123.456789')")
        try:
            with self.assertRaises(CheckViolation):
                with transaction(self.db):self.store.replace_native_books([changed])
            self.assertEqual(events,[]);self.assertEqual(before,self.store.capture())
        finally:
            close();self.db.execute('ALTER TABLE current_native_depth DROP CONSTRAINT authored_pipeline_late_failure')

    def test_nested_transaction_publishes_only_after_outer_commit_and_never_rollback(self):
        from app.storage.scanner_publication import subscribe,transaction
        rows=future_records();events=[];close=subscribe(events.append)
        epoch=self.store.capture()['epoch']
        try:
            with transaction(self.db):
                with transaction(self.db):self.store.upsert_records(rows)
                self.assertEqual(events,[])
                with connect(self.name) as reader:self.assertEqual(CurrentRowStore(reader).records(),[])
            saved=self.store.capture();self.assertEqual(len(events),1)
            self.assertEqual(events[0]['current_rows_revision'],saved['revision']);self.assertEqual(events[0]['epoch'],epoch)
            changed=deepcopy(rows);changed[0]['quote']['times'].update(source_at='2026-10-15T12:02:00Z',received_at='2026-10-15T12:02:01Z');changed[0]['quote']['original']['value']='3.21'
            with self.assertRaisesRegex(RuntimeError,'authored rollback'):
                with transaction(self.db):
                    self.store.upsert_records(changed)
                    raise RuntimeError('authored rollback')
            self.assertEqual(len(events),1);self.assertEqual(saved,self.store.capture())
            with self.db.transaction():
                with transaction(self.db):self.store.upsert_records(changed)
            self.assertEqual(len(events),1);self.assertEqual(self.store.capture()['epoch'],epoch)
            self.assertNotEqual(saved['revision'],self.store.capture()['revision'])
        finally:close()

    @patch('app.storage.current_rows.utc', return_value=AT)
    def test_direct_sink_native_and_aggregate_are_atomic_without_archives(self, storage_clock):
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
        with patch('app.collection.current_database.connect',owner_connect), \
             patch('app.collection.current_database.utc',return_value=AT) as clock:
            sink.commit(dict(header,type='coverage_inventory',inventory=cats,generation=1,previous_generation=None),states)
            observation=deepcopy(next(o for e in envelopes() if e['record']['kind']=='admitted_books' and e['record']['source']==source for o in e['record']['value']['observations']))
            observation['book'].pop('book_confirmation',None)
            sink.commit(dict(observation,**header),states)
            native=self.store.records();self.assertTrue(any(r['quote'].get('depth') for r in native))
            one_sided=deepcopy(observation);one_sided['book']['outcomes'][0]['asks']=None
            one_sided['book']['raw'].update(exchange_at='2026-10-15T12:10:00Z',received_at='2026-10-15T12:10:01Z')
            clock.return_value=storage_clock.return_value=one_sided['book']['raw']['received_at']
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

    def test_reopen_preserves_epoch_prices_and_clocks(self):
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
        # Routine data-process restarts preserve the owner data epoch. Runtime
        # identity and result bindings separately revoke old selected authority.
        self.assertEqual(len({before['epoch'],first,second}),1)
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
