"""Guarded checkpoint dispatch, full scope and causal timing without a provider."""
import asyncio
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.collection import experiment_acquisition as acquisition
from app.collection.activity_collector import ActivityBudgetDelayed, ActivityCollector
from app.collection.sportsgameodds_ledger import ObjectLedger
from app.collection.sportsgameodds_transport import PageResponse


def setup(tmp_path, *, latency=2, started=False, source_flags=None):
    at = datetime.now(timezone.utc)
    clock = [at]
    event = dict(event_id='event', league='NBA', starts_at=(at+timedelta(minutes=10)).isoformat())
    source_status=dict(live=False, started=started, startsAt=event['starts_at'])
    source_status.update(source_flags or {})
    body = json.dumps(dict(success=True, data=[dict(eventID='event', leagueID='NBA',
        status=source_status,
        teams=dict(home=dict(teamID='home', names=dict(long='Home')),
                   away=dict(teamID='away', names=dict(long='Away'))), odds={})])).encode()
    ledger = ObjectLedger(tmp_path/'ledger.sqlite3')
    reset = at+timedelta(days=10)
    ledger.create_window('account:window', limit=100000, initial_used=0, reserve=10000,
                         reset_at=reset, requests_per_minute=50)
    dispatched = []

    async def fetch(params, key):
        dispatched.append(dict(params))
        clock[0] += timedelta(seconds=latency)
        return PageResponse(200, body, clock[0].isoformat(), None)

    async def usage():
        return dict(used=ledger.status('account:window')['charged'], limit=100000,
                    reset_at=reset, requests_per_minute=50, at=datetime.now(timezone.utc))

    control = dict(stopped=False, source_paused=False)
    worker = SimpleNamespace(
        service=SimpleNamespace(config=dict(enabled=True, aggregate_enabled=True,
            aggregate_provider='sportsgameodds', sports=['NBA'])),
        controls=lambda:dict(control), ledger=ledger, window_id='account:window',
        collector=SimpleNamespace(account_usage=usage), transport=SimpleNamespace(fetch=fetch),
        request_lock=asyncio.Lock(), key='fixture-key', now=lambda:clock[0],
        metrics={}, original_response_root=tmp_path/'originals', experiment_late_waiting=False,
        experiment_reserved_objects=0, experiment_reserved_requests=0)
    task = dict(game_id='game', checkpoint='late', token='claim',
                event=dict(source_event_id='event', league='NBA', starts_at=event['starts_at'],
                           phase='pregame', status=dict(started=False, live=False)),
                target_at=(at-timedelta(seconds=1)).isoformat(),
                deadline_at=(at+timedelta(seconds=60)).isoformat())
    return worker, task, control, dispatched


def storage_patches():
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch.object(acquisition, 'connect', side_effect=lambda:nullcontext(None)))
    stack.enter_context(patch('app.collection.current_storage_policy.sql_usage', return_value=0))
    stack.enter_context(patch('app.collection.current_storage_policy.require_disk_space'))
    return stack


def test_full_declared_book_surface_and_postgame_request_scope(tmp_path):
    _, task, _, _ = setup(tmp_path)
    params = acquisition.request_scope(task)
    assert params['limit'] == 1 and params['eventIDs'] == 'event'
    assert params['includeAltLines'] is True and params['includeOpposingOdds'] is True
    assert set(params['bookmakerID'].split(',')) == {
        'kalshi','polymarket','novig','prophetexchange','fanduel','draftkings','betmgm','caesars','betonline'}
    assert set(params['oddID'].split(',')) == set(acquisition.ODD_IDS)
    assert 'includeAltLines' not in acquisition.request_scope(dict(task, checkpoint='outcome'))


def test_game_declared_scope_overrides_current_books_without_widening_old_tasks(tmp_path):
    from app.comparison.reference_scope import REQUEST_BOOKS, REFERENCE_BOOKS
    from app.comparison.sgo_reference import BEST_BOOKS
    _, task, _, _ = setup(tmp_path)
    old = acquisition.request_scope(task)
    new = acquisition.request_scope(dict(task, requested_scope=dict(bookmakers=list(REQUEST_BOOKS),
        odd_ids=list(acquisition.ODD_IDS), includeAltLines=True)))
    assert old['bookmakerID'].split(',') == list(acquisition.LEGACY_BOOKS)
    assert new['bookmakerID'].split(',') == list(REQUEST_BOOKS)
    assert len(REFERENCE_BOOKS) == 10 and len(REQUEST_BOOKS) == 14
    assert set(REFERENCE_BOOKS).isdisjoint({'kalshi','polymarket','novig','prophetexchange','matchbook','betfairexchange','sporttrade'})
    assert BEST_BOOKS == ('fanduel','draftkings','betmgm','caesars')


def test_control_scope_and_checkpoint_window_are_rechecked(tmp_path):
    worker, task, controls, _ = setup(tmp_path)
    assert acquisition.authorized(worker, task, at=worker.now())
    assert not acquisition.authorized(worker, task, at=worker.now()-timedelta(seconds=2))
    assert not acquisition.authorized(worker, task, at=worker.now()+timedelta(seconds=61))
    controls['source_paused'] = True
    assert not acquisition.authorized(worker, task, at=worker.now())
    controls['source_paused'] = False
    controls['stopped'] = True
    assert not acquisition.authorized(worker, task, at=worker.now())
    controls['stopped'] = False
    task['event']['league'] = 'NFL'
    assert not acquisition.authorized(worker, task, at=worker.now())


def test_guarded_page_keeps_paid_receipt_and_dispatch_clocks(tmp_path):
    async def scenario():
        worker, task, _, dispatched = setup(tmp_path)
        with storage_patches():
            result = await acquisition.acquire(worker, task)
        assert len(dispatched) == 1
        assert result['request_scope'] == dispatched[0]
        assert result['dispatch_at'] < result['received_at'] == result['known_at']
        assert result['acquisition']['charged_objects'] == 1
        assert result['acquisition']['original_response']['state'] == 'retained'
        state = worker.ledger.status(worker.window_id)
        assert (state['charged'],state['held'],state['interrupted']) == (1,0,0)
        assert not worker.experiment_late_waiting
    asyncio.run(scenario())


def test_delayed_receipt_is_paid_but_never_backdated_into_checkpoint(tmp_path):
    async def scenario():
        worker, task, _, dispatched = setup(tmp_path, latency=61)
        with storage_patches(), pytest.raises(acquisition.CheckpointUnavailable, match='response_after_deadline') as failure:
            await acquisition.acquire(worker, task)
        assert len(dispatched) == 1 and failure.value.dispatched
        assert failure.value.details['received_at'] > task['deadline_at']
        assert worker.ledger.status(worker.window_id)['charged'] == 1
        assert worker.ledger.status(worker.window_id)['held'] == 0
        assert not worker.experiment_late_waiting
    asyncio.run(scenario())


@pytest.mark.parametrize('revoke_at', [3,4])
def test_authority_revoked_after_usage_or_reservation_never_dispatches(tmp_path, revoke_at):
    async def scenario():
        worker, task, _, dispatched = setup(tmp_path)
        checks = 0
        def eligible(_task, at):
            nonlocal checks
            checks += 1
            return checks < revoke_at
        with storage_patches(), pytest.raises(acquisition.CheckpointUnavailable):
            await acquisition.acquire(worker, task, eligible=eligible)
        assert not dispatched
        state=worker.ledger.status(worker.window_id)
        assert (state['charged'],state['held'],state['interrupted']) == (0,0,0)
    asyncio.run(scenario())


def test_ordinary_mode_keeps_late_object_and_rate_headroom(tmp_path):
    async def scenario():
        worker, task, _, _ = setup(tmp_path)
        worker._fetch = AsyncMock()
        worker.experiment_reserved_requests = 3
        for _ in range(47):
            worker.ledger.reserve_request('account', requests_per_minute=50, now=worker.now())
        before = worker.ledger.status(worker.window_id)
        capacity = worker.ledger.request_capacity(worker.window_id, now=worker.now())
        assert capacity['available'] == 3
        collector = ActivityCollector(worker, store=SimpleNamespace())
        with pytest.raises(ActivityBudgetDelayed, match='checkpoint_rate_headroom'):
            await collector.dispatch(dict(run={}), acquisition.request_scope(task), {})
        worker._fetch.assert_not_awaited()
        assert before == worker.ledger.status(worker.window_id)
    asyncio.run(scenario())


@pytest.mark.parametrize('checkpoint', ['early','outcome'])
def test_early_and_postgame_cannot_spend_the_last_reserved_late_object(tmp_path, checkpoint):
    async def scenario():
        worker, task, _, dispatched = setup(tmp_path)
        task['checkpoint'] = checkpoint
        if checkpoint == 'outcome':
            task['event']['starts_at'] = (worker.now()-timedelta(hours=3)).isoformat()
        worker.experiment_reserved_objects = 1
        worker.ledger.reserve(worker.window_id,'prior-cycle',objects=299,now=worker.now())
        worker.ledger.resolve('prior-cycle',charged=299,evidence='fixture prior cycle',now=worker.now())
        before=worker.ledger.status(worker.window_id)
        rate=worker.ledger.request_capacity(worker.window_id,now=worker.now())
        with storage_patches(), pytest.raises(acquisition.CheckpointUnavailable,match='operational_object_budget'):
            await acquisition.acquire(worker,task)
        assert not dispatched
        assert worker.ledger.status(worker.window_id) == before
        assert worker.ledger.request_capacity(worker.window_id,now=worker.now()) == rate
        # The late task consumes its own reserved allowance under the same cap.
        task['checkpoint']='late'
        task['event']['starts_at']=(worker.now()+timedelta(minutes=10)).isoformat()
        with storage_patches():
            await acquisition.acquire(worker,task)
        assert len(dispatched)==1
        assert worker.ledger.status(worker.window_id)['charged']==300
    asyncio.run(scenario())


@pytest.mark.parametrize('checkpoint', ['early','outcome'])
def test_early_and_postgame_preserve_imminent_late_request_rate_slot(tmp_path, checkpoint):
    async def scenario():
        worker,task,_,dispatched=setup(tmp_path)
        task['checkpoint']=checkpoint
        if checkpoint == 'outcome':
            task['event']['starts_at']=(worker.now()-timedelta(hours=3)).isoformat()
        worker.experiment_reserved_requests=1
        for _ in range(49):
            worker.ledger.reserve_request('account',requests_per_minute=50,now=worker.now())
        before=worker.ledger.status(worker.window_id)
        with storage_patches(), pytest.raises(acquisition.CheckpointUnavailable,match='checkpoint_rate_headroom'):
            await acquisition.acquire(worker,task)
        assert not dispatched and worker.ledger.status(worker.window_id)==before
        assert worker.ledger.request_capacity(worker.window_id,now=worker.now())['used']==49
        task['checkpoint']='late'
        task['event']['starts_at']=(worker.now()+timedelta(minutes=10)).isoformat()
        with storage_patches():
            await acquisition.acquire(worker,task)
        assert len(dispatched)==1
        assert worker.ledger.request_capacity(worker.window_id,now=worker.now())['used']==50
        assert worker.ledger.status(worker.window_id)['charged']==1
    asyncio.run(scenario())


def test_ordinary_and_experiment_requests_share_one_owned_slot(tmp_path):
    async def scenario():
        from app.collection.sportsgameodds_worker import SportsGameOddsWorker
        worker, task, _, dispatched = setup(tmp_path)
        entered, release = asyncio.Event(), asyncio.Event()
        async def ordinary(_params):
            entered.set()
            await release.wait()
            return 'ordinary'
        worker._fetch_owned = ordinary
        normal = asyncio.create_task(SportsGameOddsWorker._fetch(worker, {}))
        await entered.wait()
        with storage_patches():
            checkpoint = asyncio.create_task(acquisition.acquire(worker, task))
            await asyncio.sleep(0)
            assert worker.experiment_late_waiting and not dispatched
            release.set()
            assert await normal == 'ordinary'
            assert (await checkpoint)['page'].events[0]['event_id'] == 'event'
        assert len(dispatched) == 1
    asyncio.run(scenario())


def test_source_metadata_failure_cannot_starve_already_due_checkpoint(tmp_path):
    async def scenario():
        worker, task, _, _ = setup(tmp_path)
        worker.service.workers = {'sportsgameodds':worker}
        scheduler = acquisition.ExperimentAcquisition(worker.service)
        acquired = dict(page='paid-page')
        with patch.object(scheduler,'_prepare',side_effect=ValueError('bad source metadata')), \
                patch.object(scheduler,'_claim',return_value=task), \
                patch.object(scheduler,'_finish',return_value=dict(state='captured')), \
                patch.object(acquisition,'acquire',AsyncMock(return_value=acquired)):
            await scheduler.tick()
        assert scheduler.progress['last_saved']['state'] == 'captured'
        assert scheduler.progress['discovery_reason'] == 'bad source metadata'
        assert not worker.page_in_progress and not worker.experiment_late_waiting
    asyncio.run(scenario())


@pytest.mark.parametrize('phase_flag', ['started','live','ended','completed','finalized','cancelled'])
def test_actual_started_or_closed_response_cannot_be_a_pregame_checkpoint(tmp_path, phase_flag):
    async def scenario():
        from app.collection.background_work import BackgroundWork
        from app.research import experiment
        worker,task,_,_=setup(tmp_path,source_flags={phase_flag:True})
        with storage_patches():
            acquired=await acquisition.acquire(worker,task)
        # The source's event-ID query can ignore phase/start filters. The
        # contradictory lifecycle comes from the actual retained response.
        scheduler=acquisition.ExperimentAcquisition(worker.service,connector=lambda:nullcontext(None))
        memory=BackgroundWork(sampler=lambda:64*1024*1024)
        with patch('app.collection.background_work.BACKGROUND',memory), \
                patch.object(experiment,'discover') as discover, \
                patch('app.research.ev_movement.build_snapshot',side_effect=AssertionError('post-start math ran')):
            with pytest.raises(acquisition.CheckpointUnavailable,match='response_not_pregame') as failure:
                scheduler._finish(worker,task,acquired)
        assert failure.value.dispatched and discover.call_count == 1
        assert worker.ledger.status(worker.window_id)['charged'] == 1
    asyncio.run(scenario())
