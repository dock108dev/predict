"""Exercise the scheduled worker with HTTP fixtures and a disposable product store."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from email.utils import format_datetime
from hashlib import sha256
import json
from types import SimpleNamespace

from aiohttp.test_utils import make_mocked_request
import httpx
import pytest

from app.collection import kalshi_fee_refresh as kalshi
from app.collection import public_fee_refresh as worker
from app.fees import product_schedules as products
from app.storage import store

AT = store.stamp('2026-11-11T05:00:00Z')
RENDERER = 'https://renderer.example.test/kalshi-fee-schedule'
TEXT = 'Synthetic complete rendered schedule for the November 10 approval.'
DIRECT = dict(url=kalshi.SOURCE, retrieved_at='2026-11-10T14:43:00Z', http_status=429)


@pytest.fixture
def sources(monkeypatch, tmp_path):
    config = tmp_path / 'renderer.json'
    config.write_text(json.dumps({'url': RENDERER}))
    monkeypatch.setattr(kalshi, 'CONFIG', config)
    monkeypatch.setattr(kalshi, 'API_SPACING_SECONDS', 0)
    monkeypatch.setattr(worker, 'now', AT.isoformat)
    digest = sha256(' '.join(TEXT.split()).encode()).hexdigest()
    monkeypatch.setitem(products.PRODUCTS[kalshi.KEY], 'rendered_sha256', digest)
    approved = products.approved(kalshi.KEY)
    body = json.loads((products.ROOT / approved['reference']).read_bytes())
    series = {kalshi.API + 'series/' + key: value['response'] for key, value in body['series'].items()}
    return {**series, kalshi.SERIES_CHANGES: body['series_changes'], kalshi.EVENT_CHANGES: body['event_changes'],
            kalshi.ROUNDING: body['rounding_document']}


def transport(sources, requests, *, fault=None):
    def respond(request):
        url = str(request.url.copy_with(query=None)) if request.url.params.get('request_id') else str(request.url)
        requests.append(url)
        assert request.headers['cache-control'] == 'no-cache'
        assert 'authorization' not in request.headers
        if url == RENDERER:
            body = dict(format=kalshi.FORMAT, request_id=request.url.params['request_id'],
                        source_url=kalshi.SOURCE, origin_http_status=200, origin_sha256='a' * 64,
                        origin_retrieved_at=AT.isoformat(), complete=True, page_count=12, text=TEXT)
        else:
            body = deepcopy(sources[url])
        headers = {'date': format_datetime(AT, usegmt=True)}
        status = fault(url, body, headers) if fault else None
        raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        return httpx.Response(status or 200, headers=headers, stream=httpx.ByteStream(raw))

    return httpx.MockTransport(respond)


def attempt(sources, state, *, fault=None, allowed=lambda: True, requests=None):
    async def run():
        async with httpx.AsyncClient(transport=transport(sources, requests if requests is not None else [], fault=fault)) as client:
            async def retrieve(url, limit, **options):
                return await worker.fetch(client, url, limit, **options)

            return await worker.refresh_product(kalshi.KEY, state, retrieve, clock=AT.isoformat, allowed=allowed)

    return asyncio.run(run())


def test_scheduled_renewal_reaches_admin_and_ordinary_offer(sources, monkeypatch, tmp_path):
    from app.dashboard.multi_game_server import create_app
    from app.dashboard.trade_desk import page
    from app.storage import ordinary_publication as live
    from app.storage.current_rows import contract_id
    from tests.test_current_state import owner
    from tests.test_f04_kalshi_public import input_row
    from tests.test_trade_desk import quote

    # Pre-existing row holds the legacy direct check in its old shape.
    states = {kalshi.KEY: dict(next_attempt_at=AT.isoformat(), last_attempt={
        'state': 'failed', 'retrieval': {'failed_request': DIRECT}})}
    writes = []

    class ProductStore:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def execute(self, sql, args):
            if sql.startswith('SELECT venue,state'):
                return SimpleNamespace(fetchall=lambda: [dict(venue=key, state=value) for key, value in states.items()])
            if sql.startswith('SELECT state FROM public_fee_schedule'):
                return SimpleNamespace(fetchone=lambda: None)
            assert sql.startswith('INSERT INTO public_fee_schedule')
            key, value = args
            states[key] = deepcopy(value.obj)
            writes.append(key)

    requests = []
    client = httpx.AsyncClient(transport=transport(sources, requests), follow_redirects=False, trust_env=False)
    monkeypatch.setattr(worker.httpx, 'AsyncClient', lambda **_: client)
    monkeypatch.setattr(store, 'connect', ProductStore)
    monkeypatch.setattr(store, 'now', AT.isoformat)

    async def cycle():
        wake = asyncio.Event()
        runtime = SimpleNamespace(stopping=asyncio.Event(), global_stopped=False,
                                  paused_sources={'the_odds_api', 'polymarket_us'}, connector=ProductStore,
                                  service=SimpleNamespace(config={'enabled': True}), board=SimpleNamespace(wake=wake))
        task = asyncio.create_task(worker.run(runtime))
        try:
            await asyncio.wait_for(wake.wait(), timeout=3)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert runtime.paused_sources == {'the_odds_api', 'polymarket_us'}
        assert not runtime.global_stopped
        app = create_app(owner=owner(), sessions={}, watch_path=tmp_path / 'watches.json')
        route = next(route for route in app.router.routes()
                     if route.method == 'GET' and route.resource.canonical == '/api/admin/fee-schedules')
        response = await route.handler(make_mocked_request('GET', '/api/admin/fee-schedules', app=app))
        return next(p for p in json.loads(response.body)['products'] if p['venue'] == 'kalshi')

    admin = asyncio.run(cycle())
    assert writes == [kalshi.KEY]
    assert requests == [RENDERER, *sources]
    assert admin['state'] == 'verified' and admin['refresh']['state'] == 'verified'
    assert admin['last_verified_at'] == AT.isoformat()
    assert admin['review_before'] == (AT + timedelta(days=1)).isoformat()
    assert admin['next_refresh_at'] == (AT + timedelta(hours=6)).isoformat()
    assert admin['direct_pdf'] == DIRECT
    assert admin['retrieval']['series_count'] == 18 and admin['retrieval']['event_history_complete']
    assert admin['retrieval']['rendered_origin']['http_status'] == 200

    native, _, _ = input_row()
    row = {**quote('rendered-renewal', 'kalshi'), **native}
    row.pop('reference')
    row.update(start_at=(AT + timedelta(hours=2)).isoformat(),
               times=dict(source_at=AT.isoformat(), received_at=AT.isoformat()))
    record = dict(event={'start_at': row['start_at']}, quote=row.copy())
    row['original_record'] = record
    deps = {contract_id(record): ['price', 'contract', 'event', 'receipt']}
    inputs = dict(quotes=[row], captured_at=AT.isoformat(), dependencies=deps, policy_identity='policy',
                  epoch='epoch', id='capture', games=[], references=[], sources={}, issues=[], capture_seconds=0,
                  fee_products=states)
    settings = {'revision': 'settings', 'benchmark_venue': 'pinnacle'}
    published = live.prices(inputs, settings)
    projected = live.project(published, deps, dict(healthy=True, active=True, fee_products=states),
                             {'kalshi': {'state': 'available'}, 'pinnacle': {'state': 'unavailable'}},
                             at=AT, policy='policy', epoch='epoch')
    view = page(projected, {'venue': 'kalshi', 'basis': 'conservative'}, ('ev', 'gross_return_percent', 0, 25))
    offer = view['rows'][0]['offers'][0]
    fee = offer['trade_fee']
    assert offer['current'] and not offer['reference_current']
    assert fee['trade_fee_usd'] == '0.02'
    assert fee['evidence']['reviewed_at'] == admin['last_verified_at']
    assert fee['evidence']['review_before'] == admin['review_before']
    assert fee['evidence']['retrieval']['rendered_origin'] == admin['retrieval']['rendered_origin']
    assert fee['evidence']['verification_revision'] == states[kalshi.KEY]['last_verified']['revision']
    before = products.for_offer(states, row, AT - timedelta(minutes=1))
    assert before['review_before'] == '2026-11-11T04:24:42.474962+00:00'


@pytest.mark.parametrize(('scenario', 'outcome', 'reason'), [
    ('renderer_503', 'failed', 'fee_http_status'),
    ('wrong_nonce', 'failed', 'kalshi_rendered_origin_unverified'),
    ('stale_origin', 'failed', 'kalshi_rendered_origin_unverified'),
    ('origin_429', 'failed', 'kalshi_rendered_origin_http_status'),
    ('stale_api', 'failed', 'fee_response_freshness_unverified'),
    ('incomplete_render', 'review_required', 'kalshi_rendered_scope_ambiguous'),
    ('pdf_changed', 'review_required', 'kalshi_rendered_schedule_changed'),
    ('series_changed', 'review_required', 'kalshi_market_terms_changed'),
    ('series_history_changed', 'review_required', 'kalshi_market_terms_changed'),
    ('partial_events', 'review_required', 'kalshi_market_terms_ambiguous'),
    ('event_override', 'review_required', 'kalshi_market_terms_changed'),
    ('rounding_changed', 'review_required', 'kalshi_rounding_terms_changed'),
])
def test_only_complete_unchanged_fresh_evidence_can_renew(sources, scenario, outcome, reason):
    previous = attempt(sources, {'direct_pdf': DIRECT})

    def fault(url, body, headers):
        if url == RENDERER:
            if scenario == 'renderer_503':
                return 503
            if scenario == 'wrong_nonce':
                body['request_id'] = 'wrong'
            if scenario == 'stale_origin':
                body['origin_retrieved_at'] = (AT - timedelta(seconds=1)).isoformat()
            if scenario == 'origin_429':
                body['origin_http_status'] = 429
            if scenario == 'incomplete_render':
                body['complete'] = False
            if scenario == 'pdf_changed':
                body['text'] += ' New fee.'
        if url == kalshi.API + 'series/KXNBAGAME' and scenario == 'series_changed':
            body['series']['fee_multiplier'] = 2
        if url == kalshi.SERIES_CHANGES and scenario == 'series_history_changed':
            body['series_fee_change_arr'].append(dict(series_ticker='KXNBAGAME', scheduled_ts=AT.isoformat(),
                                                      fee_type='quadratic', fee_multiplier=2))
        if url == kalshi.EVENT_CHANGES:
            if scenario == 'partial_events':
                body['cursor'] = 'next'
            if scenario == 'event_override':
                body['event_fee_changes'].append(dict(series_ticker='KXNBAGAME', event_ticker='KXNBAGAME-FIXTURE',
                    scheduled_ts=AT.isoformat(), fee_type_override=None, fee_multiplier_override=0))
            if scenario == 'stale_api':
                headers['age'] = '600'

    changed_sources = {**sources, kalshi.ROUNDING: 'Changed official rounding terms.'} if scenario == 'rounding_changed' else sources
    result = attempt(changed_sources, previous, fault=fault)
    assert result['last_attempt']['state'] == outcome
    assert result['last_attempt']['error'] == reason
    assert result['last_verified'] == previous['last_verified']
    assert result['direct_pdf'] == DIRECT
    if outcome == 'review_required':
        assert products.for_offer({kalshi.KEY: result}, {'venue': 'kalshi'}, AT)['unavailable_reason'] == products.REVIEW_REQUIRED
        retried = attempt(sources, result)
        assert retried['last_attempt']['error'] == 'prior_change_requires_explicit_review'
    else:
        assert 'review_required' not in result
        assert result['next_attempt_at'] == (AT + timedelta(minutes=15)).isoformat()


def test_source_pause_mid_attempt_prevents_followup_and_persistence(sources):
    requests = []
    result = attempt(sources, None, requests=requests, allowed=lambda: not requests)
    assert result is None
    assert requests == [RENDERER]
