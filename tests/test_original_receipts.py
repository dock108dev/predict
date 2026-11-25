import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.collection.original_receipts import capture, encoded, lookup, read, status, writable
from app.collection.sportsgameodds_adapter import parse_page
from app.collection.sportsgameodds_current_rows import current_rows
from app.collection.sportsgameodds_transport import PageResponse
from tests.test_sportsgameodds_adapter import AT, response
from tests.test_sportsgameodds_collector import NOW, PARAMS, setup


def receipt():
    value = response()
    odds = value['data'][0]['odds']
    odds['player-test'] = dict(periodID='game', statID='rebounds', betTypeID='ou',
                               playerID='player-retained-only')
    value['data'][0]['results'] = {'game': {'home': {'points': '99'}, 'away': {'points': '98'}}}
    return PageResponse(200, json.dumps(value).encode(), AT, None)


def test_original_response_reparse_keeps_supported_identity_price_clocks_and_unsupported_fields(tmp_path):
    raw = receipt()
    original = parse_page(raw.body, raw.received_at)
    saved = capture(PARAMS, raw, root=tmp_path)
    metadata, restored = read(saved['id'], root=tmp_path)
    reparsed = parse_page(restored, metadata['received_at'])
    assert current_rows(reparsed, metadata['receipt_sha256']) == current_rows(original, original.receipt_sha256)
    assert reparsed.quotes == original.quotes
    assert b'player-retained-only' in restored
    assert saved['fields']['received_unsupported_markets'] == 1
    assert saved['fields']['other_markets'] == 'not_requested'
    assert saved['fields']['received_result_events'] == 1
    assert lookup(original.receipt_sha256, root=tmp_path)['state'] == 'retained'
    assert saved['gzip_bytes'] < saved['raw_bytes']
    assert saved['admission'] == 'not_inferred_from_retention'


def test_safe_scope_idempotency_and_identical_response_deduplication(tmp_path):
    raw = receipt()
    params = dict(PARAMS, cursor='private-provider-cursor')
    saved = capture(params, raw, root=tmp_path)
    assert capture(params, raw, root=tmp_path) == saved
    later = replace(raw, received_at='2026-11-10T20:01:00Z')
    assert capture(params, later, root=tmp_path)['id'] != saved['id']
    assert len(list(tmp_path.glob('*.json.gz'))) == 1
    assert saved['request_scope']['cursor'] == sha256(params['cursor'].encode()).hexdigest()
    assert 'private-provider-cursor' not in json.dumps(saved)
    assert status(root=tmp_path)['captured_receipts'] == 2
    with pytest.raises(ValueError):
        capture(dict(PARAMS, api_key='secret'), raw, root=tmp_path)


@pytest.mark.parametrize(('limits', 'reason'), [
    ({'max_bytes': 0}, 'compressed_byte_cap'),
    ({'max_receipts': 0}, 'receipt_count_cap'),
])
def test_retention_cap_reports_gap_without_deleting_prior_evidence(tmp_path, limits, reason):
    saved = capture(PARAMS, receipt(), root=tmp_path, **limits)
    assert saved['state'] == 'not_retained' and saved['reason'] == reason
    assert not list(tmp_path.glob('*.json.gz'))
    assert status(root=tmp_path)['gaps'][0]['reason'] == reason


def test_retention_resumes_after_previous_count_cap_without_rewriting_history(tmp_path):
    previous_cap = 4096
    raw = receipt()
    saved = capture(PARAMS, raw, root=tmp_path, max_receipts=previous_cap)
    start = datetime.fromisoformat(raw.received_at)

    def existing_receipts():
        for offset in range(1, previous_cap):
            at = (start + timedelta(seconds=offset)).isoformat()
            identity = sha256(encoded([saved['receipt_sha256'], at, saved['request_scope'],
                                       saved['parser_version']])).hexdigest()
            metadata = dict(saved, id=identity, received_at=at)
            yield identity, saved['receipt_sha256'], at, encoded(metadata).decode()

    with writable(tmp_path) as manifest:
        manifest.executemany('INSERT INTO receipt VALUES (?,?,?,?)', existing_receipts())

    missed = replace(raw, body=raw.body + b' ', received_at=(start + timedelta(hours=2)).isoformat())
    assert capture(PARAMS, missed, root=tmp_path, max_receipts=previous_cap)['reason'] == 'receipt_count_cap'
    next_raw = replace(raw, body=raw.body + b'  ', received_at=(start + timedelta(hours=3)).isoformat())
    recovered = capture(PARAMS, next_raw, root=tmp_path)

    assert recovered['state'] == 'retained'
    assert read(recovered['id'], root=tmp_path)[1] == next_raw.body
    assert read(saved['id'], root=tmp_path) == (saved, raw.body)
    assert lookup(sha256(missed.body).hexdigest(), root=tmp_path)['state'] == 'not_recorded'
    current = status(root=tmp_path)
    assert current['captured_receipts'] == previous_cap + 1
    assert current['receipt_cap'] == 16_384
    assert [(gap['reason'], gap['count']) for gap in current['gaps']] == [('receipt_count_cap', 1)]


def test_disk_guard_and_corrupt_payload_do_not_claim_reparse(tmp_path):
    with patch('app.collection.original_receipts.shutil.disk_usage', return_value=SimpleNamespace(free=0)):
        saved = capture(PARAMS, receipt(), root=tmp_path)
    assert saved['reason'] == 'disk_free_floor'
    later = replace(receipt(), received_at='2026-11-10T20:01:00Z')
    saved = capture(PARAMS, later, root=tmp_path)
    payload, = tmp_path.glob('*.json.gz')
    payload.write_bytes(b'broken')
    assert lookup(saved['receipt_sha256'], root=tmp_path)['state'] == 'unavailable'
    assert capture(PARAMS, later, root=tmp_path)['reason'] == 'original_receipt_storage_error'
    with pytest.raises((OSError, EOFError, ValueError)):
        read(saved['id'], root=tmp_path)
    again = capture(PARAMS, replace(later, received_at='2026-11-10T20:02:00Z'), root=tmp_path)
    assert again['reason'] == 'original_receipt_storage_error'


def test_player_points_are_received_but_not_supported_and_bad_manifest_is_optional(tmp_path):
    raw = json.loads(receipt().body)
    raw['data'][0]['odds']['player-points'] = dict(periodID='game', statID='points', betTypeID='ou',
                                                sideID='over', statEntityID='player-id')
    saved = capture(PARAMS, replace(receipt(), body=json.dumps(raw).encode()), root=tmp_path)
    assert saved['fields']['received_supported_markets'] == 1
    assert saved['fields']['received_unsupported_markets'] == 2
    (tmp_path / 'manifest.sqlite3').write_bytes(b'bad sqlite database')
    assert status(root=tmp_path)['state'] == 'unavailable'
    assert lookup(saved['receipt_sha256'], root=tmp_path)['state'] == 'unavailable'


def test_passive_absent_manifest_and_transport_errors_never_create_retention(tmp_path):
    root = tmp_path / 'absent'
    assert lookup('a' * 64, root=root)['state'] == 'not_recorded'
    assert status(root=root)['state'] == 'not_started'
    assert not root.exists()
    assert capture(PARAMS, PageResponse(500, b'', AT, None), root=root)['state'] == 'not_retained'
    assert not root.exists()


def test_retention_full_never_changes_charge_or_successful_ingress_eligibility(tmp_path):
    raw = PageResponse(200, b'{"success":true,"data":[]}', NOW.isoformat(), None)
    collector, ledger, _, transport = setup(tmp_path, raw)
    collector.receipt_retainer = lambda params, raw: capture(params, raw, root=tmp_path / 'raw', max_bytes=0)
    page = asyncio.run(collector.fetch(PARAMS, 'private', now=NOW))
    assert not page.events
    assert (ledger.status('w')['charged'], ledger.status('w')['held']) == (1, 0)
    transport.fetch.assert_awaited_once()
    assert status(root=tmp_path / 'raw')['gaps'][0]['count'] == 1


def test_worker_retention_follows_disposable_ledger_namespace(tmp_path):
    from app.collection.sportsgameodds_worker import SportsGameOddsWorker
    worker = SportsGameOddsWorker(SimpleNamespace(), ledger_path=tmp_path / 'fixture-ledger.sqlite3')
    asyncio.run(worker.retain_original(PARAMS, receipt()))
    assert worker.metrics['original_receipt']['state'] == 'retained'
    assert status(root=tmp_path / 'original-responses')['captured_receipts'] == 1
