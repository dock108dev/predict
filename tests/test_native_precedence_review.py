import json,unittest
from pathlib import Path
from app.dashboard.native_precedence_review import precedence,shared_suspension,VERSION
from app.dashboard.native_retained_review import SESSION,CUTOFF
from app.dashboard import session_history,product_view
class PrecedenceTests(unittest.TestCase):
 def test_quote_provenance_and_no_supersession_inferred(self):
  t=precedence();self.assertEqual(len(t['rows']),11)
  for r in t['rows']:self.assertTrue(r['explicit_supersession']);self.assertTrue(r['native_linkage'])
  self.assertEqual(t['sources']['K-CURRENT']['effective'],'unknown')
  self.assertIn('missing precedence',[r['status'] for r in t['rows']])
 def test_common_branches_and_strict_unknowns(self):
  flags=dict(no_scheduled_resumption=True,not_completed_in_time=True,period_complete=False,criterion_definitive=False)
  self.assertTrue(shared_suspension('54',league_final=False,**flags)['available'])
  self.assertTrue(shared_suspension('56',league_final=True,**flags)['available'])
  for m,final in [('55',False),('56',False),('54',True),('NaN',False),('bad',False)]:self.assertFalse(shared_suspension(m,league_final=final,**flags)['available'])
  for k in flags:self.assertFalse(shared_suspension('54',league_final=False,**dict(flags,**{k:None}))['available'])
  self.assertIsNone(shared_suspension('54',league_final=False,**flags)['payout'])
 def test_versions_exact_and_unchanged_economics(self):
  s=session_history.load(Path('evidence/b6-two-source-scope-'+SESSION)/SESSION,CUTOFF)
  for v in (1,2,3,4,5):
   expected=json.loads(Path(f'evidence/b6-native-review-20260923-v{v}/review.json').read_text())['calculations']
   self.assertEqual(json.loads(json.dumps({g['id']:product_view.calculate(s,g,{'review':f'atl-gb-native-review-{v}'}) for g in s['games']})),expected)
  for g in s['games']:
   before=product_view.calculate(s,g,{'review':'atl-gb-native-review-5'});after=product_view.calculate(s,g,{'review':VERSION})
   self.assertEqual(before['candidates'],after['candidates']);self.assertEqual(before['ev'],after['ev'])
   self.assertEqual(after['retained_review']['version'],VERSION)
