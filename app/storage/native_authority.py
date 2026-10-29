"""Compact read-time stream authority for exact retained native prices.

A current generation, complete image and caught-up ordered feed are all required.
No source timestamp is renewed. This proof never changes captured Details inputs.
"""
from fractions import Fraction
from .store import stamp,hashed


def stream_ready(metrics):
    sync=metrics.get('synchronization',{})
    delay=sync.get('oldest_processing_delay_seconds')
    # Initial/invalid images elsewhere in the venue do not revoke an exact
    # synchronized market below. Ordered transport and its backlog bound do.
    return bool(metrics.get('stream_connected') and sync.get('continuity_intact')
        and sync.get('generation') is not None and isinstance(delay,(int,float))
        and 0<=delay<=2)


def capture(db,owner):
    panels={p.get('provider'):p.get('metrics',{}) for p in owner.get('status',{}).get('sources',[])}
    result={}
    if not owner.get('active') or not owner.get('healthy') or owner.get('global_stopped'):return result
    for venue in ('kalshi','polymarket_us'):
        m=panels.get(venue,{});sync=m.get('synchronization',{})
        if venue in owner.get('paused_sources',[]) or not stream_ready(m):
            continue
        rows=db.execute('''SELECT i.event_id,i.market_id,(SELECT jsonb_agg(jsonb_build_object('outcome_id',o->>'outcome_id','asks',jsonb_build_object('levels',jsonb_build_array(o#>'{asks,levels,0}')))) FROM jsonb_array_elements(i.image->'outcomes') o WHERE o#>'{asks,levels,0}' IS NOT NULL) outcomes,i.image#>>'{raw,exchange_at}' source_at,
            i.image#>>'{raw,received_at}' received_at
            FROM current_acquisition_image i JOIN current_acquisition_market m USING(source,event_id,market_id)
            WHERE i.source=%s AND i.runtime_id=%s AND i.connection_generation=%s
            AND i.census_generation=m.generation AND NOT m.withdrawn
            AND NOT(i.market_id=ANY(%s)) AND i.image->>'sync'='synchronized' AND i.image->>'state'='active' ''',
            (venue,owner['runtime_id'],sync['generation'],m.get('invalid_current_market_ids',[]))).fetchall()
        for r in rows:
            # Retain only the selected top prices, never complete wire frames.
            for o in r['outcomes'] or []:
                asks=(o.get('asks') or {}).get('levels') or []
                if asks:
                    result[hashed([venue,r['event_id'],r['market_id'],o['outcome_id']])]=dict(
                        value=asks[0]['price']['value'],source_at=r['source_at'],received_at=r['received_at'],
                        runtime_id=owner['runtime_id'],generation=sync['generation'])
    return result


def assessment(q,proofs,at):
    s=q['source'];p=proofs.get(hashed([q['venue'],s['native_event_id'],s['native_market_id'],s['native_outcome_id']]))
    if p is None:return None
    try:
        if not p.get('received_at') or not q['times'].get('received_at'):return None
        value=Fraction(q['original']['value'])/(100 if q['original']['units']=='cents_per_contract' else 1)
        if value!=Fraction(p['value']):return None
        if stamp(p['received_at'])>at:return None
        if p.get('source_at') and stamp(p['source_at'])>stamp(p['received_at']):return None
        if stamp(q['times']['received_at'])>stamp(p['received_at']):return None
    except (ValueError,KeyError,TypeError):return None
    return dict(clock_at=q['times']['source_at'],basis='ordered_native_stream_exact_price',current_until=None,reasons=[],
        runtime_id=p['runtime_id'],generation=p['generation'],image_source_at=p.get('source_at'),image_received_at=p['received_at'])
