"""Fair delivery order and source receipt watermarks for ordinary publication."""

from .store import hashed, stamp


def receipt_watermarks(db, aggregate_provider='the_odds_api'):
    """Keep aggregate delivery separate from short-lived signed book work."""
    aggregate = {r['event_id']:stamp(r['at']) for r in db.execute('''SELECT c.event_id,max(o.received_at) at
        FROM current_offer o JOIN current_contract c ON c.id=o.contract_id
        JOIN current_event e ON e.id=c.event_id
        WHERE e.provider=%s AND c.venue IN ('novig','prophetx','pinnacle','kalshi')
        GROUP BY c.event_id''', (aggregate_provider,))}
    if aggregate_provider == 'sportsgameodds':
        for row in db.execute('''SELECT e.id,f.facts->>'received_at' AS received_at FROM current_event e
            JOIN current_sgo_event_frame f ON f.event_id=e.native_event_id WHERE e.provider=%s''', (aggregate_provider,)):
            received = stamp(row['received_at'])
            aggregate[row['id']] = max(received, aggregate.get(row['id'], received))
    native = db.execute('''SELECT c.event_id,
        CASE WHEN e.provider='sportsgameodds' AND c.venue<>'pinnacle' THEN 'sgo_live'
             ELSE c.venue END venue,
        max(greatest(o.source_at::timestamptz,
            (o.facts#>>'{book_confirmation,confirmed_at}')::timestamptz))::text at
        FROM current_offer o JOIN current_contract c ON c.id=o.contract_id
        JOIN current_event e ON e.id=c.event_id
        WHERE (c.venue=e.provider AND c.venue IN ('kalshi','polymarket_us'))
           OR (c.venue='pinnacle' AND e.provider=%s)
           OR (c.venue=e.provider AND c.venue='novig' AND o.facts ? 'novig_runtime_id')
           OR (%s='sportsgameodds' AND e.provider='sportsgameodds'
               AND c.venue IN ('novig','prophetx','kalshi') AND o.facts->>'state'='available'
               AND e.facts#>>'{status,live}'='true' AND e.facts#>>'{status,ended}' IS DISTINCT FROM 'true'
               AND e.facts#>>'{status,closed}' IS DISTINCT FROM 'true'
               AND e.facts#>>'{status,status}' IS DISTINCT FROM 'delayed'
               AND e.scheduled_start::timestamptz <= o.source_at::timestamptz
               AND o.source_at::timestamptz <= o.received_at::timestamptz)
        GROUP BY 1,2''', (aggregate_provider, aggregate_provider)).fetchall()
    return aggregate, native


def prioritize_current(pending, scope, evidence, at, *, material=(), undelivered=()):
    """Reserve oldest and source slots, then alternate fair and fresh work.

    Preserve a fair rotation slot. A fresh explicit SGO live receipt can use
    the aggregate delivery slot first, before its short source-clock deadline.
    Native slots retain their own turns. Reads still validate exact authority.
    """
    if not pending:return []
    from app.collection.current_benchmark import MAXIMUM_AGE
    reference_events={r['event_id'] for r in evidence if r['venue']=='pinnacle' and r['at']
        and 0 <= (at-stamp(r['at'])).total_seconds() <= MAXIMUM_AGE}
    from app.comparison.game_phase import LIVE_SECONDS
    sgo_live = {r['event_id']: stamp(r['at']) for r in evidence
                if r['venue'] == 'sgo_live' and r['at'] and
                0 <= (at - stamp(r['at'])).total_seconds() <= LIVE_SECONDS}
    # An earlier source clock has less time left in the same freshness window.
    live_candidates = sorted(
        (min(sgo_live[e] for e in scope[key] if e in sgo_live), index, key)
        for index, key in enumerate(pending) if key in undelivered and any(e in sgo_live for e in scope[key])
    )
    live_first = live_candidates[0][-1] if live_candidates else None
    order = list(dict.fromkeys([live_first, pending[0]])) if live_first else [pending[0]]
    fresh = {}
    # A newly admitted aggregate batch deserves a first-delivery slot before
    # unchanged native confirmations. Oldest-first within that batch preserves
    # fairness. This never promotes an expired quote or changes eligibility.
    first_delivery=[key for key in pending if key in undelivered and key not in order]
    if first_delivery and not live_first:order.append(first_delivery[0])
    for venue, maximum_age in (('kalshi', 30), ('polymarket_us', 30), ('novig', LIVE_SECONDS)):
        recent={r['event_id']:stamp(r['at']) for r in evidence
            if r['venue']==venue and r['at'] and 0 <= (at-stamp(r['at'])).total_seconds() <= maximum_age}
        candidates=[(key not in undelivered,key not in material,reference_events.isdisjoint(scope[key]),-max(recent[e].timestamp() for e in scope[key] if e in recent),index,key)
            for index,key in enumerate(pending) if key not in order and recent.keys() & set(scope[key])]
        for already_delivered,confirmation_only,no_reference,clock,index,key in candidates:
            rank=(already_delivered,confirmation_only,no_reference,clock,index)
            fresh[key]=min(fresh.get(key,rank),rank)
        # First delivery can also satisfy a native source slot. Prefer that
        # overlap before repeatedly refreshing an already-delivered hot game.
        # Oldest work and each source still retain their reserved turn.
        if candidates:order.append(min(candidates)[-1])
    # Previously every slot after the source representatives went to old
    # rotation. Fresh books behind them could expire before their first seal.
    # Keep at least half the remaining slots for rotation (including API work),
    # interleaving recent complete native components without dropping any scope.
    scheduled=set(order)
    recent_order=iter(sorted(fresh,key=lambda key:(fresh[key],key)))
    delivery_order=iter(dict.fromkeys([*(key for _, _, key in live_candidates), *first_delivery]))
    for key in pending:
        if key in scheduled:continue
        order.append(key);scheduled.add(key)
        delivered=False
        for waiting in delivery_order:
            if waiting not in scheduled:
                order.append(waiting);scheduled.add(waiting);delivered=True;break
        if delivered:continue
        for hot in recent_order:
            if hot not in scheduled:
                order.append(hot);scheduled.add(hot);break
    return order


def captured_aggregate_receipts(inputs):
    receipts={}
    provider = inputs.get('reference_provider', 'the_odds_api')
    for q in (*inputs['quotes'],*inputs.get('references',[])):
        source=q['source']
        if source['provider'] != provider:continue
        key=hashed([source['provider'],source['native_event_id']])
        received=q['times']['received_at']
        if key not in receipts or stamp(received)>stamp(receipts[key]):receipts[key]=received
    if provider == 'sportsgameodds':
        for event_id, value in (inputs.get('sgo_reference_events') or {}).items():
            frame = (value.get('frame') or {}).get('facts') or {}
            if frame.get('provider') != provider or frame.get('event_id') != event_id:
                continue
            key = hashed([provider, event_id])
            received = frame['received_at']
            if key not in receipts or stamp(received) > stamp(receipts[key]):
                receipts[key] = received
    return receipts


def awaiting_aggregate(facts,events,receipts,at):
    # Optional calculation time is not evidence that a later receipt was
    # captured. Compare the exact per-event clocks sealed in the component.
    captured=facts.get('aggregate_receipts',{})
    return any(e in receipts and (e not in captured or stamp(captured[e])<receipts[e])
        and 0<=(at-receipts[e]).total_seconds()<=900 for e in events)
