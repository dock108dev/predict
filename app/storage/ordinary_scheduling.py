"""Fair delivery order and source receipt watermarks for ordinary publication."""

from .store import hashed, stamp


def receipt_watermarks(db):
    """Keep aggregate delivery separate from short-lived signed book work."""
    aggregate = {r['event_id']:stamp(r['at']) for r in db.execute('''SELECT c.event_id,max(o.received_at) at
        FROM current_offer o JOIN current_contract c ON c.id=o.contract_id
        JOIN current_event e ON e.id=c.event_id
        WHERE e.provider='the_odds_api' AND c.venue IN ('novig','prophetx','pinnacle')
        GROUP BY c.event_id''')}
    native = db.execute('''SELECT c.event_id,c.venue,
        max(greatest(o.source_at::timestamptz,
            (o.facts#>>'{book_confirmation,confirmed_at}')::timestamptz))::text at
        FROM current_offer o JOIN current_contract c ON c.id=o.contract_id
        WHERE c.venue IN ('kalshi','polymarket_us','pinnacle')
           OR (c.venue='novig' AND o.facts ? 'novig_runtime_id')
        GROUP BY c.event_id,c.venue''').fetchall()
    return aggregate, native


def prioritize_current(pending, scope, evidence, at, *, material=(), undelivered=()):
    """Reserve oldest and source slots, then alternate fair and fresh work.

    The first slot always advances fair rotation, including API/reference work.
    The native source slots prevent every native frame expiring behind a full-slate
    rotation. This is scheduling only; reads still validate exact source clocks.
    """
    if not pending:return []
    from app.collection.current_benchmark import MAXIMUM_AGE
    reference_events={r['event_id'] for r in evidence if r['venue']=='pinnacle' and r['at']
        and 0 <= (at-stamp(r['at'])).total_seconds() <= MAXIMUM_AGE}
    order=[pending[0]];fresh={}
    # A newly admitted aggregate batch deserves a first-delivery slot before
    # unchanged native confirmations. Oldest-first within that batch preserves
    # fairness. This never promotes an expired quote or changes eligibility.
    first_delivery=[key for key in pending if key in undelivered and key not in order]
    if first_delivery:order.append(first_delivery[0])
    from app.comparison.game_phase import LIVE_SECONDS
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
    delivery_order=iter(first_delivery)
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
    for q in (*inputs['quotes'],*inputs.get('references',[])):
        source=q['source']
        if source['provider']!='the_odds_api':continue
        key=hashed([source['provider'],source['native_event_id']])
        received=q['times']['received_at']
        if key not in receipts or stamp(received)>stamp(receipts[key]):receipts[key]=received
    return receipts


def awaiting_aggregate(facts,events,receipts,at):
    # Optional calculation time is not evidence that a later receipt was
    # captured. Compare the exact per-event clocks sealed in the component.
    captured=facts.get('aggregate_receipts',{})
    return any(e in receipts and (e not in captured or stamp(captured[e])<receipts[e])
        and 0<=(at-receipts[e]).total_seconds()<=900 for e in events)
