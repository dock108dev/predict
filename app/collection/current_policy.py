"""Versioned running-app operation; separate from sealed finite policies."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from .current_aggregate_policy import MARKET_FAMILIES, POLICY as AGGREGATE_POLICY

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'predict-native-current-1'
GRANT = 'predict-standing-native-20261002'
MIB = 1024 * 1024
APP_RUNNING_DURATION = 31536000  # Existing configuration sentinel for process lifetime.
SPORTS = ['NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL']
DEFAULT = dict(schema=VERSION, authority=GRANT, enabled=True, aggregate_enabled=True, aggregate_provider='the_odds_api',
    sports=['NFL'], aggregate_sports=[], native_sports=[], native_families=[],
    families=['moneyline', 'spread', 'total'], duration_seconds=APP_RUNNING_DURATION,
    rediscovery_seconds=120, markets_per_source=20, events_per_source=24,
    requests_per_source=10000, connections_per_source=240,
    source_bytes=256*MIB, rss_bytes=768*MIB, cleanup_seconds=5,
    backoff_seconds=[2, 5, 15, 30, 60], reconnect_failures=5,
    ingress_records=16000, ingress_bytes=8*MIB, issue_records=200,
    issue_bytes=MIB, discovery_pages=36)
OPTIONAL_FLAGS = ('direct_novig_enabled', 'direct_kalshi_enabled', 'direct_polymarket_us_enabled', 'live_enabled')
AGGREGATE_PROVIDERS = ('the_odds_api', 'sportsgameodds')


class PregameWindowClosed(Exception):
    """A scheduled request reached kickoff before dispatch."""


def aggregate_provider(config):
    """Resolve the provider for present and older native configurations."""
    return (config or {}).get('aggregate_provider') or DEFAULT['aggregate_provider']


def price_routes(config):
    routes = {'novig': 'sportsgameodds', 'prophetx': 'sportsgameodds'}
    for venue in ('kalshi', 'polymarket_us'):
        routes[venue] = venue if config.get('direct_' + venue + '_enabled', True) else 'sportsgameodds'
    return routes


def validate(value):
    if isinstance(value,dict):
        value=dict(value)
        value.setdefault('aggregate_provider', aggregate_provider(value))
        for key in ('aggregate_sports','native_sports','native_families'):
            value.setdefault(key,[])
    if not isinstance(value, dict) or set(value) - set(OPTIONAL_FLAGS) != set(DEFAULT):
        raise ValueError('Exact native operational configuration required')
    if any(type(value[key]) is not bool for key in OPTIONAL_FLAGS if key in value):
        raise ValueError('Invalid optional source setting')
    if value['schema'] != VERSION or value['authority'] != GRANT or any(type(value[k]) is not bool for k in ('enabled','aggregate_enabled')):
        raise ValueError('Native operational authority/schema conflict')
    if value['aggregate_provider'] not in AGGREGATE_PROVIDERS:
        raise ValueError('Unsupported aggregate provider')
    for k in ('sports', 'families'):
        allowed=SPORTS if k=='sports' else DEFAULT[k]
        if not isinstance(value[k], list) or not value[k] or len(set(value[k])) != len(value[k]) or set(value[k])-set(allowed):
            raise ValueError('Unsupported native acquisition scope')
    scope=value['aggregate_sports']
    if not isinstance(scope,list) or len(set(scope))!=len(scope) or set(scope)-set(SPORTS):
        raise ValueError('Unsupported aggregate acquisition scope')
    for key,allowed in (('native_sports',SPORTS),('native_families',DEFAULT['families'])):
        scope=value[key]
        if not isinstance(scope,list) or len(set(scope))!=len(scope) or set(scope)-set(allowed):
            raise ValueError('Unsupported independent native acquisition scope')
    if value['backoff_seconds'] != DEFAULT['backoff_seconds']:
        raise ValueError('Exact native backoff policy required')
    for k, ceiling in DEFAULT.items():
        if type(ceiling) is int and (type(value[k]) is not int or value[k] < 1):
            raise ValueError('Native operational resource ceiling exceeded')
    if value['rediscovery_seconds'] < 60:
        raise ValueError('Native rediscovery must be at least 60 seconds')
    return deepcopy(value)


def aggregate_scope(config):
    return list(config.get('aggregate_sports') or config['sports'])


def native_scope(config):
    """Explicit native scope, with the unchanged legacy fallback when absent."""
    return list(config.get('native_sports') or config['sports'])


def native_markets(config):
    return list(config.get('native_families') or config['families'])


def live_enabled(config):
    """Only an explicit opt-in enables in-play collection and reads."""
    return (config or {}).get('live_enabled') is True


def odds_api_cutoff(at):
    from datetime import timedelta, timezone
    from app.storage.store import stamp

    at = stamp(at).astimezone(timezone.utc)
    whole_second = at.replace(microsecond=0)
    if at.microsecond:
        whole_second += timedelta(seconds=1)
    return whole_second.strftime('%Y-%m-%dT%H:%M:%SZ')


def aggregate_markets(config):
    families=config.get('families',DEFAULT['families'])
    if not isinstance(families,list) or not families or len(set(families))!=len(families) or set(families)-set(MARKET_FAMILIES.values()):
        raise ValueError('Exact aggregate market families required')
    return tuple(market for market, family in MARKET_FAMILIES.items() if family in families)


def aggregate_requests(config, sports=None, *, at=None):
    """Exact configured requests shared by scheduled and explicit refresh work."""
    from app.reference.product import SPORT_KEYS
    configured=aggregate_scope(config)
    selected=configured if sports is None else sports
    if (not isinstance(selected,list) or not selected or len(set(selected))!=len(selected)
            or set(selected)-set(configured)):
        raise ValueError('aggregate_scope_not_configured')
    params=dict(bookmakers=','.join(AGGREGATE_POLICY.bookmakers),
        markets=','.join(aggregate_markets(config)),oddsFormat='decimal',dateFormat='iso')
    if at is not None and not live_enabled(config):
        params['commenceTimeFrom'] = odds_api_cutoff(at)
    return [dict(path='/v4/sports/'+SPORT_KEYS[sport]+'/odds',params=deepcopy(params))
            for sport in selected]


def load(path=None):
    explicit = path is not None
    path = Path(path) if path else ROOT / '.local/predict-current-config.json'
    if not path.exists():
        if explicit:
            raise FileNotFoundError('Explicit current configuration file does not exist')
        return validate(DEFAULT)
    if path.is_symlink() or path.stat().st_size > 8192:
        raise ValueError('Native configuration file bound')
    return validate(json.loads(path.read_text()))


def candidate():
    # Canonical JSON ordering keeps source identity consistent across callers.
    manifest = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
                for p in sorted((ROOT/'app').rglob('*')) if p.is_file()
                and '__pycache__' not in p.parts and p.suffix in {'.py','.json','.js','.html','.css'}
                # Reader-only presentation cannot change transport, accounting,
                # configuration or financial evidence. Those remain attested.
                and not (p.is_relative_to(ROOT/'app/dashboard/opportunity_static')
                         and p.suffix in {'.js','.html','.css'})}
    return sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest(), manifest


def consume(directory, runtime, config, digest):
    """Small immutable attempt identity before credentials or dispatch; no quotes."""
    from datetime import datetime, timezone
    from .current_storage_policy import require_disk_space
    from .venue_access import ENDPOINTS
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    value = dict(schema=VERSION, authority=GRANT, runtime_id=runtime, attempt_id=runtime,
        candidate_digest=digest, at=datetime.now(timezone.utc).isoformat(),
        endpoints=ENDPOINTS, config=config, consumed=True, odds_api_requests=0,
        grant='Owner approves necessary live-data attempts and retries; bounded native and shared aggregate read-only scope',
        aggregate_policy=(AGGREGATE_POLICY.record(aggregate_scope(config),markets=aggregate_markets(config))
            if config['aggregate_provider']=='the_odds_api' else dict(provider='sportsgameodds', scope=aggregate_scope(config), status='awaiting_account_and_integration')))
    import os
    # Standing operation can accumulate startup receipts indefinitely. Keep
    # every prior receipt and apply the disk floor to this append only. Provider
    # quotas and dispatch attempts are recorded and guarded separately.
    body = json.dumps(value, sort_keys=True).encode()
    require_disk_space(directory, len(body))
    fd = os.open(directory/('attempt-'+runtime+'.json'), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return value
