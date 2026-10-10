"""Ordinary admission/store integration with authored prices; no acquisitions."""
from copy import deepcopy
from fractions import Fraction
import json
import unittest
from unittest.mock import patch

from app.collection.current_policy import DEFAULT
from app.collection.current_service import CurrentService
from app.collection.current_sink import LatestStateSink
from app.dashboard.current_state import CurrentStore, CurrentStateProvider
from app.dashboard.current_contract import quotes_of, validate_snapshot
from tests.test_current_aggregate import body
from tests.test_comparison_net_costs import setup_case
from app.comparison.net_costs import calculate_net_costs

AT='2026-10-09T12:00:00+00:00'


class OrdinaryIntegration(unittest.TestCase):
    def test_sink_attaches_partial_profiles_preserves_gross_and_originals(self):
        service=CurrentService(config=dict(DEFAULT,enabled=False,aggregate_enabled=False))
        envelope=service.initial_state();envelope.update(clock_at=AT,projected_at=AT)
        class Initial(CurrentStateProvider):
            def initial_state(self):return deepcopy(envelope)
        service.store=store=CurrentStore(Initial(),monotonic=lambda:0)
        sink=LatestStateSink(store,envelope)
        states={v:dict(s,state='available') for v,s in service.states.items()}
        with patch('app.collection.current_sink.utc',return_value=AT):
            sink.commit(dict(type='current_aggregate',sport='MLB',body=body(at=AT,books=('novig','prophetx','pinnacle')),received_at=AT),states)
        raw=store.snapshot();validate_snapshot(raw)
        self.assertGreater(len(raw['comparison_profiles']),2)
        quotes=[q for e in raw['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)]
        novig=next(q for q in quotes if q['venue']=='novig')
        self.assertEqual(novig['state'],'budget_delayed')
        self.assertEqual(novig['times']['source_at'],AT)
        self.assertEqual(novig['original']['value'],'2.5000')
        self.assertEqual(novig['comparison_input_status']['fee']['status'],'applicability_unresolved')
        self.assertNotEqual(novig['calculations']['net_ev']['reason'],'comparison_inputs_unbound')
        self.assertTrue(novig['sharp_reference'])
        prophet=next(q for q in quotes if q['venue']=='prophetx')
        self.assertEqual(prophet['comparison_input_status']['fee']['status'],'applicability_unresolved')
        self.assertFalse(prophet['calculations']['net_ev']['eligible'])
        self.assertIn('execution_channel_and_mandatory_charges_unqualified',prophet['calculations']['net_ev']['reason'])
        self.assertIsNotNone(prophet['comparison_input_refs']['refs']['quantity'])
        ref=raw['comparison_profiles'][prophet['comparison_input_refs']['refs']['reference']]['payload']
        self.assertEqual(ref['outcomes'][0]['selection']['schema_version'],'comparison-domain-1')
        self.assertTrue(all(not group['comparison_pairs'] for event in raw['events'] for group in event['groups']))
        self.assertEqual(sink.metrics['admitted_observations'],1)

    def test_unknown_exception_keeps_decisive_commission_cashflows(self):
        request,scenario,kwargs=setup_case('prophetx',quantity='100',gross_win='250')
        scenario=deepcopy(scenario)
        scenario['legs'][0]['receipts']['refund']=None
        result=calculate_net_costs(request,scenario,**kwargs)
        self.assertTrue(result['available'],result['reasons'])
        self.assertFalse(result['complete_state_available'])
        self.assertEqual(Fraction(result['states']['win']['net_profit_usd']),147)
        self.assertEqual(Fraction(result['states']['loss']['net_profit_usd']),-100)
        self.assertIsNone(result['states']['refund']['net_profit_usd'])
        self.assertEqual(result['states']['refund']['reasons'],['scenario_receipt_unknown'])


if __name__=='__main__':unittest.main()
