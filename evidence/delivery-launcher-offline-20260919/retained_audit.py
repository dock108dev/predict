"""Read-only old inputs; new report path must not exist."""
import json,resource,signal,time
from pathlib import Path
from tests.delivery_fixture import NetworkGuard
from app.collection.delivery_analysis import analyze
resource.setrlimit(resource.RLIMIT_CPU,(60,60));signal.alarm(60)
began=time.monotonic();root=Path('evidence/upstream-diagnostic-offline-20260919')
with NetworkGuard():
 direct=analyze(root/'direct/history');saved=json.loads((root/'direct/analysis.json').read_text())
 assert {k:v for k,v in direct.items() if k!='replay_state_peak'}=={k:v for k,v in saved.items() if k!='replay_state_peak'}
 assert direct['replay_state_peak']<=48*1024**2 and saved['replay_state_peak']<=48*1024**2
 cutoff=analyze(root/'cutoff/history');assert not cutoff['complete']
 assert all(c['classification']=='insufficient_evidence' for c in cutoff['comparisons'])
 result=dict(direct_deterministic_fields_identical=True,direct_frames=direct['native_frames'],cutoff_complete=False,direct_replay_state_bytes=direct['replay_state_peak'],cutoff_replay_state_bytes=cutoff.get('replay_state_peak'),cutoff_unavailable_metrics_remain_unknown=True,wall_seconds=time.monotonic()-began,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
 assert result['peak_rss_bytes']<256*1024**2
 with Path('evidence/delivery-launcher-offline-20260919/retained-audit-final.json').open('x') as f:json.dump(result,f,indent=2)
 print(json.dumps(result))
