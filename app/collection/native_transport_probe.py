"""Payload-free evidence at the installed websocket protocol/flow-control boundary."""
from collections import deque
import time
from websockets.asyncio.client import ClientConnection
from websockets.frames import Frame, PING, PONG, CLOSE


class ProbedConnection(ClientConnection):
    def __init__(self,*args,probe_metrics=None,probe_generation=None,**kwargs):
        self.probe_metrics=probe_metrics if probe_metrics is not None else {}
        self.probe_generation=probe_generation
        self.probe_events=deque(maxlen=48)
        self.probe_start=time.monotonic()
        super().__init__(*args,**kwargs)

    def evidence(self,kind,**values):
        transport=getattr(self,'transport',None)
        row=dict(kind=kind,elapsed=round(time.monotonic()-self.probe_start,6),generation=self.probe_generation,**values)
        if transport:
            row.update(write_buffer=transport.get_write_buffer_size(),reading=transport.is_reading())
        assembler=getattr(self,'recv_messages',None)
        if assembler is not None:row.update(protocol_frames=len(assembler.frames),protocol_paused=assembler.paused)
        self.probe_events.append(row)
        self.probe_metrics['transport_trace']=list(self.probe_events)

    async def ping(self,data=None):
        start=time.monotonic();self.evidence('ping_invoked',pending=len(self.pending_pings))
        waiter=await super().ping(data)
        self.evidence('ping_flow_control_complete',seconds=time.monotonic()-start,pending=len(self.pending_pings))
        return waiter

    async def drain(self):
        started=time.monotonic()
        await super().drain()
        elapsed=time.monotonic()-started
        self.probe_metrics['transport_drain_max_seconds']=max(self.probe_metrics.get('transport_drain_max_seconds',0),elapsed)
        if elapsed>.1:self.evidence('write_pressure_released',seconds=elapsed)

    def data_received(self,data):
        self.probe_metrics['protocol_received_bytes']=self.probe_metrics.get('protocol_received_bytes',0)+len(data)
        self.probe_metrics['protocol_last_receive_monotonic']=time.monotonic()
        started=time.monotonic();super().data_received(data)
        self.probe_metrics['protocol_processing_max_seconds']=max(self.probe_metrics.get('protocol_processing_max_seconds',0),time.monotonic()-started)

    def process_event(self,event):
        if isinstance(event,Frame) and event.opcode in (PING,PONG,CLOSE):
            self.evidence({PING:'peer_ping',PONG:'peer_pong',CLOSE:'peer_close'}[event.opcode],
                          matched=bytes(event.data) in self.pending_pings if event.opcode==PONG else None)
        super().process_event(event)

    def acknowledge_pings(self,data):
        matched=data in self.pending_pings
        super().acknowledge_pings(data)
        if matched:self.evidence('pong_acknowledged',pending=len(self.pending_pings),latency=self.latency)

    def send_data(self):
        super().send_data()
        close=getattr(self.protocol,'close_sent',None)
        if close and not getattr(self,'probe_close_recorded',False):
            self.probe_close_recorded=True
            self.evidence('close_written',code=close.code,heartbeat_timeout=close.reason=='keepalive ping timeout')

    async def send(self,message,*args,**kwargs):
        self.evidence('control_send_started',bytes=len(message) if isinstance(message,(str,bytes)) else None)
        started=time.monotonic()
        try:return await super().send(message,*args,**kwargs)
        finally:self.evidence('control_send_finished',seconds=time.monotonic()-started)

    def connection_lost(self,exc):
        self.evidence('connection_lost',transport_error=exc is not None,pending=len(self.pending_pings))
        super().connection_lost(exc)
