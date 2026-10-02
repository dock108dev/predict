"""Production reader/semantic admission/journal/replay on actual loopback sockets.

Every US body is an explicitly constructed engineering control. Kalshi input is
the unchanged HTTP receipt and 55 frames already captured by the consumed v3
attempt. The local session is mock; original clocks are retained and no pairing
with a new provider observation is claimed. No launcher/approval package exists.
"""
import asyncio
import base64
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import random
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.collection.continuous import ContinuousSession, REST
from app.collection.native_approval import digest, implementation
from app.collection.native_book_report import summarize
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
from app.dashboard.session_history import load, verified

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/us-metadata-delivery-repair-20260930-v1'
PACKAGE = ROOT / 'evidence/native-nyi-tor-20260930-v3'
ORIGINAL = ROOT / 'evidence/native-nyi-tor-binding-attempt-315b9167-a753-4e5b-ae18-19dd9724cfb7/5aa176bf-992c-4d48-a40c-7572099af32f'
NOW = datetime(2026, 9, 30, 22, 31, 3, tzinfo=timezone.utc)
KIB = 1024
MIB = 1024 * KIB
SECRET = b'OFFLINE-SENTINEL-DO-NOT-PERSIST-573809'
CLASSIFICATION = ('SYNTHETIC ENGINEERING CONTROL ONLY. US complete bodies were constructed '
                  'from retained reviewed objects, never from a failed prefix. Kalshi HTTP '
                  'and books are historical offline replays with original source timestamps; '
                  'no new provider observation or contemporaneous two-source pairing.')


class OfflineClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


class FixtureCredential:
    """Synthetic echo detector; no secret-store/signing implementation is used."""
    def headers(self, *args):
        return {'OFFLINE-Protocol-Fixture': 'not-a-credential'}

    def check(self, raw, headers=None):
        if SECRET in raw or base64.b64encode(SECRET) in raw:
            raise ValueError('credential echo suppressed')


class OfflineSession(ContinuousSession):
    async def start(self):
        result = await super().start()
        self.credentials = {}
        return result


class EchoControlREST(REST):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A synthetic detector is injected only in the echo control, into the
        # unchanged production reader; session fixture credentials stay empty.
        self.credential = FixtureCredential()


def inputs():
    rows = list(verified(ORIGINAL)['rows'])
    metadata = next(r for r in rows if r['type'] == 'prediction_discovery_http' and r['source'] == 'kalshi')
    frames = [r for r in rows if r['type'] == 'prediction_frame' and r['source'] == 'kalshi']
    assert metadata['complete'] and len(frames) == 55
    return metadata, frames


def body_for(scenario):
    spec = json.loads((PACKAGE / 'run-spec.json').read_text())
    event = deepcopy(spec['native_review_records'][0]['sources']['polymarket_us']['catalog_evidence']['event']['native_metadata'])
    envelope = {'event': event, 'constructed_engineering_padding': ''}
    if scenario in ('realistic_nested_large', 'inventory_overflow'):
        selected = deepcopy(event['markets'][0])
        # Fully constructed unrelated embedded markets with repeated terms,
        # sides and teams. No source objects are synthesized from a prefix.
        for index in range(170 if scenario == 'inventory_overflow' else 125):
            market = deepcopy(selected)
            market.update(id=str(8000000 + index), slug='constructed-market-' + str(index))
            for side_index, side in enumerate(market['marketSides']):
                side.update(id=str(9000000 + 2 * index + side_index), marketId=8000000 + index,
                            identifier='constructed-market-' + str(index))
            event['markets'].append(market)
        raw = json.dumps(envelope, separators=(',', ':')).encode()
        assert 512 * KIB < len(raw) < 2 * MIB
        return raw
    if scenario == 'changed_terms':
        event['markets'][0]['description'] += ' CONSTRUCTED changed settlement term.'
    if scenario == 'unknown_terms':
        event['markets'][0]['constructed_unknown_contract_field'] = 'unreviewed'
    if scenario.startswith('secret_echo'):
        envelope = {'constructed_echo': SECRET.decode(), **envelope}
    if scenario == 'unexpected_envelope':
        return json.dumps({'events': [event]}).encode()
    if scenario == 'malformed':
        return b'{"event":INVALID}'
    if scenario == 'truncated':
        return b'{"event":{"id":"127804"'
    if scenario == 'structure_overflow':
        return b'{"event":{},"constructed":[' + b','.join([b'{}'] * 50001) + b']}'
    target = (512 * KIB if scenario == 'legacy_exact_boundary' else
              2 * MIB if scenario in ('exact_boundary', 'exact_boundary_incompressible') else
              2 * MIB + 1 if scenario in ('entity_overflow', 'both_terminal', 'secret_echo_overflow') else 700 * KIB)
    raw = json.dumps(envelope, separators=(',', ':')).encode()
    count = target - len(raw)
    if scenario == 'exact_boundary_incompressible':
        rng = random.Random(20260930)
        envelope['constructed_engineering_padding'] = base64.b64encode(rng.randbytes((count * 3 + 3) // 4)).decode()[:count]
    else:
        envelope['constructed_engineering_padding'] = 'x' * count
    raw = json.dumps(envelope, separators=(',', ':')).encode()
    assert len(raw) == target
    return raw


class LocalProviderControls:
    def __init__(self, scenario):
        self.scenario = scenario
        self.metadata, self.frames = inputs()
        self.us_body = body_for(scenario)
        self.http_requests = []
        self.ws_requests = []
        self.frame_hashes = []
        self.handlers = set()
        self.kalshi_done = asyncio.Event()
        self.http_server = None
        self.ws_server = None

    async def __aenter__(self):
        self.http_server = await asyncio.start_server(self.http, '127.0.0.1', 0)
        app = web.Application()
        app.router.add_get('/ws/{source}', self.websocket)
        self.ws_server = TestServer(app, host='127.0.0.1')
        await self.ws_server.start_server()
        port = self.http_server.sockets[0].getsockname()[1]
        self.endpoints = {v: dict(rest=f'http://127.0.0.1:{port}', ws=str(self.ws_server.make_url('/ws/' + v)).replace('http:', 'ws:'))
                          for v in ('kalshi', 'polymarket_us')}
        return self

    async def __aexit__(self, *args):
        self.http_server.close()
        await self.http_server.wait_closed()
        for task in list(self.handlers):
            task.cancel()
        await asyncio.gather(*self.handlers, return_exceptions=True)
        await self.ws_server.close()

    async def http(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        try:
            request = await reader.readuntil(b'\r\n\r\n')
            lines = request.decode('ascii').split('\r\n')
            method, target, protocol = lines[0].split(' ')
            headers = dict(line.split(': ', 1) for line in lines[1:] if ': ' in line)
            assert method == 'GET' and protocol == 'HTTP/1.1'
            assert headers['Accept-Encoding'] == 'identity'
            source = 'kalshi' if target.startswith('/trade-api/') else 'polymarket_us'
            self.http_requests.append(dict(source=source, target=target, headers=headers))
            assert sum(r['source'] == source for r in self.http_requests) == 1
            if source == 'kalshi':
                assert urlsplit(target).path == '/trade-api/v2/events'
                assert parse_qs(urlsplit(target).query) == dict(tickers=['KXNHLGAME-26SEP30NYITOR'], with_milestones=['true'], with_nested_markets=['true'], limit=['1'])
                body = base64.b64decode(self.metadata['body_b64'])
                if self.scenario == 'both_terminal':
                    data = json.loads(body)
                    data['events'][0]['title'] = 'CONSTRUCTED changed event identity'
                    body = json.dumps(data).encode()
            else:
                assert target == '/v1/events/127804'
                body = self.us_body
            status = '200 OK'
            extra_headers = []
            if source == 'polymarket_us':
                if self.scenario == 'redirect':
                    status = '302 Found'
                    extra_headers = ['Location: https://provider.invalid/never-follow']
                elif self.scenario == 'unsupported_encoding':
                    extra_headers = ['Content-Encoding: gzip']
                elif self.scenario in ('secret_echo', 'secret_echo_html'):
                    extra_headers = ['Set-Cookie: ' + SECRET.decode(), 'X-API-Key: ' + SECRET.decode()]
                elif self.scenario == 'timeout':
                    await asyncio.sleep(10)
                    return
            chunked = source == 'polymarket_us' and self.scenario in ('chunked_large', 'wire_overflow')
            declared = len(body)
            if source == 'polymarket_us' and self.scenario == 'long_content_length':
                declared += 20
            elif source == 'polymarket_us' and self.scenario == 'short_content_length':
                declared -= 20
            elif source == 'polymarket_us' and self.scenario == 'valid_prefix_excess':
                body += b'CONSTRUCTED-SURPLUS-DELIVERY'
            framing = 'Transfer-Encoding: chunked' if chunked else f'Content-Length: {declared}'
            content_type = 'text/html' if source == 'polymarket_us' and self.scenario == 'secret_echo_html' else 'application/json'
            response = ('HTTP/1.1 ' + status + '\r\nContent-Type: ' + content_type + '\r\nConnection: close\r\n' + framing + '\r\n' + '\r\n'.join(extra_headers) + ('\r\n' if extra_headers else '') + '\r\n').encode()
            writer.write(response)
            if source == 'polymarket_us' and self.scenario in ('body_timeout', 'secret_echo_timeout'):
                writer.write(body[:60])
                await writer.drain()
                await asyncio.sleep(10)
                return
            if chunked:
                if self.scenario == 'wire_overflow':
                    for pos in range(0, len(body), 32768):
                        writer.write(b''.join(b'1\r\n' + bytes([byte]) + b'\r\n' for byte in body[pos:pos + 32768]))
                        await writer.drain()
                        await asyncio.sleep(.002)
                else:
                    for pos in range(0, len(body), 32768):
                        chunk = body[pos:pos + 32768]
                        writer.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                        await writer.drain()
                writer.write(b'0\r\n\r\n')
            else:
                writer.write(body)
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass  # An overflow/refusal closes this deliberately local control.
        finally:
            writer.close()
            await writer.wait_closed()
            self.handlers.discard(task)

    async def websocket(self, request):
        source = request.match_info['source']
        ws = web.WebSocketResponse(compress=False)
        await ws.prepare(request)
        message = await ws.receive()
        command = json.loads(message.data)
        self.ws_requests.append(dict(source=source, command=command))
        if source == 'kalshi':
            assert command['params']['market_tickers'] == ['KXNHLGAME-26SEP30NYITOR-NYI', 'KXNHLGAME-26SEP30NYITOR-TOR']
            for index, row in enumerate(self.frames):
                raw = base64.b64decode(row['body_b64'])
                self.frame_hashes.append(sha256(raw).hexdigest())
                if index == 0:
                    data = json.loads(raw)
                    data['id'] = command['id']  # Only the local acknowledgement request ID is rebound.
                    raw = json.dumps(data).encode()
                await ws.send_str(raw.decode())
                await asyncio.sleep(.004)
            self.kalshi_done.set()
        else:
            assert command['subscribe']['marketSlugs'] == ['aec-nhl-nyi-tor-2026-09-30']
            # No US books: engineering metadata cannot create provider prices.
        async for _ in ws:
            pass
        return ws


SCENARIOS = ('large_valid', 'realistic_nested_large', 'inventory_overflow', 'exact_boundary', 'exact_boundary_incompressible', 'entity_overflow', 'chunked_large',
             'wire_overflow', 'malformed', 'truncated', 'long_content_length', 'short_content_length', 'valid_prefix_excess',
             'unsupported_encoding', 'unexpected_envelope', 'redirect', 'timeout', 'body_timeout',
             'changed_terms', 'unknown_terms', 'structure_overflow', 'secret_echo',
             'secret_echo_html', 'secret_echo_overflow', 'secret_echo_timeout',
             'both_terminal', 'legacy_exact_boundary', 'legacy_overflow')
SUCCESS = {'large_valid', 'realistic_nested_large', 'exact_boundary', 'exact_boundary_incompressible', 'chunked_large', 'legacy_exact_boundary'}
EXPECTED_REASON = {
    'entity_overflow': 'native_entity_byte_cap',
    'both_terminal': 'native_entity_byte_cap',
    'unsupported_encoding': 'native_unsupported_encoding',
    'unexpected_envelope': 'native_unexpected_envelope',
    'redirect': 'native_http_redirect_refused',
    'timeout': 'native_http_timeout',
    'body_timeout': 'native_http_timeout',
    'wire_overflow': 'native_wire_byte_cap',
    'long_content_length': 'native_http_length_mismatch',
    'short_content_length': 'native_http_surplus_bytes',
    'valid_prefix_excess': 'native_http_surplus_bytes',
    'malformed': 'native_malformed_json',
    'truncated': 'native_incomplete_json',
    'changed_terms': 'changed_missing_unknown_or_conflicting_terms_require_review',
    'unknown_terms': 'changed_missing_unknown_or_conflicting_terms_require_review',
    'structure_overflow': 'native_json_structure_cap',
    'inventory_overflow': 'native_source_inventory_cap',
    'legacy_overflow': 'native_response_byte_cap',
    'secret_echo': 'native_credential_echo_suppressed',
    'secret_echo_html': 'native_credential_echo_suppressed',
    'secret_echo_overflow': 'native_entity_byte_cap',
    'secret_echo_timeout': 'native_http_timeout',
}


async def run(scenario='large_valid', output=None):
    from app.collection.native_payload import TRANSPORT_CONTRACT
    assert scenario in SCENARIOS
    runtime_before = implementation()
    temporary = tempfile.TemporaryDirectory(prefix='us-metadata-delivery-') if output is None else None
    folder = Path(temporary.name) if temporary else Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    network = dict(external_attempts=0, real_credentials=0)

    def allow_local(sock, address):
        if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1'):
            network['external_attempts'] += 1
            raise AssertionError('External networking denied in offline control')
        return original_connect(sock, address)

    def allow_local_ex(sock, address):
        if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1'):
            network['external_attempts'] += 1
            raise AssertionError('External networking denied in offline control')
        return original_connect_ex(sock, address)

    def deny_credentials(*args, **kwargs):
        network['real_credentials'] += 1
        raise AssertionError('Real credential access denied in offline control')

    try:
        with ExitStack() as stack:
            stack.enter_context(patch('socket.socket.connect', allow_local))
            stack.enter_context(patch('socket.socket.connect_ex', allow_local_ex))
            stack.enter_context(patch('app.collection.venue_access.load_credentials', deny_credentials))
            if scenario.startswith('secret_echo'):
                stack.enter_context(patch('app.collection.continuous.REST', EchoControlREST))
            for name in ('app.collection.run_spec.datetime', 'app.collection.transport_session.datetime', 'app.collection.continuous.datetime'):
                stack.enter_context(patch(name, OfflineClock))
            async with LocalProviderControls(scenario) as server:
                spec = json.loads((PACKAGE / 'run-spec.json').read_text())
                spec.update(mode='mock', start_after='2026-09-30T00:00:00Z', start_before='2026-09-30T23:23:30Z')
                if not scenario.startswith('legacy_'):
                    spec['native_transport'] = deepcopy(TRANSPORT_CONTRACT)
                owner = CoverageOwner(folder / 'saved', pilot_output=folder / 'sessions', product_mode=True,
                                      session_factory=OfflineSession, spec_factory=lambda: deepcopy(spec), endpoints=server.endpoints)
                async with TestClient(TestServer(create_app(owner=owner, sessions={}))) as client:
                    origin = {'Origin': str(client.make_url('')).rstrip('/')}
                    response = await client.post('/api/start', headers=origin, json={'duration': 90})
                    assert response.status == 200, (scenario, await response.text())
                    session = owner.session
                    session.emit('session', dict(type='offline_control_classification', classification=CLASSIFICATION,
                        historical_source_folder=str(ORIGINAL), synthetic_us_response_sha256=sha256(server.us_body).hexdigest(),
                        retrospective_clock=NOW.isoformat(), source_timestamps='unchanged retained Kalshi clocks',
                        acquisition_authority_remaining=False))
                    deadline = time.monotonic() + 12
                    while time.monotonic() < deadline:
                        if scenario == 'both_terminal' and session.cleanup_complete:
                            break
                        if session.discovery.completed and server.kalshi_done.is_set():
                            await asyncio.sleep(.3)
                            break
                        await asyncio.sleep(.05)
                    assert session.discovery.completed, (scenario, owner.error, session.reason, session.discovery.refresh)
                    if scenario == 'both_terminal':
                        assert session.cleanup_complete and session.reason == 'all_selected_sources_terminal_no_permitted_work'
                        assert time.monotonic() - started < 5
                        assert not server.ws_requests
                    else:
                        assert server.kalshi_done.is_set(), (scenario, session.discovery.source_stops)
                        assert not session.stop_event.is_set(), (scenario, session.reason)
                        assert (await client.post('/api/stop', headers=origin, json={})).status == 200
                    await owner.finalizer
                    assert owner.error is None, (scenario, owner.error)
                    assert session.cleanup_complete and not session.cleanup_errors
                    rows = list(verified(session.output)['rows'])
                    saved = load(session.output)
                    us = next(r for r in rows if r['type'] == 'prediction_discovery_http' and r['source'] == 'polymarket_us')
                    us_reason = session.discovery.source_stops.get('polymarket_us')
                    if scenario in SUCCESS:
                        assert us['complete'] and us['usable_metadata']
                        assert session.discovery.book_market_ids['polymarket_us'] == ['1061481']
                        assert len([r for r in rows if r['type'] == 'native_review']) == 2
                        assert us['body_sha256'] == sha256(server.us_body).hexdigest()
                        assert base64.b64decode(us['body_b64']) == server.us_body
                    else:
                        assert us_reason, (scenario, session.discovery.source_stops)
                        if scenario in EXPECTED_REASON:
                            assert us_reason == EXPECTED_REASON[scenario], (scenario, us_reason)
                        if us_reason.startswith('native_') and scenario != 'inventory_overflow':
                            assert us.get('delivery_reason') == us_reason, (scenario, us_reason, us.get('delivery_reason'))
                        assert session.discovery.book_market_ids['polymarket_us'] == []
                        assert not any(r['type'] == 'native_review' for r in rows)
                        assert not any(r.get('source') == 'polymarket_us' and r['type'] in ('prediction_command', 'prediction_book') for r in rows)
                        assert any(r['type'] == 'native_source_stopped' and r['source'] == 'polymarket_us' and r['reason'] == us_reason for r in rows)
                        assert session.discovery.inventory['polymarket_us']['source_error'] == us_reason
                        if not us['usable_metadata']:
                            assert session.discovery.inventory['polymarket_us']['events'] == []
                            assert session.discovery.inventory['polymarket_us']['markets'] == []
                    observation = summarize(rows)
                    if scenario != 'both_terminal':
                        assert server.frame_hashes == [r['body_sha256'] for r in server.frames]
                        replayed_frames = [r for r in rows if r['type'] == 'prediction_frame' and r['source'] == 'kalshi']
                        assert len(replayed_frames) == 55
                        assert [r['body_sha256'] for r in replayed_frames[1:]] == [r['body_sha256'] for r in server.frames[1:]]
                        original_ack = json.loads(base64.b64decode(server.frames[0]['body_b64']))
                        replayed_ack = json.loads(base64.b64decode(replayed_frames[0]['body_b64']))
                        original_ack.pop('id')
                        replayed_ack.pop('id')
                        assert original_ack == replayed_ack
                        accepted = observation['sources']['kalshi']['accepted']
                        assert accepted.get('initial_snapshot') == 2 and accepted.get('price_or_quantity_change') == 52, accepted
                    feed = await (await client.get('/api/dashboard', params={'view': 'feed', 'capture': session.sid})).json()
                    assert not feed['comparisons']
                    assert all(r.get('economics') is None for r in rows)
                    assert all(r['book']['raw']['kind'] == 'synthetic' for r in rows if r['type'] == 'prediction_book')
                    code = ('import json,socket,sys;from pathlib import Path;from unittest.mock import patch;'
                            'from app.dashboard.session_history import load,verified;from app.collection.native_approval import digest;'
                            '\nwith patch("socket.socket.connect",side_effect=AssertionError("network denied")),patch("socket.socket.connect_ex",side_effect=AssertionError("network denied")),patch("app.collection.venue_access.load_credentials",side_effect=AssertionError("credentials denied")):'
                            '\n p=Path(sys.argv[1]);rows=list(verified(p)["rows"]);print(json.dumps(dict(digest=digest(load(p)),stops={r["source"]:r["reason"] for r in rows if r["type"]=="native_source_stopped"})))')
                    fresh = json.loads(subprocess.check_output([sys.executable, '-c', code, str(session.output)], cwd=ROOT, text=True))
                    assert fresh['digest'] == digest(saved)
                    assert fresh['stops'] == session.discovery.source_stops
                    if scenario.startswith('secret_echo'):
                        assert us['body_b64'] == '' and not us['usable_metadata']
                        assert us['request_provenance'].get('redacted') is True
                        assert us['response_headers'] == [] and us['response_url'] == '<redacted>'
                        assert us.get('redaction_reason') == 'native_credential_echo_suppressed'
                        assert SECRET not in json.dumps(rows).encode()
                        for path in session.output.rglob('*'):
                            if path.is_file():
                                assert SECRET not in path.read_bytes() and base64.b64encode(SECRET) not in path.read_bytes(), path
                    assert network == dict(external_attempts=0, real_credentials=0)
                    assert implementation() == runtime_before, 'Runtime source changed during offline verification'
                    result = dict(scenario=scenario, classification=CLASSIFICATION,
                        production_http_reader=True, actual_loopback_tcp=True, intercepted_http_calls=False,
                        provider_requests=0, real_credentials=0, acquisition_package_created=False,
                        constructed_us_body_bytes=len(server.us_body), retained_us_body_bytes=len(base64.b64decode(us['body_b64'])),
                        us_complete=us['complete'], us_usable=us['usable_metadata'], us_failure_reason=us_reason,
                        us_metadata_admitted=bool(session.discovery.book_market_ids.get('polymarket_us')),
                        selected_us_market_ids=session.discovery.book_market_ids.get('polymarket_us', []),
                        transport_evidence={k: v for k, v in us.items() if k not in ('body_b64',)},
                        transport_policy=spec.get('native_transport'), historical_kalshi_folder=str(ORIGINAL),
                        original_kalshi_http_sha256=server.metadata['body_sha256'], retained_kalshi_wire_frames=len(server.frames),
                        kalshi_replayed_frames=len(server.frame_hashes), kalshi_observations=observation['sources'].get('kalshi'),
                        http_requests=server.http_requests, subscriptions=[r['source'] for r in server.ws_requests],
                        terminal_reason=session.reason, source_stops=session.discovery.source_stops,
                        resources=session.resources(), expanded_journal_bytes=session.journal.expanded_bytes,
                        storage_bytes=sum(p.stat().st_size for p in session.output.rglob('*') if p.is_file()),
                        accounting=session.accounting(), cleanup_complete=session.cleanup_complete,
                        fresh_process_digest=fresh['digest'], exact_fresh_reopening=True, paired_cards=0,
                        economics=None, output=str(session.output), seconds=time.monotonic()-started)
                    result['runtime_before_sha256'] = digest(runtime_before)
                    result['runtime_after_sha256'] = digest(implementation())
                    if not temporary:
                        (folder / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
                    return result
    finally:
        if temporary:
            temporary.cleanup()


async def main():
    run_folder = OUT / 'loopback-controls' / datetime.now(timezone.utc).strftime('%H%M%S%f')
    run_folder.mkdir(parents=True)
    runtime_before = implementation()
    (run_folder / 'source-before.json').write_text(json.dumps(runtime_before, indent=2) + '\n')
    results = []
    for scenario in SCENARIOS:
        try:
            result = await run_isolated(scenario, run_folder / scenario)
        except Exception as exc:
            (run_folder / 'verification-failure.json').write_text(json.dumps(dict(
                scenario=scenario, failure_class=type(exc).__name__, classification=CLASSIFICATION,
                finished_controls=results, incomplete_verifier=True), indent=2) + '\n')
            raise
        results.append(result)
        print(scenario + ' PASS ' + str(result['us_failure_reason']), flush=True)
    (run_folder / 'verification.json').write_text(json.dumps(results, indent=2) + '\n')
    runtime_after = implementation()
    assert runtime_after == runtime_before, 'Runtime source changed between offline controls'
    assert all(r['runtime_before_sha256'] == digest(runtime_before) and
               r['runtime_after_sha256'] == digest(runtime_before) for r in results)
    (run_folder / 'source-after.json').write_text(json.dumps(runtime_after, indent=2) + '\n')
    print('Retained engineering results: ' + str(run_folder), flush=True)


async def run_isolated(scenario, output=None):
    """Each finite owner is measured in its own process; peak RSS never resets."""
    temporary = tempfile.TemporaryDirectory(prefix='us-metadata-delivery-process-') if output is None else None
    folder = Path(temporary.name) if temporary else Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        process = await asyncio.create_subprocess_exec(sys.executable, '-m',
            'tests.us_metadata_delivery_rehearsal', '--scenario', scenario,
            '--output', str(folder), cwd=ROOT, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)
        stdout, _ = await asyncio.wait_for(process.communicate(), 30)
        assert process.returncode == 0, stdout.decode()
        return json.loads((folder / 'verification.json').read_text())
    finally:
        if temporary:
            temporary.cleanup()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=SCENARIOS)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.scenario:
        assert args.output
        result = asyncio.run(run(args.scenario, args.output))
        print(args.scenario + ' PASS ' + str(result['us_failure_reason']), flush=True)
    else:
        asyncio.run(main())
