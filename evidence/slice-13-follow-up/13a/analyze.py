"""Rebuild the compact baseline summary and independently check ledger invariants."""
from collections import Counter
import json
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parent
measurement=json.loads((ROOT/'baseline/measurements.json').read_text())
runs=measurement['runs']
summary=[]
for r in runs:
    accounting=r['accounting'];items=accounting['items'];bindings=accounting['bindings'];counts=accounting['counts']
    bootstrap=[b for b in bindings if b['kind']=='receipt' and b['committed'] and b['item_id'].startswith('bootstrap:')]
    committed=[b for b in bindings if b['kind']=='receipt' and b['committed']]
    checks={**accounting['gates'],
        'one_binding_per_committed_receipt':len(committed)==len({b['id'] for b in committed}),
        'expected_bootstrap_sides':len(bootstrap)==4*r['markets_per_venue'],
        'each_processed_book_two_committed_sides':all(sum(b['kind']=='receipt' and b['committed'] for b in x['writes'])==2 for x in items if x['processed'] and x['kind']=='book'),
        'each_processed_item_one_committed_evaluation':all(sum(b['kind']=='calculation' and b['committed'] for b in x['writes'])==1 for x in items if x['processed']),
        'each_processed_disconnect_committed_event':all(sum(b['kind']=='event' and b['committed'] for b in x['writes'])==1 for x in items if x['processed'] and x['kind']=='disconnect'),
        'queue_matches_explicit_unprocessed':r['remaining_queue']==counts['unprocessed'],
        'side_rows_equal_receipts':counts['retained_per_side_observations']==counts['committed_receipts'],
        'synthetic_session':r['saved_state']['environment']==r['saved_state']['evidence_class']=='synthetic',
        'calculation_bindings_exist':all(x['receipt_id'] in {b['id'] for b in committed} for x in r['calculation_receipt_bindings'])}
    if r['scenario']=='overflow40':checks['known_overflow']=r['expected_failure_reproduced']
    assert all(checks.values()),checks
    stages=[s for s in r['stages'] if s['item_id'].startswith('item:')]
    totals={name:sum(x['seconds'] for x in stages if x['stage']==name) for name in sorted({x['stage'] for x in stages})}
    services=[x['completed_at']-x['worker_started_at'] for x in items if x['processed'] and x['kind']=='book']
    unit_counts={kind:{state:sum(x['kind']==kind and (True if state=='offered' else x[state]) for x in items) for state in ('offered','accepted','processed')} for kind in ('book','disconnect')}
    row=dict(markets=r['markets_per_venue'],scenario=r['scenario'],timing=r['instrumentation_enabled'],
        counts=counts,unit_counts=unit_counts,bootstrap_side_receipts=len(bootstrap),checks=checks,
        book_service_mean=statistics.mean(services),book_service_max=max(services),
        book_service_rate=len(services)/sum(services),queue_high_water=r['queue_high_water'],
        estimated_bytes_high_water=r['queue_bytes_high_water'],oldest_seconds=r['oldest_item_age_max'],
        worker_queue_wait_max=max((x.get('worker_wait_seconds',0) for x in items),default=0),
        accepted_queue_wait_max=max((x.get('queue_wait_seconds',0) for x in items),default=0),
        item_stage_totals=totals,session_stage_summary=r['stage_summary'],
        input_rate=r['input_rate_items_per_second'],input_span=r['input_span_seconds'],elapsed=r['elapsed_seconds'])
    summary.append(row)
assert len(summary)==24, 'full matrix required'
overhead={}
for n in (2,4):
    means={enabled:statistics.mean(r['book_service_mean'] for r in summary if r['markets']==n and r['scenario']=='ordinary' and r['timing']==enabled) for enabled in (True,False)}
    overhead[n]=dict(enabled_mean=means[True],disabled_mean=means[False],difference_fraction=means[True]/means[False]-1,
                    limitation='two sequential trials per arm; measures detailed timers only; ledger, wrappers and guard retained')
(ROOT/'summary.json').write_text(json.dumps(dict(fixture_sha256=measurement['fixture_sha256'],runs=summary,timing_overhead=overhead,
    gate='PASS: all 24 trial ledgers independently reconciled; expected failure remains unfixed'),indent=2)+'\n')
print('PASS: 24 trial ledgers, per-side bindings, control events, calculation links, and known overflow')
for n in (2,4):
    for s in ('ordinary','burst24','overflow40','slow','depth'):
        rows=[r for r in summary if r['markets']==n and r['scenario']==s and r['timing']]
        print(n,s,'processed',[r['counts']['processed'] for r in rows], 'unprocessed',[r['counts']['unprocessed'] for r in rows],
              'book_ms',[round(1000*r['book_service_mean'],1) for r in rows], 'hwm',[r['queue_high_water'] for r in rows])
print('timing_overhead',json.dumps(overhead))
