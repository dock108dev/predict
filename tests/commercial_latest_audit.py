"""Final-source read-only check of the tracker's latest completed session."""
import json
from pathlib import Path
from app.collection.two_source_audit import verify
from app.dashboard import session_history
from app.dashboard.price_comparison import comparisons
from app.dashboard.opportunity_history import build_history, validate_watch
from tests.commercial_retained_audit import hashes,BASE

SID='860107f6-56ff-44fe-9fd0-088ceaabe2a6'
FOLDER=Path('evidence/supervised-capacity-run-'+SID)/SID

def main():
    before=hashes(FOLDER)
    audit=verify(FOLDER)
    assert audit['state']=='PASS' and audit['scope']['state']=='PASS'
    snap=session_history.load(FOLDER,audit['exact_cutoff'])
    rows=comparisons(snap,{'quantity':'100'})
    assert len(rows)==8
    assert all(r['net'] is None and r['settlement_status']=='INCOMPATIBLE' for r in rows)
    watch=validate_watch(dict(name='Latest retained raw gap',metric='raw_gap',threshold='.03',quantity='100',filters={}))
    report=build_history(FOLDER,[watch])
    assert report['coverage']['complete'] and not any(i['active'] for i in report['items'])
    assert before==hashes(FOLDER)
    (BASE/'latest-retained-history.json').write_text(json.dumps(report,indent=2))
    summary=dict(session=SID,original_files_preserved=len(before),original_hashes=before,exact_snapshot=audit['exact_snapshot'],exact_calculations=audit['exact_calculations'],exact_native_replay=audit['exact_native_replay'],scope=audit['scope']['state'],comparisons=8,net_still_unavailable=True,coverage=report['coverage'],distinct_crossings=sum(i['episodes'] for i in report['items']),qualifying_observations=sum(i['qualifying_observations'] for i in report['items']))
    (BASE/'latest-retained-audit.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k!='original_hashes'},indent=2),flush=True)

if __name__=='__main__':main()
