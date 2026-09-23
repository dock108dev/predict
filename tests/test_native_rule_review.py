import json,unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from app.dashboard import product_view,session_history
from app.dashboard.native_retained_review import SESSION,CUTOFF
from app.dashboard.native_rule_review import VERSION,evidence,conditional_payout,conditional_kalshi_model
class RuleReviewTests(unittest.TestCase):
 def test_provenance_and_distinct_missing_vs_different_rules(self):
  e=evidence();self.assertFalse(e['kalshi_fee']['historical_applicability']);self.assertFalse(e['settlement_equivalent'])
  self.assertEqual(e['kalshi_fee']['settlement_charge_in_extraction'],'0')
  self.assertEqual(e['kalshi_fee']['taker_formula'],'M * 0.07 * C * P * (1-P)')
  self.assertIn('different contractual triggers',[b['status'] for b in e['branches']])
  self.assertIn('missing US documentation',[b['status'] for b in e['branches']])
 def test_conditional_formula_never_claims_charged_fee(self):
  for price,expected in [('.30','1.47'),('.71','1.4413')]:
   r=conditional_kalshi_model([dict(price=price,quantity='100')]);self.assertEqual(Decimal(r['raw_fee']),Decimal(expected));self.assertIsNone(r['charged_fee'])
  with self.assertRaises(ValueError):conditional_kalshi_model([dict(price='NaN',quantity='100')])
 def test_only_supported_branch_payouts(self):
  for outcome in ('ordinary_final_winner','full_game_tie'):
   self.assertEqual(conditional_payout(outcome,'100'),'100')
   self.assertIsNone(conditional_payout(outcome,'100',exceptional=True))
  for outcome in ('fair_price','suspension','forfeit','overtime','unknown'):
   self.assertIsNone(conditional_payout(outcome,'100'))
  for q in ('NaN','Infinity','0','-1','1e1000'):
   with self.assertRaises(ValueError):conditional_payout('full_game_tie',q)
 def test_ordinary_saved_details_preserves_versions_and_failures(self):
  with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials')):
   s=session_history.load(Path('evidence/b6-two-source-scope-'+SESSION)/SESSION,CUTOFF)
   for version in (1,2,3):
    expected=json.loads(Path(f'evidence/b6-native-review-20260923-v{version}/review.json').read_text())['calculations']
    self.assertEqual(json.loads(json.dumps({g['id']:product_view.calculate(s,g,{'review':f'atl-gb-native-review-{version}'}) for g in s['games']})),expected)
   for g in s['games']:
    r=product_view.calculate(s,g,{'review':VERSION})
    for c in r['candidates']:
     self.assertIsNone(c['profit']);self.assertFalse(c['current_executable'])
     b=c['review_partial_margin'];self.assertEqual(Decimal(b['lower']),Decimal('-2.43') if Decimal(c['notional'])==101 else Decimal('-1.95'))
     self.assertIsNone(c['review_settlement_branches']['fair_price'])
     if any(float(l['age_seconds'])>15 for l in c['legs']):
      self.assertIn('Receipt stale at cutoff',c['reasons']);self.assertIn('Books more than 5 seconds apart at cutoff',c['reasons'])
