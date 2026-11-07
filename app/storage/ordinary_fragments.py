"""Immutable member projections shared by roots, inside the publication owner.

A root is a bounded manifest, never a chain of patches. Reads resolve all exact
members in one MVCC query. Existing member/lease FKs protect every fragment.
"""
from . import comparison_snapshot as snapshots

FIELDS=('rows','pairs','games','references','issues')
VERSION='ordinary-member-fragments-1'


class FragmentRoot(dict):
    """An exact lazy manifest read, eligible for the single-root reader cache."""


def expand(result,db,*,lazy,previous=None):
    ids=result.pop('_read_fragments')
    if len(ids)>32768 or len(ids)!=len(set(ids)):
        raise snapshots.SnapshotOperationError('ordinary_fragment_manifest_invalid')
    prior=previous.get('component_slices',{}) if lazy and isinstance(previous,FragmentRoot) else {}
    reused=set(ids)&prior.keys()
    # Check every member's presence in this MVCC frame, even for a cache hit.
    # An immutable member ID binds the exact original content. Avoid fetching
    # and decoding that content again from the immediately preceding root.
    blobs={r['member_id']:r['content'] for r in db.execute(
        'SELECT member_id,CASE WHEN member_id=ANY(%s) THEN NULL ELSE content END content '
        'FROM comparison_live_read_fragment WHERE member_id=ANY(%s)',(list(reused),ids))}
    if len(blobs)!=len(ids):raise snapshots.SnapshotOperationError('ordinary_fragment_unavailable')
    result['component_slices']={}
    for member in ids:
        content=blobs.pop(member)
        if member in reused:
            old=prior[member]
            part={field:previous[field][old[field][0]:old[field][1]] for field in FIELDS}
            part.update(id=member,captured_at=old['captured_at'],sources=old['sources'],
                publication=dict(finance=old['finance']))
        else:part=snapshots._decode(content)
        if part['id']!=member:raise snapshots.SnapshotOperationError('ordinary_fragment_identity')
        offsets={field:len(result[field]) for field in FIELDS}
        for field in FIELDS:result[field].extend(part[field])
        result['sources'].update(part['sources'])
        result['component_slices'][member]=dict(captured_at=part['captured_at'],sources=part['sources'],
            finance=part['publication']['finance'],**{f:[offsets[f],len(result[f])] for f in FIELDS})
    return FragmentRoot(result) if lazy else result
