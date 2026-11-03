"""Observe a fixed publication cohort separately from live arrivals; no acquisition."""
import sys,json,time
from pathlib import Path
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect
from app.storage.current_games import engine_binding,observation_binding

def snapshot():
 with connect() as db,db.transaction():
  db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
  at=db.execute('select transaction_timestamp()::text at').fetchone()['at']
  rows=db.execute("""select b.game_key,b.publication_events,b.calculated_at,b.observation_as_of,
      b.facts#>>'{context,engine_binding}' engine,b.facts->>'observation_binding' observation,
      b.facts#>>'{estimate_availability,state}' state from latest_board b
      where exists(select 1 from latest_board_status s,jsonb_array_elements(s.facts->'games') g
       where g->>'game_key'=b.game_key and (g->>'start_at')::timestamptz>=now()
        and (g->>'start_at')::timestamptz<now()+interval '72 hours')""").fetchall()
  attempts=db.execute('select event_id,branch,first_attempt::text,last_attempt::text,attempts,disposition,reason,elapsed_ms,engine,facts from current_pipeline_attempt').fetchall()
  inputs=db.execute("""SELECT e.id,e.provider,e.competition,e.scheduled_start,e.revision,
      encode(sha256(convert_to(COALESCE((SELECT string_agg(c.id||o.revision,',' ORDER BY c.id)
        FROM current_contract c JOIN current_offer o ON o.contract_id=c.id WHERE c.event_id=e.id),'') ||
        COALESCE((SELECT string_agg(b.native_market_id||b.revision,',' ORDER BY b.native_market_id)
        FROM current_native_book b WHERE b.event_id=e.id),''),'UTF8')),'hex') inputs
      FROM current_event e WHERE e.scheduled_start::timestamptz>=now()
        AND e.scheduled_start::timestamptz<now()+interval '72 hours'
        AND EXISTS(SELECT 1 FROM current_contract c JOIN current_offer o ON o.contract_id=c.id WHERE c.event_id=e.id)""").fetchall()
  runtime=db.execute('select runtime_id,heartbeat_at::text,status,global_stopped,paused_sources from data_runtime').fetchone()
 return dict(at=at,rows=rows,attempts=attempts,runtime=runtime,inputs=inputs)

def run(path,samples=7,interval=20):
 engine=engine_binding();obs=observation_binding();cohort=None;records=[];input_cohort=None
 for i in range(samples):
  v=snapshot();rows={r['game_key']:r for r in v['rows']}
  if cohort is None:cohort=rows
  if input_cohort is None:input_cohort={r['id']:r for r in v['inputs']}
  current_inputs={r['id']:r for r in v['inputs']}
  stable={eid for eid,r in input_cohort.items() if eid in current_inputs and
      (r['revision'],r['inputs'])==(current_inputs[eid]['revision'],current_inputs[eid]['inputs'])}
  current_events={eid for r in rows.values() if r['engine']==engine for eid in r['publication_events'] or []}
  fixed=[rows[k] for k in cohort if k in rows]
  summary=dict(sample=i,at=v['at'],engine_unchanged=engine_binding()==engine,cohort=len(cohort),remaining=len(fixed),
    engine_current=sum(r['engine']==engine for r in fixed),observation_current=sum(r['observation']==obs for r in fixed),
    arrivals=len(rows.keys()-cohort.keys()),retired=len(cohort.keys()-rows.keys()),
    advanced=sum(r['calculated_at']!=cohort[r['game_key']]['calculated_at'] for r in fixed),
    input_events=len(input_cohort),stable_input_events=len(stable),stable_current_engine_events=len(stable & current_events),
    changed_input_events=len(input_cohort.keys() & current_inputs.keys())-len(stable),
    new_input_events=len(current_inputs.keys()-input_cohort.keys()),retired_input_events=len(input_cohort.keys()-current_inputs.keys()),
    attempt_reasons=dict(Counter(r['branch']+':'+r['reason'] for r in v['attempts'])))
  v['summary']=summary;records.append(v)
  Path(path).write_text(json.dumps(dict(engine=engine,observation=obs,cohort=cohort,records=records),indent=2))
  print(json.dumps(summary),flush=True)
  if i<samples-1:time.sleep(interval)
if __name__=='__main__':run(sys.argv[1],int(sys.argv[2]) if len(sys.argv)>2 else 7)
