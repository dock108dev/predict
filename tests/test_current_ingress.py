"""Slow SQL cannot own the event loop or lose its serialized commit lifetime."""
import asyncio
from threading import Event, get_ident
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from app.collection.current_ingress import Ingress, operation, call
from app.collection.current_database import DatabaseIngressSink


class SlowSink:
    commit_async = DatabaseIngressSink.commit_async

    def __init__(self):
        self.entered=Event();self.release=Event();self.finished=[];self.prepared=[]
        self.metrics=dict(rejected_observations=0)
        self.loop_thread=get_ident()

    def prepare(self,row,states,revoked):
        assert get_ident()!=self.loop_thread
        self.entered.set();self.release.wait(3)
        if revoked.is_set():raise asyncio.CancelledError()
        self.prepared.append(row)
        return row

    def finish(self,row,states):
        assert get_ident()==self.loop_thread
        self.finished.append(row)
        return 'committed'


class Service:
    database_mode=True

    def __init__(self):
        self.sink=SlowSink();self.ingress=Ingress(self);self.acknowledged=[]

    @operation
    def publish(self, value):
        acknowledgment=yield value, {}
        self.acknowledged.append((value,acknowledgment))


class OwnedIngress(IsolatedAsyncioTestCase):
    async def entered(self, service):
        for _ in range(100):
            if service.sink.entered.is_set():return
            await asyncio.sleep(.001)
        self.fail('SQL worker did not start')

    async def test_slow_sql_allows_loop_ticks_and_acknowledges_in_source_order(self):
        service=Service();first=asyncio.create_task(call(service,service.publish,1))
        await self.entered(service)
        second=asyncio.create_task(call(service,service.publish,2))
        ticks=0
        for _ in range(10):
            await asyncio.sleep(.002);ticks+=1
        self.assertEqual(ticks,10);self.assertEqual(service.sink.finished,[])
        service.sink.release.set();await asyncio.gather(first,second)
        self.assertEqual(service.acknowledged,[(1,'committed'),(2,'committed')])
        self.assertEqual(service.sink.prepared,[1,2])

    async def test_cancel_and_shutdown_keep_work_owned_until_exit_without_late_adoption(self):
        service=Service();task=asyncio.create_task(call(service,service.publish,'obsolete'))
        await self.entered(service);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertFalse(await service.ingress.drain(.01))
        self.assertEqual(len(service.ingress.tasks),1)
        service.sink.release.set()
        self.assertTrue(await service.ingress.drain(1))
        self.assertEqual(service.sink.finished,[]);self.assertEqual(service.acknowledged,[])
        await call(service,service.publish,'new')
        self.assertEqual(service.acknowledged,[('new','committed')])

    async def test_bounded_admission_and_revoked_queued_work_never_executes(self):
        service=Service();tasks=[asyncio.create_task(call(service,service.publish,n)) for n in range(8)]
        await self.entered(service)
        waiting=asyncio.create_task(call(service,service.publish,9))
        await asyncio.sleep(.01)
        self.assertFalse(waiting.done())
        service.ingress.revoke();service.sink.release.set()
        await asyncio.gather(*tasks,waiting,return_exceptions=True)
        self.assertEqual(service.sink.finished,[])
        self.assertFalse(service.ingress.tasks)

    async def test_book_cpu_preparation_overlaps_sql_and_revocation_blocks_adoption(self):
        started=Event();release=Event()
        class ParallelSink(SlowSink):
            process_normalization=True
            def precompute_books(self,source,books,revoked):
                if source=='polymarket_us':started.set();release.wait(3)
                return dict(source=source)
            def prepare(self,row,states,revoked,*,precomputed):
                assert precomputed['source']==row
                return super().prepare(row,states,revoked)
        class NativeService(Service):
            def __init__(self):
                super().__init__();self.sink=ParallelSink()
            @operation
            def books(self,source,books):
                yield source,{}
        service=NativeService()
        first=asyncio.create_task(call(service,service.books,'kalshi',[1]))
        await self.entered(service)
        second=asyncio.create_task(call(service,service.books,'polymarket_us',[2]))
        for _ in range(100):
            if started.is_set():break
            await asyncio.sleep(.001)
        self.assertTrue(started.is_set(),'Second source CPU preparation waited behind first SQL')
        service.ingress.revoke();release.set();service.sink.release.set()
        await asyncio.gather(first,second,return_exceptions=True)
        self.assertEqual(service.sink.finished,[])
        self.assertFalse(service.ingress.tasks)

    async def test_stop_revokes_before_slow_control_persistence(self):
        from unittest.mock import AsyncMock, Mock
        from app.collection.data_runtime import DataRuntime
        persisted=asyncio.Event();release=asyncio.Event()
        service=SimpleNamespace(dispatch=True,globally_stopped=False,ingress=Mock(),cleanup_errors=[],close=AsyncMock())
        runtime=DataRuntime(service=service)
        async def persistence(*args):
            persisted.set();await release.wait()
        runtime.persist_control=persistence
        task=asyncio.create_task(runtime.control('stop',{}))
        try:
            await persisted.wait()
            self.assertFalse(service.dispatch)
            service.ingress.revoke.assert_called_once()
        finally:
            release.set();await task

class CursorLifetime(IsolatedAsyncioTestCase):
    async def test_row_factory_does_not_retain_its_cursor_or_result_buffer(self):
        import gc
        import weakref
        from unittest.mock import patch
        from app.storage.payload_codec import payload_row
        class Cursor:
            connection=object()
        cursor=Cursor();reference=weakref.ref(cursor)
        with patch('psycopg.rows.dict_row',new=lambda cursor:lambda values:dict(facts=values[0])):
            cursor.row_factory=payload_row(cursor)
        previous=gc.isenabled();gc.disable()
        try:
            self.assertEqual(cursor.row_factory([{'original':'unchanged'}]),{'facts':{'original':'unchanged'}})
            del cursor
            self.assertIsNone(reference(), 'cursor/result must release without a cyclic-GC pass')
        finally:
            if previous:gc.enable()


class CatalogPreparation(IsolatedAsyncioTestCase):
    async def test_catalog_preparation_does_not_block_prices_or_replace_new_catalog(self):
        from unittest.mock import patch
        started=Event();release=Event();calls=[]
        class CatalogService:
            database_mode=True
            def __init__(self):
                self.sink=SimpleNamespace(reducer=SimpleNamespace(inventory={},generation=0),commit_async=self.commit)
                self.ingress=Ingress(self);self.commits=[]
            async def commit(self,row,states,revoked):
                self.commits.append(row)
                if row=='newer':self.sink.reducer=SimpleNamespace(inventory={'newer':{}},generation=1)
            @operation
            def catalog(self,source,cat,*,prepared,catalog_delta):
                yield prepared,{}
            @operation
            def prices(self,source,value):
                yield value,{}
        service=CatalogService()
        def prepare(base,*args,**kwargs):
            calls.append(base)
            if len(calls)==1:started.set();release.wait(3)
            return dict(base,prepared=True)
        with patch('app.collection.current_service.prepare_catalog',side_effect=prepare), \
                patch('app.collection.current_catalog_delta.changes',return_value={}):
            task=asyncio.create_task(call(service,service.catalog,'kalshi',{}))
            for _ in range(100):
                if started.is_set():break
                await asyncio.sleep(.001)
            self.assertTrue(started.is_set())
            try:
                await asyncio.wait_for(call(service,service.prices,'kalshi','price'),.5)
                await asyncio.wait_for(call(service,service.prices,'kalshi','newer'),.5)
                self.assertFalse(task.done())
            finally:release.set()
            await asyncio.wait_for(task,3)
        self.assertEqual(service.commits,['price','newer',{'newer':{},'prepared':True}])
        self.assertEqual(len(calls),2)
