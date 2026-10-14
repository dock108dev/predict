"""Ordinary-window controls; synthetic HTTP only, no credentials or providers."""
import asyncio,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
from unittest.mock import AsyncMock,patch
from app.collection.current_native import NativeWorker
from app.collection.current_policy import DEFAULT
from app.collection.prediction_producer import MockREST,PredictionBudget
from app.collection.native_payload import TRANSPORT_CONTRACT
from app.collection.current_journal import CurrentJournal
from app.collection.odds_http import BudgetStop
from tests.test_native_http_reader import server,fixed,PATH

class Lifecycle(unittest.IsolatedAsyncioTestCase):
    def worker(self):
        return NativeWorker(SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True,deadline=float('inf'),
            issue=lambda *a:None,source_state=lambda *a:None,observation=lambda *a:None),'kalshi')

    async def test_http_passes_reach_finite_cap_without_resetting_hour_or_lifetime(self):
        body=b'{"event":{},"padding":"'+b'x'*(400*1024)+b'"}'
        async def deliver(writer):writer.write(fixed(body));await writer.drain()
        async with server(deliver) as (endpoint,requests):
            limits=dict(session_bytes=2*1024*1024,discovery_requests=100,dollars_per_discovery_request='0',dollar_cap_per_source='0')
            worker=self.worker();client=MockREST(endpoint,limits,lambda r:None,2,PredictionBudget(limits))
            worker.client=client
            client.transport_policy=dict(TRANSPORT_CONTRACT,discovery_wire_bytes=800*1024,discovery_decoded_bytes=800*1024)
            try:
                worker.begin_discovery()
                await client.get(endpoint+PATH)
                with self.assertRaises(BudgetStop):await client.get(endpoint+PATH)
                spent=client.budget.bytes;count=client.budget.requests
                worker.begin_discovery()
                self.assertEqual(client.budget.bytes,spent);self.assertEqual(client.budget.requests,count)
                await client.get(endpoint+PATH)
                self.assertGreater(client.budget.bytes,spent)
                self.assertGreater(worker.http_totals['wire']+client.http_wire_bytes,800*1024)
                # A new pass cannot defeat the shared hourly cap.
                client.budget.bytes=limits['session_bytes'];worker.begin_discovery()
                with self.assertRaisesRegex(BudgetStop,'prediction_session_byte_cap'):await client.get(endpoint+PATH)
            finally:await client.aclose()

    async def test_discovery_cap_waits_for_due_pass_and_stop_cancels(self):
        worker=self.worker();client=SimpleNamespace(budget=SimpleNamespace(requests=2,bytes=17),aclose=AsyncMock())
        calls=[];waiting=asyncio.Event()
        async def discover():
            calls.append(1)
            worker.receipt(dict(path='/test',params={},status=200,complete=False,usable_metadata=False,body_sha256='0'*64,delivery_reason='native_discovery_wire_byte_cap'))
            raise BudgetStop('native_discovery_wire_byte_cap')
        async def sleep(seconds):
            self.assertEqual(seconds,DEFAULT['rediscovery_seconds']);waiting.set();await asyncio.Event().wait()
        with patch('app.collection.current_native.load_credentials',return_value={'kalshi':object()}),patch('app.collection.current_native.REST',return_value=client),patch('app.collection.current_native.native_payload.configure_transport'),patch.object(worker,'discover',side_effect=discover),patch('app.collection.current_native.asyncio.sleep',side_effect=sleep):
            task=asyncio.create_task(worker.run());await waiting.wait()
            self.assertFalse(worker.failed);self.assertEqual(len(calls),1)
            worker.service.dispatch=False;task.cancel();await asyncio.gather(task,return_exceptions=True)
            self.assertEqual(len(calls),1);client.aclose.assert_awaited_once()

    async def test_hour_renewal_waits_for_http_refund_and_stop_prevents_reset(self):
        worker=self.worker();worker.client=SimpleNamespace(budget=SimpleNamespace(requests=100,bytes=999))
        worker.metrics['connections']=21;worker.budget_started-=3601;worker.http_active=True
        worker.guard();self.assertEqual(worker.client.budget.bytes,999)
        worker.http_active=False;worker.guard()
        self.assertEqual(worker.client.budget.bytes,0);self.assertEqual(worker.budget_totals['bytes'],999)
        self.assertEqual(worker.metrics['connections'],21);self.assertEqual(worker.metrics['budget_window']['connections'],0)
        worker.budget_started-=3601;worker.client.budget.bytes=100;worker.closed=True
        with self.assertRaises(asyncio.CancelledError):worker.guard()
        self.assertEqual(worker.client.budget.bytes,100)

class Retention(unittest.TestCase):
    def test_retention_is_explicit_and_isolated(self):
        from app.collection.current_service import CurrentService
        with tempfile.TemporaryDirectory() as root:
            service=CurrentService(config=dict(DEFAULT,aggregate_enabled=False),directory=Path(root)/'state')
            self.assertIsNone(service.journal)
            service.retain('kalshi','controlled',{})
            self.assertEqual(list(Path(root).iterdir()),[])
            service=CurrentService(config=dict(DEFAULT,aggregate_enabled=False),directory=Path(root)/'state',observation_directory=Path(root)/'observations')
            service.dispatch=True
            service.retain('kalshi','controlled',{'received_at':'2026-10-13T00:00:00Z'})
            self.assertEqual(service.journal.records,1)
            before=service.journal.path.read_bytes();service.closed=True
            with self.assertRaises(asyncio.CancelledError):service.retain('kalshi','controlled',{})
            self.assertEqual(service.journal.path.read_bytes(),before)
    def test_reopen_preserves_clocks_and_full_storage_never_overwrites(self):
        with tempfile.TemporaryDirectory() as root:
            journal=CurrentJournal(root,byte_cap=400)
            record=dict(kind='admitted_books',value=dict(source_at='2026-10-13T00:00:00Z',received_at='2026-10-13T00:00:01Z',price='.48'))
            journal.append(record);before=journal.path.read_bytes()
            CurrentJournal(root,byte_cap=400).append(record)
            self.assertEqual(json.loads(journal.path.read_bytes().splitlines()[0]),record)
            with self.assertRaisesRegex(BudgetStop,'current_observation_storage_cap'):CurrentJournal(root,byte_cap=len(before)*2).append(record)
            self.assertEqual(journal.path.read_bytes(),before*2)
            with journal.path.open('ab') as stream:stream.write(b'{')
            with self.assertRaisesRegex(BudgetStop,'current_observation_incomplete_tail'):journal.append(record)

if __name__=='__main__':unittest.main()
