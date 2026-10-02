"""Actual H1 evidence and hostile scope changes through shared saved routes."""
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from aiohttp.test_utils import TestClient, TestServer
from app.reference import aggregate_assessment as rules
from app.dashboard.session_history import load
from app.dashboard.price_comparison import comparisons
from app.dashboard.session_projection import stable
from app.dashboard import product_view
from app.settlement import validate

ROOT=Path(__file__).resolve().parents[1]
F=ROOT/'evidence/source-bindings-20260929/sessions/odds-aggregate-2d5e0a0b077b851fc632'
OUT=ROOT/'evidence/h1-rules-identity-20260929'

class Assessments(unittest.TestCase):
 def test_exact_record_only_public_rules_not_payouts(self):
  s=load(F);original=deepcopy(s);rows=comparisons(s,{})
  self.assertEqual(s,original)
  self.assertEqual(len(rows),2)
  for row in rows:
   a=row['rule_analysis']
   self.assertEqual(a['version'],rules.VERSION)
   self.assertEqual(a['status'],'documented_unbound')
   self.assertEqual(a['hash'],stable({k:v for k,v in a.items() if k!='hash'}))
   self.assertEqual(row['settlement_status'],'UNKNOWN')
   self.assertFalse(row['settlement_audit']['qualified'])
   self.assertIsNone(row['net']);self.assertIsNone(row['ev'])
   for p in a['documented_profiles'].values(): validate(p)
   for p in a['effective_profiles'].values():
    validate(p);self.assertTrue(all(x['value'] is None for x in p['dimensions'].values()))
    self.assertTrue(all(x['kind']=='unknown' for x in p['payouts'].values()))
   self.assertEqual(a['documented_profiles']['novig']['payouts']['tie']['value'],'0.5')
   self.assertEqual(a['documented_profiles']['prophetx']['payouts']['tie']['kind'],'unknown')
   self.assertTrue(a['documented_comparison']['conflicts'])
   self.assertFalse(row['settlement_audit']['conflicts'])
   self.assertIn('documented only',str(row['decision']))
   self.assertIn('ProphetX first-half tie',str(row['decision']['net_reason']))
   for book,b in a['books'].items():
    self.assertIsNone(b['crosswalk']['book_market_id'])
    self.assertFalse(b['crosswalk']['native_contract_verified'])
    self.assertFalse(b['crosswalk']['contemporaneous_native_observation'])
    self.assertFalse(b['crosswalk']['rule_binding_verified'])
   self.assertTrue(all(l['url'] is None and l['top_size'] is None and not l['levels'] for l in row['legs']))
   self.assertTrue(all(l['entry']['upper'] is None for l in row['legs']))
  self.assertEqual(len(s['aggregate_coverage']),63)
  self.assertEqual(len(s['references']),18)
  self.assertTrue(all(not product_view.usable(r) for r in s['references']))
  self.assertTrue(all(not comparisons(s,{'venue':b}) for b in ('pinnacle','draftkings','betmgm')))
  self.assertFalse(product_view.dashboard(s,{'view':'arb'},{}))
  self.assertFalse(product_view.dashboard(s,{'view':'ev'},{}))

 def test_original_outputs_exact_and_research_deterministic(self):
  # The prior frozen ordinary feed is independently retained, not regenerated.
  frozen=json.loads((ROOT/'evidence/acquisition-execution-20260929/ordinary-feed.json').read_text())['comparisons']
  self.assertEqual(comparisons(load(F),{'rule_version':'original'}),frozen)
  first=comparisons(load(F),{})
  self.assertEqual(first,comparisons(load(F),{'rule_version':rules.VERSION}))
  self.assertEqual(first,comparisons(load(F,first[0]['cutoff']),{}))
  baseline=ROOT/'evidence/aggregate-ingestion-20260929/sessions/odds-aggregate-92257c7e512de1189a81'
  self.assertEqual(comparisons(load(baseline),{}),comparisons(load(baseline),{'rule_version':'original'}))

 def test_watch_exclusions_pin_research_without_live_signals(self):
  from app.dashboard.opportunity_history import observations
  from tests.test_commercial_engineering import watch
  for metric in ('raw_gap','arb_return','ev'):
   rows=observations(load(F),watch(metric))
   self.assertEqual(len(rows),2)
   for r in rows:
    self.assertFalse(r['qualifies'])
    self.assertEqual(r['point']['rule_version'],rules.VERSION)
    self.assertEqual(r['basis']['rule_analysis']['version'],rules.VERSION)
    if metric!='raw_gap':
     self.assertIsNone(r['metric'])
     self.assertIn('ProphetX first-half tie',str(r['reasons']))

 def test_scope_and_exact_record_guards(self):
  original=comparisons(load(F),{'rule_version':'original'})[0]
  for key,value in [('market','h2h'),('receipt_sha256','other'),('source_event_id','other'),('outcome','Similar Team'),('received_at','2026-09-30T00:00:00Z')]:
   row=deepcopy(original);row['legs'][0]['provenance']['original'][key]=value
   self.assertNotIn('rule_analysis',rules.enrich(row))
  row=deepcopy(original);row['legs'][0]['provenance']['original']['source_fields']['outcome']['sid']='another'
  self.assertNotIn('rule_analysis',rules.enrich(row))
  for field,value in [('period','full_game'),('competition','NCAAF'),('family','spread')]:
   row=deepcopy(original);row['identity'][field]=value
   self.assertNotIn('rule_analysis',rules.enrich(row))
  row=deepcopy(original);row['legs'][0]['venue']='pinnacle'
  self.assertNotIn('rule_analysis',rules.enrich(row))
  with self.assertRaises(ValueError):rules.enrich(deepcopy(original),'invented-version')

 def test_changed_evidence_fails_closed_without_losing_raw(self):
  row=comparisons(load(F),{'rule_version':'original'})[0]
  with patch.object(rules,'DATA_SHA256','wrong'):
   result=rules.enrich(deepcopy(row))
  self.assertEqual(result['rule_analysis']['status'],'unavailable')
  self.assertEqual(result['legs'],row['legs'])
  self.assertEqual(result['raw_difference'],row['raw_difference'])
  self.assertIsNone(result['net'])
  with patch.object(rules,'ROOT',Path('/nonexistent-evidence')):
   self.assertEqual(rules.enrich(deepcopy(row))['rule_analysis']['status'],'unavailable')

class Routes(unittest.IsolatedAsyncioTestCase):
 async def test_ordinary_details_versions_and_reopening(self):
  from app.dashboard.coverage_owner import CoverageOwner
  from app.dashboard.multi_game_server import create_app
  with tempfile.TemporaryDirectory() as tmp:
   owner=CoverageOwner(Path(tmp)/'legacy',pilot_output=Path(tmp)/'saved',product_mode=True)
   client=TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=Path(tmp)/'watches.json')))
   await client.start_server()
   try:
    response=await client.get('/api/dashboard?view=feed&capture='+F.name)
    self.assertEqual(response.status,200);feed=await response.json()
    self.assertEqual(feed['comparisons'],comparisons(load(F),{}))
    for row in feed['comparisons']:
     q={k:row[k] for k in ('session','hash','cutoff','contract')};q['rule_version']=rules.VERSION
     url='/api/calculate?'+urlencode(q)
     r=await client.get(url);self.assertEqual(r.status,200);a=await r.json()
     self.assertEqual(a,await (await client.get(url)).json())
     self.assertEqual(a['comparisons'][0]['rule_analysis']['version'],rules.VERSION)
     self.assertEqual({r['origin_id'] for r in a['references']},{'pinnacle','draftkings','betmgm'})
     q['rule_version']='original';old=await (await client.get('/api/calculate?'+urlencode(q))).json()
     self.assertNotIn('rule_analysis',old['comparisons'][0])
     self.assertEqual(old['comparisons'][0]['raw_difference'],a['comparisons'][0]['raw_difference'])
     r=await client.post('/api/decision-sizes',json=dict(q,sizes=['1']),headers={'Origin':str(client.make_url('/')).rstrip('/')})
     self.assertEqual(r.status,422)
   finally:await client.close()
