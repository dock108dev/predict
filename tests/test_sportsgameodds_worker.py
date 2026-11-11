import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.collection.current_policy import DEFAULT
from app.collection.sportsgameodds_adapter import Page
from app.collection.sportsgameodds_worker import SportsGameOddsWorker

NOW = datetime(2026, 11, 10, 20, tzinfo=timezone.utc)


def event(n):
    return {'event_id': f'e{n}', 'league':'NFL', 'starts_at':(NOW + timedelta(days=4)).isoformat(),
            'received_at':NOW.isoformat(), 'phase':'pregame', 'status':{}}


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
        await worker.cycle()
        assert cursors == list(range(10))
        assert len(worker.events) == 20
        assert worker.metrics['discovery_complete']['NFL'] is False
        await worker.cycle()
        assert cursors == list(range(11))
        assert len(worker.events) == 22
        assert worker.metrics['discovery_complete']['NFL'] is True
        assert not worker.discovery_progress
    asyncio.run(scenario())


def test_page_cap_and_controls_are_bounded():
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        assert worker.params(league='NFL')['limit'] == 2
        service.globally_stopped = True
        assert worker.controls()['stopped']
        service.globally_stopped = False
        service.paused_sources.add('sportsgameodds')
        assert worker.controls()['source_paused']
        await worker.cycle()
        assert worker.metrics['requests'] == 0
    asyncio.run(scenario())


def test_missing_reset_blocks_worker_without_event_dispatch(tmp_path):
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False,
                                  paused_sources=set(), database_mode=True)
        transport = SimpleNamespace(fetch=AsyncMock(), close=AsyncMock())
        async def usage(_):
            return {'tier':'amateur', 'limit':2500, 'used':11, 'requests_per_minute':10,
                    'reset_at':None, 'at':NOW}
        worker = SportsGameOddsWorker(service, key_loader=lambda:'fixture-secret', usage_reader=usage,
                                      transport=transport, ledger_path=tmp_path/'quota.sqlite', now=lambda:NOW)
        worker.state = AsyncMock()
        await worker.run()
        transport.fetch.assert_not_awaited()
        assert worker.metrics['limitation'] == 'The provider did not report an account reset time.'
        assert 'fixture-secret' not in str(worker.metrics)
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
        import pytest
        with pytest.raises(ValueError, match='moving or cyclic'):
            await worker.cycle()
        assert 'e1' in worker.events
        assert not worker.discovery_at
    asyncio.run(scenario())


def test_offer_and_reference_evidence_share_one_bounded_ingress():
    from unittest.mock import patch
    async def scenario():
        saved = []
        sink = SimpleNamespace(commit=lambda row, states: saved.append(row))
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False,
            paused_sources=set(), database_mode=False, states={}, sink=sink)
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        page = Page((event(1),), (), None, 'a'*64)
        record = {'event': {'competition':'NFL'}, 'quote': {'id':'offer'}}
        reference = {'id':'reference'}
        frames = [{'event_id':'e1'}]
        with patch('app.collection.sportsgameodds_worker.current_rows', return_value=([record], [])), \
             patch('app.storage.sportsgameodds_reference.prepare_page', return_value=[reference]), \
             patch('app.storage.sportsgameodds_reference.prepare_frames', return_value=frames):
            await worker._publish(page)
        assert len(saved) == 1
        assert saved[0]['source'] == 'sportsgameodds'
        assert saved[0]['records'] == [record]
        assert saved[0]['sgo_reference_rows'] == [reference]
        assert saved[0]['sgo_event_frames'] == frames
        assert saved[0]['complete_venues'] == []
    asyncio.run(scenario())


def test_local_rate_limit_backs_off_then_resumes_without_losing_cursor():
    from unittest.mock import patch
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False,
                                  paused_sources=set(), database_mode=True)
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda:NOW)
        worker.initialize = AsyncMock()
        worker.state = AsyncMock()
        marker = object()
        worker.discovery_progress['NFL'] = marker
        calls = []
        async def cycle():
            calls.append(1)
            assert worker.discovery_progress['NFL'] is marker
            if len(calls) == 1:
                raise RuntimeError('request rate limit')
            service.dispatch = False
        worker.cycle = cycle
        async def immediate_sleep(delay):
            assert delay in (60, 900)
        with patch('app.collection.sportsgameodds_worker.asyncio.sleep', side_effect=immediate_sleep):
            await worker.run()
        assert len(calls) == 2
        assert worker.discovery_progress['NFL'] is marker
        assert any(call.args[1] == 'sgo_request_rate' for call in worker.state.await_args_list)
    asyncio.run(scenario())
