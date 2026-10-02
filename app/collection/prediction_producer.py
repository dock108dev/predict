"""Native prediction adapters and stream engines owned by E6, never old controller."""
import asyncio
import sys
from app.diagnostics import failure
import base64
from dataclasses import asdict, replace
from hashlib import sha256
from decimal import Decimal
import json
import inspect
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import aiohttp
import httpx
from websockets.asyncio.client import connect
from app.adapters.kalshi import KalshiAdapter
from app.adapters.polymarket_us import PolymarketUSAdapter
from app.adapters.kalshi_stream import MarketStream as KStream
from app.adapters.polymarket_us_stream import MarketStream as PStream
from app.models.core import EvidenceKind
from .odds_http import mock_endpoint, utc, BudgetStop
from .run_spec import time_value
from .prediction_discovery import NFLPolymarketAdapter,validate_pregame


_SECRET_NAME = re.compile(r'key|secret|token|signature|authorization|cookie|password', re.I)
_RESPONSE_HEADERS = {'content-type', 'content-length', 'content-encoding',
    'transfer-encoding', 'date', 'server', 'retry-after', 'via', 'location',
    'connection', 'cf-cache-status', 'x-request-id', 'request-id', 'cf-ray'}


def _safe_url(value):
    """URLs are provenance, not an alternate credential persistence channel."""
    parts = urlsplit(str(value))
    host = parts.hostname or ''
    if ':' in host: host = '['+host+']'
    if parts.port: host += ':'+str(parts.port)
    values = parse_qsl(parts.query, keep_blank_values=True)
    query = (urlencode([(k, '<redacted>' if _SECRET_NAME.search(k) else v)
                       for k, v in values])
             if any(_SECRET_NAME.search(k) for k, _ in values) else parts.query)
    return urlunsplit((parts.scheme, host, parts.path, query, ''))


def _safe_headers(headers, *, response=False):
    result = []
    for key, value in headers.items():
        lower = key.lower()
        if _SECRET_NAME.search(lower):
            # Names demonstrate signing without persisting secret values.
            if not response: result.append([key, '<redacted>'])
        elif not response or lower in _RESPONSE_HEADERS:
            result.append([key, _safe_url(value) if lower == 'location' else value])
    return result


def _safe_params(query):
    if isinstance(query, str):
        values = parse_qsl(query, keep_blank_values=True)
        if not any(_SECRET_NAME.search(k) for k, _ in values): return query
        return urlencode([(k, '<redacted>' if _SECRET_NAME.search(k) else v) for k, v in values])
    if hasattr(query, 'items'):
        return {k: '<redacted>' if _SECRET_NAME.search(str(k)) else v for k, v in query.items()}
    return [[k, '<redacted>' if _SECRET_NAME.search(str(k)) else v] for k, v in query]


def _transport_capability(callback_bytes):
    """The verified private aiohttp hook must fail closed after incompatible drift."""
    from aiohttp.client_proto import ResponseHandler
    from asyncio.selector_events import _SelectorSocketTransport
    from asyncio.sslproto import SSLProtocol
    if (not aiohttp.__version__.startswith('3.14.') or
        'max_headers' not in inspect.signature(aiohttp.ClientSession).parameters or
        not callable(getattr(ResponseHandler, 'data_received', None)) or
        not callable(getattr(_SelectorSocketTransport, '_read_ready__get_buffer', None)) or
        not callable(getattr(SSLProtocol, '_do_read__buffered', None)) or
        type(callback_bytes) is not int or not 0 < callback_bytes <= 256*1024):
        raise BudgetStop('native_http_transport_capability_unverified')


class _HTTPFraming:
    """Bounded HTTP/1 response scanner, independent of JSON and aiohttp EOF.

    aiohttp may ignore bytes after an already completed Content-Length body.
    This scanner accounts for the entire observed plaintext message, including
    chunk extensions/trailers, and rejects any surplus. It stores at most 64
    bounded header lines and one bounded framing line, never a body copy.
    """
    def __init__(self):
        self.phase = 'headers'
        self.line = bytearray()
        self.headers = []
        self.header_bytes = self.trailer_count = self.entity_bytes = 0
        self.status = None
        self.remaining = 0

    def _header_line(self, line):
        if self.status is None:
            match = re.match(rb'^HTTP/1\.[01] ([0-9]{3})(?: |$)', line)
            if match is None: raise BudgetStop('native_http_framing_error')
            self.status = int(match.group(1))
            if self.status < 200: raise BudgetStop('native_http_informational_refused')
        elif line:
            if len(self.headers) >= 64 or b':' not in line:
                raise BudgetStop('native_http_framing_error')
            key, value = line.split(b':', 1)
            if not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key):
                raise BudgetStop('native_http_framing_error')
            self.headers.append((key.lower(), value.strip()))
        else:
            lengths = [v for k, v in self.headers if k == b'content-length']
            transfers = [v.lower() for k, v in self.headers if k == b'transfer-encoding']
            if (len(lengths) > 1 or len(transfers) > 1 or (lengths and transfers)
                or lengths and not re.fullmatch(rb'[0-9]{1,20}', lengths[0])):
                raise BudgetStop('native_http_framing_error')
            if self.status in (204, 304): self.phase = 'done'
            elif transfers:
                if transfers != [b'chunked']:
                    raise BudgetStop('native_unsupported_transfer_encoding')
                self.phase = 'chunk_size'
            elif lengths:
                self.remaining = int(lengths[0])
                self.phase = 'fixed' if self.remaining else 'done'
            else: self.phase = 'close'
            self.headers.clear()

    def feed(self, data):
        position = 0
        while position < len(data):
            if self.phase == 'done': raise BudgetStop('native_http_surplus_bytes')
            if self.phase == 'close':
                self.entity_bytes += len(data)-position
                return
            if self.phase in ('fixed', 'chunk_data'):
                take = min(self.remaining, len(data)-position)
                self.entity_bytes += take
                self.remaining -= take
                position += take
                if self.remaining == 0:
                    self.phase = 'done' if self.phase == 'fixed' else 'chunk_crlf'
                continue
            if self.phase == 'chunk_crlf':
                take = min(2-len(self.line), len(data)-position)
                self.line.extend(data[position:position+take]);position += take
                if len(self.line) == 2:
                    if self.line != b'\r\n': raise BudgetStop('native_http_framing_error')
                    self.line.clear();self.phase = 'chunk_size'
                continue
            end = data.find(b'\n', position)
            stop = len(data) if end == -1 else end+1
            if len(self.line)+stop-position > 8190:
                raise BudgetStop('native_http_framing_error')
            self.line.extend(data[position:stop])
            if self.phase == 'headers': self.header_bytes += stop-position
            position = stop
            if end == -1: return
            if not self.line.endswith(b'\r\n'): raise BudgetStop('native_http_framing_error')
            line = bytes(self.line[:-2]);self.line.clear()
            if self.phase == 'headers': self._header_line(line)
            elif self.phase == 'chunk_size':
                size = line.split(b';', 1)[0]
                if not re.fullmatch(rb'[0-9A-Fa-f]{1,16}', size):
                    raise BudgetStop('native_http_framing_error')
                self.remaining = int(size, 16)
                self.phase = 'chunk_data' if self.remaining else 'trailers'
            elif self.phase == 'trailers':
                if not line: self.phase = 'done'
                else:
                    self.trailer_count += 1
                    if self.trailer_count > 64 or b':' not in line:
                        raise BudgetStop('native_http_framing_error')
                    key = line.split(b':', 1)[0]
                    if (not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key)
                        or key.lower() in (b'content-length', b'transfer-encoding')):
                        raise BudgetStop('native_http_framing_error')

    def eof(self):
        if self.phase == 'close': self.phase = 'done'
        if self.phase != 'done':
            raise BudgetStop('native_http_length_mismatch' if self.phase == 'fixed'
                             else 'native_http_framing_error')


class _StrictCloseResponse(aiohttp.ClientResponse):
    def _response_eof(self):
        # Content EOF is not permission to silently drop later TCP callbacks.
        # The v2 reader awaits actual peer close before context-manager release.
        self._native_payload_eof = True


def _bounded_connector(owner, callback_bytes):
    """Count HTTP plaintext before aiohttp strips framing or buffers the entity.

    An admitted response fits the wire cap. The violating callback is counted,
    charged and rejected before parsing, with a separate finite read-ahead bound.
    This does not claim to count encrypted TLS records or IP/TCP traffic.
    """
    from aiohttp.client_proto import ResponseHandler
    _transport_capability(callback_bytes)

    class CountedResponse(ResponseHandler, asyncio.BufferedProtocol):
        def __init__(self, *, loop, state):
            super().__init__(loop)
            self.wire_state = state
            # BufferedProtocol also directs TLS decryption into this fixed
            # buffer; SSLProtocol's copied path can otherwise join many reads.
            self.ingress_buffer = bytearray(callback_bytes)

        def get_buffer(self, sizehint):
            return memoryview(self.ingress_buffer)

        def buffer_updated(self, nbytes):
            if type(nbytes) is not int or not 0 <= nbytes <= len(self.ingress_buffer):
                self._reject('native_http_transport_capability_unverified')
                return
            self.data_received(bytes(memoryview(self.ingress_buffer)[:nbytes]))

        def connection_made(self, transport):
            super().connection_made(transport)
            ssl_protocol = getattr(transport, '_ssl_protocol', None)
            if ssl_protocol is not None:
                supported = (getattr(ssl_protocol, '_app_protocol_is_buffer', False) is True
                             and getattr(ssl_protocol, '_app_protocol', None) is self)
                mode = 'TLS BufferedProtocol'
            else:
                from asyncio.selector_events import _SelectorSocketTransport
                supported = (getattr(getattr(transport, '_read_ready_cb', None), '__func__', None)
                             is _SelectorSocketTransport._read_ready__get_buffer)
                mode = 'TCP BufferedProtocol'
            self.wire_state['read_mode'] = mode
            if not supported:
                self._reject('native_http_transport_capability_unverified')

        def _reject(self, reason):
            self.wire_state['reason'] = reason
            exc = BudgetStop(reason)
            if self._payload is not None:
                self._payload.set_exception(exc)
            self.set_exception(exc)
            if self.transport is not None: self.transport.abort()

        def connection_lost(self, exc):
            state = self.wire_state
            if state['reason'] is None:
                try: state['framing'].eof()
                except BudgetStop as error: state['reason'] = str(error)
            if exc is not None and state['reason'] is None:
                state['reason'] = 'native_http_transport_error'
            try: super().connection_lost(exc)
            finally:
                if not state['closed'].done(): state['closed'].set_result(True)

        def data_received(self, data):
            # aiohttp can recursively feed an already received upgrade tail.
            # It is plaintext from the same callback, not another arrival.
            if getattr(self, '_processing_wire', False):
                super().data_received(data)
                return
            state = self.wire_state
            state['received'] += len(data)
            state['sha256'].update(data)
            state['max_callback'] = max(state['max_callback'], len(data))
            if state['reason'] is not None: return
            if len(data) > callback_bytes:
                self._reject('native_http_ingress_callback_cap')
                return
            if state['received'] > state['cap']:
                self._reject(state['cap_reason'])
                return
            try: state['framing'].feed(data)
            except BudgetStop as exc:
                self._reject(str(exc))
                return
            state['admitted'] += len(data)
            self._processing_wire = True
            try: super().data_received(data)
            finally: self._processing_wire = False

    connector = aiohttp.TCPConnector(limit=1, limit_per_host=1, force_close=True)
    if not hasattr(connector, '_factory'):
        raise BudgetStop('native_http_transport_capability_unverified')
    connector._factory = lambda: CountedResponse(loop=connector._loop,
                                                state=owner._wire_state)
    return connector


class PredictionBudget:
    def __init__(self, limits):self.limits=limits;self.dollars=Decimal(0);self.requests=0;self.connections=0;self.bytes=0
    def remaining_bytes(self):return self.limits['session_bytes']-self.bytes
    def charge_bytes(self,n):
        if n>self.remaining_bytes():raise BudgetStop('prediction_session_byte_cap')
        self.bytes+=n
    def reserve(self, kind):
        cost=Decimal(self.limits['dollars_per_'+kind])
        if self.dollars+cost>Decimal(self.limits['dollar_cap_per_source']):raise BudgetStop('prediction_dollar_cap')
        self.dollars+=cost
        if kind=='connection':self.connections+=1
        else:self.requests+=1


class MockREST:
    """Injected bounded HTTP client for unchanged REST discovery parsers."""
    def __init__(self, endpoint, limits, sink, timeout, budget, *, venue=None, credential=None):
        self.venue=venue; self.credential=credential
        if venue:
            from .venue_access import endpoint as validate
            self.endpoint=validate(venue,'rest',endpoint)
        else:self.endpoint=mock_endpoint(endpoint)
        self.limits=limits; self.sink=sink; self.timeout=timeout
        self.requests=0; self.bytes=0; self.client=None;self.budget=budget

    async def pace(self):
        if self.venue:await asyncio.sleep(getattr(self, 'request_interval', 1))

    async def get(self, url, params=None, **kwargs):
        if getattr(self, 'transport_policy', None) is not None:
            return await self._get_bounded(url, params, **kwargs)
        return await self._get_legacy(url, params, **kwargs)

    async def _get_bounded(self, url, params=None, **kwargs):
        """Explicit v2 complete-response admission on the production aiohttp path."""
        from .native_payload import parse, validate_envelope, envelope, category
        policy = self.transport_policy
        if self.budget.requests >= self.limits['discovery_requests']:
            raise BudgetStop('prediction_discovery_request_cap')
        await self.pace()
        self.budget.reserve('discovery_request')
        self.requests += 1
        path = urlsplit(url).path
        query = params if params is not None else urlsplit(url).query
        saved_query = _safe_params(query)
        constructed = self.endpoint+path
        headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity',
                   'Connection': 'close'}
        if self.credential and self.venue == 'kalshi':
            headers.update(self.credential.headers(path))
        started = utc()
        body = bytearray()
        status = None
        complete = usable = False
        reason = None
        response_headers = []
        response_url = http_version = content_length = None
        reserved = entity_read = 0
        metrics = {}
        source_wire = getattr(self, 'http_wire_bytes', 0)
        source_decoded = getattr(self, 'http_decoded_bytes', 0)
        allowance = policy['ingress_callback_bytes']
        wire_cap = min(policy['response_wire_bytes'],
            policy['discovery_wire_bytes']-source_wire-allowance,
            self.budget.remaining_bytes()-allowance)
        self._wire_state = dict(received=0, admitted=0, cap=wire_cap,
            cap_reason=('native_wire_byte_cap' if wire_cap == policy['response_wire_bytes']
                        else 'native_discovery_wire_byte_cap' if
                        policy['discovery_wire_bytes']-source_wire-allowance <= self.budget.remaining_bytes()-allowance
                        else 'prediction_session_byte_cap'),
            reason=None, max_callback=0, sha256=sha256(), framing=_HTTPFraming(),
            closed=asyncio.get_running_loop().create_future())
        request_deadline = asyncio.get_running_loop().time()+self.timeout
        request_provenance = dict(configured_endpoint=_safe_url(self.endpoint),
            supplied_url=_safe_url(url), constructed_url=_safe_url(constructed),
            dispatched_url=None, method='GET', headers=_safe_headers(headers),
            redirect_policy='refuse', auto_decompress=False, trust_env=False,
            cookie_policy='disabled', connection_policy='one request; force close')
        try:
            if envelope(path) is None:
                raise BudgetStop('native_unsupported_metadata_route')
            if wire_cap <= 0:
                raise BudgetStop(self._wire_state['cap_reason'])
            if source_decoded >= policy['discovery_decoded_bytes']:
                raise BudgetStop('native_discovery_decoded_byte_cap')
            # Reservation prevents other source tasks sharing this budget from
            # spending the read-ahead allowance while ingress is in progress.
            reserved = wire_cap+allowance
            self.budget.charge_bytes(reserved)
            if self.client is None:
                self.client = aiohttp.ClientSession(auto_decompress=False,
                    trust_env=False, cookie_jar=aiohttp.DummyCookieJar(),
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    connector=_bounded_connector(self, allowance),
                    response_class=_StrictCloseResponse,
                    read_bufsize=4096, max_line_size=8190,
                    max_field_size=8190, max_headers=64)
                self.client._retry_connection = False
                self._bounded_http_client = True
            elif not getattr(self, '_bounded_http_client', False):
                raise BudgetStop('native_http_transport_capability_unverified')
            entity_cap = min(policy['response_entity_bytes'],
                             policy['response_decoded_bytes'],
                             policy['discovery_decoded_bytes']-source_decoded)
            async with self.client.get(constructed, params=query,
                    allow_redirects=False, headers=headers) as response:
                status = response.status
                response_url = _safe_url(response.url)
                request_provenance['dispatched_url'] = _safe_url(response.request_info.real_url)
                request_provenance['headers'] = _safe_headers(response.request_info.headers)
                response_headers = _safe_headers(response.headers, response=True)
                http_version = str(response.version.major)+'.'+str(response.version.minor)
                if self.credential:
                    self.credential.check(json.dumps([request_provenance, response_headers,
                        saved_query, response_url]).encode(), headers)
                length_values = response.headers.getall('Content-Length', [])
                if length_values:
                    if len(length_values) != 1 or not re.fullmatch(r'[0-9]{1,20}', length_values[0]):
                        raise BudgetStop('native_http_framing_error')
                    content_length = int(length_values[0])
                encodings = response.headers.getall('Content-Encoding', [])
                encoding = encodings[0].strip().lower() if len(encodings) == 1 else 'identity'
                if len(encodings) > 1 or encoding != 'identity':
                    raise BudgetStop('native_unsupported_encoding')
                while True:
                    if len(body) == entity_cap:
                        extra = await response.content.read(1)
                        entity_read += len(extra)
                        if extra:
                            limit_reason = ('native_discovery_decoded_byte_cap' if entity_cap < min(
                                    policy['response_entity_bytes'], policy['response_decoded_bytes'])
                                else 'native_decoded_byte_cap' if policy['response_decoded_bytes'] < policy['response_entity_bytes']
                                else 'native_entity_byte_cap')
                            raise BudgetStop(limit_reason)
                        break
                    chunk = await response.content.read(min(4096, entity_cap-len(body)))
                    if not chunk: break
                    entity_read += len(chunk)
                    body.extend(chunk)
                if content_length is not None and entity_read != content_length:
                    raise BudgetStop('native_http_length_mismatch')
                # Force-close requests must be validated through actual peer
                # EOF; framed payload EOF alone may hide a delayed surplus.
                remaining = request_deadline-asyncio.get_running_loop().time()
                if remaining <= 0: raise BudgetStop('native_http_timeout')
                await asyncio.wait_for(asyncio.shield(self._wire_state['closed']), remaining)
                if self._wire_state['reason'] is not None:
                    raise BudgetStop(self._wire_state['reason'])
                complete = True
                raw = bytes(body)
                if self.credential: self.credential.check(raw, headers)
                if 300 <= status < 400:
                    raise BudgetStop('native_http_redirect_refused')
                if status != 200:
                    # The ordinary policy owns any permitted status retry.
                    # A complete error response is retained but cannot enter
                    # envelope, identity, semantic or book admission.
                    reason = 'native_http_status_'+str(status)
                    return httpx.Response(status, content=raw,
                        headers={k:response.headers[k] for k in ('Retry-After', 'Content-Type') if k in response.headers},
                        request=httpx.Request('GET', str(response.request_info.real_url)))
                content_types = response.headers.getall('Content-Type', [])
                if len(content_types) != 1:
                    raise BudgetStop('native_unexpected_content_type')
                content_type = content_types[0]
                media_type = content_type.split(';', 1)[0].strip().lower()
                if media_type != 'application/json' and not (
                        media_type.startswith('application/') and media_type.endswith('+json')):
                    raise BudgetStop('native_unexpected_content_type')
                charset = response.charset
                if (len(re.findall(r'(?:^|;)\s*charset\s*=', content_type, flags=re.I)) > 1 or
                    charset is not None and charset.lower().replace('_', '-') not in ('utf-8', 'utf8')):
                    raise BudgetStop('native_unsupported_encoding')
                # UTF-16/32 auto-detection by json.loads is deliberately disabled.
                raw.decode('utf-8')
                data = parse(raw, limits=policy, metrics=metrics, revised=getattr(self,"revised_parse_accounting",False))
                validate_envelope(data, path)
                usable = True
                return httpx.Response(status, content=raw,
                    headers={k:response.headers[k] for k in ('Retry-After', 'Content-Type') if k in response.headers},
                    request=httpx.Request('GET', str(response.request_info.real_url)))
        except asyncio.CancelledError:
            reason = 'native_http_cancelled'
            raise
        except BudgetStop as exc:
            reason = self._wire_state['reason'] or str(exc)
            if reason != str(exc): raise BudgetStop(reason) from None
            raise
        except json.JSONDecodeError as exc:
            text = bytes(body).decode('utf-8')
            incomplete = exc.pos >= len(text.rstrip()) or 'Unterminated' in exc.msg
            reason = 'native_incomplete_json' if incomplete else 'native_malformed_json'
            metrics.update(json_error_position=exc.pos, json_error_message=exc.msg)
            raise BudgetStop(reason) from None
        except UnicodeDecodeError:
            reason = 'native_invalid_utf8'
            raise BudgetStop(reason) from None
        except TimeoutError:
            reason = self._wire_state['reason'] or 'native_http_timeout'
            raise BudgetStop(reason) from None
        except aiohttp.ClientPayloadError:
            reason = self._wire_state['reason'] or (
                'native_http_length_mismatch' if content_length is not None and entity_read != content_length
                else 'native_http_framing_error')
            raise BudgetStop(reason) from None
        except aiohttp.ClientResponseError:
            reason = self._wire_state['reason'] or 'native_http_framing_error'
            raise BudgetStop(reason) from None
        except aiohttp.ClientError:
            reason = self._wire_state['reason'] or 'native_http_transport_error'
            raise BudgetStop(reason) from None
        except (ValueError, RecursionError) as exc:
            value = str(exc)
            reason = value if value.startswith('native_') else (
                'native_credential_echo_suppressed' if value == 'credential echo suppressed'
                else 'native_malformed_json')
            raise BudgetStop(reason) from None
        finally:
            state = self._wire_state
            self.http_wire_bytes = source_wire+state['received']
            self.http_decoded_bytes = source_decoded+entity_read
            self.bytes += entity_read
            if reserved:
                self.budget.bytes -= reserved-state['received']
            raw = bytes(body)
            provenance_redacted = False
            redaction_reason = None
            if self.credential:
                try:
                    self.credential.check(raw, headers)
                    self.credential.check(json.dumps([request_provenance, response_headers, saved_query, response_url]).encode(), headers)
                except ValueError:
                    raw = b''
                    usable = False
                    redaction_reason = 'native_credential_echo_suppressed'
                    if reason is None: reason = redaction_reason
                    request_provenance = dict(redacted=True, method='GET', redirect_policy='refuse')
                    response_headers = []
                    saved_query = '<redacted>'
                    provenance_redacted = True
            metrics.update(request_category=category(path), response_envelope=envelope(path),
                wire_bytes=state['received'], wire_admitted_bytes=state['admitted'],
                wire_max_callback_bytes=state['max_callback'], entity_bytes_read=entity_read,
                retained_body_bytes=len(raw), decoded_bytes=entity_read,
                source_wire_bytes=self.http_wire_bytes, source_decoded_bytes=self.http_decoded_bytes,
                response_content_length=content_length, active_wire_cap_bytes=wire_cap,
                active_entity_cap_bytes=locals().get('entity_cap'),
                wire_overflow_allowance_bytes=allowance,
                http_header_wire_bytes=state['framing'].header_bytes,
                framed_entity_bytes=state['framing'].entity_bytes,
                http_framing_state=state['framing'].phase,
                peer_close_observed=state['closed'].done(),
                plaintext_read_mode=state.get('read_mode'),
                fixed_ingress_buffer_bytes=allowance)
            self.sink(dict(type='prediction_discovery_http', path=path, status=status,
                complete=complete, wire_complete=complete, usable_metadata=usable, envelope_valid=usable,
                started_at=started, params=saved_query, received_at=utc(),
                delivery_reason=reason, body_b64=base64.b64encode(raw).decode(),
                body_sha256=sha256(raw).hexdigest(), requests=self.requests,
                transport_policy=dict(policy), request_provenance=request_provenance,
                response_headers=response_headers, response_url=response_url if not provenance_redacted else '<redacted>',
                http_version=http_version, resource_usage=metrics,
                redaction_reason=redaction_reason,
                wire_accounting='HTTP plaintext before framing; excludes encrypted TLS and TCP/IP',
                http_plaintext_sha256=state['sha256'].hexdigest()))

    async def _get_legacy(self, url, params=None, **kwargs):
        if self.budget.requests >= self.limits['discovery_requests']:
            raise BudgetStop('prediction_discovery_request_cap')
        await self.pace()
        self.budget.reserve('discovery_request')
        self.requests+=1
        if self.client is None:
            self.client=aiohttp.ClientSession(auto_decompress=False,trust_env=False,
                timeout=aiohttp.ClientTimeout(total=self.timeout),connector=aiohttp.TCPConnector(limit=1),read_bufsize=4096)
            # Every retry must pass the shared pre-dispatch request reservation.
            self.client._retry_connection = False
        path=urlsplit(url).path
        query=params if params is not None else urlsplit(url).query
        body=bytearray(); status=None; complete=False; reserved=0; delivery_reason=None
        started=utc(); headers={'Accept-Encoding':'identity'}
        if self.credential and self.venue=='kalshi':headers.update(self.credential.headers(path))
        try:
            async with self.client.get(self.endpoint+path,params=query,allow_redirects=False,headers=headers) as response:
                status=response.status
                if getattr(self,'native_payload_policy',False) and response.headers.get('Content-Encoding','identity')!='identity':
                    raise BudgetStop('native_compression_refused')
                lookahead=1 if getattr(self,'strict_eof',False) else 0
                cap=min(getattr(self,'response_cap',self.limits['frame_bytes']),self.budget.remaining_bytes()-lookahead)
                if getattr(self,'native_payload_policy',False):
                    from .native_payload import DISCOVERY_SESSION_BYTES
                    cap=min(cap,DISCOVERY_SESSION_BYTES-self.bytes-lookahead)
                if cap<=0: raise BudgetStop('prediction_discovery_byte_cap')
                envelope_reason='native_response_byte_cap' if getattr(self,'gap_envelope',False) and cap==self.response_cap else 'prediction_discovery_byte_cap'
                self.budget.charge_bytes(cap+lookahead);reserved=cap+lookahead
                while True:
                    if len(body)==cap:
                        if lookahead:
                            extra=await response.content.read(1)
                            self.bytes+=len(extra)
                            if extra:raise BudgetStop(envelope_reason)
                        elif not response.content.at_eof():raise BudgetStop(envelope_reason)
                        break
                    chunk=await response.content.read(min(4096,cap-len(body)))
                    if not chunk: break
                    self.bytes+=len(chunk); room=cap-len(body); body.extend(chunk[:room])
                    if len(chunk)>room: raise BudgetStop(envelope_reason)
                if response.headers.get('Content-Encoding','identity')!='identity':raise ValueError('compressed discovery refused')
                if self.credential:self.credential.check(bytes(body),headers)
                complete=True
                if getattr(self,'native_payload_policy',False):
                    from .native_payload import parse
                    try:
                        if not isinstance(parse(bytes(body)),dict):raise ValueError('native_json_object_required')
                    except json.JSONDecodeError as exc:
                        incomplete=exc.pos>=len(body)-1 or 'Unterminated' in exc.msg
                        raise BudgetStop('native_incomplete_json' if incomplete else 'native_malformed_data')
                    except (ValueError, RecursionError):raise BudgetStop('native_malformed_data')
                return httpx.Response(status,content=bytes(body),headers={k:response.headers[k] for k in ('Retry-After',) if k in response.headers},request=httpx.Request('GET',self.endpoint+path))
        except BudgetStop as exc:
            delivery_reason=str(exc)
            raise
        finally:
            if complete:self.budget.bytes-=reserved-len(body)
            raw=bytes(body)
            if self.credential:
                try:self.credential.check(raw,headers)
                except ValueError:raw=b'';complete=False
            self.sink(dict(type='prediction_discovery_http',path=path,status=status,complete=complete,
                started_at=started,params=query,received_at=utc(),delivery_reason=delivery_reason,usable_metadata=complete and delivery_reason is None,body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest(),requests=self.requests))

    async def aclose(self):
        if self.client: await self.client.close()


class PredictionProducer:
    def __init__(self, venue, spec, rest_endpoint, websocket_endpoint, emit, health, *, credential=None, budget=None):
        self.venue=venue; self.spec=spec; self.row=spec['sources'][venue]
        self.real=spec['mode']=='real'; self.credential=credential
        self.kind=EvidenceKind.OBSERVATION if self.real else EvidenceKind.SYNTHETIC
        if self.real:
            from .venue_access import endpoint,REFERENCES
            if self.row['credential_reference']!=REFERENCES[venue] or credential is None:raise ValueError('dedicated project credential required')
            self.rest_endpoint=endpoint(venue,'rest',rest_endpoint);self.ws_endpoint=endpoint(venue,'ws',websocket_endpoint)
        else:
            self.rest_endpoint=mock_endpoint(rest_endpoint); self.ws_endpoint=mock_endpoint(websocket_endpoint)
        self.emit=emit; self.health=health; self.budget=budget or PredictionBudget(spec['prediction']); self.stream=None; self.adapter=None; self.bytes=0

    async def discover(self):
        p=self.spec['prediction']
        if self.adapter is None:
            client=MockREST(self.rest_endpoint,p,lambda r:self.emit(self.venue,r),self.spec.get('http',{}).get('timeout',5),self.budget,venue=self.venue if self.real else None,credential=self.credential)
            from .native_payload import configure_transport
            configure_transport(client,self.spec)
            self.adapter=(KalshiAdapter(client=client,series=('KXNFLGAME',),max_pages=2 if self.real else 1,page_size=200 if self.real else 10,
                max_requests=p['discovery_requests'],retries=0,pregame_only=False) if self.venue=='kalshi' else
                (NFLPolymarketAdapter if self.real else PolymarketUSAdapter)(client=client,max_pages=10 if self.real else 1,page_size=5 if self.real else 10,request_cap=p['discovery_requests'],attempts=1))
        self.adapter.events.clear(); self.adapter.markets.clear()
        events=await self.adapter.discover_events()
        matches=[e for e in events if e.raw.ref.event_id==self.row['event_id']]
        if len(matches)!=1: raise ValueError('configured event absent or ambiguous in bounded discovery')
        event=matches[0]
        if event.scheduled_start != time_value(self.spec['scheduled_start']):
            raise ValueError('configured schedule changed')
        from app.normalization.observations import enrich_event
        normalized=enrich_event(event,environment='production' if self.real else 'synthetic')
        mapped=[self.row['participant_mapping'].get(x.name) for x in normalized.participants]
        if None in mapped or set(mapped)!=set(self.spec['participants']):
            raise ValueError('configured participant mapping mismatch')
        markets=await self.adapter.discover_markets(event.raw.ref.event_id)
        matches=[m for m in markets if m.raw.ref.market_id==self.row['market_id']]
        if len(matches)!=1: raise ValueError('configured market absent or ambiguous')
        market=matches[0]
        if market.state.value!='active' or market.market_type.value!='moneyline':
            raise ValueError('market not active moneyline')
        if market.raw.ref.event_id!=event.raw.ref.event_id:
            raise ValueError('configured market event mismatch')
        validate_pregame(event,market)
        self.emit(self.venue,dict(type='discovery_validated',event_id=self.row['event_id'],market_id=self.row['market_id'],
            scheduled_start=event.scheduled_start.isoformat(),mapping_revision=self.spec['mapping_revision']))
        self.emit(self.venue,dict(type='market_selected',market=json.loads(json.dumps(asdict(market),default=str))))
        return replace(market,raw=replace(market.raw,kind=self.kind))

    async def run(self, market):
        producer=self; limits=self.spec['prediction']
        class Socket:
            def __init__(self,socket,wire_limit): self.socket=socket;self.wire_limit=wire_limit
            async def send(self,body):
                producer.emit(producer.venue,dict(type='prediction_command',connection=producer.budget.connections,body=body))
                await self.socket.send(body)
            async def recv(self):
                pending=False
                try:
                    # Reserve one full permitted frame before awaiting ingress;
                    # concurrent discovery cannot spend the same byte allowance.
                    producer.budget.charge_bytes(self.wire_limit)
                    pending=True
                    body=await self.socket.recv()
                    producer.application_received_at=utc()
                    producer.application_received_monotonic=asyncio.get_running_loop().time()
                    raw=body.encode() if isinstance(body,str) else body
                    producer.application_wire_sha256=sha256(raw).hexdigest()
                    producer.budget.bytes-=self.wire_limit-len(raw)
                    pending=False
                    producer.bytes+=len(raw)
                    if producer.bytes>limits['session_bytes']: raise BudgetStop('prediction_session_byte_cap')
                    if producer.credential:producer.credential.check(raw,producer.handshake_headers)
                    from .native_payload import enabled, parse
                    if enabled(producer.spec):
                        try:
                            if not isinstance(parse(raw),dict):raise ValueError('native_book_object_required')
                        except (ValueError, RecursionError):
                            producer.emit(producer.venue,dict(type='native_frame_rejected',reason='native_parse_rejected',
                                body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest()))
                            if hasattr(producer,'payload_rejected'):producer.payload_rejected('native_parse_rejected')
                            raise BudgetStop('native_parse_rejected')
                    producer.emit(producer.venue,dict(type='prediction_frame',connection=producer.budget.connections,received_at=utc(),application_received_at=producer.application_received_at,
                        body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest()))
                    return body
                except asyncio.CancelledError:
                    # websockets.recv cancellation preserves the next complete
                    # message; no application body was delivered in this call.
                    if pending:producer.budget.bytes-=self.wire_limit
                    raise
                except BaseException:
                    producer.health(producer.venue,'disconnected')
                    raise
            async def close(self):
                producer.health(producer.venue,'disconnected')
                await self.socket.close()
        async def factory():
            if self.budget.remaining_bytes()<=0:raise BudgetStop('prediction_session_byte_cap')
            if self.budget.connections>=limits['connections']:raise BudgetStop('prediction_connection_cap')
            self.budget.reserve('connection')
            self.handshake_headers=self.credential.headers() if self.credential else {}
            wire_limit=min(limits['frame_bytes'],self.budget.remaining_bytes())
            connector=connect
            if getattr(self, 'mock_segmented', False):
                if self.real or self.credential: raise ValueError('mock credential boundary')
                mock_endpoint(self.ws_endpoint)
                class NoRedirect(connect):
                    def process_redirect(self, exc): return exc
                connector=NoRedirect
            if self.spec.get('native_discovery') or self.spec.get('two_source_qualification') or (self.real and self.spec.get('supervised_profile')):
                # The isolated real profile never follows a credentialed redirect.
                class NoLiveRedirect(connect):
                    def process_redirect(self, exc): return exc
                connector=NoLiveRedirect
            socket=await connector(self.ws_endpoint,max_size=wire_limit,max_queue=1,
                                 compression=None,open_timeout=3,close_timeout=1,proxy=None,additional_headers=self.handshake_headers)
            self.health(self.venue,'awaiting_snapshot')
            return Socket(socket,wire_limit)
        self.stream=(KStream if self.venue=='kalshi' else PStream)(market if isinstance(market,list) else [market],factory,
            duration=self.spec['duration'],max_messages=limits['messages'],max_connections=limits['connections'],
            stale_seconds=self.spec['stale_seconds'],kind=self.kind,
            **({'profile_name':self.spec['supervised_profile']} if self.spec.get('supervised_profile') else {}))
        from .native_books import enabled as book_slice, Observations
        observations = Observations() if book_slice(self.spec) else None
        try:
            async for book in self.stream.run():
                book_evidence = observations.classify(book,self.budget.connections) if observations else None
                if self.spec.get('native_sources'):
                    from .native_semantics import purchase_book
                    book = purchase_book(book)
                if self.spec.get('v1_comparison_policy')=='manual-comparison-2' and self.venue=='kalshi' and book.state.value=='unknown':
                    # WS images omit lifecycle state. Use the exact current
                    # selected metadata generation, revoked on reconciliation.
                    selected=next((m for m in (market if isinstance(market,list) else [market]) if m.raw.ref.market_id==book.raw.ref.market_id),None)
                    if selected is not None:book=replace(book,state=selected.state)
                # Preserve native book/receipt semantics; health updates aren't new wire arrivals.
                data=json.loads(json.dumps(asdict(book),default=str))
                from app.arbitrage import book_observations
                from app.storage.workflow import packet
                packets=[]
                for observation in book_observations(book,environment='production' if self.real else 'synthetic',evidence_class='current' if self.real else 'synthetic',source_time_semantics='unknown'):
                    row=packet(observation)
                    row['raw_b64']=base64.b64encode(row.pop('raw')).decode()
                    packets.append(row)
                if not hasattr(self,'application_receipts'):self.application_receipts={}
                mid=book.raw.ref.market_id
                old=self.application_receipts.get(mid)
                if old is None or old[0]!=data['raw']['received_at']:
                    tick=getattr(self,'application_received_monotonic',None)
                    timing=dict(reconstructed_at=utc(),wire_sha256=getattr(self,'application_wire_sha256',None),
                        connection=self.budget.connections,receipt_to_reconstructed_ms=None if tick is None else (asyncio.get_running_loop().time()-tick)*1000)
                    self.application_receipts[mid]=(data['raw']['received_at'],getattr(self,'application_received_at',None),timing)
                if self.spec.get('v1_comparison_policy')=='manual-comparison-2':
                    # Connect health first; the ensuing current-generation
                    # synchronized image clears invalidation atomically in the reducer.
                    self.health(self.venue,'connected' if book.sync.value=='synchronized' else ('disconnected' if self.stream.connection is None else 'ineligible'))
                self.emit(self.venue,dict(type='prediction_book',book=data,packets=packets,application_received_at=self.application_receipts[mid][1],local_timing=self.application_receipts[mid][2],
                    receipt_semantics='derived native book state; wire arrivals separately retained',
                    **({'native_observation':book_evidence} if observations else {})))
                self.health(self.venue,'connected' if book.sync.value=='synchronized' else ('disconnected' if self.stream.connection is None else 'ineligible'))
                if getattr(self, 'after_book', None):
                    await self.after_book()
        finally:
            primary = sys.exception()
            try:
                await self.stream.aclose()
                self.health(self.venue,'disconnected')
                self.emit(self.venue,dict(type='native_stream_finished',diagnostics=self.stream.diagnostics,closed=self.stream.closed))
            except Exception as exc:
                failure(__name__, 'native_stream_finalize', exc)
                if primary is None:
                    raise

    async def interrupt_connection(self):
        """Explicit supervised fault; native stream owns invalidation and recovery."""
        if not self.stream or not self.stream.connection or self.stream.closed:
            raise ValueError('source has no active connection')
        if self.budget.connections >= self.spec['prediction']['connections']:
            raise ValueError('no recovery connection allowance')
        self.emit(self.venue,dict(type='controlled_interruption',connection=self.budget.connections,
            reason='supervised client-induced socket close; not a natural outage'))
        self.health(self.venue,'disconnected')
        await self.stream.connection.close()

    async def aclose(self):
        from app.cleanup import close_all
        await close_all([resource for resource in (self.stream, self.adapter) if resource is not None])
