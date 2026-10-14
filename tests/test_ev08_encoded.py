import asyncio
import unittest
from unittest.mock import patch
from app.dashboard.current_contract import packed
from app.dashboard.current_encoded import EncodedBodies


class EncodedOwnership(unittest.IsolatedAsyncioTestCase):
    async def test_canonical_and_interleaved_readers_release_explicitly(self):
        pool=EncodedBodies();value={'rows':[{'exact':'é🙂','price':'0.24'}]*9000}
        body=pool.encode(value);a=pool.payload(body);b=pool.payload(body)
        body.release()
        class Writer:
            def __init__(self):self.blocks=[]
            async def write(self,block):self.blocks.append(block);await asyncio.sleep(0)
        x,y=Writer(),Writer();await asyncio.gather(a.write(x),b.write(y))
        self.assertEqual(b''.join(x.blocks),packed(value));self.assertEqual(x.blocks,y.blocks)
        self.assertLessEqual(max(map(len,x.blocks)),65536)
        self.assertTrue(body.file.closed);self.assertFalse(pool.owners);self.assertFalse(pool.readers)

    async def test_failure_disconnect_timeout_and_stop_close_files(self):
        for cause in ('write_failure','timeout','stop'):
            pool=EncodedBodies();body=pool.encode({'data':['x'*2048]*200});reader=pool.payload(body,adopt=True)
            class Writer:
                async def write(self,block):
                    if cause=='write_failure':raise ConnectionResetError()
                    if cause=='timeout':await asyncio.Event().wait()
                    pool.close()
            with patch.object(pool,'READER_SECONDS',.01):
                with self.assertRaises((ConnectionResetError,TimeoutError,ValueError)):
                    await reader.write(Writer())
            self.assertTrue(body.file.closed);self.assertFalse(pool.owners);self.assertFalse(pool.readers)

    async def test_request_completion_before_eof_and_cache_lease_isolation(self):
        pool=EncodedBodies();body=pool.encode({'state_revision':3})
        task=asyncio.create_task(asyncio.sleep(0))
        request=type('Request',(),{'task':task})()
        reader=pool.payload(body,request);await task;await asyncio.sleep(0)
        self.assertTrue(reader.closed);self.assertFalse(body.closed)
        body.release();self.assertTrue(body.file.closed)

    async def test_cache_expiry_during_loop_stall_does_not_truncate_reader(self):
        import time
        pool=EncodedBodies();pool.READER_SECONDS=.2
        body=pool.encode({'rows':['retained price']*9000});reader=pool.payload(body)
        asyncio.get_running_loop().call_later(.01,body.release)
        class Writer:
            def __init__(self):self.blocks=[]
            async def write(self,block):
                self.blocks.append(block)
                if len(self.blocks)==1:time.sleep(.03)
        writer=Writer();await reader.write(writer)
        self.assertEqual(b''.join(writer.blocks),packed({'rows':['retained price']*9000}))
        # The short body can now finish within one transport burst. Let the
        # expired cache callback run independently of the completed reader.
        await asyncio.sleep(.001)
        self.assertTrue(body.closed);self.assertFalse(pool.readers)

    async def test_keep_alive_request_does_not_retain_completed_readers(self):
        import weakref
        pool=EncodedBodies();owner=pool.encode({'price':'0.24'})
        task=asyncio.create_task(asyncio.Event().wait())
        request=type('Request',(),{'task':task})();refs=[]
        for _ in range(30):
            reader=pool.payload(owner,request);refs.append(weakref.ref(reader))
            reader.release();del reader
        self.assertTrue(all(ref() is None for ref in refs))
        owner.release();self.assertTrue(owner.closed)
        task.cancel();await asyncio.gather(task,return_exceptions=True);pool.close()

    async def test_repeated_encoding_no_gc_or_retention(self):
        pool=EncodedBodies()
        for age in range(50):
            body=pool.encode({'rows':[{'age':age,'utf8':'é'}]*1000})
            body.release();self.assertFalse(pool.owners)
        self.assertEqual(pool.metrics['created'],pool.metrics['released'])

    async def test_capacity_and_nonfinite_failure_cleanup(self):
        pool=EncodedBodies();bodies=[pool.encode({'a':i}) for i in range(pool.MAX_OWNERS)]
        with self.assertRaises(ValueError):pool.encode({'a':5})
        for body in bodies:body.release()
        with self.assertRaises(ValueError):pool.encode({'a':float('nan')})
        with patch('app.dashboard.current_encoded.MAX_BYTES',3):
            with self.assertRaises(ValueError):pool.encode({'a':'too long'})
        self.assertFalse(pool.owners)
        owner=pool.encode({'a':1});readers=[pool.payload(owner) for _ in range(pool.MAX_READERS)]
        with self.assertRaises(ValueError):pool.payload(owner)
        with self.assertRaises(ValueError):owner.append(b'x')
        owner.release();pool.close()
        self.assertTrue(owner.closed);self.assertTrue(all(r.closed for r in readers))
