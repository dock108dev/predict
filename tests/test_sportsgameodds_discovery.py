"""Discovery pagination, persisted cursors, and paid-page admission."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from functools import partial
from hashlib import sha256
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.collection.current_policy import DEFAULT
from app.collection.sportsgameodds_adapter import Page
from app.collection.sportsgameodds_worker import SportsGameOddsWorker
from tests.sportsgameodds_fixtures import NOW, event


@pytest.fixture(autouse=True)
def acquisition_manifest(monkeypatch):
    # These scenarios supply provider pages and isolate the cursor owner.
    monkeypatch.setattr(SportsGameOddsWorker, '_begin_pull', lambda *args: 'discovery-pull')
    monkeypatch.setattr(SportsGameOddsWorker, '_renew_pull', lambda *args: True)
    monkeypatch.setattr(SportsGameOddsWorker, '_retain_pull', lambda *args: None)
    monkeypatch.setattr(SportsGameOddsWorker, '_fail_pull', lambda *args: None)
    monkeypatch.setattr(SportsGameOddsWorker, '_finish_discovery', lambda *args: None)


def test_discovery_retains_unique_members_through_mixed_overlaps(monkeypatch):
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, now=lambda: NOW)
        finished = []
        closing = Page((event(4),), (), None, 'c' * 64)
        worker._fetch = AsyncMock(side_effect=[Page((event(1), event(2)), (), 'next', 'a' * 64),
            Page((event(2), event(3)), (), 'last', 'b' * 64), closing])
        worker._finish_discovery = lambda page, traversal, reason: finished.append((page, traversal, reason))
        monkeypatch.setattr('app.collection.sportsgameodds_worker.aggregate_scope', lambda _: ['NFL'])
        await worker.cycle()
        assert [entry.args[0].get('cursor') for entry in worker._fetch.await_args_list] == [None, 'next', 'last']
        assert worker.metrics['discovery_complete'] == {'NFL': True}
        [(page, traversal, reason)] = finished
        assert page == closing and reason.startswith('discovery_cursor_closed')
        assert traversal._seen_events == {'e1', 'e2', 'e3', 'e4'}
        assert traversal.duplicate_events == 1
        assert not traversal.authoritative_absence
    asyncio.run(scenario())


def test_discovery_continues_beyond_first_twenty_events_without_withdrawal():
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        cursors = []
        async def fetch(params, key):
            n = int(params.get('cursor', '0'))
            cursors.append(n)
            return Page((event(2*n),event(2*n+1)), (), str(n+1) if n < 10 else None, 'a'*64)
        worker.collector = SimpleNamespace(fetch=fetch)
        worker.key = 'fixture'
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        await worker.cycle()
        assert cursors == list(range(10))
        assert worker.state.await_args_list[0].args[:2] == ('available', 'sgo_page_received')
        assert len(worker.events) == 20
        assert worker.metrics['discovery_complete']['NFL'] is False
        await worker.cycle()
        assert cursors == list(range(11))
        assert len(worker.events) == 22
        assert worker.metrics['discovery_complete']['NFL'] is True
        assert not worker.discovery_progress
    asyncio.run(scenario())


def test_large_discovery_keeps_cursor_past_old_hundred_page_limit():
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        async def fetch(params, key):
            n = int(params.get('cursor', '0'))
            return Page((event(2*n), event(2*n+1)), (), str(n+1) if n < 101 else None, 'a'*64)
        worker.collector = SimpleNamespace(fetch=fetch)
        worker.key = 'fixture'
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        for _ in range(11):
            await worker.cycle()
        assert len(worker.events) == 204
        assert worker.metrics['discovery_complete']['NFL'] is True
        assert not worker.discovery_progress
    asyncio.run(scenario())


def test_incomplete_page_cap_does_not_schedule_a_completed_walk():
    from unittest.mock import patch
    from app.collection.sportsgameodds_adapter import Traversal
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        worker.collector = SimpleNamespace(fetch=AsyncMock(return_value=Page((event(1),), (), 'next', 'a'*64)))
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        with patch('app.collection.sportsgameodds_worker.Traversal', side_effect=lambda **_: Traversal(max_pages=1)):
            await worker.cycle()
        assert worker.metrics['discovery_complete']['NFL'] is False
        assert 'NFL' in worker.metrics['discovery_unstable']
        assert 'NFL' not in worker.discovery_progress
    asyncio.run(scenario())


def test_rejected_cursor_clears_checkpoint_but_preserves_observations(tmp_path):
    import pytest
    from app.collection.sportsgameodds_collector import RejectedCursor
    from app.collection.sportsgameodds_ledger import ObjectLedger
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        worker.ledger = ObjectLedger(tmp_path / 'checkpoint.sqlite')
        calls = []
        async def fetch(params, key):
            calls.append(params)
            if 'cursor' in params:
                raise RejectedCursor('provider rejected cursor')
            if sum(p.get('leagueID') == 'NFL' for p in calls) > 2:
                return Page((), (), None, 'b'*64)
            return Page((event(1),), (), 'opaque', 'a'*64)
        worker.collector = SimpleNamespace(fetch=fetch)
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        with pytest.raises(RejectedCursor):
            await worker.cycle()
        assert 'e1' in worker.events
        assert 'NFL' not in worker.discovery_progress
        assert not worker.ledger.load_discovery_progress(now=NOW)
        assert worker.metrics['discovery_complete']['NFL'] is False
        assert 'NFL' in worker.metrics['discovery_unstable']
        from unittest.mock import patch
        with patch('app.collection.sportsgameodds_worker.aggregate_scope', return_value=['NFL']):
            await worker.cycle()
        assert calls[-1]['leagueID'] == 'NFL' and 'cursor' not in calls[-1]
        assert worker.metrics['discovery_complete']['NFL'] is True
    asyncio.run(scenario())


def test_moving_event_list_stops_traversal_without_removal():
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        async def fetch(params, key):
            return Page((event(1),), (), '1' if 'cursor' not in params else None, 'a'*64)
        worker.collector = SimpleNamespace(fetch=fetch)
        worker.key = 'fixture'
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        await worker.cycle()
        assert 'e1' in worker.events
        assert worker.discovery_at['NFL'] == NOW
        assert worker.metrics['discovery_complete']['NFL'] is False
        assert 'NFL' not in worker.discovery_progress
        # An unstable walk is retried after a short delay, not the normal
        # twelve-hour complete-discovery interval.
        worker.now = lambda: NOW + timedelta(minutes=14)
        worker.collector.fetch = AsyncMock()
        await worker.cycle()
        worker.collector.fetch.assert_not_awaited()
        worker.now = lambda: NOW + timedelta(minutes=15)
        worker.collector.fetch = AsyncMock(return_value=Page((event(2),), (), None, 'a'*64))
        await worker.cycle()
        worker.collector.fetch.assert_awaited_once()
        assert worker.metrics['discovery_complete']['NFL'] is True
        assert 'NFL' not in worker.metrics['discovery_unstable']
    asyncio.run(scenario())


def test_rate_interruption_rotates_discovery_without_losing_cursors():
    from unittest.mock import patch
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False,
                                  paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        calls = []
        async def fetch(params):
            calls.append(params['leagueID'])
            if len(calls) == 1:
                raise RuntimeError('request rate limit')
            return Page((), (), None, 'a'*64)
        worker._fetch = fetch
        with patch('app.collection.sportsgameodds_worker.aggregate_scope', return_value=['NFL', 'NBA']):
            try:
                await worker.cycle()
            except RuntimeError as exc:
                assert str(exc) == 'request rate limit'
            original = worker.discovery_progress['NFL']
            await worker.cycle()
        assert calls == ['NFL', 'NBA', 'NFL']
        assert original.complete
        assert worker.metrics['discovery_complete'] == {'NBA': True, 'NFL': True}
    asyncio.run(scenario())


def test_discovery_checkpoint_survives_restart_with_original_scope(tmp_path):
    from app.collection.sportsgameodds_ledger import ObjectLedger
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        ledger = ObjectLedger(tmp_path / 'ledger.sqlite')
        worker = SportsGameOddsWorker(service, now=lambda: NOW)
        worker.ledger = ledger
        worker.max_pages = 1
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        worker.collector = SimpleNamespace(fetch=AsyncMock(return_value=Page((event(1),), (), 'next', 'a'*64)))
        # Avoid requiring a budget window in this isolated checkpoint test.
        await worker.cycle()
        resumed = SportsGameOddsWorker(service, now=lambda: NOW + timedelta(minutes=2))
        resumed.ledger = ObjectLedger(tmp_path / 'ledger.sqlite')
        resumed.restore_discovery()
        traversal = resumed.discovery_progress['NFL']
        assert traversal.next_cursor == 'next'
        assert traversal.starts_after == NOW.isoformat()
        assert traversal._seen_events == {'e1'}
        assert traversal.authoritative_absence is False
        assert not traversal.complete
        resumed.collector = SimpleNamespace(fetch=AsyncMock(return_value=Page((event(1),), (), None, 'b'*64)))
        resumed._publish = AsyncMock()
        resumed.state = AsyncMock()
        await resumed.cycle()
        assert resumed.metrics['discovery_complete']['NFL'] is False
        assert 'NFL' not in resumed.discovery_progress
        assert 'NFL' not in ledger.load_discovery_progress(now=NOW + timedelta(minutes=2))
        assert 'NFL' not in ledger.discovery_schedule(now=NOW + timedelta(minutes=2))
    asyncio.run(scenario())


def test_stale_or_changed_discovery_checkpoint_is_not_restored(tmp_path):
    from app.collection.sportsgameodds_ledger import ObjectLedger
    service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
    ledger = ObjectLedger(tmp_path / 'ledger.sqlite')
    worker = SportsGameOddsWorker(service, now=lambda: NOW)
    worker.ledger = ledger
    params = worker.params(league='NFL', starts_after=(NOW-timedelta(hours=12)).isoformat())
    ledger.save_discovery_progress('NFL', {'params': params, 'next_cursor': 'next', 'pages': 1,
                                   'seen_cursors': [], 'seen_events': ['e1']}, now=NOW)
    later = SportsGameOddsWorker(service, now=lambda: NOW + timedelta(days=2))
    later.ledger = ledger
    later.restore_discovery()
    assert not later.discovery_progress
    live_service = SimpleNamespace(config=dict(service.config, live_enabled=True), dispatch=True,
                                   globally_stopped=False, paused_sources=set())
    live = SportsGameOddsWorker(live_service, now=lambda: NOW)
    live.ledger = ledger
    live.restore_discovery()
    assert not live.discovery_progress
    worker.page_limit = 3
    worker.restore_discovery()
    assert not worker.discovery_progress


def test_restored_walk_completes_only_after_new_final_page(tmp_path):
    from app.collection.sportsgameodds_ledger import ObjectLedger
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        ledger = ObjectLedger(tmp_path / 'ledger.sqlite')
        first = SportsGameOddsWorker(service, now=lambda: NOW)
        first.ledger = ledger
        first.max_pages = 1
        first._publish = AsyncMock()
        first.state = AsyncMock()
        first.collector = SimpleNamespace(fetch=AsyncMock(return_value=Page((event(1),), (), 'next', 'a'*64)))
        await first.cycle()
        original_query = first.collector.fetch.await_args.args[0]
        checkpoint = ledger.load_discovery_progress(now=NOW)['NFL']
        assert checkpoint['params'] == original_query
        assert original_query['started'] is original_query['live'] is False
        assert original_query['startsAfter'] == NOW.isoformat()
        second = SportsGameOddsWorker(service, now=lambda: NOW + timedelta(minutes=2))
        second.ledger = ObjectLedger(tmp_path / 'ledger.sqlite')
        second.restore_discovery()
        second._publish = AsyncMock()
        second.state = AsyncMock()
        second.collector = SimpleNamespace(fetch=AsyncMock(return_value=Page((event(2),), (), None, 'b'*64)))
        await second.cycle()
        params = second.collector.fetch.await_args_list[0].args[0]
        assert params == dict(original_query, cursor='next')
        assert second.metrics['discovery_complete']['NFL'] is True
        assert 'NFL' in ledger.discovery_schedule(now=NOW + timedelta(minutes=2))
        assert 'NFL' not in ledger.load_discovery_progress(now=NOW + timedelta(minutes=2))
    asyncio.run(scenario())


def test_wrong_league_page_is_billed_without_advancing_discovery(tmp_path):
    from app.collection.sportsgameodds_collector import InvalidProviderPage
    from app.collection.sportsgameodds_transport import PageResponse
    from tests.test_sportsgameodds_adapter import response

    async def scenario():
        service = SimpleNamespace(config=dict(DEFAULT, sports=['NFL', 'NBA']), dispatch=True,
                                  globally_stopped=False, paused_sources=set())
        transport = SimpleNamespace(fetch=AsyncMock())
        usage = dict(tier='fixture', limit=1000, used=10, requests_per_minute=10,
                     reset_at=NOW + timedelta(days=10), at=NOW)
        worker = SportsGameOddsWorker(service, transport=transport, now=lambda: NOW,
                                      key_loader=lambda: 'fixture', usage_reader=AsyncMock(return_value=usage),
                                      ledger_path=tmp_path / 'ledger.sqlite')
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        worker.refresh = AsyncMock()
        worker.max_pages = 1
        await worker.initialize()
        worker.collector.fetch = partial(worker.collector.fetch, now=NOW)

        wrong = response()['data'][0]
        first = dict(wrong, eventID='nfl-event', leagueID='NFL')
        valid = dict(first, eventID='nfl-event-two')
        payload = json.dumps(dict(success=True, data=[valid, wrong], nextCursor='wrong-next')).encode()
        responses = iter((
            (PageResponse(200, json.dumps(dict(success=True, data=[first], nextCursor='nfl-next')).encode(),
                          NOW.isoformat(), None), 1),
            (PageResponse(200, b'{"success":true,"data":[]}', NOW.isoformat(), None), 1),
            (PageResponse(200, payload, NOW.isoformat(), None, provider_request_id='wrong-league-fixture'), 2),
            (PageResponse(200, b'{"success":true,"data":[]}', NOW.isoformat(), None), 1),
        ))

        async def fetch(*_):
            observed, charge = next(responses)
            usage['used'] += charge
            return observed

        transport.fetch.side_effect = fetch
        await worker.cycle()
        prior = worker.ledger.load_discovery_progress(now=NOW)['NFL']
        assert prior['next_cursor'] == 'nfl-next'
        worker._publish.reset_mock()

        with pytest.raises(InvalidProviderPage, match='outside requested league') as rejected:
            await worker.cycle()
        assert transport.fetch.await_args.args[0]['cursor'] == 'nfl-next'
        worker._publish.assert_not_awaited()
        assert set(worker.events) == {'nfl-event'}
        assert worker.ledger.load_discovery_progress(now=NOW)['NFL'] == prior
        assert 'NFL' not in worker.ledger.discovery_schedule(now=NOW)
        assert worker.metrics['discovery_complete']['NFL'] is False
        assert await worker.wait_for_dispatch(rejected.value, retry_at=NOW + timedelta(minutes=15))
        assert worker.state.await_args.args[:2] == ('budget_delayed', 'sgo_discovery_league_mismatch')
        assert worker.ledger.status(worker.window_id)['charged'] == 4
        assert worker.ledger.status(worker.window_id)['interrupted'] == 0
        with sqlite3.connect(worker.ledger_path) as db:
            assert db.execute('''SELECT r.status,r.charged,t.response_sha256
                FROM sgo_request_trace t JOIN sgo_object_reservation r ON r.id=t.reservation_id
                WHERE t.provider_request_id='wrong-league-fixture' ''').fetchone() == (
                    'resolved', 2, sha256(payload).hexdigest())
        await worker.cycle()
        assert transport.fetch.await_args.args[0]['cursor'] == 'nfl-next'
        assert worker.metrics['discovery_complete']['NFL'] is True
        assert 'NFL' in worker.ledger.discovery_schedule(now=NOW)

    asyncio.run(scenario())
