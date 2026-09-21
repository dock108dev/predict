from pathlib import Path
import json,hashlib,collections,base64
from app.collection.transport_session import reopen
from app.collection.journal_encoding import encode
from app.reference.records import packed
from app.dashboard.coverage_owner import replay_groups
from app.dashboard.bounds import retained_bytes
from tests.test_journal_efficiency import ORIGINAL
out=Path('evidence/d2-coverage/record-capacity-decision-20260916');sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
prior={str(p):sha(p) for p in Path('evidence').rglob('*') if p.is_file() and out not in p.parents};(out/'prior-sha256.json').write_text(json.dumps(prior,indent=2))
saved=reopen(ORIGINAL);rows=saved['rows'];states={};transition=[];repeat=[];frame=collections.Counter()
for r in rows:
 if r['type']=='source_health':
  key=r.get('stream_group',r['source']);v={k:r.get(k) for k in ('state','market_ids','gap_reason')}
  (repeat if states.get(key)==v else transition).append(r);states[key]=v
 if r['type']=='prediction_frame':
  d=json.loads(base64.b64decode(r['body_b64']));frame[(r['source'],d.get('type',d.get('subscriptionType','unknown')))]+=1
original=[r for r in rows if r['type']!='session_finished'];repids={r['ingress_id'] for r in repeat}
variants={'all_original':original,'hypothetical_no_repeated_health':[r for r in original if r.get('ingress_id') not in repids],'hypothetical_native_plus_transitions':[r for r in original if r.get('ingress_id') not in repids and r['type']!='prediction_book']}
metrics={k:dict(logical_rows=len(rs),physical_envelopes=len(rs)+1,encoded_ingress=sum(len(packed(encode(r)).encode()) for r in rs),expanded_payload=sum(len(packed(r).encode()) for r in rs),note='hypothetical omissions not permitted for original identities; reconstruction metadata excluded from this optimistic lower bound' if k!='all_original' else 'actual retained ingress') for k,rs in variants.items()}
replay=replay_groups(saved)
# Explicitly repeated workload pressure, with counts derived rather than temporal extrapolation.
pressure=[]
for n in (1,2,4,8):
 pressure.append(dict(repetitions=n,logical_ingress=n*1914,physical_with_one_terminal=n*1914+1,encoded_ingress=n*metrics['all_original']['encoded_ingress'],expanded=n*metrics['all_original']['expanded_payload'],minimum_replay_reservation=6*n*metrics['all_original']['expanded_payload'],classification='arithmetic repetition, not additional live history or duration forecast'))
result=dict(frame_types={str(k):v for k,v in frame.items()},health_state_changes=len(transition),same_state_notifications=len(repeat),health_transition_ids=[r['ingress_id'] for r in transition],repeated_health_ids=[r['ingress_id'] for r in repeat],variants=metrics,pressure=pressure,expanded_python_rows_bytes=retained_bytes(rows),exact_replay=replay)
(out/'workload-analysis.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('exact_replay','health_transition_ids','repeated_health_ids')},indent=2))
