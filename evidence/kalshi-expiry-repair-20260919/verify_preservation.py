"""Hash original evidence and workspace; allow only the bounded adapter repair."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
R=Path(__file__).resolve().parents[2]
D=Path(__file__).resolve().parent

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads(p.read_text())
def write(name, value): (D/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')

e=read(D/'evidence-before.json')
# The initial repair manifest excluded bytecode. Verify those 48 retained files
# against the immutable diagnosis baseline, not a new after-the-fact baseline.
prior=read(R/'evidence/coverage-diagnosis-20260919/preservation-before.json')
supplement={p:x for p,x in prior.items() if p not in e}
assert len(supplement)==48 and all('__pycache__' in p for p in supplement)
e.update(supplement)
assert set(e)=={str(p.relative_to(R)) for p in (R/'evidence').rglob('*') if p.is_file() and D not in p.parents}
w=read(D/'workspace-before.json')
ec=[p for p,x in e.items() if not (R/p).is_file() or sha(R/p)!=x['sha256']]
wc=[p for p,x in w.items() if not (R/p).is_file() or sha(R/p)!=x['sha256']]
assert ec==[],ec
assert wc==['app/adapters/kalshi_stream.py'],wc
previous=read(R/'evidence/finalization-resources-offline-20260919/candidate.json')
paths=sorted(set(previous['files'])|{'tests/test_kalshi_expiry.py'})
files={p:sha(R/p) for p in paths}
assert [p for p,h in previous['files'].items() if files[p]!=h]==wc
candidate=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
write('candidate.json',dict(files=files,sha256=candidate))
patch=''.join(difflib.unified_diff((D/'kalshi_stream-before.py').read_text().splitlines(True),(R/'app/adapters/kalshi_stream.py').read_text().splitlines(True),fromfile='pre-repair/app/adapters/kalshi_stream.py',tofile='repaired/app/adapters/kalshi_stream.py'))
(D/'repair-only.patch').write_text(patch)
result=dict(candidate=candidate,candidate_source_files=len(files),git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),
 preexisting_evidence_files=len(e),preexisting_evidence_bytes=sum(x['bytes'] for x in e.values()),changed_evidence=ec,
 preexisting_workspace_files=len(w),changed_preexisting_workspace_files=wc,
 added_test='tests/test_kalshi_expiry.py',previous_candidate=previous['sha256'],
 preserved_uncommitted_work='All other preexisting app/test/doc files byte-identical; initial git status and diff retained.',
 diagnosis_preserved=True, retained_bytecode_files_verified_from_prior_baseline=len(supplement), historical_stale_timestamps_and_counts='Exact retained native/packet replay; see retained-replay.json',
 no_live_access=True,threshold_and_budgets='No configuration or resource-budget files changed; strict greater-than comparison retained')
write('verification.json',result)
print(json.dumps(result,indent=2))
