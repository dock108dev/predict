"""Public schedule refresh, order-time selection and historical fee evidence."""
import asyncio
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.collection import public_fee_refresh as worker
from app.comparison.snapshot_fee_outcome import outcome
from app.fees import schedule_lifecycle as lifecycle
from app.storage import comparison_snapshot as snapshots, odds_replay, ordinary_publication as live
from app.storage.store import stamp
from tests.test_l02_native_finance import retained
from tests.test_snapshot_completion import fee_row

PDF = b'%PDF-1.7\nreviewed synthetic artifact\n%%EOF'
AT = stamp('2026-11-09T19:00:00Z')


def card(approval, *, version=None):
    return f'''<a href="{approval['document_url']}"><h4>Straight Trade Fees</h4>
    <p>All straight trades on site will be charged a trading fee based on the Fee Schedule for Straight Contracts</p>
    <p>Last Updated</p><p>{approval['published_update']}</p>
    <p>Version number</p><p>{version or approval['published_version']}</p></a>'''.encode()


@pytest.fixture
def approved():
    return dict(lifecycle.approved(), document_sha256=sha256(PDF).hexdigest())


def attempt(approved, at=AT, *, state=None, index=None, document=PDF, error=False, allowed=lambda: True):
    async def retrieve(url, limit):
        if error:
            raise httpx.ConnectError('fixture failure')
        body = (card(approved) if index is None else index) if url == lifecycle.SOURCE_URL else document
        return body, dict(url=url, retrieved_at=at.isoformat(), http_status=200, bytes=len(body),
                          sha256=sha256(body).hexdigest())

    return asyncio.run(worker.refresh(state, retrieve, clock=at.isoformat, load=lambda: approved, allowed=allowed))


def test_unchanged_refresh_renews_deadline_without_revoking_still_valid_terms(approved):
    first = attempt(approved)
    second = attempt(approved, AT + timedelta(hours=6), state=first, index=b'<p>New layout</p>'+card(approved)*2)
    assert second['last_attempt']['state'] == 'unchanged_verified'
    assert first['last_verified']['retrieval']['document']['sha256'] == second['last_verified']['retrieval']['document']['sha256']
    assert second['last_verified']['review_before'] == (AT + timedelta(hours=30)).isoformat()
    assert lifecycle.revision(first) == lifecycle.revision(second)
    assert lifecycle.publication_revision(first) != lifecycle.publication_revision(second)
    original = lifecycle.basis(first, AT)
    assert original['published_effective_from'] is None
    assert original['effective_from'] == AT.isoformat()
    assert lifecycle.basis(second, AT) is None


def test_failed_refresh_preserves_original_review_and_expires_at_original_deadline(approved):
    first = attempt(approved)
    failed = attempt(approved, AT + timedelta(hours=6), state=first, error=True)
    assert failed['last_attempt']['state'] == 'failed'
    assert failed['last_attempt']['error'] == 'fee_retrieval_failed'
    assert failed['last_verified'] == first['last_verified']
    assert failed['next_attempt_at'] == (AT + timedelta(hours=6, minutes=15)).isoformat()
    assert lifecycle.publication_revision(first) == lifecycle.publication_revision(failed)
    assert lifecycle.summary(failed, AT + timedelta(hours=24))['state'] == 'expired'
    assert attempt(approved, state=first, allowed=lambda: False) is None


@pytest.mark.parametrize('case,reason', [
    ('changed', 'public_straight_schedule_changed'),
    ('conflict', 'conflicting_straight_fee_documents'),
    ('bad_index', 'fee_index_unparseable'),
    ('bad_document', 'fee_document_unparseable'),
    ('override_conflict', 'conflicting_approved_rules'),
])
def test_public_conflict_and_unreadable_terms_require_explicit_review(approved, case, reason):
    first = attempt(approved)
    body = PDF
    index = card(approved)
    candidate = deepcopy(approved)
    if case == 'changed':
        body = b'%PDF-1.7\nchanged terms\n%%EOF'
    elif case == 'conflict':
        index += card(approved, version='2.0')
    elif case == 'bad_index':
        index = index.replace(b'Last Updated', b'Released')
    elif case == 'bad_document':
        body = b'<!doctype html>'
    else:
        candidate['rules'].append(dict(candidate['rules'][0], version='conflicting-rule'))
    later = AT + timedelta(hours=6)
    rejected = attempt(candidate, later, state=first, index=index, document=body)
    assert rejected['last_verified'] == first['last_verified']
    assert rejected['review_required']['reason'] == reason
    assert lifecycle.basis(rejected, later)['unavailable_reason'] == lifecycle.REVIEW_REQUIRED
    assert lifecycle.revision(rejected) != lifecycle.revision(first)
    if case != 'override_conflict':
        reverting = attempt(approved, later + timedelta(hours=1), state=rejected)
        assert reverting['last_attempt']['error'] == 'prior_change_requires_explicit_review'
        assert reverting['review_required'] == rejected['review_required']


@pytest.mark.parametrize('status,headers,body,reason', [
    (302, {}, b'', 'fee_http_status'),
    (200, {'content-encoding': 'gzip'}, b'a', 'fee_response_encoding_unsupported'),
    (200, {}, b'12345', 'fee_response_size_limit'),
])
def test_transport_bounds_keep_invalid_responses_out_of_verification(status, headers, body, reason):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield body

    def handler(request):
        assert request.headers['accept-encoding'] == 'identity'
        return httpx.Response(status, headers=headers, stream=Stream())

    async def retrieve():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
            with pytest.raises(worker.RetrievalFailed, match=reason) as failed:
                await worker.fetch(client, lifecycle.SOURCE_URL, 4)
            assert failed.value.receipt['http_status'] == status
            assert 'sha256' not in failed.value.receipt

    asyncio.run(retrieve())


def test_scheduled_override_switches_at_order_time_and_leaves_other_markets_unchanged(approved):
    cutover = AT + timedelta(hours=2)
    original = approved['rules'][0]
    approved['rules'].append(dict(version='reviewed-future-exact-market', market_id='market',
        effective_from=cutover.astimezone(ZoneInfo('America/New_York')).isoformat(),
        terms=dict(original['terms'], fee_rate='0.06')))
    state = attempt(approved)
    row = dict(fee_row(), venue='prophetx', source=dict(fee_row()['source'], native_market_id='alternate:market'))
    row.update(start_at='2026-11-10T02:00:00Z', league='NBA')
    old = lifecycle.for_offer(state, row, cutover - timedelta(microseconds=1))
    assert old['review_before'] == cutover.isoformat()
    assert lifecycle.summary(state, AT)['next_change']['market_id'] == 'market'
    new = lifecycle.for_offer(state, row, cutover)
    assert new['fee_rate'] == '0.06' and new['effective_from'] == cutover.isoformat()
    assert lifecycle.basis(state, cutover, 'another')['fee_rate'] == '0.02'
    fee = outcome(row, at=cutover, phase='scheduled', review=new)
    assert fee['fee_cashflows'] == {'at_fill_usd': '0', 'winning_settlement_usd': '0.03',
                                   'losing_settlement_usd': '0'}


def test_frozen_rebuild_and_inspection_keep_the_terms_captured_with_the_offer(approved, tmp_path, monkeypatch):
    inputs = retained()[1]
    inputs['captured_at'] = '2026-11-04T22:56:00+00:00'
    at = stamp(inputs['captured_at'])
    quote_at = (at - timedelta(seconds=10)).isoformat()
    for row in inputs['quotes']:
        if row['venue'] == 'prophetx':
            for quote in (row, row['original_record']['quote']):
                quote['times'].update(source_at=quote_at, received_at=quote_at)
    inputs['fee_lifecycle'] = attempt(approved, at - timedelta(minutes=10))
    owner = dict(healthy=True, active=True)
    states = {venue: dict(state='available') for venue in ('novig','prophetx','pinnacle','kalshi','polymarket_us')}
    settings = snapshots.assumptions()[0]
    captured = inputs, settings, owner, states
    replacement = deepcopy(approved)
    replacement['rules'][0]['terms']['fee_rate'] = '0.05'
    monkeypatch.setattr(lifecycle, 'approved', lambda: replacement)

    odds_replay.compile_archive('frozen', captured, tmp_path)
    with odds_replay.open_archive(tmp_path/'frozen.sqlite3') as db:
        board = snapshots.unpack(db.execute("SELECT payload FROM archive WHERE kind='board'").fetchone()[0])
        row = next(r for r in board['rows'] if r['venue'] == 'prophetx' and r['trade_fee']['available'])
        proof = snapshots.unpack(db.execute("SELECT payload FROM detail WHERE id=?", (row['id'],)).fetchone()[0])
    saved = proof['inspection']['trade_fee']['evidence']
    assert saved['fee_rate'] == '0.02' and saved['version'] == 'prophetx-retail-straight-1.0'
    assert saved['reviewed_at'] == (at - timedelta(minutes=10)).isoformat()

    # A contradictory live source withdraws the fee while the exact offer price
    # stays current. Replaying the saved archive continues to show its terms.
    bound = live.bind(snapshots.calculate(inputs, settings), inputs, 'ready')
    changed = attempt(approved, at, state=inputs['fee_lifecycle'], document=b'%PDF-1.7\nchanged\n%%EOF')
    read = live.project(bound, inputs['dependencies'], dict(owner, fee_lifecycle=changed), states,
                        at=at, epoch=inputs['epoch'], policy=inputs['policy_identity'])
    projected = next(r for r in read['rows'] if r['id'] == row['id'])
    assert projected['price_current'] and projected['trade_fee']['reason'] == lifecycle.REVIEW_REQUIRED
    assert projected['conservative_return_percent'] is None
