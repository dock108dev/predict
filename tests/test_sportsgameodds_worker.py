import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.collection.current_policy import DEFAULT
from app.collection.sportsgameodds_adapter import Page
from app.collection.sportsgameodds_schedule import SchedulePolicy
from app.collection.sportsgameodds_worker import SportsGameOddsWorker
from tests.sportsgameodds_fixtures import NOW, event


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


def test_planned_storage_interval_waits_for_paid_page_and_blocks_next_dispatch():
    from app.collection.data_runtime import DataRuntime

    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        service.workers = {'sportsgameodds': worker}
        runtime = DataRuntime(service=service)
        fetching, finish_fetch = asyncio.Event(), asyncio.Event()
        admitting, finish_admission = asyncio.Event(), asyncio.Event()
        page = Page((event(1),), (), 'next-cursor', 'a'*64)

        async def fetch(params, key):
            fetching.set()
            await finish_fetch.wait()
            assert worker.controls() == {'stopped': False, 'source_paused': False}
            return page

        async def publish(admitted_page):
            assert admitted_page is page
            admitting.set()
            await finish_admission.wait()
            assert worker.controls() == {'stopped': False, 'source_paused': False}

        worker.collector = SimpleNamespace(fetch=AsyncMock(side_effect=fetch))
        worker._publish = publish
        worker.state = AsyncMock()
        cycle = asyncio.create_task(worker.cycle())
        await asyncio.wait_for(fetching.wait(), 1)
        assert not runtime.storage_interval_ready()
        finish_fetch.set()
        await asyncio.wait_for(admitting.wait(), 1)
        assert not runtime.storage_interval_ready()
        finish_admission.set()
        await asyncio.wait_for(cycle, 1)
        assert runtime.storage_interval_ready()
        assert worker.events == {'e1': event(1)}
        assert worker.discovery_progress['NFL'].next_cursor == 'next-cursor'
        assert worker.controls() == {'stopped': True, 'source_paused': False}
        assert service.dispatch and not service.globally_stopped and not service.paused_sources
        worker.collector.fetch.assert_awaited_once()

    asyncio.run(scenario())


def test_worker_replans_every_minute_overnight_and_keeps_discovery_cursor():
    from unittest.mock import patch

    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False,
                                  paused_sources=set(), database_mode=True)
        now = datetime(2026, 11, 11, 4, 55, tzinfo=timezone.utc)
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: now)
        worker.initialize, worker.state = AsyncMock(), AsyncMock()
        worker.discovery_progress['NFL'] = object()
        start_times = []

        async def cycle():
            nonlocal now
            start_times.append(now)
            now += timedelta(seconds=20)
            if len(start_times) == 3:
                service.dispatch = False

        async def sleep(delay):
            nonlocal now
            assert delay == 40
            now += timedelta(seconds=delay)

        worker.cycle = cycle
        with patch('app.collection.sportsgameodds_worker.asyncio.sleep', side_effect=sleep), \
             patch('app.collection.sportsgameodds_worker.retained_schedule', return_value=({}, False)):
            await worker.run()
        assert start_times == [start_times[0] + timedelta(minutes=index) for index in range(3)]
        assert worker.discovery_progress

    asyncio.run(scenario())


def test_active_and_kickoff_refresh_interleave_with_discovery_and_retain_cursor_filter():
    async def scenario():
        service = SimpleNamespace(config=dict(DEFAULT, live_enabled=True), dispatch=True, globally_stopped=False, paused_sources=set())
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
                observed = active if params['eventIDs'] == 'e3' else upcoming
                return Page((dict(observed, phase='live', received_at=now.isoformat()),), (), None, 'b'*64)
            if 'cursor' in params:
                return Page((event(2),), (), None, 'c'*64)
            now += timedelta(seconds=3)
            return Page((upcoming,), (), 'next', 'a'*64)

        worker.collector = SimpleNamespace(fetch=fetch)
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        await worker.cycle()
        first, active_refresh, kickoff_refresh, last = requests
        assert [r['eventIDs'] for r in (active_refresh,kickoff_refresh)] == ['e3','e1']
        assert all(r['includeAltLines'] and r['limit'] == 1 for r in (active_refresh,kickoff_refresh))
        assert 'includeAltLines' not in first and 'bookmakerID' not in first
        assert 'includeAltLines' not in last and 'bookmakerID' not in last
        assert first['startsAfter'] == last['startsAfter']
        assert last['cursor'] == 'next'
        assert worker.events['e1']['phase'] == 'live'
        poll = {'events': 1, 'between_discovery_pages': 1, 'max_schedule_delay_seconds': 1}
        assert worker.metrics['completed_refresh_polls'] == {'active': poll, 'kickoff': poll}

    asyncio.run(scenario())


def test_pregame_default_skips_kickoff_and_in_play_refreshes_and_preserves_pregame_receipts():
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        now = NOW
        kickoff = NOW + timedelta(seconds=1)
        worker = SportsGameOddsWorker(service, now=lambda: now)
        pregame = dict(event(1), starts_at=kickoff.isoformat())
        live = dict(event(3), phase='live', starts_at=(NOW-timedelta(hours=1)).isoformat())
        worker.events['e3'] = live
        requests = []

        async def fetch(params, key):
            nonlocal now
            requests.append(params)
            if 'cursor' in params:
                return Page((event(2),), ({'event_id':'e2'},), None, 'b'*64)
            now = kickoff
            return Page((pregame, live), ({'event_id':'e1'}, {'event_id':'e3'}), 'next', 'a'*64)

        worker.collector = SimpleNamespace(fetch=fetch)
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        await worker.cycle()

        first, second = requests
        assert first['started'] is second['started'] is False
        assert first['live'] is second['live'] is False
        assert first['startsAfter'] == second['startsAfter'] == NOW.isoformat()
        assert [call.args[0].quotes for call in worker._publish.await_args_list] == [
            ({'event_id':'e1'},), ({'event_id':'e2'},)]
        assert set(worker.events) == {'e2'}

    asyncio.run(scenario())


def test_pregame_alternate_retry_does_not_dispatch_when_clock_reaches_kickoff():
    from app.collection.sportsgameodds_collector import InvalidProviderPage

    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        now = NOW
        kickoff = NOW + timedelta(seconds=1)
        worker = SportsGameOddsWorker(service, now=lambda: now)
        worker.events['e1'] = dict(event(1), starts_at=kickoff.isoformat(),
                                   received_at=(NOW-timedelta(hours=1)).isoformat())
        worker.discovery_at['NFL'] = NOW

        async def fetch(params, key):
            nonlocal now
            assert params['includeAltLines']
            now = kickoff
            raise InvalidProviderPage('fixture crosses kickoff')

        worker.collector = SimpleNamespace(fetch=AsyncMock(side_effect=fetch))
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        await worker.cycle()
        worker.collector.fetch.assert_awaited_once()
        worker._publish.assert_not_awaited()

    asyncio.run(scenario())


def test_started_event_uses_active_polling_without_relabeling_phase():
    service = SimpleNamespace(config=dict(DEFAULT, live_enabled=True), dispatch=True, globally_stopped=False, paused_sources=set())
    worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
    started = event(1)
    started.update(phase='started', starts_at=(NOW - timedelta(hours=1)).isoformat(),
                   received_at=(NOW - timedelta(minutes=14)).isoformat())
    worker.events['e1'] = started
    assert worker.events['e1']['phase'] == 'started'

    async def check_due():
        started['received_at'] = (NOW - timedelta(minutes=16)).isoformat()
        worker.discovery_at.update({league: NOW for league in ('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL')})
        worker._fetch = AsyncMock()
        await worker.cycle()
        assert worker._fetch.await_args.args[0]['eventIDs'] == 'e1'
        assert worker.metrics['completed_refresh_polls']['started']['events'] == 1
        assert worker.events['e1']['phase'] == 'started'

        worker._fetch.reset_mock()
        worker.events['e2'] = dict(event(2), phase='live', starts_at=(NOW - timedelta(minutes=20)).isoformat(),
                                   received_at=(NOW - timedelta(minutes=15)).isoformat())
        await worker.cycle()
        assert [call.args[0]['eventIDs'] for call in worker._fetch.await_args_list] == ['e2','e1']
    asyncio.run(check_due())


def test_every_game_deadline_and_faster_band_wake_without_extra_discovery():
    service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True,
                              globally_stopped=False, paused_sources=set())
    worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
    policy = SchedulePolicy(approaching=timedelta(minutes=3), imminent=timedelta(minutes=6))
    worker.events['e1'] = dict(event(1), starts_at=(NOW+timedelta(hours=4)).isoformat(),
                              received_at=(NOW-timedelta(minutes=5,seconds=50)).isoformat())
    assert worker.next_pregame_refresh(NOW,policy,NOW+timedelta(minutes=1)) == NOW+timedelta(seconds=10)
    worker.events['e1'].update(starts_at=(NOW+timedelta(hours=2,seconds=5)).isoformat(),
                               received_at=NOW.isoformat())
    assert worker.next_pregame_refresh(NOW,policy,NOW+timedelta(minutes=1)) == NOW+timedelta(seconds=5)


def test_replanning_fresh_games_does_not_spend_or_repeat_a_discovery_walk():
    async def scenario():
        moment = NOW
        service = SimpleNamespace(config=deepcopy(DEFAULT),dispatch=True,
                                  globally_stopped=False,paused_sources=set())
        worker = SportsGameOddsWorker(service,transport=SimpleNamespace(close=AsyncMock()),now=lambda: moment)
        worker.events['e1'] = dict(event(1),starts_at=(NOW+timedelta(hours=4)).isoformat(),received_at=NOW.isoformat())
        worker.discovery_at['NFL'] = NOW
        worker._fetch = AsyncMock()
        for _ in range(3):
            await worker.cycle()
            moment += timedelta(minutes=1)
        worker._fetch.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize('base_readable', [True, False])
def test_unreadable_alternates_try_main_lines_and_keep_scanning(base_readable):
    from app.collection.sportsgameodds_collector import InvalidProviderPage

    async def scenario():
        service = SimpleNamespace(config=dict(DEFAULT, live_enabled=True), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        original_receipt = (NOW - timedelta(minutes=16)).isoformat()
        worker.events = {
            f'e{i}': dict(event(i), starts_at=(NOW - timedelta(hours=1)).isoformat(),
                          received_at=original_receipt, phase='live')
            for i in (1, 2)
        }
        worker.discovery_at['NFL'] = NOW
        calls = []

        async def fetch(params, key):
            identifier = params['eventIDs']
            alternates = params.get('includeAltLines', False)
            calls.append((identifier, alternates))
            if identifier == 'e1' and (alternates or not base_readable):
                raise InvalidProviderPage('fixture unreadable page')
            return Page((dict(worker.events[identifier], received_at=NOW.isoformat()),), (), None, 'a'*64)

        worker.collector = SimpleNamespace(fetch=fetch)
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        await worker.cycle()

        assert calls == [('e1', True), ('e1', False), ('e2', True)]
        assert worker.events['e2']['received_at'] == NOW.isoformat()
        assert worker.metrics['alternate_parse_fallbacks'] == 1
        if base_readable:
            assert worker.events['e1']['received_at'] == NOW.isoformat()
        else:
            assert worker.events['e1']['received_at'] == original_receipt
            assert worker.events['e1']['last_polled_at'] == NOW.isoformat()
            assert worker.metrics['unreadable_refresh_events'] == 1

    asyncio.run(scenario())


def test_alternates_use_bounded_approaching_event_refresh_and_track_admission():
    from app.collection.sportsgameodds_schedule import EventDue, SchedulePolicy

    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        active = dict(event(1), starts_at=(NOW+timedelta(hours=2)).isoformat())
        response = Page((active,), ({'alternate':True},{}), None, 'b'*64, 500,
                        alternate_rows=3, duplicate_alternate_rows=1, conflicting_alternate_lines=1,
                        ignored_bookmaker_groups=4)
        worker.collector = SimpleNamespace(fetch=AsyncMock(side_effect=[response,Page((),(),None)]))
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        due = [EventDue('e1',NOW+timedelta(hours=2)), EventDue('e2',NOW+timedelta(hours=2,seconds=1)),
               EventDue('e3',NOW+timedelta(hours=12))]
        worker.events = {item.event_id: dict(event(index), starts_at=item.starts_at.isoformat())
                         for index, item in enumerate(due, 1)}
        await worker.refresh(due,SchedulePolicy())
        first, other = [c.args[0] for c in worker.collector.fetch.await_args_list]
        assert first['eventIDs'] == 'e1' and first['limit'] == 1 and first['includeAltLines'] is True
        assert set(first['bookmakerID'].split(',')) == {'kalshi','polymarket','novig','prophetexchange','fanduel','draftkings','betmgm','caesars'}
        assert other['eventIDs'] == 'e2,e3' and other['limit'] == 2
        assert not {'bookmakerID','includeAltLines'} & other.keys()
        metrics = worker.metrics['alternate_refresh']
        assert (metrics['resolved_requests'],metrics['returned_events'],metrics['received_alternate_rows'],
                metrics['admitted_alternate_rows'],metrics['ignored_bookmaker_groups']) == (1,1,3,1,4)
        assert metrics['largest_page_bytes'] == 500 and metrics['conflicting_alternate_lines'] == 1

    asyncio.run(scenario())


def test_page_cap_and_controls_are_bounded():
    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        assert worker.params(league='NFL', starts_after=NOW.isoformat())['limit'] == 2
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
        worker.events = {'e1': old, 'e2': replacement}
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
            assert delay == 60
        with patch('app.collection.sportsgameodds_worker.asyncio.sleep', side_effect=immediate_sleep), \
                patch('app.collection.sportsgameodds_worker.retained_schedule', return_value=({}, False)):
            await worker.run()
        assert len(calls) == 2
        assert worker.discovery_progress['NFL'] is marker
        assert any(call.args[1] == 'sgo_request_rate' for call in worker.state.await_args_list)
    asyncio.run(scenario())


@pytest.mark.parametrize(('headroom_seconds', 'expected_delay'), [(92, 92), (1200, 1200)])
def test_daily_pacing_waits_for_both_scan_and_headroom(headroom_seconds, expected_delay):
    from unittest.mock import patch

    from app.collection.sportsgameodds_collector import DailyObjectPacing

    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False,
                                  paused_sources=set(), database_mode=True)
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: NOW)
        worker.initialize = AsyncMock()
        worker.state = AsyncMock()
        cursor = object()
        worker.discovery_progress['NFL'] = cursor
        retry_at = NOW+timedelta(seconds=headroom_seconds)

        async def cycle():
            assert worker.discovery_progress['NFL'] is cursor
            if worker.cycle.await_count == 1:
                raise DailyObjectPacing(retry_at=retry_at, requested=2, rolling=4, allowance=5)
            service.dispatch = False

        worker.cycle = AsyncMock(side_effect=cycle)
        with patch('app.collection.sportsgameodds_worker.asyncio.sleep', new=AsyncMock()) as wait, \
             patch('app.collection.sportsgameodds_worker.retained_schedule', return_value=({}, False)):
            await worker.run()
        assert worker.cycle.await_count == 2
        assert wait.await_args_list[0].args == (expected_delay,)
        assert any(call.args[1] == 'sgo_daily_pacing' for call in worker.state.await_args_list)
        assert 'daily_pacing' not in worker.metrics

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


@pytest.mark.parametrize('scan_delay', [0, 2])
def test_pregame_refresh_between_scans_does_not_restart_discovery(scan_delay):
    from unittest.mock import patch

    async def scenario():
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False,
                                  paused_sources=set(), database_mode=True)
        moment = NOW
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(close=AsyncMock()), now=lambda: moment)
        worker.initialize = AsyncMock()
        worker.state = AsyncMock()
        policy = SchedulePolicy(approaching=timedelta(minutes=15))
        delays = []

        async def cycle():
            nonlocal moment
            if not worker.events:
                # The first receipt lands just after its sweep began. The same
                # instant in the next sweep is too early for this exact quote.
                moment += timedelta(seconds=1)
                worker.events['e1'] = dict(event(1), starts_at=(NOW + timedelta(hours=1)).isoformat(),
                                           received_at=moment.isoformat())
            else:
                # The last discovery page can finish after the event is due.
                moment += timedelta(seconds=scan_delay)
            return policy

        async def sleep(delay):
            nonlocal moment
            delays.append(delay)
            moment += timedelta(seconds=delay)

        async def refresh(due, selected):
            assert [entry.event_id for entry in due] == ['e1']
            assert selected is policy
            assert moment == NOW + timedelta(minutes=15, seconds=max(1, scan_delay))
            service.dispatch = False

        worker.cycle = AsyncMock(side_effect=cycle)
        worker.refresh = AsyncMock(side_effect=refresh)
        with patch('app.collection.sportsgameodds_worker.SCAN_INTERVAL',timedelta(minutes=15)), \
             patch('app.collection.sportsgameodds_worker.asyncio.sleep', side_effect=sleep), \
             patch('app.collection.sportsgameodds_worker.retained_schedule', return_value=({}, False)):
            await worker.run()
        assert delays[:2] == [899, max(0, 1 - scan_delay)]
        assert worker.cycle.await_count == 2
        worker.refresh.assert_awaited_once()

    asyncio.run(scenario())
