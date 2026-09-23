import json,unittest,importlib.util
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from app.dashboard import product_view,session_history
from app.dashboard.native_retained_review import SESSION,CUTOFF
from app.dashboard.native_filing_review import VERSION,ROOT,facts,series_at,suspension_modes
class FilingReviewTests(unittest.TestCase):
 def test_explicit_series_baseline_and_conflicts(self):
  h=json.loads((ROOT/'03-response.bin').read_text());at='2026-09-23T15:09:37+00:00'
  self.assertEqual(series_at(h,at)['effective_from'],'2026-01-01T08:00:00Z')
  self.assertIsNone(series_at(h,'2026-01-01T07:59:59+00:00'))
  self.assertIsNone(series_at(dict(h,cursor='next'),at));self.assertIsNone(series_at({},at))
  x=deepcopy(h);x['series_fee_change_arr'].append(dict(x['series_fee_change_arr'][0],fee_multiplier=2));self.assertIsNone(series_at(x,at))
  x=deepcopy(h);x['series_fee_change_arr'][0]['series_ticker']='OTHER';self.assertIsNone(series_at(x,at))
 def test_material_suspension_conflict_never_assigns_payout(self):
  r=suspension_modes('56',league_final=False,not_resumed=True);self.assertNotEqual(r['filing'],r['current_terms']);self.assertIsNone(r['payout'])
  r=suspension_modes('56',league_final=True,not_resumed=True);self.assertEqual(r['filing'],r['current_terms'])
  for minute in ('55','60','NaN'):
   self.assertFalse(suspension_modes(minute,league_final=False,not_resumed=True)['available'])
  self.assertFalse(suspension_modes('56',league_final=None,not_resumed=True)['available'])
  self.assertFalse(suspension_modes('56',league_final=1,not_resumed=True)['available'])
 def test_prior_reviews_exact_and_new_review_does_not_qualify(self):
  s=session_history.load(Path('evidence/b6-two-source-scope-'+SESSION)/SESSION,CUTOFF)
  for v in (1,2,3,4):
   expected=json.loads(Path(f'evidence/b6-native-review-20260923-v{v}/review.json').read_text())['calculations']
   self.assertEqual(json.loads(json.dumps({g['id']:product_view.calculate(s,g,{'review':f'atl-gb-native-review-{v}'}) for g in s['games']})),expected)
  for g in s['games']:
   r=product_view.calculate(s,g,{'review':VERSION});self.assertEqual(r['retained_review']['filing_review']['series_history']['fee_multiplier'],'1')
   for c in r['candidates']:
    self.assertIsNone(c['profit']);self.assertFalse(c['current_executable'])
    self.assertIsNone(c['review_settlement_branches']['suspension'])
    if any(float(l['age_seconds'])>15 for l in c['legs']):self.assertIn('Receipt stale at cutoff',c['reasons']);self.assertIn('Books more than 5 seconds apart at cutoff',c['reasons'])
  self.assertFalse(facts()['fees_fully_qualified'])
 def test_consumed_before_network(self):
  path=ROOT.parent/'package/run.py';s=importlib.util.spec_from_file_location('closed_exact',path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
  with patch.object(m.aiohttp,'ClientSession',side_effect=AssertionError('network')):
   with self.assertRaisesRegex(m.GlobalStop,'consumed'):m.consume(ROOT.parent/'approval.json')
