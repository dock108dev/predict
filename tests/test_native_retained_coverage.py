"""Real retained source corpus; fixtures remain in test_native_reviews separately."""
from pathlib import Path
from copy import deepcopy
from decimal import Decimal as D
import json,socket,tempfile,unittest,subprocess
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
from app.dashboard.session_projection import SessionProjection,stable
from app.dashboard.session_history import load,verified
from app.dashboard.price_comparison import comparisons,comparisons_for_game
from app.dashboard.native_reviews import DIRECTORY,records,historical_paths
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
from app.dashboard.opportunity_history import WatchStore,validate_watch,observations
ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'evidence/native-retained-coverage-20260930-v1'
SID='860107f6-56ff-44fe-9fd0-088ceaabe2a6'
FOLDER=ROOT/'evidence/supervised-capacity-run-860107f6-56ff-44fe-9fd0-088ceaabe2a6'/SID
NFL={'KXNFLGAME-26OCT04ARINYG':('118974','960579','1920642','1920643',{'NFL:ARI','NFL:NYG'}),'KXNFLGAME-26OCT04INDWAS':('118973','960578','1920640','1920641',{'NFL:IND','NFL:WAS'}),'KXNFLGAME-26SEP28PHICHI':('112325','848861','1697210','1697211',{'NFL:PHI','NFL:CHI'}),'KXNFLGAME-26OCT01PITCLE':('115743','919543','1838570','1838571',{'NFL:PIT','NFL:CLE'})}

def projection(folder=FOLDER):
 p=SessionProjection()
 for r in verified(folder)['rows']:p.apply(r)
 return p

def watch():return validate_watch(dict(name='Retained NFL prices',metric='raw_gap',threshold='0',quantity='1',filters={'competition':'NFL'}))

class RetainedReviews(unittest.TestCase):
 def test_archives_do_not_override_ordinary_saved_default(self):
  with tempfile.TemporaryDirectory() as d:
   owner=CoverageOwner(Path(d)/'saved',pilot_output=Path(d)/'unused',product_mode=True)
   with patch('app.dashboard.native_reviews.historical_paths',return_value={'archive':Path(d)/'archive','duplicate':Path(d)/'old'}),patch('app.dashboard.session_history.list_sessions',return_value={'duplicate':Path(d)/'new','ordinary':Path(d)/'ordinary'}):
    paths=owner.history_paths();self.assertEqual(list(paths),['archive','duplicate','ordinary']);self.assertEqual(paths['duplicate'],Path(d)/'new')
 def test_four_actual_events_eight_cards_and_separate_alternatives(self):
  p=projection();v=p.snapshot();rs=comparisons(v,{});self.assertEqual(len(v['games']),8);self.assertEqual(len(rs),8)
  self.assertEqual({g['sources']['kalshi']['event_id'] for g in v['games']},set(NFL))
  for g in v['games']:
   k,u=g['sources']['kalshi'],g['sources']['polymarket_us'];expected=NFL[k['event_id']];self.assertEqual((u['event_id'],u['market_id']),(expected[0],expected[1]));r=g['native_review']['record'];self.assertEqual(set(r['participants']),expected[4]);self.assertEqual(set(r['sources']['polymarket_us']['outcomes']),set(expected[2:4]))
   native=r['sources']['kalshi']['metadata'];self.assertEqual(native['ticker'],k['market_id']);self.assertEqual(native['event_ticker'],k['event_id']);self.assertIn('then the market resolves to Yes.',native['rules_primary'])
   self.assertEqual(native['yes_sub_title'],native['no_sub_title'])
   self.assertEqual(len(comparisons_for_game(v,{},g['id'])),2)
  for r in rs:
   self.assertEqual(len(r['alternatives']),1);self.assertNotEqual(r['native_review']['binding_sha256'],r['alternatives'][0]['native_review']['binding_sha256']);self.assertIsNone(r['net']);self.assertIsNone(r['ev'])
   self.assertTrue(all(l['entry']['fee_status']=='UNKNOWN' and l['entry']['upper'] is None for l in r['legs']))
 def test_prices_and_whole_depth_match_independent_wire_oracle(self):
  oracle=json.loads((EVIDENCE/'oracles'/(SID+'.json')).read_text());v=load(FOLDER)
  for g in v['games']:
   for r in comparisons_for_game(v,{},g['id']):
    for l in r['legs']:
     n=l['native_identity'];key='|'.join((l['venue'],n['event_id'],n['market_id']));expected=oracle['latest_purchases'][key][l['side']]
     self.assertEqual([(D(x['price']),D(x['quantity'])) for x in l['levels']],[(D(x['price']),D(x['quantity'])) for x in expected])
     self.assertEqual(D(l['ask']),D(expected[0]['price']));self.assertEqual(D(l['top_size']),D(expected[0]['quantity']))
 def test_missing_tampered_metadata_and_other_event_isolation(self):
  p=projection();p.spec['native_review_records']=[];self.assertFalse(p.snapshot()['games'])
  p=projection();rr,_=records(p);p.native_reviews={str(i):deepcopy(r) for i,r in enumerate(rr)};p.native_reviews['0']['sources']['kalshi']['metadata']['title']='tampered';v=p.snapshot();self.assertEqual(len(v['games']),7);self.assertTrue(v['native_comparison_review']['errors'])
  p=projection();e=p.inventory['kalshi']['events'][0];e['native_metadata']['title']='later revision';v=p.snapshot();self.assertLess(len(v['games']),8);self.assertGreater(len(v['games']),0)
  p=projection();key=next(k for k in p.books if k[0]=='polymarket_us');p.books.pop(key);v=p.snapshot();self.assertEqual(len(v['games']),6);self.assertEqual(sum(a.get('status')=='METADATA_ONLY' for a in v['native_comparison_review']['assessments'].values()),2)
 def test_metadata_only_gap_records_and_distinct_actual_terms(self):
  folder=historical_paths()['d923a237-b03c-4869-a4db-d4d48ad242d2'];v=load(folder);self.assertFalse(v['games']);a=v['native_comparison_review'];self.assertEqual(sum(x.get('status')=='METADATA_ONLY' for x in a['assessments'].values()),4)
  self.assertEqual(len(a['records']),4)
  for r in a['records'].values():
   self.assertEqual(r['settlement_assessment']['status'],'INCOMPATIBLE');self.assertFalse(r['settlement_assessment']['qualified']);self.assertTrue(all(s['fee_review']['status']=='UNKNOWN' for s in r['sources'].values()))
   terms=r['sources']['polymarket_us']['metadata']['description'];self.assertIn('two calendar days' if r['identity']['competition']=='NHL' else 'two weeks',terms)
  self.assertTrue(any(m.get('native_review_assessments') for m in v['market_catalog']))
 def test_metadata_revisions_cutoffs_and_old_short_derivation(self):
  folder=historical_paths()['75ec21c1-5962-48e1-96e2-5f6b5ef07150'];p=SessionProjection();seen=set();priced=0;last_token=None
  for row in verified(folder)['rows']:
   p.apply(row)
   if row['type']!='prediction_book':continue
   v=p.snapshot();rs=comparisons(v,{});self.assertFalse(v['native_comparison_review']['errors'])
   if not rs:continue
   priced+=1;seen.add(rs[0]['native_review']['record']['revision']);last_token=v['durable_cursor']
   for r in rs:
    for l in r['legs']:
     self.assertLessEqual(l['received_at'],v['last_update']);self.assertTrue(l['ask'] is not None)
     if l['venue']=='polymarket_us' and l['native_outcome']['native_direction']=='short':
      raw=json.loads(l['original_native_input']['json_text'])['marketData'];self.assertEqual(D(l['ask']),1-max(D(x['px']['value']) for x in raw['bids']))
  self.assertGreater(priced,0);self.assertEqual(seen,{1,2,3});self.assertEqual(stable(load(folder,last_token)),stable(load(folder,last_token)))
 def test_cutoff_is_exact_and_references_never_supply_books(self):
  p=SessionProjection();token=None;prefix=None
  for row in verified(FOLDER)['rows']:
   p.apply(row)
   if row['type']=='prediction_book' and len(p.books)==12:
    prefix=p.snapshot();token=prefix['durable_cursor'];break
  self.assertTrue(prefix['games']);later=load(FOLDER,token);self.assertEqual(prefix['points'],later['points']);self.assertEqual(prefix['games'],later['games'])
  p=projection();v=p.snapshot();reference=projection(historical_paths()['pinnacle-nfl-retained-20260921']);p.references=deepcopy(reference.references)
  # Reference storage is a separate namespace and cannot satisfy a missing prediction book.
  p.books.clear();self.assertFalse(p.snapshot()['games'])
 def test_raw_watches_keep_unknown_clock_qualification_separate(self):
  p=projection();p.finished=None
  for row in observations(p.snapshot(),watch()):self.assertFalse(row['qualifies'])
 def test_independent_origins_and_reference_roles_are_required(self):
  p=projection();p.inventory['polymarket_us']['origin_id']='kalshi';self.assertFalse(p.snapshot()['games'])
  p=projection();p.inventory['polymarket_us']['role']='reference';self.assertFalse(p.snapshot()['games'])
 def test_original_failure_kept_and_r4_excluded_catalog_repaired(self):
  folder=historical_paths()['ea3936a3-8e9f-4557-b4be-ae7a56b98f73']
  with self.assertRaisesRegex(ValueError,'projection market bound'):load(folder,native_interpretation='native-book-comparison-3')
  v=load(folder);self.assertFalse(any(g.get('native_raw') for g in v['games']));source=next(s for s in v['sources'] if s['source_id']=='polymarket_us');self.assertEqual(len(source['catalog']['excluded_catalog']['markets']),1841)
 def test_sealed_v3_reopens_original_corpus_exactly(self):
  audit=json.loads((EVIDENCE/'sessions'/(SID+'.json')).read_text());self.assertEqual(stable(load(FOLDER,native_interpretation='native-book-comparison-3')),audit['original_projection_sha256'])
 def test_default_history_exposes_reviewed_real_sessions(self):
  with tempfile.TemporaryDirectory() as d:
   owner=CoverageOwner(Path(d)/'saved',pilot_output=Path(d)/'unused',product_mode=True);self.assertEqual(set(owner.history_paths()) & set(historical_paths()),set(historical_paths()))

class RetainedRoutes(unittest.IsolatedAsyncioTestCase):
 async def test_all_eight_native_contracts_details_sizes_download_and_review_export(self):
  original=socket.socket.connect
  def local(sock,address):
   if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1'):raise AssertionError('No provider network')
   return original(sock,address)
  with tempfile.TemporaryDirectory() as d,patch('socket.socket.connect',local),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
   root=Path(d);owner=CoverageOwner(root/'saved',pilot_output=root/'unused',product_mode=True);owner.history_paths=lambda:{SID:FOLDER};w=root/'watches.json';WatchStore(w).save([{k:v for k,v in watch().items() if k!='id'}])
   async with TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=w))) as client:
    response=await client.get('/api/dashboard',params={'view':'feed','capture':SID});self.assertEqual(response.status,200);data=await response.json();self.assertEqual(len(data['comparisons']),8)
    variants={r['game_id']:r for p in data['comparisons'] for r in [p,*p['alternatives']]};self.assertEqual(len(variants),8)
    for r in variants.values():
     q={k:r[k] for k in ('session','hash','cutoff')};response=await client.get('/api/calculate',params=q);self.assertEqual(response.status,200);detail=await response.json();self.assertEqual(len(detail['comparisons']),2);self.assertEqual(detail['native_review']['binding_sha256'],r['native_review']['binding_sha256'])
     response=await client.get('/api/calculate',params=dict(q,download='true'));self.assertEqual(await response.json(),detail)
     response=await client.post('/api/decision-sizes',headers={'Origin':str(client.make_url('')).rstrip('/')},json=dict(q,sizes=['1','100']));self.assertEqual(response.status,200);self.assertIsNone((await response.json())['best'])
    response=await client.get('/api/native-reviews',params=dict(capture=SID,cutoff=data['durable_cursor'],download='true'));self.assertEqual(response.status,200);export=await response.json();digest=export.pop('sha256');self.assertEqual(digest,stable(export));self.assertEqual(len(export['review']['records']),8)
    response=await client.get('/api/opportunity-history',params=dict(capture=SID,download='true'));self.assertEqual(response.status,200);report=await response.json();self.assertFalse(report['events']);self.assertEqual(len(report['items']),8)
