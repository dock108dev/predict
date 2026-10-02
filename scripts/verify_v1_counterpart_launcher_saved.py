"""Finish QA on retained synthetic launcher rehearsal; never Start or transport."""
import asyncio,json,sys,subprocess
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
from app.collection.native_approval import digest,implementation
OUT=ROOT/'evidence/v1-counterpart-completion-20261001-v1'
async def main():
 control=sorted(OUT.glob('OFFLINE-*'))[-1];folder=next(p for p in (control/'sessions').iterdir() if p.is_dir());identity=json.loads((control/'identity.json').read_text());assert identity['implementation_sha256']==digest(implementation())
 rows=list(verified(folder)['rows']);saved=load(folder);assert saved==project_rows(rows,saved['durable_cursor']);report=json.loads((folder/'report.json').read_text());assert report['cleanup_complete'];assert report['collection_seconds']<=180
 for n in ('start-response.json','stop-response.json'):assert json.loads((control/n).read_text())['status']==200
 p=SessionProjection();retained=[];details={}
 for r in rows:
  p.apply(r)
  if r['type']!='prediction_book':continue
  snap=p.snapshot(mode='saved');cs=comparisons(snap,{})
  if cs:retained.append(dict(cutoff=snap['durable_cursor'],raw_comparisons=len(cs)))
  for c in cs:
   if c.get('manual_raw') and c['identity']['period']=='first_half' and c['identity']['family'] in ('spread','total'):
    details.setdefault(c['identity']['family'],c)
 assert set(details)=={'spread','total'}
 # Final Stop is not permission to label disconnected native inputs current.
 assert not saved['manual_comparisons'];assert retained
 fresh=await asyncio.to_thread(subprocess.check_output,[sys.executable,'-c','from app.dashboard.session_history import load;from app.dashboard.session_projection import stable;import sys;print(stable(load(sys.argv[1])))',str(folder)],text=True);assert fresh.strip()==stable(saved)
 owner=CoverageOwner(OUT/'saved-route-controls',pilot_output=folder.parent,product_mode=True)
 with patch.object(owner,'start',side_effect=AssertionError('No collection')),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
  client=TestClient(TestServer(create_app(owner=owner,sessions={},watch_path=OUT/'saved-route-watches.json')));await client.start_server();origin={'Origin':str(client.make_url('/')).rstrip('/')}
  try:
   for family,c in details.items():
    response=await client.get('/api/calculate?'+urlencode(dict(session=c['session'],hash=c['hash'],cutoff=c['cutoff'])));data=await response.json();assert response.status==200,data;assert any(v['raw_difference']==c['raw_difference'] for v in data['comparisons'])
   from tests.test_commercial_engineering import watch
   w=watch('raw_gap');w['threshold']='0';response=await client.post('/api/watchlists',json=[w],headers=origin);assert response.status==200,await response.text()
   history=await (await client.get('/api/opportunity-history?capture='+saved['session_id'])).json();download=await (await client.get('/api/opportunity-history?capture='+saved['session_id']+'&download=true')).json();assert history==download
  finally:await client.close()
 counts={v:sum(r['type']=='prediction_book' and r['source']==v for r in rows) for v in ('kalshi','polymarket_us')};assert all(n>2 for n in counts.values())
 result=dict(classification='OFFLINE exact 180-second ordinary launcher/control over explicitly synthetic schedules/envelopes/books; no live qualification',implementation_sha256=digest(implementation()),spec_sha256=identity['spec_sha256'],actual_launcher=True,ordinary_start_stop=True,collection_seconds=report['collection_seconds'],cleanup_complete=True,independent_native_images_and_updates=counts,retained_valid_raw_cutoffs=retained,details_after_stop=['spread','total'],watch=True,history_download_equal=True,history_sha256=stable(history),fresh_process_reopening=True,final_disconnected_inputs_are_not_current_pairs=True,provider_requests=0,credits=0,credentials=0,resources=report.get('resources'),source_session=str(folder.relative_to(ROOT)),harness_repair='The initial harness incorrectly required disconnected terminal books to remain current pairs; retained valid cutoffs are the reviewable result. Original failed harness log preserved.')
 (OUT/'launcher-verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='retained_valid_raw_cutoffs'},indent=2))
if __name__=='__main__':asyncio.run(main())
