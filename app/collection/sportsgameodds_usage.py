"""Read only the nonsecret account facts required for safe dispatch."""
from datetime import datetime, timezone
import json

import aiohttp

URL = 'https://api.sportsgameodds.com/v2/account/usage'


def parse_usage(body: bytes, received_at: datetime) -> dict:
    if not isinstance(body, bytes) or len(body) > 65536:
        raise ValueError('usage response size')
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError('usage receipt time')
    try:
        value = json.loads(body)
        data = value['data']
        if value['success'] is not True or data['isActive'] is not True:
            raise ValueError('account inactive')
        monthly = data['rateLimits']['per-month']
        minute = data['rateLimits']['per-minute']
        limit, used = monthly['max-entities'], monthly['current-entities']
        requests = minute['max-requests']
        if any(type(v) is not int or v < 0 for v in (limit, used, requests)) or not limit or not requests or used > limit:
            raise ValueError('account limits unavailable')
        reset_text = monthly.get('currentIntervalEndTime') or monthly.get('current-interval-end-time')
        reset = datetime.fromisoformat(reset_text.replace('Z', '+00:00')) if reset_text else None
        if reset is not None and (reset.tzinfo is None or reset.utcoffset() is None):
            raise ValueError('account reset time invalid')
        tier = data.get('tier')
        if tier not in ('amateur', 'rookie', 'pro', 'all-star', 'allstar', None):
            tier = None
        return {'tier': tier, 'limit': limit, 'used': used, 'requests_per_minute': requests,
                'reset_at': reset, 'at': received_at}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError('usage response invalid or insufficient') from None


async def read_usage(api_key: str, *, session=None) -> dict:
    if not isinstance(api_key, str) or not api_key or len(api_key) > 1024:
        raise ValueError('credential unavailable')
    owns = session is None
    if owns:
        session = aiohttp.ClientSession(auto_decompress=False, trust_env=False,
                    connector=aiohttp.TCPConnector(limit=1, force_close=True),
                    timeout=aiohttp.ClientTimeout(total=15))
        session._retry_connection = False
    try:
        async with session.get(URL, headers={'x-api-key': api_key, 'Accept-Encoding': 'identity'}, allow_redirects=False) as response:
            at = datetime.now(timezone.utc)
            if response.status != 200 or response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                raise RuntimeError('account usage unavailable')
            body = bytearray()
            async for chunk in response.content.iter_chunked(4096):
                if len(body) + len(chunk) > 65536:
                    raise RuntimeError('account usage response exceeded bound')
                body.extend(chunk)
            if api_key.encode() in body:
                raise RuntimeError('sensitive response suppressed')
            return parse_usage(bytes(body), at)
    except (aiohttp.ClientError, TimeoutError, OSError):
        raise RuntimeError('account usage request failed') from None
    finally:
        if owns:
            await session.close()
