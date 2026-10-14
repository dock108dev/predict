"""Explicit EV05 long-only authored slate, preserving historical generators.

EV03/04's Short observations lack scoped collateral and must remain refused by
EV05. This active-model workload independently declares Long contracts for those
synthetic IDs, removes their bid-complement transformation, and hashes those new
authored inputs before admission. Counts/reference omissions stay identical.
"""
from copy import deepcopy
from hashlib import sha256
from time import perf_counter
import json

from tests.ev04_workload import AT
from tests.ev03_workload import records
from tests.current_fixture import fixture
from app.collection.current_benchmark import attach
from app.dashboard.current_normalized import catalog_from_normalized


def workload(games=150, quotes=2000):
    rows, refs, expected=records(games,quotes)
    def move(value):
        if isinstance(value,dict):return {k:move(v) for k,v in value.items()}
        if isinstance(value,list):return [move(v) for v in value]
        if isinstance(value,str):return value.replace('2026-10-08T','2026-10-11T').replace('2026-10-09T','2026-10-12T')
        return value
    rows,refs=move(rows),move(refs)
    for record in rows:
        q=record['quote'];q.pop('sharp_reference',None)
        if q['source']['native_side'].lower()=='short':
            q['source']['native_side']='Long'
            for key in ('native_value','native_units','transformation'):q['original'].pop(key,None)
            record['comparison_source_metadata']['native_key'][-1]='Long'
        q['rule_note']='Authored EV05 Long contract; normal winner, actual exceptional settlement unknown'
        q['provenance']['sha256']=sha256(json.dumps(dict(source=q['source'],original=q['original'],
            selection=record['selection'],rule_note=q['rule_note']),sort_keys=True).encode()).hexdigest()
    for event in {r['event']['id'] for r in rows}:
        local=[r for r in rows if r['event']['id']==event]
        attach(local,[r for r in refs if r['event']['id']==event])
        for i,r in enumerate(local):
            if not expected[int(event.rsplit(':',1)[1])][i]:r['quote'].pop('sharp_reference',None)
    envelope=fixture();envelope.update(events=[],runtime_id='synthetic:ev05:long:150-games-2000-quotes',
        clock_at=AT.isoformat(),projected_at=AT.isoformat())
    started=perf_counter()
    raw=catalog_from_normalized(envelope,rows,reference_records=refs)
    return raw,expected,perf_counter()-started
