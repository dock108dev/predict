"""Sealed r3 acquisition launcher. Local checks, then idle ordinary app; never auto-Start."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from .native_approval import digest,implementation,validate_approval
from .venue_access import ENDPOINTS
from .run_spec import preflight
from .acquisition_policy import dynamic

ROOT=Path(__file__).resolve().parents[2]
PACKAGE=ROOT/'evidence/integrated-acquisition-r3-20260930'

def prepared(*,approval_required=True):
    identity=json.loads((PACKAGE/'identity.json').read_text())
    if identity['implementation_sha256']!=digest(implementation()):
        raise ValueError('Source changed; rebind and review before activation')
    attempt=json.loads((PACKAGE/'attempt.json').read_text())
    output=Path(attempt['output'])
    if output.exists():raise ValueError('Attempt destination must be unused; never reset it')
    spec=json.loads((PACKAGE/'run-spec.json').read_text())
    if not dynamic(spec) or digest(spec)!=identity['spec_sha256'] or not preflight(spec)['valid']:
        raise ValueError('Static acquisition contract changed or expired')
    endpoints={**ENDPOINTS,'aggregate':'https://api.the-odds-api.com'}
    approval=PACKAGE/'approval.json'
    if approval_required:validate_approval(spec,endpoints,approval,output)
    return spec,endpoints,approval,output

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve',action='store_true')
    args=parser.parse_args()
    try:spec,endpoints,approval,output=prepared(approval_required=args.serve)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        raise SystemExit('BLOCKED: '+str(exc)) from None
    if not args.serve:
        print(json.dumps(dict(static_preflight='PASS',spec_sha256=digest(spec),
            approved=approval.exists(),startup_obtains=['quota','native catalog IDs','aggregate event IDs'],
            activation='Separate exact approval and ordinary Start required; no credentials or network used')))
        return
    # Explicit approved launch only; never touched by static preflight or imports.
    import os
    from .credential_handoff import handoff
    os.environ['ODDS_API_KEY']=handoff(ROOT,os.environ.get('ODDS_API_KEY'))
    from aiohttp import web
    from app.dashboard.coverage_owner import CoverageOwner
    from app.dashboard.multi_game_server import create_app
    owner=CoverageOwner(output/'unused-saved',pilot_output=output,endpoints=endpoints,
        spec_factory=lambda:deepcopy(spec),product_mode=True,native_approval_path=approval)
    owner.start_controls=frozenset({'duration'})
    web.run_app(create_app(owner=owner,sessions={},watch_path=output/'watches.json'),host='127.0.0.1',port=8831)

if __name__=='__main__':main()
