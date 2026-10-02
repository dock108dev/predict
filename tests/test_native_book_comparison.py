"""Original native packets, independent decimal oracles and adversarial review gates."""
from copy import deepcopy
from decimal import Decimal as D
import json, unittest, tempfile, socket, subprocess
from pathlib import Path
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
from tests.test_native_book_capture import ROOT,FOLDER,SID,rows
from app.dashboard.session_projection import SessionProjection,stable
from app.dashboard.session_history import load
from app.dashboard.price_comparison import comparisons
from app.dashboard.native_book_comparison import review
from app.dashboard.decision_support import size_report
from app.dashboard.opportunity_history import validate_watch,build_history,observations,WatchStore
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app

def project(records=None):
 p=SessionProjection()
 for r in rows() if records is None else records:p.apply(r)
 return p

def watch(metric='raw_gap'):
 return validate_watch(dict(name='Captured NCAAF',metric=metric,threshold='0',quantity='100',filters={'competition':'NCAAF'}))

class CapturedComparisons(unittest.TestCase):
 def setUp(self):
  for target in ('socket.socket.connect','app.collection.venue_access.load_credentials'):
   p=patch(target,side_effect=AssertionError('offline only'));p.start();self.addCleanup(p.stop)
 def test_independent_orientation_and_prices(self):
  v=load(FOLDER);rs=comparisons(v,{'quantity':'100'});self.assertEqual(len(rs),2)
  by={r['outcome']:r for r in rs}
  # Decimal expectations derived directly from opposite native bids and US Long offers.
  expected={'New Mexico State':{'kalshi':('yes','0.5600','133248.26'),'polymarket_us':('1865333','0.5550','51135.7700')},'Western Kentucky':{'kalshi':('no','0.4500','24685.91'),'polymarket_us':('1865332','0.4500','26183.4300')}}
  for outcome,sources in expected.items():
   for l in by[outcome]['legs']:
    side,ask,size=sources[l['venue']];self.assertEqual(l['side'],side);self.assertEqual(D(l['ask']),D(ask));self.assertEqual(D(l['top_size']),D(size));self.assertEqual(D(l['entry']['notional']),100*D(ask))
  self.assertEqual(D(by['New Mexico State']['raw_difference']),D('.005'));self.assertEqual(D(by['Western Kentucky']['raw_difference']),0)
  self.assertEqual(by['New Mexico State']['lower_raw'],'Polymarket US');self.assertEqual(by['Western Kentucky']['lower_raw'],'Equal')
 def test_independent_native_ladder_transform(self):
  p=project();v=p.snapshot(mode='saved');g=v['games'][0]
  from app.opportunities.board import contracts
  cs=contracts(v['points'][g['id']],g)
  for key,c in cs.items():
   source=c['venue'];b=next(b['book'] for k,b in p.books.items() if k[0]==source)
   if source=='kalshi':
    other='no' if c['side']=='yes' else 'yes';ladder=next(o for o in b['outcomes'] if o['outcome_id']==other)['bids']['levels']
    oracle=sorted([(1-D(l['price']['value']),D(l['quantity']['value'])) for l in ladder])
   else:
    # US adapter's Short ladder is independently checked against the original wire Long bids.
    raw=json.loads(b['raw']['json_text'])['marketData'];short=c['side']=='1865333'
    oracle=sorted([((1-D(l['px']['value']) if short else D(l['px']['value'])),D(l['qty'])) for l in raw['bids' if short else 'offers']])
   self.assertEqual([(D(l['price']),D(l['quantity'])) for l in c['levels']],oracle)
 def test_duplicate_labels_do_not_reverse_outcomes(self):
  b=review()['sources']['kalshi'];self.assertEqual(b['metadata']['yes_sub_title'],b['metadata']['no_sub_title'])
  g=load(FOLDER)['games'][0];self.assertEqual(g['sides']['kalshi:yes']['participant'],'New Mexico State');self.assertEqual(g['sides']['kalshi:no']['predicate'],'not_win')
 def test_structured_ids_resolve_independently_of_subtitles(self):
  from app.normalization.native_registry import native_registry
  registry=native_registry()
  for venue,native,target in [('kalshi','7a77c54f-511d-4bcd-a4d5-7e84ea5eda89','NCAAF:NCAA472'),('polymarket_us','1167','NCAAF:NCAA772'),('polymarket_us','1309','NCAAF:NCAA472')]:
   resolution=registry.resolve('team',league='NCAAF',venue=venue,environment='production',native_id=native)
   self.assertEqual(resolution.canonical_id,target)
 def test_mutated_orientation_or_evidence_fails_closed(self):
  for source,change in [('kalshi',lambda m:m['custom_strike'].update(football_team='wrong')),('kalshi',lambda m:m.update(rules_primary='Western Kentucky wins')),('polymarket_us',lambda m:m['marketSides'][0].update(long=False)),('polymarket_us',lambda m:m['marketSides'][0].update(teamId=1309))]:
   p=project();b=review()['sources'][source];m=next(m for m in p.inventory[source]['markets'] if m['id']==b['market_id']);change(m['native_metadata'])
   v=p.snapshot(mode='saved');self.assertFalse(v['games']);self.assertIn(source,v['native_comparison_review']['rejections'])
  p=project();next(iter(p.metadata.values()))['market']['raw']['json_text']='{}';self.assertFalse(p.snapshot(mode='saved')['games'])
 def test_settlement_and_fee_scopes(self):
  for r in comparisons(load(FOLDER),{'quantity':'100'}):
   self.assertEqual(r['settlement_status'],'INCOMPATIBLE');self.assertFalse(r['settlement_audit']['qualified']);self.assertIsNone(r['net']);self.assertIsNone(r['ev'])
   k,u=r['legs'];self.assertIsNone(k['entry']['upper'])
   q=D('100');price=D(k['ask']);raw=D('.07')*q*price*(1-price)
   from decimal import ROUND_CEILING,ROUND_HALF_EVEN
   fee=raw.quantize(D('.01'),rounding=ROUND_CEILING)
   self.assertEqual(D(k['entry']['conditional_fee_scenario']['entry_cash_requirement']),q*price+fee)
   price=D(u['ask']);bound=(D('.0695')*q*price*(1-price)).quantize(D('.01'),rounding=ROUND_HALF_EVEN)
   self.assertEqual(D(u['entry']['upper']),q*price+bound);self.assertEqual(D(u['entry']['lower']),q*price)
 def test_old_source_image_and_health_emissions(self):
  p=SessionProjection();old_id=None;seen=False
  for row in rows():
   p.apply(row)
   if row['type']!='prediction_book':continue
   v=p.snapshot(mode='saved');rs=comparisons(v,{'quantity':'1'})
   if not rs:continue
   u=next(l for l in rs[0]['legs'] if l['venue']=='polymarket_us')
   if row['source']=='polymarket_us' and (row.get('native_observation') or {}).get('classification')=='initial_snapshot':
    self.assertGreater(D(u['source_to_receipt_seconds']),D('106.49'));self.assertFalse(u['source_time_eligible']);old_id=u['book_id'];seen=True
    self.assertTrue(all(not x['qualifies'] for x in observations(v,watch())))
   elif row['source']=='polymarket_us' and not row.get('native_observation') and old_id:
    self.assertEqual(u['book_id'],old_id)
   if row['source']=='polymarket_us' and row.get('native_observation'):old_id=u['book_id']
  self.assertTrue(seen)
 def test_history_excludes_stale_and_net_and_preserves_counts(self):
  for metric in ('raw_gap','arb_return','ev'):
   r=build_history(FOLDER,[watch(metric)]);self.assertTrue(r['coverage']['complete']);self.assertFalse(r['events']);self.assertTrue(r['items'])
   for item in r['items']:self.assertFalse(item['active']);self.assertEqual(item['qualifying_observations'],0)
  b=r['items'][0]['basis']['observations'];self.assertTrue(all(l['observation']['counts']=={'initial_snapshot':1,'price_or_quantity_change':1} for l in b))
 def test_sizing_and_net_ranking_exclusions(self):
  from app.dashboard.product_view import dashboard
  v=load(FOLDER);g=v['games'][0];r=size_report(v,g,{'sizes':['1','100','.01','100000000']})
  self.assertTrue(all(x['entry']['upper'] is not None for x in r['sizes'][2]['acquisitions'] if x['venue']=='polymarket_us'))
  self.assertIsNone(r['best']);self.assertTrue(all(not x['candidates'] for x in r['sizes']));self.assertTrue(all(x['entry']['notional'] is None for x in r['sizes'][-1]['acquisitions']))
  for view in ('arb','ev'):self.assertEqual(dashboard(v,dict(view=view),{}),[])
 def test_fresh_process_derived_reopen_and_original_preservation(self):
  original=json.loads((ROOT/'evidence/native-books-derived-20260930-v1/saved-projection-v1.json').read_text());self.assertFalse(original['games'])
  code="from tests.test_native_book_comparison import *; socket.socket.connect=lambda *a:(_ for _ in ()).throw(AssertionError('offline')); print(stable(load(FOLDER)))"
  self.assertEqual(subprocess.check_output([str(ROOT/'.venv/bin/python'),'-c',code],cwd=ROOT,text=True).strip(),stable(load(FOLDER)))

class OrdinaryPath(unittest.IsolatedAsyncioTestCase):
 async def test_dashboard_details_sizing_history_download(self):
  original=socket.socket.connect
  def guarded(sock,address):
   if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1'):raise AssertionError('external intercepted')
   return original(sock,address)
  with tempfile.TemporaryDirectory() as d,patch('socket.socket.connect',guarded),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('no credentials')):
   p=Path(d);owner=CoverageOwner(p/'saved',pilot_output=p/'unused',product_mode=True);owner.history_paths=lambda:{SID:FOLDER}
   w=p/'watches.json';WatchStore(w).save([{k:v for k,v in watch().items() if k!='id'}])
   async with TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=w))) as client:
    response=await client.get('/api/dashboard?view=feed&capture='+SID);self.assertEqual(response.status,200);data=await response.json();self.assertEqual(len(data['comparisons']),2)
    r=data['comparisons'][0];q={k:r[k] for k in ('session','hash','cutoff')}
    response=await client.get('/api/calculate',params=q);self.assertEqual(response.status,200);detail=await response.json();self.assertTrue(detail['native_raw']);self.assertFalse(detail['aggregated'])
    response=await client.get('/api/calculate',params=dict(q,download='true'));self.assertEqual(response.status,200);self.assertIn('attachment',response.headers['Content-Disposition']);self.assertEqual(await response.json(),detail)
    response=await client.post('/api/decision-sizes',headers={'Origin':str(client.make_url('')).rstrip('/')},json=dict(q,sizes=['1','100'],quantity='100'))
    # Unknown controls are rejected; then use the supported ordinary schema.
    self.assertEqual(response.status,422)
    response=await client.post('/api/decision-sizes',headers={'Origin':str(client.make_url('')).rstrip('/')},json=dict(q,sizes=['1','100']));self.assertEqual(response.status,200);self.assertIsNone((await response.json())['best'])
    response=await client.post('/api/math-scenario',headers={'Origin':str(client.make_url('')).rstrip('/')},json=q);self.assertEqual(response.status,200);math=await response.json();self.assertFalse(math['references']['estimates'])
    response=await client.get('/api/math-scenario-download',params={'sha256':math['sha256']});self.assertEqual(response.status,200);self.assertEqual(await response.json(),math)
    response=await client.get('/api/opportunity-history',params={'capture':SID,'download':'true'});self.assertEqual(response.status,200);self.assertIn('attachment',response.headers['Content-Disposition']);self.assertFalse((await response.json())['events']);self.assertFalse(owner.active())
