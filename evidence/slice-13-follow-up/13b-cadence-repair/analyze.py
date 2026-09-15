"""Read saved evidence only; never opens a database or modifies 13A."""
import json
from pathlib import Path
from hashlib import sha256
import statistics

BASE=Path(__file__).resolve().parent
runs=json.loads((BASE/'final-matrix/measurements.json').read_text())
faults=json.loads((BASE/'final-faults/measurements.json').read_text())
frozen=json.loads((BASE.parent/'13a/baseline/measurements.json').read_text())
assert runs['fixture_sha256']==frozen['fixture_sha256']
rows=[]
for r in runs['runs']:
    c=r['accounting']['counts'];n=r['markets_per_venue']
    books=sum(i['kind']=='book' and i['processed'] for i in r['accounting']['items'])
    checks=dict(accounting=all(r['accounting']['gates'].values()),zero_loss=c['rejected']==c['unprocessed']==0,
        side_receipts=c['committed_receipts']==books*2+4*n,
        shutdown=r['shutdown_seconds']<=10,producers=r['producer_close_seconds']<=2,
        database=r['database_bytes']<=256*1024*1024,exact_replay=r['replay_verified']>0,
        exact_receipt_inputs=r['exact_detector_receipt_bindings_verified']>0)
    if r['scenario']=='overflow40':
        checks.update(burst=c['accepted']==41,burst_span=r['input_span_seconds']<=.05)
    if r['scenario']=='burst40':checks['receipt_rate']=r['receipt_throughput']>=8
    # Count only actual collection refreshes after the first producer item starts.
    first=min(i['offered_at'] for i in r['accounting']['items'])
    refresh=[v for v in r['refreshes'] if v['during_collection'] and v['run_start']>=first]
    lat=[v['latency'] for v in refresh]
    starts=[v['run_start'] for v in refresh]
    completion=[v['run_start']+v['latency'] for v in refresh]
    intervals=[b-a for a,b in zip(completion,completion[1:])]
    # Both latency and completion cadence are reported. Quiet/drain intervals do
    # not prove a missed capture view. Any observed active cadence miss fails.
    cadence=dict(target_seconds=.25,latency_max=max(lat,default=0),
        completion_interval_max=max(intervals,default=0),
        prior_view_age_max=max((v['age'] for v in refresh),default=0),
        evaluated_inputs=sum(v['inputs'] for v in r['refreshes']),
        intermediate_evaluations_not_performed=sum(v['coalesced'] for v in r['refreshes']))
    published=[v for v in refresh if v.get('published',False)]
    published_completion=[v['completion_at'] for v in published]
    publication_intervals=[b-a for a,b in zip(published_completion,published_completion[1:])]
    cadence.update(actual_publication_interval_max=max(publication_intervals,default=0),
        published_views=len(published),discarded_completions=sum(not v.get('published',False) for v in refresh),
        input_to_publication_max=max((v.get('input_to_publication_seconds') or 0 for v in refresh),default=0),
        oldest_input_to_publication_max=max((v.get('oldest_input_to_publication_seconds') or 0 for v in refresh),default=0),
        stage_maxima={k:max((v.get(k,0) for v in refresh),default=0) for k in ('snapshot_seconds','scheduling_wait_seconds',
            'detector_seconds','view_seconds','artifact_prepare_seconds','compute_handoff_seconds',
            'persistence_seconds','publication_seconds')})
    checks['actual_publication_cadence']=max(publication_intervals,default=0)<=.25
    checks['new_inputs_only']=all(v['inputs']>0 for v in refresh)
    checks['one_refresh_chain']=r['shutdown_accounting']['refresh_work']['max_inflight']<=1 and r['shutdown_accounting']['refresh_work']['settled']
    checks['view_cadence']=cadence['latency_max']<=.25 and cadence['completion_interval_max']<=.25
    rows.append(dict(markets=n,scenario=r['scenario'],counts=c,checks=checks,cadence=cadence,
        receipt_books_per_second=r['receipt_throughput'],shutdown_seconds=r['shutdown_seconds'],
        queue_retained_bytes=r['retained_queue_bytes_high_water'],stage_summary=r['stage_summary']))
fault_rows=[]
for r in faults['runs']:
    s=r['scenario'];c=r['accounting']['counts']
    expected='interrupted' if s in ('overload','byte_limit') else 'failed' if s in ('receipt_limit','storage_limit','rollback') else 'running' if s in ('database_failure','finalization_failure') else 'complete'
    checks=dict(accounting=all(r['accounting']['gates'].values()),terminal=r['saved_state']['state']==expected,
        stop=r['shutdown_seconds']<=10,producers=r['producer_close_seconds']<=2)
    fault_rows.append(dict(markets=r['markets_per_venue'],scenario=s,counts=c,checks=checks,
        seconds=r['shutdown_seconds'],saved_state=expected,shutdown=r['shutdown_accounting']))
summary=dict(complete=all(all(r['checks'].values()) for r in rows+fault_rows),
    source_identity_sha256=sha256((BASE/'final-matrix/source-identity.json').read_bytes()).hexdigest(),
    fixture_sha256=runs['fixture_sha256'],runs=rows,faults=fault_rows,
    historical_owner_cause='unknown; measurements concern synthetic fixtures only')
(BASE/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(dict(complete=summary['complete'],runs=len(rows),faults=len(fault_rows),
    failed_gates=[dict(markets=r['markets'],scenario=r['scenario'],failed=[k for k,v in r['checks'].items() if not v]) for r in rows+fault_rows if not all(r['checks'].values())]),indent=2))
