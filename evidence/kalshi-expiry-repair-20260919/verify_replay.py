"""Read immutable admitted history with repaired candidate; write only this repair directory."""
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import socket
from unittest.mock import patch

from app.collection.segmented import SegmentedReader
from app.collection.native_replay import GroupedNativeVerifier

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
OLD = ROOT / 'evidence/coverage-diagnosis-20260919'
LIVE = ROOT / 'evidence/supervised-5m-live-20260916'
def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def forbidden(*args, **kwargs): raise AssertionError('offline replay: network forbidden')

with patch.object(socket.socket, 'connect', forbidden), patch.object(socket.socket, 'connect_ex', forbidden):
    validation = read(LIVE / 'attempt/validation.json')
    sid = validation['session']
    history = LIVE / 'attempt' / sid / 'history'
    retained = read(OLD / 'identity-and-replay.json')
    analysis = read(LIVE / 'analysis.json')
    manifest = read(history / 'manifest.json')
    assert sha(history / 'manifest.json') == analysis['exact_history_manifest']
    assert sha(history.parent / 'manifest.json') == analysis['exact_replay_manifest']
    for seg in manifest['segments']:
        assert sha(history / seg['name']) == seg['sha256']
    rows = list(SegmentedReader(history).rows())
    assert len(rows) == 6218
    assert all(row['session_id'] == sid for row in rows)
    assert len({row['ingress_id'] for row in rows if 'ingress_id' in row}) == 6217
    verifier = GroupedNativeVerifier('predict-supervised-segmented-5m-v1')
    historical = {o['ingress_id']: o for m in read(OLD / 'per-market.json')['markets'] for o in m['observations']}
    stale = Counter()
    stale_rows = []
    packets = 0
    for row in rows:
        if 'body_b64' in row:
            assert hashlib.sha256(base64.b64decode(row['body_b64'])).hexdigest() == row['body_sha256']
        verifier.feed(row)
        if row['type'] == 'prediction_book':
            book = row['book']
            old = historical[row['ingress_id']]
            assert old['observed_at'] == row['observed_at']
            assert old['native_received_at'] == book['raw']['received_at']
            assert old['receipt_freshness'] == book['receipt_freshness']
            packets += len(row['packets'])
            if book['receipt_freshness'] == 'stale':
                stale[row['source']] += 1
                stale_rows.append([row['ingress_id'], row['observed_at'], book['raw']['received_at']])
    result = verifier.result()
    assert result == retained['replay']
    native = sum(sum(g['exact_native_books'].values()) for g in result.values())
    assert native == 1885 and verifier.derived_health_books == 149 and packets == 4068
    assert stale == {'kalshi': 112, 'polymarket_us': 37}
    assert all(g['exact_packets'] and not g['gaps'] for g in result.values())
    report = dict(session=sid, rows=len(rows), native_books=native,
                  derived_stale_books=verifier.derived_health_books, exact_packets=packets,
                  stale_counts=dict(stale), all_2034_historical_emission_and_receipt_times_match=True,
                  historical_stale_times_sha256=hashlib.sha256(json.dumps(stale_rows,separators=(',',':')).encode()).hexdigest(),
                  segment_hashes_verified=len(manifest['segments']), replay=result,
                  history_manifest_sha256=sha(history/'manifest.json'),
                  note='Historical observed emissions replayed exactly; no nominal-deadline replacement.')
    (OUT / 'retained-replay.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='replay'},indent=2))
