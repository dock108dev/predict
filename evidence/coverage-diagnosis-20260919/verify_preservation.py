"""Verify earlier evidence and preexisting source/docs without modifying them."""
import hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[2];D=Path(__file__).resolve().parent
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text())
b=load(D/'preservation-before.json');changed=[p for p,x in b.items() if not (R/p).is_file() or h(R/p)!=x['sha256']]
w=load(D/'workspace-before.json');wc=[p for p,x in w.items() if not (R/p).is_file() or h(R/p)!=x]
old=load(R/'evidence/finalization-resources-offline-20260919/preexisting-evidence-sha256.json');oc=[p for p,x in old.items() if h(R/p)!=x]
c=load(R/'evidence/finalization-resources-offline-20260919/candidate.json');cc=[p for p,x in c['files'].items() if h(R/p)!=x]
assert not changed and not wc and not oc and not cc,(changed,wc,oc,cc)
result=dict(preexisting_evidence_files=len(b),preexisting_evidence_bytes=sum(x['bytes'] for x in b.values()),changed_evidence=changed,preexisting_app_tests_docs_files=len(w),changed_app_tests_docs=wc,prior_finalization_baseline_files_verified=len(old),prior_finalization_baseline_changes=oc,current_finalization_candidate=c['sha256'],current_finalization_candidate_changes=cc,network='diagnostic replay blocks socket connections; no live calls or credentials used',scope='Only isolated diagnosis artifacts and Desktop tracker written; no application behavior or proposed repair implemented')
(D/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
