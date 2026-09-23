"""Pending/eliminated championship evidence is distinct from a declared award."""
from app.resolution.core import revision_error

def sporting_error(p):
    if p.get('status') not in ('pending','eliminated','final','cancelled','administrative_change','unknown'):return 'Unsupported championship status'
    reason=revision_error(p,'championship')
    if reason:return reason
    e=p['target']['event']
    if p['status']=='eliminated':
        if not isinstance(p.get('eliminated'),list) or not p['eliminated'] or any(cid not in e['field'] for cid in p['eliminated']):return 'Missing explicitly eliminated field participant'
    if p['status']=='final':
        if p.get('completion')!='official_championship_awarded' or p.get('award_basis')!='declared_by_governing_body' or p.get('winning_state') not in {v['id'] for v in e['states']}:return 'Missing exact declared championship state; standings and projections are not awards'
    return None
