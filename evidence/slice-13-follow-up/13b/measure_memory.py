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
