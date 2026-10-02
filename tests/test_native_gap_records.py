"""Original complete gap-probe bytes; mutations below are explicit negative controls."""
import base64,json,unittest
from pathlib import Path
from datetime import datetime,timedelta
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from app.collection.native_selectors import candidates,gap_market_query
from app.collection.continuous import Discovery
from app.adapters.polymarket_us import event_game_binding,PolymarketUSAdapter,Response
from app.normalization.native_registry import native_registry
from app.normalization.registry import Registry
ROOT=Path(__file__).resolve().parents[1];D=ROOT/'evidence/native-gap-derived-20260930-v1'
def pages():return json.loads((D/'captured-pages.json').read_text())
def at():return datetime.fromisoformat(pages()[0]['params']['startTimeMin'])-timedelta(minutes=5)
def events():return [(p,e) for p in pages() if p['source']=='polymarket_us' for e in json.loads(base64.b64decode(p['body_b64'])).get('events',[])]
class Captured(unittest.TestCase):
 def test_cfb_payload_complete_and_bounded_empty_findings(self):
  p=pages()[0];self.assertTrue(p['complete']);self.assertEqual(len(base64.b64decode(p['body_b64'])),13774)
  for sport in ('NBA','NCAAB'):self.assertEqual(candidates(pages(),'polymarket_us',sport,at()),([],[]))
 def test_nhl_missing_gameid_ancillary_team_does_not_define_pair(self):
  games,ex=candidates(pages(),'polymarket_us','NHL',at());self.assertFalse(ex);self.assertEqual([e['id'] for e in games],['127796','127804'])
  self.assertTrue(all(e['game_id'] is None for e in games));self.assertTrue(all('slug' in gap_market_query('polymarket_us',e) for e in games))
  p,e=next(x for x in events() if x[1]['id']=='127804');bound=event_game_binding(e,'nhl');self.assertEqual(bound['ignored_team_ids'],['1499']);self.assertEqual({t['id'] for t in bound['teams']},{1494,1490})
 def test_explicit_roles_and_conflicting_sides(self):
  for p,e in events():
   bound=event_game_binding(e,p['params']['tagSlug']);self.assertEqual({t['ordering'] for t in bound['teams']},{'home','away'})
   wrong=deepcopy(e);wrong['markets'][0]['marketSides'][0]['teamId']=987654
   with self.assertRaises(ValueError):event_game_binding(wrong,p['params']['tagSlug'])
   wrong=deepcopy(e);wrong['markets'][0]['marketSides'][0]['team']['ordering']='home'
   with self.assertRaises(ValueError):event_game_binding(wrong,p['params']['tagSlug'])
 def test_college_entities_reused_and_cbb_unqualified(self):
  r=native_registry();original=json.loads((ROOT/'app/normalization/college-2026-27.json').read_text())
  extra=json.loads((ROOT/'app/normalization/native-gap-bindings-20260930.json').read_text())
  self.assertEqual(len(extra['entities']),10)
  for entity in extra['entities']:self.assertEqual(r.entities[entity['id']],next(x for x in original['entities'] if x['id']==entity['id']))
  self.assertIsNone(r.resolve('league','cbb').canonical_id)
  data=json.loads((D/'participant-bindings-v1.json').read_text())
  for x in data['bindings']:self.assertEqual(r.resolve('team',x['name'],league=x['target'].split(':')[0],venue=x['venue'],environment='production',native_id=x['native_id']).canonical_id,x['target'])
  self.assertEqual(r.resolve('team','Flyers',league='NHL',venue='polymarket_us',environment='production',native_id='1497').status,'conflicting')
 def test_catalog_binds_embedded_markets_preserves_empty_lookup_contradiction(self):
  d=Discovery(SimpleNamespace(spec=json.loads((ROOT/'evidence/native-gap-probe-20260930/run-spec.json').read_text())));d.pages=pages();cats,ms=d.project();us=cats['polymarket_us']
  self.assertEqual({e['id'] for e in us['events']},{'116584','127796','127804','129551'})
  self.assertEqual(len(us['markets']),4);self.assertTrue(all(m['period']=='full_game' and m['exclusion'] is None for m in us['markets']))
  for e in us['events']:
   if e['id'] in ('116584','129551'):self.assertEqual(e['market_discovery'],'contradictory_listings')
  self.assertTrue(all(m['event_id'] in {e['id'] for e in cats[v]['events']} for v in cats for m in cats[v]['markets']))
 def test_slug_query_cannot_bind_foreign_market(self):
  from app.collection.coverage import catalog
  from hashlib import sha256
  p,e=events()[0];m=deepcopy(e['markets'][0]);m['id']='999999'
  raw=json.dumps({'markets':[m]}).encode();page=dict(p,path='/v1/markets',params={'slug':[m['slug']],'limit':5,'offset':0},body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest())
  cat=catalog([p,page],'polymarket_us',at());self.assertNotIn('999999',[m['id'] for m in cat['markets']]);self.assertTrue(any('999999' in row for row in cat['excluded_catalog']['markets']))
class AdapterLookup(unittest.IsolatedAsyncioTestCase):
 async def test_ordinary_adapter_uses_retained_embedded_metadata_without_invented_game_id(self):
  # Direct adapter hydration uses unchanged retained event bytes. No market HTTP
  # response is invented: discover_markets() exposes captured embedded records.
  for p,e in events():
   class RetainedClient:
    async def get(self,url,params=None,**kw):
     import httpx
     return httpx.Response(200,content=base64.b64decode(p['body_b64']),request=httpx.Request('GET',url))
   adapter=PolymarketUSAdapter(client=RetainedClient(),max_pages=1,page_size=1)
   with patch('socket.socket.connect',side_effect=AssertionError('No provider access')):
    found=await adapter.discover_events(league=None);self.assertEqual(len(found),1)
    markets=await adapter.discover_markets(e['id']);self.assertEqual({m.raw.ref.market_id for m in markets},{m['id'] for m in e['markets']})
   self.assertTrue(all(m.raw.ref.event_id==e['id'] for m in markets))
if __name__=='__main__':unittest.main()
