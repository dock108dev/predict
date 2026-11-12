import asyncio
import sqlite3
from functools import wraps
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.collection.sportsgameodds_collector import GuardedPageCollector, RejectedCursor
from app.collection.sportsgameodds_ledger import ObjectLedger
from app.collection.sportsgameodds_transport import PageResponse

NOW = datetime(2026, 11, 10, 20, tzinfo=timezone.utc)
RESET = NOW + timedelta(days=10)
PARAMS = {'leagueID': 'NBA', 'oddID': 'points-home-game-ml-home', 'limit': 5}


def run_async(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapper


def setup(tmp_path, response):
    ledger = ObjectLedger(tmp_path / 'book.sqlite')
    ledger.create_window('w', limit=100, initial_used=10, reserve=10, reset_at=RESET, requests_per_minute=10)
    usage = AsyncMock(return_value={'used': 10, 'limit': 100, 'reset_at': RESET, 'requests_per_minute': 10, 'at': NOW})
    transport = SimpleNamespace(fetch=AsyncMock(return_value=response))
    collector = GuardedPageCollector(ledger, 'w', transport, controls=lambda: {'stopped': False, 'source_paused': False}, account_usage=usage)
    return collector, ledger, usage, transport


@run_async
async def test_successful_empty_page_accounts_minimum(tmp_path):
    c, ledger, _, _ = setup(tmp_path, PageResponse(200, b'{"success":true,"data":[]}', NOW.isoformat(), None))
    page = await c.fetch(PARAMS, 'private', now=NOW)
    assert not page.events
    assert ledger.status('w')['charged'] == 1
    assert ledger.status('w')['held'] == 0
    with sqlite3.connect(ledger.path) as db:
        assert db.execute('SELECT category, league FROM sgo_reservation_context').fetchall() == [('discovery', 'NBA')]
        assert db.execute('SELECT league, phase, objects FROM sgo_charge_breakdown').fetchall() == [('NBA', 'unknown', 1)]


@run_async
async def test_event_refresh_category_is_recorded_before_dispatch(tmp_path):
    c, ledger, _, transport = setup(tmp_path, PageResponse(200, b'{"success":true,"data":[]}', NOW.isoformat(), None))
    async def fetch(*args):
        with sqlite3.connect(ledger.path) as db:
            assert db.execute('SELECT category, league FROM sgo_reservation_context').fetchall() == [('event_refresh', None)]
        return PageResponse(200, b'{"success":true,"data":[]}', NOW.isoformat(), None)
    transport.fetch.side_effect = fetch
    await c.fetch({'eventIDs': 'event-1', 'oddID': PARAMS['oddID'], 'limit': 1}, 'private', now=NOW)
    assert ledger.status('w')['charged'] == 1


@run_async
async def test_refresh_attributes_returned_events_not_requested_ids(tmp_path):
    c, ledger, _, _ = setup(tmp_path, PageResponse(200, b'{}', NOW.isoformat(), None))
    page = SimpleNamespace(events=[{'league': 'NBA', 'phase': 'live'},
                                   {'league': 'NCAAB', 'phase': 'started'}])
    with patch('app.collection.sportsgameodds_collector.parse_page', return_value=page):
        await c.fetch({'eventIDs': 'a,b', 'oddID': PARAMS['oddID'], 'limit': 2}, 'private', now=NOW)
    assert ledger.charge_breakdown('w', since=NOW - timedelta(seconds=1)) == [
        {'category': 'event_refresh', 'league': 'NBA', 'phase': 'live', 'objects': 1},
        {'category': 'event_refresh', 'league': 'NCAAB', 'phase': 'started', 'objects': 1},
    ]


@run_async
async def test_bad_response_or_429_retains_uncertain_reservation(tmp_path):
    c, ledger, _, _ = setup(tmp_path, PageResponse(429, b'', NOW.isoformat(), 60))
    with pytest.raises(RuntimeError, match='rate limited'):
        await c.fetch(PARAMS, 'private', now=NOW)
    assert ledger.status('w')['held'] == 5
    with sqlite3.connect(ledger.path) as db:
        assert db.execute('SELECT category, league FROM sgo_reservation_context').fetchall() == [('discovery', 'NBA')]
    assert ledger.status('w')['retry_after'] == NOW + timedelta(seconds=60)
    with pytest.raises(RuntimeError, match='unresolved'):
        await c.fetch(PARAMS, 'private', now=NOW + timedelta(minutes=1))


@run_async
async def test_rejected_cursor_retains_reservation(tmp_path):
    c, ledger, _, _ = setup(tmp_path, PageResponse(400, b'', NOW.isoformat(), None, True))
    with pytest.raises(RejectedCursor):
        await c.fetch(dict(PARAMS, cursor='opaque'), 'private', now=NOW)
    assert ledger.status('w')['held'] == 5
    with pytest.raises(RuntimeError, match='unresolved'):
        await c.fetch(PARAMS, 'private', now=NOW)


@run_async
async def test_changed_account_or_stop_never_dispatches(tmp_path):
    c, ledger, usage, transport = setup(tmp_path, PageResponse(200, b'', NOW.isoformat(), None))
    usage.return_value['used'] = 9
    with pytest.raises(RuntimeError, match='usage evidence'):
        await c.fetch(PARAMS, 'private', now=NOW)
    usage.return_value['used'] = 10
    c.controls = lambda: {'stopped': True, 'source_paused': False}
    with pytest.raises(RuntimeError, match='stopped'):
        await c.fetch(PARAMS, 'private', now=NOW)
    transport.fetch.assert_not_awaited()
    assert ledger.status('w')['held'] == 0


@run_async
async def test_other_client_usage_reduces_available_allowance(tmp_path):
    c, ledger, usage, _ = setup(tmp_path, PageResponse(200, b'{"success":true,"data":[]}', NOW.isoformat(), None))
    usage.return_value['used'] = 13
    await c.fetch(PARAMS, 'private', now=NOW)
    state = ledger.status('w')
    assert state['initial_used'] == 13
    assert state['charged'] == 1
    assert state['available'] == 76


@run_async
async def test_account_observation_timestamp_after_request_start_is_accepted(tmp_path):
    from datetime import datetime, timezone
    c, ledger, usage, _ = setup(tmp_path, PageResponse(200, b'{"success":true,"data":[]}', NOW.isoformat(), None))
    reset = datetime.now(timezone.utc) + timedelta(days=2)
    ledger = ObjectLedger(tmp_path / 'current.sqlite')
    ledger.create_window('w', limit=1000, initial_used=10, reserve=10, reset_at=reset, requests_per_minute=10)
    c.ledger = ledger
    async def observe():
        return {'used':10, 'limit':1000, 'requests_per_minute':10, 'reset_at':reset, 'at':datetime.now(timezone.utc)}
    c.account_usage = observe
    await c.fetch(PARAMS, 'private')
    assert ledger.status('w')['charged'] == 1


@run_async
async def test_daily_pacing_refuses_an_oversized_page_before_dispatch(tmp_path):
    c, ledger, usage, transport = setup(tmp_path, PageResponse(200, b'', NOW.isoformat(), None))
    ledger = ObjectLedger(tmp_path / 'paced.sqlite')
    ledger.create_window('w', limit=100, initial_used=10, reserve=10, reset_at=NOW+timedelta(days=30), requests_per_minute=10)
    c.ledger = ledger
    usage.return_value['reset_at'] = NOW+timedelta(days=30)
    with pytest.raises(RuntimeError, match='daily object pacing'):
        await c.fetch(PARAMS, 'private', now=NOW)
    transport.fetch.assert_not_awaited()
