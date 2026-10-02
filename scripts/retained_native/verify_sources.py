"""Check admitted reviews against complete original source objects, not summaries."""
import base64,json,sys,subprocess
from pathlib import Path
from app.dashboard.session_history import verified
from app.collection.transport_session import reopen
from app.dashboard.session_projection import stable
from hashlib import sha256
ROOT=Path('.');OUT=ROOT/'evidence/native-retained-coverage-20260930-v1';DIRECTORY=ROOT/'app/reviews/native';index=json.loads((DIRECTORY/'index-v4.json').read_text());receipts={};sources=[]
if len(sys.argv)==1:
 (OUT/'source-checks').mkdir(exist_ok=True);results=[];logs=[]
 for sid in [*index['historical_sessions'],*index.get('historical_acquisitions',{})]:
  run=subprocess.run([sys.executable,__file__,sid],capture_output=True,text=True);logs.append(dict(session_id=sid,returncode=run.returncode,output=run.stdout,error=run.stderr))
  if run.returncode==0:results+=json.loads((OUT/'source-checks'/(sid+'.json')).read_text())['checks']
 (OUT/'source-check-execution.json').write_text(json.dumps(logs,indent=2))
 (OUT/'source-checks.json').write_text(json.dumps(dict(records=len(results),checks=results),sort_keys=True,indent=2)+'\n')
 print('Exact source records checked:',len(results),'failures:',sum(r['returncode']!=0 for r in logs))
 sys.exit(any(r['returncode'] for r in logs))
session_id=sys.argv[1]
names=index['historical_sessions'].get(session_id,index.get('historical_acquisitions',{}).get(session_id,[]))
needed={(v,p['body_sha256']) for name in names for v,s in json.loads((DIRECTORY/name).read_text())['sources'].items() for p in s['provenance']}
for p in (OUT/'sessions').glob('*.json'):
 x=json.loads(p.read_text())
 if x['session_id']!=session_id:continue
 rows=verified(x['folder'])['rows']
 for cursor,row in enumerate(rows,1):
  if row['type'] not in ('prediction_discovery_http','prediction_http') or (row['source'],row['body_sha256']) not in needed:continue
  raw=base64.b64decode(row['body_b64']);assert sha256(raw).hexdigest()==row['body_sha256']
  if not row.get('complete') or row.get('status')!=200:continue
  try:body=json.loads(raw)
  except ValueError:continue
  receipts[(x['session_id'],row['source'],row['body_sha256'])]=body
for x in json.loads((OUT/'standalone-discovery.json').read_text()):
 aid='discovery-'+x['journal_sha256'][:24]
 if aid!=session_id:continue
 for row in reopen(x['path'])['rows']:
  if row['type']!='prediction_discovery_http' or not row.get('complete') or row.get('status')!=200:continue
  receipts[(aid,row['source'],row['body_sha256'])]=json.loads(base64.b64decode(row['body_b64']))
for name in names:
 r=json.loads((DIRECTORY/name).read_text());sid=r.get('historical_session_id') or r.get('historical_acquisition_id') or '3363b035-4a97-43df-bae8-57426e873514';checks=[]
 for venue,s in r['sources'].items():
  bodies=[receipts[(sid,venue,p['body_sha256'])] for p in s['provenance']]
  events=[e for b in bodies for e in b.get('events',[]) if str(e.get('event_ticker' if venue=='kalshi' else 'id'))==s['event_id']]
  markets=[m for b in bodies for m in b.get('markets',[])+[m for e in b.get('events',[]) if str(e.get('id'))==s['event_id'] for m in e.get('markets',[])] if str(m.get('ticker' if venue=='kalshi' else 'id'))==s['market_id']]
  assert any(stable(m)==s['native_metadata_sha256'] for m in markets),(name,'market metadata not present in original bytes')
  assert any(stable(e)==s['event_metadata_sha256'] for e in events),(name,'event metadata not present in original bytes')
  event=next(e for e in events if stable(e)==s['event_metadata_sha256'])
  if venue=='kalshi':
   starts={m['start_date'] for b in bodies for m in b.get('milestones',[]) if s['event_id'] in m.get('related_event_tickers',[]) and m.get('category')=='Sports'}
   from app.dashboard.session_projection import stamp
   assert {stamp(t) for t in starts}=={stamp(r['event'][0])},(name,'Native milestone schedule differs')
  else:
   from app.dashboard.session_projection import stamp
   assert stamp(event.get('startTime') or event['startDate'])==stamp(r['event'][0]),(name,'US native schedule differs')
  m=next(m for m in markets if stable(m)==s['native_metadata_sha256'])
  if venue=='kalshi':
   assert m['event_ticker']==s['event_id'];assert m['market_type']=='binary';assert set(s['outcomes'])=={'yes','no'};assert s['outcomes']['yes']['predicate']=='win';assert s['outcomes']['no']['predicate']=='not_win'
   assert 'If '+r.get('sources',{})['kalshi']['orientation_evidence'].get('rules_primary',m['rules_primary']).split('If ',1)[-1].split(' wins',1)[0]+' wins' in m['rules_primary']
  else:
   assert set(s['outcomes'])=={str(side['id']) for side in m['marketSides']}
   for side in m['marketSides']:
    o=s['outcomes'][str(side['id'])];assert str(side['marketId'])==s['market_id'];assert str(side['teamId'])==str(side['team']['id']);assert o['native_direction']==('long' if side['long'] else 'short')
  checks.append(dict(venue=venue,event_id=s['event_id'],market_id=s['market_id'],outcome_ids=sorted(s['outcomes']),complete_source_metadata=True))
 sources.append(dict(record=name,sha256=r['sha256'],source=sid,checks=checks))
(OUT/'source-checks'/(session_id+'.json')).write_text(json.dumps(dict(records=len(sources),checks=sources),sort_keys=True,indent=2)+'\n');print('Exact source records checked:',len(sources))
