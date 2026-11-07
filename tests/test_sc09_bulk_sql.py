"""Restartable native census and raw evidence independent of semantic admission."""
from copy import deepcopy
from unittest import TestCase, skipUnless
from unittest.mock import patch

from app.collection.bulk_checkpoint import Checkpoint, save_images
from tests import test_sc02_sql as base
from tests.test_current_service import native_fixture


@skipUnless(base.SOCKET, 'Disposable SQL harness required')
class Checkpoints(TestCase):
    connect = classmethod(base.SQL.connect.__func__)
    setUpClass = classmethod(base.SQL.setUpClass.__func__)
    tearDownClass = classmethod(base.SQL.tearDownClass.__func__)

    def setUp(self):
        # Every test owns independent evidence inside the disposable class DB.
        with self.connect() as db:
            db.execute('TRUNCATE current_acquisition_page,current_acquisition_query,current_acquisition_image_parts,'
                'current_acquisition_market,current_acquisition_aggregate,current_acquisition_alternate,'
                'current_acquisition_event_census,current_acquisition_failure,current_native_market_recovery,current_native_catalog_recovery,data_runtime')

    def test_page_codec_preserves_original_receipt_restart_and_raw_reference_with_noop_retries(self):
        import json
        from psycopg.types.json import Jsonb
        from app.collection.bulk_checkpoint import read_page
        body=dict(markets=[dict(id=str(n),title='完整 original market '+str(n),
            rules='Exact source settlement terms. '*30,quantity='9007199254740993.00001')for n in range(250)])
        original=dict(status=200,received_at='2026-11-04T12:00:00.123456789Z',
            body=body,json_text=json.dumps(body,ensure_ascii=False,indent=2),headers=[['date','original header']],number=10**80)
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect),self.connect()as db:
            checkpoint=Checkpoint('kalshi',{'sports':['NFL']});key,_=checkpoint.query('/markets',{})
            ref=dict(source='kalshi',query_key=key,position=0)
            db.execute('INSERT INTO current_acquisition_page VALUES(%s,%s,0,%s)',('kalshi',key,Jsonb(original)))
            before=db.execute('SELECT pg_column_size(receipt) n FROM current_acquisition_page').fetchone()['n']
            self.assertEqual(checkpoint.query('/markets',{})[1],[original])
            checkpoint.page(key,0,original,False)
            row=db.execute('SELECT receipt,ctid::text tuple_id,pg_column_size(receipt) n FROM current_acquisition_page').fetchone()
            self.assertIn('_predict_storage',row['receipt']);self.assertLess(row['n'],before)
            for _ in range(10):checkpoint.page(key,0,original,False)
            self.assertEqual(db.execute('SELECT ctid::text tuple_id FROM current_acquisition_page').fetchone()['tuple_id'],row['tuple_id'])
            self.assertEqual(Checkpoint('kalshi',{'sports':['NFL']}).query('/markets',{})[1],[original])
            self.assertEqual(read_page(ref),original)
            with self.assertRaisesRegex(ValueError,'unavailable'):read_page(dict(ref,source='polymarket_us'))
            damaged=deepcopy(row['receipt']);damaged['_predict_storage']['sha256']='f'*64
            db.execute('UPDATE current_acquisition_page SET receipt=%s',(Jsonb(damaged),))
            with self.assertRaisesRegex(ValueError,'integrity'):read_page(ref)
            db.execute('UPDATE current_acquisition_page SET receipt=%s',(Jsonb(original),))
            self.assertEqual(read_page(ref),original)
            checkpoint.finish();checkpoint.begin()
            with self.assertRaisesRegex(ValueError,'unavailable'):read_page(ref)

    def test_reimaging_preserves_both_exact_observations_until_atomic_replacement(self):
        from app.storage.current_rows import CurrentRowStore
        from tests.test_d03_current_rows import future_records
        records=future_records('polymarket_us')
        source=records[0]['quote']['source']
        key=('polymarket_us',source['native_event_id'],source['native_market_id'])
        with self.connect() as db:
            rows=CurrentRowStore(db)
            db.execute("DELETE FROM current_event WHERE provider=%s AND native_event_id=%s",key[:2])
            rows.upsert_records(records)
            def offers():
                return db.execute("""SELECT c.native_side,o.price_value,o.source_at,o.received_at,
                    o.facts->>'state' state FROM current_offer o JOIN current_contract c
                    ON c.id=o.contract_id WHERE c.venue=%s AND c.native_market_id=%s
                    ORDER BY c.native_side""",(key[0],key[2])).fetchall()
            before=offers()
            self.assertEqual([r['native_side'] for r in before],['Long','Short'])
            rows.withdraw_native_markets([key],reimaging=True)
            retained=[dict(r,state='resyncing') for r in before]
            self.assertEqual(offers(),retained)
            with self.assertRaisesRegex(ValueError,'rollback'),db.transaction():
                rows.upsert_records(records)
                raise ValueError('rollback')
            self.assertEqual(offers(),retained)
            rows.upsert_records(records)
            self.assertEqual(offers(),before)
            rows.withdraw_native_markets([key])
            self.assertEqual(offers(),[])

    def test_resume_only_skips_exact_completed_event_details(self):
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect):
            checkpoint=Checkpoint('polymarket_us',{'sports':['NFL']})
            for path,params,complete in [('/v1/events/a',{},True),('/v1/events/b',{},False),
                    ('/v1/events/c',{'variant':'other'},True),('/v1/events',{},True)]:
                key,_=checkpoint.query(path,params)
                checkpoint.page(key,0,{'path':path},complete)
            self.assertEqual(checkpoint.completed_details(),{'/v1/events/a'})
            self.assertFalse(Checkpoint('polymarket_us',{}).completed_details())
            checkpoint.finish()
            self.assertFalse(checkpoint.completed_details())

    def test_packed_recovery_retains_exact_catalog_and_parsed_clocks(self):
        from datetime import datetime,timezone,timedelta
        from app.collection.native_recovery import save,load,decode,market_value
        cat,book=native_fixture();cat['events'][0]['scheduled_start']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        mid=book['raw']['ref']['market_id']
        cat['markets'][0]['title']='Exact recovery fixture'
        cat['markets'][0]['literal_evidence']='unchanged original witness '*3000
        value=dict(raw=dict(book['raw'],source='fixture'),title='fixture',market_type='unknown',state='active',period='full_game',canonical_id=None,
            outcomes=[dict(native_id=o['outcome_id'],label=o['outcome_id'],canonical_id=None) for o in book['outcomes']])
        market=decode(value,'kalshi')
        with patch('app.collection.native_recovery.connect',side_effect=self.connect),self.connect() as db:
            save('kalshi','scope',cat,{mid:market})
            row=db.execute('SELECT metadata,display_metadata,receipt_fields FROM current_native_market_recovery WHERE market_id=%s',(mid,)).fetchone()
            self.assertIn('_predict_storage',row['metadata'])
            self.assertEqual(market_value(row['metadata'],row['receipt_fields']),cat['markets'][0])
            self.assertEqual(row['display_metadata']['title'],cat['markets'][0]['title'])
            restored,parsed,_=load('kalshi','scope')
            self.assertEqual(restored,cat);self.assertEqual(parsed[mid],market)
            self.assertEqual(parsed[mid].raw.received_at,market.raw.received_at)
            cat['markets'][0]['literal_evidence']+=' material change'
            save('kalshi','scope',cat,{mid:market})
            self.assertEqual(load('kalshi','scope')[0],cat)

    def test_identical_raw_checkpoint_is_no_physical_update_but_context_advances(self):
        _,book=native_fixture();mid=book['raw']['ref']['market_id']
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect),self.connect() as db:
            save_images('kalshi',[book],'pending',contexts={mid:('owner',1,'first')})
            def row():return db.execute('SELECT p.ctid::text tuple,i.image,i.persisted_at,i.runtime_id,i.connection_generation,i.census_generation FROM current_acquisition_image i JOIN current_acquisition_image_parts p USING(source,event_id,market_id)').fetchone()
            before=row()
            for _ in range(10):save_images('kalshi',[book],'pending',contexts={mid:('owner',1,'first')})
            self.assertEqual(row(),before)
            save_images('kalshi',[book],'pending',contexts={mid:('owner',2,'second')})
            after=row();self.assertNotEqual(after['tuple'],before['tuple'])
            self.assertEqual(after['image'],book)
            self.assertEqual(after['persisted_at'],before['persisted_at'])
            self.assertEqual(after['connection_generation'],2)

    def test_final_disposition_and_superseded_image_do_not_encode_depth_again(self):
        _,book=native_fixture();book['raw']['ref']['market_id']='lightweight-disposition'
        mid=book['raw']['ref']['market_id']
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect):
            save_images('kalshi',[book],'pending',contexts={mid:('runtime',3,'census')})
            with self.connect() as db:
                before=db.execute('SELECT image,runtime_id,connection_generation,census_generation FROM current_acquisition_image WHERE market_id=%s',(mid,)).fetchone()
            with patch('app.collection.bulk_checkpoint.Jsonb',side_effect=AssertionError('depth encoded again')):
                save_images('kalshi',[book],'pending',ensure_only=True)
                save_images('kalshi',[book],'admitted',known_persisted=True)
                old=deepcopy(book);old['raw']['received_at']='2000-01-01T00:00:00Z'
                save_images('kalshi',[old],'pending')
                save_images('kalshi',[old],'rejected',known_persisted=True)
            with self.connect() as db:
                after=db.execute('SELECT image,runtime_id,connection_generation,census_generation,disposition FROM current_acquisition_image WHERE market_id=%s',(mid,)).fetchone()
            self.assertEqual(after.pop('disposition'),'admitted')
            self.assertEqual(before,after)

    def test_failed_or_successful_old_attempt_cannot_finish_new_pending_image(self):
        _,first=native_fixture()
        second=deepcopy(first)
        second['raw']['received_at']='2099-01-01T00:00:00+00:00'
        mid=first['raw']['ref']['market_id']
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect),self.connect() as db:
            save_images('kalshi',[first],'pending',contexts={mid:('owner',1,'first')})
            save_images('kalshi',[second],'pending',contexts={mid:('owner',2,'second')})
            for result in ('rejected','admitted'):
                save_images('kalshi',[first],result,known_persisted=True)
                row=db.execute('SELECT disposition,census_generation,image FROM current_acquisition_image').fetchone()
                self.assertEqual((row['disposition'],row['census_generation'],row['image']),('pending','second',second))
            save_images('kalshi',[second],'admitted',known_persisted=True)
            self.assertEqual(db.execute('SELECT disposition FROM current_acquisition_image').fetchone()['disposition'],'admitted')

    def test_concurrent_raw_and_derived_writers_lock_images_in_same_order(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        _,book=native_fixture();books=[]
        for n in range(80):
            value=deepcopy(book);value['raw']['ref']['market_id']='concurrent-'+str(n)
            books.append(value)
        barrier=Barrier(2)
        def write(values,state):
            barrier.wait(timeout=5)
            for _ in range(4):save_images('kalshi',values,state)
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect):
            with ThreadPoolExecutor(max_workers=2) as pool:
                left=pool.submit(write,books,'pending')
                right=pool.submit(write,list(reversed(books)),'admitted')
                left.result(timeout=15);right.result(timeout=15)
            with self.connect() as db:
                rows=db.execute("SELECT disposition FROM current_acquisition_image WHERE market_id LIKE 'concurrent-%'").fetchall()
            self.assertEqual(len(rows),80)
            self.assertTrue(all(r['disposition']=='admitted' for r in rows))

    def test_atomic_catalog_restart_restores_locators_and_original_clocks_only(self):
        from datetime import datetime,timezone,timedelta
        from app.collection.native_recovery import save,load,decode
        cat,book=native_fixture();cat['events'][0]['scheduled_start']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        value=dict(raw=dict(book['raw'],source='fixture'),title='fixture',market_type='unknown',state='active',period='full_game',canonical_id=None,
                   outcomes=[dict(native_id=o['outcome_id'],label=o['outcome_id'],canonical_id=None) for o in book['outcomes']])
        market=decode(value,'kalshi');mid=market.raw.ref.market_id
        with patch('app.collection.native_recovery.connect',side_effect=self.connect):
            save('kalshi','scope',cat,{mid:market})
            restored,parsed,_=load('kalshi','scope')
            self.assertEqual(restored,cat)
            self.assertEqual(parsed[mid],market)
            self.assertIsNone(load('kalshi','other-scope'))
            # A failed replacement cannot erase the previous complete snapshot.
            invalid=deepcopy(cat);invalid['markets'].append(invalid['markets'][0])
            with self.assertRaises(Exception):save('kalshi','scope',invalid,{mid:market})
            self.assertEqual(load('kalshi','scope')[1][mid],market)
            cat['events'][0]['scheduled_start']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
            save('kalshi','scope',cat,{mid:market})
            self.assertEqual(load('kalshi','scope')[1],{})

    def test_raw_generation_is_preserved_by_same_receipt_admission_and_not_inferred_for_new_image(self):
        _,book=native_fixture();book['raw']['ref']['market_id']+='-generation';mid=book['raw']['ref']['market_id']
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect):
            save_images('kalshi',[book],'pending',contexts={mid:('runtime',3,'census')})
            save_images('kalshi',[book],'admitted')
            with self.connect() as db:
                row=db.execute('SELECT * FROM current_acquisition_image WHERE market_id=%s',(mid,)).fetchone()
                self.assertEqual((row['runtime_id'],row['connection_generation'],row['census_generation']),('runtime',3,'census'))
            newer=deepcopy(book);newer['raw']['received_at']='2099-01-01T00:00:00+00:00'
            save_images('kalshi',[newer],'pending')
            with self.connect() as db:
                row=db.execute('SELECT * FROM current_acquisition_image WHERE market_id=%s',(mid,)).fetchone()
                self.assertIsNone(row['runtime_id'])

    def test_current_connection_accounting_excludes_disconnect_invalid_and_stale_runtime(self):
        from psycopg.types.json import Jsonb
        from app.collection.acquisition_report import report
        _,book=native_fixture();book['raw']['ref']['market_id']+='-connection'
        ref=book['raw']['ref'];mid=ref['market_id']
        state=dict(connections=3,stream_connected=True,invalid_current_market_ids=[])
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect):
            save_images('kalshi',[book],'pending',contexts={mid:('connection-runtime',3,'census')})
        with self.connect() as db:
            db.execute("INSERT INTO current_acquisition_market (source,event_id,market_id,sport,family,generation,observed_at,disposition,metadata) VALUES ('kalshi',%s,%s,'NFL','moneyline','census',now(),'subscribed','{}')",(ref['event_id'],mid))
            db.execute("INSERT INTO data_runtime (runtime_id,owner_pid,started_at,heartbeat_at,state,config,source_status,dispatch,status,fingerprint) VALUES ('connection-runtime',1,now(),now(),'running','{}','{}',true,%s,'fixture')",(Jsonb(dict(metrics=dict(kalshi=state))),))
            def count():
                cell=next(c for c in report(db)['cells'] if (c['venue'],c['sport'],c['family'])==('kalshi','NFL','moneyline'))
                return cell['current_connection_images']
            self.assertEqual(count(),1)
            for changed in (dict(state,stream_connected=False),dict(state,invalid_current_market_ids=[mid]),dict(state,connections=4)):
                db.execute('UPDATE data_runtime SET status=%s',(Jsonb(dict(metrics=dict(kalshi=changed))),))
                self.assertEqual(count(),0)
            db.execute("UPDATE data_runtime SET status=%s,heartbeat_at=now()-interval '1 minute'",(Jsonb(dict(metrics=dict(kalshi=state))),))
            self.assertEqual(count(),0)
            sync=dict(state='synchronized',generation=3,continuity_intact=True)
            def synchronized(changed):
                panel=dict(provider='kalshi',metrics=dict(state,synchronization=changed))
                db.execute("UPDATE data_runtime SET heartbeat_at=clock_timestamp(),status=%s",(Jsonb(dict(metrics={},sources=[panel])),))
                cell=next(c for c in report(db)['cells'] if (c['venue'],c['sport'],c['family'])==('kalshi','NFL','moneyline'))
                return cell['synchronized_market_images']
            self.assertEqual(synchronized(sync),1)
            self.assertEqual(synchronized(dict(sync,state='catching_up')),0)
            self.assertEqual(synchronized(dict(sync,generation=4)),0)
            self.assertEqual(synchronized(dict(sync,state='disconnected')),0)
            db.execute('DELETE FROM data_runtime')

    def test_alternate_prior_cycle_receipt_is_not_current_census_acquisition(self):
        from psycopg.types.json import Jsonb
        from app.collection.acquisition_report import report
        with self.connect() as db:
            db.execute('INSERT INTO current_acquisition_event_census VALUES (%s,%s,now(),%s,%s)',
                ('NFL','new-cycle','census',Jsonb([dict(id='a'),dict(id='b')])))
            for eid,cycle in [('a','old-cycle'),('b','new-cycle')]:
                payload=dict(id=eid,bookmakers=[dict(key='novig',markets=[dict(key='alternate_spreads',outcomes=[dict(name='A',point=-2.5,price=2)])])])
                db.execute('INSERT INTO current_acquisition_alternate VALUES (%s,%s,now(),%s,%s,%s,%s)',
                    ('NFL',eid,cycle,'receipt','received_pending_qualification',Jsonb(payload)))
            result=report(db)
        cell=next(c for c in result['cells'] if (c['venue'],c['sport'],c['family'])==('novig','NFL','spread'))
        self.assertEqual(cell['alternate_received'],2)
        self.assertEqual(cell['alternate_current_cycle_received'],1)
        self.assertEqual(cell['alternate_prior_cycle_retained'],1)
        self.assertEqual(sum(e['current_cycle_received'] for e in result['alternate_events']),1)
        self.assertFalse(result['qualified_99_percent'])
        self.assertTrue(all(e['pregame_at_census'] is None for e in result['alternate_events']))
        self.assertEqual(next(e for e in result['alternate_events'] if e['event_id']=='a')['reason'],'event_start_unknown')

    def test_started_absence_is_explained_without_shrinking_missing_denominator(self):
        from app.collection.acquisition_report import report
        from psycopg.types.json import Jsonb
        with self.connect() as db:
            def cell():return next(c for c in report(db)['cells'] if (c['venue'],c['sport'],c['family'])==('kalshi','NHL','total'))
            before=cell()
            for mid,start,withdrawn in [('past','2000-01-01T00:00:00Z',False),('future','2099-01-01T00:00:00Z',False),('closed','2000-01-01T00:00:00Z',True)]:
                db.execute("INSERT INTO current_acquisition_market (source,event_id,market_id,sport,family,generation,observed_at,withdrawn,disposition,metadata) VALUES ('kalshi','scope-event',%s,'NHL','total','scope',now(),%s,%s,%s)",
                    ('scope-'+mid,withdrawn,'confirmed_closed' if withdrawn else 'suspected_absent',Jsonb(dict(occurrence_datetime=start))))
            after=cell()
            self.assertEqual(after['known_markets'],before['known_markets']+2)
            self.assertEqual(after.get('current_connection_missing',0),before.get('current_connection_missing',0)+4)
            self.assertEqual(after['suspected_absent_started_by_retained_schedule'],before.get('suspected_absent_started_by_retained_schedule',0)+1)
            self.assertEqual(after['suspected_absent_pregame_by_retained_schedule'],before.get('suspected_absent_pregame_by_retained_schedule',0)+1)
            self.assertEqual(after['confirmed_closed_markets'],before.get('confirmed_closed_markets',0)+1)
            self.assertFalse(report(db)['qualified_99_percent'])

    def test_restart_keeps_exact_page_and_publication_starts_new_census(self):
        with patch('app.collection.bulk_checkpoint.connect', side_effect=self.connect):
            first = Checkpoint('kalshi', {'sports': ['NFL']})
            key, pages = first.query('/trade-api/v2/events', {'series_ticker': 'fixture'})
            self.assertEqual(pages, [])
            receipt = {'body_sha256': 'original', 'cursor': 'second'}
            first.page(key, 0, receipt, False)
            restart = Checkpoint('kalshi', {'sports': ['NFL']})
            restart.begin()
            self.assertEqual(restart.query('/trade-api/v2/events', {'series_ticker': 'fixture'})[1], [receipt])
            restart.page(key, 1, {'cursor': ''}, True)
            restart.finish()
            # Last complete census remains inspectable until a new pass begins.
            self.assertEqual(len(restart.query('/trade-api/v2/events', {'series_ticker': 'fixture'})[1]), 2)
            restart.begin()
            self.assertEqual(restart.query('/trade-api/v2/events', {'series_ticker': 'fixture'})[1], [])

    def test_rejected_image_survives_restart_and_older_receipt_cannot_replace(self):
        _, book = native_fixture()
        with patch('app.collection.bulk_checkpoint.connect', side_effect=self.connect):
            save_images('kalshi', [book], 'pending')
            save_images('kalshi', [book], 'rejected')
            # Independent raw writes cannot downgrade an equal-clock final disposition.
            save_images('kalshi', [book], 'pending')
            older = deepcopy(book)
            older['raw']['received_at'] = '2000-01-01T00:00:00Z'
            save_images('kalshi', [older], 'admitted')
            with self.connect() as db:
                row = db.execute('SELECT disposition,image FROM current_acquisition_image WHERE source=%s AND market_id=%s', ('kalshi',book['raw']['ref']['market_id'])).fetchone()
            self.assertEqual(row['disposition'], 'rejected')
            self.assertEqual(row['image'], book)

    def test_moving_census_absence_is_not_withdrawal_and_reappearance_clears_suspicion(self):
        from app.collection.bulk_checkpoint import save_census
        from app.collection.acquisition_report import report
        events=[dict(id='e',competition='NFL')]
        markets=[dict(id=m,event_id='e',market_type='spread',_native=dict(id=m)) for m in ('one','two')]
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect):
            save_census('polymarket_us',events,markets,{'one'})
            save_census('polymarket_us',events,markets[1:]+[dict(markets[0],id='new')],{'two','new'})
            with self.connect() as db:
                rows=list(db.execute("SELECT market_id,withdrawn FROM current_acquisition_market WHERE source='polymarket_us' ORDER BY market_id"))
                result=report(db)
        self.assertEqual(rows,[dict(market_id='new',withdrawn=False),dict(market_id='one',withdrawn=False),dict(market_id='two',withdrawn=False)])
        self.assertEqual(len(result['cells']),90)
        cell=next(c for c in result['cells'] if (c['venue'],c['sport'],c['family'])==('polymarket_us','NFL','spread'))
        self.assertEqual(cell['known_markets'],3)
        self.assertEqual(len(cell['missing_markets']),3)
        self.assertIsNone(cell['offered_price_units'])
        self.assertFalse(result['qualified_99_percent'])

        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect):
            save_census('polymarket_us',events,markets[1:],{'two'})
            with self.connect() as db:
                row=db.execute("SELECT * FROM current_acquisition_market WHERE market_id='one'").fetchone()
                self.assertFalse(row['withdrawn'])
                self.assertEqual(row['missing_passes'],2)
                self.assertEqual(row['disposition'],'suspected_absent')
            save_census('polymarket_us',events,markets,{'one','two'})
            with self.connect() as db:
                row=db.execute("SELECT * FROM current_acquisition_market WHERE market_id='one'").fetchone()
                self.assertEqual(row['missing_passes'],0)
                self.assertIsNone(row['absent_since'])
            closed=dict(markets[0],_native=dict(id='one',closed=True))
            save_census('polymarket_us',events,[closed,markets[1]],{'two'})
            with self.connect() as db:
                row=db.execute("SELECT * FROM current_acquisition_market WHERE market_id='one'").fetchone()
                self.assertTrue(row['withdrawn'])
                self.assertEqual(row['disposition'],'confirmed_closed')


    def test_malformed_frame_retention_is_opaque_bounded_and_not_an_image(self):
        from app.collection.bulk_checkpoint import save_failure
        from app.collection.current_sink import utc
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect):
            for i in range(70):
                save_failure('kalshi',b'<unsafe malformed>'+str(i).encode(),utc(),2,'decode')
            with self.connect() as db:
                rows=list(db.execute("SELECT * FROM current_acquisition_failure WHERE source='kalshi'"))
                self.assertEqual(len(rows),64)
                self.assertEqual({r['disposition'] for r in rows},{'unusable_not_math_eligible'})
                self.assertTrue(all(bytes(r['body']).startswith(b'<unsafe malformed>') for r in rows))
            with self.assertRaises(ValueError):save_failure('kalshi',b'x'*262145,utc(),2,'decode')

    def test_split_evidence_turnover_reuses_toast_without_losing_receipts_or_provenance(self):
        from datetime import datetime,timezone,timedelta
        from hashlib import sha256
        from psycopg.types.json import Jsonb
        _,book=native_fixture();mid=book['raw']['ref']['market_id']
        book['raw']['json_text']=''.join(sha256(str(i).encode()).hexdigest() for i in range(300))
        book['outcomes'][0]['literal_depth']=[sha256(str(i+300).encode()).hexdigest() for i in range(300)]
        at=datetime.now(timezone.utc)
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect),self.connect() as db:
            db.execute('CREATE TEMP TABLE whole_image(i integer PRIMARY KEY,image jsonb,disposition text)')
            def toast(rel):
                db.execute('SELECT pg_stat_force_next_flush()');db.execute('SELECT pg_stat_clear_snapshot()')
                return db.execute('SELECT sum(pg_stat_get_tuples_inserted(c.reltoastrelid)) n FROM pg_class c WHERE c.oid IN (SELECT relid FROM pg_partition_tree(%s::regclass) WHERE isleaf) OR c.oid=%s::regclass',(rel,rel)).fetchone()['n']
            first=last=None
            for i in range(16):
                book['raw']['received_at']=(at+timedelta(seconds=i)).isoformat()
                book['book_confirmation']={'confirmed_at':book['raw']['received_at'],'literal':str(i)}
                if i==8:book['outcomes'][0]['literal_depth'].reverse()
                if i==12:book['raw']['json_text']+=' exact wire change'
                db.execute("INSERT INTO whole_image VALUES(1,%s,'pending') ON CONFLICT(i) DO UPDATE SET image=excluded.image,disposition='pending'",(Jsonb(book),))
                save_images('kalshi',[book],'pending',ensure_only=True)
                save_images('kalshi',[book],'admitted',known_persisted=True)
                # Delayed raw writer carries the generation for this exact
                # receipt, while a conflicting same-clock callback cannot
                # replace the finalized image or attach its different context.
                save_images('kalshi',[book],'pending',contexts={mid:('owner',2,'census')})
                bad=deepcopy(book);bad['raw']['json_text']+='wrong'
                save_images('kalshi',[bad],'pending',contexts={mid:('other',3,'crossed')})
                row=db.execute('SELECT * FROM current_acquisition_image').fetchone()
                self.assertEqual(row['image'],book)
                self.assertEqual((row['disposition'],row['runtime_id'],row['connection_generation'],row['census_generation']),('admitted','owner',2,'census'))
                if last:self.assertGreater(row['persisted_at'],last)
                last=row['persisted_at']
                if i==0:first=[toast('current_acquisition_image_parts'),toast('whole_image')]
            writes=[int(toast(rel)-n) for rel,n in zip(('current_acquisition_image_parts','whole_image'),first)]
            self.assertLess(writes[0]*3,writes[1],writes)
            print('receipt/depth/wire turnover TOAST inserts (parts,whole):',writes)

    def test_recovery_complete_replacement_separates_receipts_legacy_and_retirement(self):
        from datetime import datetime,timezone,timedelta
        from app.collection.native_recovery import save,load,decode,encode
        from app.storage.recovery_codec import freeze
        from psycopg.types.json import Jsonb
        cat,book=native_fixture();cat['events'][0]['scheduled_start']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        mid=book['raw']['ref']['market_id'];m=next(m for m in cat['markets'] if m['id']==mid)
        m['literal']='精確 receipt body '*3000;m['provenance']=[{'receipt':'original'}]
        old=dict(m,id='not-seen-again',inventory_recovery_disposition='suspected_absent')
        cat['markets'].append(old)
        value=dict(raw=dict(book['raw'],json_text='{"market":{}, "source_receipt_sha256": "first"}',source='fixture'),title='fixture',market_type='unknown',state='active',period='full_game',canonical_id=None,
            outcomes=[dict(native_id=o['outcome_id'],label=o['outcome_id'],canonical_id=None) for o in book['outcomes']])
        obj=decode(value,'kalshi')
        with patch('app.collection.native_recovery.connect',side_effect=self.connect),self.connect() as db:
            save('kalshi','scope',cat,{mid:obj})
            db.execute('UPDATE current_native_market_recovery SET metadata=%s,receipt_fields=NULL WHERE market_id=%s',(Jsonb(freeze(old)),old['id']))
            self.assertEqual(save('kalshi','scope',cat,{mid:obj})['writes'],0)
            m['provenance']=[{'receipt':'new'}];value['raw']['json_text']=value['raw']['json_text'].replace('first','second')
            value['raw']['received_at']=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat();obj=decode(value,'kalshi')
            r=save('kalshi','scope',cat,{mid:obj})
            self.assertEqual((r['writes'],r['receipt_only']),(1,1))
            restored,parsed,_=load('kalshi','scope')
            self.assertEqual(sorted(restored['markets'],key=lambda m:m['id']),sorted(cat['markets'],key=lambda m:m['id']))
            self.assertEqual(encode(parsed[mid]),encode(obj))
            self.assertIsNone(db.execute('SELECT receipt_fields FROM current_native_market_recovery WHERE market_id=%s',(old['id'],)).fetchone()['receipt_fields'])
            cat['markets'].remove(old);m['literal']+=' new catalog fact'
            r=save('kalshi','scope',cat,{mid:obj});self.assertEqual((r['retired'],r['payload_changes']),(1,1))
            self.assertEqual(load('kalshi','scope')[0]['markets'],cat['markets'])

    def test_repeat_converted_native_catalogs_over_equal_populations(self):
        """Opt-in real-shaped turnover in disposable SQL, including retired IDs."""
        import json
        import os
        from pathlib import Path
        from app.collection import native_recovery as recovery
        fixture=os.environ.get('L05_CONVERTED_CATALOG')
        if not fixture:self.skipTest('Requires bounded captured recovery population')
        data=json.loads(Path(fixture).read_text())
        samples=[]
        def footprint(db):
            query="""SELECT c.oid,c.reltoastrelid,pg_relation_size(c.oid) heap,pg_indexes_size(c.oid) indexes,
                pg_total_relation_size(c.reltoastrelid) overflow,pg_total_relation_size(c.oid) total
                FROM pg_class c JOIN pg_inherits i ON i.inhrelid=c.oid
                WHERE i.inhparent='current_native_market_recovery'::regclass"""
            parts=db.execute(query).fetchall()
            totals={k:sum(r[k] for r in parts) for k in ('heap','indexes','overflow','total')}
            totals['live_payload']=db.execute("""SELECT sum(pg_column_size(metadata)+coalesce(pg_column_size(parsed),0)+
                coalesce(pg_column_size(receipt_fields),0)) n FROM current_native_market_recovery""").fetchone()['n']
            totals['free_and_dead']=sum(db.execute('SELECT free_space+dead_tuple_len reusable FROM pgstattuple(%s::oid::regclass)',
                (oid,)).fetchone()['reusable'] for row in parts for oid in (row['oid'],row['reltoastrelid']) if oid)
            return totals
        with patch.object(recovery,'connect',side_effect=self.connect),self.connect() as db:
            db.execute('CREATE EXTENSION IF NOT EXISTS pgstattuple')
            for source,values in data.items():
                markets=values['markets']
                parsed={key:recovery.decode(value,source) for key,value in values['parsed'].items()}
                catalog=dict(events=values['events'],markets=markets)
                recovery.save(source,'turnover',catalog,parsed)
                for cycle in range(3):
                    before=footprint(db)
                    for market in markets[:16]:
                        market['provenance']={'original':market.get('provenance'),'fixture_receipt':cycle}
                    for market in markets[16:24]:
                        market['title']=str(market.get('title',''))+str(cycle)
                    old=markets[-1]['id']
                    self.assertNotIn(old,parsed)
                    markets[-1]=dict(markets[-1],id=old+'-replacement')
                    with db.transaction():
                        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                        visible=db.execute('SELECT market_id FROM current_native_market_recovery WHERE source=%s ORDER BY 1',(source,)).fetchall()
                        self.assertIn({'market_id':old},visible)
                        stats=recovery.save(source,'turnover',catalog,parsed)
                        self.assertEqual(db.execute('SELECT market_id FROM current_native_market_recovery WHERE source=%s ORDER BY 1',(source,)).fetchall(),visible)

                    self.assertEqual((stats['receipt_only'],stats['payload_changes'],stats['new'],stats['retired'],
                        stats['unchanged'],stats['writes'],stats['legacy_conversions']),
                        (16,8,1,1,len(markets)-25,25,0))
                    saved=db.execute('SELECT market_id,metadata,parsed,receipt_fields FROM current_native_market_recovery WHERE source=%s',(source,)).fetchall()
                    self.assertEqual({r['market_id']:recovery.market_value(r['metadata'],r['receipt_fields']) for r in saved},
                                     {m['id']:m for m in markets})
                    self.assertEqual({r['market_id']:recovery.parsed_value(r['parsed'],r['receipt_fields']) for r in saved if r['parsed']},values['parsed'])
                    self.assertEqual(recovery.save(source,'turnover',catalog,parsed)['writes'],0)
                    samples.append(dict(source=source,cycle=cycle,before=before,after=footprint(db),**stats))
                db.execute('TRUNCATE current_native_market_recovery,current_native_catalog_recovery')
        print('Complete converted catalog turnover:',json.dumps(samples))
