from pathlib import Path
import json,tempfile,base64
from tests.test_e6_recovery import crash
from app.collection.transport_session import reopen,ObservationJournal
from app.collection.journal_encoding import VERSION
from app.collection.recovery import inspect,index,reopen_index
out=Path('evidence/d2-coverage/record-capacity-decision-20260916');results={}
with tempfile.TemporaryDirectory() as temp:
 root=Path(temp);source=crash(root/'source','books');rows=reopen(source)['rows']
 for name,encoding in [('old',None),('new',VERSION)]:
  p=root/(name+'.jsonl');j=ObservationJournal(p,encoding=encoding)
  for r in rows:j.save(r)
  j.close();r,s=inspect(p);assert s['rows']==rows;assert r['replay']['exact_packets']
  idx=root/(name+'-index.json');indexed=index(p,idx);assert reopen_index(idx)[0]==indexed
  with p.open('ab') as f:f.write(b'{"row":')
  torn,saved=inspect(p);assert torn['excluded_trailing_bytes']==7
  rejected=False
  try:reopen_index(idx)
  except ValueError:rejected=True
  assert rejected
  results[name]=dict(exact_rows=True,replay=r['replay'],device=r['source']['device'],fresh_index_reopened=True,torn_suffix_excluded_bytes=7,changed_index_source_rejected=True,status=r['status'],records=len(rows))
(out/'fresh-recovery.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
