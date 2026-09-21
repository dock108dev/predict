from pathlib import Path
import json,base64,hashlib,statistics,collections,datetime
from app.collection.coverage import load_pages,build,stamp
from app.collection.transport_session import reopen
out=Path(Path('.local/d2-replacement-path.txt').read_text().strip());sid=json.load(open(out/'attempt.json'))['session'];folder=out/sid
saved=reopen(folder/(sid+'.jsonl'));rows=saved['rows'];r=json.load(open(folder/'report.json'));manifest=json.load(open(folder/'manifest.json'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert all(sha(folder/p)==h for p,h in manifest['files'].items())
assert saved['sha256']==manifest['journal_chain'] and saved['state']=='complete'
gens={g:[x for x in rows if x.get('discovery_generation')==g and x['type']=='prediction_discovery_http'] for g in (1,2,3)}
audit=dict(session=sid,journal_chain=saved['sha256'],start=rows[0]['observed_at'],end=rows[-1]['observed_at'],duration=r['collection_seconds'],reason=r['reason'],generation={})
for g,records in gens.items():
 ps=[x for x in records if x['path'].endswith(('/events','/markets'))]
 if not ps:continue
 inventory=build(ps,dict(classification='live replacement pilot; retrospective audit',path=str(folder/(sid+'.jsonl')),sha256=sha(folder/(sid+'.jsonl'))),max(stamp(p['received_at']) for p in ps))
 # Preserve raw embedded US observations in an independent projection, without reclassifying them as complete.
 embedded=[p for p in ps if p['source']=='polymarket_us' and p['path'].endswith('/events')]
 embedded_inventory=build(embedded,dict(classification='embedded-only subset of live capture',path=str(folder/(sid+'.jsonl')),sha256=sha(folder/(sid+'.jsonl'))),max(stamp(p['received_at']) for p in ps))['venues']['polymarket_us']
 inventories=[x for x in rows if x['type']=='coverage_inventory' and x['generation']==g]
 audit['generation'][g]=dict(first_request=min(x['started_at'] for x in records),last_receipt=max(x['received_at'] for x in records),published=bool(inventories),
     events={v:len(c['events']) for v,c in inventory['venues'].items()},markets={v:len(c['markets']) for v,c in inventory['venues'].items()},
     embedded_us_counts=embedded_inventory['counts'],embedded_us_market_ids=[m['id'] for m in embedded_inventory['markets']],
     independent_us_market_pages=sum(p['source']=='polymarket_us' and p['path'].endswith('/markets') for p in ps),
     us_completeness_assessment='UNESTABLISHED: empty independent responses contradict retained embedded markets; runtime exhaustion flag is not proof')
 (out/('generation-'+str(g)+'-embedded-us.json')).write_text(json.dumps(embedded_inventory,indent=2))
by_market=collections.defaultdict(list);source=collections.Counter();frames=collections.Counter()
for row in rows:
 if row['type']=='prediction_frame':
  frame=json.loads(base64.b64decode(row['body_b64']));frames[frame.get('type','unknown')]+=1
 if row['type']=='prediction_book' and row['book']['receipt_freshness']=='recent':
  b=row['book'];by_market[b['raw']['ref']['market_id']].append(stamp(b['raw']['received_at']))
  source[b['source_time_progress']]+=1
intervals=[(b-a).total_seconds() for times in by_market.values() for a,b in zip(times,times[1:])]
audit.update(native_frames=dict(frames),market_book_receipt_counts={k:len(v) for k,v in by_market.items()},source_time_progress=dict(source),
 observed_per_market_receipt_intervals_seconds=dict(count=len(intervals),minimum=min(intervals),median=statistics.median(intervals),maximum=max(intervals)),
 preserved_health_transitions=[{k:x.get(k) for k in ('source','observed_at','stream_group','state','gap_reason')} for x in rows if x['type']=='source_health'],
 final_accounting=rows[-1],pilot_directory_bytes=sum(p.stat().st_size for p in folder.iterdir() if p.is_file()),
 manual_stop=dict(verified=False,requested=False,reason='Operator missed requested prompt around 120 seconds; active at 120.52 seconds; resource stop followed at 123.56 seconds'),
 browser_independence=dict(verified=True,basis='Viewing tab closed while running; independent loopback status recorded ongoing REST requests; reopened active viewing tab'),
 completion='incomplete: US market-discovery conflict and manual Stop unverified')
(out/'audit.json').write_text(json.dumps(audit,indent=2))
print(json.dumps({k:v for k,v in audit.items() if k not in ('market_book_receipt_counts','preserved_health_transitions','final_accounting')},indent=2))
