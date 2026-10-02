import asyncio,json,time,socket,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
from app.collection.continuous import Discovery,REST
from app.collection.prediction_producer import PredictionBudget
from app.collection.native_selectors import GAP_CAPS,GAP_SPORTS,gap_query
from app.collection.acquisition_policy import native_caps
from app.collection.odds_http import BudgetStop
from app.collection.venue_access import ENDPOINTS
from app.normalization.registry import Registry
from app.models.core import Venue
from tests.native_gap_fixture import HTTP,PAGES,ROOT

def spec():return json.loads((ROOT/'evidence/native-gap-probe-20260930/run-spec.json').read_text())
class Fair(unittest.IsolatedAsyncioTestCase):
 async def execute(self,mode='oversized',retry=False):
  HTTP.reset(mode,retry);records=[];stops=[];s=spec()
  session=SimpleNamespace(spec=s,started_monotonic=time.monotonic(),credentials={},endpoints=ENDPOINTS,producers={v:SimpleNamespace(budget=PredictionBudget(s['prediction']),groups={}) for v in ('kalshi','polymarket_us')},emit=lambda v,r:records.append(dict(r,source=v)),request_stop=stops.append)
  d=Discovery(session);session.discovery=d;d.selection_time=__import__('datetime').datetime.now(__import__('datetime').timezone.utc)
  try:
   with patch('aiohttp.ClientSession',HTTP),patch.object(REST,'pace',AsyncMock()),patch('socket.socket.connect',side_effect=AssertionError('No sockets')):
    await asyncio.gather(d.venue('kalshi'),d.venue('polymarket_us'))
    cats,markets=d.project()
  finally:
   for c in d.clients.values():await c.aclose()
  return d,records,stops,cats
 async def test_oversized_cfb_fair_opportunities_and_orphans(self):
  d,rows,stops,cats=await self.execute(retry=True)
  us=[r for r in rows if r['type']=='native_gap_operation' and r['source']=='polymarket_us']
  self.assertEqual([r['sport'] for r in us[:5]],list(GAP_SPORTS['polymarket_us']));self.assertTrue(all(r['phase']=='first_opportunities' and r['attempt']==1 for r in us[:5]))
  self.assertFalse(d.source_stops);self.assertFalse(stops)
  decision=next(r for r in rows if r['type']=='native_acquisition_selection' and r['source']=='polymarket_us')
  self.assertTrue(decision['sports']['NCAAF']['response_envelope_exceeded']);self.assertEqual(decision['sports']['NBA']['metadata'],'query_failed');self.assertIn('NCAAB',decision['selected'])
  self.assertEqual(len([c for c in HTTP.calls if c['params'].get('tagSlug')=='cfb']),1)
  self.assertTrue(any(r['phase']=='deferred_recovery' for r in us))
  for cat in cats.values():self.assertTrue(all(m['event_id'] in {e['id'] for e in cat['events']} for m in cat['markets']))
 async def test_complete_cfb_and_missing_metadata(self):
  d,rows,stops,cats=await self.execute('complete')
  r=next(r for r in rows if r['type']=='native_acquisition_selection' and r['source']=='polymarket_us');self.assertIn('NCAAF',r['selected']);self.assertEqual(r['sports']['NCAAF']['metadata'],'complete_bounded_page');self.assertFalse(stops)
 async def test_missing_schedule_exclusion_is_inspectable(self):
  d,rows,_,_=await self.execute('null_schedule')
  result=next(r for r in rows if r['type']=='native_acquisition_selection' and r['source']=='polymarket_us')
  self.assertNotIn('NCAAF',result['selected']);self.assertIn('missing_schedule_for_current_selection',[e['reason'] for e in result['sports']['NCAAF']['exclusions']])
 async def test_retry_cannot_starve_first_pages(self):
  d,rows,_,_=await self.execute('retry_first')
  ops=[r for r in rows if r['type']=='native_gap_operation' and r['source']=='polymarket_us'];self.assertEqual([r['sport'] for r in ops[:5]],list(GAP_SPORTS['polymarket_us']));self.assertTrue(any(r['attempt']==2 and r['sport']=='NBA' for r in ops[5:]))
 async def test_duplicate_second_page_stops_source_after_fair_opportunities(self):
  d,rows,_,_=await self.execute('duplicate');self.assertEqual(d.source_stops['polymarket_us'],'invalid_gap_traversal')
  ops=[r for r in rows if r['type']=='native_gap_operation' and r['source']=='polymarket_us'];self.assertEqual(len([r for r in ops if r['phase']=='first_opportunities']),5)
class Bindings(unittest.TestCase):
 def test_caps_scope_and_real_aliases(self):
  self.assertEqual(native_caps(spec()),GAP_CAPS);self.assertEqual(sum(GAP_CAPS.values()),42)
  with self.assertRaises(ValueError):gap_query('polymarket_us','NFL',None)
  r=Registry.load();self.assertEqual(r.resolve('team','Buffalo',venue=Venue.KALSHI,league='NHL').canonical_id,'NHL:BUF');self.assertIsNone(r.resolve('team','Buffalo',league='NCAAF').canonical_id)
  self.assertIsNone(r.resolve('league','cbb').canonical_id)
 def test_native_id_bindings_are_reviewed_and_conflicts_remain(self):
  data=json.loads((ROOT/'evidence/native-gap-preparation-20260930/participant-bindings.json').read_text());r=Registry.load()
  for row in data['bindings']:
   if row['kind']=='native_role_id':self.assertEqual(r.resolve('team',row['name'],league=row['target'].split(':')[0],venue=Venue.KALSHI,environment='production',native_id=row['native_id']).canonical_id,row['target'])

if __name__=='__main__':unittest.main()

class Boundaries(unittest.IsolatedAsyncioTestCase):
 async def test_global_budget_stop_is_not_swallowed_as_query_failure(self):
  from app.collection.native_selectors import discover_gaps
  from datetime import datetime,timezone
  session=SimpleNamespace(spec=spec(),started_monotonic=time.monotonic(),emit=lambda *a:None)
  d=SimpleNamespace(session=session,clients={'polymarket_us':SimpleNamespace(requests=0)},source_stops={},selection_time=datetime.now(timezone.utc),pages_for=AsyncMock(side_effect=BudgetStop('journal_cap')))
  with self.assertRaisesRegex(BudgetStop,'journal_cap'):await discover_gaps(d,'polymarket_us')
 def test_alias_and_native_id_disagreement_is_conflicting(self):
  r=Registry.load();data=json.loads((ROOT/'evidence/native-gap-preparation-20260930/participant-bindings.json').read_text());x=next(x for x in data['bindings'] if x.get('target')=='NHL:BUF' and x['kind']=='native_role_id')
  self.assertEqual(r.resolve('team','Columbus',league='NHL',venue=Venue.KALSHI,environment='production',native_id=x['native_id']).status,'conflicting')
