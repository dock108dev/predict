"""Real spawned reconstruction, exact ordering and original receipt clocks."""
from dataclasses import replace
from datetime import datetime,timezone,timedelta
import json
from unittest import IsolatedAsyncioTestCase
from app.collection.native_reconstruction import Reconstruction
from app.collection.native_book_value import book_value
from app.collection.native_semantics import current_purchase_book
from app.adapters.kalshi_stream import BookReconstructor
from tests.test_kalshi import market,frame,ack
from tests.test_polymarket_us import market as us_market
from tests.test_polymarket_us_stream import message


class Batch:
    def __init__(self,rows):self.rows=rows;self.calls=0
    async def recv_batch(self,limit,size):
        self.calls+=1
        assert len(self.rows)<=limit
        return self.rows


class CompactChildState(IsolatedAsyncioTestCase):
    async def test_current_wire_matches_legacy_exact_decimal_and_unicode_encoding(self):
        from decimal import Decimal
        from app.adapters.kalshi_stream import encode
        from app.collection.native_reconstruction import current_wire
        for value in ({'side':'yes','price':'0.123456789012345678901','quantity':123},
                      {'unicode':'é 🎯'}, {'quantity':10**80},
                      {'price':Decimal('0.123456789012345678901')}):
            self.assertEqual(current_wire(value),encode(value))

    async def test_native_packing_preserves_decimal_strings_unicode_and_existing_seal(self):
        from app.collection.native_reconstruction import pack_native_image
        from app.collection.current_confirmation import content
        from app.collection.current_book_images import decode_container
        from tests.test_current_service import native_fixture
        _,book=native_fixture()
        for side in ('yes','é 🎯'):
            book['outcomes'][0]['outcome_id']=side
            book['outcomes'][0]['asks']['levels'][0]['quantity']['value']='9007199254740993.00000000000001'
            digest,image=pack_native_image(book)
            self.assertEqual(digest,content(book))
            self.assertEqual(decode_container(image),book)

    async def test_reused_levels_preserve_previous_images_and_retire_removed_prices(self):
        from app.collection import native_reconstruction as worker
        from app.collection.current_book_images import decode_container
        from copy import deepcopy
        at=datetime.now(timezone.utc)
        worker.initialize('kalshi',[market()],1,None,{})
        rows,_=worker.reconstruct([(ack(1),at),(frame(1,yes_dollars_fp=[['0.4','3'],['0.3','5']]),at)])
        first=rows[-1]['value'];saved=deepcopy(first)
        delta=json.loads(frame(2,'orderbook_delta'))
        delta['msg'].update(side='yes',price_dollars='0.4',delta_fp='-3')
        rows,_=worker.reconstruct([(json.dumps(delta),at)])
        self.assertEqual(first,saved)
        self.assertEqual(decode_container(rows[-1]['prepared_image']),rows[-1]['value'])
        self.assertEqual([x['price']['value'] for x in rows[-1]['value']['outcomes'][0]['bids']['levels']],['0.3'])
        worker.reconfigure([],None,{'request_id':2})
        self.assertFalse(worker._LEVEL_IMAGES)

    async def test_compact_transfer_keeps_full_ladder_and_confirmation_content(self):
        from app.collection import native_reconstruction as worker
        from app.collection.current_book_images import decode_container,CurrentBookImages
        from app.collection.current_confirmation import content
        from app.collection.current_native import top_price_identity
        from tests.test_polymarket_us_stream import SLUG
        at=datetime.now(timezone.utc)
        for venue,markets,request,raw,mapping in (
                ('kalshi',[market()],None,[ack(1),frame(1,yes_dollars_fp=[['0.4','3'],['0.3','5']])],None),
                ('polymarket_us',[us_market()],'r',[message('r',transactTime=at.isoformat())],{SLUG:'r'})):
            worker.initialize(venue,markets,1,request,{},mapping)
            full,_=worker.reconstruct([(v,at) for v in raw])
            worker.initialize(venue,markets,1,request,{},mapping)
            compact,_=worker.reconstruct([(v,at) for v in raw],compact=True)
            original=full[-1]['value'];entry=compact[-1];hint=entry['queue_hint']
            self.assertNotIn('value',entry)
            self.assertEqual(decode_container(entry['prepared_image']),original)
            self.assertEqual(top_price_identity(hint),top_price_identity(original))
            self.assertEqual(entry['content_sha256'],content(original))
            images=CurrentBookImages()
            images.set_prepared('m',entry['prepared_image'],exchange_at=hint['raw']['exchange_at'],confirmation=None)
            self.assertEqual(images['m'],original)

    async def test_reconstruction_does_not_retain_redundant_decoded_image_roster(self):
        from app.collection import native_reconstruction as worker
        from tests.test_polymarket_us_stream import SLUG
        at=datetime.now(timezone.utc)
        for venue,markets,request,frames,mapping in (
                ('kalshi',[market()],None,[ack(1),frame(1),frame(2,'orderbook_delta')],None),
                ('polymarket_us',[us_market()],'r',[message('r',transactTime=at.isoformat())],{SLUG:'r'})):
            worker.initialize(venue,markets,1,request,{},mapping)
            rows,_=worker.reconstruct([(raw,at) for raw in frames])
            self.assertFalse(worker._ENGINE.last)
            self.assertIsNotNone(rows[-1]['book'])
            from app.collection.current_book_images import decode_container
            self.assertEqual(decode_container(rows[-1]['prepared_image']),rows[-1]['value'])
            if venue=='kalshi':self.assertTrue(worker._ENGINE.sides)
            else:self.assertTrue(worker._ENGINE.source_time_high_water)


class ReconstructionProcess(IsolatedAsyncioTestCase):
    async def test_warm_loads_all_workers_without_consuming_a_frame(self):
        metrics={};worker=Reconstruction('kalshi',[market()],1,None,{},metrics,partitions=2)
        try:
            await worker.warm()
            self.assertEqual(len(set(metrics['reconstruction_ready_workers'])),2)
            self.assertFalse(worker.ready)
            self.assertIsNone(worker.pending)
            at=datetime.now(timezone.utc);batch=Batch([(ack(1),at),(frame(1),at)])
            await worker.recv(batch)
            row=await worker.recv(batch)
            self.assertEqual(row['value']['sequence'],'1')
            self.assertEqual(row['received'],at)
        finally:await worker.close()
        self.assertTrue(metrics['reconstruction_worker_stopped'])

    async def test_full_catalog_control_reply_preserves_sequence_and_neighbor_book(self):
        from websockets.asyncio.server import serve
        from websockets.asyncio.client import connect
        at=datetime.now(timezone.utc)
        control=json.dumps(dict(type='ok',id=2,sid=7,seq=2,
            msg=dict(market_tickers=[f'KXNCAAMBGAME-26NOV02-TEAM{i:05d}' for i in range(10000)])))
        self.assertGreater(len(control),256*1024)
        raw=[ack(1),frame(1),control,frame(3,'orderbook_delta')]
        async def send(socket):
            for body in raw:await socket.send(body)
            await socket.wait_closed()
        async with serve(send,'127.0.0.1',0) as server:
            port=server.sockets[0].getsockname()[1]
            async with connect(f'ws://127.0.0.1:{port}',max_size=1024*1024,max_queue=16,compression=None) as socket:
                batch=Batch([(await socket.recv(),at) for _ in raw])
        worker=Reconstruction('kalshi',[market()],1,None,{}, {})
        try:
            rows=[await worker.recv(batch) for _ in raw]
            self.assertFalse(any(r.get('error') for r in rows))
            self.assertIsNone(rows[2]['book'])
            self.assertEqual(rows[2]['seq'],2)
            self.assertEqual(rows[-1]['value']['sequence'],'3')
        finally:await worker.close()

    async def test_bounded_prefetch_keeps_wire_order_and_closes_owned_child(self):
        import asyncio
        from app.collection.native_receive import NativeReceive
        at=datetime.now(timezone.utc);metrics={}
        raw=[ack(1),frame(1)]+[frame(i,'orderbook_delta') for i in range(2,4100)]
        class Socket:
            def __init__(self):self.items=iter(raw)
            async def recv(self):
                try:return next(self.items)
                except StopIteration:await asyncio.Event().wait()
        receiver=NativeReceive(Socket(),metrics)
        worker=Reconstruction('kalshi',[market()],1,None,{},metrics)
        try:
            while receiver.queue.qsize()<len(raw):await asyncio.sleep(0)
            first=await worker.recv(receiver)
            self.assertIsNotNone(worker.pending)
            self.assertEqual(first['sid'],7)
            rows=[await worker.recv(receiver) for _ in range(len(raw)-1)]
            self.assertEqual([r['seq'] for r in rows],list(range(1,4100)))
            self.assertFalse(any(r.get('error') for r in rows))
            self.assertEqual(rows[-1]['value']['sequence'],'4099')
            self.assertLessEqual(metrics['reconstruction_batch_frames'],4096)
        finally:
            await receiver.close();await worker.close()
        self.assertIsNone(worker.pending)
        self.assertTrue(metrics['reconstruction_worker_stopped'])

    async def test_delayed_images_survive_multiple_catalog_transitions_without_reviving_retired_members(self):
        at=datetime.now(timezone.utc);worker=Reconstruction('kalshi',[market(),market('OLD')],1,None,{}, {})
        try:
            initial=Batch([(ack(1),at),(frame(1),at),(frame(2,mid='OLD'),at)])
            await worker.recv(initial)  # Both old-catalog images remain ready.
            await worker.reconfigure([market()],None,dict(request_id=1000001))
            await worker.reconfigure([market(),market('NEW')],None,[])
            unchanged=await worker.recv(initial);retired=await worker.recv(initial)
            self.assertFalse(worker.obsolete_book(unchanged))
            self.assertTrue(worker.obsolete_book(retired))
            self.assertEqual([unchanged['seq'],retired['seq']],[1,2])
            self.assertEqual(retired['value']['raw']['received_at'],at.isoformat())
            self.assertEqual(set(worker.market_revisions),{market().raw.ref.market_id,'NEW'})
            # An unknown image claiming the current revision must still reach
            # ordinary ownership refusal; it cannot masquerade as retired work.
            self.assertFalse(worker.obsolete_book(dict(retired,catalog_revision=worker.catalog_revision)))
            await worker.reconfigure([market(),market('NEW'),market('OLD')],None,[])
            self.assertTrue(worker.obsolete_book(retired))
            self.assertFalse(worker.obsolete_book(dict(retired,catalog_revision=worker.catalog_revision)))
            self.assertFalse(worker.obsolete_book(unchanged))
        finally:await worker.close()

    async def test_kalshi_addition_preserves_sid_sequence_and_existing_ladder(self):
        at=datetime.now(timezone.utc);worker=Reconstruction('kalshi',[market()],1,None,{}, {})
        try:
            initial=Batch([(ack(1),at),(frame(1),at)])
            await worker.recv(initial);await worker.recv(initial)
            await worker.reconfigure([market(),market('NEW')],None,[])
            replies=Batch([(json.dumps(dict(type='ok',sid=7,seq=2,id=1000001,msg={})),at),
                           (frame(3,mid='NEW'),at),(frame(4,'orderbook_delta'),at)])
            control=await worker.recv(replies);added=await worker.recv(replies);existing=await worker.recv(replies)
            self.assertIsNone(control['book']);self.assertEqual(control['seq'],2)
            self.assertEqual(added['value']['raw']['ref']['market_id'],'NEW')
            self.assertEqual(existing['seq'],4);self.assertEqual(existing['sid'],7)
            self.assertNotIn('error',existing)
        finally:await worker.close()

    async def test_kalshi_removal_keeps_other_book_and_checks_retired_sequence(self):
        at=datetime.now(timezone.utc);worker=Reconstruction('kalshi',[market(),market('OLD')],1,None,{}, {},partitions=2)
        try:
            initial=Batch([(ack(1),at),(frame(1),at),(frame(2,mid='OLD'),at)])
            for _ in range(3):await worker.recv(initial)
            await worker.reconfigure([market()],None,dict(request_id=1000001))
            replies=Batch([(frame(3,'orderbook_delta',mid='OLD'),at),
                (frame(4,'orderbook_delta'),at),
                (json.dumps(dict(type='ok',sid=7,seq=5,id=1000001,msg={})),at),
                (frame(6,'orderbook_delta'),at),(frame(7,'orderbook_delta',mid='OLD'),at)])
            retired=await worker.recv(replies);healthy=await worker.recv(replies)
            self.assertIsNone(retired['book']);self.assertNotIn('error',retired)
            self.assertEqual(healthy['seq'],4);self.assertIsNotNone(healthy['book'])
            removal_ack=await worker.recv(replies)
            self.assertIsNone(removal_ack['book'])
            self.assertEqual(removal_ack['data']['id'],1000001)
            self.assertIsNotNone((await worker.recv(replies))['book'])
            # Once acknowledged, an unexpected retired frame is fail-closed.
            self.assertIn('error',await worker.recv(replies))
        finally:await worker.close()
        engine=BookReconstructor([market(),market('OLD')]);engine.begin(1)
        engine.feed(ack(1),engine.generation,at);engine.feed(frame(1),engine.generation,at)
        engine.reconfigure([market()],1000002)
        from app.adapters.kalshi_stream import RecoveryRequired
        with self.assertRaises(RecoveryRequired):
            engine.feed(frame(3,'orderbook_delta',mid='OLD'),engine.generation,at)

    async def test_group_replacement_rejects_late_old_images_and_keeps_original_clocks(self):
        from tests.test_polymarket_us_stream import SLUG
        at=datetime.now(timezone.utc)-timedelta(seconds=5)
        worker=Reconstruction('polymarket_us',[us_market()],1,'connection',{}, {},market_requests={SLUG:'old'})
        try:
            old=await worker.recv(Batch([(message('old',transactTime=at.isoformat()),at)]))
            self.assertIsNotNone(old['book'])
            await worker.reconfigure([us_market()],{SLUG:'new'},['old'])
            later=at+timedelta(seconds=1)
            receiver=Batch([(message('old',transactTime=later.isoformat()),later),
                            (json.dumps({'requestId':'old','unsubscribed':True}),later),
                            (message('new',transactTime=later.isoformat()),later)])
            stale=await worker.recv(receiver);retirement=await worker.recv(receiver);fresh=await worker.recv(receiver)
            self.assertIsNone(stale['book']);self.assertNotIn('error',stale)
            self.assertEqual(retirement['data'],{'requestId':'old','unsubscribed':True})
            self.assertIsNone(retirement['book']);self.assertNotIn('error',retirement)
            self.assertEqual(fresh['data']['requestId'],'new')
            self.assertEqual(fresh['value']['raw']['received_at'],later.isoformat())
            self.assertEqual(fresh['value']['raw']['exchange_at'],later.isoformat())
        finally:await worker.close()

    async def test_reconstruction_and_catalog_submissions_share_one_partition_boundary(self):
        import asyncio
        from unittest.mock import patch
        from app.collection.native_reconstruction import owned_thread

        at=datetime.now(timezone.utc)
        worker=Reconstruction('kalshi',[market()],1,None,{}, {},partitions=2)
        submitting=asyncio.Event()
        concurrent=0
        peak=0

        async def measured_submit(function):
            nonlocal concurrent,peak
            concurrent+=1
            peak=max(peak,concurrent)
            submitting.set()
            try:
                await asyncio.sleep(.03)
                return await owned_thread(function)
            finally:
                concurrent-=1

        try:
            with patch('app.collection.native_reconstruction.owned_thread',side_effect=measured_submit):
                loading=asyncio.create_task(worker.load(Batch([(ack(1),at),(frame(1),at)])))
                await submitting.wait()
                (_,rows,_),_=await asyncio.gather(loading,worker.reconfigure([market(),market('NEW')],None,[]))
            self.assertEqual(peak,1)
            self.assertEqual([row['catalog_revision'] for row in rows],[0,0])
            self.assertEqual(worker.catalog_revision,1)
        finally:await worker.close()

    async def test_ordered_deltas_match_direct_and_gap_ends_the_batch(self):
        at=datetime.now(timezone.utc);metrics={};highwater={}
        values=[ack(3),frame(1),frame(2,'orderbook_delta'),frame(4,'orderbook_delta'),frame(5,'orderbook_delta')]
        receiver=Batch([(raw,at+timedelta(microseconds=i)) for i,raw in enumerate(values)])
        worker=Reconstruction('kalshi',[market()],3,None,highwater,metrics)
        direct=BookReconstructor([market()]);generation=direct.begin(3) and direct.generation
        try:
            entries=[await worker.recv(receiver) for _ in range(4)]
            for i in range(3):
                expected=direct.feed(values[i],generation,receiver.rows[i][1])
                if expected is None:self.assertIsNone(entries[i]['book'])
                else:self.assertEqual(entries[i]['value'],book_value(current_purchase_book(replace(expected,state=market().state))))
            self.assertEqual([e['seq'] for e in entries[:3]],[None,1,2])
            self.assertIn('error',entries[3])
            self.assertEqual(receiver.calls,1)
            self.assertEqual(metrics['reconstruction_frames_discarded_on_resync'],1)
            processes=list(worker.pool._processes.values())
        finally:await worker.close()
        self.assertTrue(all(not p.is_alive() for p in processes))

    async def test_independent_bad_image_isolated_and_socket_receipt_preserved(self):
        at=datetime.now(timezone.utc)-timedelta(seconds=5);metrics={};highwater={}
        bad=json.loads(message('r'));bad['marketData']['bids'][0]['px']['value']='invalid'
        receiver=Batch([(message('r',transactTime=at.isoformat()),at),
                        (json.dumps(bad),at+timedelta(seconds=1)),
                        (message('r','0.45',transactTime=(at+timedelta(seconds=2)).isoformat()),at+timedelta(seconds=2))])
        worker=Reconstruction('polymarket_us',[us_market()],1,'r',highwater,metrics)
        try:
            rows=[await worker.recv(receiver) for _ in range(3)]
            self.assertEqual(rows[0]['value']['raw']['received_at'],at.isoformat())
            self.assertIn('malformed_slug',rows[1])
            self.assertNotIn('error',rows[2])
            self.assertEqual(rows[2]['value']['raw']['received_at'],(at+timedelta(seconds=2)).isoformat())
            self.assertTrue(highwater)
            self.assertEqual(metrics['reconstruction_frames_discarded_on_resync'],0)
        finally:await worker.close()

    async def test_adjacent_deltas_keep_every_change_and_emit_only_latest_complete_image(self):
        at=datetime.now(timezone.utc);metrics={};highwater={}
        values=[ack(1),frame(1),frame(2,'orderbook_delta'),frame(3,'orderbook_delta')]
        receiver=Batch([(raw.decode() if isinstance(raw,bytes) else raw,at) for raw in values])
        worker=Reconstruction('kalshi',[market()],1,None,highwater,metrics)
        direct=BookReconstructor([market()]);direct.begin(1)
        try:
            rows=[await worker.recv(receiver) for _ in values]
            for raw in values:expected=direct.feed(raw,1,at)
            self.assertIsNone(rows[2]['book'])
            self.assertTrue(rows[2]['coalesced'])
            self.assertEqual(rows[3]['value'],book_value(current_purchase_book(replace(expected,state=market().state))))
            self.assertEqual([row['seq'] for row in rows],[None,1,2,3])
            self.assertEqual(metrics['reconstruction_coalesced_frames'],1)
            self.assertEqual(highwater,direct.source_highwater)
        finally:await worker.close()

    async def test_regressed_independent_us_image_isolated_without_losing_next_frame(self):
        at=datetime.now(timezone.utc)-timedelta(seconds=5);metrics={};highwater={}
        receiver=Batch([(message('r',transactTime=clock.isoformat()),at+timedelta(seconds=i))
            for i,clock in enumerate((at,at-timedelta(seconds=1),at+timedelta(seconds=2)))])
        worker=Reconstruction('polymarket_us',[us_market()],1,'r',highwater,metrics)
        try:
            rows=[await worker.recv(receiver) for _ in range(3)]
            self.assertEqual(rows[1]['isolated_reason'],'regressed_native_source_clock')
            self.assertIn('malformed_slug',rows[1])
            self.assertNotIn('error',rows[2])
            self.assertEqual(rows[2]['value']['raw']['exchange_at'],(at+timedelta(seconds=2)).isoformat())
            self.assertEqual(metrics['reconstruction_frames_discarded_on_resync'],0)
        finally:await worker.close()


class ReceiveBatch(IsolatedAsyncioTestCase):
    async def test_terminal_signal_follows_prior_frames_without_loss(self):
        from app.collection.native_receive import NativeReceive
        class Socket:
            def __init__(self):self.items=iter([b'first',b'second'])
            async def recv(self):
                try:return next(self.items)
                except StopIteration:raise ConnectionError('fixture_closed') from None
        revoked=[];metrics={};receiver=NativeReceive(Socket(),metrics,on_failure=lambda:revoked.append(True))
        try:
            await receiver.task
            self.assertEqual(revoked,[True])  # Revoke before queued old frames drain.
            with self.assertRaisesRegex(ConnectionError,'fixture_closed'):receiver.require_active()
            rows=await receiver.recv_batch(64,1024)
            self.assertEqual([b for b,_ in rows],[b'first',b'second'])
            with self.assertRaises(ConnectionError):await receiver.recv_batch(64,1024)
        finally:await receiver.close()
        self.assertEqual(metrics['receive_frames_discarded_on_resync'],0)

class InterleavedDeltaBatch(IsolatedAsyncioTestCase):
    async def test_interleaved_markets_materialize_final_images_with_exact_levels(self):
        from app.collection.native_reconstruction import initialize,reconstruct
        a=market();b=replace(a,raw=replace(a.raw,ref=replace(a.raw.ref,market_id='OTHER')))
        at=datetime.now(timezone.utc)
        def wire(seq,mid,kind='orderbook_delta'):
            data=json.loads(frame(seq,kind));data['msg']['market_ticker']=mid
            data['msg']['market_id']='uuid-'+mid
            return json.dumps(data)
        values=[ack(1),wire(1,a.raw.ref.market_id,'orderbook_snapshot'),wire(2,'OTHER','orderbook_snapshot')]
        values += [wire(i,a.raw.ref.market_id if i%2 else 'OTHER') for i in range(3,103)]
        direct=BookReconstructor([a,b]);direct.begin(1);expected={}
        for raw in values:
            book=direct.feed(raw,1,at)
            if book:expected[book.raw.ref.market_id]=book_value(current_purchase_book(replace(book,state=a.state)))
        initialize('kalshi',[a,b],1,None,{})
        rows,_=reconstruct([(raw,at) for raw in values])
        emitted={r['book'].raw.ref.market_id:r['value'] for r in rows if r.get('book')}
        self.assertEqual(emitted,expected)
        self.assertEqual(sum(bool(r.get('book')) for r in rows),4)
        self.assertEqual(sum(bool(r.get('coalesced')) for r in rows),98)
        self.assertEqual([r['seq'] for r in rows[1:]],list(range(1,103)))


class ProviderFailureReason(IsolatedAsyncioTestCase):
    async def test_exact_subscription_overflow_is_safe_and_stops_at_failed_frame(self):
        from app.collection import native_reconstruction as worker
        at=datetime.now(timezone.utc)
        for code,reason in ((25,'provider_subscription_buffer_overflow'),(99,'native_reconstruction_failure')):
            worker.initialize('kalshi',[market()],1,None,{})
            error=json.dumps(dict(type='error',sid=7,seq=2,msg=dict(code=code,msg='PRIVATE provider message')))
            rows,_=worker.reconstruct([(ack(1),at),(frame(1),at),(error,at),(frame(3,'orderbook_delta'),at)])
            self.assertEqual(len(rows),3)
            self.assertEqual(rows[-1]['error'],reason)
            self.assertNotIn('PRIVATE',reason)

class PartitionedReconstruction(IsolatedAsyncioTestCase):
    async def test_two_children_emit_identical_books_and_fail_at_same_sequence_gap(self):
        from app.collection.current_book_images import decode_container
        at=datetime.now(timezone.utc)
        frames=[ack(),frame(1,mid='M'),frame(2,mid='N'),frame(3,'orderbook_delta',mid='M'),
            frame(4,'orderbook_delta',mid='N'),frame(6,'orderbook_delta',mid='M'),frame(7,'orderbook_delta',mid='N')]
        outputs=[]
        for count in (1,2):
            worker=Reconstruction('kalshi',[market('M'),market('N')],1,None,{}, {},compact=True,partitions=count)
            try:
                _,rows,_=await worker.load(Batch([(f,at) for f in frames]))
                outputs.append([{k:r.get(k) for k in ('sid','seq','error','clock','content_sha256','prepared_image','queue_hint')} for r in rows])
                self.assertEqual(len(rows),6)
                self.assertEqual(rows[-1]['error'],'native_reconstruction_failure')
                for r in rows:
                    if r.get('prepared_image'):
                        b=decode_container(r['prepared_image'])
                        self.assertEqual(b['raw']['received_at'],at.isoformat())
            finally:await worker.close()
            self.assertTrue(all(p._shutdown_thread for p in worker.pools))
        self.assertEqual(outputs[0],outputs[1])

    async def test_partition_disagreement_never_adopts_partial_results(self):
        from app.collection.native_reconstruction import merge_partitions
        a=[dict(received='now',sid=7,seq=1,catalog_revision=0)]
        b=[dict(a[0],seq=2)]
        with self.assertRaisesRegex(ValueError,'partition_state_conflict'):
            merge_partitions([(a,{}),(b,{})])

    async def test_us_partitions_preserve_full_replacement_and_isolated_withdrawal(self):
        from tests.test_polymarket_us_stream import SLUG
        at=datetime.now(timezone.utc);stamp=at.isoformat()
        frames=[message('r',transactTime=stamp),message('r',offers=None,transactTime=stamp),
            message('r','0.3',transactTime=stamp),message('r','0.4',transactTime=(at-timedelta(seconds=1)).isoformat())]
        outputs=[]
        for count in (1,2):
            worker=Reconstruction('polymarket_us',[us_market()],1,'r',{}, {},compact=True,
                market_requests={SLUG:'r'},partitions=count)
            try:
                _,rows,_=await worker.load(Batch([(f,at) for f in frames]))
                outputs.append([{k:r.get(k) for k in ('error','clock','content_sha256','prepared_image','queue_hint','malformed_slug','isolated_reason')} for r in rows])
                self.assertEqual(rows[1]['malformed_slug'],SLUG)
                self.assertIsNotNone(rows[2]['book'])
                self.assertEqual(rows[3]['isolated_reason'],'regressed_native_source_clock')
            finally:await worker.close()
        self.assertEqual(outputs[0],outputs[1])
