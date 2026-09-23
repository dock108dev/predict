"""Browser boundary for the direct, loopback-only personal dashboard."""
import json
import math
from aiohttp import web

CONTROL_BODY_LIMIT = 4096
IMPORT_BODY_LIMIT = 1024 * 1024
IMPORT_ROUTES = frozenset(('/api/references', '/api/resolutions'))


def body_limit(path):
    return IMPORT_BODY_LIMIT if path in IMPORT_ROUTES else CONTROL_BODY_LIMIT


HEADERS = {
    'Cache-Control': 'no-store',
    'Content-Security-Policy': "default-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    'X-Robots-Tag': 'noindex, nofollow',
}


def check_browser(request):
    # Derive the port from the listening socket, never from untrusted Host/Forwarded.
    address = request.transport.get_extra_info('sockname') if request.transport else None
    hosts = {f'{host}:{address[1]}' for host in ('127.0.0.1', 'localhost')} if address else set()
    if len(request.headers.getall('Host', [])) != 1 or request.headers['Host'] not in hosts:
        raise web.HTTPForbidden(text='Use the local dashboard address')
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        raise web.HTTPForbidden(text='Cross-site request denied')
    origins = request.headers.getall('Origin', [])
    expected = 'http://' + request.headers['Host']
    if origins and origins != [expected]:
        raise web.HTTPForbidden(text='Cross-origin request denied')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        if origins != [expected]:
            raise web.HTTPForbidden(text='Same-origin request required')
        if request.headers.getall('Content-Encoding', ['identity']) != ['identity']:
            raise web.HTTPUnsupportedMediaType(text='Uncompressed JSON required')
        if request.content_type != 'application/json':
            raise web.HTTPUnsupportedMediaType(text='JSON required')


async def read_json(request):
    """Bound actual bytes, including chunked requests, before parsing/dispatch."""
    limit = body_limit(request.path)
    if (request.content_length or 0) > limit:
        raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=request.content_length)
    body = bytearray()
    while True:
        chunk = await request.content.read(min(65536, limit + 1 - len(body)))
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > limit:
            raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=len(body))

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError('Nonfinite JSON number')

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('Nonfinite JSON number')
        return result

    try:
        return json.loads(body.decode('utf-8'), object_pairs_hook=unique_object,
                          parse_constant=invalid_constant, parse_float=finite_float)
    except (ValueError, RecursionError):
        # Parser messages must not echo input fields, contents or encoding bytes.
        raise ValueError('Invalid JSON body; use unique fields and finite values') from None
