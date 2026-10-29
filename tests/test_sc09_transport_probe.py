import asyncio
from functools import partial
import json
from unittest import IsolatedAsyncioTestCase
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from app.collection.native_transport_probe import ProbedConnection
from app.collection.retained_memory import measure


class ProtocolTrace(IsolatedAsyncioTestCase):
    async def test_actual_protocol_ping_pong_and_control_write_without_payload_logging(self):
        async def echo(socket):
            async for value in socket:await socket.send(value)
        metrics={}
        async with serve(echo,'127.0.0.1',0) as server:
            port=server.sockets[0].getsockname()[1]
            async with connect('ws://127.0.0.1:'+str(port),create_connection=partial(ProbedConnection,probe_metrics=metrics,probe_generation=7),ping_interval=20,ping_timeout=60) as socket:
                await socket.send('private-payload-not-a-diagnostic')
                self.assertEqual(await socket.recv(),'private-payload-not-a-diagnostic')
                pong=await socket.ping(b'private-ping-token')
                await asyncio.wait_for(pong,1)
        kinds={e['kind'] for e in metrics['transport_trace']}
        self.assertTrue({'ping_invoked','ping_flow_control_complete','peer_pong','pong_acknowledged','control_send_finished','connection_lost'}<=kinds)
        self.assertTrue(all(e['generation']==7 for e in metrics['transport_trace']))
        self.assertNotIn('private-',json.dumps(metrics))
        self.assertGreater(metrics['protocol_received_bytes'],0)

    def test_memory_counts_shared_objects_once_and_bounds_work(self):
        shared={'values':[str(i) for i in range(20)]}
        result=measure([('first',shared),('second',shared)])
        self.assertGreater(result['roots']['first']['unique_bytes'],0)
        self.assertEqual(result['roots']['second']['unique_bytes'],0)
        self.assertNotIn('values',json.dumps(result))
        self.assertTrue(measure([('first',shared)],limit=2)['roots']['first']['incomplete'])


def test_small_encoder_and_owned_book_projection_preserve_exact_values():
    from dataclasses import asdict
    from datetime import datetime,timezone
    from decimal import Decimal
    from app.dashboard.current_contract import packed,canonical_chunks
    from app.collection.native_book_value import book_value
    from app.adapters.polymarket_us_stream import MarketStream
    from tests.test_polymarket_us import market
    from tests.test_polymarket_us_stream import message
    stream=MarketStream([market()],None);generation=stream.begin_subscription('r')
    book=stream.parse(message('r'),'r',generation=generation)
    old=json.loads(json.dumps(asdict(book),default=lambda v:v.isoformat() if isinstance(v,datetime) else str(v)))
    assert book_value(book)==old
    for value in [old,{'unicode':'é 🎯','quoted':'\\\"','amount':None,'zero':-0.0,'array':[True,False,1,2.3]}, {'large':list(range(1000))}]:
        assert packed(value)==''.join(canonical_chunks(value)).encode()
    assert book_value((Decimal('0.1234567890123456789'),datetime(2026,1,1,tzinfo=timezone.utc)))==['0.1234567890123456789','2026-01-01T00:00:00+00:00']
