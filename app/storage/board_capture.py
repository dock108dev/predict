"""Bound and schedule complete matching components before decoding publications."""
from .store import stamp
from . import observation_publication as publication


SOURCE_PREVIOUS = """jsonb_build_object(
    'publication_dependencies',facts->'publication_dependencies',
    'selection_frame_available',facts->'selection_frame_available',
    'observation_binding',facts->'observation_binding',
    'observation_valid_until',facts->'observation_valid_until',
    'valid_until',facts->'valid_until')"""


def capture_reservation(db, *, observations_only=False, event_ids=None):
    """Bound decoded captures before reading JSON or hydrated depth rows."""
    previous=SOURCE_PREVIOUS if observations_only else 'facts'
    size=db.execute('''SELECT COALESCE(sum(n),0) AS n FROM (
        SELECT octet_length(facts::text) n FROM current_event
        UNION ALL SELECT octet_length(e.facts::text)+octet_length(c.facts::text)+octet_length(o.facts::text)
            FROM current_contract c JOIN current_offer o ON o.contract_id=c.id JOIN current_event e ON e.id=c.event_id
            WHERE (%s::text[] IS NULL OR c.event_id=ANY(%s))
        UNION ALL SELECT octet_length(('''+previous+''')::text) FROM latest_board
            WHERE (%s::text[] IS NULL OR latest_board.publication_events ?| %s)
        UNION ALL SELECT octet_length(facts::text) FROM latest_board_status) inputs''',
        (event_ids,event_ids,event_ids,event_ids)).fetchone()['n']
    # Hydration keeps exact decimal strings and Python containers. Reserve for
    # selected asks only, with the same conservative bound as selected reads.
    depth=db.execute('''SELECT COALESCE(sum(n),0) AS n FROM (
        SELECT 2048 n FROM current_native_depth WHERE side='asks' AND (%s::text[] IS NULL OR event_id=ANY(%s))
        UNION ALL SELECT 2048 FROM current_depth d JOIN current_contract c ON c.id=d.contract_id
            WHERE side='asks' AND (%s::text[] IS NULL OR c.event_id=ANY(%s))) levels''',
        (event_ids,event_ids,event_ids,event_ids)).fetchone()['n']
    # Full alternate games peak near 456 MB in the isolated measured pipeline:
    # resolution, selected evidence and compaction overlap transiently. Encoded
    # source bytes alone at 8x under-reserved that overlap and could kill ingress.
    required=int(size)*32+int(depth)+64*1024*1024
    # Reserve complete MiB pages so ordinary receipt-size changes do not cause
    # needless admission retries; every byte of padding remains charged.
    return ((required+1024*1024-1)//(1024*1024))*1024*1024


def capture_batches(db):
    """Partition complete possible-peer components before decoding contracts.

    Packing is deliberately bounded below the source runway. A large component
    gets its own admission decision; it cannot defer healthy components.
    """
    index=publication.identity_index(db);remaining=set(index['active_events']);groups=[]
    while remaining:
        from app.comparison.calculation_control import checkpoint
        checkpoint()
        seed=min(remaining)
        ids=[row[0] for row in publication.neighborhood(index,dict(events=[seed],occurrences=[],shared=[]))]
        if seed not in ids:raise ValueError('publication_component_membership_inconsistent')
        remaining.difference_update(ids)
        groups.append(ids)
    return groups


def prioritize_sources(db, batches, at):
    """Prioritize one recent source/confirmation per venue, then ordinary rotation.

    This is scheduling only. Rendering still validates confirmations, original
    source age, complete outcomes and source authority under the same policy.
    """
    recent=db.execute('''SELECT c.event_id,c.venue,
        max(greatest(o.source_at::timestamptz,
            (o.facts#>>'{book_confirmation,confirmed_at}')::timestamptz))::text receipt
        FROM current_offer o JOIN current_contract c ON c.id=o.contract_id
        WHERE c.venue IN ('kalshi','polymarket_us') GROUP BY c.event_id,c.venue''').fetchall()
    clocks={}
    for row in db.execute("SELECT publication_events members,observation_as_of published_at FROM latest_board").fetchall():
        for eid in row['members'] or []:clocks[eid]=row['published_at'] or ''
    selected=[]
    for venue in ('kalshi','polymarket_us'):
        hot={r['event_id']:stamp(r['receipt']) for r in recent if r.get('venue',venue)==venue and r['receipt']
             and 0<=(stamp(at)-stamp(r['receipt'])).total_seconds()<=30}
        candidates=[(-max(hot[eid].timestamp() for eid in ids if eid in hot),
                     min(clocks.get(eid,'') for eid in ids if eid in hot),i)
                    for i,ids in enumerate(batches) if ids and hot.keys() & set(ids)]
        if candidates:
            index=min(candidates)[2]
            if index not in selected:selected.append(index)
    return [*(batches[i] for i in selected),*(ids for i,ids in enumerate(batches) if i not in selected)]


def prioritize_pending(db,batches):
    """Committed first-calculation backlog precedes already evaluated work.

    Keep the rotated order within both populations. Completed publications survive
    an auxiliary child's cancellation, unlike its in-memory turn result.
    """
    pending=set()
    for row in db.execute("""SELECT publication_events members FROM latest_board
            WHERE facts#>>'{estimate_availability,state}'='pending'""").fetchall():
        pending.update(row['members'] or [])
    return sorted(batches,key=lambda ids:not bool(pending.intersection(ids or [])))



