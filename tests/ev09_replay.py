"""Acquisition-free replay of retained actual NFL inputs and overlapping reads."""
import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import patch
from hashlib import sha256

from app.collection.current_policy import DEFAULT
from app.collection.current_sink import LatestStateSink
from app.collection.current_retained import RetainedInputs
from app.dashboard.current_state import CurrentStore, unavailable
from app.dashboard.current_contract import packed, snapshot_inputs

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'test-results/ev09-delivery-20261013'


def actual_raw():
    path = ROOT / 'test-results/conservative-recovery-implemented-20261013/final-delivered-observations.jsonl'
    record = next(json.loads(line) for line in path.open()
                  if json.loads(line)['kind'] == 'aggregate_batch' and json.loads(line)['value']['sport'] == 'NFL')
    value = record['value']; body = base64.b64decode(value['body_b64'])
    assert sha256(body).hexdigest() == value['body_sha256']
    raw = unavailable(); raw.update(runtime_id=record['runtime_id'], clock_at=value['received_at'], projected_at=value['received_at'])
    capture = RetainedInputs(raw); sink = LatestStateSink(capture, raw, DEFAULT)
    with patch('app.collection.current_sink.utc', return_value=value['received_at']):
        sink.commit(dict(type='current_aggregate', source='the_odds_api', sport='NFL',
                         body=body, received_at=value['received_at']), raw['source_status'])
    return capture._state, value['body_sha256']


async def main():
    raw, source_hash = actual_raw()
    class Provider:
        allow_synthetic = False
        def initial_state(self): return raw
        async def close(self): pass
    tick = [0]; store = CurrentStore(Provider(), monotonic=lambda: tick[0])
    captured = store._state; epoch = store._calculation_epoch
    expected = packed(captured); reader = store.encoded_transport_snapshot()
    parts = []; error = None
    class Writer:
        async def write(self, block):
            parts.append(block)
            if len(parts) == 1:
                incoming = snapshot_inputs(store._state)
                incoming['state_revision'] += 1
                store.commit(incoming)
                tick[0] = 1; store.refresh_age()
    try: await reader.write(Writer())
    except Exception as exc: error = dict(type=type(exc).__name__, reason=str(exc))
    result = dict(evidence_class='isolated replay of actual retained inputs; no acquisition',
        source_sha256=source_hash, runtime_id=captured['runtime_id'], state_revision=captured['state_revision'],
        calculation_epoch=epoch, latest_epoch=store._calculation_epoch,
        economic_deadline=str(store._economic_deadline), reader_seconds=store.encoded_bodies.READER_SECONDS,
        expected_bytes=len(expected), delivered_bytes=sum(map(len,parts)), chunks=len(parts), exception=error,
        headers_committed=True, body_complete=b''.join(parts)==expected,
        reader_released=reader.closed, active_readers=len(store.encoded_bodies.readers),
        cause='ordinary source supersession during captured body; no Stop, expiry or resource stop',
        owners=store.encoded_bodies.metrics)
    REPORT.mkdir(exist_ok=True)
    destination = REPORT / ('replay-before.json' if error else 'replay-after.json')
    assert not destination.exists(), 'Preserve earlier replay evidence'
    destination.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))
    await store.close()


if __name__ == '__main__': asyncio.run(main())
