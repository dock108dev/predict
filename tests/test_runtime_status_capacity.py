"""Source status size must not terminate healthy broad acquisition."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from app.collection.current_policy import DEFAULT
from app.collection.runtime_status import RuntimeState,STATUS_BYTES


class DatabaseFailureStatus(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        from app.collection.current_database import DatabasePipeline
        sink=SimpleNamespace(error=None,error_details=None)
        service=SimpleNamespace(sink=sink,config=deepcopy(DEFAULT))
        return DatabasePipeline(service)

    async def test_three_maintenance_failures_do_not_permanently_kill_recovery(self):
        from psycopg.errors import LockNotAvailable
        pipeline=self.fixture();pipeline.wake.set();attempts=[]
        actual=pipeline.tick
        def tick():
            attempts.append(1)
            if len(attempts)<=3:
                pipeline.wake.set()
                raise LockNotAvailable('secret provider response must not escape')
            self.assertEqual(pipeline.status()['failure_owner'],'maintenance')
            self.assertEqual(pipeline.status()['maintenance_failure']['sqlstate'],'55P03')
            pipeline.closed=False
            actual()
            pipeline.closed=True
        with patch('app.collection.current_database.connect',return_value=MagicMock()), \
                patch('app.storage.current_rows.CurrentRowStore'), \
                patch('app.storage.storage_maintenance.maintain',return_value={'after_bytes':123}), \
                patch('app.collection.current_database.sql_usage',return_value=123), \
                patch.object(pipeline,'tick',side_effect=tick):
            await pipeline.run_maintenance()
        self.assertEqual(len(attempts),4)
        status=pipeline.status()
        self.assertEqual(status['state'],'available')
        self.assertIsNone(status['maintenance_failure'])
        self.assertEqual(status['maintenance_failures'],0)
        self.assertTrue(status['maintenance_last_success_at'])
        self.assertNotIn('secret',json.dumps(status))

    async def test_busy_is_not_recovery_and_ingress_failure_is_independent(self):
        pipeline=self.fixture();pipeline.error='LockNotAvailable'
        pipeline.error_details={'exception':'LockNotAvailable','frames':[],'sqlstate':'55P03'}
        with patch('app.collection.current_database.connect',return_value=MagicMock()), \
                patch('app.storage.current_rows.CurrentRowStore'), \
                patch('app.storage.storage_maintenance.maintain',return_value={'state':'busy'}), \
                patch('app.collection.current_database.sql_usage',return_value=123):
            pipeline.tick()
        self.assertEqual(pipeline.status()['state'],'unavailable')
        self.assertEqual(pipeline.status()['failure_owner'],'maintenance')
        pipeline.service.sink.error='OperationalError'
        pipeline.service.sink.error_details={'exception':'OperationalError','frames':[]}
        with patch('app.collection.current_database.connect',return_value=MagicMock()), \
                patch('app.storage.current_rows.CurrentRowStore'), \
                patch('app.storage.storage_maintenance.maintain',return_value={'after_bytes':123}), \
                patch('app.collection.current_database.sql_usage',return_value=123):
            pipeline.tick()
        self.assertIsNone(pipeline.error)
        self.assertEqual(pipeline.status()['state'],'unavailable')
        self.assertEqual(pipeline.status()['failure_owner'],'ingress')

    def test_safe_exception_evidence_has_bounded_frames_without_messages(self):
        from app.diagnostics import failure_details
        def nested(n):
            if n:return nested(n-1)
            raise ValueError('source-secret')
        try:nested(40)
        except ValueError as error:details=failure_details(error)
        self.assertEqual(len(details['frames']),16)
        self.assertNotIn('source-secret',json.dumps(details))


class RuntimeStatusCapacity(unittest.TestCase):
    def fixture(self):
        metrics={v:dict(requests=36,books=1000,
            native_identity_trace=[dict(market_id=f'CONTROLLED-{i}',proof='x'*500) for i in range(40)],
            identity_exclusions=[dict(market_id=f'CONTROLLED-{i}',reason='x'*300) for i in range(60)],
            coverage=[dict(sport='NFL',evidence='x'*900) for _ in range(10)])
            for v in ('kalshi','polymarket_us')}
        status=dict(metrics=metrics,sources=[dict(provider=v,metrics=deepcopy(m)) for v,m in metrics.items()],
            coverage=dict(cells=[dict(sport='NFL',evidence='x'*2000) for _ in range(30)]),
            issues=[dict(reason='x'*900) for _ in range(32)],
            quota=dict(reserved=9,unresolved_attempts=3,remaining=98555,
                       recovery_authority=[dict(id=f'CONTROLLED-audit-{i}',original='x'*6000) for i in range(3)]))
        service=SimpleNamespace(status=lambda:deepcopy(status),runtime_id='CONTROLLED-runtime',
            config=deepcopy(DEFAULT),states=dict(kalshi=dict(state='available',reason_code='native_image',
                source_at='2026-10-21T01:30:00Z',received_at='2026-10-21T01:30:01Z')),dispatch=True)
        return service,status

    def test_broad_diagnostics_fit_without_dropping_accounting_or_source_details(self):
        service,original=self.fixture()
        self.assertGreater(len(json.dumps(original,separators=(',',':')).encode()),256*1024)
        result=RuntimeState().snapshot(service,paused_sources={'the_odds_api'},global_stopped=True)
        projected=result['status']
        self.assertLessEqual(len(json.dumps(projected,separators=(',',':')).encode()),STATUS_BYTES)
        self.assertEqual(projected['sources'],original['sources'])
        self.assertEqual(projected['quota'],original['quota'])
        self.assertEqual(projected['coverage'],original['coverage'])
        self.assertEqual(projected['issues'],original['issues'])
        self.assertEqual(result['states'],service.states)
        self.assertEqual(result['paused_sources'],['the_odds_api'])
        self.assertTrue(result['global_stopped'])
        for provider,metrics in projected['metrics'].items():
            self.assertEqual(metrics['requests'],36)
            self.assertEqual(metrics['books'],1000)
            self.assertNotIn('native_identity_trace',metrics)

    def test_ninety_family_inventories_fit_with_original_accounting(self):
        service,original=self.fixture()
        original['coverage']['cells']=[dict(sport=s,venue=v,family_queries=[dict(family=f,
            latest=dict(inventory={'evidence':'x'*1800}),last_success=dict(inventory={'evidence':'x'*1800}))
            for f in ('moneyline','spread','total')])
            for s in ('NFL','NCAAF','NBA','NCAAB','MLB','NHL')
            for v in ('kalshi','polymarket_us','novig','prophetx','pinnacle')]
        result=RuntimeState().snapshot(service)
        self.assertEqual(result['status']['coverage'],original['coverage'])
        self.assertEqual(result['status']['quota'],original['quota'])

    def test_unmirrored_details_and_hard_capacity_guard_are_preserved(self):
        service,original=self.fixture()
        original['metrics']['kalshi']['unmirrored']=dict(reason='CONTROLLED-distinct')
        result=RuntimeState().snapshot(service)
        self.assertEqual(result['status']['metrics']['kalshi']['unmirrored'],original['metrics']['kalshi']['unmirrored'])
        original['unexpected_payload']='x'*STATUS_BYTES
        with self.assertRaisesRegex(ValueError,'data_runtime_status_capacity'):
            RuntimeState().snapshot(service)

    def test_full_coverage_and_accounting_fit_alongside_native_delivery_samples(self):
        service, original = self.fixture()
        original['coverage']['cells'][0]['evidence'] = 'c' * 380000
        original['quota']['recovery_authority'][0]['original'] = 'q' * 140000
        for panel in original['sources']:
            samples = [dict(market=i, timing='x' * 1600) for i in range(128)]
            panel['metrics']['delivery_trace'] = samples
            original['metrics'][panel['provider']]['delivery_trace'] = samples

        report = RuntimeState().snapshot(service)['status']
        self.assertEqual(report['quota'], original['quota'])
        self.assertEqual(report['coverage'], original['coverage'])
        for i, panel in enumerate(report['sources']):
            samples = original['sources'][i]['metrics']['delivery_trace']
            self.assertEqual(len(samples), 128)
            self.assertEqual(panel['metrics']['delivery_trace'], samples[-16:])
            self.assertEqual(report['status_retention']['delivery_samples'][panel['provider']],
                             dict(available=128, retained=16))
        self.assertLessEqual(len(json.dumps(report, separators=(',', ':')).encode()), STATUS_BYTES)

    def test_capacity_reduces_diagnostic_samples_without_changing_accounting_or_controls(self):
        service,original=self.fixture()
        original['coverage']['cells'][0]['evidence']='c'*700000
        original['exclusions']=[dict(example=i,detail='x'*1800) for i in range(100)]
        before=deepcopy(original)
        result=RuntimeState().snapshot(service,global_stopped=True,paused_sources=['kalshi'])
        report=result['status']
        self.assertLessEqual(len(json.dumps(report,separators=(',',':')).encode()),STATUS_BYTES)
        self.assertEqual(report['quota'],before['quota'])
        self.assertEqual(report['coverage'],before['coverage'])
        self.assertEqual(report['exclusions'],before['exclusions'][-20:])
        self.assertEqual(report['issues'],before['issues'][-16:])
        self.assertEqual(result['states'],service.states)
        self.assertTrue(result['global_stopped'])
        self.assertEqual(result['paused_sources'],['kalshi'])
        self.assertEqual(original,before)
        self.assertIn('capacity_compaction',report['status_retention'])

    def test_large_subscription_roster_is_a_counted_diagnostic_not_heartbeat_payload(self):
        from collections import Counter
        actions=[dict(action='create',market_id=str(i),owner_token='x'*64) for i in range(6000)]
        service,status=self.fixture()
        status['sources'][0]['metrics']['subscription_changes']=dict(actions=actions[:20],
            action_counts=dict(Counter(a['action'] for a in actions)),omitted_actions=len(actions)-20,
            complete_roster='current_acquisition_market')
        result=RuntimeState().snapshot(service)
        self.assertEqual(result['status']['sources'][0]['metrics']['subscription_changes']['action_counts'],dict(create=6000))
