import json,unittest
from pathlib import Path
from app.dashboard.native_us_rulebook_review import VERSION,facts,conditional_priority
from app.dashboard.native_retained_review import SESSION,CUTOFF
from app.dashboard import session_history,product_view
class USRulebookTests(unittest.TestCase):
 def test_priority_requires_scope_applicability_and_no_same_level_conflict(self):
  rows=[dict(market_id='779756',layer=k,value=v) for k,v in [('rulebook','generic'),('product_specifications','product'),('contract_terms','last fair price')]]
  self.assertFalse(conditional_priority(rows,market_id='779756')['available'])
  self.assertEqual(conditional_priority(rows,market_id='779756',applicability_established=True)['selected']['value'],'last fair price')
  self.assertFalse(conditional_priority(rows,market_id='other',applicability_established=True)['available'])
  self.assertFalse(conditional_priority(rows+[dict(rows[-1],value='50-50')],market_id='779756',applicability_established=True)['available'])
 def test_effective_date_and_fee_omission_are_not_assumed(self):
  f=facts();self.assertEqual(f['document_date'],'2026-09-14');self.assertIsNone(f['effective_at_historical_cutoff']);self.assertIsNone(f['fees']['settlement_charge']);self.assertFalse(f['net_qualified'])
 def test_original_reviews_and_economics_unchanged(self):
  s=session_history.load(Path('evidence/b6-two-source-scope-'+SESSION)/SESSION,CUTOFF)
  for v in (1,2,3,4,5,6):
   want=json.loads(Path(f'evidence/b6-native-review-20260923-v{v}/review.json').read_text())['calculations']
   self.assertEqual(json.loads(json.dumps({g['id']:product_view.calculate(s,g,{'review':f'atl-gb-native-review-{v}'}) for g in s['games']})),want)
  for g in s['games']:
   old=product_view.calculate(s,g,{'review':'atl-gb-native-review-6'});new=product_view.calculate(s,g,{'review':VERSION});self.assertEqual(old['candidates'],new['candidates']);self.assertEqual(old['ev'],new['ev'])
