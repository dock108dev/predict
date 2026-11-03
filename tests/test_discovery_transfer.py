"""Disposable-worker hint transfers fail cold and retain bounded lifetimes."""
import json
import time
from app.storage import discovery_index as index


def test_transfer_round_trip_keeps_age_and_ignores_partial_temporary(tmp_path):
    index.clear()
    try:
        path=tmp_path/'discovery.json'
        index._CACHE['proof']=dict(created=index.monotonic()-20,captured_at='2026-11-01T12:00:00+00:00',
            boundary=None,game='game',dependency_key='dependency',plan=dict(units=[],contracts={}))
        index._OCCURRENCES['structure']=(index.monotonic()-30,b'{"audits":{},"changes":[]}')
        assert index.save_transfer(path)
        path.with_suffix('.tmp').write_text('{"partial":')
        index.clear()
        assert index.load_transfer(path)=='transferred'
        assert 20<=index.monotonic()-index._CACHE['proof']['created']<25
        assert 30<=index.monotonic()-index._OCCURRENCES['structure'][0]<35
        assert index._CACHE['proof']['plan']==dict(units=[],contracts={})
    finally:index.clear()


def test_missing_truncated_expired_and_oversize_transfers_rebuild_cold(tmp_path):
    index.clear()
    try:
        path=tmp_path/'discovery.json'
        assert index.load_transfer(path)=='transfer_missing_or_invalid'
        path.write_text('{"version":2,"plans":[')
        assert index.load_transfer(path)=='transfer_missing_or_invalid'
        path.write_text(json.dumps(dict(version=2,saved_at=time.time()-index.TTL_SECONDS-1,plans=[],occurrences=[])))
        assert index.load_transfer(path)=='transfer_expired'
        path.write_bytes(b' '* (index.TRANSFER_BYTES+1))
        assert index.load_transfer(path)=='transfer_capacity'
        assert not index._CACHE and not index._OCCURRENCES
    finally:index.clear()
