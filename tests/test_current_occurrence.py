"""Retained exact receipts plus labeled controlled identity/quote variants."""
import asyncio,json,unittest
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from app.collection import coverage
from app.collection.current_occurrence import annotate,load,PATH
from app.collection.current_policy import DEFAULT
from app.collection.current_service import CurrentService
from app.collection.current_sink import LatestStateSink,utc
from app.dashboard.current_state import CurrentStore
from tests.test_current_state import request

P=Path(__file__).resolve().parent/'fixtures/current-colts-commanders-retained.json'
def catalogs():
 return json.loads(P.read_text())['catalogs']

def target(cat,v):return next(e for e in cat['events'] if e['id']==load()['sources'][v]['event_id'])

def book(v,m,at):
 sides=m['sides']
 return dict(raw=dict(ref=dict(venue=v,event_id=m['event_id'],market_id=m['id']),kind='observation',received_at=at,exchange_at=at,json_text='{}'),outcomes=[dict(outcome_id=s['id'],asks=dict(depth='full',levels=[dict(price=dict(value='.48' if i==0 else '.53'),quantity=dict(value='5',unit='contracts'))]),bids=None) for i,s in enumerate(sides)],state='active',sync='synchronized',sequence='1',quantity_unit='contracts')

class Occurrence(unittest.TestCase):
 def setUp(self):
  clock=patch('app.collection.current_occurrence.datetime');self.clock=clock.start();self.clock.now.return_value=datetime(2026,10,3,14,tzinfo=timezone.utc);self.addCleanup(clock.stop)
 def test_positive_exact_occurrence_and_original_release_evidence(self):
  for v,c in catalogs().items():
   annotate(c,v);e=target(c,v)
   self.assertEqual(e['game_id'],'aa29dd21-4feb-11f1-abca-2c54536568a9')
   self.assertEqual(e['original_start'],load()['event']['original_start'])
   self.assertTrue(all(m.get('direct_win_binding') for m in c['markets'] if m['event_id']==e['id']))
 def test_conflicts_withhold_binding(self):
  for kind in ('schedule','roles','rematch','original','rescheduled','outcome','orientation','predicate','hash','milestone','instrument','event_id','expired'):
   with self.subTest(kind=kind):
    v='kalshi' if kind=='milestone' else 'polymarket_us';c=catalogs()[v];e=target(c,v);m=next(m for m in c['markets'] if m['event_id']==e['id']);n=m['_native']
    if kind=='schedule':e['scheduled_start']='2026-10-05T13:30:00+00:00'
    if kind=='roles':e['home']='NFL:IND';e['away']='NFL:WAS'
    if kind=='rematch':e['_native']['gameId']=19503
    if kind=='original':e['original_start']='2026-10-03T13:30:00+00:00'
    if kind=='rescheduled':e['_native']['rescheduledFromGameId']=19501
    if kind=='outcome':n['marketSides'][0]['id']='wrong'
    if kind=='orientation':n['marketSides'][0]['long']=False
    if kind=='predicate':n['description']='Different material winner rule'
    if kind=='hash':m['v1_raw_binding']['sha256']='stale'
    if kind=='milestone':e['observed_identity_facts'][0].pop('status')
    if kind=='instrument':annotate(c,v);m['id']='wrong'
    if kind=='event_id':annotate(c,v);e['id']='wrong';m['event_id']='wrong'
    if kind=='expired':self.clock.now.return_value=datetime(2026,10,4,14,tzinfo=timezone.utc)
    annotate(c,v);self.assertFalse(m.get('direct_win_binding'))
 def test_binding_missing_original_evidence_and_stale_seal_rejected(self):
  import tempfile
  import app.collection.current_occurrence as module
  for field in ('original_start_evidence','schedule_status_evidence','sha256'):
   b=load();b[field]=None
   if field!='sha256':b['sha256']=__import__('app.dashboard.session_projection',fromlist=['stable']).stable({k:v for k,v in b.items() if k!='sha256'})
   with tempfile.TemporaryDirectory() as d:
    p=Path(d)/'binding.json';p.write_text(json.dumps(b))
    with patch.object(module,'PATH',p),self.assertRaises(ValueError):module.load()

class Selection(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  clock=patch('app.collection.current_occurrence.datetime');self.clock=clock.start();self.clock.now.return_value=datetime(2026,10,3,14,tzinfo=timezone.utc);self.addCleanup(clock.stop)
 async def test_shared_direct_wins_preserve_native_no_prices_clocks_and_held_review(self):
  s=CurrentService(config=dict(DEFAULT,enabled=False,aggregate_enabled=False));store=CurrentStore(s);s.store=store;s.sink=LatestStateSink(store,s.initial_state());s.dispatch=True
  cats=catalogs();at=utc();original={}
  for v,c in cats.items():
   s.catalog(v,c)
   for m in c['markets']:
    if m['event_id']==load()['sources'][v]['event_id']:
     b=book(v,m,at);original[(v,m['id'])]=deepcopy(b);s.book(v,b)
  snap=store.snapshot();common=[o for e in snap['events'] for g in e['groups'] for o in g['outcomes'] if len(o['quotes'])==2]
  self.assertEqual({o['participant'] for o in common},{'NFL:IND','NFL:WAS'})
  self.assertTrue(all(o['predicate']=='win' for o in common))
  for o in common:
   for q in o['quotes'].values():
    self.assertTrue(q['binding']['verified']);self.assertTrue(q['comparison']['eligible']);self.assertEqual(q['times']['source_at'],at)
    self.assertTrue(q['rules_differ']);self.assertEqual(q['depth'][0]['quantity'],'5')
    self.assertTrue(q['calculations']['arbitrage']['eligible'])
    self.assertIn('denominator',q['calculations']['arbitrage']['basis'])
    self.assertFalse(q['calculations']['ev']['eligible'])
    self.assertIn('native_predicate',q)
    native_book=original[(q['venue'],q['source']['native_market_id'])]
    original_side=next(side for side in native_book['outcomes'] if side['outcome_id']==q['source']['native_outcome_id'])
    self.assertEqual(__import__('decimal').Decimal(q['original']['value']),__import__('decimal').Decimal(original_side['asks']['levels'][0]['price']['value']))
    self.assertEqual(len(q['native_predicate']['domain']),2)
    for limitation in ('Tie pays 0.50','48 hours','two weeks','Kalshi NO is not opponent YES'):
     self.assertIn(limitation,q['rule_note'])
  nos=[q for e in snap['events'] for g in e['groups'] for o in g['outcomes'] for q in o['quotes'].values() if q['source']['native_side']=='no']
  self.assertEqual(len(nos),2);self.assertTrue(all('native_predicate' not in q for q in nos))
  for q in nos:self.assertEqual(q['original']['native_value'],str(1-__import__('decimal').Decimal(q['original']['value'])))
  chosen=common[0]['quotes']['kalshi'];req=dict(schema=snap['schema'],runtime_id=snap['runtime_id'],state_revision=snap['state_revision'],quote_id=chosen['id'],quote_revision=chosen['revision'],client_id='binding-test');held=store.create(req);frozen=deepcopy(held['review'])
  b=original[('kalshi',chosen['source']['native_market_id'])];b['outcomes'][0]['asks']['levels'][0]['price']['value']='.49';s.book('kalshi',b)
  self.assertEqual(store.get(held['selection_id'])['review'],frozen)
  bad=deepcopy(cats['kalshi']);target(bad,'kalshi')['scheduled_start']='2026-10-05T13:30:00+00:00';s.catalog('kalshi',bad)
  self.assertEqual(store.get(held['selection_id'])['review'],frozen)
  s.catalog('kalshi',dict(events=[],markets=[],selection=dict(ids=[])));self.assertEqual(store.get(held['selection_id'])['review'],frozen)
  await store.close()

 async def test_alignment_does_not_supply_missing_or_stale_source_clocks(self):
  for mode in ('unknown','stale'):
   with self.subTest(mode=mode):
    s=CurrentService(config=dict(DEFAULT,enabled=False,aggregate_enabled=False));store=CurrentStore(s);s.store=store;s.sink=LatestStateSink(store,s.initial_state());s.dispatch=True
    for v,c in catalogs().items():
     s.catalog(v,c)
     for m in c['markets']:
      b=book(v,m,utc());b['raw']['exchange_at']=None if mode=='unknown' else (datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat();s.book(v,b)
    quotes=[q for e in store.snapshot()['events'] for g in e['groups'] for o in g['outcomes'] for q in o['quotes'].values() if q.get('native_predicate')]
    self.assertEqual(len(quotes),4);self.assertTrue(all(q['binding']['verified'] for q in quotes));self.assertTrue(all(not q['comparison']['eligible'] for q in quotes))
    await store.close()
