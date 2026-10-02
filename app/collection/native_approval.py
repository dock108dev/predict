"""Exact, once-consumed native qualification. No credentials or network in validation."""
from hashlib import sha256
import json
from pathlib import Path
from .native_product import validate_sources
from .venue_access import ENDPOINTS
from .run_spec import preflight


def digest(value):return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def implementation():
    root=Path(__file__).resolve().parents[2]
    return {str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in sorted((root/'app').rglob('*')) if p.is_file() and p.suffix in ('.py','.js','.html','.css','.json') and '__pycache__' not in p.parts}


def validate_approval(spec,endpoints,path,output,*,consume=False):
    marker=Path(output)/'b3-attempt.json'
    if marker.exists():raise ValueError('Native qualification allowance consumed; no automatic repeat')
    if not path:raise ValueError('explicit native qualification approval required')
    value=json.loads(Path(path).read_text())
    if 'engineering_master' in value:
        from .engineering_authorization import validate_child_approval
        validate_child_approval(value,spec,endpoints,output)
    validate_sources(spec)
    expected_endpoints={**ENDPOINTS,'aggregate':'https://api.the-odds-api.com'} if spec.get('source_session') else ENDPOINTS
    if spec['mode']!='real' or endpoints!=expected_endpoints or not preflight(spec)['valid']:raise ValueError('invalid native qualification configuration')
    if spec.get('source_session'):
        from datetime import datetime, timezone
        from .run_spec import time_value
        now = datetime.now(timezone.utc)
        if not time_value(spec['start_after']) <= now <= time_value(spec['start_before']):
            raise ValueError('outside frozen acquisition start window')
        if not spec['source_session'].get('quota_startup') and not 0 <= (now-time_value(spec['source_session']['quota_observed_at'])).total_seconds() <= 60:
            raise ValueError('Fresh quota baseline required at explicit Start')
    if value.get('approved') is not True or value.get('spec_sha256')!=digest(spec) or value.get('implementation_sha256')!=digest(implementation()):raise ValueError('approval does not bind this candidate and scope')
    if value.get('output')!=str(Path(output).resolve()):raise ValueError('approval output mismatch')
    if spec.get('native_discovery'):
        from datetime import datetime, timezone
        from .run_spec import time_value
        if not time_value(spec['start_after'])<=datetime.now(timezone.utc)<=time_value(spec['start_before']):
            raise ValueError('outside frozen native discovery window')
    from .us_metadata_diagnostic import enabled as us_diagnostic
    if us_diagnostic(spec):
        from uuid import UUID
        try:
            attempt_id=value['attempt_id']
            if not isinstance(attempt_id,str) or str(UUID(attempt_id))!=attempt_id:raise ValueError()
        except (ValueError,KeyError,AttributeError):raise ValueError('metadata diagnostic requires exact fresh attempt identity') from None
    if spec.get('two_source_qualification'):
        from datetime import datetime, timezone
        from .run_spec import time_value
        if not time_value(spec['start_after'])<=datetime.now(timezone.utc)<=time_value(spec['start_before']):
            raise ValueError('outside frozen qualification start window')
    if consume:
        with marker.open('x') as f:
            json.dump(dict(approval_sha256=sha256(Path(path).read_bytes()).hexdigest(),spec_sha256=digest(spec),
                **(dict(started_monotonic=__import__('time').monotonic(),attempt_id=spec['two_source_qualification']['attempt_id']) if spec.get('two_source_qualification') else
                   dict(started_monotonic=__import__('time').monotonic(),attempt_id=value['attempt_id']) if us_diagnostic(spec) else
                   dict(started_monotonic=__import__('time').monotonic(),attempt_id=value['attempt_id'],
                        master_sha256=value['engineering_master']['master_sha256'],
                        reservation_sha256=value['engineering_master']['reservation_sha256']) if 'engineering_master' in value else {})),f)
            f.flush()
            __import__('os').fsync(f.fileno())
