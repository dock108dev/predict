"""Read-only streamed distribution analysis; not collector qualification."""
import base64
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import resource
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.collection.journal_encoding import decode, encode
from app.dashboard.bounds import retained_bytes
from app.reference.records import packed

OUT = Path(__file__).parent
MIB = 1024**2
resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
resource.setrlimit(resource.RLIMIT_FSIZE, (8*MIB, 8*MIB))
signal.alarm(120)
started = time.monotonic()
def digest(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(65536), b''): h.update(b)
    return h.hexdigest()

real = ROOT/'evidence/d2-coverage/validation-20260916T170132Z-2cbe6460/3b9cf13c-0696-4fcb-b643-bdd545d9bbd3/3b9cf13c-0696-4fcb-b643-bdd545d9bbd3.jsonl'
sets = {'real': [real]}
for scenario in ('busy-refresh-stop', 'resource-stop', 'stop-at-rotation'):
    sets[scenario] = sorted((ROOT/'evidence/d3-mock-integration/qualified'/scenario).glob('pilot/*/history/segment-*.jsonl'))
    assert sets[scenario], scenario
files = [p for paths in sets.values() for p in paths]
assert sum(p.stat().st_size for p in files) <= 128*MIB
before = {str(p.relative_to(ROOT)): digest(p) for p in files}
source_before = {str(p.relative_to(ROOT)): digest(p) for p in (ROOT/'app').rglob('*.py')}
def distribution(values):
    values.sort()
    return dict(n=len(values), total=sum(values), mean=sum(values)/len(values),
                p50=values[math.ceil(.5*len(values))-1], p95=values[math.ceil(.95*len(values))-1],
                p99=values[math.ceil(.99*len(values))-1], maximum=values[-1])

results = {}; total = 0
for name, paths in sets.items():
    stats = defaultdict(lambda: defaultdict(list)); requests = Counter(); wire = Counter(); frames = Counter()
    buckets = Counter(); frame_buckets = Counter(); frame_times = []; groups = Counter(); first = last = None
    physical = 0; stored = 0
    for p in paths:
        with p.open('rb') as f:
            while True:
                line = f.readline(32*MIB+1)
                if not line: break
                assert len(line) <= 32*MIB
                total += 1; assert total <= 20000
                assert resource.getrusage(resource.RUSAGE_SELF).ru_maxrss < 256*MIB
                physical += 1; stored += len(line)
                row = decode(json.loads(line)['row'])
                typ = row['type']
                if typ.startswith('d3_') or typ == 'session_finished': continue
                n = len(packed(encode(row)).encode()); e = len(packed(row).encode()); o = retained_bytes(row)
                for key in ('ALL', typ):
                    stats[key]['encoded'].append(n); stats[key]['expanded'].append(e); stats[key]['python_object'].append(o)
                at = datetime.fromisoformat(row['observed_at']).timestamp()
                first = at if first is None else min(first, at); last = at if last is None else max(last, at)
                buckets[math.floor(at)] += 1
                if typ == 'prediction_frame':
                    frames[row['source']] += 1; groups[row.get('stream_group', '_legacy')] += 1
                    frame_buckets[math.floor(at)] += 1; frame_times.append(at)
                if 'body_b64' in row:
                    wire[row.get('source', '?')+' / '+typ] += len(base64.b64decode(row['body_b64']))
                if 'path' in row and 'status' in row:
                    requests[row.get('source', '?')+' / '+row['path']] += 1
    frame_times.sort(); j = 0; rolling_peak = 0
    for i, at in enumerate(frame_times):
        while at-frame_times[j] >= 1: j += 1
        rolling_peak = max(rolling_peak, i-j+1)
    results[name] = dict(distributions={k:{m:distribution(v) for m,v in s.items()} for k,s in stats.items()},
        physical=physical, stored_bytes=stored, ingress_span_seconds=last-first,
        requests=dict(requests), wire_bytes=dict(wire), frames=dict(frames), frames_by_group=dict(groups),
        peak_calendar_second_ingress=max(buckets.values()), peak_calendar_second_frames=max(frame_buckets.values()),
        peak_rolling_second_frames=rolling_peak,
        active_frame_span_seconds=max(frame_times)-min(frame_times))

r = results['real']['distributions']['ALL']
sensitivity = []
for factor in (1,2,4,8):
    scale = 1800/50.904*factor
    sensitivity.append(dict(factor=factor, logical=math.ceil(r['encoded']['n']*scale),
        encoded_MiB=r['encoded']['total']*scale/MIB, expanded_MiB=r['expanded']['total']*scale/MIB,
        frames=math.ceil(sum(results['real']['frames'].values())*scale)))
result = dict(classification='Streamed distributions and arithmetic sensitivity; no new traffic or capacity qualification',
    limits=dict(input_bytes=128*MIB, records=20000, rss_bytes=256*MIB,cpu_seconds=60,wall_seconds=120,output_bytes=8*MIB),
    inputs=before, source_hashes=source_before, datasets=results,
    sensitivity=sensitivity, measurements=dict(elapsed_seconds=time.monotonic()-started,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, input_bytes=sum(p.stat().st_size for p in files),records=total),
    input_hashes_unchanged=all(digest(ROOT/p)==h for p,h in before.items()),
    app_source_hashes_unchanged=all(digest(ROOT/p)==h for p,h in source_before.items()))
body=json.dumps(result,indent=2)+'\n'; assert len(body.encode()) < 8*MIB
with (OUT/'measurements.json').open('x') as f: f.write(body)
print(json.dumps(dict(measurements=result['measurements'],sensitivity=sensitivity, datasets={k:{x:v[x] for x in ('distributions','requests','wire_bytes','frames','frames_by_group','peak_rolling_second_frames','active_frame_span_seconds')} for k,v in results.items()}),indent=2))
