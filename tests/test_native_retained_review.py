import json
from pathlib import Path
import unittest
from copy import deepcopy
from app.dashboard import session_history,product_view
from app.dashboard.native_retained_review import VERSION,SESSION,CUTOFF,point_for
ROOT=Path('evidence/b6-two-source-scope-'+SESSION)/SESSION
class RetainedReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot=session_history.load(ROOT,CUTOFF)
        cls.oracle=json.loads((ROOT/'qualification-oracle.json').read_text())
    def test_original_unchanged_and_review_stricter(self):
        for game in self.snapshot['games']:
            old=product_view.calculate(self.snapshot,game,{})
            self.assertEqual(json.loads(json.dumps({k:v for k,v in old.items() if k!='state'})),self.oracle['calculations'][game['id']])
            review=product_view.calculate(self.snapshot,game,{'review':VERSION})
            for a,b in zip(old['candidates'],review['candidates']):
                self.assertEqual(a['notional'],b['notional']);self.assertIsNone(b['profit'])
                self.assertIn('Market state unknown at cutoff',b['reasons'])
                if any(float(l['age_seconds'])>15 for l in b['legs']):self.assertIn('Receipt stale at cutoff',b['reasons'])
                self.assertIn(b['review_before_fees']['normal_winner_margin'],('-1.0000','-0.5000'))
    def test_exact_binding_and_no_clock_or_age_promotion(self):
        point=next(iter(self.snapshot['points'].values()))
        for age,stale in [('15',False),('15.000001',True),('-0.1',True),(None,True)]:
            p=deepcopy(point);p['cards'][0]['age_seconds']=age
            self.assertEqual(point_for(self.snapshot,p,VERSION)['cards'][0]['receipt_stale'],stale)
        for field,value in [('session_id','other'),('durable_cursor','other')]:
            s=dict(self.snapshot);s[field]=value
            with self.assertRaises(ValueError):point_for(s,point,VERSION)

class OrdinaryReviewRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_and_versioned_calculations_through_saved_details_route(self):
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.coverage_owner import CoverageOwner
        from app.dashboard.multi_game_server import create_app
        from unittest.mock import patch
        from app.dashboard.opportunity_board import present
        owner=CoverageOwner(ROOT.parent/'legacy',pilot_output=ROOT.parent,product_mode=True)
        async def forbidden(*args,**kwargs):raise ValueError('Read-only review')
        owner.start=forbidden
        with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('no access')):
            client=TestClient(TestServer(create_app(owner=owner,sessions={})))
            await client.start_server()
            try:
                snap=session_history.load(ROOT,CUTOFF)
                for game in snap['games']:
                    from app.dashboard.native_acquisition_review import VERSION as acquired_version
                    for version in ('',VERSION,acquired_version,'atl-gb-native-review-3','atl-gb-native-review-4','atl-gb-native-review-5','atl-gb-native-review-6','atl-gb-native-review-7'):
                        q=dict(session=SESSION+'~'+game['id'],hash=SESSION,cutoff=CUTOFF,quantity='100',scenario='unknown')
                        if version:q['review']=version
                        response=await client.get('/api/calculate',params=q)
                        self.assertEqual(response.status,200)
                        data=await response.json()
                        expected=present(product_view.calculate(snap,game,q))
                        self.assertEqual(data['candidates'],expected['candidates'])
                response=await client.post('/api/start',json={'duration':90},headers={'Origin':str(client.make_url('/')).rstrip('/')})
                self.assertEqual(response.status,422)
            finally:await client.close()

class AcquiredReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot=session_history.load(ROOT,CUTOFF)

    def test_metadata_is_not_promoted_to_historical_fees_or_state(self):
        from app.dashboard.native_acquisition_review import VERSION as acquired_version,HISTORICAL_FEE_GAP
        v1=json.loads(Path('evidence/b6-native-review-20260923-v1/review.json').read_text())
        for game in self.snapshot['games']:
            old=product_view.calculate(self.snapshot,game,{'review':VERSION})
            self.assertEqual(json.loads(json.dumps(old)),v1['calculations'][game['id']])
            result=product_view.calculate(self.snapshot,game,{'review':acquired_version,'scenario':'cent'})
            f=result['retained_review']['acquired_evidence']
            self.assertEqual(f['kalshi']['observed_fee_type'],'quadratic_with_maker_fees')
            self.assertEqual(f['kalshi']['observed_fee_multiplier'],'1')
            self.assertTrue(f['kalshi']['event_history_pagination_complete'])
            self.assertEqual(f['kalshi']['returned_event_overrides'],[])
            self.assertFalse(f['kalshi']['historical_fee_baseline_qualified'])
            self.assertFalse(f['historical_state_qualified'])
            self.assertFalse(f['historical_clock_offset_qualified'])
            self.assertFalse(f['kalshi']['contract_document_retrieved'])
            for key in ('exact_entry_fees','applicable_fee_bounds','settlement_charges','kalshi_account_balance_precision','resting_order_split'):
                self.assertIsNone(f['fee_and_rule_qualification'][key])
            self.assertEqual(result['scenario'],'unknown')
            for before,after in zip(old['candidates'],result['candidates']):
                self.assertEqual(before['review_before_fees'],after['review_before_fees'])
                self.assertIsNone(after['profit'])
                self.assertFalse(after['usable'])
                self.assertFalse(after['current_executable'])
                self.assertIn(HISTORICAL_FEE_GAP,after['reasons'])
                self.assertEqual('Receipt stale at cutoff' in before['reasons'],'Receipt stale at cutoff' in after['reasons'])
                self.assertEqual('Books more than 5 seconds apart at cutoff' in before['reasons'],'Books more than 5 seconds apart at cutoff' in after['reasons'])
                for a,b in zip(before['legs'],after['legs']):
                    for key in ('fills','notional','book_id','source_at','received_at','age_seconds','fees'):
                        self.assertEqual(a.get(key),b.get(key))

    def test_acquired_review_requires_exact_saved_binding(self):
        from app.dashboard.native_acquisition_review import VERSION as acquired_version
        point=next(iter(self.snapshot['points'].values()))
        for field in ('session_id','durable_cursor'):
            s=dict(self.snapshot);s[field]='other'
            with self.assertRaises(ValueError):point_for(s,point,acquired_version)
        with self.assertRaises(ValueError):point_for(self.snapshot,point,'atl-gb-native-review-999')

    def test_acquired_response_or_provenance_tampering_fails_closed(self):
        from app.dashboard.native_acquisition_review import facts,HASHES,ROOT as acquired_root
        from tempfile import TemporaryDirectory
        import shutil
        with TemporaryDirectory() as directory:
            root=Path(directory)
            for name in HASHES:shutil.copyfile(acquired_root/name,root/name)
            for name in HASHES:
                original=(root/name).read_bytes()
                (root/name).write_bytes(original+b' ')
                with self.assertRaisesRegex(ValueError,'hash mismatch'):facts(root)
                (root/name).write_bytes(original)
            self.assertEqual(facts(root)['execution']['requests'],3)

    def test_acquisition_consumed_before_any_network_constructor(self):
        import importlib.util
        from unittest.mock import patch
        path=Path('evidence/b6-native-acquisition-20260923-v1/acquire.py')
        spec=importlib.util.spec_from_file_location('closed_acquisition',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.object(module.aiohttp,'ClientSession',side_effect=AssertionError('No new network')) as network:
            with self.assertRaises(FileExistsError):module.Attempt()
            network.assert_not_called()
