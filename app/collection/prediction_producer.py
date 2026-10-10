"""Native prediction adapters and stream engines owned by the observation session."""
import asyncio
import sys
from app.diagnostics import failure
import base64
from dataclasses import asdict, replace
from hashlib import sha256
from decimal import Decimal
import json
import re
from urllib.parse import urlsplit
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


# Preserve existing import paths while the transport owns its implementation.
from .native_http_transport import (
    _SECRET_NAME as _SECRET_NAME,
    _RESPONSE_HEADERS as _RESPONSE_HEADERS,
    _safe_url as _safe_url,
    _safe_headers as _safe_headers,
    _safe_params as _safe_params,
    _transport_capability as _transport_capability,
    _HTTPFraming as _HTTPFraming,
    _StrictCloseResponse as _StrictCloseResponse,
    _bounded_connector as _bounded_connector,
)


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
