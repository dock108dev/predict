"""Format-aware immutable saved readers. Validation precedes publication."""
import json
from pathlib import Path
from app.dashboard.e6_live import digest
from app.collection.transport_session import reopen
from app.collection.segmented import SegmentedReader
from app.dashboard.session_projection import SessionProjection


def verified(folder):
    folder=Path(folder); path=folder/'manifest.json'
    manifest=json.loads(path.read_text()) if path.exists() else None
    if manifest and 'report.json' not in manifest['files']:
        from app.dashboard.multi_game import saved_rows
        return saved_rows(folder)
    allowed={'run-spec.json','aggregate-limits.json','report.json','replay.json','history/manifest.json',folder.name+'.jsonl'}
    if manifest:
        if set(manifest['files'])-allowed or not {'run-spec.json','report.json','replay.json','aggregate-limits.json'}<=set(manifest['files']): raise ValueError('invalid coverage package')
        for name,h in manifest['files'].items():
            if (folder/name).is_symlink() or digest(folder/name)!=h: raise ValueError('saved file changed')
    if (folder/'storage-failure.json').exists():raise ValueError('persistence failed; unacknowledged tail is not publishable')
    if (folder/'report.json').exists():
        report=json.loads((folder/'report.json').read_text())
        if report.get('outcome',{}).get('persistence_error'):raise ValueError('persistence failed; verified recovery required')
    segmented=(folder/'history/manifest.json').exists()
    if manifest and ('history/manifest.json' if segmented else folder.name+'.jsonl') not in manifest['files']:raise ValueError('primary journal absent from manifest')
    if segmented:
        reader=SegmentedReader(folder/'history')
        # Reader verifies the entire chain before yielding; bounded reducer consumes it.
        rows=reader.rows(allow_interrupted=not bool(manifest))
        state='complete' if manifest else 'interrupted'
    else:
        saved=reopen(folder/(folder.name+'.jsonl')); rows=iter(saved['rows']); state=saved['state']
        if manifest and (saved['sha256']!=manifest['journal_chain'] or state!='complete'): raise ValueError('coverage journal identity mismatch')
    if not manifest: state='interrupted'
    if manifest:
        report=json.loads((folder/'report.json').read_text())
        if not report.get('cleanup_complete') or report.get('outcome',{}).get('status','complete')!='complete' or (folder/'finalization-failure.json').exists(): raise ValueError('incomplete finalization')
        replay=json.loads((folder/'replay.json').read_text())
        if replay.get('verified') is False: raise ValueError('native replay incomplete')
    return dict(rows=rows,state=state)


def project_rows(rows,through_cursor=None):
    p=SessionProjection(); selected=None
    for row in rows:
        p.apply(row)
        token=str(p.cursor)+'-'+p.chain
        if through_cursor==token: selected=p.snapshot(mode='saved')
    if through_cursor:
        if selected is None: raise ValueError('Unknown cutoff')
        return selected
    return p.snapshot(mode='saved')


def load(folder,through_cursor=None):
    data=verified(folder)
    result=project_rows(data['rows'],through_cursor)
    if result['session_id']!=Path(folder).name:raise ValueError('saved session identity mismatch')
    result['state']='saved' if data['state']=='complete' and 'failure' not in (result['stop_reason'] or '') else 'incomplete'
    return result


def list_sessions(roots):
    found={}
    for root in roots:
        for p in sorted(Path(root).glob('*/run-spec.json'),key=lambda p:p.stat().st_mtime):
            found[p.parent.name]=p.parent
    return found
