from pathlib import Path
import json,hashlib,collections,zlib,base64
from app.collection.transport_session import reopen
from app.reference.records import packed
out=Path('evidence/d2-coverage/journal-efficiency-20260916')
prior={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('evidence').rglob('*') if p.is_file() and out not in p.parents}
(out/'prior-sha256.json').write_text(json.dumps(prior,indent=2))
p=Path('evidence/d2-coverage/validation-20260916T170132Z-2cbe6460/3b9cf13c-0696-4fcb-b643-bdd545d9bbd3/3b9cf13c-0696-4fcb-b643-bdd545d9bbd3.jsonl');rows=reopen(p)['rows'];tot=collections.defaultdict(lambda:dict(records=0,bytes=0,components=collections.Counter()))
repeats=collections.defaultdict(list)
def scan(x,path=''):
 if isinstance(x,dict):
  for k,v in x.items():
   if k in ('body','body_b64','book','packets','market','inventory','quotes','raw'):
    val=packed(v);repeats[(k,hashlib.sha256(val.encode()).hexdigest())].append(len(val.encode()))
   scan(v,path+'/'+k)
 elif isinstance(x,list):
  for v in x:scan(v,path)
for r in rows:
 t=tot[r['type']];t['records']+=1;t['bytes']+=len(packed(r).encode())
 for k,v in r.items():t['components'][k]+=len(packed({k:v}).encode())-2
 scan(r)
result=dict(by_type=tot,repeated_subtrees={k:dict(occurrences=sum(len(ns) for (key,h),ns in repeats.items() if key==k),repeated_bytes=sum(sum(ns[1:]) for (key,h),ns in repeats.items() if key==k)) for k in {k for k,h in repeats}},note='Component sums omit braces/commas; nested repeat categories overlap, not additive.')
(out/'measurement.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:{a:b for a,b in v.items() if a!='components'} for k,v in tot.items()},indent=2));print(result['repeated_subtrees'])
