import sys,json,base64
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime
sys.path.insert(0,str(Path.cwd()))
from app.collection.segmented import SegmentedReader,digest_file
root=Path(__file__).resolve().parent
v=json.loads((root/'attempt/validation.json').read_text());folder=root/'attempt'/v['session']
rest=defaultdict(list);health=defaultdict(Counter);inventories=[];applied=[];frames=Counter();wire=Counter();packets=0;gaps=[];books=defaultdict(Counter);account=[];terminal=None;start=None;flow=defaultdict(Counter)
from app.collection.journal_encoding import encode
from app.reference.records import packed
for row in SegmentedReader(folder/'history').rows():
 typ=row['type'];venue=row.get('source')
 if typ=='session_started':start=row['observed_at']
 if typ=='prediction_discovery_http':
  rest[venue].append({k:row.get(k) for k in ('started_at','received_at','path','params','status','complete','requests')})
  wire[venue+'_rest']+=len(base64.b64decode(row['body_b64']))
 if typ=='source_health':health[venue][row['state']]+=1
 if typ=='coverage_inventory':inventories.append(dict(generation=row['generation'],at=row['observed_at'],inventory=row['inventory']))
 if typ=='coverage_applied':applied.append({k:row.get(k) for k in ('generation','source','observed_at','selected_ids','stream_groups','usable')})
 if typ=='prediction_frame':
  frames[venue]+=1;wire[venue+'_frame']+=len(base64.b64decode(row['body_b64']))
  flow[venue]['encoded']+=len(packed(encode(row)).encode());flow[venue]['expanded']+=len(packed(row).encode())
 if typ=='prediction_book':packets+=len(row['packets']);books[venue][row['book']['receipt_freshness']]+=1
 if 'gap' in typ:gaps.append({k:val for k,val in row.items() if k not in ('body_b64','body')})
 if typ=='verified_account_budget':account.append(row)
 if typ=='session_finished':terminal=row
summary={}
for venue,rs in rest.items():
 stamps=[datetime.fromisoformat(r['started_at']) for r in rs]
 summary[venue]=dict(attempts=len(rs),minimum_start_interval=min((b-a).total_seconds() for a,b in zip(stamps,stamps[1:])),statuses=dict(Counter(r['status'] for r in rs)),incomplete=sum(not r['complete'] for r in rs))
changes={}
for venue in ('kalshi','polymarket_us'):
 first=inventories[0]['inventory'][venue];second=inventories[-1]['inventory'][venue]
 a={r['id'] for r in first['markets']};b={r['id'] for r in second['markets']}
 changes[venue]=dict(added=sorted(b-a),removed=sorted(a-b),initial_counts=first['counts'],refreshed_counts=second['counts'],selection_changes=sorted(set(first['selection']['ids'])^set(second['selection']['ids'])),exclusions=dict(Counter(r.get('subscription_exclusion') or 'none' for r in second['markets'])))
result=dict(session=v['session'],session_started_row_utc=start,events=v['events'],rest_summary=summary,request_timestamps=rest,
 health_observations={k:dict(c) for k,c in health.items()},frames=frames,wire_bytes=wire,frame_serialization_bytes=flow,books=books,packets=packets,gaps=gaps,
 inventories=inventories,applied=applied,changes=changes,account_pacing=account,terminal=terminal,
 actual_attempt_output_bytes=sum(p.stat().st_size for p in (root/'attempt').rglob('*') if p.is_file()),
 validation_bytes=(root/'attempt/validation.json').stat().st_size,
 exact_replay_manifest=digest_file(folder/'manifest.json'),exact_history_manifest=digest_file(folder/'history/manifest.json'))
(root/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ('session_started_row_utc','events','rest_summary','health_observations','frames','wire_bytes','frame_serialization_bytes','books','packets','gaps','changes','actual_attempt_output_bytes','validation_bytes')},indent=2))
