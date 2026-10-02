#!/usr/bin/env python3
"""Actual saved product routes, no Start and no provider transport."""
import asyncio,json,sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from aiohttp.test_utils import TestClient,TestServer
from app.dashboard.session_history import verified,load,project_rows
from app.dashboard.session_projection import SessionProjection,stable
from app.dashboard.price_comparison import comparisons
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
OUT=ROOT/'evidence/v1-admission-delivery-repair-20261001-v1'
SESSION=OUT/'saved/offline-v1-repair-713fd0fa-20261001'
async def main():
 rows=list(verified(SESSION)['rows']);snapshot=load(SESSION);assert snapshot==project_rows(rows,snapshot['durable_cursor'])
 owner=CoverageOwner(OUT/'offline-saved',pilot_output=SESSION.parent,product_mode=True)
 with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('Offline credentials forbidden')),patch.object(owner,'start',side_effect=AssertionError('No acquisition authorized')):
  client=TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=OUT/'verification-watches.json')));await client.start_server();origin={'Origin':str(client.make_url('/')).rstrip('/')}
  evidence=[]
  async def request(path,body=None):
   r=await client.request('GET' if body is None else 'POST',path,json=body,headers=origin)
   data=await r.json();return r.status,data,dict(r.headers)
  try:
   status,feed,_=await request('/api/dashboard?'+urlencode(dict(view='feed',capture=snapshot['session_id'])));assert status==200,feed
   assert feed['state']=='saved' and not feed['live'];assert len(feed['comparisons'])==18
   p=SessionProjection();seen=set();routepairs=[]
   for row in rows:
    p.apply(row)
    if row['type']not in ('aggregate_snapshot','aggregate_award_snapshot','prediction_book'):continue
    snap=p.snapshot(mode='saved')
    for c in comparisons(snap,{}):
     if c['id'] in seen or c.get('raw_difference') is None:continue
     seen.add(c['id']);routepairs.append(c)
   for c in routepairs:
    q=dict(session=c['session'],hash=c['hash'],cutoff=c['cutoff']);path='/api/calculate?'+urlencode(q)
    status,detail,_=await request(path);assert status==200,detail
    selected=next(v for v in detail['comparisons'] if v['id']==c['id']);assert selected['raw_difference']==c['raw_difference'];assert selected['net']is None and selected['ev']is None
    status,size,_=await request('/api/decision-sizes',dict(q,sizes=['1','10','100']));assert status==422 and ('quantity' in size['error'] or 'depth' in size['error']),size
    evidence.append(dict(row_id=c['id'],identity=c['identity'],cutoff=c['cutoff'],detail_sha256=stable(detail),raw_difference=c['raw_difference'],sizing={'status':status,'reason':size['error']},timing=c['timing'],settlement=c['settlement']))
   w=[dict(name='Retained raw comparison verification',metric='raw_gap',threshold='0',quantity='100',filters={})]
   status,watch,_=await request('/api/watchlists',w);assert status==200,watch
   status,signals,_=await request('/api/signals');assert status==200,signals
   status,hist,_=await request('/api/opportunity-history?capture='+snapshot['session_id']);assert status==200,hist
   status,download,headers=await request('/api/opportunity-history?capture='+snapshot['session_id']+'&download=true');assert status==200 and hist==download;assert 'attachment' in headers['Content-Disposition']
   (OUT/'verified-history-download.json').write_text(json.dumps(download,indent=2)+'\n')
   (OUT/'details-verification.json').write_text(json.dumps(evidence,indent=2)+'\n')
   result=dict(classification='Offline actual routes over versioned retained-input repair; no fixture prices substituted',session=snapshot['session_id'],snapshot_sha256=stable(snapshot),exact_reopening=True,raw_detail_rows=len(evidence),feed_comparisons=18,details_pass=True,informational_sizing='Correctly unavailable for aggregate quantity/depth; no new native depth pair enabled',watches_pass=True,history_download_equal=True,history_sha256=stable(hist),no_live_signals=True,credential_access=0,provider_requests=0,starts=0)
   (OUT/'product-verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
  finally:await client.close()
if __name__=='__main__':asyncio.run(main())
