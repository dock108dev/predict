"""Source status size must not terminate healthy broad acquisition."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from app.collection.current_policy import DEFAULT
from app.collection.runtime_status import RuntimeState,STATUS_BYTES


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
        self.assertGreater(len(json.dumps(original,separators=(',',':')).encode()),STATUS_BYTES)
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

    def test_unmirrored_details_and_hard_capacity_guard_are_preserved(self):
        service,original=self.fixture()
        original['metrics']['kalshi']['unmirrored']=dict(reason='CONTROLLED-distinct')
        result=RuntimeState().snapshot(service)
        self.assertEqual(result['status']['metrics']['kalshi']['unmirrored'],original['metrics']['kalshi']['unmirrored'])
        original['unexpected_payload']='x'*STATUS_BYTES
        with self.assertRaisesRegex(ValueError,'data_runtime_status_capacity'):
            RuntimeState().snapshot(service)
