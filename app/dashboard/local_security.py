"""Browser boundary for the direct, loopback-only personal dashboard."""
from app.fees.engine import number
from aiohttp import web

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
        if request.content_type != 'application/json':
            raise web.HTTPUnsupportedMediaType(text='JSON required')


def decimal_input(value, label):
    # Reuse the existing exact numeric policy before loading saved datasets.
    if type(value) not in (str, int, float) or len(str(value)) > 128:
        raise ValueError('Invalid ' + label)
    return number(value)


def calculation_inputs(query):
    decimal_input(query.get('quantity', '100'), 'quantity')
    if query.get('probability'):
        decimal_input(query['probability'], 'probability')


def validate_assumptions(value):
    if not isinstance(value, dict) or len(value) > 256:
        raise ValueError('Invalid assumptions object')
    for key, entry in value.items():
        if not isinstance(key, str) or not isinstance(entry, dict) or set(entry) - {'probability', 'basis'}:
            raise ValueError('Invalid assumption')
        if not isinstance(entry.get('basis', ''), str) or len(entry.get('basis', '')) > 2000:
            raise ValueError('Invalid assumption basis')
        if entry.get('probability') not in (None, ''):
            decimal_input(entry['probability'], 'probability')
    return value
