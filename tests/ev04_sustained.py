"""EV04-boundary reuse of EV03 finite sustained slate verification, separate from later EV08 qualification."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import resource
from time import perf_counter
import platform
import sys
import os
import subprocess

from tests.ev04_workload import workload
from tests.current_fixture import InjectedTestProvider
from app.comparison.shared_templates import keys, resolve, shared
from app.comparison.metrics import snapshot_metrics
from app.dashboard.current_contract import packed, quotes_of, serialize, snapshot_inputs
from app.dashboard.current_state import CurrentStore

ROOT=Path('test-results/ev04/adapted')


def qs(state):
    return [q for e in state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)]


def observations(state):
    return {q['source']['native_outcome_id']:[q['source'],q['original'],q['times'],q['revision'],q['provenance']]
        for q in qs(state)}


def run():
    raw,expected,admission=workload();input_originals=observations(raw)
    profiles=raw['comparison_profiles'];start=perf_counter()
    empty=deepcopy({k:v for k,v in raw.items() if k not in ('events','comparison_profiles')});empty['events']=[]
    store=CurrentStore(InjectedTestProvider(empty),monotonic=lambda:0)
    raw['state_revision']=2;assert store.commit(raw);initial_seconds=perf_counter()-start
    state=store._state;steps=[]
    ROOT.joinpath('sustained-progress.json').write_text(json.dumps(dict(phase='initial_commit',peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))+'\n')
    supported=sum(sum(s) for s in expected.values());positions=[];attachments=[]
    for event in state['events']:
        quotes=qs(dict(events=[event]));position=int(quotes[0]['source']['native_event_id'].rsplit(':',1)[1])
        entry=dict(position=position,quotes=len(quotes),supported=sum(expected[position]),
            eligible=sum(q['calculations']['net_ev']['eligible'] for q in quotes),
            capacity_deferrals=sum(any('capacity' in s['reason'] for s in q['comparison_input_status'].values()) for q in quotes),
            missing_refusals=sum(not q['calculations']['net_ev']['eligible'] for q in quotes))
        assert entry['eligible']==entry['supported'] and entry['capacity_deferrals']==0,entry
        positions.append(entry)
        attachments.extend(len(packed(dict(refs=q['comparison_input_refs'],status=q['comparison_input_status']))) for q in quotes)
    assert observations(state)==input_originals
    response_start=perf_counter();response_bytes=len(packed(snapshot_metrics(state)));response_seconds=perf_counter()-response_start
    # Resolve one late-event selected contract, preserving original price/clocks
    # and exact result; retain a full lease across six coherent revisions.
    target=next(q for q in qs(state) if q['source']['native_event_id'].endswith(':149') and q['calculations']['net_ev']['eligible'])
    request=dict(runtime_id=state['runtime_id'],state_revision=2,quote_id=target['id'])
    start=perf_counter();details=store.details(request);details_seconds=perf_counter()-start
    assert details['quote']['calculations']['net_ev']['exact']==target['calculations']['net_ev']['exact']
    lease=store.create(dict(schema='predict-current-1',**request,quote_revision=target['revision'],client_id='synthetic:ev03:late-selected'))
    frozen=deepcopy(lease['review'])
    peak_samples=[resource.getrusage(resource.RUSAGE_SELF).ru_maxrss]
    base=2
    for revision in range(3,9):
        proposed=dict(raw,state_revision=revision)
        start=perf_counter();assert store.commit(proposed);seconds=perf_counter()-start
        delta=json.loads(store.encoded_changes(raw['runtime_id'],base))
        # The unchanged large-slate delta carries zero event replacements. The
        # three-event tests independently exercise client merge and removals.
        assert delta['events']==[] and delta['removed_events']==[]
        merged=dict(delta['snapshot'],events=store._state['events'])
        assert packed(merged)==store.encoded_snapshot()
        del delta,merged
        assert observations(store._state)==input_originals
        assert store.get(lease['selection_id'])['review']==frozen
        assert sum(q['calculations']['net_ev']['eligible'] for q in qs(store._state))==supported
        steps.append(dict(revision=revision,seconds=seconds,**store.projection_metrics))
        base=revision;peak_samples.append(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        ROOT.joinpath('sustained-progress.json').write_text(json.dumps(dict(phase='commit',steps=steps,peak_samples=peak_samples))+'\n')
        assert peak_samples[-1]<768*1024*1024,peak_samples[-1]
    assert json.loads(store.encoded_changes('obsolete-runtime',1))['schema']=='predict-current-1'
    # Keep the independent full oracle in a fresh process, as memory-sensitive
    # regressions do. It measures its own peak; it is not a second server catalog.
    start=perf_counter()
    code="from tests.ev04_workload import workload;from app.dashboard.current_contract import serialize,packed;from hashlib import sha256;import resource,json;r,_,_=workload();r['state_revision']=8;print(json.dumps(dict(sha256=sha256(packed(serialize(r,allow_synthetic=True))).hexdigest(),peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)))"
    oracle=json.loads(subprocess.check_output([sys.executable,'-c',code],env=os.environ.copy(),text=True,timeout=180))
    assert oracle['sha256']==sha256(store.encoded_snapshot()).hexdigest(),oracle
    assert oracle['peak_rss_bytes']<768*1024*1024,oracle
    equivalence_seconds=perf_counter()-start;peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert peak<768*1024*1024,peak
    binding_sizes=[len(packed(b)) for b in profiles['bindings'].values()]
    expanded_bytes=sum(len(packed({k:resolve(profiles,k)})) for k in keys(profiles))+2
    return dict(evidence_class='explicitly synthetic, offline finite sustained slate; not EV08 or live qualification',
        environment=dict(python=sys.version,platform=platform.platform(),executable=sys.executable),
        games=len(state['events']),quotes=len(qs(state)),supported=supported,missing_refusals=2000-supported,capacity_deferrals=0,
        template_count=len(profiles['templates']),binding_count=len(profiles['bindings']),template_bytes=len(packed(profiles['templates'])),
        binding_bytes=len(packed(profiles['bindings'])),representation_bytes=len(packed(profiles)),fully_expanded_profile_bytes=expanded_bytes,
        contract_attachment_bytes=dict(max=max(attachments),mean=sum(attachments)/len(attachments)),
        binding_record_bytes=dict(max=max(binding_sizes),mean=sum(binding_sizes)/len(binding_sizes)),
        snapshot_bytes=len(store.encoded_snapshot()),comparison_response_bytes=response_bytes,
        selected_details_bytes=len(packed(details)),admission_seconds=admission,initial_projection_seconds=initial_seconds,
        comparison_response_seconds=response_seconds,selected_details_seconds=details_seconds,
        full_equivalence_seconds=equivalence_seconds,oracle=oracle,sustained_steps=steps,peak_samples=peak_samples,peak_rss_bytes=peak,
        source_observations_sha256=sha256(packed(input_originals)).hexdigest(),by_event=sorted(positions,key=lambda p:p['position']),
        acquisition_requests=0,claims=dict(fair_coverage=True,unchanged_calculations=True,full_incremental_equivalence=True,
            cursor_recovery=True,selected_details=True,frozen_lease=True,stable_originals=True,bounded_memory=True))


if __name__=='__main__':
    ROOT.mkdir(parents=True,exist_ok=True);report=run();ROOT.joinpath('sustained.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('by_event','sustained_steps')},indent=2))
