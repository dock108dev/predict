"""Whole-query boundaries, resume and cancellation without provider access."""
import asyncio
import base64
from hashlib import sha256
import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from app.collection.bulk_native import pages


class Traversal(IsolatedAsyncioTestCase):
    def worker(self, venue, responses):
        worker = SimpleNamespace(venue=venue, pages=[], metrics={}, guard=lambda: None)
        calls = []

        async def get(path, params, field, scope):
            calls.append(dict(params))
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            raw = json.dumps(response).encode()
            worker.pages.append(dict(path=path, params=params, body_b64=base64.b64encode(raw).decode(),
                                     body_sha256=sha256(raw).hexdigest()))
        worker.get = get
        return worker, calls

    async def test_exhausts_all_cursor_pages_and_preserves_distinct_ids(self):
        worker, calls = self.worker('kalshi', [dict(events=[{'id': str(i)}], cursor=str(i+1) if i < 60 else '') for i in range(61)])
        rows, count = await pages(worker, '/trade-api/v2/events', {}, 'events', size=1)
        self.assertEqual((len(rows), count), (61, 61))
        self.assertEqual(calls[-1]['cursor'], '60')

    async def test_repeated_cursor_and_repeated_offset_page_never_complete(self):
        for venue, responses in [('kalshi', [dict(events=[{'id': 'a'}], cursor='x')]*2),
                                  ('polymarket_us', [dict(events=[{'id': 'a'}])]*2)]:
            worker, _ = self.worker(venue, responses)
            with self.assertRaisesRegex(ValueError, 'repeated'):
                await pages(worker, '/v1/events', {}, 'events', size=1)
            self.assertFalse(worker.metrics['bulk_progress']['exhausted'])

    async def test_resume_reuses_receipts_and_stop_prevents_next_dispatch(self):
        worker, _ = self.worker('kalshi', [dict(events=[{'id': 'a'}], cursor='next'), RuntimeError('interrupted')])
        saved = []

        class Checkpoint:
            def query(self, *args):
                return 'key', list(saved)
            def page(self, key, index, receipt, complete):
                saved.append(receipt)
        worker.checkpoint = Checkpoint()
        with self.assertRaises(RuntimeError):
            await pages(worker, '/trade-api/v2/events', {}, 'events')
        restart, calls = self.worker('kalshi', [dict(events=[{'id': 'b'}], cursor='')])
        restart.checkpoint = worker.checkpoint
        rows, count = await pages(restart, '/trade-api/v2/events', {}, 'events')
        self.assertEqual(rows, [{'id': 'a'}, {'id': 'b'}])
        self.assertEqual(count, 2)
        self.assertEqual(calls, [dict(limit=50, cursor='next')])
        def stopped():
            raise asyncio.CancelledError()
        restart.guard = stopped
        with self.assertRaises(asyncio.CancelledError):
            await pages(restart, '/trade-api/v2/events', {}, 'events')
        self.assertEqual(len(calls), 1)

    async def test_raw_pipeline_drains_tail_without_waiting_for_derived_publication(self):
        from copy import deepcopy
        from unittest.mock import patch
        from app.collection.current_policy import DEFAULT
        from app.collection.current_native import NativeWorker
        from tests.test_current_service import native_fixture
        _,book=native_fixture();saved=[]
        service=SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True,database_mode=True)
        worker=NativeWorker(service,'kalshi')
        def retain(source,images,disposition):saved.extend((b['raw']['ref']['market_id'],disposition) for b in images)
        with patch('app.collection.bulk_checkpoint.save_images',side_effect=retain):
            for i in range(221):
                image=deepcopy(book);image['raw']['ref']['market_id']=str(i)
                worker.queue_book(image)
            worker.publication_handle.cancel();worker.publication_handle=None
            await worker.drain_raw()
        self.assertEqual({mid for mid,state in saved},{str(i) for i in range(221)})
        self.assertEqual(len(worker.pending_books),221)
        self.assertEqual(worker.metrics['raw_backlog'],0)
        await worker.close()

    async def test_cancelled_checkpoint_operation_is_joined_before_owner_returns(self):
        from threading import Event
        from app.collection.bulk_checkpoint import owned_thread
        entered=Event();release=Event();finished=Event()
        def operation():
            entered.set();release.wait(2);finished.set()
        task=asyncio.create_task(owned_thread(operation))
        while not entered.is_set():await asyncio.sleep(.001)
        task.cancel();await asyncio.sleep(.01)
        self.assertFalse(task.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(finished.is_set())

    async def test_catalog_process_preserves_market_metadata_and_joins_on_close(self):
        import os
        from datetime import datetime,timezone
        from app.collection import coverage
        from app.collection.bulk_native import build_catalog,close_catalog_worker
        from app.collection.native_selectors import query
        from tests.multisport_fixtures import source_case,fake_discovery
        from tests.test_current_multisport_ingress import worker
        value,_=worker('polymarket_us',['NFL'],['moneyline'])
        case=source_case('NFL','moneyline','process-catalog')
        fake_discovery(value,[case]);value._coverage_sport='NFL';value._coverage_checked=set()
        path,params=query('polymarket_us','NFL',families=['moneyline'])
        await value.get(path,dict(params,limit=5,offset=0),'events')
        at=datetime.now(timezone.utc)
        selection=dict(events=[case['events']['polymarket_us']['id']],markets=[case['markets']['polymarket_us']['id']])
        expected=coverage.catalog(value.pages,value.venue,at,compact_output=False,current_selection=selection)
        for event in expected['events']:event.get('_native',{}).pop('markets',None)
        value.checkpoint=True
        try:
            actual=await build_catalog(value,value.pages,at,selection)
            self.assertEqual(actual,expected)
            self.assertNotEqual(value.metrics['catalog_worker']['pid'],os.getpid())
            processes=list(value.catalog_pool._processes.values())
        finally:await close_catalog_worker(value)
        self.assertTrue(all(not process.is_alive() for process in processes))
        self.assertTrue(value.metrics['catalog_worker_stopped'])

    async def test_cancelled_catalog_waits_for_running_process_result(self):
        from concurrent.futures import Future
        from app.collection.bulk_native import build_catalog
        result=Future();result.set_running_or_notify_cancel()
        worker=SimpleNamespace(checkpoint=True,venue='kalshi',metrics={},
            catalog_pool=SimpleNamespace(submit=lambda *args:result))
        task=asyncio.create_task(build_catalog(worker,[],None,{}))
        await asyncio.sleep(.01);task.cancel();await asyncio.sleep(.01)
        self.assertFalse(task.done())
        result.set_result(({},{}))
        with self.assertRaises(asyncio.CancelledError):await task


class PriceBoundaries(IsolatedAsyncioTestCase):
    async def test_native_slots_come_from_listing_and_exclude_synthetic_complements(self):
        from app.collection.price_units import native_boundary
        from tests.test_current_service import native_fixture
        _,book=native_fixture()
        result=native_boundary('kalshi',{},book)
        self.assertEqual(result['expected_slots'],2)
        self.assertEqual({u['side'] for u in result['units']},{'bids'})
        missing=native_boundary('kalshi',{},None)
        self.assertEqual(missing['missing'],2)
        pm=native_boundary('polymarket_us',{'marketSides':[{'id':'long','long':True},{'id':'short','long':False}]},
            {'outcomes':[{'outcome_id':'long','bids':{'levels':[]},'asks':None}]})
        self.assertEqual((pm['expected_slots'],pm['empty'],pm['unavailable']),(2,1,1))
        self.assertIsNone(native_boundary('polymarket_us',{},None)['expected_slots'])

    async def test_route_overlap_preserves_provenance_distinct_lines_and_absent_quotes(self):
        from app.collection.price_units import aggregate_units,merge_units
        def events(key,point,price):
            return [dict(id='event',bookmakers=[dict(key='novig',markets=[dict(key=key,outcomes=[dict(name='A',point=point,price=price)])])])]
        units=aggregate_units(events('spreads',-3,2),'novig','spread','featured')
        merge_units(units,aggregate_units(events('alternate_spreads',-3.0,2),'novig','spread','alternate'))
        self.assertEqual(len(units),1)
        self.assertEqual(next(iter(units.values()))['routes'],['alternate','featured'])
        merge_units(units,aggregate_units(events('alternate_spreads',-3.5,None),'novig','spread','alternate'))
        self.assertEqual(len(units),2)
        self.assertEqual(sum(u['disposition']=='absent_quote' for u in units.values()),1)


class SocketDrain(IsolatedAsyncioTestCase):
    async def test_socket_drains_before_slow_reconstruction_and_preserves_order(self):
        from app.collection.native_receive import NativeReceive
        class Socket:
            def __init__(self):self.count=0
            async def recv(self):
                self.count+=1
                if self.count<=200:return str(self.count)
                await asyncio.Future()
        socket=Socket();metrics={};reader=NativeReceive(socket,metrics)
        try:
            for _ in range(1000):
                if metrics.get('socket_reads')==200:break
                await asyncio.sleep(0)
            self.assertEqual(metrics['socket_reads'],200)
            self.assertEqual(metrics['receive_buffer_frames'],200)
            values=[(await reader.recv())[0] for _ in range(200)]
            self.assertEqual(values,[str(i) for i in range(1,201)])
            self.assertEqual(metrics['receive_buffer_bytes'],0)
        finally:await reader.close()
        self.assertTrue(reader.task.done())

    async def test_byte_capacity_requires_immediate_explicit_resynchronization(self):
        from app.collection.native_receive import NativeReceive
        class Socket:
            def __init__(self):self.count=0
            async def recv(self):
                self.count+=1
                return f'{self.count:04d}'.encode()
        metrics={};reader=NativeReceive(Socket(),metrics,byte_limit=8)
        try:
            await reader.task  # Saturate before consuming; independent of task scheduling.
            with self.assertRaisesRegex(ValueError,'native_receive_backlog_capacity'):await reader.recv()
            self.assertEqual(metrics['receive_buffer_peak_bytes'],8)
        finally:await reader.close()
        self.assertEqual(metrics['receive_frames_discarded_on_resync'],2)


def test_full_catalog_replacement_keeps_every_instrument_below_legacy_projection_bound():
    from copy import deepcopy
    from unittest.mock import patch
    from tests.test_current_service import native_fixture
    from app.collection.current_database import normalize_current
    cat,book=native_fixture();market=cat['markets'][0]
    cat['markets']=[];books=[]
    for index in range(1100):
        mid='bulk-'+str(index)
        cat['markets'].append(dict(deepcopy(market),id=mid))
        image=deepcopy(book);image['raw']['ref']['market_id']=mid
        obs=dict(type='prediction_book',source='kalshi',book=image,observed_at=image['raw']['received_at'],packets=[])
        books.append(dict(id=mid,record=dict(retained_at=image['raw']['received_at'],value=dict(observations=[obs]))))
    catalog=dict(id='catalog',record=dict(source='kalshi',value=dict(inventory=cat)))
    seen=[]
    def capture(reducer,*args,**kwargs):
        assert len(reducer.books)<=256
        seen.extend(k[2] for k in reducer.books)
        return [],[]
    # Run the actual SessionProjection: the old all-roster call raised at 1024.
    with patch('app.comparison.combined_native.normalized_records',side_effect=capture):
        assert normalize_current(catalog,books,at=book['raw']['received_at'])==([],[])
    assert len(seen)==len(set(seen))==1100
    assert set(seen)=={m['id'] for m in cat['markets']}

class EmbeddedRoute(IsolatedAsyncioTestCase):
    async def test_kalshi_complete_embedded_markets_avoid_per_event_round_trips(self):
        from unittest.mock import AsyncMock,patch
        from app.collection.bulk_native import enumerate_native
        from app.collection.current_policy import DEFAULT
        raw=json.dumps(dict(events=[dict(event_ticker='E',markets=[dict(ticker='M1'),dict(ticker='M2')])],cursor='')).encode()
        calls=[]
        worker=SimpleNamespace(venue='kalshi',config=dict(DEFAULT,sports=['NFL'],families=['moneyline']),pages=[],metrics={},findings=[],guard=lambda:None)
        async def get(path,params,kind,scope):
            calls.append((path,params))
            worker.pages.append(dict(source='kalshi',path=path,params=params,body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest(),native_scope_binding=scope))
        worker.get=get
        catalog=dict(events=[dict(id='E')],markets=[dict(id='M1'),dict(id='M2')])
        with patch('app.collection.bulk_native.build_catalog',new=AsyncMock(return_value=catalog)):
            _,_,markets=await enumerate_native(worker)
        assert len(calls)==1 and calls[0][1]['with_nested_markets']=='true'
        assert {m['id'] for m in markets}=={'M1','M2'}


def test_missing_moving_pass_retains_instrument_until_explicit_reappearance():
    from app.collection.native_recovery import retain_absent
    old=dict(events=[dict(id='E')],markets=[dict(id='M',event_id='E')])
    new=dict(events=[],markets=[])
    assert retain_absent(old,new)=={'M'}
    assert new['markets'][0]['inventory_recovery_disposition']=='suspected_absent'
    assert new['events']==old['events']
    returned=dict(events=[dict(id='E')],markets=[dict(id='M',event_id='E',_native={'closed':True})])
    assert retain_absent(new,returned)==set()
    assert len(returned['markets'])==1 and returned['markets'][0]['_native']['closed']


def test_event_packaging_does_not_change_native_material_or_drop_selected_markets():
    from copy import deepcopy
    from app.collection.current_native_catalog import book_material,detach_event_packaging
    from tests.test_current_service import native_fixture
    catalog,_=native_fixture()
    event=catalog['events'][0];market=catalog['markets'][0]
    event.setdefault('_native',{})['markets']=[deepcopy(market)]
    before=book_material('kalshi',event,market)
    selected=deepcopy(catalog['markets'])
    detach_event_packaging(catalog)
    assert catalog['markets']==selected
    assert 'markets' not in catalog['events'][0]['_native']
    assert book_material('kalshi',catalog['events'][0],market)==before

class NormalizationProcess(IsolatedAsyncioTestCase):
    async def test_compact_market_parse_matches_original_without_loading_receipt(self):
        from dataclasses import replace
        from copy import deepcopy
        from unittest.mock import patch
        from app.collection.current_native_catalog import parse_retained_market
        from tests.test_current_multisport_ingress import worker
        from tests.multisport_fixtures import source_case,fake_discovery
        for venue in ('kalshi','polymarket_us'):
            for family in ('moneyline','spread','total'):
                w,published=worker(venue,['NFL'],[family])
                case=source_case('NFL',family,'compact-'+venue+'-'+family)
                fake_discovery(w,[case]);await w.discover()
                catalog=published[-1];events={e['id']:e for e in catalog['events']}
                before=deepcopy(catalog)
                for market in catalog['markets']:
                    if market['id'] not in w.markets:continue
                    original=w.markets[market['id']]
                    compact=json.dumps(dict(market=market['_native'],source_receipt_sha256=market['provenance'][0]['body_sha256']))
                    expected=replace(original,raw=replace(original.raw,json_text=compact))
                    with patch('app.collection.coverage.decode_page',side_effect=AssertionError('receipt reload')):
                        actual=parse_retained_market(venue,market,events[market['event_id']])
                    self.assertEqual(actual,expected)
                self.assertEqual(catalog,before)
                await w.stop_stream()

    async def test_spawned_batch_matches_direct_complete_native_records(self):
        from concurrent.futures import ProcessPoolExecutor
        from multiprocessing import get_context
        from app.collection.current_database import normalize_current
        from tests.test_current_multisport_ingress import worker
        from tests.multisport_fixtures import source_case,fake_discovery,current_book
        with ProcessPoolExecutor(max_workers=1,mp_context=get_context('spawn')) as pool:
            for venue in ('kalshi','polymarket_us'):
                w,published=worker(venue,['NFL'],['moneyline'])
                case=source_case('NFL','moneyline','process-'+venue)
                fake_discovery(w,[case]);await w.discover()
                book=current_book(case,venue);at=book['raw']['received_at']
                catalog=dict(id='catalog',record=dict(source=venue,value=dict(inventory=published[-1])))
                books=[dict(id='book',record=dict(retained_at=at,value=dict(observations=[dict(type='prediction_book',source=venue,observed_at=at,book=book)])))]
                direct=normalize_current(catalog,books,at=at)
                self.assertTrue(direct[0])
                self.assertEqual(normalize_current(catalog,books,at=at,executor=pool),direct)
                await w.stop_stream()


def test_shared_catalog_preparation_matches_detached_and_preserves_original_rows():
    from copy import deepcopy
    from app.collection.current_service import prepare_catalog
    from tests.test_current_service import native_fixture
    cat,_=native_fixture();original=deepcopy(cat)
    expected=prepare_catalog({},'kalshi',cat)
    actual=prepare_catalog({},'kalshi',cat,share_metadata=True)
    assert actual==expected
    assert cat==original
    assert actual['kalshi']['markets'][0] is not cat['markets'][0]
    assert actual['kalshi']['markets'][0].get('_native') is cat['markets'][0].get('_native')


def test_metadata_sharing_keeps_new_clocks_types_and_detached_rows():
    from copy import deepcopy
    from app.collection.current_native_catalog import share_catalog_metadata
    prior=dict(events=[dict(id='e',_native=dict(teams=['a','b']),received_at='old')],
               markets=[dict(id='m',status=1,_native=dict(sides=['yes','no']),received_at='old')])
    new=deepcopy(prior)
    new['events'][0]['received_at']='new';new['markets'][0]['status']=True
    untouched=deepcopy(prior)
    shared=share_catalog_metadata(prior,new)
    assert shared==new and type(shared['markets'][0]['status']) is bool
    assert shared['events'][0] is not prior['events'][0]
    assert shared['events'][0]['_native'] is prior['events'][0]['_native']
    assert shared['markets'][0]['_native'] is prior['markets'][0]['_native']
    shared['markets'][0]['annotation']='replacement'
    assert prior==untouched


def test_catalog_binding_snapshot_checks_boundaries_and_detaches_values():
    from unittest.mock import Mock,patch
    from app.collection import public_contracts as pc
    original=pc.load('events')
    path=Mock(wraps=pc.PATH)
    with patch.object(pc,'PATH',path):
        with pc.binding_snapshot():
            for _ in range(100):
                value=pc.load('events');value.clear()
            with pc.binding_snapshot():
                assert pc.load('events')==original
        assert path.stat.call_count==2
    assert pc.load('events')==original


def test_catalog_binding_snapshot_rejects_changed_file_and_resets_scope():
    import pytest
    from unittest.mock import Mock,patch
    from app.collection import public_contracts as pc
    original=pc.load('events');stat=pc.PATH.stat()
    path=Mock(wraps=pc.PATH)
    path.stat.side_effect=[stat,SimpleNamespace(st_mtime_ns=stat.st_mtime_ns+1,st_size=stat.st_size)]
    with patch.object(pc,'PATH',path):
        with pytest.raises(ValueError,match='changed during projection'):
            with pc.binding_snapshot():assert pc.load('events')==original
    assert pc.load('events')==original


def test_shared_two_source_enrichment_matches_detached_without_mutating_inputs():
    from copy import deepcopy
    from app.collection.current_service import prepare_catalog
    from tests.test_v1_comparison import prepared
    inventory=prepared().inventory
    for cat in inventory.values():
        for event in cat['events']:
            event['observed_identity_facts']=[dict(season_year='invalid')]
            event['identity_conflicts']=['original conflict']
    original=deepcopy(inventory)
    expected=prepare_catalog(inventory,'polymarket_us',inventory['polymarket_us'])
    actual=prepare_catalog(inventory,'polymarket_us',inventory['polymarket_us'],share_metadata=True)
    assert actual==expected
    assert inventory==original


def test_catalog_byte_measurement_is_exact_without_whole_roster_encoding():
    import json
    from unittest.mock import patch
    from app.collection.current_native_catalog import catalog_encoded_bytes
    value=dict(events=[dict(id='é',metadata={'nested':[1,True,None,'\n']})],
        markets=[dict(id=str(n),text='quoted \" '+('x'*1000)) for n in range(300)],selection={'ids':['1','2']})
    expected=len(json.dumps(value,default=str).encode())
    original=json.dumps
    def bounded(v,*args,**kwargs):
        assert not isinstance(v,dict) or len(v.get('markets',[]))<300
        return original(v,*args,**kwargs)
    with patch('app.collection.current_native_catalog.json.dumps',side_effect=bounded):
        assert catalog_encoded_bytes(value)==expected
    assert catalog_encoded_bytes(dict(events=[],markets=[]))==len(json.dumps(dict(events=[],markets=[])).encode())


class ListingFallback(IsolatedAsyncioTestCase):
    async def test_event_detail_omission_keeps_original_listing_market_subscribed(self):
        from tests.test_current_multisport_ingress import worker
        from tests.multisport_fixtures import source_case,fake_discovery
        from app.collection.coverage import decode_page
        w,published=worker('polymarket_us',['NCAAB'],['moneyline'])
        case=source_case('NCAAB','moneyline','listing-fallback')
        fake_discovery(w,[case]);original_get=w.get;listing_hash=None
        async def get(path,params,field=None,scope=None):
            nonlocal listing_hash
            result=await original_get(path,params,field,scope)
            page=w.pages[-1]
            if path.startswith('/v1/events/'):
                _,payload=decode_page(page);payload['events'][0]['markets']=[]
                raw=json.dumps(dict(event=payload['events'][0])).encode()
                page.update(body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest())
            else:listing_hash=page['body_sha256']
            return result
        w.get=get
        try:
            await w.discover()
            mid=case['markets']['polymarket_us']['id']
            assert mid in w.markets
            market=next(m for m in published[-1]['markets'] if m['id']==mid)
            assert market['_native']==case['markets']['polymarket_us']
            assert market['provenance'][0]['body_sha256']==listing_hash
            assert w.metrics['listing_only_markets']==1
        finally:await w.stop_stream()
