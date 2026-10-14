"""Bounded writes of captured immutable JSON bodies under ordinary middleware.

Encoding remains synchronous and revision-coherent. Yielding transport writes
never mixes a newer state into a captured body. Clients retain their existing
latest-only generation/revision checks.
"""
from aiohttp import web
from aiohttp.payload import BytesPayload

WRITE_BYTES=64*1024


class BoundedBytes(BytesPayload):
    async def write(self,writer):
        await self.write_with_length(writer,None)

    async def write_with_length(self,writer,content_length):
        import asyncio
        view=memoryview(self._value)
        if content_length is not None:view=view[:content_length]
        for offset in range(0,len(view),WRITE_BYTES):
            await writer.write(view[offset:offset+WRITE_BYTES])
            await asyncio.sleep(0)


class ComparisonDelivery(BytesPayload):
    """Fresh request envelope around one shared immutable complete JSON body."""
    def __init__(self,body,metadata):
        from .current_contract import packed
        prefix=packed(metadata)
        self.prefix=prefix[:-1]+(b',' if len(body)>2 else b'')
        super().__init__(body,content_type='application/json')
        self._size=len(self.prefix)+len(body)-1

    async def as_bytes(self,encoding='utf-8',errors='strict'):
        return self.prefix+self._value[1:]

    def decode(self,encoding='utf-8',errors='strict'):
        return (self.prefix+self._value[1:]).decode(encoding,errors)

    async def write(self,writer):
        await self.write_with_length(writer,None)

    async def write_with_length(self,writer,content_length):
        import asyncio
        remaining=self._size if content_length is None else content_length
        prefix=self.prefix[:remaining]
        await writer.write(prefix);remaining-=len(prefix)
        view=memoryview(self._value)[1:]
        view=view[:remaining]
        for offset in range(0,len(view),WRITE_BYTES):
            await writer.write(view[offset:offset+WRITE_BYTES])
            await asyncio.sleep(0)


class CurrentResponse(web.Response):
    async def prepare(self,request):
        from .current_encoded import EncodedPayload
        from .current_contract import packed
        body=self._body
        if not self.prepared and isinstance(body,EncodedPayload):
            capture=body.capture
            for key,value in capture.items():
                if value is not None:self.headers['X-Predict-'+key]=str(value)
            if body.closed or (body.valid is not None and not body.valid()):
                body.release()
                self.body=packed(dict(error='capture_superseded',reason='Inputs changed before delivery; retry the current view.',retry_after_seconds=1))
                self.set_status(409)
        return await super().prepare(request)

    async def write_eof(self,data=b''):
        body=self._body
        from .current_encoded import EncodedPayload
        if isinstance(body,EncodedPayload):
            try:await super().write_eof(data)
            finally:body.release();self._body=None
            return
        if isinstance(body,bytes) and len(body)>WRITE_BYTES and self._compressed_body is None:
            # Wrap after middleware/header preparation. Socket-free readers
            # still see ordinary bytes; backpressure bounds transport copies.
            self._body=BoundedBytes(body)
            try:await super().write_eof(data)
            finally:self._body=None
        else:
            try:await super().write_eof(data)
            finally:
                if isinstance(body,(bytes,ComparisonDelivery)):self._body=None
