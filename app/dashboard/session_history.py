"""Format-aware immutable saved readers. Validation precedes publication."""
import json
from pathlib import Path
from app.dashboard.e6_live import digest
from app.collection.transport_session import reopen
from app.collection.segmented import SegmentedReader
from app.dashboard.session_projection import SessionProjection


def _flat_stream(path, manifest=None, nested_spec=None):
    """Verify a legacy flat chain before yielding, without retaining all books."""
    from hashlib import sha256
    from app.collection.transport_session import OBSERVATION_JOURNAL_BYTES, OBSERVATION_JOURNAL_RECORDS
    from app.collection.journal_encoding import decode, MAX_EXPANDED, packed_size
    from app.reference.records import packed
    from app.collection.recovery import signature
    def scan():
        previous='0'*64; expanded=count=0
        if path.stat().st_size>min(64*1024*1024,OBSERVATION_JOURNAL_BYTES):raise ValueError('saved byte cap')
        with path.open('rb') as stream:
            for line in stream:
                if count>=OBSERVATION_JOURNAL_RECORDS or not line.endswith(b'\n'):raise ValueError('incomplete or overbound journal')
                value=json.loads(line); digest=sha256((previous+packed(value['row'])).encode()).hexdigest()
                if value['previous']!=previous or value['sha256']!=digest:raise ValueError('saved hash chain mismatch')
                row=decode(value['row']); expanded+=packed_size(row); count+=1;previous=digest
                if expanded>MAX_EXPANDED:raise ValueError('saved expanded byte cap')
                del value, line
                yield row, previous
                del row
    before=signature(path.stat());first=last_type=None;chain='0'*64
    for row,chain in scan():
        if first is None:first=row
        last_type=row['type']
        del row
    state='complete' if last_type=='session_finished' else 'interrupted'
    if nested_spec is not None and (not first or first['type']!='session_started' or first['session_id']!=path.stem or first['spec']!=nested_spec):raise ValueError('Legacy native session specification differs')
    if manifest and (chain!=manifest['journal_chain'] or state!='complete'):raise ValueError('coverage journal identity mismatch')
    def rows():
        for row,_ in scan():
            yield row
            del row
        if before!=signature(path.stat()):raise ValueError('history changed during replay')
    return dict(rows=rows(),state=state)


def verified(folder, *, stream_flat=False):
    folder = Path(folder)
    path = folder / 'manifest.json'
    nested=list((folder/'session').glob('*.jsonl')) if (folder/'session').is_dir() else []
    if not path.exists() and len(nested)==1 and (folder/'run-spec.json').exists():
        if nested[0].stat().st_size>64*1024*1024:raise ValueError('Flat saved session exceeds read limit')
        if stream_flat:return _flat_stream(nested[0],nested_spec=json.loads((folder/'run-spec.json').read_text()))
        saved=reopen(nested[0]);first=saved['rows'][0]
        if first['type']!='session_started' or first['session_id']!=nested[0].stem or first['spec']!=json.loads((folder/'run-spec.json').read_text()):raise ValueError('Legacy native session specification differs')
        return dict(rows=iter(saved['rows']),state=saved['state'])
    manifest = json.loads(path.read_text()) if path.exists() else None
    if manifest and 'report.json' not in manifest['files']:
        from app.dashboard.multi_game import saved_rows
        return saved_rows(folder)

    allowed = {
        'run-spec.json', 'aggregate-limits.json', 'report.json',
        'replay.json', 'history/manifest.json', folder.name + '.jsonl',
    }
    if manifest:
        if (
            set(manifest['files']) - allowed
            or not {'run-spec.json', 'report.json', 'replay.json', 'aggregate-limits.json'}
            <= set(manifest['files'])
        ):
            raise ValueError('invalid coverage package')
        for name, h in manifest['files'].items():
            if (folder / name).is_symlink() or digest(folder / name) != h:
                raise ValueError('saved file changed')

    if (folder / 'storage-failure.json').exists():
        raise ValueError('persistence failed; unacknowledged tail is not publishable')
    if (folder / 'report.json').exists():
        report = json.loads((folder / 'report.json').read_text())
        if report.get('outcome', {}).get('persistence_error'):
            raise ValueError('persistence failed; verified recovery required')

    segmented = (folder / 'history/manifest.json').exists()
    if (
        manifest
        and ('history/manifest.json' if segmented else folder.name + '.jsonl')
        not in manifest['files']
    ):
        raise ValueError('primary journal absent from manifest')

    if segmented:
        reader = SegmentedReader(folder / 'history')
        # Reader verifies the entire chain before yielding; the reducer is bounded.
        rows = reader.rows(allow_interrupted=not bool(manifest))
        state = 'complete' if manifest else 'interrupted'
    else:
        # Flat reopening materializes records: check size before allocation.
        # Preserve older files; new long sessions use segmented storage.
        if (folder / (folder.name + '.jsonl')).stat().st_size > 64 * 1024 * 1024:
            raise ValueError(
                'Flat saved session exceeds the 64 MiB read limit; original file preserved. '
                'Use segmented storage for new long sessions.'
            )
        saved = _flat_stream(folder/(folder.name+'.jsonl'),manifest) if stream_flat else reopen(folder / (folder.name + '.jsonl'))
        rows = saved['rows'] if stream_flat else iter(saved['rows'])
        state = saved['state']
        if not stream_flat and manifest and (saved['sha256'] != manifest['journal_chain'] or state != 'complete'):
            raise ValueError('coverage journal identity mismatch')

    if not manifest:
        state = 'interrupted'
    if manifest:
        report = json.loads((folder / 'report.json').read_text())
        if (
            not report.get('cleanup_complete')
            or report.get('outcome', {}).get('status', 'complete') != 'complete'
            or (folder / 'finalization-failure.json').exists()
        ):
            raise ValueError('incomplete finalization')
        replay = json.loads((folder / 'replay.json').read_text())
        if replay.get('verified') is False:
            raise ValueError('native replay incomplete')
    return dict(rows=rows, state=state)


def project_rows(rows, through_cursor=None, native_interpretation="native-book-comparison-4"):
    p = SessionProjection()
    if native_interpretation not in ("original","native-book-comparison-2","native-book-comparison-3","native-book-comparison-4"):raise ValueError("Unknown native interpretation version")
    p.native_interpretation=native_interpretation
    selected = None
    for row in rows:
        p.apply(row)
        token = str(p.cursor) + '-' + p.chain
        if through_cursor == token:
            selected = p.snapshot(mode='saved')
    if through_cursor:
        if selected is None:
            raise ValueError('Unknown cutoff')
        return selected
    return p.snapshot(mode='saved')


def load(folder, through_cursor=None, native_interpretation="native-book-comparison-4"):
    data = verified(folder)
    if native_interpretation=='native-book-comparison-4':
        from app.dashboard.native_reviews import packaged_index
        from app.dashboard.session_projection import stable
        index=packaged_index()
        bound=next((v for v in index.get('historical_paths',{}).values() if (Path(__file__).resolve().parents[2]/v['folder']).resolve()==Path(folder).resolve()),None) if index is not None else None
        chain=['0'*64]
        original_rows=data['rows']
        def anchored_rows():
            for row in original_rows:
                chain[0]=stable([chain[0],row]);yield row
        result=project_rows(anchored_rows(),through_cursor,native_interpretation)
        if bound and chain[0]!=bound['product_chain']:raise ValueError('Retained native historical source chain differs from sealed review index')
    else:result = project_rows(data['rows'], through_cursor, native_interpretation)
    if result['session_id'] != Path(folder).name and not (Path(folder)/'session'/(result['session_id']+'.jsonl')).is_file():
        raise ValueError('saved session identity mismatch')
    result['state'] = (
        'saved'
        if data['state'] == 'complete' and 'failure' not in (result['stop_reason'] or '')
        else 'incomplete'
    )
    return result


def list_sessions(roots):
    found = {}
    for root in roots:
        for p in sorted(Path(root).glob('*/run-spec.json'), key=lambda p: p.stat().st_mtime):
            found[p.parent.name] = p.parent
    return found


EMPTY_RESOLUTION_INDEX=Path(__file__).resolve().parents[1]/'fixtures/retained-empty-resolution-index-v1.json'


def _retained_empty_resolution(folder):
    """A verified negative fact, valid only while every source file stays exact.

    This avoids decoding unrelated native price payloads to prove zero resolution
    rows again. It never indexes a positive resolution or bypasses price replay.
    Unknown, modified, incomplete and unindexed captures use the full reader.
    """
    from hashlib import sha256
    from app.dashboard.session_projection import stable
    root=Path(__file__).resolve().parents[2];folder=Path(folder)
    try:key=str(folder.resolve().relative_to(root))
    except ValueError:return None
    if not EMPTY_RESOLUTION_INDEX.exists():return None
    if EMPTY_RESOLUTION_INDEX.stat().st_size>256*1024:raise ValueError('Empty resolution index bound')
    index=json.loads(EMPTY_RESOLUTION_INDEX.read_text())
    if index.get('version')!='retained-empty-resolutions-1' or index.get('collection_authorized') is not False or index.get('sha256')!=stable({k:v for k,v in index.items() if k!='sha256'}):raise ValueError('Empty resolution index seal conflict')
    row=index.get('entries',{}).get(key)
    if not row:return None
    if row.get('resolution_records')!=0 or row.get('state')!='complete':raise ValueError('Invalid negative resolution fact')
    paths={str(p.relative_to(folder)):p for p in folder.rglob('*') if p.is_file()}
    if set(paths)!=set(row['files']):return None
    for name,path in paths.items():
        if path.is_symlink() or path.stat().st_size>64*1024*1024:return None
        digest=sha256()
        with path.open('rb') as stream:
            while chunk:=stream.read(65536):digest.update(chunk)
        if digest.hexdigest()!=row['files'][name]:return None
    return dict(records=[],state='complete',options=[])


def resolution_history(folder, through_cursor=None):
    """Read the existing verified journal, without reprojecting postgame books.

    Prefix token uses the same durable cursor algorithm as SessionProjection.
    No sidecar journal or mutation of completed packages is involved.
    """
    from app.dashboard.session_projection import stable
    from app.resolution.core import validate, MAX_RECORDS

    negative=_retained_empty_resolution(folder) if through_cursor is None else None
    if negative is not None:return negative
    data = verified(folder,stream_flat=True)
    chain = '0' * 64
    records = {}
    options = []
    selected = None
    sid = None
    mode = None
    finished = False
    for cursor, row in enumerate(data['rows'], 1):
        if finished:
            raise ValueError('Observation after terminal')
        if row['type'] == 'session_started':
            sid = row['session_id']
            mode = row['spec']['mode']
        if row['session_id'] != sid or (sid != Path(folder).name and not (Path(folder)/'session'/(sid+'.jsonl')).is_file()):
            raise ValueError('Resolution journal identity mismatch')

        # Same token bytes as stable(), without a run-sized serialization buffer.
        from hashlib import sha256
        token_hash=sha256()
        for chunk in json.JSONEncoder(sort_keys=True,separators=(',',':')).iterencode([chain,row]):
            token_hash.update(chunk.encode())
        chain = token_hash.hexdigest()
        token = str(cursor) + '-' + chain
        if row['type'] == 'product_resolution':
            r = row['resolution']
            validate(r)
            if mode != 'mock' and r['evidence_mode'] == 'synthetic':
                raise ValueError('Synthetic resolution in real session')
            if r['id'] not in records:
                records[r['id']] = dict(record=r, observed_at=row['observed_at'], cursor=cursor)
            if len(records) > MAX_RECORDS:
                raise ValueError('Resolution bound')
            options.append(dict(
                cutoff=token,
                as_of=row['observed_at'],
                label=(
                    r['kind'] + ' · ' + str(r['payload'].get('status', 'unknown'))
                    + (' · correction' if r['payload']['supersedes'] else '')
                ),
                targets=[{k:t.get(k) for k in ('session_id','game_id','prediction_cutoff')} for v in records.values() if (t:=v['record']['payload'].get('target'))],
            ))
        if token == through_cursor:
            selected = list(records.values())
        if row['type'] == 'session_finished':
            finished = True
        del row
    if through_cursor and selected is None:
        raise ValueError('Unknown resolution cutoff')
    return dict(
        records=selected if through_cursor else list(records.values()),
        options=options,
        state=data['state'],
    )
