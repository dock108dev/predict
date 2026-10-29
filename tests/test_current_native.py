"""Controlled new-worker sequence/recovery and book semantics; no external I/O."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timezone
from datetime import timedelta
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock
from app.collection.current_native import NativeWorker
from app.collection.current_policy import DEFAULT
from app.collection.prediction_producer import PredictionBudget
from app.collection.native_semantics import current_purchase_book
from app.models.core import MarketState
from tests.test_kalshi import market,frame,ack,engine,NOW
from tests.test_polymarket_us import market as us_market
from tests.test_polymarket_us_stream import message

class Credential:
    def headers(self,*args):return {}
    def check(self,*args):pass

class Socket:
    def __init__(self,venue,number):self.venue=venue;self.number=number;self.sent=[];self.closed=False;self.count=0
    async def send(self,raw):self.sent.append(json.loads(raw))
    async def close(self):self.closed=True
    async def recv(self):
        self.count+=1
        if self.venue=='kalshi':
            if self.count==1:return ack(self.sent[0]['id'])
            if self.count==2:return frame(1)
            if self.number==1 and self.count==3:return frame(3,'orderbook_delta') # CONTROLLED sequence gap
            if self.number==2 and self.count==3:return frame(2,'orderbook_delta',ts=NOW.isoformat())
        else:
            rid=self.sent[0]['subscribe']['requestId']
            if self.count==1:return message(rid,state='MARKET_STATE_OPEN',transactTime=datetime.now(timezone.utc).isoformat())
            if self.number==1 and self.count==2:return message(rid,delta=True) # CONTROLLED ambiguous image
            if self.count==2:return '{"heartbeat":{}}'
        await asyncio.Event().wait()

class WorkerControls(unittest.IsolatedAsyncioTestCase):
    async def test_derived_turn_is_fifo_coalesced_and_byte_bounded(self):
        service=SimpleNamespace(config=dict(DEFAULT,ingress_bytes=8192),dispatch=True,database_mode=True,books=lambda *args:None)
        worker=NativeWorker(service,'kalshi')
        at=datetime.now(timezone.utc).isoformat()
        for i in range(600):
            mid=str(i)
            worker.pending_books[mid]=dict(raw=dict(ref=dict(market_id=mid),received_at=at),padding='x'*100)
            worker.pending_since[mid]=float(i)
            worker.derived_served[mid]=600-i
        # A frequently updated market keeps its original place in the queue.
        updated=worker.pending_books['0'];updated['padding']='latest'
        worker.pending_books['0']=updated
        captured=[]
        async def admit(service,fn,venue,books):captured.extend(books)
        with patch('app.collection.current_native.call',side_effect=admit),patch('app.collection.bulk_checkpoint.save_images'):
            worker.flush_books();await worker.publication_task
            if worker.publication_handle:worker.publication_handle.cancel();worker.publication_handle=None
        self.assertEqual(captured[0]['raw']['ref']['market_id'],'0')
        self.assertEqual(captured[0]['padding'],'latest')
        self.assertEqual([b['raw']['ref']['market_id'] for b in captured],[str(i) for i in range(len(captured))])
        self.assertLessEqual(sum(len(json.dumps(b,default=str).encode()) for b in captured),4096)
        self.assertEqual(len(worker.pending_books)+len(captured),600)

    async def test_metadata_recalculation_age_is_not_fresh_update_delivery_latency(self):
        service=SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True,database_mode=True,books=lambda *args:None)
        worker=NativeWorker(service,'kalshi');worker.persist_raw=AsyncMock()
        old=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        book=dict(raw=dict(ref=dict(market_id='quiet'),received_at=old))
        captured=[]
        async def admit(service,fn,venue,books):captured.extend(books)
        with patch('app.collection.current_native.call',side_effect=admit),patch('app.collection.bulk_checkpoint.save_images'):
            worker.queue_derived(book);worker.flush_books();await worker.publication_task
            latency=worker.synchronization.snapshot({})['delivery_latency']
            self.assertEqual(latency['derived']['samples'],0)
            self.assertEqual(latency['metadata_recalculation']['samples'],1)
            self.assertLess(latency['metadata_recalculation']['p95_seconds'],60)
            self.assertEqual(captured[0]['raw']['received_at'],old)
            # A real received update superseding the queued metadata recheck
            # belongs in the receipt-delivery distribution, with its own clock.
            worker.queue_derived(book)
            newer=deepcopy(book);newer['raw']['received_at']=datetime.now(timezone.utc).isoformat()
            worker.queue_book(newer);worker.flush_books();await worker.publication_task;await worker.raw_task
            latency=worker.synchronization.snapshot({})['delivery_latency']
            self.assertEqual(latency['derived']['samples'],1)
            self.assertEqual(latency['metadata_recalculation']['samples'],1)
            self.assertLess(latency['derived']['p95_seconds'],60)
            self.assertFalse(worker.pending_recalculations)
        if worker.publication_handle:worker.publication_handle.cancel()

    async def test_short_steady_turns_and_bulk_catchup_keep_all_pending_books(self):
        service=SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True,database_mode=True,books=lambda *args:None)
        at=datetime.now(timezone.utc).isoformat()
        for count,expected in ((400,128),(1200,512)):
            worker=NativeWorker(service,'kalshi')
            for i in range(count):
                worker.pending_books[str(i)]=dict(raw=dict(ref=dict(market_id=str(i)),received_at=at))
                worker.pending_since[str(i)]=float(i)
            captured=[]
            async def admit(service,fn,venue,books):captured.extend(books)
            with patch('app.collection.current_native.call',side_effect=admit),patch('app.collection.bulk_checkpoint.save_images'):
                worker.flush_books();await worker.publication_task
                if worker.publication_handle:worker.publication_handle.cancel()
            self.assertEqual(len(captured),expected)
            self.assertEqual(len(worker.pending_books)+len(captured),count)

    async def test_kalshi_catalog_removal_keeps_socket_without_reimaging_survivors(self):
        from app.adapters.kalshi_stream import BookReconstructor
        service=SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True,deadline=asyncio.get_running_loop().time()+10)
        worker=NativeWorker(service,'kalshi');current=market();old=market('OLD')
        mid=current.raw.ref.market_id
        selections=[dict(market_id=m.raw.ref.market_id,event=dict(id=m.raw.ref.event_id),material_revision='same') for m in (current,old)]
        worker.lifecycle.leases={s['market_id']:dict(selection=s) for s in selections};worker.lifecycle_initialized=True
        worker.markets={mid:current,'OLD':old};worker.active_engine=BookReconstructor([current,old]);worker.active_engine.sid=7
        worker.socket=SimpleNamespace(send=AsyncMock(),close=AsyncMock())
        worker.reconstruction=SimpleNamespace(reconfigure=AsyncMock())
        worker.stream_task=asyncio.create_task(asyncio.Event().wait())
        worker.stream_markets=[current,old];worker.stream_market_index=dict(worker.markets)
        worker.stream_seen={mid,'OLD'};worker.stream_isolated=set();worker.stream_snapshot_requests={}
        worker.synchronization.begin(1,[mid,'OLD']);worker.synchronization.acknowledge('7')
        for member in (mid,'OLD'):worker.synchronization.image(member)
        try:
            await worker.quiesce_catalog({mid:current},{},selections[:1])
            self.assertEqual(worker.subscription_blocked,{'OLD'})
            worker.markets={mid:current};worker.lifecycle.leases.pop('OLD')
            await worker.finish_subscription_transition()
            sent=[json.loads(c.args[0]) for c in worker.socket.send.await_args_list]
            self.assertEqual(len(sent),1);self.assertEqual(sent[0]['params']['action'],'delete_markets')
            self.assertEqual(sent[0]['params']['market_tickers'],['OLD'])
            self.assertEqual(worker.stream_seen,{mid});self.assertEqual(worker.metrics['missing_initial_images'],0)
            self.assertEqual(worker.metrics['catalog_transition']['reimaged_markets'],0)
            self.assertEqual(worker.synchronization.images,{mid});worker.socket.close.assert_not_awaited()
        finally:
            worker.stream_task.cancel();await asyncio.gather(worker.stream_task,return_exceptions=True)

    async def test_catalog_group_replacement_keeps_socket_and_waits_for_new_request_images(self):
        from app.adapters.polymarket_us_stream import MarketStream
        service=SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True,deadline=asyncio.get_running_loop().time()+10)
        worker=NativeWorker(service,'polymarket_us');m=us_market();mid=m.raw.ref.market_id
        selection=dict(market_id=mid,event=dict(id=m.raw.ref.event_id),material_revision='old')
        worker.lifecycle.leases={mid:dict(selection=selection)};worker.lifecycle_initialized=True
        worker.markets={mid:m};worker.subscription_groups={'old-request':[mid]}
        worker.active_engine=MarketStream([m],None);worker.active_engine.begin_subscription('connection')
        worker.socket=SimpleNamespace(send=AsyncMock(),close=AsyncMock())
        worker.reconstruction=SimpleNamespace(reconfigure=AsyncMock())
        worker.stream_task=asyncio.create_task(asyncio.Event().wait())
        worker.stream_markets=[m];worker.stream_market_index={mid:m};worker.stream_seen={mid};worker.stream_isolated=set()
        worker.synchronization.begin(1,[mid]);worker.synchronization.acknowledge('connection');worker.synchronization.image(mid)
        revised=dict(selection,material_revision='new')
        try:
            await worker.quiesce_catalog({mid:m},{},[revised])
            worker.socket.close.assert_not_awaited();self.assertFalse(worker.stream_task.done())
            self.assertEqual(worker.subscription_blocked,{mid});self.assertNotIn(mid,worker.synchronization.images)
            worker.lifecycle.leases[mid]['selection']=revised
            await worker.finish_subscription_transition()
            sent=[json.loads(c.args[0]) for c in worker.socket.send.await_args_list]
            self.assertEqual(sent[0],{'unsubscribe':{'requestId':'old-request'}})
            self.assertNotEqual(sent[1]['subscribe']['requestId'],'old-request')
            self.assertEqual(worker.stream_seen,set());self.assertFalse(worker.subscription_blocked)
            self.assertIsNone(worker.subscription_transition);worker.socket.close.assert_not_awaited()
        finally:
            worker.stream_task.cancel();await asyncio.gather(worker.stream_task,return_exceptions=True)

    async def test_transient_rediscovery_failure_keeps_owned_healthy_socket(self):
        from app.collection.odds_http import BudgetStop
        states=[];calls=0
        service=SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True,deadline=asyncio.get_running_loop().time()+10,
            source_state=lambda *a:states.append(a),issue=lambda *a:None,observation=lambda *a:None)
        worker=NativeWorker(service,'polymarket_us')
        worker.stream_task=asyncio.create_task(asyncio.Event().wait())
        worker.socket=SimpleNamespace(close=AsyncMock())
        socket=worker.socket;stream=worker.stream_task
        client=SimpleNamespace(budget=SimpleNamespace(requests=1,bytes=0),aclose=AsyncMock())
        async def discover():
            nonlocal calls
            calls+=1
            self.assertFalse(stream.done());socket.close.assert_not_awaited()
            if calls<3:raise BudgetStop('native_http_timeout')
            worker.closed=True
        with patch('app.collection.current_native.load_credentials',return_value={'polymarket_us':Credential()}),patch('app.collection.current_native.REST',return_value=client),patch('app.collection.current_native.native_payload.configure_transport'),patch.object(worker,'discover',side_effect=discover),patch('app.collection.current_native.asyncio.sleep',new=AsyncMock()) as sleep:
            await worker.run()
        self.assertEqual(calls,3);self.assertFalse(worker.failed)
        self.assertEqual(worker.metrics['discovery_deferrals'],2)
        self.assertEqual([c.args[0] for c in sleep.await_args_list[:2]],[2,5])
        self.assertEqual(states,[]);self.assertTrue(stream.cancelled());socket.close.assert_awaited_once()

    async def test_transient_http_timeout_retries_without_terminal_source_failure(self):
        states=[]
        service=SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True,deadline=asyncio.get_running_loop().time()+10,
            source_state=lambda *a:states.append(a),issue=lambda *a:None,observation=lambda *a:None)
        worker=NativeWorker(service,'kalshi')
        client=SimpleNamespace(budget=SimpleNamespace(requests=1,bytes=0),aclose=AsyncMock())
        calls=0
        from app.collection.prediction_producer import BudgetStop
        async def discover():
            nonlocal calls
            calls+=1
            if calls<3:
                worker.receipt(dict(path='/test',status=200,complete=False,usable_metadata=False,
                    body_sha256='0'*64,delivery_reason='native_http_timeout'))
                raise BudgetStop('native_http_timeout')
            worker.closed=True
        with patch('app.collection.current_native.load_credentials',return_value={'kalshi':Credential()}),patch('app.collection.current_native.REST',return_value=client),patch('app.collection.current_native.native_payload.configure_transport'),patch.object(worker,'discover',side_effect=discover),patch('app.collection.current_native.asyncio.sleep',new=AsyncMock()) as sleep:
            await worker.run()
        self.assertEqual(calls,3)
        self.assertFalse(worker.failed)
        self.assertEqual([c.args[0] for c in sleep.await_args_list[:2]],[2,5])
        client.aclose.assert_awaited_once()

    async def test_latest_validated_images_publish_as_one_bounded_batch(self):
        from tests.test_current_service import native_fixture
        _,book=native_fixture();published=[]
        service=SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True,books=lambda *a:published.append(deepcopy(a)))
        worker=NativeWorker(service,'kalshi')
        worker.queue_book(book)
        changed=deepcopy(book);changed['outcomes'][0]['asks']['levels'][0]['price']['value']='0.49'
        worker.queue_book(changed)
        other=deepcopy(book);other['raw']['ref']['market_id']='CONTROLLED-other'
        worker.queue_book(other)
        self.assertEqual(published,[])
        worker.flush_books()
        self.assertEqual(len(published),1)
        self.assertEqual(published[0][1],[changed,other])
        worker.queue_book(book);worker.closed=True;worker.flush_books()
        self.assertEqual(len(published),1)

    async def test_tail_priority_survives_reconnect_initial_image_order(self):
        from tests.test_current_service import native_fixture
        _,book=native_fixture();published=[]
        service=SimpleNamespace(config=dict(DEFAULT,markets_per_source=1),dispatch=True,books=lambda *a:published.append(a))
        worker=NativeWorker(service,'kalshi')
        first=book['raw']['ref']['market_id']
        worker.derived_served[first]=__import__('time').monotonic()
        worker.queue_book(book)
        tail=deepcopy(book);tail['raw']['ref']['market_id']='CONTROLLED-tail'
        worker.queue_book(tail)
        worker.flush_books()
        self.assertEqual(published[0][1][0]['raw']['ref']['market_id'],'CONTROLLED-tail')
        self.assertIn(first,worker.pending_books)
        worker.closed=True;worker.flush_books()

    async def test_each_source_gap_resync_new_socket_cancel_no_duplicate(self):
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                sockets=[];states=[];issues=[];books=[]
                service=SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True,deadline=asyncio.get_running_loop().time()+10,
                    source_state=lambda *a:states.append(a),issue=lambda *a:issues.append(a),book=lambda *a:books.append(a),books=lambda v,values:books.extend((v,b) for b in values))
                # Controlled accelerated backoff only in this disposable fixture.
                service.config['backoff_seconds']=[.001]*5
                worker=NativeWorker(service,venue);worker.credential=Credential()
                worker.client=SimpleNamespace(budget=PredictionBudget(dict(session_bytes=16*1024*1024)))
                class Connector:
                    def __init__(self,url,**kwargs):self.kwargs=kwargs
                    def __await__(self):
                        async def build():
                            self_test.assertEqual(self.kwargs['max_queue'],64);self_test.assertIsNone(self.kwargs['compression'])
                            socket=Socket(venue,len(sockets)+1);sockets.append(socket);return socket
                        return build().__await__()
                self_test=self
                m=market() if venue=='kalshi' else us_market()
                m=replace(m,state=MarketState.ACTIVE)
                with patch('app.collection.current_native.connect',Connector):
                    task=asyncio.create_task(worker.stream([m]))
                    for _ in range(450):
                        if len(books)>=1 and len(sockets)>=2:break
                        await asyncio.sleep(.005)
                    self.assertGreaterEqual(len(books),1);self.assertEqual(len(sockets),2)
                    from app.dashboard.current_contract import stamp
                    for _,b in books:
                        stamp(b['raw']['received_at']);stamp(b['raw'].get('exchange_at'),True)
                    self.assertTrue(sockets[0].closed);self.assertFalse(sockets[1].closed)
                    self.assertGreater(worker.metrics['resyncs'],0)
                    self.assertEqual(len(sockets[1].sent),1)
                    task.cancel();await asyncio.gather(task,return_exceptions=True)
                self.assertTrue(all(s.closed for s in sockets));self.assertIsNone(worker.socket)

    async def test_stop_revokes_stream_before_waiting_for_publication(self):
        service=SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True)
        worker=NativeWorker(service,'kalshi')
        publishing=asyncio.Event();release=asyncio.Event();cancelled=asyncio.Event()
        async def stream():
            try:await asyncio.Event().wait()
            finally:cancelled.set()
        async def publish():
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:
                publishing.set();await release.wait();raise
        worker.stream_task=asyncio.create_task(stream())
        worker.publication_task=asyncio.create_task(publish())
        await asyncio.sleep(0)
        stop=asyncio.create_task(worker.stop_stream())
        await asyncio.wait_for(publishing.wait(),1)
        self.assertTrue(cancelled.is_set())
        release.set();await stop

    async def test_three_malformed_images_stop_affected_source(self):
        issues=[];states=[]
        service=SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True,deadline=asyncio.get_running_loop().time()+10,
            source_state=lambda *a:states.append(a),issue=lambda *a:issues.append(a),book=lambda *a:None)
        service.config['backoff_seconds']=[.001]*5
        worker=NativeWorker(service,'kalshi');worker.credential=Credential();worker.client=SimpleNamespace(budget=PredictionBudget(dict(session_bytes=16*1024*1024)))
        class BadSocket:
            async def send(self,body):pass
            async def recv(self):return 'not JSON'
            async def close(self):pass
        class Connector:
            def __init__(self,*a,**kw):pass
            def __await__(self):
                async def build():return BadSocket()
                return build().__await__()
        with patch('app.collection.current_native.connect',Connector):await worker.stream([market()])
        self.assertTrue(worker.failed);self.assertEqual(worker.metrics['connections'],3)
        self.assertEqual(states[-1][1],'error')

    async def test_worker_clock_highwater_survives_new_subscription_engine(self):
        from app.adapters.polymarket_us import next_market_data,source_time_value
        service=SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True,deadline=asyncio.get_running_loop().time()+10,
            source_state=lambda *a:None,issue=lambda *a:None,book=lambda *a:self.fail('regressed image was admitted'))
        service.config['backoff_seconds']=[.001]*5
        worker=NativeWorker(service,'polymarket_us');worker.credential=Credential()
        worker.client=SimpleNamespace(budget=PredictionBudget(dict(session_bytes=16*1024*1024)))
        m=replace(us_market(),state=MarketState.ACTIVE);key=next_market_data(m)['slug']
        future=source_time_value((datetime.now(timezone.utc)+timedelta(hours=1)).isoformat());worker.source_highwater[key]=future
        class Connector:
            def __init__(self,*a,**kw):pass
            def __await__(self):
                async def build():return Socket('polymarket_us',1)
                return build().__await__()
        with patch('app.collection.current_native.connect',Connector):await worker.stream([m])
        self.assertTrue(worker.failed);self.assertEqual(worker.metrics['connections'],3)
        self.assertEqual(worker.source_highwater[key],future)

class PurchaseSemantics(unittest.TestCase):
    def test_useful_family_rotation_respects_parser_cap(self):
        from app.collection.current_native import balanced_markets
        rows=[dict(id=f+str(i),market_type=f) for f in ('moneyline','spread','total') for i in range(30)]
        selected=balanced_markets(rows,20,['moneyline','spread','total'])
        self.assertEqual(len(selected),20)
        self.assertEqual([m['market_type'] for m in selected[:6]],['moneyline','spread','total']*2)
        self.assertEqual(len({m['id'] for m in selected}),20)
    def test_native_kalshi_original_bids_preserved_and_asks_separate(self):
        original=engine().feed(frame(1),1,NOW);derived=current_purchase_book(original)
        self.assertIsNone(original.outcomes[0].asks)
        self.assertEqual(str(derived.outcomes[0].asks.levels[0].price.value),'0.4998')
        self.assertEqual(derived.outcomes[0].asks.levels[0].quantity,original.outcomes[1].bids.levels[0].quantity)
        self.assertEqual(derived.raw,original.raw)

    def test_selected_catalog_preserves_receipt_identity_and_legacy_default(self):
        from app.collection import coverage
        from tests.test_coverage import fixture,AS_OF
        pages=fixture()
        before=deepcopy(pages)
        legacy=coverage.catalog(pages,'polymarket_us',AS_OF,compact_output=False)
        eid=legacy['events'][0]['id'];mid=legacy['markets'][0]['id']
        selected=coverage.catalog(pages,'polymarket_us',AS_OF,compact_output=False,current_selection={'events':[eid],'markets':[mid]})
        projected=deepcopy(selected)
        for event in projected['events']:
            reference=event.pop('embedded_market_packaging_reference',None)
            if reference:
                original=next(row for row in legacy['events'] if row['id']==event['id'])
                self.assertEqual(reference['body_sha256'],original['provenance'][0]['body_sha256'])
                self.assertEqual(reference['omitted_markets'],0)
        self.assertEqual(projected,legacy);self.assertEqual(pages,before)
        self.assertEqual(coverage.catalog(pages,'polymarket_us',AS_OF,compact_output=False),legacy)
        empty=coverage.catalog(pages,'polymarket_us',AS_OF,current_selection={'events':[eid],'markets':[]})
        self.assertEqual(empty['markets'],[]);self.assertEqual(len(empty['events']),1)
        # Ordinary selection has no event-count cutoff. Unknown IDs select nothing.
        self.assertEqual(coverage.catalog(pages,'polymarket_us',AS_OF,current_selection={'events':[str(i) for i in range(25)],'markets':[]})['markets'],[])
