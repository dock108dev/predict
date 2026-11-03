"""Fixed source/cohort and semantic generation observation; never dispatches providers."""
import sys,json,time
from pathlib import Path
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,hashed,stamp
from app.storage.current_games import engine_binding,observation_binding,utc
from app.storage import observation_publication as p
from app.storage.latest_board import runtime,source_states,runtime_identity
from app.comparison.estimated_policy import load


def snapshot(*, include_fields=False):
 with connect() as db,db.transaction():
  db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
  at=utc();owner=runtime(db)
  states=source_states({r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()},owner)
  engine=engine_binding();policy=load().revision
  offered=db.execute("""SELECT e.id,e.provider,e.native_event_id,e.competition,e.scheduled_start,e.revision,
     count(*) offers,array_agg(DISTINCT c.facts#>>'{market_identity,family}') families
     FROM current_event e JOIN current_contract c ON c.event_id=e.id JOIN current_offer o ON o.contract_id=c.id
     WHERE e.scheduled_start::timestamptz>=now() AND e.scheduled_start::timestamptz<now()+interval '72 hours'
     AND c.venue<>'pinnacle' GROUP BY e.id""").fetchall()
  frame=p.capture(db,states,compact='lazy',selector=dict(events=[r['id'] for r in offered],occurrences=[],shared=[]))
  signatures={};clocks={};facts=[]
  for row in offered:
   ids=tuple(r[0] for r in p.neighborhood(frame,dict(events=[row['id']],occurrences=[],shared=[])))
   if ids not in signatures:
    values=[(cid,p.own(frame,cid),p.metric_identity(frame,cid),
      None if not o['source_at'] else (stamp(at)-stamp(o['source_at'])).total_seconds()>900)
      for cid,o in frame['offers'].items() if o['event_id'] in ids]
    signatures[ids]=hashed([engine,policy,frame['epoch'],p.neighborhood(frame,dict(events=list(ids),occurrences=[],shared=[])),values])
   facts.append(dict(row,component=list(ids),semantic_revision=signatures[ids]))
  pubs=db.execute("""SELECT game_key,publication_events,calculated_at,observation_as_of,economic_revision,
      facts#>>'{context,engine_binding}' engine,facts->>'generation_id' generation,
      facts->'financial_dependencies' financial,facts->'publication_dependencies' dependencies,
      facts->>'valid_until' valid_until,facts->>'retained_financial_only' retained_only,
      facts->'estimate_availability' availability
      FROM latest_board""").fetchall()
  catalog=db.execute('SELECT facts FROM latest_board_status').fetchone()
  selected={g['game_key'] for g in catalog['facts']['games']} if catalog else set()
  for row in pubs:
   row['selected']=row['game_key'] in selected
   proof=row.pop('financial') or row['dependencies'];row.pop('dependencies')
   checks=p.reasons(frame,proof) if proof else {'all':['missing_publication_manifest'],'observations':{},'comparisons':{}}
   row['dependency_failures']={k:(len([v for v in vals.values() if v]) if isinstance(vals,dict) else vals) for k,vals in checks.items()}
   row['dependency_current']=not(checks['all'] or any(checks['observations'].values()) or any(checks['comparisons'].values()))
  attempts=db.execute('SELECT event_id,branch,first_attempt::text,last_attempt::text,attempts,disposition,reason,elapsed_ms,engine,facts FROM current_pipeline_attempt').fetchall()
  generations=db.execute('SELECT *,admitted_at::text admitted_at,last_attempt::text last_attempt,completed_at::text completed_at,published_at::text published_at FROM pipeline_generation').fetchall()
  runtime_status=owner.get('status',{})
  bg=runtime_status.get('background_work',{});bg={k:v for k,v in bg.items() if k!='loop_progress'}
  extra={}
  if include_fields:
   extra['field_rows']=db.execute('''SELECT c.id,c.event_id,o.price_value,o.price_units,o.source_at,o.received_at,
       c.contract_dependency,c.metric_dependency,o.revision,
       b.depth_revision,b.state,b.sync,b.received_at book_received_at
       FROM current_contract c JOIN current_offer o ON o.contract_id=c.id
       LEFT JOIN current_native_book b ON b.venue=c.venue AND b.event_id=c.event_id AND b.native_market_id=c.native_market_id
       WHERE c.event_id=ANY(%s)''',([r['id'] for r in offered],)).fetchall()
   extra['database_bytes']=db.execute('SELECT pg_database_size(current_database()) n').fetchone()['n']
   extra['snapshot_finished_at']=utc()
  return dict(**extra,at=at,engine=engine,policy=policy,observation=observation_binding(),events=facts,publications=pubs,attempts=attempts,generations=generations,
    runtime=runtime_identity(owner),heartbeat=owner.get('heartbeat_at'),resources=runtime_status.get('resources'),background=bg,
    calculations=runtime_status.get('background_calculations'),metrics=runtime_status.get('metrics'),
    ingress=runtime_status.get('ingress'),sink=runtime_status.get('sink'),
    maintenance=runtime_status.get('database'),
    source_workers=[{k:r.get(k) for k in ('source','state','metrics','queue','derived_queue','pending','reason_code')}
        for r in runtime_status.get('sources',[]) if isinstance(r,dict)] if isinstance(runtime_status.get('sources'),list) else [],
    source_metrics={k:v.get('metrics') for k,v in runtime_status.get('sources',{}).items()} if isinstance(runtime_status.get('sources'),dict) else {})


def run(path,seconds=1200,interval=20):
 records=json.loads(Path(path).read_text())['records'] if Path(path).exists() else []
 start=time.monotonic();initial=None;stable=None;arrivals_seen=set()
 if records:
  initial={r['id']:r for r in records[0]['events']};stable=set(records[-1]['summary']['stable_ids'])
  start-=(stamp(utc())-stamp(records[0]['at'])).total_seconds()
  arrivals_seen={r['id'] for v in records for r in v['events']}-set(initial)
 while True:
  try:v=snapshot()
  except Exception as exc:
   print(json.dumps(dict(sample_error=type(exc).__name__,message=str(exc)[:160])),flush=True)
   time.sleep(interval);continue
  current={r['id']:r for r in v['events']}
  if initial is None:initial=current;stable=set(current)
  stable={eid for eid in stable if eid in current and current[eid]['semantic_revision']==initial[eid]['semantic_revision']}
  arrivals_seen.update(set(current)-set(initial))
  engine_events={eid for r in v['publications'] if r['engine']==v['engine'] and r['selected'] for eid in r['publication_events'] or []}
  valid_events={eid for r in v['publications'] if r['engine']==v['engine'] and r['selected'] and r['dependency_current'] and r['retained_only']!='true' for eid in r['publication_events'] or []}
  summary=dict(at=v['at'],elapsed=round(time.monotonic()-start,2),initial=len(initial),stable=len(stable),
   stable_engine=len(stable&engine_events),stable_dependency_current=len(stable&valid_events),
   arrivals=len(arrivals_seen),arrivals_still_offered=len(set(current)-set(initial)),current_offered=len(current),current_engine=len(set(current)&engine_events),
   generations=len(v['generations']),generation_dispositions=dict(Counter(r['disposition'] for r in v['generations'])),
   runtime=v['runtime']['runtime_id'],engine=v['engine'],stable_ids=sorted(stable))
  v['summary']=summary;records.append(v)
  Path(path).write_text(json.dumps(dict(records=records),indent=2,default=str))
  print(json.dumps({k:v for k,v in summary.items() if k!='stable_ids'}),flush=True)
  if time.monotonic()-start>=seconds:break
  time.sleep(interval)
if __name__=='__main__':run(sys.argv[1],int(sys.argv[2]) if len(sys.argv)>2 else 1200)
