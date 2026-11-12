import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.collection.current_policy import DEFAULT
from app.collection.sportsgameodds_adapter import Page
from app.collection.sportsgameodds_worker import SportsGameOddsWorker

NOW = datetime(2026, 11, 10, 20, tzinfo=timezone.utc)


def test_credential_requires_private_untracked_file(tmp_path, monkeypatch):
    from app.collection import sportsgameodds_worker as worker

    monkeypatch.delenv('SPORTSGAMEODDS_API_KEY', raising=False)
    monkeypatch.setattr(worker, 'ROOT', tmp_path)
    subprocess.run(['git', 'init', '--quiet', str(tmp_path)], check=True)
    (tmp_path / '.gitignore').write_text('.env\n')
    key_file = tmp_path / '.env'
    key_file.write_text('SPORTSGAMEODDS_API_KEY=fixture-only\n')
    key_file.chmod(0o644)
    with pytest.raises(ValueError, match='credential unavailable'):
        worker.credential()
    key_file.chmod(0o600)
    assert worker.credential() == 'fixture-only'
    subprocess.run(['git', 'add', '-f', '.env'], cwd=tmp_path, check=True)
    with pytest.raises(ValueError, match='credential unavailable'):
        worker.credential()


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
        worker.state = AsyncMock()
        await worker.cycle()
        assert cursors == list(range(10))
        assert worker.state.await_args_list[0].args[:2] == ('available', 'sgo_page_received')
        assert len(worker.events) == 20
        assert worker.metrics['discovery_complete']['NFL'] is False
        assert worker.next_cycle_delay() == 60
        await worker.cycle()
        assert cursors == list(range(11))
        assert len(worker.events) == 22
        assert worker.metrics['discovery_complete']['NFL'] is True
        assert not worker.discovery_progress
        assert worker.next_cycle_delay() == 15 * 60
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


def test_worker_wakes_when_game_enters_approaching_window():
    from app.collection.sportsgameodds_schedule import SchedulePolicy
    service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
    worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
    worker.schedule_policy = SchedulePolicy(imminent=timedelta(hours=2))
    upcoming = event(1)
    upcoming['starts_at'] = (NOW + timedelta(hours=2, minutes=5)).isoformat()
    worker.events['e1'] = upcoming
    assert worker.next_cycle_delay() == 5 * 60


def test_active_and_kickoff_refresh_interleave_with_discovery_and_retain_cursor_filter():
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        now = NOW
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: now)
        kickoff = NOW + timedelta(seconds=2)
        upcoming = dict(event(1), starts_at=kickoff.isoformat())
        active = dict(event(3), phase='live', starts_at=(NOW - timedelta(hours=1)).isoformat(),
                      received_at=(kickoff - timedelta(minutes=15)).isoformat())
        worker.events['e3'] = active
        requests = []

        async def fetch(params, key):
            nonlocal now
            requests.append(params)
            if 'eventIDs' in params:
                return Page(tuple(dict(e, phase='live', received_at=now.isoformat())
                                  for e in (active, upcoming)), (), None, 'b'*64)
            if 'cursor' in params:
                return Page((event(2),), (), None, 'c'*64)
            now += timedelta(seconds=3)
            return Page((upcoming,), (), 'next', 'a'*64)

        worker.collector = SimpleNamespace(fetch=fetch)
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        await worker.cycle()
        first, refresh, last = requests
        assert refresh['eventIDs'] == 'e3,e1'
        assert first['startsAfter'] == last['startsAfter']
        assert last['cursor'] == 'next'
        assert worker.events['e1']['phase'] == 'live'
        poll = {'events': 1, 'between_discovery_pages': 1, 'max_schedule_delay_seconds': 1}
        assert worker.metrics['completed_refresh_polls'] == {'active': poll, 'kickoff': poll}

    asyncio.run(scenario())


def test_started_event_uses_active_polling_without_relabeling_phase():
    from app.collection.sportsgameodds_schedule import SchedulePolicy
    service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
    worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
    worker.schedule_policy = SchedulePolicy()
    started = event(1)
    started.update(phase='started', starts_at=(NOW - timedelta(hours=1)).isoformat(),
                   received_at=(NOW - timedelta(minutes=14)).isoformat())
    worker.events['e1'] = started
    assert worker.next_cycle_delay() == 60
    assert worker.events['e1']['phase'] == 'started'

    async def check_due():
        started['received_at'] = (NOW - timedelta(minutes=16)).isoformat()
        worker.discovery_at.update({league: NOW for league in ('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL')})
        worker._fetch = AsyncMock()
        await worker.cycle()
        assert worker._fetch.await_args.args[0]['eventIDs'] == 'e1'
        assert worker.events['e1']['phase'] == 'started'
    asyncio.run(check_due())


def test_rejected_cursor_clears_checkpoint_but_preserves_observations(tmp_path):
    import pytest
    from app.collection.sportsgameodds_collector import RejectedCursor
    from app.collection.sportsgameodds_ledger import ObjectLedger
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        worker.ledger = ObjectLedger(tmp_path / 'checkpoint.sqlite')
        async def fetch(params, key):
            if 'cursor' in params:
                raise RejectedCursor('provider rejected cursor; charge remains held')
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


def test_missing_id_is_retried_later_without_changing_source_receipt():
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        old = event(1)
        old['received_at'] = (NOW - timedelta(days=1)).isoformat()
        original_receipt = old['received_at']
        worker.events['e1'] = old
        worker.collector = SimpleNamespace(fetch=AsyncMock(return_value=Page((), (), None, 'a'*64)))
        worker._publish = AsyncMock()
        worker.key = 'fixture'
        await worker._fetch(worker.params(event_ids=['e1']))
        assert worker.events['e1']['received_at'] == original_receipt
        assert worker.events['e1']['last_polled_at'] == NOW.isoformat()
        assert 'e1' in worker.events
        worker.discovery_at['NFL'] = NOW
        worker.collector.fetch.reset_mock()
        await worker.cycle()
        worker.collector.fetch.assert_not_awaited()
    asyncio.run(scenario())


def test_provider_alias_replaces_only_the_old_poll_schedule():
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        old = event(1)
        replacement = event(2)
        replacement['aliases'] = ['e1']
        worker.events['e1'] = old
        worker.collector = SimpleNamespace(fetch=AsyncMock(return_value=Page((replacement,), (), None, 'a'*64)))
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        await worker._fetch(worker.params(event_ids=['e1']))
        assert set(worker.events) == {'e2'}
        worker._publish.assert_awaited_once()
    asyncio.run(scenario())


def test_failed_admission_preserves_schedule_and_retries_old_event():
    import pytest
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        old = event(1)
        replacement = event(2)
        replacement['aliases'] = ['e1']
        worker.events['e1'] = deepcopy(old)
        worker.collector = SimpleNamespace(fetch=AsyncMock(return_value=Page((replacement,), (), None, 'a'*64)))
        worker._publish = AsyncMock(side_effect=RuntimeError('ingress failed'))
        worker.state = AsyncMock()
        with pytest.raises(RuntimeError, match='ingress failed'):
            await worker._fetch(worker.params(event_ids=['e1']))
        assert worker.events == {'e1': old}
        worker.state.assert_not_awaited()
    asyncio.run(scenario())


def test_alias_does_not_remove_a_separately_returned_event():
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        old, replacement = event(1), event(2)
        replacement['aliases'] = ['e1']
        worker.collector = SimpleNamespace(fetch=AsyncMock(return_value=Page((old, replacement), (), None, 'a'*64)))
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        await worker._fetch(worker.params(event_ids=['e1', 'e2']))
        assert set(worker.events) == {'e1', 'e2'}
    asyncio.run(scenario())


def test_missing_reset_uses_labeled_calendar_assumption(tmp_path):
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
        await worker.initialize()
        transport.fetch.assert_not_awaited()
        assert worker.metrics['reset_basis'] == 'assumed_calendar_month'
        assert worker.metrics['provider_usage']['used'] == 11
        assert worker.metrics['provider_usage']['reset_at'] is None
        assert worker.ledger.status(worker.window_id)['reset_at'] == datetime(2026, 12, 1, tzinfo=timezone.utc)
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


def test_initial_usage_rate_limit_waits_and_retries():
    from unittest.mock import patch
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False,
                                  paused_sources=set(), database_mode=True)
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        worker.initialize = AsyncMock(side_effect=[RuntimeError('request rate limit'), None])
        worker.state = AsyncMock()
        async def cycle():
            service.dispatch = False
        worker.cycle = cycle
        with patch('app.collection.sportsgameodds_worker.asyncio.sleep', new=AsyncMock()) as sleep, \
             patch('app.collection.sportsgameodds_worker.retained_schedule', return_value=({}, False)):
            await worker.run()
        assert worker.initialize.await_count == 2
        assert sleep.await_args_list[0].args == (60,)
        assert any(call.args[1] == 'sgo_request_rate' for call in worker.state.await_args_list)
    asyncio.run(scenario())


def test_worker_waits_for_evidenced_charge_resolution_without_restart(tmp_path):
    from unittest.mock import patch
    from app.collection.sportsgameodds_ledger import ObjectLedger
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False,
                                  paused_sources=set(), database_mode=True)
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        ledger = ObjectLedger(tmp_path/'quota.sqlite')
        ledger.create_window('w', limit=100, initial_used=0, reserve=10,
                             reset_at=NOW + timedelta(days=1), requests_per_minute=10)
        ledger.reserve('w', 'failed', objects=2, now=NOW)
        worker.ledger, worker.window_id = ledger, 'w'
        worker.initialize, worker.state = AsyncMock(), AsyncMock()
        calls = []
        async def cycle():
            calls.append(ledger.status('w')['held'])
            if calls[-1]:
                raise RuntimeError('unresolved provider object reservation')
            service.dispatch = False
        worker.cycle = cycle
        sleeps = 0
        async def sleep(_):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 2:
                ledger.resolve('failed', charged=1, evidence='fixture request-specific receipt', now=NOW)
        with patch('app.collection.sportsgameodds_worker.asyncio.sleep', side_effect=sleep), \
             patch('app.collection.sportsgameodds_worker.retained_schedule', return_value=({}, False)):
            await worker.run()
        assert calls == [2, 2, 0]
        assert ledger.status('w')['charged'] == 1
        assert any(call.args[1] == 'sgo_charge_unresolved' for call in worker.state.await_args_list)
    asyncio.run(scenario())


def test_hourly_spend_retains_its_sample_time_until_next_cycle(tmp_path):
    from app.collection.sportsgameodds_ledger import ObjectLedger

    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False,
                                  paused_sources=set())
        now = NOW
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: now)
        ledger = ObjectLedger(tmp_path/'quota.sqlite')
        ledger.create_window('w', limit=1000, initial_used=0, reserve=100,
                             reset_at=NOW + timedelta(days=1), requests_per_minute=10)
        for minute, category in ((40, 'event_refresh'), (20, 'discovery')):
            at = NOW - timedelta(minutes=minute)
            ledger.reserve('w', category, objects=1, now=at, category=category)
            ledger.resolve(category, charged=1, evidence='fixture request-specific receipt', now=at)
        worker.ledger, worker.window_id = ledger, 'w'
        worker.discovery_at.update({league: NOW for league in ('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL')})
        worker._fetch = AsyncMock()

        await worker.cycle()
        assert worker.metrics['resolved_objects_hour_ended_at'] == NOW.isoformat()
        assert [(row['category'], row['objects']) for row in worker.metrics['resolved_objects_last_hour']] == [
            ('discovery', 1), ('event_refresh', 1)]

        now += timedelta(minutes=30)
        assert worker.metrics['resolved_objects_hour_ended_at'] == NOW.isoformat()
        await worker.cycle()
        assert worker.metrics['resolved_objects_hour_ended_at'] == now.isoformat()
        assert [(row['category'], row['objects']) for row in worker.metrics['resolved_objects_last_hour']] == [
            ('discovery', 1)]
        worker._fetch.assert_not_awaited()

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
        with patch('app.collection.sportsgameodds_worker.asyncio.sleep', side_effect=immediate_sleep), \
                patch('app.collection.sportsgameodds_worker.retained_schedule', return_value=({}, False)):
            await worker.run()
        assert len(calls) == 2
        assert worker.discovery_progress['NFL'] is marker
        assert any(call.args[1] == 'sgo_request_rate' for call in worker.state.await_args_list)
    asyncio.run(scenario())


def test_balance_mismatch_waits_for_a_new_usage_read_without_abandoning_work():
    from unittest.mock import patch

    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False,
                                  paused_sources=set(), database_mode=True)
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        worker.initialize = AsyncMock()
        worker.state = AsyncMock()
        cursor = object()
        worker.discovery_progress['NFL'] = cursor

        async def recover(delay):
            assert delay == 60 and worker.discovery_progress['NFL'] is cursor

        async def cycle():
            assert worker.discovery_progress['NFL'] is cursor
            if worker.cycle.await_count == 1:
                raise RuntimeError('current account usage evidence unavailable or changed')
            service.dispatch = False

        worker.cycle = AsyncMock(side_effect=cycle)
        with patch('app.collection.sportsgameodds_worker.asyncio.sleep', side_effect=recover), \
             patch('app.collection.sportsgameodds_worker.retained_schedule', return_value=({}, False)):
            await worker.run()
        assert worker.cycle.await_count == 2
        assert any(call.args[1] == 'sgo_usage_unreconciled' for call in worker.state.await_args_list)

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
        assert traversal.starts_after == (NOW - timedelta(hours=12)).isoformat()
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
    params = dict(worker.params(league='NFL'), startsAfter=(NOW-timedelta(hours=12)).isoformat())
    ledger.save_discovery_progress('NFL', {'params': params, 'next_cursor': 'next', 'pages': 1,
                                   'seen_cursors': [], 'seen_events': ['e1']}, now=NOW)
    later = SportsGameOddsWorker(service, now=lambda: NOW + timedelta(days=2))
    later.ledger = ledger
    later.restore_discovery()
    assert not later.discovery_progress
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
        second = SportsGameOddsWorker(service, now=lambda: NOW + timedelta(minutes=2))
        second.ledger = ObjectLedger(tmp_path / 'ledger.sqlite')
        second.restore_discovery()
        second._publish = AsyncMock()
        second.state = AsyncMock()
        second.collector = SimpleNamespace(fetch=AsyncMock(return_value=Page((event(2),), (), None, 'b'*64)))
        await second.cycle()
        params = second.collector.fetch.await_args_list[0].args[0]
        assert params['cursor'] == 'next'
        assert params['startsAfter'] == (NOW - timedelta(hours=12)).isoformat()
        assert second.metrics['discovery_complete']['NFL'] is True
        assert 'NFL' in ledger.discovery_schedule(now=NOW + timedelta(minutes=2))
        assert 'NFL' not in ledger.load_discovery_progress(now=NOW + timedelta(minutes=2))
    asyncio.run(scenario())
