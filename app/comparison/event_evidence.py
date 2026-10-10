"""Dedicated public event evidence transport; never an application collector.

Bodies go to disk. A complete, bounded JSON graph is parsed once and reduced by
the caller; incomplete bytes are transport evidence only. No retries/redirects.
"""
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import resource
import signal
import sys
import time
from urllib.parse import urlencode
import zlib

MAX_BODY = 16 * 1024 * 1024
MAX_RSS = 768 * 1024 * 1024
BLOCK = 64 * 1024
HOST = 'gateway.polymarket.us'


def exact_path(event_ids=('129629',)):
    if not event_ids or len(event_ids) != 1 or any(not str(i).isdigit() for i in event_ids):
        raise ValueError('exact_single_event_required')
    # OpenAPI array explode=true: one repeated query key for each array item.
    return '/v1/events?' + urlencode([('id', str(i)) for i in event_ids] +
        [('limit', '1'), ('includePopularPlayerProps', 'false')])


def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)


def now():
    return datetime.now(timezone.utc).isoformat()


def strict_json(path):
    """Bound graph complexity before one parse, including arrays and deep nesting."""
    depth = nodes = 0
    quoted = escape = False
    with Path(path).open('rb') as stream:
        while block := stream.read(BLOCK):
            for char in block:
                if quoted:
                    if escape:
                        escape = False
                    elif char == 92:
                        escape = True
                    elif char == 34:
                        quoted = False
                elif char == 34:
                    quoted = True
                    nodes += 1
                elif char in (123, 91):
                    depth += 1
                    nodes += 1
                elif char in (125, 93):
                    depth -= 1
                elif char == 44:
                    nodes += 1
                if depth > 64 or nodes > 1000000:
                    raise ValueError('json_complexity_limit')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('json_duplicate_key')
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('json_nonfinite')
    with Path(path).open(encoding='utf-8') as stream:
        return json.load(stream, object_pairs_hook=pairs, parse_float=str, parse_constant=invalid)


def read_response(response, directory, *, limit=MAX_BODY, deadline=None):
    """Consume a raw HTTPResponse once, enforcing independent wire/decoded caps."""
    directory = Path(directory)
    wire = directory / 'response.bin'
    decoded = directory / 'decoded.json'
    record = dict(status=response.status, headers={}, wire_bytes=0, decoded_bytes=0,
                  eof=False, transport_complete=False, json_complete=False)
    safe = ('content-type', 'content-encoding', 'content-length', 'date', 'transfer-encoding')
    for name in safe:
        values = response.headers.get_all(name, [])
        if len(values) > 1:
            record['reason'] = 'duplicate_transport_header'
            return record, None
        if values:
            record['headers'][name] = values[0][:1024]
    encoding = response.headers.get('Content-Encoding', 'identity').lower().strip()
    content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
    length = response.headers.get('Content-Length')
    compressor = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == 'gzip' else None
    whash = hashlib.sha256()
    dhash = hashlib.sha256()
    try:
        if response.status != 200:
            raise ValueError('http_status_failure')
        if content_type != 'application/json':
            raise ValueError('unsupported_content_type')
        if encoding not in ('identity', 'gzip'):
            raise ValueError('unsupported_content_encoding')
        if length is not None and (not length.isdigit() or int(length) > limit):
            raise ValueError('content_length_limit_or_invalid')
        if length is not None and response.headers.get('Transfer-Encoding'):
            raise ValueError('ambiguous_body_framing')
        with wire.open('xb') as raw, decoded.open('xb') as output:
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError('request_timeout')
                remaining = limit - record['wire_bytes']
                if remaining == 0:
                    if not response.isclosed():
                        raise ValueError('wire_byte_limit_no_eof')
                    block = b''
                else:
                    block = response.read(min(BLOCK, remaining))
                if not block:
                    record['eof'] = True
                    break
                raw.write(block)
                whash.update(block)
                record['wire_bytes'] += len(block)
                if compressor:
                    allowance = limit - record['decoded_bytes']
                    if allowance == 0:
                        raise ValueError('decoded_byte_limit')
                    value = compressor.decompress(block, allowance)
                else:
                    value = block
                if len(value) > limit - record['decoded_bytes']:
                    raise ValueError('decoded_byte_limit')
                output.write(value)
                dhash.update(value)
                record['decoded_bytes'] += len(value)
                if compressor and record['decoded_bytes'] == limit and not compressor.eof:
                    raise ValueError('decoded_byte_limit')
                if rss() >= MAX_RSS:
                    raise ValueError('memory_limit')
            if compressor and (not compressor.eof or compressor.unused_data or compressor.unconsumed_tail):
                raise ValueError('gzip_incomplete_or_trailing')
        if length is not None and record['wire_bytes'] != int(length):
            raise ValueError('content_length_mismatch')
        record['transport_complete'] = True
        graph = strict_json(decoded)
        if rss() >= MAX_RSS:
            raise ValueError('memory_limit')
        record.update(json_complete=True, reason='complete')
        return record, graph
    except (ValueError, OSError, EOFError, http.client.HTTPException, zlib.error, UnicodeError) as error:
        code = str(error)
        record['reason'] = ('request_timeout' if isinstance(error, TimeoutError) else
                            code if code in ('http_status_failure', 'unsupported_content_type',
                            'unsupported_content_encoding', 'content_length_limit_or_invalid',
                            'ambiguous_body_framing', 'wire_byte_limit_no_eof', 'decoded_byte_limit',
                            'gzip_incomplete_or_trailing', 'content_length_mismatch', 'memory_limit',
                            'json_complexity_limit', 'json_duplicate_key', 'json_nonfinite') else
                            'incomplete_or_invalid_body')
        return record, None
    finally:
        record.update(wire_sha256=whash.hexdigest(), decoded_sha256=dhash.hexdigest(), peak_rss_bytes=rss())


def fetch(directory):
    """Explicit evidence-only call; SIGALRM bounds DNS/TLS/read/parse end to end."""
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    start = time.monotonic()
    path = exact_path()
    record = dict(version='comparison-public-event-reader-1', method='GET',
        url='https://' + HOST + path, purpose='Complete exact event membership after diagnosed one-MiB cutoff',
        started_at=now(), requests=1, cost_usd='0', credits=0, retries=0, redirects=0,
        limit_wire_bytes=MAX_BODY, limit_decoded_bytes=MAX_BODY, deadline_seconds=30)
    def timeout(*_):
        raise TimeoutError('request_timeout')
    old = signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, 30)
    connection = http.client.HTTPSConnection(HOST, timeout=30)
    graph = None
    try:
        connection.request('GET', path, headers={'Accept': 'application/json', 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        record['headers_at'] = now()
        result, graph = read_response(response, directory, deadline=start + 30)
        record.update(result)
    except (OSError, http.client.HTTPException) as error:
        record.update(reason='request_timeout' if isinstance(error, TimeoutError) else 'transport_failure',
                      json_complete=False, transport_complete=False)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
        connection.close()
        record.update(finished_at=now(), elapsed_seconds=time.monotonic() - start, peak_rss_bytes=rss())
        (directory / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
    return record, graph


def fetch_nfl_events(directory, key):
    """One documented quota-free NFL identity read, separate from acquisition.

    The route and scope are fixed. Credentials are used only in the connection;
    response bytes remain temporary until checked for credential echoes. Quota
    headers are observations only and never change the owner's accounting.
    """
    import base64
    import re
    import shutil
    import tempfile
    from urllib.parse import unquote
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', key):
        raise ValueError('Existing credential format unavailable')
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    host = 'api.the-odds-api.com'
    path = '/v4/sports/americanfootball_nfl/events?' + urlencode(dict(
        dateFormat='iso', commenceTimeFrom='2026-10-11T00:00:00Z',
        commenceTimeTo='2026-10-12T23:59:59Z', includeRotationNumbers='true'))
    record = dict(version='comparison-quota-free-events-reader-1', method='GET',
        url='https://' + host + path, authentication='existing local credential, omitted',
        started_at=now(), requests=1, documented_credits=0, cost_usd='0',
        retries=0, redirects=0, deadline_seconds=30,
        limit_wire_bytes=MAX_BODY, limit_decoded_bytes=MAX_BODY,
        retained_copy_limit_bytes=48 * 1024 * 1024)
    start = time.monotonic()
    def timeout(*_):
        raise TimeoutError('request_timeout')
    old = signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, 30)
    connection = http.client.HTTPSConnection(host, timeout=30)
    graph = None
    try:
        connection.request('GET', path + '&' + urlencode({'apiKey': key}),
                           headers={'Accept': 'application/json', 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        record['headers_at'] = now()
        quota = {}
        for name in ('x-requests-last', 'x-requests-used', 'x-requests-remaining'):
            values = response.headers.get_all(name, [])
            quota[name] = (values[0] if len(values) == 1 and
                len(values[0]) <= 12 and values[0].isascii() and values[0].isdigit() else None)
        record['quota_headers'] = quota
        record['credits'] = int(quota['x-requests-last']) if quota['x-requests-last'] is not None else None
        with tempfile.TemporaryDirectory() as scratch:
            result, graph = read_response(response, scratch, deadline=start + 30)
            record.update(result)
            echo = False
            for name in ('response.bin', 'decoded.json'):
                p = Path(scratch) / name
                if not p.exists():
                    continue
                data = p.read_bytes()
                text = data.decode('utf-8', errors='replace')
                for _ in range(3):
                    text = unquote(text)
                echo |= key in text or 'apikey' in text.lower() or 'api_key' in text.lower()
                echo |= base64.b64encode(key.encode()) in data
            if echo:
                graph = None
                record.update(reason='credential_echo_suppressed', json_complete=False,
                              wire_sha256=None, decoded_sha256=None)
            else:
                for name in ('response.bin', 'decoded.json'):
                    p = Path(scratch) / name
                    if p.exists():
                        shutil.copyfile(p, directory / name)
            if record['credits'] != 0:
                graph = None
                record['reason'] = 'unexpected_or_unconfirmed_cost'
    except (OSError, http.client.HTTPException):
        record.update(reason='transport_failure', json_complete=False, transport_complete=False)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
        connection.close()
        record.update(finished_at=now(), elapsed_seconds=time.monotonic() - start, peak_rss_bytes=rss())
        (directory / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
    return record, graph
