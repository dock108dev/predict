"""Allowlisted runtime/control/account summary; never emits account identifiers."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect
from app.storage.latest_board import runtime
from app.storage.current_games import utc

with connect() as db:r=runtime(db)
s=r.get('status',{});q=s.get('quota',{})
result=dict(at=utc(),runtime={k:r.get(k) for k in ('runtime_id','healthy','active','heartbeat_at','global_stopped','paused_sources','calculations')},
    quota={k:q.get(k) for k in ('blocking_reason','reserved','held_uncertain_credits','used','ceiling','available','remaining')},
    unresolved_attempt_count=q.get('unresolved_attempts'),
    database={k:s.get('database',{}).get(k) for k in ('state','error','sql_bytes','sql_byte_cap','pending_calculations','maintenance')},
    sources=[{k:p.get(k) for k in ('provider','status','worker_done','processing_phase','socket_connected','last_book_receipt_at','last_book_observation_at','metrics')} for p in s.get('sources',[])],
    resources=s.get('resources'),background_work=s.get('background_work'),cleanup_errors=s.get('cleanup_errors'))
Path(sys.argv[1]).write_text(json.dumps(result,indent=2,default=str)+'\n')
print(json.dumps({k:result[k] for k in ('at','runtime','quota','unresolved_attempt_count')},default=str))
