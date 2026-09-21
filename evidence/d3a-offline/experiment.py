"""Run from repository root with PYTHONPATH=.; never writes original evidence."""
import asyncio
from hashlib import sha256
from itertools import zip_longest
import json
from pathlib import Path
import sys
import time
import tracemalloc
from app.collection.segmented import SegmentedReader, iter_journal, POLICY, digest_file
from app.collection.native_replay import GroupedNativeVerifier
from app.collection.odds_http import BudgetStop
from app.collection.continuous import rss
from app.dashboard.coverage_owner import OfflineHistoryOwner

ROOT=Path('evidence/d3a-offline')
SOURCE=Path('evidence/d2-coverage/validation-20260916T170132Z-2cbe6460/3b9cf13c-0696-4fcb-b643-bdd545d9bbd3/3b9cf13c-0696-4fcb-b643-bdd545d9bbd3.jsonl')

def original():
    for r,_ in iter_journal(SOURCE):yield r

async def build(name,pressure=False):
    o=OfflineHistoryOwner(ROOT/name,label='synthetic repeated retained workload; not additional history' if pressure else 'lossless derivative of retained 575-book capture')
    start=time.monotonic();stop=None; boundaries=[]
    try:
        for cycle in range(2 if pressure else 1):
            for i,r in enumerate(original()):
                if pressure and r['type']=='session_finished':continue
                if not pressure and i==174:
                    o.journal.rotate();boundaries.append(dict(source_ordinal=i,reason='between discovery/metadata and stream commands'))
                o.admit(r);o.drain()
    except BudgetStop as e:stop=str(e)
    finally:await o.stop('offline_source_end' if not pressure else 'offline_pressure_end')
    a=o.accounting();a.update(seconds=time.monotonic()-start,stop=stop,boundaries=boundaries,
        source=str(SOURCE),source_sha256=digest_file(SOURCE),policy=POLICY,
        fixture='synthetic repeated identities and busy observations' if pressure else 'retained real source, unchanged observations')
    (ROOT/(name+'-write.json')).write_text(json.dumps(a,indent=2))
    print(json.dumps(a,indent=2))

def measure(name,pressure=False):
    # Independent fresh process; neither writer nor legacy materializing reader is used.
    baseline=rss();tracemalloc.start();start=time.monotonic()
    reader=SegmentedReader(ROOT/name);verifier=GroupedNativeVerifier()
    count=books=packets=0;order=sha256();samples=[]
    def expected():
        for _ in range(2 if pressure else 1):
            for r in original():
                if pressure and r['type']=='session_finished':continue
                yield r
    source=expected()
    segments=json.loads((ROOT/name/'manifest.json').read_text())['segments']
    ends=[];end=0
    for s in segments:end+=s['observations'];ends.append(end)
    for r in reader.rows(allow_interrupted=pressure):
        assert r==next(source),'observation value/order changed'
        count+=1;order.update(json.dumps(r,sort_keys=True,separators=(',',':')).encode())
        if r['type']=='prediction_book':books+=1;packets+=len(r['packets'])
        if not pressure:verifier.feed(r)
        if count in ends:samples.append(dict(observations=count,rss_peak=rss(),traced_current=tracemalloc.get_traced_memory()[0]))
    if not pressure:
        assert next(source,None) is None
        assert books==575 and packets==1150
        assert sum(sum(g['exact_native_books'].values()) for g in verifier.result().values())==575
    current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    seconds=time.monotonic()-start
    result=dict(fixture=name,observations=count,books=books,packets=packets,exact_rows_order=True,
        sequence_sha256=order.hexdigest(),native_replay=verifier.result(state='complete',sha256=digest_file(ROOT/name/'manifest.json')) if not pressure else 'not claimed: repeated identities are pressure only',
        seconds=seconds,observations_per_second=count/seconds,baseline_rss=baseline,peak_rss=rss(),
        traced_current=current,traced_peak=peak,segment_samples=samples,
        implementation='two sequential verification passes; one row plus native engine state, no whole-run list',
        disk_bytes=sum(p.stat().st_size for p in (ROOT/name).iterdir()),segments=segments)
    (ROOT/(name+'-replay.json')).write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

if __name__=='__main__':
    action,name=sys.argv[1:];pressure='pressure' in name
    if action=='build':asyncio.run(build(name,pressure))
    else:measure(name,pressure)
