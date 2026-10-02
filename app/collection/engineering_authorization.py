"""One bounded engineering approval; durable reservations precede child authority.

No networking, credential loading or execution occurs here. Failed/uncertain
reservations remain spent. Existing exact approvals and consumed attempts are
never rewritten. A child still uses the ordinary once-consumed Start boundary.
"""
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from uuid import UUID, uuid4

from .native_payload import TRANSPORT_CONTRACT, validate_transport
from .run_spec import preflight, time_value
from .venue_access import ENDPOINTS, REFERENCES
from .source_session import ROLES

ROOT=Path(__file__).resolve().parents[2]
VERSION='predict-source-engineering-workstream-v1'
CONTROLLER='app/collection/engineering_authorization.py'
PROTECTED_FILES=(CONTROLLER,'app/collection/native_approval.py')
MIB=1024*1024
POLICY=dict(version=VERSION,max_sessions=4,max_integrated_sessions=2,
    endpoints={**deepcopy(ENDPOINTS),'aggregate':'https://api.the-odds-api.com'},
    roles=deepcopy(ROLES),native_transport=deepcopy(TRANSPORT_CONTRACT),
    session=dict(duration_seconds=180,owned_wall_seconds=240,cleanup_reserve_seconds=60,native_http_requests_per_source=48,
        native_http_requests=96,aggregate_http_requests=37,aggregate_credits=135,
        websocket_connections_per_source=2,websocket_connections=4,
        native_source_http_and_stream_bytes=8*MIB,aggregate_response_bytes=MIB,
        aggregate_session_bytes=37*256*1024,queue_bytes=4*MIB,queue_records=48,
        journal_encoded_bytes=32*MIB,journal_expanded_bytes=32*MIB,journal_records=4096,
        output_bytes=128*MIB,sampled_rss_bytes=256*MIB,free_disk_bytes=1024*MIB),
    cumulative=dict(http_requests=458,native_http_requests=384,
        aggregate_http_requests=74,aggregate_credits=270,websocket_connections=16,
        collection_seconds=720,owned_wall_seconds=960,output_bytes=512*MIB,control_bytes=8*MIB),
    enforcement=dict(owned_wall='Required owned supervisor; helper validates window/reservations only',
        rss='Sampled process peak threshold; not an allocator hard limit',
        http_bytes='HTTP plaintext before transfer framing; excludes TLS ciphertext and TCP/IP'),
    metadata_only=dict(policy='sport-directed-games-v1',generations=1,
        discovery_only=True,aggregate=False,credentials=False,websockets=False),
    candidate_revisions=dict(scope='app source engineering only',
        protected_files=list(PROTECTED_FILES),source_manifest_required=True,
        reason_required=True,offline_regression_evidence_required=True,
        reserve_before_child_approval=True,reservation_refunds=False),
    forbidden_actions=['direct Novig credentials','direct ProphetX credentials',
        'purchases','trading','outreach','restart of a reserved session'])


def digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def source_manifest():
    files={}
    for p in sorted((ROOT/'app').rglob('*')):
        if not p.is_file() or p.suffix not in ('.py','.js','.html','.css','.json') or '__pycache__' in p.parts:continue
        if p.is_symlink() or not p.resolve().is_relative_to((ROOT/'app').resolve()):
            raise ValueError('Engineering source cannot escape the app directory')
        files[str(p.relative_to(ROOT))]=sha256(p.read_bytes()).hexdigest()
    return files


def controller_hashes():
    return {name:sha256((ROOT/name).read_bytes()).hexdigest() for name in PROTECTED_FILES}


def _same(value, expected):
    # Canonical bytes retain integer/float and boolean distinctions.
    try:return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)==json.dumps(expected,sort_keys=True,separators=(',',':'),allow_nan=False)
    except (ValueError,TypeError):return False


def master_document(output_root, validity_window, initial_manifest=None):
    """Create an inert review document; approval remains a separate owner action."""
    manifest=source_manifest() if initial_manifest is None else deepcopy(initial_manifest)
    if manifest!=source_manifest():raise ValueError('Initial source manifest does not match current app source')
    value=dict(format=VERSION,policy=deepcopy(POLICY),policy_sha256=digest(POLICY),
        output_root=str(Path(output_root).resolve()),validity_window=deepcopy(validity_window),
        initial_source_manifest=manifest,initial_implementation_sha256=digest(manifest),
        protected_controller_sha256=controller_hashes())
    _validate_document(value)
    return value


def _validate_document(value):
    keys={'format','policy','policy_sha256','output_root','validity_window',
          'initial_source_manifest','initial_implementation_sha256','protected_controller_sha256'}
    if not isinstance(value,dict) or set(value)!=keys or value.get('format')!=VERSION:
        raise ValueError('Exact master engineering document required')
    if not _same(value['policy'],POLICY) or value['policy_sha256']!=digest(POLICY):
        raise ValueError('Master engineering limits or roles drifted')
    if value['protected_controller_sha256']!=controller_hashes():
        raise ValueError('Protected master authorization controller changed')
    manifest=value['initial_source_manifest']
    if (not isinstance(manifest,dict) or not manifest or value['initial_implementation_sha256']!=digest(manifest)
        or any(not isinstance(k,str) or not k.startswith('app/') or '..' in Path(k).parts
            or not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v) for k,v in manifest.items())):
        raise ValueError('Immutable initial app source manifest required')
    if not isinstance(value['output_root'],str) or value['output_root']!=str(Path(value['output_root']).resolve()):
        raise ValueError('Canonical exact master output required')
    window=value['validity_window']
    if not isinstance(window,dict) or set(window)!={'start','expires'}:
        raise ValueError('Exact master validity window required')
    if time_value(window['start'])>=time_value(window['expires']):
        raise ValueError('Ordered finite master validity window required')
    return value


def _read_json(path):
    raw=Path(path).read_bytes()
    if len(raw)>POLICY['cumulative']['control_bytes']:raise ValueError('Engineering control storage cap')
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('Duplicate engineering control key')
            result[k]=v
        return result
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite engineering control')))


def validate_master(master_path,approval_path,now=None):
    value=_validate_document(_read_json(master_path));approved=_read_json(approval_path)
    expected=dict(approved=True,master_sha256=digest(value),policy_sha256=value['policy_sha256'],
                  output_root=value['output_root'],validity_window=value['validity_window'])
    if not _same(approved,expected):raise ValueError('Exact owner-approved master, output and window required')
    at=now or datetime.now(timezone.utc)
    if at.tzinfo is None or not time_value(value['validity_window']['start'])<=at<=time_value(value['validity_window']['expires']):
        raise ValueError('Outside master engineering approval window')
    return value


def _validate_session(master,spec,endpoints,kind,now):
    if kind not in ('integrated','metadata'):raise ValueError('Explicit integrated or metadata-only session required')
    if spec.get('mode')!='real' or spec.get('reference_enabled') is not False:
        raise ValueError('Real ordinary source session with reference acquisition disabled required')
    if any(k in spec for k in ('two_source_qualification','supervised_profile','us_metadata_diagnostic')):
        raise ValueError('Historical/diagnostic approvals cannot be extended by the master')
    if validate_transport(spec)!=TRANSPORT_CONTRACT:raise ValueError('Explicit finite shared native transport required')
    result=preflight(spec,now)
    if not result['valid']:raise ValueError('Child preflight failed: '+json.dumps(result['errors']))
    if not time_value(spec['start_after'])<=now<=time_value(spec['start_before']):
        raise ValueError('Outside child session Start window')
    start=time_value(spec['start_after']);end=time_value(spec['start_before'])
    from datetime import timedelta
    if (start<time_value(master['validity_window']['start']) or
        end+timedelta(seconds=POLICY['session']['owned_wall_seconds'])>time_value(master['validity_window']['expires'])):
        raise ValueError('Child session and full owned supervisor duration must fit master window')
    runtime_limits()
    limits=POLICY['session'];p=spec['prediction']
    if (not 0<spec['duration']<=limits['duration_seconds'] or
        p['discovery_requests']>limits['native_http_requests_per_source'] or
        p['connections']>limits['websocket_connections_per_source'] or
        p['session_bytes']>limits['native_source_http_and_stream_bytes']):
        raise ValueError('Child native request/connection/duration/byte ceiling exceeded')
    if any(p[k]!='0' for k in ('dollar_cap_per_source','dollars_per_discovery_request','dollars_per_connection')):
        raise ValueError('Zero additional monetary spend required')
    sources=spec['native_sources']
    if any(sources[v].get('state')!='enabled' for v in ('kalshi','polymarket_us')):
        raise ValueError('Exactly the two approved native sources must be enabled')
    if any(sources[v]!=dict(state='disabled',selected=False) for v in ('novig','prophetx')):
        raise ValueError('Direct Novig/ProphetX native credentials and collection prohibited')
    for v in ('kalshi','polymarket_us'):
        if spec['sources'][v]['credential_reference']!=REFERENCES[v]:
            raise ValueError('Existing dedicated native credential references required')
    expected=deepcopy(ENDPOINTS)
    if kind=='metadata':
        if 'source_session' in spec or spec.get('native_review_records'):
            raise ValueError('Metadata-only session prohibits aggregate acquisition or book reviews')
        from .native_selectors import SPORTS,POLICY as DIRECTED
        probe=deepcopy(spec.get('native_discovery',{}));scopes=probe.pop('native_scopes',None)
        if scopes is not None:
            from .source_session import normalize_native_scopes
            normalize_native_scopes(scopes)
        if probe!=dict(policy=DIRECTED,sports=list(SPORTS),discovery_only=True,generations=1):
            raise ValueError('Exact public single-generation discovery-only session required')
    else:
        if 'native_discovery' in spec or 'source_session' not in spec:
            raise ValueError('Integrated session requires ordinary unified source settings')
        settings=spec['source_session'];a=settings['http']
        from .acquisition_policy import STARTUP,totals
        if (settings.get('quota_startup')!=STARTUP or settings.get('max_cycles')!=3 or
            settings['roles']!=ROLES or settings['event_limit']!=1):
            raise ValueError('Three bounded unified acquisition cycles with fresh quota required')
        t=totals(settings)
        if (t['requests']>limits['aggregate_http_requests'] or t['credits']>limits['aggregate_credits'] or
            a['requests']>limits['aggregate_http_requests'] or a['credits']>limits['aggregate_credits'] or
            a['response_bytes']>limits['aggregate_response_bytes'] or a['session_bytes']>limits['aggregate_session_bytes'] or
            a['retries']!=0 or a['dollars']!='0' or a['dollars_per_credit']!='0'):
            raise ValueError('Aggregate requests/credits/bytes/retries exceed master')
        expected['aggregate']=POLICY['endpoints']['aggregate']
    if endpoints!=expected:raise ValueError('Exact approved provider destinations required')


def _reservation(kind):
    s=POLICY['session'];aggregate=kind=='integrated'
    # Conservative full ceilings are never refunded, including metadata sockets
    # (which are forbidden in execution) and unused source request allowance.
    return dict(http_requests=s['native_http_requests']+(s['aggregate_http_requests'] if aggregate else 0),
        native_http_requests=s['native_http_requests'],aggregate_http_requests=s['aggregate_http_requests'] if aggregate else 0,
        aggregate_credits=s['aggregate_credits'] if aggregate else 0,
        websocket_connections=s['websocket_connections'],collection_seconds=s['duration_seconds'],
        owned_wall_seconds=s['owned_wall_seconds'],
        output_bytes=s['output_bytes'])


def runtime_limits():
    """Read shared effective gates without starting a session or touching secrets."""
    from .continuous import LIMITS
    from . import transport_session
    from .journal_encoding import MAX_EXPANDED
    effective=dict(queue_bytes=transport_session.TRANSPORT_QUEUE_BYTES,
        queue_records=transport_session.TRANSPORT_QUEUE_RECORDS,
        journal_encoded_bytes=transport_session.OBSERVATION_JOURNAL_BYTES,
        journal_expanded_bytes=MAX_EXPANDED,journal_records=transport_session.OBSERVATION_JOURNAL_RECORDS,
        output_bytes=LIMITS['output_bytes'],sampled_rss_bytes=LIMITS['rss_bytes'],free_disk_bytes=LIMITS['free_disk_bytes'])
    if any(type(value) is not int or value!=POLICY['session'][key] for key,value in effective.items()):
        raise ValueError('Shared runtime resource gates changed outside the master limits')
    if (LIMITS['queue_bytes']!=effective['queue_bytes'] or LIMITS['queue_records']!=effective['queue_records'] or
        LIMITS['journal_bytes']!=effective['journal_encoded_bytes'] or LIMITS['journal_records']!=effective['journal_records']):
        raise ValueError('Shared runtime resource descriptions disagree with effective gates')
    return effective


def _ledger(path,master_hash):
    path=Path(path)
    begun=(path.parent/'reservations-started.json').exists()
    if not path.exists():
        if begun or (path.parent/'children').exists():
            raise ValueError('Missing spent engineering reservation ledger; no reset')
        return []
    raw=path.read_bytes()
    if len(raw)>POLICY['cumulative']['control_bytes'] or raw and not raw.endswith(b'\n') or begun and not raw:
        raise ValueError('Uncertain engineering reservation ledger; no restart/refund')
    rows=[];previous=None
    for line in raw.splitlines():
        row=json.loads(line);body={k:v for k,v in row.items() if k!='sha256'}
        if (row.get('sha256')!=digest(body) or row.get('previous_sha256')!=previous or
            row.get('master_sha256')!=master_hash or row.get('kind') not in ('metadata','integrated') or
            row.get('reservation')!=_reservation(row['kind'])):
            raise ValueError('Engineering reservation chain or limits changed')
        rows.append(row);previous=row['sha256']
        totals={k:sum(r['reservation'][k] for r in rows) for k in _reservation('integrated')}
        if (row.get('sequence')!=len(rows) or row.get('cumulative')!=totals or
            row.get('spec_sha256')!=digest(row.get('spec')) or
            row.get('implementation_sha256')!=digest(row.get('source_manifest'))):
            raise ValueError('Engineering source/specification/reservation record changed')
    if len(rows)>POLICY['max_sessions'] or sum(r['kind']=='integrated' for r in rows)>POLICY['max_integrated_sessions']:
        raise ValueError('Engineering reservation count exceeded')
    if len({r['attempt_id'] for r in rows})!=len(rows) or len({r['output'] for r in rows})!=len(rows):
        raise ValueError('Duplicate engineering attempt/output reservation')
    totals={k:sum(r['reservation'][k] for r in rows) for k in _reservation('integrated')}
    if any(v>POLICY['cumulative'][k] for k,v in totals.items()):raise ValueError('Cumulative engineering allowance exceeded')
    return rows


def _write_new(path,value):
    raw=(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    with Path(path).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())


def _fsync_directory(path):
    fd=os.open(path,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def reserve_session(master_path,approval_path,spec,endpoints,*,kind,reason,
                    offline_regression_evidence,attempt_id=None,now=None):
    """Spend a fresh worst-case reservation, then mint its exact child approval.

    The immutable manifest/spec/reason and reservation are durable before the
    child approval exists. A crash after reservation consumes the allowance.
    No function here dispatches, resolves credentials or starts a collection.
    """
    master_path=Path(master_path).resolve();approval_path=Path(approval_path).resolve()
    package=master_path.parent;at=now or datetime.now(timezone.utc)
    master=validate_master(master_path,approval_path,at)
    _validate_session(master,spec,endpoints,kind,at)
    if not isinstance(reason,str) or not 1<=len(reason.strip())<=4096:
        raise ValueError('Concrete bounded engineering/retest reason required')
    if (not isinstance(offline_regression_evidence,list) or not 1<=len(offline_regression_evidence)<=32 or
        any(not isinstance(x,str) or not 1<=len(x)<=2048 for x in offline_regression_evidence)):
        raise ValueError('Offline regression evidence references required before a live reservation')
    identity=attempt_id or str(uuid4())
    if not isinstance(identity,str) or str(UUID(identity))!=identity:raise ValueError('Fresh canonical session UUID required')
    output=Path(master['output_root'])/identity;child=package/'children'/identity
    manifest=source_manifest();master_hash=digest(master)
    if controller_hashes()!=master['protected_controller_sha256']:
        raise ValueError('Protected master authorization controller changed')
    with (package/'reservations.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        # Validate again after owning the reservation boundary.
        validate_master(master_path,approval_path,at)
        rows=_ledger(package/'reservations.jsonl',master_hash)
        if output.exists() or child.exists() or any(r['attempt_id']==identity or r['output']==str(output) for r in rows):
            raise ValueError('Engineering attempt/output already reserved; no restart')
        if len(rows)>=POLICY['max_sessions'] or kind=='integrated' and sum(r['kind']=='integrated' for r in rows)>=POLICY['max_integrated_sessions']:
            raise ValueError('Master engineering session allowance consumed')
        reservation=_reservation(kind)
        cumulative={k:reservation[k]+sum(r['reservation'][k] for r in rows) for k in reservation}
        if any(v>POLICY['cumulative'][k] for k,v in cumulative.items()):raise ValueError('Cumulative engineering allowance exhausted')
        row=dict(format=VERSION,master_sha256=master_hash,sequence=len(rows)+1,
            previous_sha256=rows[-1]['sha256'] if rows else None,attempt_id=identity,output=str(output),
            kind=kind,created_at=at.isoformat(),reason=reason.strip(),
            offline_regression_evidence=deepcopy(offline_regression_evidence),reservation=reservation,
            cumulative=cumulative,source_manifest=manifest,implementation_sha256=digest(manifest),
            effective_runtime_limits=runtime_limits(),
            spec=deepcopy(spec),spec_sha256=digest(spec),endpoints=deepcopy(endpoints),
            state='reserved_uncertain_until_completed; never refunded or restarted')
        row['sha256']=digest(row)
        approval=dict(approved=True,spec_sha256=row['spec_sha256'],implementation_sha256=row['implementation_sha256'],
            output=str(output),attempt_id=identity,engineering_master=dict(master_path=str(master_path),
                approval_path=str(approval_path),master_sha256=master_hash,reservation_sha256=row['sha256'],attempt_id=identity))
        planned=[row,manifest,spec,approval]
        planned_bytes=sum(len(json.dumps(v,indent=2,sort_keys=True).encode())+1 for v in planned)
        retained=sum(p.stat().st_size for p in package.rglob('*') if p.is_file())
        if retained+planned_bytes>POLICY['cumulative']['control_bytes']:raise ValueError('Engineering control storage cap')
        if not rows:
            _write_new(package/'reservations-started.json',dict(master_sha256=master_hash,
                first_attempt_id=identity,reservation_sha256=row['sha256']))
            _fsync_directory(package)
        with (package/'reservations.jsonl').open('ab') as ledger:
            ledger.write((json.dumps(row,sort_keys=True,separators=(',',':'))+'\n').encode())
            ledger.flush();os.fsync(ledger.fileno())
        _fsync_directory(package)
        child.mkdir(parents=True,exist_ok=False)
        _write_new(child/'source-manifest.json',manifest);_write_new(child/'run-spec.json',spec)
        _fsync_directory(child)
        _write_new(child/'approval.json',approval);_fsync_directory(child)
        return dict(attempt_id=identity,output=str(output),approval_path=str(child/'approval.json'),
                    reservation_sha256=row['sha256'],cumulative=cumulative)


def validate_child_approval(approval,spec,endpoints,output,now=None):
    binding=approval.get('engineering_master')
    if not isinstance(binding,dict) or set(binding)!={'master_path','approval_path','master_sha256','reservation_sha256','attempt_id'}:
        raise ValueError('Exact master engineering child binding required')
    master=validate_master(binding['master_path'],binding['approval_path'],now)
    if digest(master)!=binding['master_sha256']:raise ValueError('Master engineering binding changed')
    rows=_ledger(Path(binding['master_path']).parent/'reservations.jsonl',digest(master))
    selected=[r for r in rows if r['sha256']==binding['reservation_sha256'] and r['attempt_id']==binding['attempt_id']]
    if len(selected)!=1:raise ValueError('Child has no exact durable master reservation')
    row=selected[0]
    if (row['spec_sha256']!=digest(spec) or row['implementation_sha256']!=digest(source_manifest()) or
        row['endpoints']!=endpoints or row['output']!=str(Path(output).resolve()) or
        approval.get('attempt_id')!=row['attempt_id'] or approval.get('spec_sha256')!=row['spec_sha256'] or
        approval.get('implementation_sha256')!=row['implementation_sha256'] or approval.get('output')!=row['output']):
        raise ValueError('Child candidate, specification, provider or destination changed after reservation')
    _validate_session(master,spec,endpoints,row['kind'],now or datetime.now(timezone.utc))
    return row
