"""EV03 representative authored slate at the explicit EV04 model boundary.

Only the authored observation clock is changed before admission. Retained
fixtures and every historical workload remain intact. This is no live evidence.
"""
from datetime import datetime, timezone
from time import perf_counter
from tests import ev03_workload
from tests.current_fixture import fixture
from app.dashboard.current_normalized import catalog_from_normalized
from app.dashboard.current_contract import quotes_of
from app.collection.current_benchmark import attach

AT = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


def workload():
    rows, refs, expected = ev03_workload.records()
    def move(value):
        if isinstance(value, dict):return {k:move(v) for k,v in value.items()}
        if isinstance(value, list):return [move(v) for v in value]
        if isinstance(value, str):return value.replace('2026-10-08T','2026-10-11T').replace('2026-10-09T','2026-10-12T')
        return value
    rows, refs = move(rows), move(refs)
    for r in rows:r['quote'].pop('sharp_reference',None)
    for event in {r['event']['id'] for r in rows}:
        group=[r for r in rows if r['event']['id']==event]
        attach(group,[r for r in refs if r['event']['id']==event])
        for i,r in enumerate(group):
            if not expected[int(event.rsplit(':',1)[1])][i]:r['quote'].pop('sharp_reference',None)
    envelope = fixture()
    envelope.update(events=[], runtime_id='synthetic:ev04:150-games-2000-quotes',
                    clock_at=AT.isoformat(), projected_at=AT.isoformat())
    started = perf_counter()
    raw = catalog_from_normalized(envelope, rows, reference_records=refs)
    assert sum('estimate_content' in q['comparison_input_status']['fee'] for e in raw['events']
               for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)) == 2000
    return raw, expected, perf_counter() - started
