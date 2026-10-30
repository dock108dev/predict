"""Read-only bulk reconciliation over durable source evidence, never dispatch."""
from datetime import datetime, timezone
from .current_policy import SPORTS
from .price_units import native_boundary, aggregate_units, merge_units


def event_route_status(census, event, receipt):
    """An event listing includes live games; only pregame routes are dispatched."""
    current=bool(receipt and receipt['cycle_id']==census['cycle_id'])
    # The raw census is retained before route qualification. Missing or invalid
    # provider schedule data cannot establish that an event has already started.
    required=None
    raw_start=event.get('commence_time')
    if isinstance(raw_start,str):
        try:
            start=datetime.fromisoformat(raw_start.replace('Z','+00:00'))
            if start.tzinfo is not None:required=start>census['received_at']
        except ValueError:pass
    reason=('received_current_cycle' if current else
            'event_start_unknown' if required is None else
            'started_before_census_not_requested' if not required else
            'event_route_pending_or_interrupted')
    return dict(sport=census['sport'],event_id=event['id'],census_cycle=census['cycle_id'],
        received_cycle=receipt['cycle_id'] if receipt else None,current_cycle_received=current,
        pregame_at_census=required,reason=reason,
        receipt_disposition=receipt['disposition'] if receipt else None,
        returned_markets=sum(len(b.get('markets',[])) for b in receipt['payload'].get('bookmakers',[]))
            if current and isinstance(receipt['payload'],dict) else None)


def report(db):
    cells = {(v,s,f):dict(venue=v,sport=s,family=f,offered_price_units=None,
        received=0,admitted=0,rejected=0,pending=0,known_markets=0,received_market_images=0,missing_markets=[],
        denominator_status='unknown',provider_universe_complete=False)
        for v in ('kalshi','polymarket_us','novig','prophetx','pinnacle')
        for s in SPORTS for f in ('moneyline','spread','total')}
    observed=datetime.now(timezone.utc)
    for row in db.execute('SELECT source,sport,family,count(*) AS n FROM current_acquisition_market WHERE withdrawn GROUP BY source,sport,family'):
        cell=cells.get((row['source'],row['sport'],row['family']))
        if cell is not None:cell['confirmed_closed_markets']=row['n']
    runtime=db.execute('SELECT runtime_id,status,state,heartbeat_at,dispatch FROM data_runtime WHERE singleton').fetchone()
    from .runtime_status import HEARTBEAT_SECONDS
    runtime_age=(observed-runtime['heartbeat_at']).total_seconds() if runtime else None
    runtime_id=runtime['runtime_id'] if runtime and runtime['state']=='running' and runtime['dispatch'] and 0<=runtime_age<=HEARTBEAT_SECONDS else None
    current=dict(runtime['status'].get('metrics',{}) if runtime else {})
    # Structured metrics are deduplicated into source panels at heartbeat commit.
    for panel in runtime['status'].get('sources',[]) if runtime else []:
        current[panel['provider']]={**current.get(panel['provider'],{}),**panel.get('metrics',{})}
    for row in db.execute('SELECT m.*,i.image,i.disposition AS image_disposition,i.received_at,i.runtime_id AS image_runtime_id,i.connection_generation,i.census_generation '
                          'FROM current_acquisition_market m LEFT JOIN current_acquisition_image i '
                          'USING(source,event_id,market_id) WHERE NOT m.withdrawn ORDER BY source,sport,family,market_id'):
        cell = cells.get((row['source'],row['sport'],row['family']))
        if cell is None:
            continue
        cell['known_markets'] += 1
        # Explain retained absences without declaring a provider withdrawal or
        # dropping them from the measured missing-slot denominator.
        start=row['metadata'].get('occurrence_datetime') or row['metadata'].get('gameStartTime')
        scheduled_scope='unknown'
        if isinstance(start,str):
            try:
                parsed=datetime.fromisoformat(start.replace('Z','+00:00'))
                if parsed.tzinfo is not None:
                    scheduled_scope='started_by_retained_schedule' if parsed<=observed else 'pregame_by_retained_schedule'
            except ValueError:pass
        if row['disposition']=='suspected_absent':
            key='suspected_absent_'+scheduled_scope
            cell[key]=cell.get(key,0)+1
        source_state=current.get(row['source'],{})
        connected=bool(runtime_id and source_state.get('stream_connected') and row['market_id'] not in source_state.get('invalid_current_market_ids',[])
                       and row['image_runtime_id']==runtime_id and row['connection_generation']==source_state.get('connections'))
        sync=source_state.get('synchronization',{})
        synchronized=bool(connected and sync.get('state') in ('synchronized','streaming') and sync.get('generation')==row['connection_generation'])
        cell['synchronized_market_images']=cell.get('synchronized_market_images',0)+int(synchronized)
        cell['synchronization_state']=sync.get('state','unknown') if runtime_id else 'unavailable'
        cell['current_connection_images']=cell.get('current_connection_images',0)+int(connected)
        cell['current_census_images']=cell.get('current_census_images',0)+int(connected and row['census_generation']==row['generation'])
        current_boundary=native_boundary(row['source'],row['metadata'],row['image'] if connected else None)
        for key in ('offered','empty','unavailable','missing'):
            if current_boundary[key] is not None:cell['current_connection_'+key]=cell.get('current_connection_'+key,0)+current_boundary[key]
        cell['denominator_status']='partial'
        boundary=native_boundary(row['source'],row['metadata'],row['image'])
        for key in ('expected_slots','offered','empty','unavailable','missing'):
            if boundary[key] is not None:
                cell['native_'+key]=cell.get('native_'+key,0)+boundary[key]
        if boundary['expected_slots'] is None:
            cell['unknown_native_slot_markets']=cell.get('unknown_native_slot_markets',0)+1
        if row['disposition']=='suspected_absent':
            cell['suspected_absent_markets']=cell.get('suspected_absent_markets',0)+1
        cell['synthetic_complements_excluded_from_native_counts']=True
        cell['native_boundary_method']='Independent metadata roster × native quote representations; complete images distinguish offered, empty and unavailable slots'
        cell['transformations']=boundary.get('transformations',[])
        cell.setdefault('native_market_boundaries',[]).append(dict(event_id=row['event_id'],market_id=row['market_id'],
            period='full_game',line_facts={k:row['metadata'][k] for k in ('line','floor_strike','cap_strike','strike_type') if k in row['metadata']},
            inventory_disposition=row['disposition'],retained_scheduled_start=start,scheduled_scope=scheduled_scope,**boundary))
        cell['missing_denominator_evidence']='Coherent complete listing/book boundary including suspected absences, missing images and unavailable sides'

        image=row['image']
        if image is None:
            reason='awaiting_raw_book_image' if row['disposition']=='subscribed' else row['disposition']
            cell['missing_markets'].append(dict(event_id=row['event_id'],market_id=row['market_id'],reason=reason))
            continue
        cell['received_market_images']+=1
        received_at=row['received_at'].isoformat()
        source_at=image.get('raw',{}).get('exchange_at')
        if source_at:
            cell['oldest_original_source_at']=min(cell.get('oldest_original_source_at',source_at),source_at)
            cell['newest_original_source_at']=max(cell.get('newest_original_source_at',source_at),source_at)
        else:
            cell['missing_original_source_clocks']=cell.get('missing_original_source_clocks',0)+1
        cell['oldest_image_received_at']=min(cell.get('oldest_image_received_at',received_at),received_at)
        cell['newest_image_received_at']=max(cell.get('newest_image_received_at',received_at),received_at)
        count=boundary['offered']
        cell['received'] += count
        cell[row['image_disposition']] += count
    route_units={}
    mapping={'h2h':'moneyline','spreads':'spread','totals':'total'}
    for batch in db.execute('SELECT * FROM current_acquisition_aggregate'):
        for venue in ('novig','prophetx','pinnacle'):
            for family in mapping.values():
                cell=cells[(venue,batch['sport'],family)]
                cell.update(denominator_status='complete_exact_featured_query',received_at=batch['received_at'].isoformat(),
                            scope_limitation='Featured response only; event-route completeness reported separately; full-provider denominator unknown')
        payload=batch['payload']
        for event in payload.get('events',[]) if isinstance(payload,dict) else payload:
            for book in event.get('bookmakers',[]):
                for market in book.get('markets',[]):
                    cell=cells.get((book['key'],batch['sport'],mapping.get(market['key'])))
                    if cell is None:continue
                    cell['known_markets']+=1
                    cell['received']+=sum(o.get('price') is not None for o in market.get('outcomes',[]))
        for venue in ('novig','prophetx','pinnacle'):
            for family in mapping.values():
                route_units[(venue,batch['sport'],family)]=aggregate_units(payload.get('events',[]) if isinstance(payload,dict) else payload,venue,family,'featured')
        if isinstance(payload,dict):
            for d in payload.get('dispositions',[]):
                cell=cells[(d['venue'],batch['sport'],d['family'])]
                cell.update(received=d['received'],admitted=d['admitted'],rejected=d['rejected'],pending=d['pending'],
                            featured_offered_price_units=d['unique_offered']['quotes'])
    alternate=[]
    current_alternates=set()
    for census in db.execute('SELECT * FROM current_acquisition_event_census'):
        for event in census['payload']:
            row=db.execute('SELECT * FROM current_acquisition_alternate WHERE sport=%s AND event_id=%s',
                (census['sport'],event['id'])).fetchone()
            state=event_route_status(census,event,row)
            if state['current_cycle_received']:current_alternates.add((census['sport'],event['id']))
            alternate.append(state)
    for batch in db.execute('SELECT * FROM current_acquisition_alternate'):
        payload=batch['payload']
        if not isinstance(payload,dict):continue
        for book in payload.get('bookmakers',[]):
            for market in book.get('markets',[]):
                family={'alternate_spreads':'spread','alternate_totals':'total'}.get(market.get('key'))
                cell=cells.get((book.get('key'),batch['sport'],family))
                if cell is None:continue
                if (batch['sport'],batch['event_id']) in current_alternates:
                    target=route_units.setdefault((book.get('key'),batch['sport'],family),{})
                    merge_units(target,aggregate_units([payload],book.get('key'),family,'alternate'))
                units={(o.get('name'),str(o.get('point'))) for o in market.get('outcomes',[]) if o.get('price') is not None}
                cell['alternate_received']=cell.get('alternate_received',0)+len(units)
                key='alternate_current_cycle_received' if (batch['sport'],batch['event_id']) in current_alternates else 'alternate_prior_cycle_retained'
                cell[key]=cell.get(key,0)+len(units)
                disposition='alternate_'+batch['disposition']
                cell[disposition]=cell.get(disposition,0)+len(units)
                cell['alternate_received_at']=max(cell.get('alternate_received_at',''),batch['received_at'].isoformat())
                cell['scope_limitation']='Featured and per-event alternate receipts; full-provider boundary not yet qualified'
    for key,units in route_units.items():
        cell=cells[key]
        cell['reconciled_route_units']=len(units)
        cell['featured_alternate_overlap']=sum(len(u['routes'])>1 for u in units.values())
        cell['route_absent_quotes']=sum(u['disposition']=='absent_quote' for u in units.values())
        cell['route_presence_conflicts']=sum(u['disposition']=='route_quote_presence_conflict' for u in units.values())
        cell['route_unit_identities']=[dict(unit_id=uid,**row) for uid,row in sorted(units.items())]
        cell['missing_denominator_evidence']='Featured receipt and current event-census routes need a common supported offering boundary; retained cycles cannot prove it'
    return dict(schema='predict-bulk-acquisition-report-1',read_at=datetime.now(timezone.utc).isoformat(),
        provider_requests=0,qualified_99_percent=False,
        unusable_frames=[dict(r) for r in db.execute('SELECT source,stage,disposition,count(*) AS retained_frames,min(received_at) AS oldest_receipt,max(received_at) AS newest_receipt FROM current_acquisition_failure GROUP BY source,stage,disposition')],
        cells=list(cells.values()),alternate_events=alternate,
        traversal=[dict(r) for r in db.execute('SELECT source,count(*) AS queries,count(completed_at) AS complete_queries '
            'FROM current_acquisition_query GROUP BY source')],
        limitations=['Native full-price denominator requires every listing/book boundary and native-side reconciliation',
                     'Aggregate units reconcile featured and current alternate routes; prior cycles stay separate'])


if __name__=='__main__':
    import json
    from app.storage.store import connect
    with connect() as db:
        with db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            print(json.dumps(report(db),indent=2,default=str))
