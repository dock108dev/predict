"""Read and fingerprint the exact dependencies of ordinary result packets."""

from datetime import timedelta
from hashlib import sha256
from itertools import chain

from .store import encoded, hashed

DEPENDENCY_BATCH = 2048
REFERENCE_PREFIX = 'sgo-reference:'
CATALOG_PREFIX = 'sgo-native-catalog:novig:'


def offer_dependency_query(event_ids, *, frames, at, offer_ids=None, limit=None):
    frame_join = 'LEFT JOIN frame_revisions f ON f.id=e.id' if frames else ''
    receipt = "concat(o.revision,':',o.received_at,':',coalesce(f.revision,''))" if frames else "concat(o.revision,':',o.received_at)"
    if event_ids is None:
        scope = 'scheduled_start::timestamptz >= %s AND scheduled_start::timestamptz < %s'
        params = (at-timedelta(hours=24), at+timedelta(hours=72))
    else:
        scope = 'id=ANY(%s)'
        params = (event_ids,)
    if offer_ids is not None:
        scope += ' AND id IN (SELECT event_id FROM current_contract WHERE id=ANY(%s))'
        params += (offer_ids,)
    offers = 'WHERE c.id=ANY(%s)' if offer_ids is not None else ''
    if offer_ids is not None:
        params += (offer_ids,)
    bound = ' LIMIT %s' if limit is not None else ''
    if limit is not None:
        params += (limit,)
    # Extract the SGO frame digest once per event. Inlining this extraction
    # would repeatedly detoast each large membership packet for every offer.
    frame_cte = """, frame_revisions AS MATERIALIZED (
        SELECT e.id, f.facts->>'receipt_sha256' revision
        FROM events e JOIN current_sgo_event_frame f ON f.event_id=e.native_event_id
        WHERE e.provider='sportsgameodds')""" if frames else ''
    query = '''WITH events AS (
        SELECT id, revision, provider, native_event_id FROM current_event WHERE '''+scope+''')'''+frame_cte+'''
        SELECT c.id, e.id AS event_id, '''+receipt+''' receipt,
        o.price_dependency price,
        c.revision contract,
        e.revision event FROM current_offer_storage o JOIN current_contract c ON c.id=o.contract_id
        JOIN events e ON e.id=c.event_id
        '''+frame_join+'''
        '''+offers+''' ORDER BY c.id COLLATE "C"'''+bound
    return query, params


def dependency_value(row):
    # Receipt-only confirmations schedule new proof without invalidating
    # identical captured economics or extending its deadline.
    return [row['price'], row['contract'], row['event'], row['receipt']]


def dependency_signatures(entries):
    """Reduce an ordered evidence stream to two fixed-size digests per event."""
    signatures = {}
    for event, key, value in entries:
        if event not in signatures:
            signatures[event] = (sha256(), sha256())
        receipt, material = signatures[event]
        receipt.update(encoded((key, value)) + b'\n')
        material.update(encoded((key, value[:3])) + b'\n')
    return {event: (receipt.hexdigest(), material.hexdigest())
            for event, (receipt, material) in signatures.items()}


def planning_signatures(db, event_ids, *, frames, at, reference_dependencies):
    from app.comparison.calculation_control import checkpoint
    from .sgo_native_catalog import dependencies as catalog_dependencies

    def offer_rows(cursor):
        while rows := cursor.fetchmany(DEPENDENCY_BATCH):
            checkpoint()
            yield from rows

    # Contract IDs are hex digests and sort before the prefixed SGO keys.
    extra = sorted(chain(reference_dependencies(db, event_ids, at=at), catalog_dependencies(db, event_ids, at=at)),
                   key=lambda row: row['id']) if frames else ()
    with db.cursor(name='ordinary_planning_dependencies') as cursor:
        cursor.execute(*offer_dependency_query(event_ids, frames=frames, at=at))
        return dependency_signatures((row['event_id'], row['id'], dependency_value(row))
                                     for row in chain(offer_rows(cursor), extra))


def published_dependencies(db, result, *, frames, at, reference_dependencies):
    """Resolve only evidence named in the published revision, in indexed batches."""
    witnesses = {}
    for row in result['rows']:
        authority = row['current_authority']
        for proof in (authority['price'], *authority['references'], authority.get('sgo_native_contract')):
            if proof and (key := proof.get('dependency')):
                witnesses[key] = witnesses.get(key, False) or bool(proof.get('exact_frame'))
    offers = sorted(key for key in witnesses if not key.startswith((REFERENCE_PREFIX, CATALOG_PREFIX)))
    current = {}
    for offset in range(0, len(offers), DEPENDENCY_BATCH):
        query = offer_dependency_query(None, frames=frames, at=at,
                                       offer_ids=offers[offset:offset+DEPENDENCY_BATCH])
        current.update((row['id'], dependency_value(row)) for row in db.execute(*query))
    if frames:
        from .sgo_native_catalog import dependencies as catalog_dependencies
        references = [key.removeprefix(REFERENCE_PREFIX) for key in witnesses if key.startswith(REFERENCE_PREFIX)]
        catalog = [key.removeprefix(CATALOG_PREFIX) for key in witnesses if key.startswith(CATALOG_PREFIX)]
        if references:
            current.update((row['id'], dependency_value(row))
                           for row in reference_dependencies(db, at=at, reference_ids=references))
        if catalog:
            current.update((row['id'], dependency_value(row)) for row in catalog_dependencies(db, at=at, native_ids=catalog))
    revision = hashed({key: value if witnesses[key] else value[:3] for key, value in current.items()})
    return current, revision


def capture_structure_ids(deps):
    # Membership first. Contract/event fingerprints cover the same keyed
    # sequence and can reject a successor without loading its original packet.
    keys=sorted(deps)
    return dict(offer_membership=hashed(keys),contract_revision=hashed([deps[k][1] for k in keys]),
                event_revision=hashed([deps[k][2] for k in keys]))


def governing_fields(binding):
    policy,settings,epoch,controls,sources=binding
    return dict(policy=policy,settings=settings,epoch=epoch,
                **{'owner.'+key:value for key,value in controls.items()},
                **{'source.'+key:value for key,value in sources.items()})


def component_binding(binding,venues):
    """Only sources present in this exact contract component govern its reuse."""
    return [*binding[:4],{venue:binding[4].get(venue) for venue in sorted(set(venues))}]
