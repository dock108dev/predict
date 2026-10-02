"""Real retained response shapes, with no provider requests or credentials."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import tempfile
import subprocess
from app.collection import coverage
from app.adapters import polymarket_us

ROOT=Path(__file__).resolve().parents[1]
RECORDS=ROOT/'evidence/source-engineering-authorization-20260930-v1/execution/repair-records.json'

class RetainedDeliveryRepairs(unittest.TestCase):
    def setUp(self):self.pages=json.loads(RECORDS.read_text())['pages']

    def test_overfull_complete_page_retains_all_contracts_without_exhaustion(self):
        page=next(p for p in self.pages if p['path']=='/trade-api/v2/markets')
        accepted,status=coverage.traversal([page],'kalshi','markets')
        self.assertEqual(len(accepted),1)
        self.assertEqual(len(accepted[0][2]['markets']),14)
        self.assertEqual(status['state'],'bounded/truncated')
        self.assertIn('more rows',status['reason'])
        legacy=deepcopy(page);legacy.pop('transport_policy')
        self.assertFalse(coverage.traversal([legacy],'kalshi','markets')[0])

    def test_new_basketball_type_is_exact_side_identity_not_a_league_guess(self):
        page=next(p for p in self.pages if p['source']=='polymarket_us')
        _,data=coverage.decode_page(page);event=data['events'][0]
        legacy=polymarket_us.event_game_binding(event,'nba')
        self.assertEqual(legacy['basis'],'event_teams_only')
        bound=polymarket_us.event_game_binding(event,'nba',live_bindings=True)
        self.assertEqual(bound['basis'],'embedded_full_game_side_team_ids')
        self.assertEqual(len(bound['teams']),2)
        changed=deepcopy(event);changed['markets'][0]['marketSides'][0]['teamId']=999999
        with self.assertRaises(ValueError):polymarket_us.event_game_binding(changed,'nba',live_bindings=True)

    def test_list_detail_equivalence_preserves_terms_and_old_cutoffs(self):
        pages=json.loads(RECORDS.read_text())['detail_pages']
        old=coverage.catalog(pages,'polymarket_us',coverage.stamp(pages[-1]['received_at']))
        old_markets={m['id'] for m in old['markets']}
        self.assertNotIn('919543',old_markets)
        current=deepcopy(pages)
        for p in current:p['native_binding_revision']='live-native-binding-2'
        new=coverage.catalog(current,'polymarket_us',coverage.stamp(pages[-1]['received_at']))
        self.assertIn('919543',{m['id'] for m in new['markets']})
        event_page=current[0];body,data=coverage.decode_page(event_page)
        native=next(m for e in data['events'] for m in e['markets'] if m['id']=='919543')
        records={};record=coverage.market_record('polymarket_us',event_page,body,native,'115743',1)
        coverage.insert(records,record,native,coverage.provenance(event_page,1,body))
        detail=current[1];body,data=coverage.decode_page(detail);changed=deepcopy(data['markets'][0]);changed['description']+=' materially changed rule'
        record=coverage.market_record('polymarket_us',detail,body,changed,'115743',2)
        coverage.insert(records,record,changed,coverage.provenance(detail,2,body))
        self.assertTrue(records['919543']['conflicting_duplicate'])

    def test_current_modified_timestamps_and_sort_leave_material_changes_blocked(self):
        from app.collection.native_review_contract import contract,matches,CURRENT_POLICY
        pages=json.loads(RECORDS.read_text())['detail_pages'];_,data=coverage.decode_page(pages[0]);event=data['events'][0];market=event['markets'][0]
        policy=contract('polymarket_us',event,market,policy=CURRENT_POLICY)
        refreshed=deepcopy(event);refreshed['updatedAt']='2026-10-01T02:00:00Z';refreshed['sortType']='price';refreshed['tags'][0]['updatedAt']='2026-10-01T02:00:00Z'
        updated=deepcopy(market);updated['updatedAt']='2026-10-01T02:00:00Z'
        self.assertTrue(matches('polymarket_us',policy,refreshed,updated))
        updated['description']+=' material rule change';self.assertFalse(matches('polymarket_us',policy,refreshed,updated))
        updated=deepcopy(market);updated['feeCoefficient']=999;self.assertFalse(matches('polymarket_us',policy,refreshed,updated))
        updated=deepcopy(market);updated['updatedAt']='not-a-time';self.assertFalse(matches('polymarket_us',policy,refreshed,updated))
        refreshed['tags'][0]['id']='changed-scope';self.assertFalse(matches('polymarket_us',policy,refreshed,market))

    def test_existing_ignored_credential_is_read_only_and_still_start_gated(self):
        from app.collection.credential_handoff import existing_key
        from app.collection.source_session import AggregateWorker
        from tests.test_source_session import settings
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);subprocess.run(['git','init','-q',directory],check=True)
            (root/'.gitignore').write_text('.env\n');path=root/'.env';body=b'UNCHANGED=yes\nODDS_API_KEY=dummy-existing-key\n';path.write_bytes(body)
            before=path.stat().st_mtime_ns
            self.assertEqual(existing_key(root),'dummy-existing-key');self.assertEqual(path.read_bytes(),body);self.assertEqual(path.stat().st_mtime_ns,before)
            path.write_text('ODDS_API_KEY=one\nODDS_API_KEY=two\n')
            with self.assertRaises(ValueError):existing_key(root)
        session=SimpleNamespace(spec=dict(mode='real',source_session=settings()),native_authorized=False)
        with patch('app.collection.credential_handoff.existing_key',side_effect=AssertionError('Unapproved credential access')):
            with self.assertRaisesRegex(ValueError,'approval'):AggregateWorker(session)

if __name__=='__main__':unittest.main()
