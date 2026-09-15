"""Finite, offline retained allocation experiment using frozen 13A books."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
import asyncio,gc,json,tracemalloc
from dataclasses import replace,asdict
from datetime import datetime,timezone
from app.capture_benchmark import fixture
from app.dashboard.bounds import CaptureQueue,retained_bytes
from app.dashboard.pipeline import serial

rows=[]
for n in (2,4):
    templates=fixture(n)[-1]
    gc.collect();tracemalloc.start();before=tracemalloc.take_snapshot()
    q=CaptureQueue()
    serialized=0
    for i in range(40):
        b=templates[i%len(templates)]
        b=replace(b,raw=replace(b.raw,received_at=datetime.now(timezone.utc),json_text=json.dumps(dict(fixture='13a',item=i,market=b.raw.ref.market_id))))
        item=('book',b);q.put_nowait(item)
        serialized+=len(json.dumps(serial(asdict(b))).encode())
    gc.collect();after=tracemalloc.take_snapshot();current,peak=tracemalloc.get_traced_memory()
    growth=sum(s.size_diff for s in after.compare_to(before,'lineno'))
    rows.append(dict(markets_per_venue=n,items=40,serialized_bytes=serialized,
        recursive_item_bytes=q.bytes,tracemalloc_retained_growth=growth,
        tracemalloc_peak_bytes=peak,queue_item_limit=q.maxsize,queue_byte_limit=q.byte_limit,
        interpretation='Recursive item accounting conservatively recounts shared ladders across items; tracemalloc measures new allocations including queue bookkeeping. Neither is process RSS.'))
    tracemalloc.stop()
    test=CaptureQueue(byte_limit=retained_bytes(item)-1)
    try:test.put_nowait(item)
    except asyncio.QueueFull:pass
    else:raise AssertionError('byte exhaustion not enforced')
    assert test.qsize()==0 and test.bytes==0
out=Path(__file__).with_name('memory.json');out.write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))

# Refresh work is a separate bounded owner from capture queue storage.
from app.dashboard.pipeline import Pipeline
from app.dashboard.controller import DEFAULTS
from app.dashboard.refresh import compute,thaw_result,SNAPSHOT_BYTES,RESULT_BYTES,RETAINED_BYTES
from app.capture_benchmark import synthetic_observations
refresh_rows=[]
for n in (2,4):
    p=Pipeline('synthetic',dict(DEFAULTS));p.sid='memory-only'
    p.parents,p.matcher,p.contexts,p.rows,books=fixture(n)
    p.titles={r['key']:r['native']['title'] for r in p.rows}
    for book in books:
        for o in synthetic_observations(book,source_time_semantics='unknown'):
            key=(o.quote.raw.ref.venue.value,o.quote.raw.ref.market_id,o.quote.outcome_id)
            p.observations[key]=o;p.current_receipts[key]='receipt:'+str(len(p.current_receipts))
    gc.collect();tracemalloc.start();initial=tracemalloc.get_traced_memory()[0]
    sizes=[]
    for i in range(12):
        p.dirty=1;snapshot=p.snapshot();result=compute(snapshot);sample=thaw_result(result)['sample']
        sizes.append(dict(snapshot_bytes=len(snapshot),result_bytes=len(result),result_retained_bytes=sample['result_retained_bytes']))
        del snapshot,result,sample
        gc.collect()
    current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    assert max(x['snapshot_bytes'] for x in sizes)<=SNAPSHOT_BYTES
    assert max(x['result_bytes'] for x in sizes)<=RESULT_BYTES
    assert max(x['result_retained_bytes'] for x in sizes)<=RETAINED_BYTES
    refresh_rows.append(dict(markets=n,evaluations=12,maxima={k:max(x[k] for x in sizes) for k in sizes[0]},
        retained_growth=current-initial,peak_bytes=peak,compiler_cross_call_cache_bytes=0,
        limits=dict(inflight=1,pending_evaluation_signals=1,pending_snapshots=0,pending_publications=1,
            snapshot_bytes=SNAPSHOT_BYTES,result_bytes=RESULT_BYTES,decoded_retained_bytes=RETAINED_BYTES),
        note='Traced allocations, not RSS. Measurement runs separately from performance trials. Pending publication belongs to the single in-flight chain.'))
Path(__file__).with_name('refresh-memory.json').write_text(json.dumps(refresh_rows,indent=2)+'\n')
print(json.dumps(refresh_rows,indent=2))
