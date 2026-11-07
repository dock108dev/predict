import asyncio
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock,patch
from app.collection.current_native import NativeWorker
from app.collection.current_policy import DEFAULT
from app.collection.native_queue_accounting import QueueAccounting


class NativeQueue(IsolatedAsyncioTestCase):
    def test_bounded_generations_keep_inflight_and_replacement_distinct(self):
        q=QueueAccounting('kalshi');q.admit('same',0);q.claim(['same'])
        for gen in range(1,17):
            q.admit('same',gen);q.admit('same',gen)
            q.depart(['same'],'quiescence',pending=True)
        q.depart(['same'])
        s=q.snapshot()
        self.assertEqual((s['admissions'],s['completions'],s['withdrawals'],s['residual']),(17,1,16,0))
        self.assertEqual(len(s['generations']),9)
        self.assertTrue(all(r['residual']==0 for r in s['generations']))

    async def test_cancel_before_start_with_pending_replacement_and_partial_rejection(self):
        w=NativeWorker(SimpleNamespace(dispatch=True,database_mode=True,config=DEFAULT,books=lambda *args:None),'polymarket_us')
        w.persist_raw=AsyncMock()
        def book(key):return dict(raw=dict(received_at=datetime.now(timezone.utc).isoformat(),ref=dict(market_id=key)),outcomes=[])
        w.queue_book(book('a'));w.flush_books();w.queue_book(book('a'))
        w.publication_task.cancel();await asyncio.gather(w.publication_task,return_exceptions=True)
        s=w.queue_accounting.snapshot()
        self.assertEqual((s['admissions'],s['pending'],s['inflight'],s['withdrawals']),(2,1,0,1))
        w.queue_derived(book('bad'));w.queue_book(book('invalid'));w.invalid_received['invalid']='9999'
        async def admit(service,fn,venue,books):
            if any(b['raw']['ref']['market_id']=='bad' for b in books):raise ValueError('fixture')
        with patch('app.collection.current_native.call',side_effect=admit),patch('app.collection.bulk_checkpoint.save_images') as save:
            w.flush_books();await w.publication_task
        s=w.queue_accounting.snapshot();self.assertEqual((s['completions'],s['withdrawals'],s['residual']),(1,3,0))
        reason=s['generations'][-1]['reasons']
        self.assertEqual([reason[k] for k in ('cancellation','invalidated','rejected')],[1,1,1])
        self.assertEqual([x.args[2] for x in save.call_args_list],['pending','admitted','rejected'])
        await w.raw_task

    async def test_still_fresh_material_uses_priority_slot_beside_fifo(self):
        w=NativeWorker(SimpleNamespace(dispatch=True,database_mode=True,config=DEFAULT,books=lambda *args:None),'kalshi')
        w.persist_raw=AsyncMock();at=datetime.now(timezone.utc).isoformat()
        for i in range(260):
            key=str(i);w.derived_versions[key]='old';w.queue_book(dict(raw=dict(received_at=at,
                exchange_at=at if i>=200 else '2000-01-01T00:00:00+00:00',ref=dict(market_id=key)),outcomes=[]))
            w.pending_since[key]=float(i)
        seen=[]
        async def admit(service,fn,venue,books):seen.extend(b['raw']['ref']['market_id'] for b in books)
        with patch('app.collection.current_native.call',side_effect=admit),patch('app.collection.bulk_checkpoint.save_images'):
            w.flush_books();await w.publication_task
        self.assertEqual(seen[:4],['0','200','1','201'])
        w.publication_handle.cancel();w.withdraw_pending(list(w.pending_books),'resync')
        s=w.queue_accounting.snapshot()
        self.assertEqual((s['completions'],s['withdrawals'],s['pending'],s['residual']),(128,132,0,0))
        await w.raw_task

    async def test_coalesced_fresh_confirmation_beats_expired_material_with_fifo_preserved(self):
        w=NativeWorker(SimpleNamespace(dispatch=True,database_mode=True,config=DEFAULT,books=lambda *args:None),'kalshi')
        w.persist_raw=AsyncMock()
        now=datetime.now(timezone.utc).isoformat()
        for i in range(160):
            key=str(i)
            b=dict(raw=dict(received_at=now,exchange_at='2000-01-01T00:00:00+00:00',ref=dict(market_id=key)),outcomes=[])
            w.queue_book(b)
            w.derived_versions[key]=w.pending_price_versions[key] if i==159 else 'different'
            if i==159:
                w.queue_book(dict(b,book_confirmation=dict(confirmed_at=now)))
            w.pending_since[key]=float(i)
        seen=[]
        async def admit(service,fn,venue,books):seen.extend(b['raw']['ref']['market_id'] for b in books)
        with patch('app.collection.current_native.call',side_effect=admit),patch('app.collection.bulk_checkpoint.save_images'):
            w.flush_books();await w.publication_task
        self.assertEqual(seen[:2],['0','159'])
        sample=next(t for t in w.metrics['delivery_trace'] if t['market_id']=='159')
        self.assertEqual((sample['coalesced_replacements'],sample['confirmed_at']),(1,now))
        self.assertNotIn('material_change_received_at',sample)
        self.assertEqual(w.queue_accounting.snapshot()['residual'],0)
        w.publication_handle.cancel()
        await w.raw_task
