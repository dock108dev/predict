"""Read-only, individual explanations for all unfinished loaded-engine generations."""
import json,sys
from pathlib import Path
from datetime import timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,stamp
from app.storage.current_games import utc,engine_binding

def run(path):
 with connect() as db,db.transaction():
  db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
  at=utc();engine=engine_binding();now=stamp(at)
  generations=db.execute("SELECT * FROM pipeline_generation WHERE engine=%s AND disposition IN ('eligible_pending','failed','deferred') ORDER BY admitted_at",(engine,)).fetchall()
  events={r['id']:r for r in db.execute("""SELECT e.id,e.provider,e.native_event_id,e.competition,e.scheduled_start,
   EXISTS(SELECT 1 FROM current_contract c JOIN current_offer o ON o.contract_id=c.id WHERE c.event_id=e.id AND c.venue<>'pinnacle') offered
   FROM current_event e""")}
  attempts={r['event_id']:r for r in db.execute("SELECT * FROM current_pipeline_attempt WHERE branch='metrics'")}
  rows=[]
  for g in generations:
   members=[]
   for eid in g['events']:
    event=events.get(eid);start=stamp(event['scheduled_start']) if event and event['scheduled_start'] else None
    eligible=bool(event and event['offered'] and start and now<=start<now+timedelta(hours=72))
    members.append(dict(event=event,source_event_id=eid,offered_in_window=eligible,attempt=attempts.get(eid)))
   rows.append(dict(generation=g,members=members,age_since_capture_seconds=(now-g['admitted_at']).total_seconds(),
    current_window_members=sum(m['offered_in_window'] for m in members),
    stage='publication retry' if g['completed_at'] else 'captured calculation pending',
    owner='app.storage.latest_board.reconcile / app.collection.financial_worker',
    next_action='Recapture the complete current component on its fair scheduling turn; commit only after current dependency validation' if any(m['offered_in_window'] for m in members) else
    'Outside current offered-window eligibility; retain full-inventory rotation and retire only with membership proof',
    limits=['The ledger recovery reason alone does not identify the preceding exception; event-attempt facts retain the recorded rejection.']))
 Path(path).write_text(json.dumps(dict(at=at,engine=engine,rows=rows),indent=2,default=str));print('unfinished generations',len(rows))

if __name__=='__main__':run(sys.argv[1])
