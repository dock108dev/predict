"""Offline retained evidence and explicitly constructed negative controls."""
import base64,json,unittest
from copy import deepcopy
from pathlib import Path
from datetime import datetime,timezone
from app.collection.native_review_contract import contract,compare,matches,project
from app.collection.native_target import check
from app.collection import coverage
from app.dashboard.session_history import verified
from app.dashboard.session_projection import stable
ROOT=Path(__file__).resolve().parents[1]
SPEC=json.loads((ROOT/'evidence/native-nyi-tor-20260930-v1/run-spec.json').read_text())
T=SPEC['native_review_records']
ORIGINAL=ROOT/'evidence/native-nyi-tor-attempt-5c26ecaf-d41b-4589-a590-d2423e2aa62d/5da7cfc8-926c-4591-a6e9-e3354942d45b'
class Semantic(unittest.TestCase):
 def test_captured_activity_and_material_controls(self):
  page=next(x for x in verified(ORIGINAL)['rows'] if x['type']=='prediction_discovery_http' and x['source']=='kalshi')
  e=json.loads(base64.b64decode(page['body_b64']))['events'][0]
  templates=deepcopy(T)
  for t in templates:
   b=t['sources']['kalshi'];b['semantic_review_contract']=contract('kalshi',b['catalog_evidence']['event']['native_metadata'],b['metadata'])
   m=next(m for m in e['markets'] if m['ticker']==b['market_id'])
   self.assertNotEqual(stable(m),b['native_metadata_sha256'])
   self.assertTrue(compare('kalshi',b['metadata'],m)[0])
   for key,value in [('rules_primary','CONSTRUCTED changed rules'),('custom_strike',{'changed':True}),('close_time','2026-10-03T00:00:00Z'),('unknown_material','unknown'),('yes_bid_dollars','NaN'),('status','closed')]:
    bad=deepcopy(m);bad[key]=value
    self.assertFalse(compare('kalshi',b['metadata'],bad)[0],key)
   bad=deepcopy(m);bad.pop('volume_fp');self.assertFalse(compare('kalshi',b['metadata'],bad)[0])
  cat=coverage.catalog([page],'kalshi',datetime(2026,9,30,19,tzinfo=timezone.utc))
  self.assertEqual(check(cat,'kalshi',templates,datetime(2026,9,30,19,tzinfo=timezone.utc))[0],['KXNHLGAME-26SEP30NYITOR-NYI','KXNHLGAME-26SEP30NYITOR-TOR'])
 def test_us_prices_keep_currency_terms_and_bad_values_excluded(self):
  b=T[0]['sources']['polymarket_us'];e=b['catalog_evidence']['event']['native_metadata'];m=b['metadata'];c=contract('polymarket_us',e,m)
  current=deepcopy(m);current['bestBidQuote']['value']='0.51';current['marketSides'][0]['price']='0.52'
  self.assertTrue(matches('polymarket_us',c,e,current))
  for mutate in (lambda m:m['bestBidQuote'].update(currency='EUR'),lambda m:m['marketSides'][0].update(price='NaN'),lambda m:m.update(outcomes='CONSTRUCTED other outcome'),lambda m:m.update(active=None),lambda m:m.pop('closed')):
   bad=deepcopy(current);mutate(bad);self.assertFalse(matches('polymarket_us',c,e,bad))
 def test_original_policy_still_rejects_activity(self):
  page=next(x for x in verified(ORIGINAL)['rows'] if x['type']=='prediction_discovery_http' and x['source']=='kalshi')
  cat=coverage.catalog([page],'kalshi',datetime(2026,9,30,19,tzinfo=timezone.utc))
  self.assertFalse(check(cat,'kalshi',T,datetime(2026,9,30,19,tzinfo=timezone.utc))[0])
if __name__=='__main__':unittest.main()
