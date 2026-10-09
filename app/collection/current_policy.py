"""Versioned running-app operation; separate from sealed finite policies."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from .current_aggregate_policy import POLICY as AGGREGATE_POLICY

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'predict-native-current-1'
GRANT = 'predict-standing-native-20261002'
MIB = 1024 * 1024
APP_RUNNING_DURATION = 31536000  # Existing configuration sentinel for process lifetime.
SPORTS = ['NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL']
DEFAULT = dict(schema=VERSION, authority=GRANT, enabled=True, aggregate_enabled=True,
    sports=['NFL'], aggregate_sports=[],
    families=['moneyline', 'spread', 'total'], duration_seconds=APP_RUNNING_DURATION,
    rediscovery_seconds=120, markets_per_source=20, events_per_source=24,
    requests_per_source=10000, connections_per_source=240,
    source_bytes=256*MIB, rss_bytes=768*MIB, cleanup_seconds=5,
    backoff_seconds=[2, 5, 15, 30, 60], reconnect_failures=5,
    ingress_records=16000, ingress_bytes=8*MIB, issue_records=200,
    issue_bytes=MIB, discovery_pages=36)


def validate(value):
    if isinstance(value,dict) and 'aggregate_sports' not in value:
        value=dict(value,aggregate_sports=[])
    if not isinstance(value, dict) or set(value) != set(DEFAULT):
        raise ValueError('Exact native operational configuration required')
    if value['schema'] != VERSION or value['authority'] != GRANT or any(type(value[k]) is not bool for k in ('enabled','aggregate_enabled')):
        raise ValueError('Native operational authority/schema conflict')
    for k in ('sports', 'families'):
        allowed=SPORTS if k=='sports' else DEFAULT[k]
        if not isinstance(value[k], list) or not value[k] or len(set(value[k])) != len(value[k]) or set(value[k])-set(allowed):
            raise ValueError('Unsupported native acquisition scope')
    scope=value['aggregate_sports']
    if not isinstance(scope,list) or len(set(scope))!=len(scope) or set(scope)-set(SPORTS):
        raise ValueError('Unsupported aggregate acquisition scope')
    if value['backoff_seconds'] != DEFAULT['backoff_seconds']:
        raise ValueError('Exact native backoff policy required')
    for k, ceiling in DEFAULT.items():
        if type(ceiling) is int and (type(value[k]) is not int or not 1 <= value[k] <= ceiling):
            raise ValueError('Native operational resource ceiling exceeded')
    if value['rediscovery_seconds'] < 60:
        raise ValueError('Native rediscovery must be at least 60 seconds')
    return deepcopy(value)


def aggregate_scope(config):
    return list(config.get('aggregate_sports') or config['sports'])


def load(path=None):
    path = Path(path) if path else ROOT / '.local/predict-current-config.json'
    if not path.exists():
        return validate(DEFAULT)
    if path.is_symlink() or path.stat().st_size > 8192:
        raise ValueError('Native configuration file bound')
    return validate(json.loads(path.read_text()))


def candidate():
    # Canonical JSON ordering keeps source identity consistent across callers.
    manifest = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
                for p in sorted((ROOT/'app').rglob('*')) if p.is_file()
                and '__pycache__' not in p.parts and p.suffix in {'.py','.json','.js','.html','.css'}}
    return sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest(), manifest


def consume(directory, runtime, config, digest):
    """Small immutable attempt identity before credentials or dispatch; no quotes."""
    from datetime import datetime, timezone
    from .venue_access import ENDPOINTS
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    attempts = list(directory.glob('attempt-*.json'))
    if len(attempts) >= 1024 or sum(p.stat().st_size for p in attempts) > 4*1024*1024:
        raise ValueError('Operational authority capacity; preserve records before reopening')
    value = dict(schema=VERSION, authority=GRANT, runtime_id=runtime, attempt_id=runtime,
        candidate_digest=digest, at=datetime.now(timezone.utc).isoformat(),
        endpoints=ENDPOINTS, config=config, consumed=True, odds_api_requests=0,
        grant='Owner approves necessary live-data attempts and retries; bounded native and shared aggregate read-only scope',
        aggregate_policy=AGGREGATE_POLICY.record(aggregate_scope(config)))
    import os
    fd = os.open(directory/('attempt-'+runtime+'.json'), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    return value
