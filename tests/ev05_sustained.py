"""Finite EV05 changing-slate evidence; separate from EV08 responsiveness."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json
import os
import platform
import resource
import subprocess
import sys
from time import perf_counter
from unittest.mock import patch

from tests.ev05_workload import workload
from tests.current_fixture import InjectedTestProvider
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.dashboard.current_contract import packed, quotes_of, serialize
from app.dashboard.current_state import CurrentStore

ROOT=Path('test-results/ev05/workload')


def quotes(state):
    return [q for e in state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)]


def observed_digest(state):
    return sha256(packed({q['source']['native_outcome_id']:[q['source'],q['original'],q['times'],q['revision'],q['provenance']]
        for q in quotes(state)})).hexdigest()


def check(state):
    qs=quotes(state)
    available=sum(q['calculations']['funded_estimate']['model_available'] for q in qs)
    reasons=[q['calculations']['funded_estimate']['reasons'] for q in qs if not q['calculations']['funded_estimate']['model_available']]
    assert available==1700,(available,reasons[:3])
    assert all(r==['estimate_exact_pinnacle_reference_missing'] for r in reasons),reasons[:3]
    assert not any('capacity' in s['reason'] for q in qs for s in q['comparison_input_status'].values())
    assert len(packed(state))<64*1024*1024
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert peak<768*1024*1024,peak
    return peak


def run():
    raw,expected,admission=workload(); original=observed_digest(raw)
    empty={k:v for k,v in raw.items() if k not in ('events','comparison_profiles')};empty['events']=[]
    store=CurrentStore(InjectedTestProvider(empty),monotonic=lambda:0)
    started=perf_counter();raw['state_revision']=2;assert store.commit(raw)
    steps=[dict(phase='initial',seconds=perf_counter()-started,peak_rss_bytes=check(store._state))]
    ROOT.mkdir(parents=True,exist_ok=True)
    def progress():ROOT.joinpath('progress.json').write_text(json.dumps(steps,indent=2)+'\n')
    progress()
    target=next(q for q in quotes(store._state) if q['calculations']['funded_estimate']['model_available'])
    request=dict(runtime_id=raw['runtime_id'],state_revision=2,quote_id=target['id'])
    details=store.details(request)
    assert details['quote']['calculations']['funded_estimate']['revision']==target['calculations']['funded_estimate']['revision']
    lease=store.create(dict(schema='predict-current-1',**request,quote_revision=target['revision'],client_id='synthetic:ev05'))
    frozen=sha256(packed(lease['review'])).hexdigest()
    del target,details,lease
    # Global ceilings and policies change the exact allocation and all results.
    # Each full oracle runs independently with the same declared policy.
    for revision,ceiling,buffer,tie in [(3,'500','0.005','0.005'),(4,'1000','0.01','0.005'),(5,'1000','0.005','0.01'),(6,'1000','0.005','0.005')]:
        policy=replace(DEFAULT_POLICY,capital_ceiling_usd=ceiling,buffer_rate=buffer,tie=tie)
        started=perf_counter()
        with patch('app.dashboard.current_incremental.load',return_value=policy),patch('app.comparison.estimated_policy.load',return_value=policy):
            proposed=dict(raw,state_revision=revision)
            assert store.commit(proposed)
            assert observed_digest(store._state)==original
            encoded=store.encoded_snapshot();actual=sha256(encoded).hexdigest();snapshot_bytes=len(encoded);del encoded
            peak=check(store._state)
            assert sha256(packed(store.get(next(iter(store.leases)))['review'])).hexdigest()==frozen
            oracle_code="from tests.ev05_workload import workload;from app.dashboard.current_contract import serialize,packed;from app.comparison.estimated_policy import EstimatePolicy;from hashlib import sha256;import json,resource;r,_,_=workload();r['state_revision']="+str(revision)+";p=EstimatePolicy(capital_ceiling_usd="+repr(ceiling)+",buffer_rate="+repr(buffer)+",tie="+repr(tie)+");v=serialize(r,allow_synthetic=True,estimate_policy=p);print(json.dumps(dict(sha256=sha256(packed(v)).hexdigest(),peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)))"
            oracle=json.loads(subprocess.check_output([sys.executable,'-c',oracle_code],text=True,env=os.environ.copy(),timeout=300))
            assert oracle['sha256']==actual,(oracle,actual)
            assert oracle['peak_rss_bytes']<768*1024*1024,oracle
        steps.append(dict(revision=revision,ceiling=ceiling,buffer=buffer,tie=tie,seconds=perf_counter()-started,
            peak_rss_bytes=peak,snapshot_bytes=snapshot_bytes,oracle=oracle,**store.projection_metrics));progress()
    report=dict(evidence_class='authored offline EV05 Long slate; no provider/native/owner qualification',
        workload_variance='Historical EV03/04 generators unchanged; Short collateral stays refused. New authored Long native declarations remove bid-complement transforms before admission.',
        environment=dict(python=sys.version,platform=platform.platform()),games=150,quotes=2000,supported=1700,
        missing_reference=300,capacity_deferrals=0,admission_seconds=admission,steps=steps,
        graph_bytes=len(packed(raw['comparison_profiles'])),snapshot_bytes=len(packed(store._state)),
        source_observations_sha256=original,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        full_incremental_agreement=True,frozen_lease_preserved=True,acquisition_requests=0)
    ROOT.joinpath('sustained.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    print(json.dumps(run(),indent=2))
