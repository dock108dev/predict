"""Once-only owned-server client; --check is inert, --run requires exact approval."""
import argparse
from contextlib import contextmanager
import json
import os
import re
import signal
import time
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError
import launch
from app.collection.control_binding import parse_identity, validate_identity, BODY_CAP, SCHEMA_VERSION

PACKAGE = Path(__file__).resolve().parent
RECORD_CAP = 131072


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@contextmanager
def whole_request_deadline(seconds):
    """Socket timeouts alone do not bound slow headers or a slowly streamed body."""
    previous = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    def expired(signum, frame):
        raise TimeoutError('Control whole-request deadline')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if previous_timer[0]:
            signal.setitimer(signal.ITIMER_REAL,
                             max(.001,previous_timer[0]-(time.monotonic()-started)),previous_timer[1])


def sanitize(value):
    if isinstance(value, dict):
        return {key:('[REDACTED]' if re.search(r'authorization|cookie|secret|password|token|api.?key|private.?key|credential', key, re.I)
                     else sanitize(item)) for key,item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)', '[REDACTED KEY]', value, flags=re.S)
        value = re.sub(r'(?i)\b(Bearer|Basic)\s+[^\s"<]+', r'\1 [REDACTED]', value)
        value = re.sub(r'(?i)((?:api[-_]?key|access[-_]?token|secret|password|authorization|cookie)["\']?\s*[=:]\s*["\']?)[^\s,;"\'<>]+', r'\1[REDACTED]', value)
        value = re.sub(r'(https?://[^\s?"<>]+)\?[^\s"<>]*', r'\1?[REDACTED QUERY]', value)
    return value


def body(stream, *, binding=False):
    raw = stream.read(BODY_CAP+1)
    if binding:
        try:
            value = parse_identity(raw)
        except ValueError as exc:
            return dict(body=None, binding_error=str(exc), truncated=len(raw)>BODY_CAP,
                        retained_input_bytes=min(len(raw), BODY_CAP))
        return dict(body=value, binding_schema=SCHEMA_VERSION, truncated=False,
                    retained_input_bytes=len(raw))
    try:
        value = json.loads(raw[:BODY_CAP].decode('utf-8', errors='replace'))
    except (ValueError, RecursionError):
        value = raw[:BODY_CAP].decode('utf-8', errors='replace')
    return dict(body=sanitize(value), truncated=len(raw)>BODY_CAP,
                retained_input_bytes=min(len(raw), BODY_CAP))


def request(path, method='GET', payload=None):
    if path not in ('/probe-binding','/api/status','/api/start','/api/stop'):
        raise ValueError('Control route not allowed')
    url = 'http://127.0.0.1:8831'+path
    req = Request(url, data=None if payload is None else json.dumps(payload).encode(), method=method,
                  headers={'Content-Type':'application/json','Origin':'http://127.0.0.1:8831'})
    # Start awaits the existing 5-second HTTP operation; cleanup and status are separately finite.
    timeout = {'/api/start':6, '/api/stop':2}.get(path, 1)
    try:
        with whole_request_deadline(timeout):
            try:
                with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=timeout) as response:
                    return dict(status=response.status, **body(response, binding=path=='/probe-binding'))
            except HTTPError as exc:
                with exc:
                    return dict(status=exc.code, error_class=type(exc).__name__, **body(exc))
    except Exception as exc:
        return dict(status=None, error_class=type(exc).__name__, error=sanitize(str(exc)))


def save(name, value):
    clean = sanitize(value)
    if name=='verified-server-identity.json':
        # The exemption is only this public, exact, bounded identity schema.
        # Authorization response text, headers and every other saved field stay redacted.
        if not isinstance(value,dict) or value.get('status') != 200 or value.get('binding_schema') != SCHEMA_VERSION:
            raise ValueError('Invalid retained public server binding')
        identity = parse_identity(json.dumps(value.get('body')).encode())
        clean['body'] = identity
    encoded = json.dumps(clean, indent=2).encode()
    if len(encoded)+1>RECORD_CAP:
        encoded = json.dumps(dict(control_record_truncated=True,
                                  status=clean.get('status') if isinstance(clean,dict) else None,
                                  sanitized_excerpt=encoded[:8192].decode(errors='replace'))).encode()
    with (PACKAGE/name).open('xb') as stream:
        stream.write(encoded+b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(PACKAGE, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def diagnostics(output):
    found = []
    for path in sorted(output.glob('*/startup-failure.json'))[:2]:
        try:
            with path.open('rb') as stream:
                found.append(dict(path=str(path.relative_to(output)), **body(stream)))
        except Exception as exc:
            found.append(dict(error_class=type(exc).__name__))
    return found


def run():
    spec, output = launch.prepared(True, activated=True)
    expected = validate_identity(json.loads((PACKAGE/'identity.json').read_text()))
    dispatched = False
    try:
        binding = request('/probe-binding')
        idle = request('/api/status')
        if binding.get('status') != 200 or binding.get('body') != expected:
            raise ValueError('Wrong control server binding')
        if idle.get('status') != 200 or idle.get('body',{}).get('state') != 'idle' or idle['body'].get('active') or not idle['body'].get('start_available'):
            raise ValueError('Server not unused idle')
        save('verified-server-identity.json', binding)
        # Durable consumption before the one Start; ambiguity and failure prohibit reuse.
        dispatch_at = time.monotonic()
        save('start-dispatch.json', dict(attempt_id=expected['attempt_id'], duration=spec['duration'],
                                         monotonic=dispatch_at, consumed=True))
        dispatched = True
        deadline = dispatch_at+spec['duration']
        result = request('/api/start', 'POST', {'duration':spec['duration']})
        save('start-response.json', result)
        if result.get('status') == 200:
            while time.monotonic()<deadline:
                status = request('/api/status')
                if status.get('status') == 200 and status.get('body',{}).get('active') is False:
                    save('terminal-status.json', status)
                    break
                time.sleep(max(0,min(.1,deadline-time.monotonic())))
    except BaseException as exc:
        save('control-interruption.json', dict(error_class=type(exc).__name__, error=str(exc),
                                               activated=True, dispatch=dispatched, consumed=dispatched))
        raise
    finally:
        try:
            save('stop-response.json', request('/api/stop','POST',{}))
        finally:
            try:
                save('final-status.json', request('/api/status'))
            finally:
                save('startup-diagnostics.json', diagnostics(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.run:
        run()
    else:
        launch.prepared(False)
        print('PASS: inert checks; no control/provider request or credential access')


if __name__ == '__main__':
    main()
