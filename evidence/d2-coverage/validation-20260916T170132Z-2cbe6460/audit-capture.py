from pathlib import Path
import json,hashlib,collections,statistics,fcntl,urllib.request,subprocess
from app.collection.transport_session import reopen
from app.collection.coverage import stamp
out=Path(Path('.local/d2-validation-path.txt').read_text());sid=json.load(open(out/'attempt.json'))['session'];folder=out/sid
report=json.load(open(folder/'report.json'));manifest=json.load(open(folder/'manifest.json'));saved=reopen(folder/(sid+'.jsonl'));rows=saved['rows']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert all(sha(folder/p)==h for p,h in manifest['files'].items());assert saved['state']=='complete';assert saved['sha256']==manifest['journal_chain']
prior=json.load(open(out/'prior-evidence-sha256.json'));changed=[p for p,h in prior.items() if not Path(p).is_file() or sha(Path(p))!=h];assert not changed,changed
v=json.load(open('evidence/d2-coverage/offline-repair-20260916/verification.json'));diff=[p for p,h in v['source_sha256'].items() if sha(Path(p))!=h];assert not diff,diff
f=open(out/'collector.lock','a');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);f.close()
status=json.load(urllib.request.urlopen('http://127.0.0.1:8783/api/status'));assert not status['active'];assert status['cleanup_complete'];assert all(c['usable']==0 for c in status['coverage'].values())
(out/'final-status.json').write_text(json.dumps(status,indent=2))
gens=[dict(generation=r['generation'],at=r['observed_at'],counts={v:dict(events=len(c['events']),markets=len(c['markets']),selection=c['selection'],completeness=c['market_completeness'],event_discovery=c['event_discovery']) for v,c in r['inventory'].items()}) for r in rows if r['type']=='coverage_inventory']
books=collections.defaultdict(list);progress=collections.Counter();http=collections.Counter();health=collections.Counter();frames=collections.Counter()
for r in rows:
 if r['type']=='prediction_discovery_http':http[r['source']]+=1
 if r['type']=='source_health':health[(r['source'],r['state'])]+=1
 if r['type']=='prediction_frame':frames[r['source']]+=1
 if r['type']=='prediction_book' and r['book']['receipt_freshness']=='recent':
  b=r['book'];books[(r['source'],b['raw']['ref']['market_id'])].append(stamp(b['raw']['received_at']));progress[(r['source'],b['source_time_progress'])]+=1
intervals={v:[(b-a).total_seconds() for (venue,m),times in books.items() if venue==v for a,b in zip(times,times[1:])] for v in ('kalshi','polymarket_us')}
result=dict(session=sid,candidate=v['candidate_identity_sha256'],source_differences=diff,prior_files_verified=len(prior),prior_changes=changed,journal_chain=saved['sha256'],journal_state=saved['state'],start=rows[0]['observed_at'],end=rows[-1]['observed_at'],generations=gens,durable_http=dict(http),frames=dict(frames),source_time_progress={str(k):n for k,n in progress.items()},health={str(k):n for k,n in health.items()},gaps={v:dict(count=len(ns),median=statistics.median(ns) if ns else None,maximum=max(ns) if ns else None) for v,ns in intervals.items()},terminal=rows[-1],shared_lock_free=True,manifest_valid=True,pilot_directory_bytes=sum(p.stat().st_size for p in folder.iterdir() if p.is_file()),report=report,replay=json.load(open(folder/'replay.json')))
(out/'audit.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:val for k,val in result.items() if k not in ('report','terminal','generations','replay')},indent=2));print('REPORT',report['reason'],report['collection_seconds'],report['resources'],report['accounting']);print('REPLAY',result['replay'])
