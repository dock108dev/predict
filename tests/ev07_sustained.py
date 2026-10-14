"""EV07 fresh active/historical qualification; original EV06 generators retained."""
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

from tests.current_fixture import InjectedTestProvider
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.dashboard.current_contract import packed,quotes_of,serialize
from app.dashboard.current_state import CurrentStore


def workload(kind):
    if kind=='active':from tests.ev05_workload import workload as generate
    else:from tests.ev04_workload import workload as generate
    return generate()


def observation_digest(state):
    return sha256(packed({q['source']['native_outcome_id']:[q['source'],q['original'],q['times'],q['revision'],q['provenance']]
        for e in state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)})).hexdigest()


def check(state,kind):
    qs=[q for e in state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)]
    funded=sum(q['calculations']['funded_estimate']['model_available'] for q in qs)
    legacy=sum(q['calculations']['net_ev']['eligible'] for q in qs)
    assert legacy==1700,(legacy,kind)
    if kind=='active':assert funded==1700,funded
    assert all('capacity' not in s['reason'] for q in qs for s in q['comparison_input_status'].values())
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert peak<768*1024*1024,peak
    assert len(packed(state))<64*1024*1024
    by_event=[dict(event_id=e['id'],pairs=len(e['funded_pairs']),candidate_pairs=e['funded_pair_search']['candidate_pairs'],
        truncated=e['funded_pair_search']['truncated'],consumer_probes=e['funded_pair_search']['allocation_consumer_probes']) for e in state['events']]
    assert not any(e['truncated'] for e in by_event)
    if kind=='active':assert all(e['pairs']>0 for e in by_event)
    return dict(peak_rss_bytes=peak,legacy_supported=legacy,funded_single_supported=funded,
        ev06_pairs=sum(e['pairs'] for e in by_event),by_event=by_event,capacity_deferrals=0)


def run(kind):
    out=Path('test-results/ev07/workload-final')/kind;out.mkdir(parents=True,exist_ok=True)
    raw,expected,admission=workload(kind);original=observation_digest(raw)
    graph_bytes=len(packed(raw['comparison_profiles']));assert graph_bytes<24*1024*1024
    empty={k:v for k,v in raw.items() if k not in ('events','comparison_profiles')};empty['events']=[]
    store=CurrentStore(InjectedTestProvider(empty),monotonic=lambda:0)
    raw['state_revision']=2;start=perf_counter();assert store.commit(raw)
    initial=check(store._state,kind);steps=[dict(phase='initial',seconds=perf_counter()-start,**initial)]
    out.joinpath('progress.json').write_text(json.dumps(steps,indent=2)+'\n')
    target=next(q for e in store._state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o) if q['calculations']['net_ev']['eligible'])
    request=dict(runtime_id=raw['runtime_id'],state_revision=2,quote_id=target['id'])
    details=store.details(request);selected_bytes=len(packed(details));del details
    lease=store.create(dict(schema='predict-current-1',**request,quote_revision=target['revision'],client_id='authored:ev06:'+kind))
    token=lease['selection_id'];frozen=sha256(packed(lease['review'])).hexdigest();del lease,target
    changes=[(3,'500','0.005','0.005'),(4,'1000','0.01','0.005'),(5,'1000','0.005','0.01'),(6,'1000','0.005','0.005')]
    oracles={}
    try:
        # Fresh rebuilds are independent and write no files. At most four child
        # processes; each reports and satisfies its own unchanged RSS bound.
        for revision,ceiling,buffer,tie in changes:
            code="from tests.ev07_sustained import workload;from app.dashboard.current_contract import serialize,packed;from app.comparison.estimated_policy import EstimatePolicy;from hashlib import sha256;import json,resource;r,_,_=workload("+repr(kind)+");r['state_revision']="+str(revision)+";p=EstimatePolicy(capital_ceiling_usd="+repr(ceiling)+",buffer_rate="+repr(buffer)+",tie="+repr(tie)+");v=serialize(r,allow_synthetic=True,estimate_policy=p);print(json.dumps(dict(sha256=sha256(packed(v)).hexdigest(),peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)))"
            oracles[revision]=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=os.environ.copy())
        for revision,ceiling,buffer,tie in changes:
            policy=replace(DEFAULT_POLICY,capital_ceiling_usd=ceiling,buffer_rate=buffer,tie=tie);start=perf_counter()
            with patch('app.dashboard.current_incremental.load',return_value=policy),patch('app.comparison.estimated_policy.load',return_value=policy):
                assert store.commit(dict(raw,state_revision=revision))
                assert observation_digest(store._state)==original
                encoded=store.encoded_snapshot();actual=sha256(encoded).hexdigest();snapshot_bytes=len(encoded);del encoded
                counts=check(store._state,kind)
                assert sha256(packed(store.get(token)['review'])).hexdigest()==frozen
                stdout,stderr=oracles[revision].communicate(timeout=1200)
                if oracles[revision].returncode:raise ValueError('Fresh rebuild failed: '+stderr[-2000:])
                oracle=json.loads(stdout)
                assert oracle['sha256']==actual,(oracle,actual)
                assert oracle['peak_rss_bytes']<768*1024*1024,oracle
            steps.append(dict(revision=revision,ceiling=ceiling,buffer=buffer,tie=tie,seconds=perf_counter()-start,
                snapshot_bytes=snapshot_bytes,oracle=oracle,**counts,**store.projection_metrics))
            out.joinpath('progress.json').write_text(json.dumps(steps,indent=2)+'\n')
    finally:
        for process in oracles.values():
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
    report=dict(evidence_class='authored offline '+kind+' workload; no source/native/owner qualification',
        workload='unchanged original generator: tests.ev05_workload' if kind=='active' else 'unchanged original generator: tests.ev04_workload',
        games=150,quotes=2000,missing_reference=300,graph_bytes=graph_bytes,selected_details_bytes=selected_bytes,
        admission_seconds=admission,steps=steps,source_observations_sha256=original,
        full_incremental_agreement=True,frozen_lease_preserved=True,acquisition_requests=0,
        oracle_execution='four independent fresh rebuilds launched concurrently; individual process peaks bounded; children terminated on failure',
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,environment=dict(python=sys.version,platform=platform.platform()))
    out.joinpath('sustained.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(kind=kind,peak_rss_bytes=report['peak_rss_bytes'],ev06_pairs=steps[-1]['ev06_pairs'],full_incremental_agreement=True)))


if __name__=='__main__':run(sys.argv[1] if len(sys.argv)>1 else 'active')
