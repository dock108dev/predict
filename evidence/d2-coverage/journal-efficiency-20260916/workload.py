"""Read-only original capture reproduction. Output is derived, not new history."""
from pathlib import Path
import json,time,resource,sys,collections
from app.collection.transport_session import ObservationJournal,reopen
from app.collection.journal_encoding import VERSION
from app.reference.records import packed
from app.dashboard.bounds import CaptureQueue
from tests.test_journal_efficiency import ORIGINAL
OUT=Path(__file__).resolve().parent
saved=reopen(ORIGINAL);version=VERSION if sys.argv[1]=='encoded' else None
j=ObservationJournal(OUT/(sys.argv[1]+'.jsonl'),encoding=version);q=CaptureQueue(48,4*1024*1024)
start=time.monotonic();cpu=time.process_time();n=0;count=0;types=collections.defaultdict(lambda:dict(records=0,bytes=0))
for row in saved['rows']:
 size=len(packed(j.encoded(row)).encode())
 if row['type']!='session_finished':
  assert count<2048 and n+size<=16*1024*1024
  n+=size;count+=1
 j.save(row);q.put_nowait(row);q.get_nowait();q.task_done()
 types[row['type']]['bytes']+=size;types[row['type']]['records']+=1
j.close();assert reopen(j.path)['rows']==saved['rows']
metrics=dict(classification='exact original admitted workload, synchronous writer replay',ingress_bytes=n,ingress_records=count,journal_bytes=j.bytes,journal_records=j.count,expanded_bytes=j.expanded_bytes,wall_seconds=time.monotonic()-start,cpu_seconds=time.process_time()-cpu,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,queue_high_records=q.high_items,queue_high_bytes=q.high_bytes,by_type=types)
if version:
 # Explicit repeated-fixture budget projection, not real future observations.
 tail=[r for r in saved['rows'] if r['type'] in ('prediction_frame','prediction_book','source_health')]
 extra=0
 for r in tail:
  size=len(packed(j.encoded(r)).encode())
  if count>=2048 or n+size>16*1024*1024:break
  count+=1;n+=size;extra+=1
 metrics['repeated_pressure_fixture']=dict(accepted_extra_rows=extra,accepted_records=count,ingress_bytes=n,stop='record_cap' if count==2048 else 'byte_cap',note='repeated original row values used only for budget pressure; no additional real history or replay validity claimed')
(OUT/(sys.argv[1]+'-metrics.json')).write_text(json.dumps(metrics,indent=2));print(json.dumps({k:v for k,v in metrics.items() if k!='by_type'},indent=2))
