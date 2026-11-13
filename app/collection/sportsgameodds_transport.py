"""Bounded, single-request SportsGameOdds transport.

The caller owns durable object reservations, rate controls, Stop/pause checks,
and handling of uncertain charges. This transport never retries or logs request
URLs, credentials, error bodies, or provider text.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import re
import json

import aiohttp

from .sportsgameodds_adapter import LEAGUES, MAX_PAGE_BYTES

ENDPOINT = 'https://api.sportsgameodds.com/v2/events/'
ODD_IDS = frozenset(('points-home-game-ml-home', 'points-away-game-ml-away',
                     'points-home-game-sp-home', 'points-away-game-sp-away',
                     'points-all-game-ou-over', 'points-all-game-ou-under'))


class TransportFailure(RuntimeError):
    """The request ended without a verifiable response."""


@dataclass(frozen=True)
class PageResponse:
    status: int
    body: bytes
    received_at: str
    retry_after_seconds: int | None
    invalid_cursor: bool = False
    provider_request_id: str | None = None


def _invalid_cursor(body):
    """Recognize only an explicit cursor-specific rejection; never expose text."""
    try:
        value = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return False
    if not isinstance(value, dict) or value.get('success') is not False:
        return False
    error = value.get('error')
    return (isinstance(error, str) and len(error) <= 512
            and bool(re.search(r'\bcursor\b', error, re.I))
            and bool(re.search(r'\b(?:invalid|expired|malformed)\b', error, re.I)))


def _csv(value, *, limit=100):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError('invalid filter')
    items = value.split(',')
    if not 1 <= len(items) <= limit or len(set(items)) != len(items):
        raise ValueError('invalid filter')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', item) for item in items):
        raise ValueError('invalid filter')
    return items


def validate_params(params):
    """Allow only bounded, scope-bearing event queries; never accept secrets."""
    if not isinstance(params, dict) or set(params) - {'leagueID', 'eventIDs', 'oddID', 'bookmakerID', 'limit', 'cursor', 'includeOpposingOdds', 'includeAltLines', 'live', 'started', 'startsAfter', 'startsBefore'}:
        raise ValueError('unsupported request parameters')
    if type(params.get('limit')) is not int or not 1 <= params['limit'] <= 100:
        raise ValueError('bounded page limit required')
    if ('leagueID' in params) == ('eventIDs' in params):
        raise ValueError('exactly one event or league scope required')
    if 'leagueID' in params and not set(_csv(params['leagueID'])) <= LEAGUES:
        raise ValueError('unsupported league')
    if 'eventIDs' in params:
        _csv(params['eventIDs'])
    if not set(_csv(params.get('oddID'))) <= ODD_IDS:
        raise ValueError('unsupported odds filter')
    if 'bookmakerID' in params:
        _csv(params['bookmakerID'], limit=100)
    for field in ('includeOpposingOdds', 'includeAltLines', 'live', 'started'):
        if field in params and type(params[field]) is not bool:
            raise ValueError('boolean filter required')
    for field in ('startsAfter', 'startsBefore'):
        if field in params:
            from .sportsgameodds_adapter import _time
            _time(params[field])
    cursor = params.get('cursor')
    if cursor is not None and (not isinstance(cursor, str) or not cursor.isascii() or not 1 <= len(cursor) <= 2048 or any(ord(c) < 32 for c in cursor)):
        raise ValueError('invalid cursor')
    return dict(params)


class SportsgameoddsTransport:
    def __init__(self, *, session=None, response_bytes=MAX_PAGE_BYTES, timeout_seconds=30):
        if type(response_bytes) is not int or not 1 <= response_bytes <= MAX_PAGE_BYTES:
            raise ValueError('invalid response bound')
        self._session = session
        self._owns_session = session is None
        self.response_bytes = response_bytes
        self.timeout_seconds = timeout_seconds
        self.closed = False

    async def fetch(self, params, api_key):
        params = validate_params(params)
        params = {key: str(value).lower() if type(value) is bool else value for key, value in params.items()}
        if self.closed or not isinstance(api_key, str) or not api_key or len(api_key) > 1024:
            raise ValueError('transport unavailable')
        if self._session is None:
            self._session = aiohttp.ClientSession(auto_decompress=False, trust_env=False,
                connector=aiohttp.TCPConnector(limit=1, force_close=True),
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
                read_bufsize=4096, max_line_size=4096, max_field_size=4096)
            # aiohttp internal retry must not create an unaccounted paid request.
            self._session._retry_connection = False
        try:
            async with self._session.get(ENDPOINT, params=params,
                    headers={'x-api-key': api_key, 'Accept-Encoding': 'identity'},
                    allow_redirects=False) as response:
                received_at = datetime.now(timezone.utc).isoformat()
                request_id = response.headers.get('X-Request-ID')
                if (not request_id or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', request_id)
                        or api_key in request_id):
                    request_id = None
                retry = response.headers.get('Retry-After')
                retry = int(retry) if retry and retry.isascii() and retry.isdigit() and len(retry) <= 6 else None
                if response.status != 200:
                    invalid_cursor = False
                    if response.status == 400 and 'cursor' in params:
                        body = bytearray()
                        async for chunk in response.content.iter_chunked(4096):
                            if len(body) + len(chunk) > 4096:
                                break
                            body.extend(chunk)
                        else:
                            invalid_cursor = _invalid_cursor(body)
                    return PageResponse(response.status, b'', received_at, retry, invalid_cursor, request_id)
                if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise TransportFailure('unsupported response encoding')
                body = bytearray()
                async for chunk in response.content.iter_chunked(4096):
                    if len(body) + len(chunk) > self.response_bytes:
                        raise TransportFailure('response size exceeded')
                    body.extend(chunk)
                if api_key.encode() in body:
                    raise TransportFailure('sensitive response suppressed')
                return PageResponse(response.status, bytes(body), datetime.now(timezone.utc).isoformat(), retry,
                                    provider_request_id=request_id)
        except (aiohttp.ClientError, TimeoutError, OSError):
            raise TransportFailure('provider request outcome uncertain') from None

    async def close(self):
        self.closed = True
        if self._owns_session and self._session is not None:
            await self._session.close()
