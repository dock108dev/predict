"""Read-only scheduler rank and complete-component lineage at one instant."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,hashed,stamp
from app.storage.board_capture import capture_batches,prioritize_window_waiters,capture_reservation
from app.storage.current_games import utc,engine_binding
with connect() as db,db.transaction():
 db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
 at=utc();groups=capture_batches(db);ordered=prioritize_window_waiters(db,groups,at,observations_only=False)
 events={r['id']:r for r in db.execute('SELECT id,provider,native_event_id,competition,scheduled_start FROM current_event').fetchall()}
 attempts={r['event_id']:r for r in db.execute("SELECT event_id,first_attempt::text,last_attempt::text,attempts,reason,facts FROM current_pipeline_attempt WHERE branch='metrics'").fetchall()}
 pubs=db.execute("SELECT game_key,publication_events,facts#>>'{context,engine_binding}' engine FROM latest_board").fetchall()
 rows=[]
 for rank,ids in enumerate(ordered):
  rows.append(dict(queue_identity=hashed(['metrics',ids]),priority_rank=rank+1,events=[events[eid] for eid in ids],
      attempts=[attempts.get(eid) for eid in ids],publications=[r for r in pubs if set(r['publication_events'] or [])&set(ids)],
      oldest_scheduler_age=max(((stamp(at)-stamp(attempts[eid]['first_attempt'])).total_seconds() for eid in ids if eid in attempts),default=None)))
 out=dict(at=at,engine=engine_binding(),components=len(groups),priority='three turns in four: in-window unfinished engine, then least recently attempted; fourth full-inventory anchor rotation',rows=rows)
 Path(sys.argv[1]).write_text(json.dumps(out,indent=2));print('components',len(groups))
