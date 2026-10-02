"""Once-only ordinary Start/Stop client. --check is inert; --run needs exact approval."""
import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError
import launch
from app.collection.control_binding import parse_identity, validate_identity, BODY_CAP, SCHEMA_VERSION
PACKAGE=Path(__file__).resolve().parent
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def sanitize(value):
    if isinstance(value,dict):
        return {k:('[REDACTED]' if re.search(r'authorization|cookie|secret|password|token|api.?key|private.?key|credential',k,re.I) else sanitize(v)) for k,v in value.items()}
    if isinstance(value,list):return [sanitize(v) for v in value]
    if isinstance(value,str):
        value=re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)','[REDACTED KEY]',value,flags=re.S)
        value=re.sub(r'(?i)\b(Bearer|Basic)\s+[^\s"<]+',r'\1 [REDACTED]',value)
        value=re.sub(r'(?i)((?:api[-_]?key|access[-_]?token|secret|password|authorization|cookie)[\"\']?\s*[=:]\s*[\"\']?)[^\s,;"\'<>]+',r'\1[REDACTED]',value)
        value=re.sub(r'(https?://[^\s?"<>]+)\?[^\s"<>]*',r'\1?[REDACTED QUERY]',value)
    return value

def body(stream, *, binding=False):
    raw=stream.read(BODY_CAP+1)
    if binding:
        try:value=parse_identity(raw)
        except ValueError as exc:
            return dict(body=None,binding_error=str(exc),truncated=len(raw)>BODY_CAP,retained_input_bytes=min(len(raw),BODY_CAP))
        # Only the exact public schema escapes redaction; save() still redacts records.
        return dict(body=value,binding_schema=SCHEMA_VERSION,truncated=False,retained_input_bytes=len(raw))
    text=raw[:BODY_CAP].decode('utf-8',errors='replace')
    try:value=json.loads(text)
    except (ValueError,RecursionError):value=text
    return dict(body=sanitize(value),truncated=len(raw)>BODY_CAP,retained_input_bytes=min(len(raw),BODY_CAP))

def request(path,method='GET',payload=None):
    # Fixed loopback only, no proxies, redirects, auth handlers or credential access.
    if path not in ('/probe-binding','/api/status','/api/start','/api/stop'):raise ValueError('Control route not allowed')
    req=Request('http://127.0.0.1:8831'+path,data=None if payload is None else json.dumps(payload).encode(),method=method,headers={'Content-Type':'application/json','Origin':'http://127.0.0.1:8831'})
    try:
        with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=15) as response:
            return dict(status=response.status,**body(response, binding=path=='/probe-binding'))
    except HTTPError as exc:
        with exc:return dict(status=exc.code,error_class=type(exc).__name__,**body(exc))
    except Exception as exc:return dict(status=None,error_class=type(exc).__name__,error=sanitize(str(exc)))

def save(name,value):
    clean=sanitize(value)
    encoded=json.dumps(clean,indent=2)
    if len(encoded.encode())>131072:
        encoded=json.dumps(dict(control_record_truncated=True,status=clean.get('status') if isinstance(clean,dict) else None,sanitized_excerpt=encoded[:8192]))
    with (PACKAGE/name).open('x') as f:
        f.write(encoded+'\n');f.flush();os.fsync(f.fileno())

def diagnostics(output):
    found=[]
    # One session only; bounded count and bounded reads. Never read arbitrary source files.
    for f in sorted(output.glob('*/startup-failure.json'))[:2]:
        try:
            with f.open('rb') as stream:found.append(dict(path=str(f.relative_to(output)),**body(stream)))
        except Exception as exc:found.append(dict(error_class=type(exc).__name__))
    return found

def run():
    spec,output=launch.prepared(True,activated=True)
    expected=validate_identity(json.loads((PACKAGE/'identity.json').read_text()))
    dispatched=False
    try:
        binding=request('/probe-binding');idle=request('/api/status')
        if binding.get('status')!=200 or binding.get('body')!=expected:raise ValueError('Wrong control server binding')
        if idle.get('status')!=200 or idle.get('body',{}).get('state')!='idle' or idle['body'].get('active') or not idle['body'].get('start_available'):raise ValueError('Server not unused idle')
        # Durable consumption BEFORE dispatch: failure, interruption and uncertainty never permit retry.
        save('start-dispatch.json',dict(attempt_id=expected['attempt_id'],duration=90,monotonic=time.monotonic(),consumed=True))
        dispatched=True
        # Reserve one second inside the 90-second ceiling for the final poll/Stop.
        deadline=time.monotonic()+89
        result=request('/api/start','POST',{'duration':90});save('start-response.json',result)
        if result.get('status')==200:
            while time.monotonic()<deadline:
                time.sleep(min(1,deadline-time.monotonic()))
                status=request('/api/status')
                if status.get('status')==200 and status.get('body',{}).get('active') is False:
                    save('terminal-status.json',status)
                    break
    except BaseException as exc:
        save('control-interruption.json',dict(error_class=type(exc).__name__,error=str(exc),activated=True,dispatch=dispatched,consumed=dispatched))
        raise
    finally:
        # HTTP failure body is already durable before Stop/status can themselves fail.
        try:
            save('stop-response.json',request('/api/stop','POST',{}))
        finally:
            try:save('final-status.json',request('/api/status'))
            finally:save('startup-diagnostics.json',diagnostics(output))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',action='store_true');parser.add_argument('--check',action='store_true');args=parser.parse_args()
    if args.run:run()
    else:
        launch.prepared(False)
        print('PASS: inert package checks; no control/provider request or credential access')
if __name__=='__main__':main()
