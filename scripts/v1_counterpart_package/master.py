"""Inert two-session reservation gate; one owner approval, no automatic retest."""
import fcntl,json,os,sys
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
PACKAGE=Path(__file__).resolve().parent
from app.collection.native_approval import implementation,digest
from app.collection.run_spec import preflight,time_value

def read(name):return json.loads((PACKAGE/name).read_text())
def write(path,value):
 with path.open('x') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def checked(approved=False):
 m=read('master.json')
 for n,h in m['file_hashes'].items():
  if sha256((PACKAGE/n).read_bytes()).hexdigest()!=h:raise ValueError('Package seal changed: '+n)
 if m['initial_implementation_sha256']!=digest(read('SOURCE-MANIFEST.json')):raise ValueError('Initial candidate seal changed')
 for n,h in m['protected_files'].items():
  if sha256((ROOT/n).read_bytes()).hexdigest()!=h:raise ValueError('Protected approval controller changed')
 spec=read('run-spec.json')
 if not preflight(spec)['valid'] or digest(spec)!=m['spec_sha256']:raise ValueError('Invalid sealed scope')
 now=datetime.now(timezone.utc)
 if not time_value(spec['start_after'])<=now<=time_value(spec['start_before']):raise ValueError('Outside start window')
 from app.collection.acquisition_policy import native_caps,totals
 if native_caps(spec)!=dict(kalshi=10,polymarket_us=10) or totals(spec['source_session'])!=dict(startup=1,discovery=2,paid=4,requests=7,credits=8):raise ValueError('Operation ceilings changed')
 if approved:
  if read('owner-approval.json')!=dict(approved=True,master_sha256=digest(m)):raise ValueError('Exact single owner approval required')
 return m,spec

def ledger(m):
 path=PACKAGE/'reservations.jsonl'
 if not path.exists():
  if (PACKAGE/'reservations-started.json').exists() or (PACKAGE/'children').exists():raise ValueError('Missing spent ledger')
  return []
 raw=path.read_bytes()
 if len(raw)>1024*1024 or not raw.endswith(b'\n'):raise ValueError('Uncertain reservation ledger')
 rows=[];previous=None
 for line in raw.splitlines():
  r=json.loads(line);body={k:v for k,v in r.items() if k!='sha256'}
  if r['sha256']!=digest(body) or r['previous']!=previous or r['master_sha256']!=digest(m) or r['sequence']!=len(rows)+1:raise ValueError('Reservation chain changed')
  if r.get('reservation')!=m['per_session_reservation']:raise ValueError('Reservation ceilings changed')
  if r['spec_sha256']!=m['spec_sha256'] or r['implementation_sha256']!=digest(r['source_manifest']):raise ValueError('Reservation identity changed')
  rows.append(r);previous=r['sha256']
 if len(rows)>2:raise ValueError('Two-session ceiling exceeded')
 return rows

def reserve(reason,offline_evidence):
 m,spec=checked(True)
 if not reason.strip() or not offline_evidence:raise ValueError('Concrete objective and offline verification required')
 proofs={}
 for name in offline_evidence:
  p=(ROOT/name).resolve()
  if not p.is_relative_to(ROOT/'evidence') or not p.is_file() or p.stat().st_size>1024*1024:raise ValueError('Bounded local evidence required')
  proofs[name]=sha256(p.read_bytes()).hexdigest()
 with (PACKAGE/'reservation.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  rows=ledger(m)
  if len(rows)>=2:raise ValueError('Counterpart allowance exhausted')
  manifest=implementation()
  if not rows and digest(manifest)!=m['initial_implementation_sha256']:raise ValueError('Initial candidate changed')
  if rows:
   report_path=Path(rows[-1]['output'])
   reports=list(report_path.glob('*/report.json'))
   if len(reports)!=1 or not json.loads(reports[0].read_text()).get('cleanup_complete'):raise ValueError('Prior attempt must have confirmed terminal cleanup before bounded repair/retest')
   if not reason.startswith('repair/retest:'):raise ValueError('Second session requires concrete repair/retest reason')
  attempt=str(uuid4());output=Path(m['output_root'])/attempt
  if output.exists():raise ValueError('Output already used')
  r=dict(sequence=len(rows)+1,master_sha256=digest(m),previous=rows[-1]['sha256'] if rows else None,attempt_id=attempt,output=str(output),reason=reason,offline_evidence=proofs,source_manifest=manifest,implementation_sha256=digest(manifest),spec_sha256=digest(spec),consumed=True,
   reservation=dict(http=27,credits=8,websocket_attempts=4,collection_seconds=180,supervised_seconds=240,output_bytes=134217728),reserved_at=datetime.now(timezone.utc).isoformat())
  r['sha256']=digest(r)
  if not rows:write(PACKAGE/'reservations-started.json',dict(master_sha256=digest(m),no_reset=True))
  with (PACKAGE/'reservations.jsonl').open('a') as f:f.write(json.dumps(r,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
  # Allowance is spent before child approval or any output activation.
  child=PACKAGE/'children'/attempt;child.mkdir(parents=True)
  for n in ('launch.py','control.py','execute-child.py'):
   content=(PACKAGE/n).read_text()
   if n=='launch.py':content=content.replace('parents[2]','parents[4]')
   (child/('execute.py' if n=='execute-child.py' else n)).write_text(content)
  write(child/'run-spec.json',spec);write(child/'attempt.json',dict(attempt_id=attempt,output=str(output)))
  (child/'AUTHORIZATION.txt').write_text('Child of exact approved counterpart master; consumed reservation '+r['sha256']+'\n')
  files={n:sha256((child/n).read_bytes()).hexdigest() for n in ('launch.py','control.py','execute.py','run-spec.json','attempt.json','AUTHORIZATION.txt')}
  identity=dict(implementation_sha256=digest(manifest),spec_sha256=digest(spec),attempt_id=attempt,output=str(output),file_hashes=files)
  write(child/'identity.json',identity);write(child/'approval.json',dict(approved=True,**identity))
  return child
