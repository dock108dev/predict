"""Retained exact predicate controls plus explicitly synthetic current transport/books."""
import asyncio,json,socket,subprocess,sys,tempfile,unittest
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from aiohttp import web
from tests.test_v1_coverage_collector import Fixture as Previous
from app.collection.counterparts import inventory,reserve
from app.collection.catalog_metadata import compact
from app.collection.continuous import select_inventory
from app.dashboard.session_history import load,project_rows,verified
from app.dashboard.session_projection import stable
ROOT=Path(__file__).resolve().parents[1];OLD=ROOT/'evidence/v1-admission-delivery-repair-20261001-v1';PACKAGE=ROOT/'scripts/v1_counterpart_package'
def cats():
 from app.collection.v1_comparison import annotate
 value={v:json.loads((OLD/(v+'-repaired-catalog.json')).read_text()) for v in ('kalshi','polymarket_us')}
 for v,c in value.items():annotate(c,v,policy='manual-comparison-2')
 return value
def configuration():return json.loads((PACKAGE/'run-spec.json').read_text())
class Inventory(unittest.TestCase):
 def test_exact_counterparts_and_fair_atomic_resident_selection(self):
  c=cats();pairs=inventory(c);self.assertEqual(len(pairs),48);self.assertFalse(any(p['identity']['family']=='futures' for p in pairs))
  at=datetime.fromisoformat('2026-10-01T23:19:00+00:00');accepted=reserve(c,at);self.assertTrue(accepted)
  for v,cat in c.items():
   compact(cat,v);ids=set(select_inventory(cat,at)[0]);self.assertTrue(set(cat['counterpart_reservation']['market_ids'])<=ids)
   from app.dashboard.bounds import retained_bytes
   self.assertLessEqual(retained_bytes(cat),2*1024*1024)
  for p in pairs:
   if p['id'] in accepted:
    for l in p['legs']:self.assertIn(l['market_id'],select_inventory(c[l['source']],at)[0])
  for cid in ('NCAAF/first_half/spread','NCAAF/first_half/total'):self.assertTrue(any(p['id'] in accepted and p['cell_id']==cid for p in pairs))
 def test_same_cell_different_line_and_changed_identity_are_not_pairs(self):
  c=cats();baseline=inventory(c)
  for m in c['polymarket_us']['markets']:
   b=m['v1_raw_binding']
   if b.get('identity') and b['identity']['family']=='spread' and b.get('source_predicate'):b['source_predicate']['line']='999.5'
  self.assertFalse(any(p['identity']['family']=='spread' for p in inventory(c)))
  c=cats()
  for m in c['polymarket_us']['markets']:
   if m['v1_raw_binding'].get('identity'):m['v1_raw_binding']['identity']['season']='CONSTRUCTED changed season'
  self.assertEqual(inventory(c),[]);self.assertTrue(baseline)
 def test_expired_inventory_selects_no_fixture_as_current(self):
  c=cats();at=datetime.fromisoformat('2030-01-01T00:00:00+00:00');self.assertEqual(reserve(c,at),[])
class RetainedTransport(Previous):
 def __init__(self,fault=None):
  super().__init__(fault);self.retained={v:json.loads((OLD/(v+'-repaired-catalog.json')).read_text()) for v in ('kalshi','polymarket_us')};self.native_calls=[]
  from scripts.repair_v1_retained_admission import SESSION
  self.pages=[r for r in verified(SESSION)['rows'] if r['type']=='prediction_discovery_http'];self.schedule=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
 def current(self,obj):
  if isinstance(obj,list):return [self.current(x) for x in obj]
  if not isinstance(obj,dict):return obj
  return {k:self.schedule if k in ('start_date','startTime','gameStartTime','scheduled_start') and isinstance(v,str) else self.current(v) for k,v in obj.items()}
 async def boot(self,path):
  o=await super().boot(path);o.spec_factory=lambda:dict(configuration(),mode='mock');return o
 def event_control(self):
  event=deepcopy(next(e['_native'] for e in self.retained['polymarket_us']['events'] if e['id']=='116584'))
  # Explicit synthetic envelope packaging; selected terms/IDs are retained.
  wanted={'932924','1094945','1095123'}
  event['markets']=[m['_native'] for m in self.retained['polymarket_us']['markets'] if m['event_id']=='116584' and m['id'] in wanted]
  return event
 async def rest(self,req):
  if req.path.startswith('/v4/'):return await super().rest(req)
  if '/account/' in req.path:return await super().rest(req)
  self.native_calls.append((req.path,dict(req.query)))
  if req.path=='/trade-api/v2/events':
   ticker=req.query['series_ticker'];matches=[r for r in self.pages if r['source']=='kalshi' and r['path']==req.path and r['params'].get('series_ticker')==ticker]
   import base64
   body=json.loads(base64.b64decode(matches[0]['body_b64'])) if matches else dict(events=[],cursor='')
   return web.json_response(self.current(body))
  if req.path=='/trade-api/v2/markets':
   eid=req.query['event_ticker'];markets=[m['_native'] for m in self.retained['kalshi']['markets'] if m['event_id']==eid and (m['id'].endswith('WKU3') or m['id'].endswith('-28') or 'NFL' in m['id'])]
   if 'NFL' in eid:markets=markets[:1]
   return web.json_response(self.current(dict(markets=markets,cursor='')))
  if req.path=='/v1/events':
   if req.query.get('tagSlug')!='cfb':return web.json_response(dict(events=[]))
   event=self.event_control()
   return web.json_response(self.current(dict(events=[event])))
  if req.path=='/v1/events/116584':
   if self.fault=='query_local':return web.Response(body=b'{"event":'+b' '*2100000)
   event=self.event_control()
   return web.json_response(self.current(dict(event=event)))
  if req.path.startswith('/v1/market/id/'):
   mid=req.path.rsplit('/',1)[1];m=next(m['_native'] for m in self.retained['polymarket_us']['markets'] if m['id']==mid)
   return web.json_response(self.current(dict(market=m)))
  if req.path=='/v1/markets':return web.json_response(dict(markets=[]))
  raise AssertionError(req.path)
 async def start(self,duration=30):
  r=await self.client.post('/api/start',json=dict(duration=duration,source_settings=configuration()['source_session']),headers=self.origin)
  assert r.status==200,await r.text()
  original=self.owner.session.journal.save
  def observed(row):
   original(row);self.books+=row['type']=='prediction_book';self.changed.set()
  self.owner.session.journal.save=observed
class Runtime(unittest.IsolatedAsyncioTestCase):
 async def test_retained_mappings_both_subscriptions_updates_routes_stop_reopen(self):
  from urllib.parse import urlencode
  from app.dashboard.price_comparison import comparisons
  from app.dashboard.opportunity_history import observations
  from tests.test_commercial_engineering import watch
  with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
   f=RetainedTransport();o=await f.boot(tmp)
   try:
    await f.start(duration=180)
    async with asyncio.timeout(80):
     while len(f.active())<2:
      if o.session.task.done():raise AssertionError(str((o.error,o.session.reason,o.session.discovery.source_stops,f.native_calls)))
      await asyncio.sleep(.1)
    self.assertEqual({c['venue'] for c in f.active()},{'kalshi','polymarket_us'})
    await f.images();await f.wait(lambda:bool(o.session.projection.snapshot()['manual_comparisons']))
    s=o.session.projection.snapshot();cs=comparisons(s,{})
    self.assertTrue(any(c['identity']['period']=='first_half' and c['identity']['family']=='spread' for c in cs))
    # Missing leg never enters comparisons; independent source remains usable.
    k=next(k for k in o.session.projection.books if k[0]=='polymarket_us');row=o.session.projection.books.pop(k)
    absent=o.session.projection.snapshot();self.assertFalse(any(any(l.get('native_identity',{}).get('market_id')==k[2] for l in c['legs']) for c in comparisons(absent,{})));o.session.projection.books[k]=row
    # Repeated native delta and US image are independent updates through adapters.
    for conn in f.active():await f.send(conn)
    await f.wait(lambda:len(o.session.projection.books)>=2)
    feed=await (await f.client.get('/api/dashboard?view=feed')).json();self.assertIn('comparisons',feed,feed);c=next(c for c in feed['comparisons'] if c.get('manual_raw'))
    q=dict(session=c['session'],hash=c['hash'],cutoff=c['cutoff']);detail=await f.client.get('/api/calculate?'+urlencode(q));self.assertEqual(detail.status,200,await detail.text())
    data=await detail.json();self.assertIsNone(data['comparisons'][0]['net'])
    w=watch('raw_gap');w['threshold']='0';await f.client.post('/api/watchlists',json=[w],headers=f.origin)
    await f.stop_route();self.assertTrue(o.session.cleanup_complete);self.assertIsNone(o.error,o.error)
    rows=verified(o.session.output)['rows'];saved=load(o.session.output);self.assertEqual(saved,project_rows(rows,saved['durable_cursor']))
    sid=o.session.sid;history=await (await f.client.get('/api/opportunity-history?capture='+sid)).json();download=await (await f.client.get('/api/opportunity-history?capture='+sid+'&download=true')).json();self.assertEqual(history,download)
    code='from app.dashboard.session_history import load;from app.dashboard.session_projection import stable;import sys;print(stable(load(sys.argv[1])))'
    child=await asyncio.create_subprocess_exec(sys.executable,'-c',code,str(o.session.output),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE);out,err=await asyncio.wait_for(child.communicate(),25);self.assertEqual(child.returncode,0,err.decode());self.assertEqual(out.decode().strip(),stable(saved))
    result=dict(classification='SYNTHETIC schedule refresh over retained exact native mappings and synthetic books; engineering only',both_subscriptions=True,details=True,watch=True,history_download_equal=True,stop_cleanup=True,fresh_process_reopening=True,raw_comparisons=len(cs),native_calls=f.native_calls,provider_requests=0,credits=0,credentials=0)
    # Routine regressions must never rewrite a historical qualification report.
    (Path(tmp)/'runtime-verification.json').write_text(json.dumps(result,indent=2)+'\n')
   finally:await f.close()
class Faults(unittest.IsolatedAsyncioTestCase):
 async def test_query_local_failure_keeps_independent_discovery_no_retry(self):
  with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
   f=RetainedTransport('query_local');o=await f.boot(tmp)
   try:
    await f.start(duration=180)
    async with asyncio.timeout(80):
     while not o.session.discovery.completed:
      if o.session.task.done():raise AssertionError(str((o.error,o.session.reason)))
      await asyncio.sleep(.1)
    self.assertNotIn('polymarket_us',o.session.discovery.source_stops)
    self.assertTrue(any(p=='/trade-api/v2/markets' for p,q in f.native_calls))
    self.assertEqual(sum(p=='/v1/events/116584' for p,q in f.native_calls),1)
    await f.stop_route();self.assertTrue(o.session.cleanup_complete)
    rows=verified(o.session.output)['rows'];self.assertTrue(any(r.get('delivery_reason')=='native_entity_byte_cap' for r in rows))
   finally:await f.close()
 async def test_automatic_deadline_cleanup_and_no_late_dispatch(self):
  with tempfile.TemporaryDirectory() as tmp,patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
   f=Previous();o=await f.boot(tmp);o.spec_factory=lambda:dict(configuration(),mode='mock')
   try:
    response=await f.client.post('/api/start',json=dict(duration=3,source_settings=configuration()['source_session']),headers=f.origin);self.assertEqual(response.status,200,await response.text())
    await o.finalizer;self.assertTrue(o.session.cleanup_complete);self.assertTrue(o.session.stop_event.is_set());calls=len(f.native_calls)+len(f.odds_calls);await asyncio.sleep(.05);self.assertEqual(calls,len(f.native_calls)+len(f.odds_calls))
   finally:await f.close()
class QuoteGates(unittest.TestCase):
 def test_stale_changed_identity_and_missing_leg(self):
  from tests.test_v1_comparison import prepared
  from app.collection.v1_comparison import admission
  p=prepared();v='kalshi';m=p.inventory[v]['markets'][0]
  from app.collection.v1_comparison import annotate
  annotate(p.inventory[v],v,policy='manual-comparison-2');b=m['v1_raw_binding'];book=next(r['book'] for k,r in p.books.items() if k[0]==v and k[2]==m['id']);at=datetime.fromisoformat(book['raw']['received_at'])
  self.assertFalse(admission(b,None,at.isoformat())[0]);stale=deepcopy(book);stale['raw']['received_at']=(at-timedelta(seconds=16)).isoformat();self.assertFalse(admission(b,stale,at.isoformat())[0]);changed=deepcopy(book);changed['raw']['ref']['market_id']='CONSTRUCTED changed ID';self.assertFalse(admission(b,changed,at.isoformat())[0])
