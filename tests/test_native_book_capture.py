"""Offline regressions of the immutable once-authorized September 30 capture."""
import base64, hashlib, json, socket, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from app.collection.transport_session import reopen
from app.collection.native_book_report import summarize
from app.dashboard.session_history import load
from app.dashboard.coverage_owner import replay_groups, CoverageOwner
from app.dashboard.multi_game_server import create_app
ROOT=Path(__file__).resolve().parents[1]
SID='3363b035-4a97-43df-bae8-57426e873514'
FOLDER=ROOT/'evidence/native-books-attempt-0ca80de2-d6ef-4867-8c5d-4a4c9392b751'/SID
JOURNAL=FOLDER/(SID+'.jsonl')
EXPECTED='ec133aca72d787fd9d9d0d124370e964385e6ac3083f5cd5215b9b26e4075db4'
def stable(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def rows():return reopen(JOURNAL)['rows']
def frames(source):return [json.loads(base64.b64decode(r['body_b64'])) for r in rows() if r['type']=='prediction_frame' and r['source']==source]
class Captured(unittest.TestCase):
 def setUp(self):
  self.net=patch('socket.socket.connect',side_effect=AssertionError('offline only'));self.net.start();self.addCleanup(self.net.stop)
  self.creds=patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('no credentials'));self.creds.start();self.addCleanup(self.creds.stop)
 def test_original_and_exact_replay(self):
  self.assertEqual(reopen(JOURNAL)['sha256'],'265f68c6c79b7b2c19be0fa8fb2ba7c303cc9daf94fae180585feb9590fb0248')
  result=replay_groups(reopen(JOURNAL))
  for venue in ('kalshi-1','polymarket_us-1'):
   self.assertTrue(result[venue]['exact_packets']);self.assertEqual(result[venue]['gaps'],[])
 def test_selection_http_and_exact_commands(self):
  rs=rows();http=[r for r in rs if r['type']=='prediction_discovery_http']
  self.assertEqual([(r['source'],r['path']) for r in http],[('polymarket_us','/v1/events'),('kalshi','/trade-api/v2/events'),('kalshi','/trade-api/v2/markets')])
  self.assertTrue(all(r['complete'] and r['status']==200 for r in http))
  cmds={r['source']:json.loads(r['body']) for r in rs if r['type']=='prediction_command'}
  self.assertEqual(cmds['kalshi']['params'],dict(channels=['orderbook_delta'],market_tickers=['KXNCAAFGAME-26OCT01WKUNMSU-NMSU']))
  self.assertEqual(cmds['polymarket_us']['subscribe']['marketSlugs'],['aec-cfb-wkent-nmxst-2026-10-01'])
  sel=next(r for r in rs if r['type']=='native_book_selection' and r['source']=='polymarket_us')
  self.assertEqual(sel['metadata'],'embedded_complete')
 def test_actual_quantity_changes_not_price_changes(self):
  report=summarize(rows())
  for s in report['sources'].values():
   self.assertEqual(s['accepted'],{'initial_snapshot':1,'price_or_quantity_change':1})
   self.assertEqual(s['price_level_changes'],0);self.assertEqual(s['quantity_changes'],1)
   self.assertFalse(s['recovery_comparisons']);self.assertFalse(s['stream_diagnostics'])
  k=frames('kalshi');self.assertEqual([x.get('seq') for x in k],[None,1,2])
  self.assertEqual(k[2]['msg']['price_dollars'],'0.0500');self.assertEqual(k[2]['msg']['delta_fp'],'-1.00')
  p=frames('polymarket_us');self.assertEqual(p[0]['requestId'],p[1]['requestId'])
  ladder=lambda x:{v['px']['value']:v['qty'] for v in x['marketData']['bids']}
  a,b=map(ladder,p);self.assertEqual({v:(a[v],b[v]) for v in a if a[v]!=b[v]},{'0.4350':('2705.0000','2142.0000')})
  self.assertEqual(p[0]['marketData']['offers'],p[1]['marketData']['offers'])
  self.assertEqual(p[0]['marketData']['transactTime'],'2026-09-30T14:50:06.584556100Z')
 def test_saved_scope_stop_and_health_not_observation(self):
  v=load(FOLDER);self.assertTrue(all(g.get('native_raw') for g in v['games']));self.assertEqual(len(v['market_catalog']),3)
  self.assertEqual(sum('book_evidence' in m for m in v['market_catalog']),2)
  r=json.loads((FOLDER/'report.json').read_text());self.assertTrue(r['cleanup_complete']);self.assertEqual(r['health']['kalshi'],'disconnected');self.assertEqual(r['health']['polymarket_us'],'disconnected')
  books=[r for r in rows() if r['type']=='prediction_book'];self.assertEqual(len(books),7);self.assertEqual(sum(bool(r.get('native_observation')) for r in books),4)
 def test_exact_saved_fresh_process(self):
  self.assertEqual(stable(json.loads((ROOT/'evidence/native-books-derived-20260930-v1/saved-projection-v1.json').read_text())),EXPECTED)
  code="from tests.test_native_book_capture import *; socket.socket.connect=lambda *a,**k:(_ for _ in ()).throw(AssertionError('offline')); print(stable(load(FOLDER)))"
  self.assertEqual(subprocess.check_output([str(ROOT/'.venv/bin/python'),'-c',code],cwd=ROOT,text=True).strip(),stable(load(FOLDER)))
class SavedRoute(unittest.IsolatedAsyncioTestCase):
 async def test_ordinary_saved_dashboard(self):
  original=socket.socket.connect
  def guarded(sock,address):
   if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1'):raise AssertionError('external access intercepted')
   return original(sock,address)
  with tempfile.TemporaryDirectory() as d,patch('socket.socket.connect',guarded),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('no credentials')):
   p=Path(d);owner=CoverageOwner(p/'saved',pilot_output=p/'unused',product_mode=True)
   owner.history_paths=lambda:{SID:FOLDER}
   async with TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=p/'watches.json'))) as client:
    response=await client.get('/api/dashboard?view=feed&capture='+SID);self.assertEqual(response.status,200)
    data=await response.json();self.assertEqual(len(data['market_catalog']),3)
    self.assertEqual(sum('book_evidence' in m for m in data['market_catalog']),2)
    self.assertFalse(owner.active())
