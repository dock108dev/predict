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
            if venue=='kalshi':self.assertTrue(worker._ENGINE.sides)
            else:self.assertTrue(worker._ENGINE.source_time_high_water)


class ReconstructionProcess(IsolatedAsyncioTestCase):
    async def test_bounded_prefetch_keeps_wire_order_and_closes_owned_child(self):
        import asyncio
        from app.collection.native_receive import NativeReceive
        at=datetime.now(timezone.utc);metrics={}
        raw=[ack(1),frame(1)]+[frame(i,'orderbook_delta') for i in range(2,2051)]
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
            self.assertEqual([r['seq'] for r in rows],list(range(1,2051)))
            self.assertFalse(any(r.get('error') for r in rows))
            self.assertEqual(rows[-1]['value']['sequence'],'2050')
            self.assertLessEqual(metrics['reconstruction_batch_frames'],2048)
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
        at=datetime.now(timezone.utc);worker=Reconstruction('kalshi',[market(),market('OLD')],1,None,{}, {})
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
            self.assertIsNone((await worker.recv(replies))['book'])
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
                            (message('new',transactTime=later.isoformat()),later)])
            stale=await worker.recv(receiver);fresh=await worker.recv(receiver)
            self.assertIsNone(stale['book']);self.assertNotIn('error',stale)
            self.assertEqual(fresh['data']['requestId'],'new')
            self.assertEqual(fresh['value']['raw']['received_at'],later.isoformat())
            self.assertEqual(fresh['value']['raw']['exchange_at'],later.isoformat())
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
