"""Guarded authored retained-slate measurements; never opens ordinary state.

Cold means a new Python process/application cache, not a purged filesystem.
Every timer finishes after the complete body or calculation is available.
"""
import argparse
import cProfile
from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import pstats
import resource
import sys
from time import perf_counter
from unittest.mock import patch

from app.comparison.estimated_policy import EstimatePolicy
from app.comparison.effective_policy import recalculate
from app.comparison.metrics import snapshot_metrics
from app.dashboard.current_contract import packed, quotes_of, serialize
from app.dashboard.current_state import CurrentStore
from tests.current_fixture import InjectedTestProvider
from tests.ev07_sustained import observation_digest, workload


def run(kind, destination):
    if not os.environ.get('PREDICT_CI_ISOLATED_ROOT') or not os.environ.get('PREDICT_CI_REPORT_ROOT'):
        raise ValueError('Inherited private-state/outbound guard required')
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=False)
    report = dict(evidence_class='authored offline retained slate', kind=kind,
        cold_filesystem=False, cold_application=True, concurrency=1, samples={},
        definition='ordinary generally <=1s means p95 complete-body <=1s, zero failures; useful painted content <=2s including startup for cold behavior',
        environment=dict(python=sys.version, platform=platform.platform(), machine=platform.machine()))
    def record(name, seconds, **extra):
        report['samples'].setdefault(name, []).append(dict(seconds=seconds, **extra))
        report['peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        (out/'measurements.json').write_text(json.dumps(report, indent=2)+'\n')
        print(name, round(seconds, 4), flush=True)
        if report['peak_rss_bytes'] >= 768*1024*1024:
            raise ValueError('Per-process memory cap exceeded; retained measurement')
    with ExitStack() as stack:
        policy = EstimatePolicy()
        for target in ('app.comparison.estimated_policy.load', 'app.dashboard.current_incremental.load',
                       'app.comparison.current_metrics.load_estimate_policy'):
            stack.enter_context(patch(target, return_value=policy))
        start = perf_counter(); raw, _, admission = workload(kind)
        record('generate_normalize_attach', perf_counter()-start, admission_seconds=admission)
        report.update(games=len(raw['events']), quotes=sum(len(quotes_of(o)) for e in raw['events'] for g in e['groups'] for o in g['outcomes']),
            observations_sha256=observation_digest(raw), raw_sha256=sha256(packed(raw)).hexdigest())
        retained = out/'authored-retained.json'; retained.write_bytes(packed(raw))
        start = perf_counter(); body = retained.read_bytes(); record('retained_file_read', perf_counter()-start, bytes=len(body))
        start = perf_counter(); raw = json.loads(body); del body; record('retained_decode', perf_counter()-start)
        empty = dict(raw, events=[], comparison_profiles={})
        start = perf_counter(); store = CurrentStore(InjectedTestProvider(empty), monotonic=lambda: 0)
        record('empty_store_initialization', perf_counter()-start)
        raw['state_revision'] = 2
        start = perf_counter(); store.commit(raw); record('retained_projection_admission', perf_counter()-start, metrics=store.projection_metrics)
        report['state_bytes'] = len(packed(store._state))
        report['funded_singles'] = sum(q['calculations']['funded_estimate']['model_available'] for e in store._state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o))
        report['pairs'] = sum(len(e['funded_pairs']) for e in store._state['events'])
        report['fair_pairs_per_event'] = [len(e['funded_pairs']) for e in store._state['events']]
        report['capacity_truncated'] = any(e['funded_pair_search']['truncated'] for e in store._state['events'])
        for _ in range(5):
            start = perf_counter(); encoded = store.encoded_snapshot(); record('current_complete_body', perf_counter()-start, bytes=len(encoded)); del encoded
            start = perf_counter(); value = snapshot_metrics(store._state); record('comparison_handler', perf_counter()-start)
            start = perf_counter(); encoded = packed(value); record('comparison_encoding', perf_counter()-start, bytes=len(encoded)); del encoded, value
        target = next(q for e in store._state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o) if q['calculations']['funded_estimate']['model_available'])
        for _ in range(3):
            start = perf_counter(); value = store.details(dict(runtime_id=raw['runtime_id'], state_revision=2, quote_id=target['id'])); encoded=packed(value)
            record('selected_full_details_complete_body', perf_counter()-start, bytes=len(encoded)); del value, encoded
        start=perf_counter(); value=recalculate(store._state, EstimatePolicy(capital_ceiling_usd='500')); encoded=packed(snapshot_metrics(value))
        record('override_complete_body', perf_counter()-start, bytes=len(encoded)); del value, encoded
        # Same generator and authoritative serializer on one occurrence isolates
        # call counts without multiplying profiler overhead across the full slate.
        from app.comparison.shared_templates import subset
        event=raw['events'][0]
        local=dict(raw,events=[event],comparison_profiles=subset(raw['comparison_profiles'],dict(outcomes=[o for g in event['groups'] for o in g['outcomes']])))
        profile=cProfile.Profile(); start=perf_counter(); profile.runcall(serialize,local,allow_synthetic=True,estimate_policy=policy)
        record('profiled_single_occurrence',perf_counter()-start)
        profile.dump_stats(str(out/'occurrence.prof'))
        with (out/'occurrence-profile.txt').open('w') as stream:
            pstats.Stats(profile,stream=stream).sort_stats('cumulative').print_stats(75)
        record('complete',0)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--kind',choices=('active','historical'),default='active'); parser.add_argument('--out',required=True)
    args=parser.parse_args(); run(args.kind,args.out)
