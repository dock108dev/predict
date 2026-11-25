"""Compact committed collection status and the existing owner controls."""

from datetime import datetime, timezone

from aiohttp import web

from app.collection.activity_mode import read_status
from app.owned_work import joined_thread
from app.storage.store import connect, stamp

from .local_security import PublicRequestError, read_json


def status(provider):
    current = provider.status()
    runtime = current.get('data_runtime', {})
    sources = current.get('sources', [])
    aggregate = current.get('config', {}).get('aggregate_provider', 'sportsgameodds')
    source = next((row for row in sources if row.get('provider') == aggregate), {})
    last_pull_at = source.get('last_valid_receipt_at')
    active = bool(current.get('dispatch_enabled'))
    paused = runtime.get('paused_sources') or []
    state = 'Collecting'
    problem = None
    if runtime.get('healthy') is False or current.get('service_state') == 'unavailable':
        state = 'Collection unavailable'
        problem = 'Collector heartbeat unavailable'
    elif runtime.get('global_stopped'):
        state = 'Collection stopped'
    elif aggregate in paused:
        state = 'Source paused'
    elif not active:
        state = 'Collection idle'
        if current.get('config', {}).get('enabled'):
            problem = 'Collection dispatch is blocked'
    else:
        behavior = source.get('worker_behavior')
        problem = {
            'terminal_failure': 'Odds worker stopped',
            'unavailable': 'Odds source unavailable',
            'accounting_hold': 'Waiting on a credit hold',
            'retrying': 'Odds source retry pending',
            'waiting_for_cycle': None,
        }.get(behavior)
        if not problem and any(row.get('state') == 'budget_delayed' for row in source.get('status', {}).values()):
            problem = 'Odds pull delayed by the collection budget'

    next_pull_at = None
    if active and aggregate not in paused and problem not in (
            'Odds worker stopped', 'Odds source unavailable', 'Waiting on a credit hold'):
        at = datetime.now(timezone.utc)
        with connect() as db, db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            db.execute("SET LOCAL statement_timeout='3s'")
            schedule = read_status(db, at=at)
            next_discovery = stamp(schedule['next_monitor_at'])
            checkpoint = db.execute("""SELECT min(target_at) AS at
                FROM ev_experiment_task
                WHERE state='pending' AND checkpoint IN ('early','late')
                AND deadline_at>=%s""", (at,)).fetchone()['at']
            next_pull_at = min(next_discovery, max(at, checkpoint)) if checkpoint else next_discovery
        retry_at = source.get('metrics', {}).get('next_refresh_at')
        if problem and retry_at:
            next_pull_at = max(next_pull_at, stamp(retry_at))
        next_pull_at = next_pull_at.isoformat()
    return dict(state=state, last_pull_at=last_pull_at, next_pull_at=next_pull_at,
                problem=problem, provider_requests=0)


def mount(app, provider):
    async def compact(request):
        if request.query:
            raise PublicRequestError('Collection status takes no filters.')
        value = await joined_thread(__name__, 'collection_status_after_cancellation',
                                    lambda: status(provider))
        return web.json_response(value)

    async def controls(request):
        if request.method in ('GET', 'HEAD'):
            value = await joined_thread(__name__, 'owner_status_after_cancellation', provider.status)
            return web.json_response(value)
        body = await read_json(request)
        if not isinstance(body, dict):
            raise PublicRequestError('Exact collection control required.')
        if body == {'action': 'stop'}:
            await provider.stop()
        elif (set(body) == {'action', 'source'} and body['action'] == 'pause'
                and body['source'] in ('kalshi', 'polymarket_us', 'the_odds_api', 'sportsgameodds')):
            await provider.pause(body['source'])
        elif set(body) == {'action', 'runtime_id', 'candidate_digest'} and body['action'] == 'recover':
            await provider.recover(body['runtime_id'], body['candidate_digest'])
        elif (set(body) == {'action', 'runtime_id', 'candidate_digest', 'recovery_id', 'covered_attempts'}
                and body['action'] == 'recover_accounting'):
            await provider.recover_accounting(
                body['runtime_id'], body['candidate_digest'], body['recovery_id'], body['covered_attempts'])
        else:
            raise PublicRequestError('Unsupported collection control.')
        value = await joined_thread(__name__, 'owner_status_after_control', provider.status)
        return web.json_response(value)

    app.router.add_get('/api/workspace/collection', compact)
    app.router.add_get('/api/admin/status', controls)
    app.router.add_get('/api/admin/current', controls)
    app.router.add_post('/api/admin/current', controls)
