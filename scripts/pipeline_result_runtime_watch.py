"""Bounded allowlisted runtime/queue supplement to fixed unit sampling."""
import json,sys,time
from pathlib import Path
from datetime import timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,stamp
from app.storage.latest_board import runtime
from app.storage.current_games import utc

start=json.loads(Path(sys.argv[1]).read_text())['at'];end=stamp(start)+timedelta(seconds=float(sys.argv[3]) if len(sys.argv)>3 else 1510)
ids=[r['source_event_id'] for r in json.loads(Path('test-results/d02-native-delivery/original-68.json').read_text())['rows']]
out=Path(sys.argv[2]);size=0
with out.open('x') as f:
    while stamp(utc())<end:
        with connect() as db:
            r=runtime(db);s=r.get('status',{});q=s.get('quota',{});b=s.get('background_work',{})
            attempts=db.execute("SELECT * FROM current_pipeline_attempt WHERE event_id=ANY(%s)",(ids,)).fetchall()
        value=dict(at=utc(),runtime_id=r['runtime_id'],healthy=r['healthy'],active=r['active'],calculations=r.get('calculations'),
            ingress=s.get('ingress'),background={k:b.get(k) for k in ('progress','loop_progress','counts','waiting','resident_bytes','reserved_bytes','component_admission')},
            resources={k:s.get('resources',{}).get(k) for k in ('sampled_rss_bytes','sampled_highwater_rss_bytes','rss_ceiling_bytes')},
            database=s.get('database'),quota={k:q.get(k) for k in ('blocking_reason','reserved','held_uncertain_credits','used','unresolved_attempts')},
            attempts=attempts)
        data=json.dumps(value,default=str,separators=(',',':'))+'\n';size+=len(data)
        if size>32*1024*1024:raise RuntimeError('runtime_observer_capacity')
        f.write(data);f.flush();time.sleep(10)
print(dict(bytes=size,path=str(out)))
