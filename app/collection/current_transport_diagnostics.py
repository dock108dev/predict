"""Bounded transport vocabulary; never serialize exception/provider text."""
import asyncio
import ssl
import aiohttp


def exception_kind(exc):
    for kind, cls in (
        ('cancelled', asyncio.CancelledError),
        ('dns', aiohttp.ClientConnectorDNSError),
        ('tls_certificate', aiohttp.ClientConnectorCertificateError),
        ('tls', aiohttp.ClientSSLError),
        ('tls', ssl.SSLError),
        ('timeout', TimeoutError),
        ('connection', aiohttp.ClientConnectionError),
        ('body', aiohttp.ClientPayloadError),
        ('http', aiohttp.ClientResponseError),
        ('os', OSError),
        ('validation', ValueError),
    ):
        if isinstance(exc, cls):return dict(category=kind, type=cls.__name__)
    return dict(category='other', type='Exception')


def receipt(value):
    if not isinstance(value, dict):return None
    status=value.get('status')
    if type(status) is not int or not 100<=status<=599:return None
    items=value.get('headers', [])
    safe=[]
    if isinstance(items, (list,tuple)):
        for item in items[:16]:
            if not isinstance(item,(list,tuple)) or len(item)!=2:continue
            k,v=item
            if not isinstance(k,str) or k.lower() not in ('x-requests-used','x-requests-remaining','x-requests-last'):continue
            safe.append([k.lower(),v if isinstance(v,str) and len(v)<=12 and v.isascii() and v.isdigit() else 'invalid'])
    from app.dashboard.current_contract import stamp
    at=value.get('received_at')
    try:stamp(at)
    except (ValueError,TypeError):return None
    return dict(status=status,headers=safe,received_at=at)
