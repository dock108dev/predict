"""Bound and schedule complete matching components before decoding publications."""
from .store import stamp
from . import observation_publication as publication


SOURCE_PREVIOUS = """jsonb_build_object(
    'publication_runtime',facts->'publication_runtime',
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
    from .current_games import engine_binding
    pending=set()
    for row in db.execute("""SELECT publication_events members FROM latest_board
            WHERE facts#>>'{estimate_availability,state}'='pending'
               OR facts#>>'{context,engine_binding}' IS DISTINCT FROM %s""",(engine_binding(),)).fetchall():
        pending.update(row['members'] or [])
    return sorted(batches,key=lambda ids:not bool(pending.intersection(ids or [])))




def prioritize_unpublished(db,batches,at):
    """New 72-hour games must not sit behind repeatedly dirty saved results.

    Only current offered events without any publication qualify. Complete peer
    components stay together, and the caller's rotated order remains stable.
    Other turns continue the ordinary full-inventory rotation.
    """
    from datetime import timedelta
    start=stamp(at);end=start+timedelta(hours=72)
    rows=db.execute("""SELECT e.id FROM current_event e
        WHERE (e.facts->>'scheduled_start')::timestamptz >= %s
          AND (e.facts->>'scheduled_start')::timestamptz < %s
          AND EXISTS(SELECT 1 FROM current_contract c JOIN current_offer o ON o.contract_id=c.id WHERE c.event_id=e.id)
          AND NOT EXISTS(SELECT 1 FROM latest_board b WHERE b.publication_events ? e.id)""",(start,end)).fetchall()
    missing={row['id'] for row in rows}
    return sorted(batches,key=lambda ids:not bool(missing.intersection(ids or [])))


def prioritize_window_waiters(db,batches,at,*,observations_only):
    """Least recently attempted window components first, including retries.

    A published-but-dirty game and a refused game both get another turn after
    older work. New arrivals cannot repeatedly displace existing waiters. Every
    fourth caller turn retains the ordinary full-inventory rotation.
    """
    from datetime import timedelta
    rows=db.execute("""SELECT e.id,a.last_attempt::text attempted FROM current_event e
        LEFT JOIN current_pipeline_attempt a ON a.event_id=e.id AND a.branch=%s
        WHERE (e.facts->>'scheduled_start')::timestamptz >= %s
          AND (e.facts->>'scheduled_start')::timestamptz < %s
          AND EXISTS (SELECT 1 FROM current_contract c JOIN current_offer o ON o.contract_id=c.id
              WHERE c.event_id=e.id AND c.venue<>'pinnacle')""",
        ('raw_grid' if observations_only else 'metrics',stamp(at),stamp(at)+timedelta(hours=72))).fetchall()
    clocks={r['id']:r['attempted'] or at for r in rows}
    # The final age sort must not undo first-publication priority established
    # above it. Reserve three turns for uncompleted engine work; the caller's
    # fourth ordinary turn still services already published, changing games.
    # An accepted historical capture has not completed useful publication. Keep
    # it among oldest-attempt retries rather than demoting it for three turns.
    # New admitted receipts also make a completed frame retryable. This is a
    # conservative scheduling hint, never a semantic invalidation: receipt-only
    # updates still take the exact unchanged-input reuse path inside reconcile.
    missing=set()
    if not observations_only:
        from .current_games import engine_binding
        completed={eid for row in db.execute("""WITH received AS MATERIALIZED (
                SELECT c.event_id,max(o.received_at::timestamptz) latest
                FROM current_offer o JOIN current_contract c ON c.id=o.contract_id GROUP BY c.event_id)
            SELECT b.publication_events members FROM latest_board b
            WHERE b.facts#>>'{context,engine_binding}'=%s
              AND b.facts->>'retained_financial_only' IS DISTINCT FROM 'true'
              AND b.calculated_at IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(b.publication_events) member
                JOIN received r ON r.event_id=member.value WHERE r.latest>b.calculated_at::timestamptz)""",
            (engine_binding(),)).fetchall() for eid in row['members'] or []}
        missing=set(clocks)-completed
    def priority(ids):
        times=[stamp(clocks[eid]) for eid in ids or [] if eid in clocks]
        return (0 if missing.intersection(ids or []) else 1,min(times)) if times else (2,stamp(at))
    return sorted(batches,key=priority)


def prioritize_unit_waiters(db,batches,at=None):
    """Oldest durable unit turn across parents, regardless of parent size.

    New and rejected units use the same sequence as refresh work. Other parent
    turns discover unknown populations and serve the complete ordinary rotation.
    Historical inventories are scheduling hints, never eligibility authority.
    """
    from datetime import timedelta
    from .current_games import utc
    instant=stamp(at or utc())
    rows=db.execute("""SELECT i.events,min(w.visit_order) oldest
        FROM current_result_inventory i JOIN current_result_work w USING(game_key)
        WHERE w.active AND EXISTS (SELECT 1 FROM current_event e
            WHERE i.events ? e.id AND e.scheduled_start::timestamptz>=%s
                AND e.scheduled_start::timestamptz<%s)
        GROUP BY i.game_key,i.events""",(instant,instant+timedelta(hours=72))).fetchall()
    oldest={}
    for row in rows:
        for event in row['events']:oldest[event]=min(oldest.get(event,row['oldest']),row['oldest'])
    def priority(ids):
        values=[oldest[e] for e in ids or [] if e in oldest]
        return (0,min(values)) if values else (1,0)
    return sorted(batches,key=priority)


def unit_waiter_head(db,events,at):
    """A scheduling hint's position, not authority to withdraw its membership."""
    from datetime import timedelta
    instant=stamp(at)
    return db.execute('''SELECT w.game_key,w.unit_id,w.visit_order
        FROM current_result_inventory i JOIN current_result_work w USING(game_key)
        WHERE w.active AND i.events ?| %s
          AND EXISTS (SELECT 1 FROM current_event e WHERE i.events ? e.id
            AND e.scheduled_start::timestamptz>=%s AND e.scheduled_start::timestamptz<%s)
        ORDER BY w.visit_order,w.game_key,w.unit_id LIMIT 1''',
        (events or [],instant,instant+timedelta(hours=72))).fetchone()


def refresh_waiters(db,at,*,engine,runtime_id,enqueue=False):
    """Receipt/book hints for previously sealed units, never currentness proof.

    A dedicated bounded turn keeps refreshes from waiting behind the full
    never-visited population. Exact validation can cheaply reuse receipt-only
    changes; durable visits rotate those attempts too.
    """
    from datetime import timedelta
    instant=stamp(at)
    query="""SELECT w.game_key,w.unit_id,w.visit_order,w.refresh_order,i.events, hint.version input_hint
        FROM current_result_work w LEFT JOIN current_result_unit u USING(game_key,unit_id)
        JOIN current_result_inventory i USING(game_key)
        LEFT JOIN LATERAL (SELECT md5(COALESCE(jsonb_agg(
            jsonb_build_array(x.cid,o.revision,b.depth_revision,b.source_at)
            ORDER BY x.cid)::text,'[]')) version
            FROM jsonb_object_keys(u.facts#>'{publication_dependencies,observations}') x(cid)
            LEFT JOIN current_contract c ON c.id=x.cid
            LEFT JOIN current_offer o ON o.contract_id=x.cid
            LEFT JOIN current_native_book b ON b.venue=c.venue AND b.event_id=c.event_id
                AND b.native_market_id=c.native_market_id) hint ON true
        WHERE w.active
          AND EXISTS (SELECT 1 FROM current_event e WHERE i.events ? e.id
              AND e.scheduled_start::timestamptz>=%s AND e.scheduled_start::timestamptz<%s)
          AND ((w.refresh_order IS NOT NULL OR (w.visits>0 AND w.pending_version>w.acknowledged_version))
            OR (u.facts#>>'{context,engine_binding}'=%s
              AND u.facts#>>'{publication_runtime,runtime_id}'=%s
              AND EXISTS (SELECT 1 FROM jsonb_object_keys(u.facts#>'{publication_dependencies,observations}') x(cid)
              JOIN current_contract c ON c.id=x.cid JOIN current_offer o ON o.contract_id=c.id
              LEFT JOIN current_native_book b ON b.venue=c.venue AND b.event_id=c.event_id
                  AND b.native_market_id=c.native_market_id
              WHERE greatest(o.received_at::timestamptz,b.received_at::timestamptz)>u.captured_at)))
        """
    parameters=(instant,instant+timedelta(hours=72),engine,runtime_id)
    if enqueue:
        # Repeated hints replace the pending version without adding queue rows.
        # Claim rotates a key; only validated completion consumes its work.
        with db.transaction():
            db.execute("UPDATE current_result_work SET refresh_order=NULL,refresh_visit_order=NULL WHERE NOT active")
            db.execute("WITH candidates AS MATERIALIZED ("+query+"""),
                assigned AS MATERIALIZED (SELECT *,nextval('current_result_refresh_order') queue_order
                    FROM candidates ORDER BY visit_order,game_key,unit_id)
                UPDATE current_result_work w SET
                    refresh_order=COALESCE(w.refresh_order,a.queue_order),
                    refresh_visit_order=w.visit_order,
                    pending_version=w.pending_version+CASE WHEN w.input_hint IS DISTINCT FROM a.input_hint THEN 1 ELSE 0 END,
                    input_hint=a.input_hint,dirty_since=COALESCE(w.dirty_since,clock_timestamp())
                FROM assigned a WHERE w.game_key=a.game_key AND w.unit_id=a.unit_id
                    AND (w.refresh_order IS NULL OR w.input_hint IS DISTINCT FROM a.input_hint)""",parameters)
    return db.execute(query+' ORDER BY w.refresh_order NULLS LAST,w.visit_order,w.game_key,w.unit_id',parameters).fetchall()


def refresh_priority(row):
    order=row.get('refresh_order')
    return (order is None,row['visit_order'] if order is None else order)


def prioritize_refresh_waiters(batches,waiters):
    orders={}
    for row in waiters:
        rank=refresh_priority(row)
        for event in row['events']:orders[event]=min(orders.get(event,rank),rank)
    return sorted(batches,key=lambda ids:min((orders[e] for e in ids or [] if e in orders),default=(True,float('inf'))))
