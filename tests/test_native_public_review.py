import json,unittest
from pathlib import Path
from app.dashboard import session_history,product_view
from app.dashboard.native_retained_review import SESSION,CUTOFF
from app.dashboard.native_public_review import VERSION,us_entry_bound,reviewed_registry,EFFECTIVE
class PublicReviewTests(unittest.TestCase):
 def test_original_reviews_exact_and_new_bounds_do_not_qualify_net(self):
  s=session_history.load(Path('evidence/b6-two-source-scope-'+SESSION)/SESSION,CUTOFF)
  for version in (1,2):
   old=json.loads(Path(f'evidence/b6-native-review-20260923-v{version}/review.json').read_text())
   self.assertEqual({g['id']:json.loads(json.dumps(product_view.calculate(s,g,{'review':f'atl-gb-native-review-{version}'}))) for g in s['games']},old['calculations'])
  for g in s['games']:
   r=product_view.calculate(s,g,{'review':VERSION})
   self.assertTrue(r['retained_review']['resolved_us_fee_coefficient'])
   self.assertFalse(r['retained_review']['acquired_evidence']['kalshi_terms']['historical_applicability'])
   for c in r['candidates']:
    self.assertIsNone(c['profit']);self.assertFalse(c['current_executable'])
    leg=next(l for l in c['legs'] if l['venue']=='polymarket_us')
    self.assertEqual(leg['review_entry_fee_bound']['upper'],'1.43' if leg['ask']=='0.7100' else '1.45')
    if any(float(l['age_seconds'])>15 for l in c['legs']):
     self.assertIn('Receipt stale at cutoff',c['reasons']);self.assertIn('Books more than 5 seconds apart at cutoff',c['reasons'])
 def test_dated_coefficient_and_no_unknown_split_exact_fee(self):
  f=[dict(price='0.71',quantity='100')]
  self.assertFalse(us_entry_bound(f,'2026-09-17T03:59:59+00:00','0.0695')['available'])
  self.assertFalse(us_entry_bound(f,'2026-09-24T00:00:00+00:00','0.0695')['available'])
  self.assertFalse(us_entry_bound(f,EFFECTIVE,'0.06')['available'])
  b=us_entry_bound(f,EFFECTIVE,'0.0695');self.assertEqual(b['upper'],'1.43');self.assertIsNone(b['exact_fee'])
 def test_cumulative_cap_contains_different_fill_partitions_and_half_even(self):
  from app.fee_example import scenario
  from app.fees import calculate
  from decimal import Decimal
  for price in ('.71','.295','.50'):
   upper=Decimal(us_entry_bound([dict(price=price,quantity='100')],EFFECTIVE,'0.0695')['upper'])
   for quantities in ([100],[1]*100,[33,33,34],[25]*4):
    c=scenario(price=price,quantity='100');c.update(schedule_version='pmus-2026-09-17-native-review3',trade_time=EFFECTIVE,calculation_time=EFFECTIVE)
    c['fills']=[dict(c['fills'][0],fill_id=str(i),quantity=str(q)) for i,q in enumerate(quantities)]
    a=calculate(c,reviewed_registry());self.assertLessEqual(Decimal(a['entry_fees']),upper);self.assertGreaterEqual(Decimal(a['entry_fees']),0)
  self.assertEqual(us_entry_bound([dict(price='.50',quantity='1000')],EFFECTIVE,'0.0695')['upper'],'17.38')
 def test_new_document_examples_in_existing_fee_engine(self):
  from app.fee_example import scenario
  from app.fees import calculate
  from decimal import Decimal
  for p,want in [('.10','6.26'),('.65','15.81'),('.30','14.60'),('.90','6.26'),('.50','17.38')]:
   c=scenario(price=p);c.update(schedule_version='pmus-2026-09-17-native-review3',trade_time=EFFECTIVE,calculation_time=EFFECTIVE)
   a=calculate(c,reviewed_registry());self.assertEqual(Decimal(a['entry_fees']),Decimal(want))
 def test_attempt_is_consumed_before_network(self):
  import importlib.util
  from unittest.mock import patch
  p=Path('evidence/b6-public-prerequisites-20260923-v1/package/run.py')
  spec=importlib.util.spec_from_file_location('consumed_public_run',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  with patch.object(m.aiohttp,'ClientSession',side_effect=AssertionError('network')):
   with self.assertRaisesRegex(m.GlobalStop,'consumed'):m.consume(p.parent/'approval.json')
