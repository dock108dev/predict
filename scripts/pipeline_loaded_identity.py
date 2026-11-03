"""Record loaded launch identities and a source-tree witness without acquisition."""
import json,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,hashed
from app.storage.latest_board import runtime
from app.storage.current_games import engine_binding,observation_binding,utc
with connect() as db:r=runtime(db)
root=Path(__file__).resolve().parents[1]
files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root/'app').rglob('*.py'))}
out=dict(at=utc(),engine=engine_binding(),observation=observation_binding(),python_tree=hashed(files),source_files=files,
 runtime={k:r.get(k) for k in ('runtime_id','global_stopped','paused_sources','config','healthy','active','heartbeat_at')},
 processes={role:json.loads((root/path).read_text()) for role,path in [('data','.local/predict-data-runtime/process.json'),('app','.local/opportunity-board-beta/process.json')]})
Path(sys.argv[1]).write_text(json.dumps(out,indent=2));print({k:out[k] for k in ('at','engine','python_tree')});print({k:out['runtime'][k] for k in ('runtime_id','healthy','active','global_stopped','paused_sources')})
