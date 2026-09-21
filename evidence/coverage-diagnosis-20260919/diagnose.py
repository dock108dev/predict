"""Read-only saved-session diagnosis. Run with PYTHONPATH=. .venv/bin/python <this file>."""
import base64, hashlib, json, socket
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter, defaultdict
# No network or credential providers are needed; fail closed on socket creation.
class OfflineSocket(socket.socket):
    def connect(self, *a, **k): raise RuntimeError('offline diagnosis: connect forbidden')
    def connect_ex(self, *a, **k): raise RuntimeError('offline diagnosis: connect forbidden')
socket.socket = OfflineSocket
from app.collection.segmented import SegmentedReader
from app.collection.native_replay import GroupedNativeVerifier
ROOT=Path(__file__).resolve().parents[2]; OUT=Path(__file__).resolve().parent
R=ROOT/'evidence/supervised-5m-live-20260916'
def read(p): return json.loads(p.read_text())
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(n,x): (OUT/n).write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def dt(x): return datetime.fromisoformat(x)
def proof(r): return {k:r.get(k) for k in ('ingress_id','observed_at','received_at','stream_group','type')}
v=read(R/'attempt/validation.json');sid=v['session']; H=R/'attempt'/sid/'history'
assert sid=='aa1a5562-5a5f-4b8c-aee2-6f00eaeabe62'
c=read(R/'candidate.json');assert hashlib.sha256(json.dumps(c['files'],sort_keys=True,separators=(',',':')).encode()).hexdigest()==c['sha256']==v['candidate']
changed=[p for p,h in c['files'].items() if not (ROOT/p).is_file() or digest(ROOT/p)!=h]
assert changed==['app/collection/supervised_live.py','tests/segmented_collector_fixture.py'],changed
manifest=read(H/'manifest.json')
for s in manifest['segments']: assert digest(H/s['name'])==s['sha256']
a=read(R/'analysis.json')
assert digest(H/'manifest.json')==a['exact_history_manifest']
assert digest(H.parent/'manifest.json')==a['exact_replay_manifest']
rows=list(SegmentedReader(H).rows());assert len(rows)==6218
assert all(r['session_id']==sid for r in rows)
assert len({r['ingress_id'] for r in rows if 'ingress_id' in r})==6217
assert all(dt(x['observed_at'])<=dt(y['observed_at']) for x,y in zip(rows,rows[1:]))
verifier=GroupedNativeVerifier('predict-supervised-segmented-5m-v1')
for r in rows:
 if 'body_b64' in r: assert hashlib.sha256(base64.b64decode(r['body_b64'])).hexdigest()==r['body_sha256']
 verifier.feed(r)
replay=verifier.result();assert not any(x['gaps'] for x in replay.values())
save('identity-and-replay.json',dict(session=sid,candidate=c['sha256'],source_files=len(c['files']),subsequent_changed_files=changed,unchanged_behavior_files=[p for p in c['files'] if p.startswith(('app/adapters/','app/collection/')) and p not in changed],history_manifest_sha256=digest(H/'manifest.json'),segments=manifest['segments'],replay=replay,derived_health_books=verifier.derived_health_books))
stop=next(e['utc'] for e in v['events'] if e['action']=='explicit_stop');end=rows[-1]['observed_at']; threshold=rows[0]['spec']['stale_seconds'];assert threshold==30
# Re-evaluate the historical partial-refresh safety predicates using saved pages only.
from app.collection import coverage
from app.collection.continuous import select_inventory
pages=[];generation=None;published=None;safety_checks=[];depth=Counter()
for r in rows:
 if r['type']=='prediction_discovery_http' and r['path'].endswith(('/events','/markets')):
  if r['discovery_generation']!=generation:pages=[];generation=r['discovery_generation']
  pages.append(r)
  if published:
   venue=r['source'];partial=coverage.catalog(pages,venue,dt(r['observed_at']))
   events={e['id']:e for e in partial['events']};prior={e['id']:e for e in published[venue]['events']};mm={m['id']:m for m in partial['markets']}
   blocked=[]
   for m in published[venue]['markets']:
    e=events.get(m['event_id']);reason=mm.get(m['id'],{}).get('exclusion')
    if e and (e['exclusion'] or e['scheduled_start']!=prior[e['id']]['scheduled_start']):reason='observed_event_closure_or_schedule_change'
    if reason:blocked.append([m['id'],reason])
   assert not blocked
   safety_checks.append(proof(r))
 if r['type']=='coverage_inventory':
  published=r['inventory']
  for venue,cat in published.items():
   ids,_=select_inventory(json.loads(json.dumps(cat)),dt(stop))
   assert set(ids)==set(cat['selection']['ids'])
 if r['type']=='prediction_book' and r['book']['receipt_freshness']=='recent':
  for i,o in enumerate(r['book']['outcomes']):
   for side in ('asks','bids'):
    ladder=o.get(side)
    depth[(r['source'],i,side,'missing' if ladder is None else ('empty' if not ladder['levels'] else 'populated'),None if ladder is None else ladder['depth'])]+=1
save('catalog-and-depth.json',dict(partial_refresh_safety_checks=safety_checks,all_partial_safety_exclusions_empty=True,both_generation_selections_eligible_at_stop=True,native_ladders=[dict(venue=k[0],outcome_index=k[1],side=k[2],state=k[3],depth=k[4],observations=n) for k,n in depth.items()]))
markets={}; groups={}; state={'kalshi':set(),'polymarket_us':set()}; timeline=[]; last_frame={};last_native={};frame_types=defaultdict(Counter);health=Counter();inventories=[]; applied=[]
for r in rows:
 venue=r.get('source');typ=r['type'];at=r['observed_at'];group=r.get('stream_group'); before={k:len(x) for k,x in state.items()}
 if typ=='market_selected':
  mid=r['market']['raw']['ref']['market_id'];groups.setdefault(group,[]).append(mid)
  markets[(venue,mid)]=dict(venue=venue,market_id=mid,stream_group=group,selection=proof(r),observations=[],transitions=[],native_updates=0,stale_observations=0,unchanged_native_images=0,source_time_progress={},initially_usable=False)
 if typ=='prediction_frame':
  last_frame[group]=r;raw=json.loads(base64.b64decode(r['body_b64']));frame_types[venue][raw.get('type','marketData' if 'marketData' in raw else 'heartbeat')]+=1
 if typ=='source_health':
  health[(venue,r['state'])]+=1
  if r['state'] in ('disconnected','awaiting_snapshot','ineligible'): state[venue].difference_update(r['market_ids'])
 if typ=='coverage_inventory': inventories.append(r)
 if typ=='coverage_applied': applied.append(r)
 if typ=='prediction_book':
  b=r['book'];mid=b['raw']['ref']['market_id'];m=markets[(venue,mid)];was=mid in state[venue]
  usable=b['sync']=='synchronized' and b['receipt_freshness']=='recent';old=last_native.get((venue,mid)); age=(dt(at)-dt(b['raw']['received_at'])).total_seconds()
  entry=dict(**proof(r),native_received_at=b['raw']['received_at'],exchange_at=b['raw'].get('exchange_at'),sync=b['sync'],receipt_freshness=b['receipt_freshness'],source_time_progress=b['source_time_progress'],age_seconds=age,sequence=b['sequence'],usable=usable)
  if usable:
   f=last_frame[group];entry['native_frame']=proof(f);entry['native_frame_sha256']=f['body_sha256'];entry['kind']=json.loads(base64.b64decode(f['body_b64'])).get('type','marketData')
   m['native_updates']+=1
   entry['unchanged_ladders_from_previous_native']=bool(old and old['book']['outcomes']==b['outcomes'])
   m['unchanged_native_images']+=entry['unchanged_ladders_from_previous_native'];last_native[(venue,mid)]=r
   state[venue].add(mid)
  else:
   entry['cause']='freshness_expiry' if b['receipt_freshness']=='stale' and b['sync']=='synchronized' else 'other'
   entry['prior_native_observation']=proof(old) if old else None
   entry['nominal_expiry_utc']=(dt(b['raw']['received_at'])+timedelta(seconds=threshold)).isoformat()
   entry['expiry_emission_delay_seconds']=age-threshold
   m['stale_observations']+=b['receipt_freshness']=='stale'
   state[venue].discard(mid)
  m['observations'].append(entry)
  if was!=usable: m['transitions'].append(dict(at=at,ingress_id=r['ingress_id'],usable=usable,cause='native_update' if usable else entry['cause']))
 if typ=='session_finished':
  for (venue,mid),m in markets.items():
   m['pre_stop_usable']=mid in state[venue]
   m['pre_stop_reason']='usable' if m['pre_stop_usable'] else m['observations'][-1].get('cause','unknown')
   m['last_native_before_stop']=proof(last_native[(venue,mid)])
   m['last_native_receipt_before_stop']=last_native[(venue,mid)]['book']['raw']['received_at']
   m['age_at_stop_seconds']=(dt(stop)-dt(m['last_native_receipt_before_stop'])).total_seconds()
   m['terminal_usable']=False
  state={k:set() for k in state}
 if before!={k:len(x) for k,x in state.items()}:
  timeline.append(dict(**proof(r),counts={k:len(x) for k,x in state.items()},terminal=typ=='session_finished'))
# Cross-check every retained snapshot and status at their own wall-clock sample boundary.
def counts_at(at):
 out={'kalshi':0,'polymarket_us':0}
 for t in timeline:
  if dt(t['observed_at'])>dt(at): break
  out=t['counts']
 return out
checks=[]
for s in v['snapshots']:
 actual=counts_at(s['at']);expected={k:c['usable'] for k,c in s['coverage'].items()};assert actual==expected,(s['at'],actual,expected)
 checks.append(dict(at=s['at'],counts=actual,source='validation.snapshots'))
for p in sorted(R.glob('status-*.json')):
 s=read(p);at=(dt(s['discovery']['published_at'])+timedelta(seconds=s['discovery']['age_seconds'])).isoformat()
 actual=counts_at(at);expected={k:c['usable'] for k,c in s['coverage'].items()};assert actual==expected,(p.name,actual,expected)
 checks.append(dict(at=at,counts=actual,source=p.name))
 if p.name=='status-initial.json':
  initial=at
  for m in markets.values():m['initially_usable']=next((o['usable'] for o in reversed(m['observations']) if dt(o['observed_at'])<=dt(at)),False)
assert counts_at(stop)=={'kalshi':23,'polymarket_us':29}
assert counts_at(end)=={'kalshi':0,'polymarket_us':0}
for venue in state:
 assert sum(m['pre_stop_usable'] for (ven,mid),m in markets.items() if ven==venue)==v['before_stop']['coverage'][venue]['usable']
 assert set(inventories[0]['inventory'][venue]['selection']['ids'])==set(inventories[1]['inventory'][venue]['selection']['ids'])
# Compare nominal receipt deadline with emitted state; never replace retained usability.
summary={}
for venue in state:
 ms=[m for m in markets.values() if m['venue']==venue];stales=[o for m in ms for o in m['observations'] if not o['usable']]
 assert all(o['cause']=='freshness_expiry' and o['age_seconds']>=30 for o in stales)
 summary[venue]=dict(initial_usable=sum(m['initially_usable'] for m in ms),pre_stop_usable=sum(m['pre_stop_usable'] for m in ms),lost_at_stop=[m['market_id'] for m in ms if not m['pre_stop_usable']],loss_causes=dict(Counter(m['pre_stop_reason'] for m in ms if not m['pre_stop_usable'])),markets_ever_stale=sum(m['stale_observations']>0 for m in ms),stale_observations=len(stales),native_updates=sum(m['native_updates'] for m in ms),unchanged_native_images=sum(m['unchanged_native_images'] for m in ms),frame_types=dict(frame_types[venue]),expiry_emission_delay_range_seconds=[min(o['expiry_emission_delay_seconds'] for o in stales),max(o['expiry_emission_delay_seconds'] for o in stales)],first_stale=min(o['observed_at'] for o in stales),source_time_progress=dict(Counter(o['source_time_progress'] for m in ms for o in m['observations'] if o['usable'])),health=dict((st,n) for (ven,st),n in health.items() if ven==venue),nominally_over_30_but_counted_usable_at_stop=[m['market_id'] for m in ms if m['pre_stop_usable'] and m['age_at_stop_seconds']>30])
 for m in ms:
  obs=m['observations'];m['source_time_progress']=dict(Counter(o['source_time_progress'] for o in obs if o['usable']))
  m['state_intervals']=[]
  ts=[dict(at=m['selection']['observed_at'],ingress_id=m['selection']['ingress_id'],usable=False)]+m['transitions']
  for i,t in enumerate(ts):m['state_intervals'].append(dict(start=t['at'],end=ts[i+1]['at'] if i+1<len(ts) else stop,usable=t['usable'],start_ingress_id=t['ingress_id'],basis='retained event-driven collector state, not proof of upstream continuity'))
save('per-market.json',dict(session=sid,freshness_seconds=threshold,interval_boundary='right-continuous admission events; exact runtime mutation follows emit; sub-event latency unavailable; stop to terminal cleanup is not reconstructed',markets=list(markets.values())))
save('coverage-timeline.json',dict(session=sid,start=rows[0]['observed_at'],stop=stop,terminal=end,initial_checkpoint=initial,snapshot_window=[v['snapshots'][0]['at'],v['snapshots'][-1]['at']],events=timeline,matched_checkpoints=checks))
save('summary.json',dict(session=sid,venues=summary,row_counts=dict(Counter(r['type'] for r in rows)),applied=[{k:r[k] for k in ('ingress_id','observed_at','source','generation','usable','selected_ids','stream_groups')} for r in applied],stop=stop,terminal=end,matched_checkpoints=len(checks),replay_native_books=sum(sum(x['exact_native_books'].values()) for x in replay.values()),replay_derived_health_books=verifier.derived_health_books))
print(json.dumps(summary,indent=2))
