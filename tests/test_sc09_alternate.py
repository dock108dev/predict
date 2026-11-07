"""Exact complete alternate plans and durable budget checks, no provider I/O."""
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch
from app.collection.alternate_plan import plan
from app.collection.alternate_acquisition import authority, validate_request, event_request, prioritize
from app.collection.current_quota import QuotaStop
from tests import test_current_quota as quota_tests
WINDOW=quota_tests.WINDOW

GRANT=dict(schema='predict-alternate-authority-1',enabled=True,credits_per_cycle=232,credits_per_day=12992,
    interval_seconds=900,approved_at='2026-10-03T00:00:00+00:00',expires_at='2026-11-01T00:00:00+00:00')


class AlternatePlan(TestCase):
    def test_full_plan_no_sampling_and_exact_cost(self):
        p=plan({'NFL':[dict(id=str(i)) for i in range(107)]})
        self.assertEqual((p['event_requests'],p['total_maximum_credits_per_cycle'],p['total_maximum_credits_per_operating_day']),(107,232,12992))
        for r in p['requests']:validate_request(dict(path=r['path'],params=r['params']),2)
        self.assertEqual(plan({'NFL':[dict(id=str(i)) for i in range(108)]})['total_maximum_credits_per_cycle'],234)
        with self.assertRaises(QuotaStop):validate_request(event_request('NFL'),2)

    def test_least_recent_receipts_prevent_deferred_event_starvation(self):
        requests=plan({'NFL':[{'id':'a'},{'id':'b'}],'NCAAF':[{'id':'c'},{'id':'d'}]})['requests']
        ordered=prioritize(requests,{('NFL','a'):10,('NCAAF','c'):20})
        self.assertEqual([r['event_id'] for r in ordered],['b','d','a','c'])
        self.assertEqual({r['path'] for r in ordered},{r['path'] for r in requests})

    def test_authority_expires_and_cannot_inflate(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'authority.json';p.write_text(json.dumps(GRANT))
            with patch('app.collection.alternate_acquisition.AUTHORITY_PATH',p):
                self.assertIsNotNone(authority('2026-10-31T23:59:59+00:00'))
                self.assertIsNone(authority('2026-11-01T00:00:00+00:00'))
                p.write_text(json.dumps(dict(GRANT,credits_per_cycle=236,credits_per_day=13216)))
                self.assertEqual(authority('2026-10-31T23:59:59+00:00')['credits_per_cycle'],236)
                p.write_text(json.dumps(dict(GRANT,credits_per_cycle=234)))
                with self.assertRaises(QuotaStop):authority('2026-10-31T23:59:59+00:00')


class AlternateLedger(TestCase):
    setUp=quota_tests.DurableQuota.setUp
    tearDown=quota_tests.DurableQuota.tearDown
    bootstrap=quota_tests.DurableQuota.bootstrap

    def test_exact_scope_duplicate_and_cycle_budget(self):
        self.at='2026-10-03T14:00:00+00:00';self.q.bind_window(WINDOW);self.bootstrap()
        with patch('app.collection.alternate_acquisition.authority',return_value=GRANT):
            cid=self.q.begin_cycle(self.owner,[])
            requests=[dict(path=r['path'],params=r['params']) for r in plan({'NFL':[dict(id=str(i)) for i in range(117)]})['requests']]
            with self.assertRaisesRegex(QuotaStop,'budget_exceeded'):self.q.extend_cycle(self.owner,cid,requests,2)
            self.q.extend_cycle(self.owner,cid,requests[:1],2)
            aid=self.q.reserve(self.owner,'candidate',requests[0],2,cycle_id=cid)
            self.assertEqual(self.q._read()['attempts'][aid]['cost'],2)
            self.q.dispatched(aid,self.owner)
            self.q.reconcile(aid,quota_tests.quota(22,2))
            with self.assertRaisesRegex(QuotaStop,'duplicate'):self.q.extend_cycle(self.owner,cid,requests[:1],2)
            with self.assertRaisesRegex(QuotaStop,'duplicate'):self.q.reserve(self.owner,'candidate',requests[1],2,cycle_id=cid)

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock
from app.collection.alternate_acquisition import acquire


class CompleteRoute(IsolatedAsyncioTestCase):
    def setUp(self):
        self.now='2026-10-31T20:00:00+00:00'
        clock=patch('app.collection.current_quota.now',side_effect=lambda:self.now)
        clock.start();self.addCleanup(clock.stop)
        priority=patch('app.collection.alternate_acquisition.priority_requests',side_effect=lambda requests,sports:requests)
        priority.start();self.addCleanup(priority.stop)

    async def test_over_budget_census_keeps_featured_and_sends_no_alternate_subset(self):
        scheduler=SimpleNamespace(service=SimpleNamespace(ownership=object()),cycle_id='cycle',metrics={},quota_due=lambda:'2026-10-31T20:15:00+00:00',ledger=Mock())
        scheduler.dispatch=AsyncMock(return_value=dict(parsed_frame=SimpleNamespace(payload=[dict(id=str(i),commence_time='2026-10-31T23:00:00Z') for i in range(108)])))
        with patch('app.collection.alternate_acquisition.authority',return_value=GRANT),patch('app.collection.alternate_acquisition.save_event_census'):
            await acquire(scheduler,['NFL'])
        self.assertEqual(scheduler.dispatch.await_count,1)
        self.assertEqual(scheduler.metrics['alternate_state'],'blocked_full_census_exceeds_authorized_cycle')
        self.assertEqual(scheduler.metrics['alternate_plan']['authorized_cycle'],232)
        self.assertEqual(scheduler.metrics['alternate_plan']['authorized_day'],12992)
        self.assertEqual(scheduler.ledger.extend_cycle.call_count,1)

    async def test_complete_census_exact_event_route_and_original_response_retained(self):
        census=dict(parsed_frame=SimpleNamespace(payload=[dict(id='abc',commence_time='2026-10-31T23:00:00Z')]))
        response=dict(body=b'original')
        scheduler=SimpleNamespace(service=SimpleNamespace(ownership=object()),cycle_id='cycle',metrics={},quota_due=lambda:'2026-10-31T20:15:00+00:00',ledger=Mock(),permitted=Mock())
        scheduler.dispatch=AsyncMock(side_effect=[census,response])
        with patch('app.collection.alternate_acquisition.authority',return_value=GRANT),patch('app.collection.alternate_acquisition.save_response') as saved,patch('app.collection.alternate_acquisition.save_event_census'):
            await acquire(scheduler,['NFL'])
        self.assertEqual(scheduler.metrics['alternate_completed'],1)
        self.assertEqual(scheduler.dispatch.await_args.args[1],2)
        saved.assert_called_once_with('NFL','abc',response,'cycle')

    async def test_deadline_defers_before_census_without_dispatch_or_reservation(self):
        self.now='2026-10-31T20:14:00+00:00'
        scheduler=SimpleNamespace(metrics={},quota_due=lambda:'2026-10-31T20:15:00+00:00',dispatch=AsyncMock(),ledger=Mock())
        with patch('app.collection.alternate_acquisition.authority',return_value=GRANT):
            await acquire(scheduler,['NFL'])
        scheduler.dispatch.assert_not_awaited();scheduler.ledger.extend_cycle.assert_not_called()
        self.assertEqual(scheduler.metrics['alternate_state'],'deferred_for_scheduled_refresh')
        self.assertIsNone(scheduler.metrics['alternate_deferred'])
        self.assertEqual(scheduler.next_check_at,'2026-10-31T20:15:00+00:00')

    async def test_paid_response_finishes_and_is_saved_before_deferring_remaining_events(self):
        census=dict(parsed_frame=SimpleNamespace(payload=[dict(id=i,commence_time='2026-10-31T23:00:00Z') for i in ['a','b']]))
        response=dict(body=b'exact paid response')
        scheduler=SimpleNamespace(service=SimpleNamespace(ownership=object()),cycle_id='cycle',metrics={},
            quota_due=lambda:'2026-10-31T20:15:00+00:00',ledger=Mock(),permitted=Mock())
        async def dispatch(request,cost):
            if cost==0:return census
            self.now='2026-10-31T20:14:01+00:00'
            return response
        scheduler.dispatch=AsyncMock(side_effect=dispatch)
        with patch('app.collection.alternate_acquisition.authority',return_value=GRANT),patch('app.collection.alternate_acquisition.save_response') as saved,patch('app.collection.alternate_acquisition.save_event_census'):
            await acquire(scheduler,['NFL'])
        self.assertEqual(scheduler.dispatch.await_count,2)
        saved.assert_called_once_with('NFL','a',response,'cycle')
        self.assertEqual(scheduler.metrics['alternate_completed'],1)
        self.assertEqual(scheduler.metrics['alternate_deferred'],1)
        self.assertEqual(scheduler.metrics['alternate_state'],'deferred_for_scheduled_refresh')
        # The exact full request manifest remains budgeted; only dispatch stops.
        self.assertEqual(len(scheduler.ledger.extend_cycle.call_args.args[2]),2)


class ExpandedTransport(IsolatedAsyncioTestCase):
    from tests.test_current_aggregate import SchedulerTests as _Fixture
    asyncSetUp=_Fixture.asyncSetUp
    async def asyncTearDown(self):
        self.service.database_mode=False
        await self._Fixture.asyncTearDown(self)

    async def test_final_request_beyond_old_120_cap_and_expanded_envelope_stop(self):
        self.q.bind_window(self.window)
        aid=self.q.reserve(self.service.ownership,'candidate',dict(path='/v4/sports',params={}),0,bootstrap=True)
        self.q.dispatched(aid,self.service.ownership)
        self.q.reconcile(aid,quota_tests.quota(20,0))
        grant=dict(GRANT,credits_per_cycle=300,credits_per_day=16800)
        self.service.database_mode=True
        self.wire.headers=quota_tests.quota(22,2)
        with patch('app.collection.alternate_acquisition.authority',return_value=grant):
            self.scheduler.cycle_id=self.q.begin_cycle(self.service.ownership,[])
            r=plan({'NFL':[dict(id='last')]})['requests'][0]
            request=dict(path=r['path'],params=r['params'])
            self.q.extend_cycle(self.service.ownership,self.scheduler.cycle_id,[request],2)
            # Six featured, six free census, and 140 preceding event requests.
            self.scheduler.cycle_requests=152;self.scheduler.cycle_credits=298
            await self.scheduler.dispatch(request,2)
            self.assertEqual(self.scheduler.cycle_requests,153)
            self.assertEqual(len(self.wire.calls),1)
            with self.assertRaisesRegex(QuotaStop,'aggregate_runtime_envelope_consumed'):
                await self.scheduler.dispatch(event_request('NFL'),0)
            self.assertEqual(len(self.wire.calls),1)


def test_alternate_plan_interleaves_leagues_without_omitting_events_or_changing_cost():
    events={'NFL':[{'id':str(i)} for i in range(60)],'NCAAB':[{'id':'college'}],'NHL':[{'id':'hockey'}]}
    value=plan(events)
    assert [(r['sport'],r['event_id']) for r in value['requests'][:3]]==[('NFL','0'),('NCAAB','college'),('NHL','hockey')]
    assert {(r['sport'],r['event_id']) for r in value['requests']}=={(sport,e['id']) for sport,rows in events.items() for e in rows}
    assert value['total_maximum_credits_per_cycle']==142


def test_explicit_renewal_supersedes_cutoff_without_changing_budget_guards(tmp_path):
    from app.collection.alternate_acquisition import check_expiry
    import pytest
    p=tmp_path/'renewal.json'
    renewal=dict(GRANT,schema='predict-alternate-authority-2',expires_at=None,credits_per_cycle=300,credits_per_day=16800)
    p.write_text(json.dumps(renewal))
    with patch('app.collection.alternate_acquisition.AUTHORITY_PATH',p):
        check_expiry('2026-11-01T01:00:00+00:00')
        assert authority('2026-11-01T01:00:00+00:00')['credits_per_day']==16800
        p.write_text(json.dumps(dict(renewal,credits_per_cycle=302,credits_per_day=16912)))
        with pytest.raises(QuotaStop):authority('2026-11-01T01:00:00+00:00')
