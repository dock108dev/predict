"""Integrated offline product evidence. All source lifecycle records are synthetic."""
import asyncio,json,tempfile,unittest,sys,shutil
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch
from aiohttp.test_utils import TestClient,TestServer
from app.dashboard.multi_game_server import create_app
from app.dashboard import session_history
from app.dashboard.resolution_history_worker import ResolutionHistoryCache
from app.dashboard.math_scenarios import replay
from app.resolution.source_adapters import adapt
from app.collection import public_contracts as pc
from tests.public_contract_lifecycle import owner,AT
from app.fee_example import scenario

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'evidence/public-contract-integration-20261001-v1'

def first_difference(a,b,path='root'):
 if type(a)!=type(b):return (path,type(a).__name__,type(b).__name__)
 if isinstance(a,dict):
  if set(a)!=set(b):return(path,set(a)^set(b))
  for k in a:
   d=first_difference(a[k],b[k],path+'.'+k)
   if d:return d
 elif isinstance(a,list):
  if len(a)!=len(b):return(path,len(a),len(b))
  for i,(x,y) in enumerate(zip(a,b)):
   d=first_difference(x,y,path+'.'+str(i))
   if d:return d
 elif a!=b:return(path,a,b)
 return None

class CompleteLifecycle(unittest.IsolatedAsyncioTestCase):
 async def test_all_adapters_ordinary_routes_history_download_and_fresh_reopening(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);o=owner(root);client=TestClient(TestServer(create_app(owner=o,sessions={},watch_path=root/'watchlists.json')));await client.start_server();origin=str(client.make_url('')).rstrip('/')
   async def get(path):
    r=await client.get(path);self.assertEqual(r.status,200,await r.text());return await r.json()
   async def post(path,body):
    r=await client.post(path,json=body,headers={'Origin':origin});self.assertEqual(r.status,200,await r.text());return await r.json()
   try:
    with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No account access')):
     await post('/api/start',{'duration':175});s=o.session.target;rs=o.session.records;queries=o.session.queries;sid=o.session.sid
     def query(gid):return dict(session=sid+'~'+gid,hash=sid,cutoff=s['durable_cursor'],quantity='100',scenario='cent')
     before={gid:await get('/api/calculate?'+urlencode(query(gid))) for gid in queries.values()}
     for r in rs:self.assertIsNone(r['payload']['published_at'])
     await post('/api/resolutions',rs[:4]);await post('/api/resolutions',rs[4:])
     self.assertEqual((await get('/api/resolution?'+urlencode(query(queries['us_instrument']))))['options'],[])
     await post('/api/stop',{});await o.finalizer;self.assertIsNone(o.error)
     paths=[];responses=[];bundles=[];views={}
     for format,gid in queries.items():
      q=query(gid);calculation=await get('/api/calculate?'+urlencode(q));self.assertEqual(calculation,dict(before[gid],state='saved'))
      hist=await get('/api/resolution?'+urlencode(q));self.assertTrue(hist['options']);self.assertEqual(hist['unavailable_sessions'],[])
      option=hist['options'][-1];q.update(resolution_session=option['session'],resolution_cutoff=option['cutoff'],resolution_asof=AT)
      path='/api/resolution?'+urlencode(q);value=await get(path);self.assertEqual(await get(path+'&download=true'),value)
      views[format]=value['view'];paths.append(path);responses.append(value)
      local=[v for v in value['view']['local_observation_lineage']['observations'] if v['id'] in {r['id'] for r in rs if r['payload']['adapter']['format']==format}]
      self.assertTrue(local);self.assertFalse(value['view']['local_observation_lineage']['authoritative_asof_qualification'])
      if format in ('us_instrument','novig_v3_market'):
       self.assertEqual(local[-1]['local_state'],'corrected_observation');self.assertTrue(any(v['local_state']=='superseded_observation' for v in local))
      self.assertTrue(all(v['published_at'] is None and v['provider_revision_id'] is None for v in local))
      self.assertIsNone(value['view']['sporting']['selected']);self.assertTrue(all(v['observed']['selected'] is None for v in value['view']['venues']))
      earlier=dict(q,resolution_asof='2026-10-04T21:00:00Z');old=await get('/api/resolution?'+urlencode(earlier));self.assertGreater(old['view']['excluded_future_count'],0)
     self.assertEqual(rs[-1]['payload']['home_score'],24);self.assertIsNone(rs[-1]['payload']['payout']);self.assertIsNone(rs[-1]['payload']['completion'])
     self.assertIsNone(next(r for r in rs if r['payload']['adapter']['format']=='prophetx_order' and r['payload']['status']=='settled')['payload']['payout'])
     # Unsupported correction formats and scale changes fail before ingestion.
     for r in rs:
      fmt=r['payload']['adapter']['format'];env=json.loads(r['raw']['body']);binding=env['source_adapter']['binding'];body=env['source_adapter']['original_body']
      if fmt not in ('us_instrument','novig_v3_market'):
       with self.assertRaises(ValueError):adapt(fmt,body,binding,url=r['raw']['url'],received_at=AT,evidence_mode='synthetic',previous=r)
     old=rs[3];env=json.loads(rs[4]['raw']['body']);native=json.loads(env['source_adapter']['original_body']);native['priceScale']='1000'
     with self.assertRaises(ValueError):adapt('us_instrument',json.dumps(native),env['source_adapter']['binding'],url=old['raw']['url'],received_at=AT,evidence_mode='synthetic',previous=old)
     gid=queries['us_instrument'];g=next(g for g in s['games'] if g['id']==gid)
     detail='/api/public-contracts?'+urlencode(dict(capture=sid,cutoff=s['durable_cursor'],game=gid));paths.append(detail);responses.append(await get(detail));self.assertEqual(responses[-1],await get(detail+'&download=true'))
     c=scenario('polymarket_us',quantity='3.12');c['market_id']=g['sources']['polymarket_us']['market_id'];c['trade_time']=c['calculation_time']='2026-09-30T12:00:00Z'
     requests=[dict(version=pc.VERSION,kind='fees',context=c,market=dict(id=c['market_id'],isCombo=False,feeCoefficient='0.0695'),instrument=dict(market_id=c['market_id'],fractionalQtyScale='100',source='SYNTHETIC instrument association')),
      dict(version=pc.VERSION,kind='portfolio',legs=[dict(cash='.4',receipts={'A':'1','B':'0'}),dict(cash='.4',receipts={'A':'0','B':'1'})],states=['A','B'],complete=True),
      dict(version=pc.VERSION,kind='account',format='us_execution',source='polymarket_us',market_id=c['market_id'],association_basis='SYNTHETIC explicit order-to-selected-market assumption',body=dict(order=dict(priceScale='100',fractionalQuantityScale='100'),lastPx='97',lastShares='312',commissionNotionalCollected='100')),
      dict(version=pc.VERSION,kind='account',format='kalshi_account_report',source='kalshi',market_id=g['sources']['kalshi']['market_id'],party_id='SYNTHETIC-P',body={'35':'UMS','55':g['sources']['kalshi']['market_id'],'20105':'SYNTHETIC-report','730':'30.60','parties':[{'20109':'SYNTHETIC-P','1705':'PAYOUT','1704':'30.6030','137':'0.00006','138':'USD'}]})]
     for req in requests:
      bundle=await post('/api/math-scenario',dict(query(gid),public_contract=req));self.assertEqual(replay(bundle),bundle)
      self.assertEqual(await get('/api/math-scenario-download?sha256='+bundle['sha256']),bundle);bundles.append(bundle)
     deterministic=bundles[1]['public_contract_calculation']['calculation'];self.assertTrue(deterministic['mathematical_arbitrage']);self.assertIsNone(deterministic['expected_net'])
     self.assertEqual(bundles[2]['public_contract_calculation']['decoded']['quantity'],'3.12')
     self.assertEqual(bundles[3]['public_contract_calculation']['decoded']['yes_fraction'],'0.306')
     await post('/api/watchlists',[dict(name='SYNTHETIC raw comparison',metric='raw_gap',threshold='-100',filters={'competition':'NFL'})])
     history=await get('/api/opportunity-history?capture='+sid);self.assertEqual(await get('/api/opportunity-history?capture='+sid+'&download=true'),history);self.assertTrue(all(not v['active'] for v in history['items']));self.assertTrue(history['coverage']['complete'])
     self.assertEqual(session_history.load(o.session.output,s['durable_cursor']),dict(s,state='saved'))
     paths.append('/api/opportunity-history?capture='+sid);responses.append(history)
     expected=dict(snapshot=dict(s,state='saved'),responses=responses,replays=bundles)
     request=dict(watchlists=history['watchlists'],sid=sid,cutoff=s['durable_cursor'],get=paths,bundles=bundles);request_path=root/'reopen.json';request_path.write_text(json.dumps(request));output=root/'fresh-result.json'
     process=await asyncio.create_subprocess_exec(sys.executable,'-m','tests.public_contract_reopen',str(o.session.output.parent),str(request_path),str(output),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,cwd=ROOT)
     stdout,stderr=await asyncio.wait_for(process.communicate(),25);self.assertEqual(process.returncode,0,stderr.decode());self.assertEqual(json.loads(output.read_text()),json.loads(json.dumps(expected)),first_difference(json.loads(output.read_text()),json.loads(json.dumps(expected))))
     evidence=root/'synthetic-lifecycle';evidence.mkdir(parents=True,exist_ok=True)
     shutil.copytree(o.session.output,evidence/sid,dirs_exist_ok=True)
     (evidence/'selected-reopening-request.json').write_text(json.dumps(request,indent=2)+'\n')
     (evidence/'selected-reopening-result.json').write_text(output.read_text())
     (evidence/'history.json').write_text(json.dumps(history,indent=2)+'\n')
     (evidence/'qualification.json').write_text(json.dumps(dict(evidence_mode='synthetic',provider_collection=False,formats=queries,imported=len(rs),original_prediction_unchanged=True,fresh_process_exact=True),indent=2)+'\n')
   finally:await client.close()

class WorkerOwnership(unittest.IsolatedAsyncioTestCase):
 async def test_cancel_during_process_creation_still_reaps_owned_child(self):
  cache=ResolutionHistoryCache();factory=asyncio.create_subprocess_exec;entered=asyncio.Event();release=asyncio.Event();children=[]
  async def delayed(*args,**kwargs):
   entered.set();await release.wait();child=await factory(sys.executable,'-c','import time; time.sleep(30)',**kwargs);children.append(child);return child
  with tempfile.TemporaryDirectory() as tmp,patch('app.dashboard.resolution_history_worker.asyncio.create_subprocess_exec',delayed):
   task=asyncio.create_task(cache.load({'SYNTHETIC':Path(tmp)}));await entered.wait();task.cancel();release.set()
   with self.assertRaises(asyncio.CancelledError):await task
   self.assertEqual(len(children),1);self.assertIsNotNone(children[0].returncode);self.assertFalse(cache.lock.locked())

 async def test_cancellation_reaps_worker_and_releases_serial_ownership(self):
  cache=ResolutionHistoryCache();factory=asyncio.create_subprocess_exec
  async def stalled(*args,**kwargs):
   return await factory(sys.executable,'-c','import time; time.sleep(30)',**kwargs)
  with tempfile.TemporaryDirectory() as tmp,patch('app.dashboard.resolution_history_worker.asyncio.create_subprocess_exec',stalled):
   task=asyncio.create_task(cache.load({'SYNTHETIC':Path(tmp)}))
   while cache.process is None:await asyncio.sleep(.01)
   proc=cache.process;task.cancel()
   with self.assertRaises(asyncio.CancelledError):await task
   self.assertIsNotNone(proc.returncode);self.assertIsNone(cache.process);self.assertFalse(cache.lock.locked())

 async def test_cache_verifies_all_files_and_invalidates_tampering(self):
  from tests.test_nfl_resolution import fixture,rec,ASOF
  from app.collection.transport_session import ObservationJournal
  rows,s,g,e=fixture();r=rec(s,g,e)
  rows+=[dict(type='product_resolution',source='resolution',session_id=s['session_id'],observed_at=ASOF,resolution=r),dict(type='session_finished',source='session',session_id=s['session_id'],observed_at=ASOF,reason='manual_stop')]
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp)/s['session_id'];folder.mkdir();j=ObservationJournal(folder/(folder.name+'.jsonl'))
   for row in rows:j.save(row)
   j.close();cache=ResolutionHistoryCache();paths={'SYNTHETIC':folder};factory=asyncio.create_subprocess_exec
   with patch('app.dashboard.resolution_history_worker.asyncio.create_subprocess_exec',wraps=factory) as spawn:
    one=await cache.load(paths);self.assertEqual(one,await cache.load(paths));self.assertEqual(spawn.call_count,1)
    self.assertLess(cache.last_accounting['peak_rss_bytes'],cache.last_accounting['rss_limit_bytes'])
    with j.path.open('a') as f:f.write(' ')
    two=await cache.load(paths);self.assertEqual(spawn.call_count,2);self.assertIn('error',two['SYNTHETIC'])
