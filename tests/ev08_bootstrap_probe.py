"""Fresh-process retained bootstrap/HTTP evidence, under ev08_watchdog.

Only authored retained files and loopback are permitted. The parent timestamps
before launching the fresh server interpreter, so imports, decoding, validation
and complete numerical page receipt all count. Browser paint is a separate gate.
"""
import argparse
import asyncio
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import sys
from time import perf_counter
from urllib.parse import urlencode

SCHEMA = 'predict-retained-prices-1'
PAGE_CAP = 256 * 1024
PROCESS_CAP = 768 * 1024 * 1024


def write(out, name, value):
    temporary = out / (name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(out / name)


def statistics(samples):
    values = sorted(sample['seconds'] for sample in samples)
    return dict(samples=len(values), median_seconds=None if not values else
                (values[(len(values)-1)//2] + values[len(values)//2])/2,
                p95_seconds=None if not values else values[math.ceil(.95*len(values))-1],
                max_seconds=max(values, default=None),
                failures=sum(sample['status'] != 200 for sample in samples))


def validate_page(value, *, generation=None, settings=0):
    """Independent transport invariants; never promote progress to admission."""
    assert value['schema'] == SCHEMA
    assert isinstance(value['runtime_id'], str) and value['runtime_id']
    assert isinstance(value['generation_id'], str) and value['generation_id']
    assert value['settings_generation'] == settings
    if generation is not None:
        assert value['generation_id'] == generation
    assert value['status'] in ('pending', 'ready', 'rejected', 'superseded', 'stopped')
    if value['status'] != 'ready':
        assert value['input_epoch'] is None and value['state_revision'] is None
    else:
        assert type(value['input_epoch']) is int and value['input_epoch'] >= 0
        assert type(value['state_revision']) is int and value['state_revision'] >= 1
    assert isinstance(value['estimate_policy'], dict)
    from app.dashboard.current_contract import stamp
    stamp(value['input_clock_at']); stamp(value['validation_at'])
    progress = value['progress']
    assert progress['discovery_status'] in ('validating_prices', 'prices_complete', 'evaluating', 'complete')
    for key in ('discovered_prices', 'validated_prices', 'ready_singles', 'refused_singles', 'ready_pairs', 'refused_pairs'):
        assert type(progress[key]) is int and progress[key] >= 0
    assert progress['validated_prices'] <= progress['discovered_prices']
    for kind in ('prices', 'singles', 'pairs'):
        total = progress['total_' + kind]
        assert total is None or type(total) is int and total >= 0
        if kind != 'prices':
            pending = progress['pending_' + kind]
            assert pending is None or type(pending) is int and pending >= 0
            if total is None:
                assert pending is None
            else:
                assert pending + progress['ready_' + kind] + progress['refused_' + kind] == total
    if progress['discovery_status'] == 'validating_prices':
        assert progress['total_prices'] is None
    if progress['discovery_status'] == 'complete':
        assert progress['total_prices'] == progress['validated_prices'] == progress['discovered_prices']
        assert progress['pending_singles'] == progress['pending_pairs'] == 0
    assert value['pagination']['page_size'] == 1
    assert len(value['rows']) <= 1
    if value['status'] in ('pending', 'ready'):
        assert value['pagination']['total_rows'] == progress['validated_prices']
    else:
        assert value['pagination']['total_rows'] == 0 and not value['rows']
    for row in value['rows']:
        assert isinstance(row['id'], str) and row['id']
        assert type(row['revision']) is int and row['revision'] >= 1
        assert set(('provider', 'event_id', 'market_id', 'outcome_id', 'side', 'quote_side')) <= set(row['native'])
        assert all(isinstance(row['native'][key], str) and row['native'][key]
                   for key in ('provider', 'event_id', 'market_id', 'outcome_id', 'side', 'quote_side'))
        from fractions import Fraction
        assert Fraction(row['original']['value']) > 0
        assert row['original']['units'] in ('decimal_odds', 'cents_per_contract', 'usd_per_contract')
        for key in ('source_at', 'received_at', 'projected_at'):
            stamp(row['times'][key], nullable=key == 'source_at')
        assert row['times']['source_time_kind']
    return value


async def worker(args):
    from contextlib import ExitStack
    from unittest.mock import patch
    from aiohttp import web
    from app.dashboard.current_state import CURRENT_KEY
    from app.dashboard.multi_game_server import create_app
    from tests.current_fixture import InjectedTestProvider
    from tests.test_current_state import owner
    from tests.ev07_fixture_runtime import FixtureBoundary, FIXTURE_POLICY
    out = Path(args.out)
    task = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, task.cancel)
    lags = []
    async def pulse():
        previous = perf_counter()
        while True:
            await asyncio.sleep(.01)
            now = perf_counter(); lags.append(max(0, now-previous-.01)); previous = now
            if len(lags) > 20000:
                del lags[:10000]
    with ExitStack() as stack, FixtureBoundary() as boundary:
        for target in ('app.dashboard.current_incremental.load', 'app.comparison.current_metrics.load_estimate_policy'):
            stack.enter_context(patch(target, new=lambda: FIXTURE_POLICY))
        body = Path(args.retained).read_bytes()
        raw = json.loads(body); input_hash = sha256(body).hexdigest(); del body
        raw['state_revision'] = max(2, raw['state_revision'])
        injected = InjectedTestProvider(raw)
        injected.retained_bootstrap = True
        fixture_owner = owner(); fixture_owner.start.side_effect = boundary.refuse('owner.start')
        app = create_app(owner=fixture_owner, sessions={}, current_provider=injected)
        store = app[CURRENT_KEY]
        future = store.admission.latest['future']
        del raw
        records = []
        @web.middleware
        async def timing(req, handler):
            entered = perf_counter(); dispatched = req.headers.get('X-EV08-Dispatch-Monotonic')
            cache_before = store._comparison_body_cache
            result = await handler(req)
            if req.path=='/api/comparison':
                result.headers['X-EV08-Cache-Hit']=str(cache_before is not None and cache_before is store._comparison_body_cache).lower()
            if req.path.startswith('/api/'):
                records.append(dict(path=req.path, status=result.status,
                    queue_seconds=None if dispatched is None else entered-float(dispatched),
                    handler_seconds=perf_counter()-entered,
                    comparison_cache_hit=None if req.path != '/api/comparison' else
                    cache_before is not None and cache_before is store._comparison_body_cache))
                write(out, 'server-requests.json', records[-300:])
            return result
        app.middlewares.insert(0, timing)
        async def clear_cache(req):
            # Explicit fixture action; never changes policy, input or clock.
            store._clear_comparison_body()
            return web.json_response(dict(cleared=True, acquired_prices=False))
        app.router.add_post('/__ev08/clear-comparison-cache', clear_cache)
        runner = web.AppRunner(app); await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        pulse_task = asyncio.create_task(pulse())
        outcome = None
        try:
            await site.start()
            write(out, 'ready.json', dict(url='http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1]),
                listener_monotonic=perf_counter(), input_sha256=input_hash,
                evidence_class='authored retained bootstrap; listener is not useful-price completion'))
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            stop_started = perf_counter()
            service = None
            if args.mode != 'complete':
                # Exercise the real independent stopped-health sink. This
                # fixture has no started acquisition, attempt or source workers.
                from app.collection.current_service import CurrentService
                from app.collection.current_policy import DEFAULT
                from app.collection.current_sink import LatestStateSink
                from app.collection.local_ownership import LocalOwnership
                service = CurrentService(config=dict(DEFAULT, enabled=False, aggregate_enabled=False),
                    directory=out/'authored-authority', ownership=LocalOwnership(out/'authored-owner.lock'))
                service.runtime_id = store._state['runtime_id']; service.allow_synthetic = True
                service.store = store
                service.sink = LatestStateSink(store, service.initial_state(), service.config)
                store.provider = service
            await runner.cleanup()
            if 'future' in locals() and future.done():
                outcome = future.result()
            pulse_task.cancel(); await asyncio.gather(pulse_task, return_exceptions=True)
            admission = store.admission
            state_after_stop = store._state
            await asyncio.sleep(.03)
            write(out, 'cleanup.json', dict(closed=store.closed, stop_seconds=perf_counter()-stop_started,
                outcome=None if outcome is None else outcome.status,
                outcome_error=None if outcome is None else outcome.error,
                latest_outcome=None if admission.latest is None or admission.latest['future'] is None else admission.latest['future'].result().status,
                latest_outcome_error=None if admission.latest is None or admission.latest['future'] is None else admission.latest['future'].result().error,
                admission_driver_done=admission.driver is None or admission.driver.done(),
                active=admission.active is not None, pending=admission.pending is not None,
                admission_metrics=dict(admission.metrics), no_post_stop_publication=store._state is state_after_stop,
                remaining_admission_readers=admission.readers,
                actual_iterator_closed=admission.iterator is None,
                stopped_health_acknowledgements=None if service is None else service.sink.sequence,
                stopped_source_health=store._shutdown_health,
                source_fixture=None if service is None else dict(started=False, dispatch=False,
                    workers=len(service.workers), attempt=None, cleanup_complete=service.cleanup_complete,
                    ownership_released=service.ownership.file is None,
                    evidence_class='actual shutdown-health sink; authored source authority with no acquisition start'),
                remaining_files=len(store.encoded_bodies.owners), remaining_readers=len(store.encoded_bodies.readers),
                loop_lag_samples=len(lags), loop_lag_max_seconds=max(lags, default=0),
                loop_lag_seconds=lags, kernel_highwater_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                provider_requests=0, forbidden_calls=boundary.calls,
                outgoing_connects=[item for item in boundary.network if '127.0.0.1' not in item['address']],
                evidence_class='actual fixture application cleanup; independent watchdog cleanup is separate'))


async def qualify(args):
    from aiohttp import ClientSession, ClientTimeout
    out = Path(args.out); out.mkdir(parents=True, exist_ok=False)
    report = dict(evidence_class='authored retained fresh-process HTTP; browser paint measured separately',
        cold_application=True, filesystem_cache_controlled=False,
        timer='same-host perf_counter CLOCK_MONOTONIC from before fresh interpreter launch through complete received JSON',
        environment=dict(platform=platform.platform(), machine=platform.machine(), python=sys.version,
            hardware=subprocess.check_output(['sysctl', '-n', 'hw.model', 'hw.ncpu', 'hw.memsize'], text=True).splitlines(),
            background_load=os.getloadavg()), samples=[], milestones={}, failure=None)
    # Client imports precede launch; server imports and all startup work count.
    started = perf_counter()
    with (out/'server.log').open('w') as log:
        child = subprocess.Popen([sys.executable, '-m', 'tests.ev08_bootstrap_probe', '--worker',
                                  '--retained', args.retained, '--out', str(out), '--mode', args.mode], stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = started + args.timeout
            while not (out/'ready.json').exists():
                if child.poll() is not None:
                    raise AssertionError('Fresh server exited before listener; see server.log')
                if perf_counter() > deadline:
                    raise AssertionError('Fresh listener timeout')
                await asyncio.sleep(.01)
            ready = json.loads((out/'ready.json').read_text())
            report['milestones']['listener_seconds'] = ready['listener_monotonic']-started
            url = ready['url']
            async with ClientSession(timeout=ClientTimeout(total=args.timeout)) as client:
                async def read(path, phase, *, cap=64*1024*1024, capture=True, expect=200):
                    tick = perf_counter(); count = 0; content = bytearray() if capture else None
                    async with client.get(url+path, headers={'X-EV08-Dispatch-Monotonic': str(tick)}) as response:
                        headers = perf_counter()
                        async for chunk in response.content.iter_chunked(65536):
                            count += len(chunk)
                            if count > cap:
                                raise AssertionError('Complete response exceeded declared cap')
                            if capture:
                                content.extend(chunk)
                        observed_hit=response.headers.get('X-EV08-Cache-Hit')
                        observed_phase='advancing_reuse_miss' if phase=='serial_immediate_reuse' and observed_hit=='false' else phase
                        sample = dict(path=path, phase=observed_phase, comparison_cache_hit=None if observed_hit is None else observed_hit=='true', status=response.status, bytes=count,
                                      seconds=perf_counter()-tick, headers_seconds=headers-tick)
                        report['samples'].append(sample)
                        if len(report['samples'])%50==0:write(out, 'result.json', report)
                        assert response.status == expect, sample
                    return json.loads(content) if capture else None
                generation = None; first = None; snapshots = []
                while True:
                    value = validate_page(await read('/api/current/prices?settings_generation=0&page=0', 'bootstrap', cap=PAGE_CAP))
                    if generation is not None and value['generation_id']!=generation:
                        report.setdefault('generation_transitions',[]).append(dict(previous=generation,current=value['generation_id'],
                            input_clock_at=value['input_clock_at'],reason='owned eligibility supersession; no source epoch acknowledged'))
                        write(out, 'generation-transitions.json', report['generation_transitions'])
                    generation = value['generation_id']; snapshots.append(dict(status=value['status'], progress=value['progress']))
                    if value['rows'] and first is None:
                        first = value; report['milestones']['first_useful_original_price_seconds'] = perf_counter()-started
                        write(out, 'first-price-page.json', value)
                        if report['milestones']['first_useful_original_price_seconds'] > 2:
                            raise AssertionError('Fresh-process useful original price exceeded two seconds')
                    if args.mode == 'stop-bootstrap' and value['progress']['discovery_status'] == 'validating_prices':
                        break
                    if args.mode == 'stop-admission' and value['status'] == 'pending' and value['progress']['discovery_status'] == 'evaluating':
                        break
                    if value['status'] == 'ready':
                        assert args.mode == 'complete', 'Requested Stop boundary completed before observation'
                        report['milestones']['full_fair_slate_ready_seconds'] = perf_counter()-started
                        break
                    if value['status']!='pending':write(out,'terminal-page.json',value)
                    assert value['status'] == 'pending', (value['status'],value['error'])
                    if perf_counter() > deadline:
                        raise AssertionError('Complete owned admission timeout')
                    await asyncio.sleep(.02)
                write(out, 'progress-snapshots.json', snapshots)
                if args.mode == 'complete':
                    expected = {}
                    raw = json.loads(Path(args.retained).read_bytes())
                    from app.dashboard.current_contract import quotes_of
                    for event in raw['events']:
                        for group in event['groups']:
                            for outcome in group['outcomes']:
                                for quote in quotes_of(outcome):
                                    source=quote['source']
                                    expected[(quote['venue'],*[source[k] for k in ('provider','native_event_id','native_market_id','native_outcome_id','native_side','quote_side')])] = quote
                    del raw
                    rows = {};seen_ids=set()
                    for page in range(math.ceil(value['pagination']['total_rows']/1)):
                        body = validate_page(await read('/api/current/prices?' + urlencode(dict(settings_generation=0, page=page, generation_id=generation)), 'inventory', cap=PAGE_CAP), generation=generation)
                        assert body['status'] == 'ready'
                        for row in body['rows']:
                            assert row['id'] not in seen_ids;seen_ids.add(row['id'])
                            native=row['native'];key=(row['venue'],*[native[k] for k in ('provider','event_id','market_id','outcome_id','side','quote_side')])
                            original = expected[key]
                            assert row['original'] == original['original'] and row['times'] == original['times']
                            assert row['revision'] == original['revision']
                            native = row['native']; source = original['source']
                            assert native == dict(provider=source['provider'], event_id=source['native_event_id'], market_id=source['native_market_id'], outcome_id=source['native_outcome_id'], side=source['native_side'], quote_side=source['quote_side'])
                            rows[key] = True
                    assert set(rows) == set(expected), 'Native alternatives omitted'
                    del rows, expected
                    changed_settings = validate_page(await read('/api/current/prices?settings_generation=1&page=0', 'settings_echo', cap=PAGE_CAP), generation=generation, settings=1)
                    assert changed_settings['estimate_policy'] == value['estimate_policy']
                    assert changed_settings['runtime_id'] == value['runtime_id']
                    refused = await read('/api/current/prices?settings_generation=0&page=1&generation_id=wrong', 'schema_refusal', cap=PAGE_CAP, expect=409)
                    assert refused['error'] == 'retained_prices_unavailable' and 'rows' not in refused
                    refused = await read('/api/current/prices?settings_generation=0&page=1', 'schema_refusal', cap=PAGE_CAP, expect=409)
                    assert refused['error'] == 'retained_prices_unavailable' and 'rows' not in refused
                    current = await read('/api/current', 'context_discovery')
                    context_started = perf_counter()
                    pair = next(pair for event in current['events'] for pair in event['funded_pairs'])
                    a, b = pair['legs']
                    params = dict(runtime_id=current['runtime_id'], state_revision=current['state_revision'], quote_id=a['quote_id'], quote_revision=a['quote_revision'], opposing_quote_id=b['quote_id'], opposing_quote_revision=b['quote_revision'], pair_id=pair['id'], pair_revision=pair['revision'], objective=pair['objective'])
                    del current
                    details = '/api/current/details?' + urlencode(params)
                    selected = await read(details, 'context_through_details', cap=2*1024*1024)
                    assert selected['funded_pairs'] and len(selected['leg_quotes']) == 2
                    report['milestones']['context_discovery_through_details_seconds'] = perf_counter()-context_started + report['samples'][-2]['seconds']
                    report['milestones']['first_exact_generation_estimate_seconds'] = perf_counter()-started
                    def accept_phase(phase):
                        samples = [sample for sample in report['samples'] if sample['phase'] == phase]
                        result = statistics(samples); report.setdefault('statistics', {})[phase] = result
                        assert result['failures'] == 0 and result['p95_seconds'] <= 1, (phase, result)
                    for _ in range(10):
                        async with client.post(url+'/__ev08/clear-comparison-cache',headers={'Origin':url},json={}) as response:
                            assert response.status == 200, (response.status,await response.text())
                            assert (await response.json())['cleared']
                        await read('/api/comparison', 'serial_controlled_miss', capture=False)
                        await read('/api/comparison', 'serial_immediate_reuse', capture=False)
                    accept_phase('serial_controlled_miss')
                    for _ in range(20):
                        if sum(s['phase']=='serial_immediate_reuse' for s in report['samples'])>=10:break
                        await read('/api/comparison','serial_immediate_reuse',capture=False)
                    assert sum(s['phase']=='serial_immediate_reuse' for s in report['samples'])>=10, 'Controlled cache-hit sample floor'
                    accept_phase('serial_immediate_reuse')
                    if any(s['phase']=='advancing_reuse_miss' for s in report['samples']):accept_phase('advancing_reuse_miss')
                    for _ in range(10):
                        for path in ('/api/current', '/api/comparison', details):
                            await read(path, 'serial', capture=False)
                    accept_phase('serial')
                    for _ in range(3):
                        await asyncio.gather(*(read(path, 'concurrent_four', capture=False) for path in ('/api/current', '/api/comparison', '/api/comparison', details)))
                    accept_phase('concurrent_four')
                    for _ in range(3):
                        await read('/api/comparison?ceiling=500', 'singleton_override_burst', capture=False)
                    accept_phase('singleton_override_burst')
        except BaseException as error:
            report['failure'] = type(error).__name__ + ': ' + str(error)
            raise
        finally:
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)
            try:
                await asyncio.to_thread(child.wait, timeout=10)
            except subprocess.TimeoutExpired:
                # Keep failure evidence; this never establishes graceful Stop.
                child.kill(); child.wait(); report['forced_cleanup'] = True
            report['server_returncode'] = child.returncode
            report['client_kernel_highwater_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            write(out, 'result.json', report)
    cleanup = json.loads((out/'cleanup.json').read_text())
    assert cleanup['closed'] and cleanup['admission_driver_done']
    assert not cleanup['active'] and not cleanup['pending']
    assert cleanup['actual_iterator_closed'] and cleanup['no_post_stop_publication']
    assert cleanup['remaining_admission_readers'] == 0
    assert cleanup['admission_metrics']['started'] == 1+cleanup['admission_metrics']['rebased'], 'Repeated reads launched duplicate admission jobs'
    assert cleanup['remaining_files'] == cleanup['remaining_readers'] == 0
    assert not cleanup['forbidden_calls'] and not cleanup['outgoing_connects']
    assert cleanup['kernel_highwater_bytes'] < PROCESS_CAP and report['client_kernel_highwater_bytes'] < PROCESS_CAP
    assert child.returncode == 0 and not report.get('forced_cleanup')
    if args.mode != 'complete':
        assert cleanup['outcome'] == 'stopped'
        assert cleanup['stopped_health_acknowledgements'] == 4
        assert all(state['state'] == 'stopped' for state in cleanup['stopped_source_health'].values())
        assert cleanup['source_fixture']['cleanup_complete'] and cleanup['source_fixture']['ownership_released']
    print(json.dumps(dict(status='passed', mode=args.mode, milestones=report['milestones'])))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True); parser.add_argument('--retained', required=True)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--mode', choices=('complete', 'stop-bootstrap', 'stop-admission'), default='complete')
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args()
    if not os.environ.get('PREDICT_CI_ISOLATED_ROOT') or not os.environ.get('PREDICT_CI_REPORT_ROOT'):
        raise ValueError('Inherited private-state/outbound guard required; run under ev08_watchdog')
    asyncio.run(worker(args) if args.worker else qualify(args))
