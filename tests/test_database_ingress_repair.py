import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from app.collection.current_database import DatabaseIngressSink
from app.collection.current_policy import DEFAULT
from app.storage.current_games import age_result

R=Path(__file__).resolve().parents[1]
class IngressRepair(unittest.TestCase):
    def test_aggregate_byte_payload_uses_existing_ingress_bound(self):
        sink=DatabaseIngressSink(None,None,DEFAULT)
        # Deliberately stop after byte admission, before the unrelated state reducer.
        with self.assertRaises(AttributeError):sink.commit(dict(type='current_aggregate',body=b'[]'),{})
        with self.assertRaisesRegex(ValueError,'capacity'):
            sink.commit(dict(type='current_aggregate',body=b'x'*DEFAULT['ingress_bytes']),{})
    def test_approved_reference_clocks_control_saved_freshness(self):
        v=json.loads((R/'tests/fixtures/stored-game-arrival.json').read_text())
        current=age_result(v,at=v['as_of'])
        self.assertEqual(current['status'],'current')
        original=current['state']['events'][0]['groups'][0]['outcomes'][0]['quotes']['novig']['original']
        historical=age_result(v,at='2026-10-14T01:00:00Z')
        self.assertEqual(historical['status'],'historical')
        self.assertEqual(historical['state']['events'][0]['groups'][0]['outcomes'][0]['quotes']['novig']['original'],original)

    def test_unrelated_historical_spread_keeps_current_winner_and_pair(self):
        from copy import deepcopy
        v=json.loads((R/'tests/fixtures/stored-game-arrival.json').read_text())
        event=v['state']['events'][0]
        spread=next(g for g in event['groups'] if g['market']=='spread')
        for o in spread['outcomes']:
            for q in o['quotes'].values():q['times']['source_at']='2026-10-12T20:00:00Z'
        winner=next(g for g in event['groups'] if g['market']=='winner')
        for o in winner['outcomes']:
            for q in o['quotes'].values():q['calculations']['funded_estimate']['ranking_eligible']=True
        for pair in event['funded_pairs']:pair['ranking_eligible']=True
        result=age_result(v,at=v['as_of']);self.assertEqual(result['status'],'current')
        self.assertTrue(result['state']['events'][0]['funded_pairs'][0]['ranking_eligible'])
        stale_spread=next(g for g in result['state']['events'][0]['groups'] if g['id']==spread['id'])
        self.assertTrue(all(q['saved_status']=='historical' for o in stale_spread['outcomes'] for q in o['quotes'].values()))
        result=age_result(dict(v,superseded=True),at=v['as_of']);self.assertEqual(result['status'],'historical')
        self.assertFalse(result['state']['events'][0]['funded_pairs'][0]['ranking_eligible'])
