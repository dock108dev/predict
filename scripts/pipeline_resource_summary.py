"""Summarize retained monitor samples without confusing high-water and current RSS."""
import json,sys,statistics
from pathlib import Path

def distribution(values):
 values=sorted(values)
 return dict(samples=len(values),minimum=min(values,default=None),median=statistics.median(values) if values else None,
  p95=values[min(len(values)-1,int(len(values)*.95))] if values else None,maximum=max(values,default=None))

def run(source,ingress,target):
 records=json.loads(Path(source).read_text())['records'];samples=[json.loads(line) for line in Path(ingress).read_text().splitlines() if line]
 coverage={};resident={};transfers={};attempts={};preparations={}
 for r in records:
  b=r.get('background') or {};c=b.get('coverage_progress') or {}
  if c.get('worker_pid'):coverage[c['worker_pid']]=c
  retained=b.get('retained_memory') or {}
  if retained.get('monotonic'):resident[retained['monotonic']]=retained['resident_bytes']
  transfer=b.get('catalog_transfer') or {}
  if transfer:transfers[json.dumps(transfer,sort_keys=True)]=transfer
  for a in r['attempts']:
   if a['branch']=='metrics' and a['engine']==r['engine'] and a['facts'].get('timings'):
    attempts[json.dumps(a['facts'],sort_keys=True)]=a
 for r in samples:
  for p in (r.get('sink') or {}).get('recent_preparations',[]):
   preparations[(p.get('source'),p.get('type'),p.get('phase_started'))]=p
 native=[p for p in preparations.values() if p.get('type')=='prediction_books']
 timings={}
 for a in attempts.values():
  for k,v in a['facts'].get('timings',{}).items():timings.setdefault(k,[]).append(v)
  for k in ('validation_ms','ingress_lock_wait_ms'):
   v=a['facts'].get('publication_trace',{}).get(k)
   if v is not None:timings.setdefault(k,[]).append(v)
 sources={}
 for source_name in ('kalshi','polymarket_us','the_odds_api'):
  values=[r.get('sources',{}).get(source_name,{}) for r in samples]
  sources[source_name]={k:distribution([v[k] for v in values if v.get(k) is not None]) for k in
   ('raw_oldest_pending_seconds','derived_oldest_pending_seconds','pending_books')}
  sources[source_name]['final']=values[-1] if values else None
 out=dict(interval=[records[0]['at'],records[-1]['at']],
  owner_highwater_bytes=max((r.get('resources') or {}).get('sampled_rss_bytes',0) for r in records),
  owner_current_resident_bytes=distribution(list(resident.values())),coverage_completed=list(coverage.values()),
  catalog_transfer_observations=list(transfers.values()),
  final_background=records[-1]['background'],source_backlogs=sources,
  native_admissions=dict(observed_unique=len(native),maximum_scopes=max((p.get('scopes',0) for p in native),default=None),
   preparation_seconds=distribution([p['seconds'] for p in native]),
   sql_admission_seconds=distribution([p['timings']['sql_admission'] for p in native if 'sql_admission' in p.get('timings',{})])),
  observed_component_attempt_timings_ms={k:distribution(v) for k,v in timings.items()},
  database_bytes=distribution([r['database']['sql_bytes'] for r in samples if (r.get('database') or {}).get('sql_bytes')]),
  limits=['Periodic samples can miss peaks, short reservations and completed workers.',
   'Owner high-water is lifetime getrusage; retained-memory resident samples are current process RSS.',
   'SQL admission duration includes lock waiting and preparation; it is not exclusive lock-hold duration.',
   'Attempt timing observations are deduplicated by identical stored facts shared by component members. Ledger identities remain the throughput unit.'])
 Path(target).write_text(json.dumps(out,indent=2))
 print('owner highwater',out['owner_highwater_bytes'],'observed coverage completions',len(coverage),'observed native admissions',len(native))

if __name__=='__main__':run(*sys.argv[1:])
