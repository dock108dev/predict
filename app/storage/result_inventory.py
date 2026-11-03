"""Independent discovered population and restart-safe fair unit visit order.

This is an inventory proof, not a cached calculation or a currentness grant.
Quote prices are excluded from structural roster proofs except for references,
whose complete selection universe remains conservatively bound.
"""
from psycopg.types.json import Jsonb
from .store import encoded, hashed
from . import observation_publication as publication
from . import result_dependencies as dependencies
from .current_games import observation_binding

MAX_BYTES = 8 * 1024 * 1024


def proof(frame, selector, *, engine, policy, owner=None):
    neighborhood=publication.neighborhood(frame,selector)
    boundaries=[frame['events'][row[0]]['start'] for row in neighborhood if frame['events'][row[0]].get('start')]
    from .store import stamp
    return dict(version='result-inventory-1',epoch=frame['epoch'],selector=selector,
        matching=hashed(neighborhood),valid_until=min(boundaries,key=stamp) if boundaries else None,owner=owner,
        roster=dependencies.roster(frame,selector),engine=engine,policy=policy,
        observation_binding=observation_binding(),control=frame.get('control_barrier'))


def current(frame, saved, *, engine, policy, owner, at):
    from .store import stamp
    return (saved==proof(frame,saved['selector'],engine=engine,policy=policy,owner=owner)
        and (not saved.get('valid_until') or stamp(at)<stamp(saved['valid_until'])))


def record(db, bundle, units, saved):
    """Commit before the first calculation, including all-deferred inventories.

    One financial owner performs writes; the timestamp guard also refuses an
    obsolete capture. Revisions reconcile unit identities, never cursor offsets.
    Removed entries retain their visit history and an explicit disposition.
    """
    revision=hashed([saved,units]);size=len(encoded([saved,units]))
    if size>1024*1024:raise ValueError('result_inventory_capacity')
    from app.collection.current_storage_policy import require_disk_space, sql_usage, SQL_BYTE_CAP
    from .store import ROOT
    append=size+512*len(units)
    require_disk_space(ROOT/'.local/postgres',append_bytes=append)
    with db.transaction():
        if sql_usage(db)+append>=SQL_BYTE_CAP:raise ValueError('current_database_storage_cap')
        total=db.execute('''SELECT COALESCE(sum(octet_length(dependencies::text)+octet_length(units::text)),0) n
            FROM current_result_inventory WHERE game_key<>%s''',(bundle['game_key'],)).fetchone()['n']
        if total+size>MAX_BYTES:raise ValueError('result_inventory_capacity')
        updated=db.execute('''INSERT INTO current_result_inventory
            (game_key,discovered_at,revision,events,dependencies,units) VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT(game_key) DO UPDATE SET discovered_at=excluded.discovered_at,
                revision=excluded.revision,events=excluded.events,dependencies=excluded.dependencies,units=excluded.units,
                superseded_at=NULL,superseded_by=NULL
            WHERE current_result_inventory.discovered_at<=excluded.discovered_at
                AND (current_result_inventory.superseded_at IS NULL OR current_result_inventory.superseded_at<excluded.discovered_at)
            RETURNING revision''',
            (bundle['game_key'],bundle['as_of'],revision,Jsonb(saved['selector']['events']),Jsonb(saved),Jsonb(units))).fetchone()
        if not updated:raise ValueError('result_inventory_capture_obsolete')
        wanted=[u['id'] for u in units]
        db.execute('''UPDATE current_result_work SET active=false,reason='inventory_revision_removed',reconciled_at=clock_timestamp()
            WHERE game_key=%s AND active AND NOT(unit_id=ANY(%s))''',(bundle['game_key'],wanted))
        db.execute('''INSERT INTO current_result_work(game_key,unit_id,inventory_revision)
            SELECT %s,uid,%s FROM unnest(%s::text[]) AS u(uid)
            ON CONFLICT(game_key,unit_id) DO UPDATE SET active=true,inventory_revision=excluded.inventory_revision,
                reconciled_at=clock_timestamp(),
                pending_version=current_result_work.pending_version+1,
                dirty_since=COALESCE(current_result_work.dirty_since,clock_timestamp()),
                reason=CASE WHEN NOT current_result_work.active THEN 'inventory_revision_restored' ELSE current_result_work.reason END
            WHERE NOT current_result_work.active OR current_result_work.inventory_revision<>excluded.inventory_revision''',
            (bundle['game_key'],revision,wanted))
    return revision


def reconcile_catalog(db,games,*,at):
    """Called only by publication after complete catalog/authority validation.

    Every old member must have a positive replacement in this captured catalog.
    Absence, invalid matching and partial scope cannot retire an inventory.
    Captured inventory and Originals remain historical evidence.
    """
    members={g['game_key']:{hashed(member) for member in g['members']} for g in games}
    covered=set().union(*members.values()) if members else set()
    for old in db.execute('SELECT game_key,events FROM current_result_inventory WHERE superseded_at IS NULL AND discovered_at<=%s',(at,)):
        events=set(old['events'])
        if old['game_key'] in members or not events or not events<=covered:continue
        successors=sorted(key for key,ids in members.items() if events&ids)
        db.execute('UPDATE current_result_inventory SET superseded_at=%s,superseded_by=%s WHERE game_key=%s',
            (at,Jsonb(successors),old['game_key']))
        db.execute("""UPDATE current_result_work SET active=false,reason='occurrence_inventory_superseded',
            reconciled_at=clock_timestamp(),refresh_order=NULL,refresh_visit_order=NULL WHERE game_key=%s AND active""",(old['game_key'],))


def ordered(db, game, units):
    visits={r['unit_id']:r['visit_order'] for r in db.execute(
        'SELECT unit_id,visit_order FROM current_result_work WHERE game_key=%s AND active',(game,))}
    return sorted(units,key=lambda u:(visits[u['id']],u['id']))


def visit(db, game, uid):
    # Persist BEFORE reuse, capture or calculation. Cancellation and hot updates
    # consume a turn too. New arrivals join the tail rather than a zero-age prefix.
    row=db.execute('''UPDATE current_result_work SET visit_order=nextval('current_result_visit'),
        visits=visits+1,last_visit=clock_timestamp(),reason='visited',
        claimed_version=pending_version,
        refresh_order=CASE WHEN refresh_order IS NOT NULL THEN nextval('current_result_refresh_order') END
        WHERE game_key=%s AND unit_id=%s AND active RETURNING claimed_version''',(game,uid)).fetchone()

    return row['claimed_version'] if row else None


def acknowledge(db, game, uid, version):
    """Called inside the validated seal transaction, never on failure/visit."""
    if version is None:return
    db.execute('''UPDATE current_result_work SET
        acknowledged_version=greatest(acknowledged_version,%s),
        refresh_order=CASE WHEN pending_version=%s THEN NULL ELSE refresh_order END,
        refresh_visit_order=CASE WHEN pending_version=%s THEN NULL ELSE refresh_visit_order END,
        dirty_since=CASE WHEN pending_version=%s THEN NULL ELSE dirty_since END
        WHERE game_key=%s AND unit_id=%s AND active AND claimed_version=%s''',
        (version,version,version,version,game,uid,version))


def prune(db):
    # Only obsolete working cursors. Active all-deferred inventory is retained;
    # reader Originals and account/control records are owned elsewhere.
    db.execute("DELETE FROM current_result_work WHERE NOT active AND reconciled_at<clock_timestamp()-interval '2 hours'")
    # Reclaim only with positive current schedule evidence for EVERY member.
    # Absence of an event/offer is not a withdrawal or a completed inventory.
    db.execute('''DELETE FROM current_result_inventory i
        WHERE discovered_at<clock_timestamp()-interval '2 hours' AND jsonb_array_length(events)>0
        AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(i.events) AS member(id)
            LEFT JOIN current_event e ON e.id=member.id
            WHERE e.id IS NULL OR e.scheduled_start IS NULL OR e.scheduled_start::timestamptz>clock_timestamp())''')
