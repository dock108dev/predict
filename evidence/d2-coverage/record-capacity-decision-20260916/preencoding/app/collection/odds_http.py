"""Bounded event-odds wire path. This package permits loopback mocks only."""
import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import ipaddress
import re
from urllib.parse import urlsplit
import aiohttp


def utc():
    return datetime.now(timezone.utc).isoformat()


def mock_endpoint(url):
    parsed = urlsplit(url)
    try:
        local = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        local = False
    if not local or parsed.scheme not in ('http', 'ws') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('provider activation disabled; numeric loopback mock endpoint required')
    return url.rstrip('/')


@dataclass(frozen=True)
class HTTPPolicy:
    requests: int
    credits: int
    dollars: Decimal
    dollars_per_credit: Decimal
    reserve_per_request: int
    initial_used: int
    initial_remaining: int
    plan_evidence: str
    response_bytes: int
    session_bytes: int
    timeout: float
    retries: int
    backoff: float

    def __post_init__(self):
        import math
        for name in ('requests', 'credits', 'reserve_per_request', 'response_bytes', 'session_bytes'):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError('positive integer required: ' + name)
        for name in ('initial_used', 'initial_remaining', 'retries'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError('nonnegative integer required: ' + name)
        if self.requests > 256 or self.response_bytes > 1048576 or self.session_bytes > 16777216 or self.retries > 3:
            raise ValueError('HTTP engineering ceiling exceeded')
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 30 for v in (self.timeout, self.backoff)):
            raise ValueError('finite timeout/backoff between zero and 30 seconds required')
        if any(not isinstance(v, Decimal) or not v.is_finite() or v < 0 for v in (self.dollars, self.dollars_per_credit)) or not self.plan_evidence:
            raise ValueError('explicit finite cost and plan evidence required')


class BudgetStop(RuntimeError):
    pass


class Budget:
    def __init__(self, policy):
        self.policy = policy
        self.requests = self.credits = 0
        self.used, self.remaining = policy.initial_used, policy.initial_remaining
        self.reported_remaining = policy.initial_remaining
        self.reason = None

    def reserve(self):
        p = self.policy
        if self.reason:
            raise BudgetStop(self.reason)
        n = p.reserve_per_request
        if self.requests + 1 > p.requests or self.credits + n > p.credits or n > self.remaining or (self.credits+n)*p.dollars_per_credit > p.dollars:
            self.reason = 'request_credit_or_dollar_cap'
            raise BudgetStop(self.reason)
        self.requests += 1
        self.credits += n  # Uncertain charges are never refunded.
        self.remaining -= n

    def reconcile(self, headers):
        values = {}
        for key in ('x-requests-used', 'x-requests-remaining', 'x-requests-last'):
            found = [v for k, v in headers if k == key]
            if len(found) != 1 or not re.fullmatch(r'[0-9]{1,12}', found[0]):
                self.reason = 'quota_unknown_or_duplicate'
                return
            values[key] = int(found[0])
        used, remaining, last = (values[k] for k in ('x-requests-used', 'x-requests-remaining', 'x-requests-last'))
        p = self.policy
        previous_remaining = self.reported_remaining
        if used-self.used != last or previous_remaining-remaining != last or last > p.reserve_per_request:
            self.reason = 'quota_contradictory'
            self.credits += max(0, last-p.reserve_per_request)
        # Retain conservative available allowance, including over-reservations.
        self.used = used
        self.reported_remaining = remaining
        self.remaining = min(self.remaining, remaining)
        if remaining == 0:
            self.reason = self.reason or 'quota_exhausted'

    def snapshot(self):
        return dict(requests=self.requests, reserved_credits=self.credits,
                    charged_dollar_bound=str(self.credits*self.policy.dollars_per_credit),
                    reported_used=self.used, conservative_remaining=self.remaining, stop=self.reason)


class OddsHTTP:
    """One sequential request, no redirects/decompression; no credential loader.

    Every dispatched attempt emits a capture, including partial bytes on cancellation.
    The injected sink must durably retain it before returning.
    """
    def __init__(self, endpoint, event_id, policy, sink, *, dummy_key='e6-dummy-key', real_key=None):
        self.real=real_key is not None
        if self.real:
            if endpoint!='https://api.the-odds-api.com' or not isinstance(real_key,str) or not real_key:
                raise ValueError('invalid optional reference configuration')
            if policy.credits>5 or policy.dollars!=0 or policy.dollars_per_credit!=0:
                raise ValueError('optional reference limited to five free credits')
            self.endpoint=endpoint
        else:self.endpoint = mock_endpoint(endpoint)
        self._key=real_key if self.real else dummy_key
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', event_id):
            raise ValueError('invalid native event ID')
        if dummy_key != 'e6-dummy-key':
            raise ValueError('only the fixed dummy credential is permitted in this package')
        self.event_id, self.policy, self.sink = event_id, policy, sink
        self.budget = Budget(policy)
        self.total_bytes = 0
        self._client = None
        self._busy = False
        self.closed = False
        self._owner = None

    def metadata(self):
        return dict(path=f'/v4/sports/americanfootball_nfl/events/{self.event_id}/odds',
                    params=dict(markets='h2h', bookmakers='pinnacle', oddsFormat='decimal', dateFormat='iso', includeSids='true'))

    async def request(self):
        if self.closed or self._busy:
            raise BudgetStop('closed_or_concurrent_request')
        self._busy = True
        self._owner = asyncio.current_task()
        try:
            return await self._request()
        finally:
            self._busy = False
            self._owner = None

    async def _request(self):
        if self.total_bytes >= self.policy.session_bytes:
            raise BudgetStop('session_byte_cap')
        self.budget.reserve()
        started = utc()
        body = bytearray()
        status, headers, reason = None, [], None
        cancelled = False
        try:
            if self._client is None:
                self._client = aiohttp.ClientSession(auto_decompress=False, trust_env=False,
                    connector=aiohttp.TCPConnector(limit=1), timeout=aiohttp.ClientTimeout(total=self.policy.timeout),
                    read_bufsize=4096, max_line_size=4096, max_field_size=4096)
            meta = self.metadata()
            async with self._client.get(self.endpoint+meta['path'], params={**meta['params'], 'apiKey':self._key},
                                        allow_redirects=False, headers={'Accept-Encoding':'identity'}) as response:
                status = response.status
                for key, value in response.headers.items():
                    key = key.lower()
                    if key in ('x-requests-used','x-requests-remaining','x-requests-last','retry-after'):
                        headers.append((key, value if re.fullmatch(r'[0-9]{1,12}', value) else 'invalid'))
                self.budget.reconcile(headers)
                cap = min(self.policy.response_bytes, self.policy.session_bytes-self.total_bytes)
                while True:
                    room = cap-len(body)
                    if room == 0:
                        if not response.content.at_eof():
                            reason = 'incomplete_capture_byte_limit'
                        break
                    chunk = await response.content.read(min(4096, room))
                    if not chunk:
                        break
                    body.extend(chunk)
                    self.total_bytes += len(chunk)
                if response.headers.get('Content-Encoding', 'identity') != 'identity':
                    reason = reason or 'unsupported_content_encoding'
                if 300 <= status < 400:
                    reason = reason or 'redirect_disabled'
        except asyncio.CancelledError:
            reason, cancelled = 'incomplete_capture_cancelled', True
        except (TimeoutError, aiohttp.ClientError, OSError):
            reason = 'incomplete_capture_transport_failure'
        finally:
            if reason:
                self.budget.reason = self.budget.reason or reason
            # Never persist a credential echoed by an error endpoint. Discard, do not
            # relabel altered bytes as exact capture. No exception messages are used.
            raw = bytes(body)
            if self._key.encode() in raw or base64.b64encode(self._key.encode()) in raw:
                raw = b''
                reason = 'incomplete_capture_secret_echo_suppressed'
                self.budget.reason = reason
            if status is None:
                self.budget.reason = self.budget.reason or 'quota_unknown_after_dispatch'
            record = dict(type='reference_http', request=self.metadata(), request_started_at=started,
                          received_at=utc(), status=status, headers=headers,
                          complete=reason is None, reason=reason, body_b64=base64.b64encode(raw).decode(),
                          body_sha256=sha256(raw).hexdigest(), accounting=self.budget.snapshot(),
                          provenance='real optional provider response; pairing/lineage/settlement unqualified' if self.real else 'fabricated/local-mock protocol; not provider observation')
            self.sink(record)
        if cancelled:
            raise asyncio.CancelledError()
        return record

    async def aclose(self):
        self.closed = True
        owner=self._owner
        if owner is not None and owner is not asyncio.current_task() and not owner.done():
            owner.cancel()
            await asyncio.gather(owner,return_exceptions=True)
        if self._client is not None:
            await self._client.close()
