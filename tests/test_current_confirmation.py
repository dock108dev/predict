"""Labeled controlled confirmations: full books, clocks, continuity and leases."""
import json,unittest,time
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from dataclasses import asdict
from unittest.mock import patch
from app.collection.current_confirmation import Confirmations,validate,content
from app.collection.current_service import CurrentService
from app.collection.current_policy import DEFAULT
from app.collection.current_sink import LatestStateSink,utc
from app.dashboard.current_state import CurrentStore
from app.dashboard.current_contract import snapshot_inputs
from tests.test_current_occurrence import catalogs,book
from app.dashboard.session_projection import stable

NOW=datetime.now(timezone.utc)
def observation(v,m,at,generation=1,sequence=1):
 b=book(v,m,(at+timedelta(seconds=1)).isoformat());b['raw']['exchange_at']=at.isoformat() if v=='polymarket_us' else None
 d=dict(type='orderbook_snapshot',sending_ts_ms=int(at.timestamp()*1000),sid=2,seq=sequence,msg=dict(market_ticker=m['id'])) if v=='kalshi' else dict(requestId='sub-'+str(generation),subscriptionType='SUBSCRIPTION_TYPE_MARKET_DATA',marketData=dict(bids=[],offers=[],transactTime=at.isoformat()))
 raw=json.dumps(d).encode();return b,d,raw

def proof(tracker,b,d,raw,generation=1):
 return tracker.observe(b,d,raw,generation=generation,request_id='sub-'+str(generation),requested_at=(NOW-timedelta(seconds=10)).isoformat() if tracker.venue=='kalshi' else None,sid=2 if tracker.venue=='kalshi' else None,sequence=d.get('seq'))

class Confirmation(unittest.TestCase):
 def test_new_complete_evidence_same_content_and_repeat_does_not_renew(self):
  for v,c in catalogs().items():
   t=Confirmations(v);t.begin(1);m=c['markets'][0];b,d,r=observation(v,m,NOW-timedelta(seconds=2));a=proof(t,b,d,r);validate(a,b['raw']['ref'],b)
   repeated=deepcopy(b);repeated['raw']['received_at']=NOW.isoformat();self.assertEqual(proof(t,repeated,d,r),a)
   b2,d2,r2=observation(v,m,NOW-timedelta(seconds=1),sequence=2);new=proof(t,b2,d2,r2)
   self.assertEqual(content(b),content(b2));self.assertNotEqual(new['sha256'],a['sha256']);self.assertGreater(new['confirmed_at'],a['confirmed_at'])
 def test_clock_regression_future_missing_and_generation_isolation(self):
  for v,c in catalogs().items():
   t=Confirmations(v);t.begin(1);m=c['markets'][0];b,d,r=observation(v,m,NOW-timedelta(seconds=2));proof(t,b,d,r)
   old,od,orr=observation(v,m,NOW-timedelta(seconds=3));
   with self.assertRaises(ValueError):proof(t,old,od,orr)
   future,fd,fr=observation(v,m,NOW+timedelta(seconds=1));future['raw']['received_at']=NOW.isoformat()
   with self.assertRaises(ValueError):proof(t,future,fd,fr)
   t.begin(2)
   with self.assertRaises(ValueError):proof(t,b,d,r)
   if v=='polymarket_us':d['requestId']='sub-2'
   self.assertIsNone(proof(t,b,d,r,generation=2))
   missing,md,mr=observation(v,m,NOW,2);missing['raw']['exchange_at']=None;md.pop('sending_ts_ms',None)
   self.assertIsNone(proof(t,missing,md,json.dumps(md).encode(),generation=2))
 def test_content_identity_and_seal_invalidated(self):
  for v,c in catalogs().items():
   t=Confirmations(v);t.begin(1);b,d,r=observation(v,c['markets'][0],NOW);a=proof(t,b,d,r)
   bad=deepcopy(b);bad['outcomes'][0]['asks']['levels'][0]['price']['value']='.47'
   with self.assertRaises(ValueError):validate(a,bad['raw']['ref'],bad)
   bad=deepcopy(b);bad['raw']['ref']['market_id']='wrong'
   with self.assertRaises(ValueError):validate(a,bad['raw']['ref'],bad)
   a['payload_sha256']='0'*64
   with self.assertRaises(ValueError):validate(a)

class Held(unittest.IsolatedAsyncioTestCase):
 async def test_unknown_price_clock_fresh_confirmation_no_reprice_held_inputs_and_expiry(self):
  clock=patch('app.collection.current_occurrence.datetime');fake=clock.start();fake.now.return_value=datetime(2026,10,3,14,tzinfo=timezone.utc);self.addCleanup(clock.stop)
  svc=CurrentService(config=dict(DEFAULT,enabled=False,aggregate_enabled=False));store=CurrentStore(svc);svc.store=store;svc.sink=LatestStateSink(store,svc.initial_state());svc.dispatch=True
  cats=catalogs();trackers={};books={}
  for v,c in cats.items():
   svc.catalog(v,c);trackers[v]=Confirmations(v);trackers[v].begin(1)
   for m in c['markets']:
    b,d,r=observation(v,m,NOW-timedelta(seconds=2));b['book_confirmation']=proof(trackers[v],b,d,r);svc.book(v,b);books[v,m['id']]=b
  snap=store.snapshot();pairs=[o for e in snap['events'] for g in e['groups'] for o in g['outcomes'] if len(o['quotes'])==2];self.assertEqual(len(pairs),2)
  self.assertTrue(all(q['comparison']['eligible'] for o in pairs for q in o['quotes'].values()))
  chosen=pairs[0]['quotes']['kalshi'];self.assertIsNone(chosen['times']['source_at']);self.assertIsNone(chosen['age_seconds']);self.assertIsNotNone(chosen['confirmation_age_seconds'])
  held=store.create(dict(schema=snap['schema'],runtime_id=snap['runtime_id'],state_revision=snap['state_revision'],quote_id=chosen['id'],quote_revision=chosen['revision'],client_id='confirm-test'));frozen=deepcopy(held['review']);expires=store.leases[held['selection_id']]['deadline']
  for v,c in cats.items():
   for m in c['markets']:
    b,d,r=observation(v,m,NOW-timedelta(seconds=1),sequence=2);b['book_confirmation']=proof(trackers[v],b,d,r);svc.book(v,b)
  current=store.index(store.snapshot())[chosen['id']]['quote'];self.assertEqual(current['revision'],chosen['revision']);self.assertEqual(current['times'],chosen['times']);self.assertNotEqual(current['book_confirmation'],chosen['book_confirmation'])
  self.assertEqual(store.get(held['selection_id'])['review'],frozen);self.assertEqual(store.leases[held['selection_id']]['deadline'],expires)
  # A genuinely changed original price requires explicit adoption; confirmations do not.
  m=next(m for m in cats['kalshi']['markets'] if m['id']==chosen['source']['native_market_id'])
  b,d,r=observation('kalshi',m,NOW,sequence=3);b['outcomes'][0]['asks']['levels'][0]['price']['value']='.47';b['book_confirmation']=proof(trackers['kalshi'],b,d,r);svc.book('kalshi',b)
  latest=store.index(store.snapshot())[chosen['id']]['quote'];self.assertGreater(latest['revision'],chosen['revision']);self.assertEqual(store.get(held['selection_id'])['review'],frozen)
  state=store.snapshot();adopted=store.create(dict(schema=state['schema'],runtime_id=state['runtime_id'],state_revision=state['state_revision'],quote_id=latest['id'],quote_revision=latest['revision'],client_id='adopt-test'));self.assertEqual(adopted['review']['quote']['original']['value'],'.47')
  start=store.monotonic();store.monotonic=lambda:start+40;store.refresh_age();stale=store.index(store.snapshot())[chosen['id']]['quote'];self.assertTrue(stale['stale']);self.assertFalse(stale['comparison']['eligible'])
  self.assertEqual(store.get(held['selection_id'])['review'],frozen)
  svc.source_state('kalshi','resyncing','Controlled sequence failure');self.assertFalse(store.index(store.snapshot())[chosen['id']]['quote']['comparison']['eligible'])
  await store.close()

class WireControls(unittest.TestCase):
 def test_complete_adapters_reject_gap_wrong_market_and_incomplete_us(self):
  from tests.test_kalshi import engine,frame
  from app.adapters.kalshi_stream import RecoveryRequired
  from tests.test_polymarket_us_stream import message
  from tests.test_polymarket_us import market
  from app.adapters.polymarket_us_stream import MarketStream,StaleSubscriptionFrame
  k=engine();k.feed(frame(1),k.generation,NOW)
  with self.assertRaises(RecoveryRequired):k.feed(frame(3,'orderbook_delta'),k.generation,NOW)
  self.assertIsNone(k.sid)
  u=MarketStream([market()],None);g=u.begin_subscription('current')
  with self.assertRaises(StaleSubscriptionFrame):u.parse(message('prior'), 'current',generation=g)
  bad=json.loads(message('current'));bad['marketData']['marketSlug']='wrong'
  with self.assertRaises(ValueError):u.parse(json.dumps(bad),'current',generation=g)
  u=MarketStream([market()],None);g=u.begin_subscription('current');bad=json.loads(message('current'));bad['marketData'].pop('offers')
  parsed=u.parse(json.dumps(bad),'current',generation=g);self.assertNotEqual(parsed.sync.value,'synchronized')

class SnapshotBudget(unittest.IsolatedAsyncioTestCase):
 async def test_snapshot_requests_share_budget_and_do_not_change_subscription(self):
  from types import SimpleNamespace
  from app.collection.current_native import NativeWorker
  from app.collection.prediction_producer import PredictionBudget
  from app.collection.odds_http import BudgetStop
  config=dict(DEFAULT,duration_seconds=180,requests_per_source=2)
  service=SimpleNamespace(config=config,dispatch=True,deadline=time.monotonic()+180)
  w=NativeWorker(service,'kalshi');w.client=SimpleNamespace(budget=PredictionBudget(dict(session_bytes=1024*1024)));pending={};commands=[]
  class Socket:
   async def send(self,wire):commands.append(json.loads(wire));pending.clear()
  w.socket=Socket();markets=[SimpleNamespace(raw=SimpleNamespace(ref=SimpleNamespace(market_id='exact-market')))]
  async def no_sleep(seconds):pass
  with patch('app.collection.current_native.asyncio.sleep',no_sleep),self.assertRaises(BudgetStop):await w.snapshots(SimpleNamespace(sid=7),markets,pending)
  self.assertEqual(len(commands),2);self.assertEqual(w.client.budget.requests,2)
  self.assertTrue(all(c['cmd']=='update_subscription' and c['params']==dict(sid=7,market_tickers=['exact-market'],action='get_snapshot') for c in commands))
