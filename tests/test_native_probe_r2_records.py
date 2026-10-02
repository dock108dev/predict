"""Complete r2 records are source evidence; truncated bytes stay inadmissible."""
import base64,json,unittest
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
from copy import deepcopy
from app.collection import native_selectors as ns,coverage,catalog_metadata
from app.collection.continuous import Discovery
from app.collection.acquisition_policy import native_caps
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/native-probe-r2-derived-20260930-v1'
def pages():return json.loads((OUT/'captured-pages.json').read_text())
def spec():return json.loads((ROOT/'evidence/native-discovery-probe-r2-20260930/run-spec.json').read_text())
AT=datetime.fromisoformat('2026-09-30T04:14:43.673417+00:00')
class Records(unittest.TestCase):
 def test_league_identifier_complete_evidence_not_division(self):
  leagues=[l for p in pages() if p['path']=='/v2/leagues' and p['complete'] for l in json.loads(base64.b64decode(p['body_b64']))['leagues']]
  row=next(l for l in leagues if l['slug']=='cbb');self.assertEqual((row['id'],row['sportId'],row['tagId']),(4,1,8));self.assertTrue(any(l['slug']=='wcbb' for l in leagues))
  self.assertEqual(ns.query('polymarket_us','NCAAB')[1]['tagSlug'],'cbb')
  self.assertEqual(native_caps(spec()),dict(kalshi=36,polymarket_us=34))
 def test_kickoffs_change_selection_without_inferred_ticker_dates(self):
  expected={'NFL':'KXNFLGAME-26OCT01PITCLE','NCAAF':'KXNCAAFGAME-26OCT01WKUNMSU','MLB':'KXMLBGAME-26SEP301400PHIATL','NHL':'KXNHLGAME-26SEP30NYITOR'}
  for sport,eid in expected.items():
   games,_=ns.candidates(pages(),'kalshi',sport,AT);self.assertEqual(games[0]['id'],eid);self.assertIsNotNone(games[0]['scheduled_start'])
  games,excluded=ns.candidates(pages(),'kalshi','NBA',AT);self.assertFalse(games);self.assertEqual(len(excluded),3)
 def test_catalog_projects_and_market_parent_is_present(self):
  d=Discovery(SimpleNamespace(spec=spec()));d.pages=pages();cats,markets=d.project()
  self.assertTrue(markets['kalshi']);self.assertTrue(cats['polymarket_us']['events'])
  for c in cats.values():
   ids={e['id'] for e in c['events']}
   self.assertTrue(all(m['event_id'] in ids for m in c['markets']))
  self.assertTrue(any(e['id']=='KXMLBGAME-26SEP301400PHIATL' and len(e['participants'])==2 for e in cats['kalshi']['events']))
 def test_unresolved_parent_compacts_market_without_discarding_source(self):
  c={'events':[dict(id='e',identity='unresolved',exclusion=None,provenance=[dict(body_sha256='hash',path='/events',received_at='at')])], 'markets':[dict(id='m',event_id='e',exclusion=None,provenance=[dict(body_sha256='hash',path='/events',received_at='at')])]}
  catalog_metadata.compact(c,'kalshi');self.assertEqual(c['markets'],[]);self.assertEqual(c['excluded_catalog']['markets'][0][3],'unresolved_parent_event')
 def test_truncated_cfb_is_not_repaired_or_admitted(self):
  p=next(p for p in pages() if not p['complete']);self.assertEqual(len(base64.b64decode(p['body_b64'])),2*1024*1024)
  with self.assertRaises(ValueError):coverage.decode_page(p)
  accepted,state=coverage.traversal([p],'polymarket_us','events');self.assertFalse(accepted);self.assertEqual(state['state'],'failed')
 def test_missing_milestone_does_not_create_schedule(self):
  p=next(p for p in pages() if p['source']=='kalshi' and p['params'].get('series_ticker')=='KXNHLGAME')
  from app.adapters import kalshi
  b=base64.b64decode(p['body_b64']).decode();data=json.loads(b);e=data['events'][0];data['milestones']=[]
  r=kalshi.Response(json.dumps(data),'offline',AT);self.assertIsNone(kalshi.parse_event(r,e,'KXNHLGAME').scheduled_start)

if __name__=='__main__':unittest.main()
