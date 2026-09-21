"""Executable freeze for the isolated diagnostic. No secrets, transport or Start."""
from hashlib import sha256
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
from uuid import UUID

from .delivery_budget import CAP
from .supervised import PROFILE
from .venue_access import ENDPOINTS, REFERENCES

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_ROOT = ROOT / 'evidence/d2-coverage'
SCHEMA = 'kalshi-delivery-launcher-v1'
SUFFIXES = {'.py', '.json', '.js', '.html', '.css', '.sh'}


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return sha256(packed(value)).hexdigest()


def read_json(path):
    def unique(pairs):
        value = {}
        for k, v in pairs:
            if k in value: raise ValueError('duplicate_json_key')
            value[k] = v
        return value
    raw = Path(path).read_bytes()
    if len(raw) > PROFILE['manifest_bytes']: raise ValueError('input_manifest_size')
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('json_constant')))


def specification(output, attempt, *, mode='offline', ownership=None):
    """Proposed configuration only. A separate matching approval is required at Start."""
    return dict(schema=SCHEMA, mode=mode, output=str(Path(output).resolve()), attempt=attempt,
        ownership=str(Path(ownership or PRODUCTION_ROOT).resolve()),
        endpoints={'kalshi': dict(ENDPOINTS['kalshi'])},
        credential_reference=REFERENCES['kalshi'], duration=300, direct_stop=240,
        finalization=300, refresh=120, startup=60, kickoff_margin=600,
        slots=list(range(60, 300, 15)), requests=[40, 40, 16], generations=[44, 52],
        frozen=dict(PROFILE), subcaps=dict(CAP), market_policy='KXNFLGAME-pregame-kickoff-ticker-first',
        control='private-unix-v1', supervisor='independent-watchdog-v1',
        fixture='tests.delivery_launcher_fixture:Runtime' if mode=='offline' else None)


def validate_spec(spec):
    if not isinstance(spec, dict) or spec.get('mode') not in ('offline', 'real'):
        raise ValueError('diagnostic_spec')
    if str(UUID(spec['attempt'])) != spec['attempt']: raise ValueError('attempt_uuid')
    for k in ('output', 'ownership'):
        if not isinstance(spec[k], str) or str(Path(spec[k]).resolve()) != spec[k]:
            raise ValueError('canonical_path')
    if spec['mode']=='real' and Path(spec['ownership'])!=PRODUCTION_ROOT:
        raise ValueError('production_ownership_root')
    if spec['mode']=='offline' and Path(spec['ownership'])==PRODUCTION_ROOT:
        raise ValueError('fixture_production_root')
    if Path(spec['output'])==Path(spec['ownership']) or Path(spec['output']) in Path(spec['ownership']).parents:
        raise ValueError('overlapping_output_ownership')
    expected=specification(spec['output'], spec['attempt'], mode=spec['mode'], ownership=spec['ownership'])
    if packed(spec)!=packed(expected): raise ValueError('diagnostic_spec_mismatch')
    return spec


def runtime_inventory():
    return dict(python=sys.version, executable=str(Path(sys.executable).resolve()),
        platform=platform.platform(), implementation=platform.python_implementation(),
        dependencies=sorted([d.metadata['Name'],d.version] for d in metadata.distributions()))


def executable_manifest(spec):
    validate_spec(spec)
    paths=[]
    for base in ('app','tests','scripts'):
        paths.extend(p for p in (ROOT/base).rglob('*') if p.is_file() and '__pycache__' not in p.parts
                     and (p.suffix in SUFFIXES or base=='scripts'))
    paths.extend(ROOT/n for n in ('pyproject.toml','uv.lock','requirements.txt') if (ROOT/n).is_file())
    files={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    def git(*args):return subprocess.check_output(['git', *args],cwd=ROOT)
    untracked=git('ls-files','--others','--exclude-standard','-z').decode().split('\0')
    payload=dict(schema=SCHEMA, files=files, spec_sha256=digest(spec), execution=spec,
        runtime=runtime_inventory(), head=git('rev-parse','HEAD').decode().strip(),
        tracked_diff_sha256=sha256(git('diff','--binary','HEAD')).hexdigest(),
        untracked=sorted(p for p in untracked if p in files),
        roles=dict(launcher='app/collection/delivery_live.py',
            watchdog='app/collection/delivery_watchdog.py',
            fixture='tests/delivery_launcher_fixture.py', auditor='tests/delivery_launcher_audit.py'),
        profiles=dict(frozen=dict(PROFILE),subcaps=dict(CAP)))
    return dict(payload=payload, sha256=digest(payload))


def verify(manifest, spec):
    validate_spec(spec)
    if manifest!=executable_manifest(spec): raise ValueError('executable_candidate_mismatch')
    return manifest['sha256']


def validate_approval(approval, manifest, spec):
    expected=dict(schema=SCHEMA, approved=True, scope=spec['mode'],
                  candidate=manifest['sha256'], spec=digest(spec), attempt=spec['attempt'])
    if not isinstance(approval,dict) or set(approval)!=set(expected)|{'authorization'}:
        raise ValueError('explicit_approval_required')
    if any(approval[k]!=v for k,v in expected.items()) or not isinstance(approval['authorization'],str) or not approval['authorization'].strip():
        raise ValueError('approval_binding')
    if len(packed(approval))>16384:raise ValueError('approval_size')


def validate_session_spec(actual, spec):
    expected=dict(schema='kalshi-delivery-diagnostic-v1',
        mode='synthetic' if spec['mode']=='offline' else 'real',duration=spec['duration'],
        direct_stop=spec['direct_stop'],slots=spec['slots'],frozen=spec['frozen'],subcaps=spec['subcaps'])
    if packed(actual)!=packed(expected):raise ValueError('generated_session_spec_mismatch')
