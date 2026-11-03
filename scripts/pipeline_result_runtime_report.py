"""Summarize bounded runtime observations without claiming exact queue residence."""
import json,sys
from pathlib import Path
from collections import Counter
from datetime import datetime
from pipeline_result_unit_report import distribution
root=Path(sys.argv[1])
rows=[json.loads(x) for x in (root/'accepted-runtime-observations.jsonl').read_text().splitlines()]
delivery=json.loads((root/'delivery-report.json').read_text())
records={json.dumps(r,sort_keys=True):r for s in rows for r in (s.get('ingress') or {}).get('records',[])}
maintenance={json.dumps((s.get('database') or {}).get('maintenance'),sort_keys=True) for s in rows}
missing={d['source_event_id']:d for d in delivery['original_dispositions'] if not d['units_ever_current']}
attempts={a['event_id']:a for s in rows for a in s['attempts'] if a['event_id'] in missing and a['branch']=='estimates'}
# Discover the persisted branch names rather than treating absent estimates as success.
branches=dict(Counter(a['branch'] for a in rows[-1]['attempts']))
if not attempts:
 attempts={a['event_id']:a for s in rows for a in s['attempts'] if a['event_id'] in missing and a['branch']!='raw_grid'}
oldest=sorted(attempts.values(),key=lambda a:a['first_attempt'])
value=dict(start=rows[0]['at'],end=rows[-1]['at'],samples=len(rows),sample_gaps_seconds=distribution([(datetime.fromisoformat(b['at'])-datetime.fromisoformat(a['at'])).total_seconds() for a,b in zip(rows,rows[1:])]),
 ingress_unique_records=len(records),ingress_seconds={k:distribution([r[k] for r in records.values() if isinstance(r.get(k),(int,float))]) for k in ('queue_seconds','prepare_seconds','precompute_seconds','commit_seconds','seconds')},
 resources={k:distribution([s['resources'][k] for s in rows if isinstance(s['resources'].get(k),(int,float))]) for k in rows[-1]['resources']},
 board_states=dict(Counter((s.get('calculations') or {}).get('board') for s in rows)),database_states=dict(Counter((s.get('database') or {}).get('state') for s in rows)),database_errors=sorted({str(s['database']['error']) for s in rows if (s.get('database') or {}).get('error')}),
 maintenance_snapshots=[json.loads(x) for x in sorted(maintenance)],quota_states=[json.loads(x) for x in sorted({json.dumps(s['quota'],sort_keys=True) for s in rows})],
 attempt_branches=branches,oldest_original_without_sampled_current=[dict(native_event_id=missing[a['event_id']]['native_event_id'],source=missing[a['event_id']]['source'],**{k:a[k] for k in ('event_id','branch','first_attempt','last_attempt','attempts','disposition','reason')}) for a in oldest[:5]],
 notes=['Supplement begins after the main fixed observation; exact bounds above.', 'Ingress records are deduplicated bounded operation records, not exhaustive source-to-SQL measurements.', 'Attempt first/last timestamps describe observed scheduler history, not continuous queue residence. A parent passed state does not establish complete result delivery.'])
(root/'runtime-report.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(value,indent=2))
