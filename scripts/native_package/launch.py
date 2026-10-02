"""Sealed native market-detail and book-update slice; inert until approved ordinary Start."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
PACKAGE=Path(__file__).resolve().parent
from app.collection.native_approval import implementation,digest,validate_approval
from app.collection.run_spec import preflight,time_value
from app.collection.venue_access import ENDPOINTS

def prepared(approved=False, *, activated=False):
    ident=json.loads((PACKAGE/'identity.json').read_text())
    if digest(implementation())!=ident['implementation_sha256']:raise ValueError('Candidate changed; fresh binding required')
    for name in ident['file_hashes']:
        if sha256((PACKAGE/name).read_bytes()).hexdigest()!=ident['file_hashes'][name]:raise ValueError('Sealed package changed: '+name)
    spec=json.loads((PACKAGE/'run-spec.json').read_text());a=json.loads((PACKAGE/'attempt.json').read_text())
    output=Path(a['output'])
    if a['attempt_id']!=ident['attempt_id'] or a['output']!=ident['output']:raise ValueError('Attempt identity mismatch')
    if (PACKAGE/'start-dispatch.json').exists() or (output/'b3-attempt.json').exists():raise ValueError('Attempt consumed; never restart')
    if not activated and ((PACKAGE/'activation.json').exists() or output.exists()):raise ValueError('Destination already exists or activated; never reset or reuse')
    if activated:
        activation=json.loads((PACKAGE/'activation.json').read_text())
        if activation['attempt_id']!=a['attempt_id'] or activation['output']!=str(output):raise ValueError('Activation mismatch')
        if not output.is_dir():raise ValueError('Destination is not unused idle output')
        # Ordinary Owner creates this empty saved-session directory while idle.
        for child in output.iterdir():
            if child.name!='unused-saved' or child.is_symlink() or not child.is_dir() or any(child.iterdir()):
                raise ValueError('Destination is not unused idle output')
    if not preflight(spec)['valid'] or digest(spec)!=ident['spec_sha256']:raise ValueError('Invalid spec')
    if not time_value(spec['start_after'])<=datetime.now(timezone.utc)<=time_value(spec['start_before']):raise ValueError('Outside sealed window')
    if approved:
        approval=json.loads((PACKAGE/'approval.json').read_text())
        if approval.get('attempt_id')!=a['attempt_id']:raise ValueError('Approval attempt mismatch')
        if approval.get('file_hashes')!=ident['file_hashes']:raise ValueError('Approval package seals mismatch')
        validate_approval(spec,ENDPOINTS,PACKAGE/'approval.json',output)
    return spec,output

def install_diagnostics():
    import logging
    class StartupLog(logging.Handler):
        def emit(self,record):
            # Only app.diagnostics' safe location record: no exception messages/locals.
            if record.msg!='%s failed (%s); frames=%s':return
            path=PACKAGE/'startup-locations.log'
            raw=(record.getMessage()+'\n').encode()[:4096]
            if (path.stat().st_size if path.exists() else 0)+len(raw)<=65536:
                with path.open('ab') as f:
                    f.write(raw);f.flush();__import__('os').fsync(f.fileno())
    handler=StartupLog()
    __import__('logging').getLogger('app.dashboard.coverage_owner').addHandler(handler)
    return handler

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--serve',action='store_true');args=parser.parse_args()
    try:spec,output=prepared(args.serve)
    except (OSError,ValueError,KeyError,TypeError) as exc:raise SystemExit('BLOCKED: '+str(exc)) from None
    if not args.serve:
        print(json.dumps(dict(static_checks='PASS',approved=False,activation='Separate exact approval required',provider_requests=0,credential_access=0)));return
    install_diagnostics()
    from aiohttp import web
    from app.dashboard.coverage_owner import CoverageOwner
    from app.dashboard.multi_game_server import create_app
    with (PACKAGE/'activation.json').open('x') as f:
        json.dump(dict(attempt_id=json.loads((PACKAGE/'attempt.json').read_text())['attempt_id'],output=str(output)),f)
    owner=CoverageOwner(output/'unused-saved',pilot_output=output,endpoints=ENDPOINTS,spec_factory=lambda:deepcopy(spec),product_mode=True,native_approval_path=PACKAGE/'approval.json')
    owner.start_controls=frozenset({'duration'})
    app=create_app(owner=owner,sessions={},watch_path=output/'watches.json')
    async def binding(request):
        return web.json_response(json.loads((PACKAGE/'identity.json').read_text()))
    app.router.add_get('/probe-binding',binding)
    web.run_app(app,host='127.0.0.1',port=8831)
if __name__=='__main__':main()
