"""Single socket reader, independent of reconstruction and downstream callbacks."""
import asyncio
from collections import deque
from datetime import datetime, timezone
import time


class NativeReceive:
    def __init__(self, socket, metrics, *, byte_limit=32*1024*1024, on_failure=None):
        self.socket=socket
        self.metrics=metrics
        self.byte_limit=byte_limit
        self.bytes=0
        self.queue=asyncio.Queue()
        self.arrivals=deque()
        self.on_failure=on_failure
        self.error=None
        self.capacity_failed=False
        self.task=asyncio.create_task(self.read(),name='predict-native-socket-reader')

    async def read(self):
        try:
            while True:
                body=await self.socket.recv()
                received=datetime.now(timezone.utc)
                size=len(body.encode()) if isinstance(body,str) else len(body)
                self.metrics['socket_reads']=self.metrics.get('socket_reads',0)+1
                self.metrics['last_socket_read_at']=received.isoformat()
                if self.bytes+size>self.byte_limit:
                    self.capacity_failed=True
                    self.metrics['receive_capacity_failures']=self.metrics.get('receive_capacity_failures',0)+1
                    raise ValueError('native_receive_backlog_capacity')
                self.bytes+=size
                self.arrivals.append(time.monotonic())
                self.queue.put_nowait((body,received,size))
                self.metrics['receive_buffer_peak_bytes']=max(self.metrics.get('receive_buffer_peak_bytes',0),self.bytes)
                self.measure()
                # Buffered receives need not suspend; give heartbeat/Stop a turn.
                if self.metrics['socket_reads']%64==0:await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error=exc
            if self.on_failure:self.on_failure()
            self.queue.put_nowait(None)

    def require_active(self):
        """Live publication cannot drain frames after connection authority is revoked."""
        if self.error is not None:raise self.error

    def measure(self):
        self.metrics['receive_buffer_bytes']=self.bytes
        self.metrics['receive_buffer_frames']=len(self.arrivals)
        self.metrics['receive_oldest_seconds']=time.monotonic()-self.arrivals[0] if self.arrivals else 0

    async def recv(self):
        # A lost frame breaks delta continuity. Resynchronize immediately rather
        # than leaving a stopped reader behind minutes of queued work.
        if self.capacity_failed:raise self.error
        row=await self.queue.get()
        if row is None:
            raise self.error
        body,received,size=row
        self.bytes-=size
        self.arrivals.popleft()
        self.metrics['receive_queue_wait_ms']=(datetime.now(timezone.utc)-received).total_seconds()*1000
        self.measure()
        return body,received

    async def recv_batch(self,limit,byte_limit):
        first=await self.recv();rows=[first]
        size=len(first[0].encode()) if isinstance(first[0],str) else len(first[0])
        while len(rows)<limit and size<byte_limit and not self.queue.empty():
            if self.capacity_failed:
                self.metrics['receive_frames_discarded_on_resync']=self.metrics.get('receive_frames_discarded_on_resync',0)+len(rows)
                raise self.error
            try:row=await self.recv()
            except Exception:
                # Preserve the terminal signal for the next batch, after these
                # earlier complete frames have been reconstructed in order.
                self.queue.put_nowait(None)
                break
            rows.append(row);size+=len(row[0].encode()) if isinstance(row[0],str) else len(row[0])
        return rows

    async def close(self):
        self.task.cancel()
        await asyncio.gather(self.task,return_exceptions=True)
        self.metrics['receive_frames_discarded_on_resync']=self.metrics.get('receive_frames_discarded_on_resync',0)+len(self.arrivals)
        while not self.queue.empty():self.queue.get_nowait()
        self.bytes=0;self.arrivals.clear();self.measure()
