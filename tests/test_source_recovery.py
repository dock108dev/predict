"""Disposable failures across native retry bursts; no provider traffic."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from app.collection.current_native import NativeWorker
from app.collection.current_policy import DEFAULT
from app.collection.odds_http import BudgetStop
from tests.test_current_native import Credential


class Recovery(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, reason, *, denied=False, stop=False):
        states=[]
        service=SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True,
            deadline=asyncio.get_running_loop().time()+1000,
            source_state=lambda *a:states.append(a),issue=lambda *a:None,observation=lambda *a:None)
        worker=NativeWorker(service,'polymarket_us')
        client=SimpleNamespace(budget=SimpleNamespace(requests=0,bytes=0),aclose=AsyncMock())
        calls=0
        async def discover():
            nonlocal calls
            calls+=1
            client.budget.requests+=1
            if calls <= 3:
                worker.receipt(dict(path='/v1/markets',status=401 if denied else 200,
                    complete=False,usable_metadata=False,body_sha256='0'*64,
                    delivery_reason=reason))
                raise BudgetStop(reason)
            worker.closed=True
        async def sleep(delay):
            if stop:service.dispatch=False
            # Simulate passing the actual cooldown without resetting budgets.
            worker.backoff_until=0
        with patch('app.collection.current_native.load_credentials',return_value={'polymarket_us':Credential()}),patch('app.collection.current_native.REST',return_value=client),patch('app.collection.current_native.native_payload.configure_transport'),patch.object(worker,'discover',side_effect=discover),patch('app.collection.current_native.asyncio.sleep',side_effect=sleep):
            await worker.run()
        client.aclose.assert_awaited_once()
        return worker,client,calls,states

    async def test_framing_failure_recovers_after_burst_without_resetting_budget(self):
        for reason in ('native_http_framing_error','native_http_length_mismatch','native_http_timeout'):
            with self.subTest(reason=reason):
                worker,client,calls,states=await self.exercise(reason)
                self.assertEqual(calls,4)
                self.assertEqual(client.budget.requests,4)
                self.assertFalse(worker.failed)
                self.assertEqual(worker.metrics['last_discovery_failure']['reason'],reason)
                self.assertTrue(any('next bounded retry' in s[-1] for s in states))

    async def test_authentication_denial_does_not_retry(self):
        worker,client,calls,states=await self.exercise('native_http_framing_error',denied=True)
        self.assertEqual(calls,1)
        self.assertTrue(worker.failed)

    async def test_owner_stop_during_backoff_does_not_dispatch_again(self):
        worker,client,calls,states=await self.exercise('native_http_framing_error',stop=True)
        self.assertEqual(calls,1)
        self.assertFalse(worker.failed)

    async def test_malformed_metadata_stays_blocked(self):
        worker,client,calls,states=await self.exercise('native_malformed_json')
        self.assertEqual(calls,1)
        self.assertTrue(worker.failed)

    async def test_handshake_signs_after_connection_creation_and_on_each_reconnect(self):
        from websockets.asyncio.client import ClientConnection
        from tests.test_current_native import Socket
        from tests.test_kalshi import market
        from unittest.mock import Mock
        service=SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True,
            deadline=asyncio.get_running_loop().time()+100,
            source_state=lambda *a:None,issue=lambda *a:None,observation=lambda *a:None)
        worker=NativeWorker(service,'kalshi')
        credential=Credential();credential.headers=Mock(side_effect=[{'test':'first'},{'test':'second'}])
        worker.credential=credential
        worker.client=SimpleNamespace(budget=PredictionBudgetForTest())
        worker.queue_book=lambda book:None
        connections=0
        class Connector:
            def __init__(connector,*a,**kwargs):connector.factory=kwargs['create_connection']
            def __await__(connector):
                async def open_connection():
                    nonlocal connections
                    # No credentials were prepared while waiting for TCP/TLS.
                    self.assertEqual(credential.headers.call_count,connections)
                    connection=object.__new__(connector.factory)
                    await connection.handshake()
                    connections+=1
                    if connections==2:worker.closed=True
                    return Socket('kalshi',connections)
                return open_connection().__await__()
        with patch('app.collection.current_native.connect',Connector),patch.object(ClientConnection,'handshake',new_callable=AsyncMock) as handshake:
            task=asyncio.create_task(worker.stream([market()]))
            # Fixture's first complete image followed by a gap requires reconnect.
            for _ in range(50):
                if connections>=2:break
                await asyncio.sleep(.1)
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        self.assertEqual(connections,2)
        self.assertEqual([c.args[0] for c in handshake.await_args_list],[{'test':'first'},{'test':'second'}])
        self.assertEqual(worker.metrics['last_handshake']['result'],'connected')


class PredictionBudgetForTest:
    requests=0
    bytes=0
    def charge_bytes(self,n):self.bytes+=n


class AggregateConnections(unittest.IsolatedAsyncioTestCase):
    async def test_each_paid_operation_uses_fresh_connection_without_hidden_retry(self):
        from aiohttp import web
        from app.collection.current_aggregate import CurrentOddsTransport
        peers=[]
        async def handler(request):
            peers.append(request.transport.get_extra_info('peername'))
            return web.json_response([],headers={'x-requests-used':'0','x-requests-remaining':'100000','x-requests-last':'0'})
        app=web.Application();app.router.add_get('/v4/sports',handler)
        runner=web.AppRunner(app);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        transport=CurrentOddsTransport()
        try:
            with patch('app.collection.current_aggregate.BASE',f'http://127.0.0.1:{port}'):
                for _ in range(2):
                    response=await transport.request({'path':'/v4/sports','params':{}},'CONTROLLED-test-key')
                    self.assertEqual(response['status'],200)
            self.assertEqual(len(peers),2)
            self.assertNotEqual(peers[0],peers[1])
        finally:
            await transport.close();await runner.cleanup()
