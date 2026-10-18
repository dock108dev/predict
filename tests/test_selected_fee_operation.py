"""Finite HOU-JAC owner operation: disposable evidence, mocked transport, no sockets."""
import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from app.collection import selected_fee_operation as fee
from app.collection.current_native import NativeWorker
from app.collection.current_policy import DEFAULT
from app.collection.data_runtime import DataRuntime
from app.collection.prediction_producer import PredictionBudget
from app.dashboard.current_state import SelectionError


class Clock:
    def __init__(self):self.value=1000
    def timer(self):return self.value
    def utc(self):
        return (datetime(2026,10,17,13,tzinfo=timezone.utc)+timedelta(seconds=self.value-1000)).isoformat()


def payloads():
    return [dict(series=dict(ticker=fee.SERIES,fee_type='quadratic',fee_multiplier=1,
                contract_url='https://kalshi.com/contract.pdf')),
            dict(series_fee_change_arr=[]),dict(event_fee_changes=[],cursor='')]


class FakeREST(fee.FeeREST):
    """Exercise real reservation/receipt hooks without constructing a socket."""
    async def get(self,url,params=None):
        op=self.operation;op.test_clock.value+=2
        await self.pace()
        self.budget.reserve('discovery_request');self.requests+=1
        op.test_dispatched.set()
        if getattr(op,'test_block',False):await asyncio.Event().wait()
        index=op.index;raw=json.dumps(op.test_values[index]).encode()
        self.http_wire_bytes=getattr(self,'http_wire_bytes',0)+len(raw)+200
        self.http_decoded_bytes=getattr(self,'http_decoded_bytes',0)+len(raw)
        started=op.clock();op.test_clock.value+=.1
        status=getattr(op,'test_status',{}).get(index,200)
        row=dict(path=fee.ROUTES[index][0],params=params,status=status,
            started_at=started,received_at=op.clock(),complete=True,usable_metadata=status==200,
            delivery_reason=None if status==200 else 'http_status',body_b64=base64.b64encode(raw).decode(),
            body_sha256=sha256(raw).hexdigest(),resource_usage=dict(wire_bytes=len(raw)+200,decoded_bytes=len(raw)),
            response_headers=[['content-type','application/json'],['retry-after','60']],
            response_url=url,request_provenance=dict(configured_endpoint=self.endpoint,
                dispatched_url=url,method='GET',headers=[['Accept','application/json']],redirect_policy='refuse'),
            http_plaintext_sha256=sha256(raw).hexdigest())
        if getattr(op,'test_wire_oversize',False):row['resource_usage']['wire_bytes']=fee.CAP+1
        self.sink(row)
        if getattr(op,'test_after_response',None):op.test_after_response()
        return httpx.Response(status,content=raw)

    async def aclose(self):self.closed=True


class OperationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.clock=Clock()
        config=deepcopy(DEFAULT)
        self.service=SimpleNamespace(config=config,runtime_id='fixture-runtime',digest='fixture-candidate',
            workers={},dispatch=True,globally_stopped=False,deadline=time.monotonic()+1000,cleanup_errors=[])
        self.worker=NativeWorker(self.service,'kalshi');self.service.workers['kalshi']=self.worker
        limits=dict(discovery_requests=config['requests_per_source'],session_bytes=config['source_bytes'],
            frame_bytes=fee.CAP,dollars_per_discovery_request='0',dollars_per_connection='0',dollar_cap_per_source='0')
        self.worker.client=SimpleNamespace(budget=PredictionBudget(limits))
        self.runtime=SimpleNamespace(service=self.service,global_stopped=False,paused_sources=set(),
            stopping=asyncio.Event(),resource_guard=Mock(),connector=Mock())
        self.identity=Mock(return_value=dict(native_key=['kalshi',fee.EVENT,fee.MARKET,'yes','yes'],
            original_terms_sha256=fee.TERMS,scheduled_start=fee.START,sql_contract_id='fixture'))
        self.op=self.make_operation();self.binding=patch.object(fee,'candidate',return_value=('fixture-candidate',{}));self.candidate_mock=self.binding.start()
        self.sockets=patch('socket.socket.connect',side_effect=AssertionError('provider/socket traffic forbidden'));self.sockets.start()

    def make_operation(self):
        op=fee.SelectedFeeOperation(self.runtime,directory=Path(self.temp.name)/'operation',
            client_factory=FakeREST,identity=self.identity,clock=self.clock.utc,timer=self.clock.timer)
        op.test_clock=self.clock;op.test_values=payloads();op.test_dispatched=asyncio.Event()
        return op

    def body(self):
        return dict(scope=fee.SCOPE,authority=fee.AUTHORITY,runtime_id=self.service.runtime_id,candidate_digest=self.service.digest)

    async def execute(self):
        await self.op.start(self.body());await self.op.task
        return json.loads((self.op.directory/'result.json').read_text())

    async def asyncTearDown(self):
        if self.op.task and not self.op.task.done():await self.op.stop()
        self.sockets.stop();self.binding.stop();self.temp.cleanup()

    async def test_complete_charges_shared_limits_keeps_response_clocks_and_once_only(self):
        self.worker.metrics['connections']=7
        result=await self.execute()
        self.assertEqual(result['state'],'complete_evidence_only')
        self.assertEqual(result['requests_reserved'],3)
        self.assertEqual(self.worker.client.budget.requests,3)
        self.assertEqual(self.worker.supplemental_connections,3)
        self.assertEqual(self.worker.metrics['connections'],7)
        self.assertEqual(self.worker.connection_allowance_used(),10)
        self.assertEqual(self.worker.client.budget.bytes,result['observed_wire_bytes'])
        self.assertTrue(result['cleanup_confirmed']);self.assertTrue(self.op.client.closed)
        self.assertEqual(result['baseline_observed_at'],result['responses'][0]['received_at'])
        self.assertNotEqual(result['baseline_observed_at'],result['assembled_at'])
        self.assertEqual(result['context']['observed_at'],result['baseline_observed_at'])
        self.assertFalse(result['credentials_used']);self.assertFalse(result['model_applicability_granted'])
        self.assertEqual([r['params'] for r in result['responses']],[q for p,q in fee.ROUTES])
        self.assertTrue(all(datetime.fromisoformat(b['at'])-datetime.fromisoformat(a['at'])>=timedelta(seconds=1)
                            for a,b in zip(result['reservations'],result['reservations'][1:])))
        for response in result['responses']:
            self.assertEqual(sha256((self.op.directory/response['body_path']).read_bytes()).hexdigest(),response['body_sha256'])
            self.assertEqual(response['request_provenance']['redirect_policy'],'refuse')
            self.assertTrue(response['response_url'].startswith('https://external-api.kalshi.com/'))
        self.assertEqual((await self.op.start(self.body()))['operation_state'],'complete_evidence_only')
        restarted=self.make_operation();self.assertEqual((await restarted.start(self.body()))['operation_state'],'complete_evidence_only')
        self.assertIsNone(restarted.task);self.assertEqual(self.worker.client.budget.requests,3)

    async def test_identity_or_candidate_mismatch_does_not_consume(self):
        for error in ('identity','candidate','body'):
            with self.subTest(error=error):
                self.identity.side_effect=ValueError('selected_fee_identity_conflict') if error=='identity' else None
                with patch.object(fee,'candidate',return_value=('wrong' if error=='candidate' else 'fixture-candidate',{})):
                    body=self.body();body.update(extra=True) if error=='body' else None
                    with self.assertRaises(ValueError):await self.op.start(body)
                self.assertFalse((self.op.directory/'attempt.json').exists())
        self.assertEqual(self.worker.client.budget.requests,0)

    async def test_consumed_attempt_without_result_never_redispatches(self):
        self.op.directory.mkdir();(self.op.directory/'attempt.json').write_text('{}')
        result=await self.op.start(self.body())
        self.assertEqual(result['operation_state'],'consumed_result_unknown');self.assertIsNone(self.op.task)

    async def test_restart_with_running_receipt_reports_interrupted_and_preserves_evidence(self):
        self.op.directory.mkdir();(self.op.directory/'attempt.json').write_text('{}')
        path=self.op.directory/'result.json';path.write_text(json.dumps(dict(state='running',consumed=True)))
        original=path.read_bytes();result=await self.op.start(self.body())
        self.assertEqual(result['operation_state'],'consumed_interrupted_unknown')
        self.assertEqual(path.read_bytes(),original);self.assertIsNone(self.op.task)
        self.assertEqual(self.worker.client.budget.requests,0)

    async def test_large_valid_history_retains_raw_and_terminal_capacity_refusal(self):
        base=datetime(2026,10,1,tzinfo=timezone.utc)
        self.op.test_values[1]['series_fee_change_arr']=[dict(series_ticker=fee.SERIES,
            scheduled_ts=(base+timedelta(seconds=n)).isoformat(),fee_type='quadratic',fee_multiplier=1) for n in range(700)]
        result=await self.execute()
        self.assertEqual(result['state'],'unbound');self.assertEqual(result['reason'],'selected_fee_receipt_capacity')
        self.assertEqual(len(result['responses']),3);self.assertTrue(result['cleanup_confirmed'])
        self.assertIsNone(result['context']);self.assertTrue((self.op.directory/'response-2.body').is_file())

    async def test_full_source_allowance_reserved_before_any_dispatch(self):
        for kind in ('requests','connections','bytes','dollars'):
            with self.subTest(kind=kind):
                self.op=self.make_operation();self.op.directory=Path(self.temp.name)/kind
                self.worker.client.budget.requests=0;self.worker.client.budget.bytes=0;self.worker.supplemental_connections=0
                self.worker.client.budget.limits['dollar_cap_per_source']='0'
                if kind=='requests':self.worker.client.budget.requests=self.worker.config['requests_per_source']-2
                if kind=='connections':self.worker.supplemental_connections=self.worker.config['connections_per_source']-2
                if kind=='bytes':self.worker.client.budget.bytes=self.worker.client.budget.limits['session_bytes']-fee.TOTAL+1
                if kind=='dollars':self.worker.client.budget.limits['dollar_cap_per_source']='1'
                result=await self.execute()
                self.assertEqual(result['state'],'unbound');self.assertEqual(result['requests_reserved'],0)
                self.assertTrue(result['cleanup_confirmed']);self.assertIsNone(self.op.client)

    async def test_stop_before_coroutine_starts_is_confirmed_without_requests(self):
        await self.op.start(self.body())
        self.assertTrue(await self.op.stop())
        self.assertEqual(self.op.record['state'],'stopped');self.assertEqual(self.op.record['requests_reserved'],0)

    async def test_stop_while_waiting_source_lock_has_no_reservation(self):
        await self.worker.http_lock.acquire()
        try:
            await self.op.start(self.body());await asyncio.sleep(0)
            self.assertTrue(await self.op.stop())
            self.assertEqual(self.op.record['requests_reserved'],0)
            self.assertFalse(self.service.cleanup_errors);self.assertEqual(self.worker.client.budget.bytes,0)
        finally:self.worker.http_lock.release()

    async def test_stop_inflight_closes_transport_no_stale_success_and_no_resume(self):
        self.op.test_block=True;await self.op.start(self.body());await self.op.test_dispatched.wait()
        self.runtime.global_stopped=True
        self.assertTrue(await self.op.stop())
        self.assertTrue(self.op.client.closed);self.assertEqual(self.op.record['state'],'stopped')
        self.assertIsNone(self.op.record['context']);self.assertEqual(self.worker.client.budget.requests,1)
        self.runtime.global_stopped=False
        self.assertEqual((await self.op.start(self.body()))['operation_state'],'stopped')
        self.assertEqual(self.worker.client.budget.requests,1)

    async def test_request_and_queued_absolute_deadlines_are_terminal(self):
        self.op.test_block=True
        with patch.object(fee,'REQUEST_SECONDS',.01):result=await self.execute()
        self.assertEqual(result['reason'],'selected_fee_timeout');self.assertTrue(result['cleanup_confirmed'])
        self.op=self.make_operation();self.op.directory=Path(self.temp.name)/'deadline'
        await self.worker.http_lock.acquire()
        try:
            with patch.object(fee,'DEADLINE_SECONDS',.01):result=await self.execute()
            self.assertEqual(result['requests_reserved'],0);self.assertEqual(result['reason'],'selected_fee_timeout')
        finally:self.worker.http_lock.release()

    async def test_http_errors_do_not_retry_and_429_updates_existing_backoff(self):
        for status in (302,401,429):
            with self.subTest(status=status):
                self.op=self.make_operation();self.op.directory=Path(self.temp.name)/str(status)
                self.op.test_status={0:status};self.worker.backoff_until=0
                before=self.worker.client.budget.requests;result=await self.execute()
                self.assertEqual(result['state'],'unbound');self.assertEqual(len(result['responses']),1)
                self.assertEqual(self.worker.client.budget.requests-before,1)
                if status==429:self.assertGreater(self.worker.backoff_until,time.monotonic())

    async def test_nonempty_cursor_wrong_identity_and_interval_change_fail_closed(self):
        for kind in ('cursor','identity','interval'):
            with self.subTest(kind=kind):
                self.op=self.make_operation();self.op.directory=Path(self.temp.name)/kind
                if kind=='cursor':self.op.test_values[2]['cursor']='more'
                if kind=='identity':self.op.test_values[0]['series']['ticker']='other'
                if kind=='interval':self.op.test_values[1]['series_fee_change_arr']=[dict(series_ticker=fee.SERIES,
                    scheduled_ts=self.clock.utc(),fee_type='quadratic',fee_multiplier=2)]
                if kind=='interval':self.op.test_values[1]['series_fee_change_arr'][0]['scheduled_ts']=(
                    datetime.fromisoformat(self.clock.utc())+timedelta(seconds=3)).isoformat()
                result=await self.execute()
                self.assertEqual(result['state'],'unbound');self.assertIsNone(result['context'])
                if kind=='interval':self.assertEqual(result['reason'],'selected_fee_change_crossed_read_interval')

    async def test_rejected_wire_over_cap_never_produces_context(self):
        self.op.test_wire_oversize=True;result=await self.execute()
        self.assertEqual(result['state'],'unbound');self.assertEqual(result['reason'],'selected_fee_response_cap')
        self.assertIsNone(result['context'])

    async def test_null_event_overrides_remain_explicit(self):
        self.op.test_values[2]['event_fee_changes']=[dict(series_ticker=fee.SERIES,event_ticker=fee.EVENT,
            scheduled_ts='2026-10-17T12:00:00+00:00',fee_type_override=None,fee_multiplier_override=None)]
        result=await self.execute()
        self.assertEqual(result['state'],'complete_evidence_only')
        self.assertIsNone(result['context']['event_changes'][0]['fee_multiplier_override'])

    async def test_candidate_or_selected_identity_change_during_response_cannot_succeed(self):
        for kind in ('identity','candidate'):
            with self.subTest(kind=kind):
                self.op=self.make_operation();self.op.directory=Path(self.temp.name)/kind
                self.identity.side_effect=None;self.candidate_mock.return_value=('fixture-candidate',{})
                def change():
                    if kind=='identity':self.identity.side_effect=ValueError('selected_fee_identity_conflict')
                    else:self.candidate_mock.return_value=('changed-candidate',{})
                self.op.test_after_response=change
                result=await self.execute()
                self.assertEqual(result['state'],'unbound');self.assertIsNone(result['context'])
                self.assertEqual(result['requests_reserved'],1)

    async def test_native_guard_immediately_observes_stop_and_source_pause(self):
        for field in ('globally_stopped','paused_sources'):
            with self.subTest(field=field):
                self.service.globally_stopped=field=='globally_stopped'
                self.service.paused_sources={'kalshi'} if field=='paused_sources' else set()
                with self.assertRaises(asyncio.CancelledError):self.worker.guard()

    async def test_cleanup_failure_keeps_reservation_and_revokes_source(self):
        class BadClose(FakeREST):
            async def aclose(self):raise OSError('fixture')
        self.op.client_factory=BadClose
        result=await self.execute()
        self.assertFalse(result['cleanup_confirmed']);self.assertTrue(self.worker.failed)
        self.assertEqual(self.worker.client.budget.bytes,fee.TOTAL)
        self.assertEqual(result['reason'],'selected_fee_cleanup_unresolved')
        self.assertIn('selected_fee_cleanup_unresolved',self.service.cleanup_errors)

    async def test_stop_during_transport_close_finishes_close_and_withdraws_success(self):
        entered=asyncio.Event()
        class SlowClose(FakeREST):
            async def aclose(self):
                entered.set();await asyncio.sleep(.02);self.closed=True
        self.op.client_factory=SlowClose
        await self.op.start(self.body());await entered.wait()
        self.assertTrue(await self.op.stop())
        self.assertTrue(self.op.client.closed);self.assertIsNone(self.op.record['context'])
        self.assertEqual(self.op.record['state'],'stopped')

    def test_fixed_transport_cap_includes_ingress_lookahead(self):
        client=fee.FeeREST(self.op)
        self.assertEqual(client.transport_policy['response_wire_bytes']+client.transport_policy['ingress_callback_bytes'],fee.CAP)
        self.assertEqual(client.transport_policy['response_decoded_bytes'],fee.CAP)
        self.assertEqual(client.transport_policy['discovery_wire_bytes'],fee.TOTAL)
        self.assertEqual((fee.REQUEST_SECONDS,fee.DEADLINE_SECONDS,fee.SPACING_SECONDS),(10,45,1))
        self.assertIsNone(client.credential)


class StopOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_finite_cleanup_does_not_delay_ordinary_revocation(self):
        for action in ('stop','pause'):
            with self.subTest(action=action):
                revoked=asyncio.Event();finish=asyncio.Event();worker=SimpleNamespace(closed=False)
                service=SimpleNamespace(workers={'kalshi':worker},dispatch=True,globally_stopped=False,
                    paused_sources=set(),cleanup_errors=[],source_state=Mock())
                async def ordinary(*args):
                    worker.closed=True
                    if action=='stop':service.dispatch=False
                    revoked.set()
                async def finite():await finish.wait();return True
                service.close=ordinary;service.pause=ordinary
                runtime=DataRuntime(service=service);runtime.persist=Mock()
                runtime.selected_fees=SimpleNamespace(stop=finite)
                task=asyncio.create_task(runtime.control(action,{} if action=='stop' else dict(source='kalshi')))
                await asyncio.wait_for(revoked.wait(),.1)
                self.assertTrue(worker.closed);self.assertFalse(task.done())
                if action=='stop':self.assertFalse(service.dispatch)
                finish.set();await task

    async def test_command_ack_fails_after_ordinary_revocation_on_finite_failure(self):
        worker=SimpleNamespace(closed=False)
        service=SimpleNamespace(runtime_id='fixture-runtime',workers={'kalshi':worker},dispatch=True,
            globally_stopped=False,cleanup_errors=[])
        async def close():service.dispatch=False;worker.closed=True
        service.close=close;runtime=DataRuntime(service=service);runtime.persist=Mock()
        runtime.selected_fees=SimpleNamespace(stop=AsyncMock(return_value=False))
        runtime.state=Mock()
        runtime.state.pending.return_value=[dict(id='fixture-command',runtime_id='fixture-runtime',action='stop',body={})]
        runtime.state.acknowledge.side_effect=lambda *args,**kwargs:runtime.stopping.set()
        await runtime.commands()
        self.assertFalse(service.dispatch);self.assertTrue(worker.closed)
        args,kwargs=runtime.state.acknowledge.call_args
        self.assertTrue(kwargs['failed']);self.assertEqual(args[1]['error'],'cleanup_safety_unresolved')

    async def test_supplemental_failure_always_revokes_ordinary_owner_and_fails_ack(self):
        for action in ('stop','pause'):
            for raises in (False,True):
                with self.subTest(action=action,raises=raises):
                    worker=SimpleNamespace(closed=False)
                    service=SimpleNamespace(workers={'kalshi':worker},dispatch=True,globally_stopped=False,
                        paused_sources=set(),cleanup_errors=[],source_state=Mock())
                    async def close():service.dispatch=False;worker.closed=True
                    async def pause(venue):worker.closed=True
                    service.close=AsyncMock(side_effect=close);service.pause=AsyncMock(side_effect=pause)
                    runtime=DataRuntime(service=service);runtime.persist=Mock()
                    runtime.selected_fees=SimpleNamespace(stop=AsyncMock(side_effect=RuntimeError('fixture') if raises else None,return_value=False))
                    with self.assertRaises(SelectionError) as exc:
                        await runtime.control(action,{} if action=='stop' else dict(source='kalshi'))
                    self.assertEqual(exc.exception.body['error'],'cleanup_safety_unresolved')
                    self.assertTrue(worker.closed)
                    if action=='stop':
                        self.assertFalse(service.dispatch);service.close.assert_awaited_once()
                    else:service.pause.assert_awaited_once_with('kalshi')


if __name__=='__main__':unittest.main()
