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
            db.execute('TRUNCATE current_acquisition_page,current_acquisition_query,current_acquisition_image,'
                'current_acquisition_market,current_acquisition_aggregate,current_acquisition_alternate,'
                'current_acquisition_event_census,current_acquisition_failure,current_native_market_recovery,current_native_catalog_recovery,data_runtime')

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
