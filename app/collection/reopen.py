"""Verify exported evidence without a database or transport."""
import json
from pathlib import Path
from hashlib import sha256
from app.pricing.baseline import restore as price_restore
from app.opportunities.service import restore as audit_restore, replay
from app.reference.records import import_records, as_of


def reopen(path):
    path=Path(path)
    manifest=json.loads((path/'manifest.json').read_text())
    if len(manifest)>131 or sum((path/name).stat().st_size for name in manifest if Path(name).name==name)>512*1024*1024:raise ValueError('saved reopening capacity exceeded')
    for name,h in manifest.items():
        if Path(name).name!=name or sha256((path/name).read_bytes()).hexdigest()!=h:raise ValueError('saved evidence identity mismatch')
    session=json.loads((path/'session.json').read_text())
    refs=import_records((path/'references.json').read_text())
    snapshots=[]
    for row in session['calculations']:
        from .context import validate_context
        validate_context(row.get('session_context'),row['cutoff'])
        estimate=price_restore((path/(row['estimate']+'.estimate.json')).read_text())
        if estimate.id!=row['estimate'] or as_of(refs,row['cutoff'])!=estimate.data['dependencies']:raise ValueError('saved reference dependency mismatch')
        audit=None
        if row['audit']:
            audit=audit_restore((path/(row['audit']+'.audit.json')).read_text())
            if audit.id!=row['audit'] or audit.data['inputs']['estimate']!=estimate.export():raise ValueError('saved calculation dependency mismatch')
            if replay(audit).export()!=audit.export():raise ValueError('calculation replay differs')
            for book in audit.data['inputs']['market']['books']:
                matches=[event['detail']['e6_ingress'] for event in session['events'] if event['detail'].get('e6_ingress',{}).get('kind')=='prediction' and event['detail']['e6_ingress']['value']['id']==book['id']]
                # Dependencies from earlier sessions may be present only in the complete audit.
                if not matches or any(x['value']!=book for x in matches):raise ValueError('book missing from captured delivery ledger')
        snapshots.append(dict(session_context=row.get('session_context'),cutoff=row['cutoff'],estimate=estimate.data,audit=None if audit is None else audit.data))
    return dict(synthetic=True,state=session['session']['state'],id=session['session']['id'],counts=session['counts'],
                coverage='Saved delivered snapshots; gaps are unobserved intervals, never filled',
                calculations=len(snapshots),snapshots=snapshots,events=session['events'])
