"""Finite immutable encoded HTTP bodies; explicit leases and no full-size copy.

The canonical synchronous bytes API remains separate. A body is sealed before
any await and cannot be changed by a later store revision. All files/readers are
bounded and released by EOF, request-task completion, cache eviction and Stop.
"""
import os
from tempfile import TemporaryFile
from time import monotonic
from aiohttp.payload import Payload
from .current_contract import MAX_BYTES, canonical_chunks


class EncodedBodies:
    MAX_OWNERS = 4
    MAX_READERS = 16
    CACHE_SECONDS = 30
    # Match the existing complete HTTP request bound. A synchronous temporal
    # rebuild can currently occupy more than 60 seconds of this same loop.
    # Count/byte bounds remain fixed and Stop/disconnect still release sooner.
    READER_SECONDS = 300

    def __init__(self):
        self.owners = set()
        self.readers = set()
        self.closed = False
        self.metrics = dict(created=0, released=0, peak_owners=0, peak_readers=0,
                            peak_file_bytes=0, peak_block_bytes=0)

    def encode(self, value):
        if self.closed or len(self.owners) >= self.MAX_OWNERS:
            raise ValueError('Encoded HTTP owner capacity')
        owner = EncodedBody(self)
        self.owners.add(owner)
        try:
            for chunk in canonical_chunks(value):
                owner.append(chunk.encode())
            owner.seal()
            self.metrics['created'] += 1
            self.metrics['peak_owners'] = max(self.metrics['peak_owners'], len(self.owners))
            self.metrics['peak_file_bytes'] = max(self.metrics['peak_file_bytes'], sum(o.size for o in self.owners))
            return owner
        except BaseException:
            owner.release()
            raise

    def adopt_file(self,file,size):
        if self.closed or len(self.owners)>=self.MAX_OWNERS:raise ValueError('Encoded HTTP owner capacity')
        if size>MAX_BYTES:raise ValueError('Encoded body byte capacity')
        file.flush();owner=EncodedBody(self)
        try:
            owner.file.close();owner.file=os.fdopen(os.dup(file.fileno()),'rb')
            owner.size=size;owner.sealed=True;self.owners.add(owner)
            self.metrics['created']+=1
            self.metrics['peak_owners']=max(self.metrics['peak_owners'],len(self.owners))
            self.metrics['peak_file_bytes']=max(self.metrics['peak_file_bytes'],sum(o.size for o in self.owners))
            return owner
        except BaseException:owner.close();raise

    def payload(self, owner, request=None, *, adopt=False, valid=None, alive=None, capture=None):
        if self.closed or owner.closed or len(self.readers) >= self.MAX_READERS:
            if adopt: owner.release()
            raise ValueError('Encoded HTTP reader capacity')
        reader = EncodedPayload(owner, adopt=adopt, valid=valid, alive=alive, capture=capture)
        self.readers.add(reader)
        self.metrics['peak_readers'] = max(self.metrics['peak_readers'], len(self.readers))
        reader.bind_request(request)
        return reader

    def close(self):
        self.closed = True
        for reader in tuple(self.readers): reader.abort()
        for owner in tuple(self.owners): owner.close()


class EncodedBody:
    def __init__(self, manager):
        self.manager = manager
        self.file = TemporaryFile()
        self.size = 0
        self.refs = 1
        self.closed = False
        self.sealed = False
        self.expires_at = monotonic() + manager.CACHE_SECONDS

    def __len__(self): return self.size

    def append(self, block):
        if self.closed or self.sealed: raise ValueError('Encoded body is immutable')
        if self.size + len(block) > MAX_BYTES: raise ValueError('Encoded body byte capacity')
        self.file.write(block)
        self.size += len(block)
        self.manager.metrics['peak_block_bytes'] = max(self.manager.metrics['peak_block_bytes'], len(block))

    def seal(self):
        self.file.flush()
        self.sealed = True

    def retain(self):
        if self.closed or not self.sealed: raise ValueError('Encoded body unavailable')
        self.refs += 1

    def release(self):
        if self.closed: return
        self.refs -= 1
        if self.refs == 0: self.close()

    def close(self):
        if self.closed: return
        self.closed = True
        self.file.close()
        self.manager.owners.discard(self)
        self.manager.metrics['released'] += 1

    def block(self, offset, count):
        if self.closed or not self.sealed: raise ValueError('Encoded body unavailable')
        self.file.seek(offset)
        value = self.file.read(count)
        if len(value) != count: raise ValueError('Incomplete encoded HTTP body')
        return value


class EncodedPayload(Payload):
    def __init__(self, owner, *, adopt=False, valid=None, alive=None, capture=None):
        if not adopt: owner.retain()
        super().__init__(owner, content_type='application/json')
        self._size = owner.size
        self.closed = False
        self.valid = valid
        self.alive = alive
        self.capture = capture or {}
        self.writing_task = None
        self.request_task = None
        self.request_done = None
        import asyncio
        self.expiry = asyncio.get_running_loop().call_later(owner.manager.READER_SECONDS,self.abort)

    def bind_request(self,request):
        task=getattr(request,'task',None)
        if task is not None:
            # aiohttp can reuse this task for keep-alive requests. Remove the
            # callback at EOF too, so completed readers have finite ownership.
            self.request_task=task;self.request_done=lambda _:self.release()
            task.add_done_callback(self.request_done)

    def abort(self):
        import asyncio
        task=self.writing_task
        self.release()
        if task is not None and task is not asyncio.current_task() and not task.done():task.cancel()

    def release(self):
        if self.closed: return
        self.closed = True
        self.expiry.cancel()
        if self.request_task is not None:self.request_task.remove_done_callback(self.request_done)
        self.request_task=None;self.request_done=None;self.writing_task=None;self.valid=None
        self.alive=None
        self._value.manager.readers.discard(self)
        self._value.release()

    async def close(self):
        self.release()

    async def write(self, writer):
        await self.write_with_length(writer, None)

    async def write_with_length(self, writer, content_length):
        import asyncio
        self.writing_task=asyncio.current_task()
        length = self._size if content_length is None else min(content_length, self._size)
        try:
            async with asyncio.timeout(self._value.manager.READER_SECONDS):
                for offset in range(0, length, 65536):
                    # Eligibility is checked before HTTP headers. Once sealed,
                    # transport owns bytes only, never authority to publish them
                    # as current. Stop and the original reader deadline still
                    # revoke delivery; ordinary supersession does not tear JSON.
                    if self.closed or (self.alive is not None and not self.alive()):raise ConnectionResetError('Encoded delivery stopped')
                    await writer.write(self._value.block(offset, min(65536, length-offset)))
                    # Backpressure still applies to every 64 KiB write. Avoid
                    # forcing a source-admission turn between every fragment of
                    # a large capture; queued synchronous admissions otherwise
                    # hold the reader for hundreds of turns.
                    if (offset//65536+1)%16==0:await asyncio.sleep(0)
        finally: self.release()

    async def as_bytes(self, encoding='utf-8', errors='strict'):
        # Explicit synchronous consumer compatibility, never used by HTTP writes.
        return self._value.block(0, self._size)

    def decode(self, encoding='utf-8', errors='strict'):
        return self._value.block(0, self._size).decode(encoding, errors)


class EncodedDelivery(EncodedPayload):
    """Fresh bounded metadata prefix over shared complete economic bytes."""
    def __init__(self,owner,metadata,request=None,*,valid=None,alive=None,capture=None):
        from .current_contract import packed
        if owner.manager.closed or owner.closed or len(owner.manager.readers)>=owner.manager.MAX_READERS:
            owner.release();raise ValueError('Encoded HTTP reader capacity')
        try:prefix=packed(metadata)
        except BaseException:owner.release();raise
        self.prefix=prefix[:-1]+(b',' if owner.size>2 else b'')
        if len(self.prefix)+owner.size-1>MAX_BYTES:
            owner.release();raise ValueError('Encoded delivery byte capacity')
        super().__init__(owner,adopt=True,valid=valid,alive=alive,capture=capture)
        self._size=len(self.prefix)+owner.size-1
        owner.manager.readers.add(self)
        owner.manager.metrics['peak_readers']=max(owner.manager.metrics['peak_readers'],len(owner.manager.readers))
        self.bind_request(request)

    async def write_with_length(self,writer,content_length):
        import asyncio
        self.writing_task=asyncio.current_task()
        remaining=self._size if content_length is None else min(content_length,self._size)
        try:
            async with asyncio.timeout(self._value.manager.READER_SECONDS):
                if self.closed or (self.alive is not None and not self.alive()):raise ConnectionResetError('Encoded delivery stopped')
                prefix=self.prefix[:remaining];await writer.write(prefix);remaining-=len(prefix)
                for offset in range(1,1+remaining,65536):
                    if self.closed or (self.alive is not None and not self.alive()):raise ConnectionResetError('Encoded delivery stopped')
                    await writer.write(self._value.block(offset,min(65536,1+remaining-offset)))
                    if ((offset-1)//65536+1)%16==0:await asyncio.sleep(0)
        finally:self.release()

    async def as_bytes(self,encoding='utf-8',errors='strict'):
        return self.prefix+self._value.block(1,self._value.size-1)

    def decode(self,encoding='utf-8',errors='strict'):
        return (self.prefix+self._value.block(1,self._value.size-1)).decode(encoding,errors)
