"""Exact packaged control/owned-server path, actual local production HTTP reader.

All bodies are constructed complete controls from reviewed complete objects.
No provider data, credentials, historical books or paired comparisons are used.
The final package is never activated by this harness.
"""
import base64
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import socketserver
import subprocess
import sys
import threading
import time
import uuid

from app.collection.native_approval import digest, implementation
from app.dashboard.session_history import load, verified

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'evidence/us-metadata-diagnostic-preparation-20260930-v1'
CLASSIFICATION = ('SYNTHETIC COMPLETE ENGINEERING CONTROL: unchanged reviewed complete '
                  'US objects in a constructed envelope; only loopback delivery. '
                  'No provider authority, credentials, books or paired comparisons.')


def control_body(scenario):
    if scenario == 'catalog_overflow':
        from tests.us_metadata_delivery_rehearsal import body_for
        return body_for('inventory_overflow')
    old = json.loads((ROOT/'evidence/native-nyi-tor-20260930-v3/run-spec.json').read_text())
    event = deepcopy(old['native_review_records'][0]['sources']['polymarket_us']['catalog_evidence']['event']['native_metadata'])
    if scenario == 'closed':
        event['closed'] = True
        event['active'] = False
        event['markets'][0]['closed'] = True
        event['markets'][0]['active'] = False
    if scenario == 'changed_terms':
        event['markets'][0]['description'] += ' CONSTRUCTED altered settlement term.'
    if scenario == 'unexpected_envelope':
        return json.dumps({'events': [event]}).encode()
    if scenario == 'malformed':
        return b'{"event":INVALID}'
    if scenario == 'truncated':
        return b'{"event":{"id":"127804"'
    envelope = {'event': event, 'constructed_engineering_padding': ''}
    raw = json.dumps(envelope, separators=(',', ':')).encode()
    size = 2*1024*1024+(scenario == 'overflow') if scenario in ('boundary', 'overflow') else 700*1024
    envelope['constructed_engineering_padding'] = 'x'*(size-len(raw))
    raw = json.dumps(envelope, separators=(',', ':')).encode()
    assert len(raw) == size
    return raw


class LocalHTTP(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(3)
        request = bytearray()
        while b'\r\n\r\n' not in request and len(request) < 16384:
            part = self.request.recv(4096)
            if not part:
                break
            request.extend(part)
        self.server.requests.append(bytes(request))
        assert bytes(request).startswith(b'GET /v1/events/127804 HTTP/1.1\r\n')
        assert b'Accept-Encoding: identity\r\n' in request
        assert b'Connection: close\r\n' in request
        assert b'Authorization:' not in request and b'Cookie:' not in request
        scenario = self.server.scenario
        if scenario == 'timeout':
            time.sleep(6)
            return
        raw = control_body(scenario)
        status = b'302 Found' if scenario == 'redirect' else b'200 OK'
        extra = b'Location: https://gateway.polymarket.us/v1/events/127804\r\n' if scenario == 'redirect' else b''
        headers = (b'HTTP/1.1 '+status+b'\r\nContent-Type: application/json\r\n'
                   b'Content-Length: '+str(len(raw)).encode()+b'\r\nConnection: close\r\n'
                   b'X-Request-ID: constructed-offline-control\r\n'+extra+b'\r\n')
        try:
            self.request.sendall(headers+raw)
        except (BrokenPipeError, ConnectionResetError):
            pass


def fixture_source(endpoint, audit):
    # Only endpoint configuration is redirected. MockREST.get, aiohttp reader,
    # framing, parser, semantic review, journal and replay stay production code.
    return f'''import json,socket
from pathlib import Path
AUDIT=Path({str(audit)!r})
def record(value):
 with AUDIT.open('a') as f:f.write(json.dumps(value)+'\\n')
original_connect=socket.socket.connect
def local_connect(sock,address):
 if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1'):
  record(dict(forbidden_network=str(address)));raise RuntimeError('OFFLINE external network denied')
 record(dict(loopback_connect=list(address)));return original_connect(sock,address)
socket.socket.connect=local_connect
original_connect_ex=socket.socket.connect_ex
def local_connect_ex(sock,address):
 if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1'):
  record(dict(forbidden_network=str(address)));raise RuntimeError('OFFLINE external network denied')
 return original_connect_ex(sock,address)
socket.socket.connect_ex=local_connect_ex
from app.collection import continuous,venue_access,native_product,prediction_producer
ENDPOINT={endpoint!r}
def endpoints_for(session):
 assert session.spec['native_discovery']['slice']=='us-event-delivery-diagnostic-v1'
 return {{**venue_access.ENDPOINTS,'polymarket_us':dict(rest=ENDPOINT,ws='ws://127.0.0.1:1/FORBIDDEN')}}
continuous.endpoints_for=endpoints_for
def endpoint(venue,kind,value):
 assert venue=='polymarket_us' and kind=='rest' and value==ENDPOINT
 return value
venue_access.endpoint=endpoint
def forbidden(*a,**kw):
 record(dict(forbidden_credentials_or_socket=True));raise RuntimeError('OFFLINE credentials/books prohibited')
venue_access.load_credentials=forbidden
native_product.load_native_secret=forbidden
prediction_producer.connect=forbidden
'''


def builder():
    path = ROOT/'scripts/us_metadata_package/build.py'
    spec = importlib.util.spec_from_file_location('us_metadata_builder', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(scenario):
    folder = OUT/'owned-server-controls'/(scenario+'-'+str(time.time_ns()))
    folder.mkdir(parents=True)
    package = ROOT/'evidence'/('OFFLINE-us-metadata-diagnostic-package-'+str(uuid.uuid4()))
    ident = builder().build(package, offline=True)
    assert ident['implementation_sha256'] == digest(implementation())
    fixture = folder/'fixture'
    fixture.mkdir()
    audit = folder/'offline-boundary-audit.jsonl'
    with LocalHTTP(('127.0.0.1', 0), Handler) as server:
        server.scenario = scenario
        server.requests = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = 'http://127.0.0.1:'+str(server.server_address[1])
        (fixture/'sitecustomize.py').write_text(fixture_source(endpoint, audit))
        env = dict(os.environ)
        env['PYTHONPATH'] = str(fixture)+os.pathsep+str(ROOT)
        started = time.monotonic()
        try:
            result = subprocess.run([sys.executable, str(package/'supervise.py')], cwd=ROOT,
                                    env=env, capture_output=True, text=True, timeout=35)
        finally:
            server.shutdown()
            thread.join(timeout=2)
        elapsed = time.monotonic()-started
        (folder/'supervisor-stdout.txt').write_text(result.stdout)
        (folder/'supervisor-stderr.txt').write_text(result.stderr)
        assert result.returncode == 0, result.stderr+result.stdout
        assert len(server.requests) == 1, len(server.requests)
        (folder/'request.bin').write_bytes(server.requests[0])
    supervisor = json.loads((package/'supervisor-result.json').read_text())
    assert supervisor['owned_server_closed'] and not supervisor.get('cleanup_status_unsettled')
    assert (package/'activation.json').exists() and (package/'start-dispatch.json').exists()
    output = Path(ident['output'])
    assert (output/'b3-attempt.json').exists()
    sessions = [p.parent for p in output.glob('*/manifest.json')]
    assert len(sessions) == 1, list(output.iterdir())
    session = sessions[0]
    rows = list(verified(session)['rows'])
    receipts = [r for r in rows if r['type']=='prediction_discovery_http']
    assert len(receipts) == 1 and receipts[0]['source']=='polymarket_us'
    assert not [r for r in rows if r['type'] in ('prediction_frame','prediction_book','native_review')]
    reports = [r for r in rows if r['type']=='us_metadata_delivery_diagnostic']
    assert len(reports) == 1
    diagnostic = reports[0]
    if scenario in ('overflow','timeout'):
        assert diagnostic['delivery']['transport_complete'] is False
        assert diagnostic['json']['whole_document_valid'] is None
        assert diagnostic['target_identity']['agrees'] is None
    else:
        assert diagnostic['delivery']['transport_complete'] is True
    if scenario in ('malformed','truncated'):
        assert diagnostic['json']['whole_document_valid'] is False
        assert diagnostic['target_identity']['agrees'] is None
    if scenario == 'unexpected_envelope':
        assert diagnostic['json']['whole_document_valid'] is True
        assert diagnostic['json']['expected_envelope_valid'] is False
        assert diagnostic['target_identity']['agrees'] is None
    if scenario == 'redirect':
        assert diagnostic['metadata_admission']['admitted'] is False
        assert diagnostic['target_identity']['agrees'] is None
    if scenario in ('closed','boundary','changed_terms'):
        assert diagnostic['json']['whole_document_valid'] is True
        assert diagnostic['target_identity']['agrees'] is True
    if scenario == 'closed':
        assert diagnostic['material_terms']['event_agrees'] is True
        assert diagnostic['material_terms']['market_agrees'] is True
        assert diagnostic['pregame_eligibility']['eligible'] is False
    if scenario == 'changed_terms':
        assert diagnostic['material_terms']['market_agrees'] is False
        assert diagnostic['pregame_eligibility']['eligible'] is False
    if scenario == 'catalog_overflow':
        assert diagnostic['json']['whole_document_valid'] is True
        assert diagnostic['metadata_admission']['reason'] == 'native_source_inventory_cap'
        assert diagnostic['target_identity']['agrees'] is None
    report = json.loads((session/'report.json').read_text())
    assert report['cleanup_complete'] and report['journal_state']=='complete'
    # Ordinary resource/health snapshots are retained; no native book frames
    # or price observations may enter the diagnostic.
    assert not [r for r in rows if r['type']=='prediction_book']
    value = load(session)
    code = ('import sys,json;from pathlib import Path;from app.dashboard.session_history import load,verified;'
            'from app.collection.native_approval import digest;from app.collection.us_metadata_diagnostic import verify;'
            'p=Path(sys.argv[1]);print(json.dumps(dict(projection_sha256=digest(load(p)),diagnostic=verify(list(verified(p)["rows"])))))')
    fresh_result = json.loads(subprocess.check_output([sys.executable, '-c', code, str(session)], cwd=ROOT, text=True))
    fresh = fresh_result['projection_sha256']
    assert fresh == digest(value)
    replay = json.loads((session/'replay.json').read_text())
    assert fresh_result['diagnostic'] == replay['us_metadata_diagnostic']
    audit_rows = [json.loads(line) for line in audit.read_text().splitlines()]
    assert not any('forbidden_network' in r or 'forbidden_credentials_or_socket' in r for r in audit_rows)
    try:
        import socket
        with socket.create_connection(('127.0.0.1',8831),timeout=.3):
            raise AssertionError('owned server still open')
    except ConnectionRefusedError:
        pass
    check = subprocess.run([sys.executable,str(package/'launch.py')],cwd=ROOT,capture_output=True,text=True)
    assert check.returncode != 0 and 'consumed' in (check.stdout+check.stderr).lower()
    receipt = receipts[0]
    summary = dict(scenario=scenario,classification=CLASSIFICATION,implementation_sha256=ident['implementation_sha256'],
                   spec_sha256=ident['spec_sha256'],attempt_id=ident['attempt_id'],package=str(package),output=str(session),
                   owned_server_control_elapsed_seconds=elapsed,provider_requests=0,credentials=0,
                   local_http_requests=1,kalshi_requests=0,book_connections=0,activation_dispatch_consumption=True,
                   owned_server_closed=True,port_closed=True,terminal_completion=True,cleanup=True,
                   consumed_reuse_rejected=True,fresh_process_sha256=fresh,exact_fresh_reopening=True,
                   fresh_process_diagnostic=fresh_result['diagnostic'],
                   diagnostic=reports[0],receipt_summary={k:receipt.get(k) for k in ('complete','wire_complete','usable_metadata','delivery_reason','resource_usage')},
                   resources=report['resources'],accounting=report['accounting'],collection_seconds=report['collection_seconds'])
    (folder/'verification.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(dict(scenario=scenario,status='PASS',elapsed_seconds=elapsed,output=str(session))),flush=True)
    return summary


if __name__=='__main__':
    run(sys.argv[1] if len(sys.argv)>1 else 'closed')
