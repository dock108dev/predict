"""Real production HTTP boundary over numeric loopback; no provider requests."""
import asyncio
import base64
from contextlib import asynccontextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import ssl
import tempfile
from datetime import datetime, timezone, timedelta
from ipaddress import ip_address
import unittest
from unittest.mock import patch

import aiohttp

from app.collection.native_payload import TRANSPORT_CONTRACT, parse
from app.collection.odds_http import BudgetStop
from app.collection.prediction_producer import MockREST, PredictionBudget

PATH = '/v1/events/127804'
LIMITS = dict(session_bytes=8*1024*1024, discovery_requests=8,
    dollar_cap_per_source='0', dollars_per_discovery_request='0',
    dollars_per_connection='0', frame_bytes=262144)
GOOD = b'{"event":{"id":"SIMULATED"}}'
RESULTS = []


def retain(name, row):
    RESULTS.append(dict(control=name, reason=row['delivery_reason'],
        complete=row['complete'], usable_metadata=row['usable_metadata'],
        redaction_reason=row.get('redaction_reason'),
        body_sha256=row['body_sha256'], resource_usage=row['resource_usage']))


def tearDownModule():
    destination = os.environ.get('NATIVE_HTTP_CONTROL_OUTPUT')
    if destination:
        Path(destination).write_text(json.dumps(dict(classification='synthetic local HTTP engineering controls',
            policy=TRANSPORT_CONTRACT, controls=RESULTS), indent=2)+'\n')


def fixed(body, *, headers=b'', length=None, status=b'200 OK'):
    length = len(body) if length is None else length
    return (b'HTTP/1.1 '+status+b'\r\nContent-Type: application/json\r\n'
        b'Content-Length: '+str(length).encode()+b'\r\nConnection: close\r\n'+headers+b'\r\n'+body)


def framed_exact(size):
    """Small valid entity, finite chunk extensions consume the plaintext budget."""
    body = b'{"event":{},"padding":"'+b'x'*(1024-25)+b'"}'
    assert len(body) == 1024
    headers = (b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
               b'Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n')
    padding = size-len(headers)-len(body)*9-5
    base, extra = divmod(padding, len(body))
    assert 0 < base+1 < 8190
    chunks = [b'1;x='+b'x'*(base+(i < extra))+b'\r\n'+bytes((char,))+b'\r\n'
              for i, char in enumerate(body)]
    raw = headers+b''.join(chunks)+b'0\r\n\r\n'
    assert len(raw) == size
    return raw, body


@asynccontextmanager
async def server(deliver, ssl_context=None):
    requests = []
    tasks = set()
    async def handle(reader, writer):
        task = asyncio.current_task();tasks.add(task)
        try:
            request = await reader.readuntil(b'\r\n\r\n')
            requests.append(request)
            await deliver(writer)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try: await writer.wait_closed()
            except ConnectionError: pass
            tasks.discard(task)
    listener = await asyncio.start_server(handle, '127.0.0.1', 0, ssl=ssl_context)
    endpoint = ('https' if ssl_context else 'http')+'://127.0.0.1:'+str(listener.sockets[0].getsockname()[1])
    try: yield endpoint, requests
    finally:
        listener.close();await listener.wait_closed()
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)


class Boundary(unittest.IsolatedAsyncioTestCase):
    async def request(self, wire, expected=None, *, timeout=1, credential=None):
        async def deliver(writer):
            # A sequence supplies deliberate chunk/packet scheduling controls.
            parts = wire if isinstance(wire, list) else [wire]
            for part in parts:
                writer.write(part);await writer.drain();await asyncio.sleep(0)
        async with server(deliver) as (endpoint, requests):
            rows = [];budget = PredictionBudget(LIMITS)
            client = MockREST(endpoint, LIMITS, rows.append, timeout, budget,
                              credential=credential)
            client.transport_policy = dict(TRANSPORT_CONTRACT)
            try:
                if expected:
                    with self.assertRaisesRegex(BudgetStop, '^'+expected+'$'):
                        await client.get(endpoint+PATH)
                else:
                    await client.get(endpoint+PATH)
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row['delivery_reason'], expected)
                self.assertEqual(budget.bytes, row['resource_usage']['wire_bytes'])
                self.assertEqual(row['http_plaintext_sha256'], sha256(b''.join(wire) if isinstance(wire, list) else wire).hexdigest())
                self.assertEqual(len(requests), 1)
                self.assertIn(b'Accept-Encoding: identity\r\n', requests[0])
                self.assertNotIn(b'Cookie:', requests[0])
                retain(self.id()+':'+str(expected)+':'+str(len(wire)), row)
                return row
            finally: await client.aclose()

    async def test_plaintext_exact_boundary_and_one_byte_excess(self):
        cap = TRANSPORT_CONTRACT['response_wire_bytes']
        wire, body = framed_exact(cap)
        row = await self.request(wire)
        self.assertTrue(row['complete']);self.assertTrue(row['usable_metadata'])
        self.assertEqual(row['resource_usage']['wire_bytes'], cap)
        self.assertEqual(base64.b64decode(row['body_b64']), body)
        wire, _ = framed_exact(cap+1)
        row = await self.request(wire, 'native_wire_byte_cap')
        self.assertFalse(row['complete']);self.assertFalse(row['usable_metadata'])
        self.assertEqual(row['resource_usage']['wire_bytes'], cap+1)
        self.assertLessEqual(row['resource_usage']['wire_max_callback_bytes'], 262144)

    async def test_entity_decoded_exact_and_overflow(self):
        cap = TRANSPORT_CONTRACT['response_decoded_bytes']
        body = b'{"event":{},"padding":"'+b'x'*(cap-25)+b'"}'
        row = await self.request(fixed(body))
        self.assertEqual(row['resource_usage']['decoded_bytes'], cap)
        self.assertLess(row['resource_usage']['parse_estimated_expansion_bytes'], 16*1024*1024)
        self.assertLess(row['resource_usage']['parse_object_bytes'], 16*1024*1024)
        row = await self.request(fixed(body+b' '), 'native_entity_byte_cap')
        self.assertEqual(len(base64.b64decode(row['body_b64'])), cap)
        self.assertEqual(row['resource_usage']['entity_bytes_read'], cap+1)
        self.assertFalse(row['complete'])

    async def test_json_controls(self):
        cases = [(b'{"event":{},"event":{}}', 'native_json_duplicate_key'),
                 (b'{"event":{},"x":NaN}', 'native_json_nonfinite'),
                 (b'{"event":{},"x":"\xff"}', 'native_invalid_utf8'),
                 (b'{"event":{}', 'native_incomplete_json'),
                 (b'{"event":oops}', 'native_malformed_json'),
                 (b'{"events":[]}', 'native_unexpected_envelope'),
                 (b'{"event":{},"x":'+b'['*33+b']'*33+b'}', 'native_json_depth_cap'),
                 (b'{"event":{},"x":['+b'0,'*100000+b'0]}', 'native_json_structure_cap'),
                 (b'{"event":{},"x":['+b'0,'*70000+b'0]}', 'native_parse_expansion_cap')]
        for body, reason in cases:
            with self.subTest(reason=reason):
                row = await self.request(fixed(body), reason)
                self.assertTrue(row['complete']);self.assertFalse(row['usable_metadata'])
                self.assertEqual(base64.b64decode(row['body_b64']), body)
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            parse(GOOD.decode().encode('utf-16-le'), limits=TRANSPORT_CONTRACT)

    async def test_response_headers_and_framing_controls(self):
        cases = [
            (fixed(GOOD, headers=b'X-Long: '+b'x'*9000+b'\r\n'), 'native_http_framing_error'),
            (fixed(GOOD, headers=b'Content-Length: '+str(len(GOOD)).encode()+b'\r\n'), 'native_http_framing_error'),
            (fixed(GOOD, headers=b'Transfer-Encoding: chunked\r\n'), 'native_http_framing_error'),
            (fixed(GOOD, length=len(GOOD)+1), 'native_http_length_mismatch'),
            (fixed(GOOD, length=len(GOOD)-5), 'native_http_surplus_bytes'),
            (b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 13\r\nConnection: close\r\n\r\n<h1>oops</h1>', 'native_unexpected_content_type'),
            (fixed(GOOD, headers=b'Content-Encoding: gzip\r\n'), 'native_unsupported_encoding'),
            (fixed(GOOD, headers=b'Content-Encoding: identity\r\nContent-Encoding: gzip\r\n'), 'native_unsupported_encoding'),
            (fixed(GOOD, headers=b'Content-Type: text/html\r\n'), 'native_unexpected_content_type'),
            (fixed(GOOD, status=b'302 Found', headers=b'Location: https://outside.invalid/\r\n'), 'native_http_redirect_refused'),
            (b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n'+hex(len(GOOD))[2:].encode()+b'\r\n'+GOOD+b'\r\n', 'native_http_framing_error'),
        ]
        for wire, reason in cases:
            with self.subTest(reason=reason):
                row = await self.request(wire, reason)
                self.assertFalse(row['usable_metadata'])

    async def test_repeated_source_plaintext_cap(self):
        wire, _ = framed_exact(4*1024*1024)
        async def deliver(writer):
            writer.write(wire);await writer.drain()
        async with server(deliver) as (endpoint, requests):
            rows=[];budget=PredictionBudget(LIMITS)
            client=MockREST(endpoint,LIMITS,rows.append,2,budget)
            client.transport_policy=dict(TRANSPORT_CONTRACT)
            try:
                await client.get(endpoint+PATH)
                with self.assertRaisesRegex(BudgetStop,'^native_discovery_wire_byte_cap$'):
                    await client.get(endpoint+PATH)
                self.assertEqual(len(requests),2)
                self.assertLessEqual(client.http_wire_bytes,TRANSPORT_CONTRACT['discovery_wire_bytes'])
                self.assertEqual(budget.bytes,client.http_wire_bytes)
                self.assertFalse(rows[-1]['usable_metadata'])
                retain(self.id()+':complete',rows[0]);retain(self.id()+':overflow',rows[1])
            finally:await client.aclose()

    async def test_tls_plaintext_buffer_wire_limits_and_delayed_surplus(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        # Disposable loopback-only key/cert; production TLS verification stays
        # untouched. The test connector trusts only this generated certificate.
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'SIMULATED loopback HTTP control')])
        at=datetime.now(timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(at-timedelta(minutes=1)).not_valid_after(at+timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address('127.0.0.1'))]),critical=False)
            .sign(key,hashes.SHA256()))
        with tempfile.TemporaryDirectory() as temporary:
            cert_path=Path(temporary)/'local-cert.pem';key_path=Path(temporary)/'local-key.pem'
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_context.load_cert_chain(cert_path,key_path)
            client_context=ssl.create_default_context(cafile=str(cert_path))
            real_connector=aiohttp.TCPConnector
            def connector(**kwargs):return real_connector(ssl=client_context,**kwargs)
            cap=TRANSPORT_CONTRACT['response_wire_bytes']
            for kind in ('entity','wire_exact','wire_overflow','surplus_delayed'):
                if kind=='entity':
                    body=b'{"event":{},"padding":"'+b'x'*(TRANSPORT_CONTRACT['response_entity_bytes']-25)+b'"}'
                    wire=fixed(body);reason=None
                elif kind.startswith('wire'):
                    wire,body=framed_exact(cap+(kind=='wire_overflow'))
                    reason='native_wire_byte_cap' if kind=='wire_overflow' else None
                else:
                    wire=fixed(GOOD);body=GOOD;reason='native_http_surplus_bytes'
                async def deliver(writer):
                    # A single server write forces the client TLS protocol to
                    # handle a large pending plaintext burst with its buffer.
                    writer.write(wire);await writer.drain()
                    if kind=='surplus_delayed':
                        await asyncio.sleep(.02);writer.write(b'TLS-SURPLUS');await writer.drain()
                async with server(deliver,server_context) as (endpoint,_):
                    rows=[];budget=PredictionBudget(LIMITS)
                    with patch('app.collection.prediction_producer.mock_endpoint',side_effect=lambda value:value),patch('app.collection.prediction_producer.aiohttp.TCPConnector',side_effect=connector):
                        client=MockREST(endpoint,LIMITS,rows.append,3,budget)
                        client.transport_policy=dict(TRANSPORT_CONTRACT)
                        try:
                            if reason:
                                with self.assertRaisesRegex(BudgetStop,'^'+reason+'$'):await client.get(endpoint+PATH)
                            else:await client.get(endpoint+PATH)
                            row=rows[0]
                            self.assertEqual(row['delivery_reason'],reason)
                            self.assertEqual(row['usable_metadata'],reason is None)
                            self.assertEqual(row['resource_usage']['plaintext_read_mode'],'TLS BufferedProtocol')
                            self.assertLessEqual(row['resource_usage']['wire_max_callback_bytes'],262144)
                            self.assertEqual(budget.bytes,row['resource_usage']['wire_bytes'])
                            self.assertEqual(row['resource_usage']['wire_bytes'],len(wire)+(len(b'TLS-SURPLUS') if kind=='surplus_delayed' else 0))
                            retain(self.id()+':'+kind,row)
                        finally:await client.aclose()

    async def test_timeout_and_cancellation_exact_charges(self):
        head=b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 200\r\n\r\n'
        ready=asyncio.Event()
        async def deliver(writer):
            writer.write(head+GOOD);await writer.drain();ready.set();await asyncio.sleep(2)
        for cancel in (False,True):
            with self.subTest(cancel=cancel):
                async with server(deliver) as (endpoint,_):
                    rows=[];budget=PredictionBudget(LIMITS)
                    client=MockREST(endpoint,LIMITS,rows.append,.1 if not cancel else 1,budget)
                    client.transport_policy=dict(TRANSPORT_CONTRACT)
                    try:
                        task=asyncio.create_task(client.get(endpoint+PATH))
                        await ready.wait();await asyncio.sleep(.01)
                        if cancel:
                            task.cancel()
                            with self.assertRaises(asyncio.CancelledError):await task
                        else:
                            with self.assertRaisesRegex(BudgetStop,'^native_http_timeout$'):await task
                        row=rows[0]
                        self.assertEqual(row['delivery_reason'],'native_http_cancelled' if cancel else 'native_http_timeout')
                        self.assertEqual(budget.bytes,len(head)+len(GOOD))
                        self.assertEqual(row['resource_usage']['entity_bytes_read'],len(GOOD))
                        self.assertFalse(row['complete']);self.assertFalse(row['usable_metadata'])
                        retain(self.id()+':cancel='+str(cancel),row)
                    finally:await client.aclose();ready.clear()

    async def test_header_only_credential_echo_suppressed_before_return(self):
        secret=b'SIMULATED-SECRET-HEADER-DO-NOT-SAVE'
        class Credential:
            def check(self,raw,headers=None):
                if secret in raw:raise ValueError('credential echo suppressed')
        wire=fixed(GOOD,headers=b'X-Request-ID: '+secret+b'\r\n')
        row=await self.request(wire,'native_credential_echo_suppressed',credential=Credential())
        self.assertFalse(row['usable_metadata'])
        self.assertEqual(base64.b64decode(row['body_b64']),b'')
        self.assertNotIn(secret,json.dumps(row).encode())

    async def test_observed_and_delayed_surplus_never_admitted(self):
        for chunked in (False, True):
            for delayed in (False, True):
                with self.subTest(chunked=chunked,delayed=delayed):
                    if chunked:
                        complete=(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                            b'Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n'+
                            hex(len(GOOD))[2:].encode()+b'\r\n'+GOOD+b'\r\n0\r\n\r\n')
                    else:complete=fixed(GOOD)
                    async def deliver(writer):
                        writer.write(complete)
                        if delayed:
                            await writer.drain();await asyncio.sleep(.02)
                        writer.write(b'UNEXPECTED-SURPLUS');await writer.drain()
                    async with server(deliver) as (endpoint,_):
                        rows=[];budget=PredictionBudget(LIMITS)
                        client=MockREST(endpoint,LIMITS,rows.append,1,budget)
                        client.transport_policy=dict(TRANSPORT_CONTRACT)
                        try:
                            with self.assertRaisesRegex(BudgetStop,'^native_http_surplus_bytes$'):
                                await client.get(endpoint+PATH)
                            self.assertFalse(rows[0]['complete']);self.assertFalse(rows[0]['usable_metadata'])
                            self.assertEqual(budget.bytes,len(complete)+len(b'UNEXPECTED-SURPLUS'))
                            retain(self.id()+':chunked='+str(chunked)+':delayed='+str(delayed),rows[0])
                        finally:await client.aclose()

    async def test_full_and_partial_body_echo_preserves_precise_reason(self):
        secret=b'SIMULATED-SECRET-BODY-DO-NOT-SAVE'
        class Credential:
            def check(self,raw,headers=None):
                if secret in raw:raise ValueError('credential echo suppressed')
        row=await self.request(fixed(b'<html>'+secret+b'</html>').replace(
            b'Content-Type: application/json',b'Content-Type: text/html'),
            'native_credential_echo_suppressed',credential=Credential())
        self.assertNotIn(secret,json.dumps(row).encode())
        partial=b'{"event":{},"padding":"'+secret+b'x'*TRANSPORT_CONTRACT['response_entity_bytes']
        row=await self.request(fixed(partial),'native_entity_byte_cap',credential=Credential())
        self.assertEqual(row['redaction_reason'],'native_credential_echo_suppressed')
        self.assertEqual(base64.b64decode(row['body_b64']),b'')
        self.assertNotIn(secret,json.dumps(row).encode())

        head=b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 1000\r\n\r\n'
        async def deliver(writer):
            writer.write(head+secret);await writer.drain();await asyncio.sleep(2)
        async with server(deliver) as (endpoint,_):
            rows=[];budget=PredictionBudget(LIMITS)
            client=MockREST(endpoint,LIMITS,rows.append,.1,budget,credential=Credential())
            client.transport_policy=dict(TRANSPORT_CONTRACT)
            try:
                with self.assertRaisesRegex(BudgetStop,'^native_http_timeout$'):
                    await client.get(endpoint+PATH)
                self.assertEqual(rows[0]['delivery_reason'],'native_http_timeout')
                self.assertEqual(rows[0]['redaction_reason'],'native_credential_echo_suppressed')
                self.assertEqual(base64.b64decode(rows[0]['body_b64']),b'')
                self.assertNotIn(secret,json.dumps(rows[0]).encode())
                retain(self.id()+':timeout',rows[0])
            finally:await client.aclose()


if __name__=='__main__':unittest.main()
