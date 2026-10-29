"""Selective raw acquisition reads. No normalization, matching or calculation owner."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from app.storage.store import hashed

HEADER = """
SELECT 'native'::text kind,i.source venue,i.event_id,i.market_id,
 COALESCE(m.sport,'unknown') sport,COALESCE(m.family,'unknown') family,
 COALESCE(r.display_metadata->>'period',m.display_period,'unknown') period,
 COALESCE(r.display_metadata->>'title',m.display_title,i.market_id) title,
 i.received_at,i.persisted_at,i.disposition,i.runtime_id,i.connection_generation,i.census_generation,
 m.generation,m.withdrawn,r.display_metadata->'sides' sides,
 m.display_line line
FROM current_acquisition_image i
LEFT JOIN current_acquisition_market m USING(source,event_id,market_id)
LEFT JOIN current_native_market_recovery r ON r.source=i.source AND r.market_id=i.market_id
UNION ALL
SELECT kind,venue,event_id,market_id,sport,family,'full_game',title,received_at,NULL::timestamptz,
 'received_pending_qualification',NULL,NULL,NULL,NULL,false,NULL,NULL
FROM raw_aggregate_display
"""
FILTERS = ('sport', 'venue', 'family', 'period', 'event_id')


def where(filters):
    clauses=[]; args=[]
    for key in FILTERS:
        if filters.get(key):
            clauses.append(f'{key}=%s');args.append(filters[key])
    if filters.get('search'):
        clauses.append("(title ILIKE %s OR event_id ILIKE %s OR market_id ILIKE %s)")
        args.extend(['%'+filters['search'].replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%']*3)
    return (' WHERE '+' AND '.join(clauses) if clauses else ''),args


def state_expression(owner):
    cases=[];args=['aggregate' if source_information(owner,'novig')['refresh_status']=='scheduled' else 'last_known']
    for panel in owner.get('status',{}).get('sources',[]):
        venue=panel.get('provider');metrics=panel.get('metrics',{});sync=metrics.get('synchronization',{})
        if (owner.get('active') and owner.get('healthy') and not owner.get('global_stopped')
                and venue not in owner.get('paused_sources',[]) and metrics.get('stream_connected') and sync.get('continuity_intact')):
            cases.append("WHEN venue=%s AND runtime_id=%s AND connection_generation=%s AND census_generation=generation AND NOT COALESCE(withdrawn,false) AND NOT(market_id=ANY(%s)) THEN %s")
            args.extend((venue,owner.get('runtime_id'),sync.get('generation'),metrics.get('invalid_current_market_ids',[]),'synchronized' if sync.get('current') else 'delayed'))
    return ("CASE WHEN kind<>'native' THEN %s WHEN disposition='rejected' THEN 'unqualified' "+' '.join(cases)+" ELSE 'last_known' END"),args


def selection(filters,owner):
    clause,args=where(filters)
    if filters.get('state'):
        expression,values=state_expression(owner)
        clause+=(' AND ' if clause else ' WHERE ')+expression+'=%s'
        args.extend((*values,filters['state']))
    return clause,args


def headers(db, filters, offset, limit,owner=None):
    clause,args=selection(filters,owner or {})
    owner=owner or {}
    generations={p.get('provider'):p.get('metrics',{}).get('synchronization',{}).get('generation')
        for p in owner.get('status',{}).get('sources',[])}
    order=""" ORDER BY CASE WHEN kind<>'native' OR (runtime_id=%s AND census_generation=generation
        AND connection_generation=CASE venue WHEN 'kalshi' THEN %s::bigint WHEN 'polymarket_us' THEN %s::bigint END)
        THEN 0 ELSE 1 END,venue,event_id,market_id,kind,sport OFFSET %s LIMIT %s"""
    return db.execute('SELECT * FROM ('+HEADER+') h'+clause+order,
        (*args,owner.get('runtime_id'),generations.get('kalshi'),generations.get('polymarket_us'),offset,limit)).fetchall()


def total(db,filters,owner=None):
    clause,args=selection(filters,owner or {})
    return db.execute('SELECT count(*) n FROM ('+HEADER+') h'+clause,args).fetchone()['n']


def source_information(owner,venue):
    native=venue in ('kalshi','polymarket_us')
    provider=venue if native else 'the_odds_api'
    panel=next((p for p in owner.get('status',{}).get('sources',[]) if p.get('provider')==provider),{})
    if native:return dict(synchronization=panel.get('metrics',{}).get('synchronization',{}))
    quota=owner.get('status',{}).get('quota',{})
    stopped=(not owner.get('active') or not owner.get('healthy') or owner.get('global_stopped') or provider in owner.get('paused_sources',[]))
    from app.collection.current_aggregate_policy import POLICY
    from zoneinfo import ZoneInfo
    hour=datetime.now(ZoneInfo(POLICY.timezone)).hour
    operating=POLICY.opens_at_hour<=hour<POLICY.closes_at_hour
    return dict(refresh_seconds=900,next_due_at=quota.get('next_due_at'),
        operating_window=f'{POLICY.opens_at_hour:02}:00–{POLICY.closes_at_hour:02}:00 {POLICY.timezone}',
        refresh_status='stopped' if stopped else 'paused' if quota.get('pause') else 'scheduled' if operating else 'outside_operating_hours',
        source_age_is_receipt_age=False)


def status(row,owner):
    if row['kind']!='native':return 'aggregate' if source_information(owner,row['venue'])['refresh_status']=='scheduled' else 'last_known'
    panel=next((p for p in owner.get('status',{}).get('sources',[]) if p.get('provider')==row['venue']),{})
    metrics=panel.get('metrics',{});sync=metrics.get('synchronization',{})
    bound=(owner.get('active') and owner.get('healthy') and not owner.get('global_stopped')
        and row['venue'] not in owner.get('paused_sources',[]) and row['runtime_id']==owner.get('runtime_id')
        and row['connection_generation']==sync.get('generation') and row['census_generation']==row['generation']
        and metrics.get('stream_connected') and sync.get('continuity_intact')
        and row['market_id'] not in metrics.get('invalid_current_market_ids',[]) and not row['withdrawn'])
    if row['disposition']=='rejected':return 'unqualified'
    if bound and sync.get('current'):return 'synchronized'
    if bound:return 'delayed'
    return 'last_known'


def valid_price(value,native):
    try:
        n=Decimal(str(value))
        return n.is_finite() and (0<=n<=1 if native else n>1)
    except (ValueError,InvalidOperation):return False


def book(db,row,owner):
    native=row['kind']=='native'
    if native:
        # Recovery catalogs contain current subscription members only. Historical
        # books still own source metadata in the durable acquisition roster.
        if not row.get('sides') or row['period']=='unknown' or row['venue']=='polymarket_us':
            meta=db.execute('SELECT metadata FROM current_acquisition_market WHERE source=%s AND event_id=%s AND market_id=%s',
                (row['venue'],row['event_id'],row['market_id'])).fetchone()
            if meta:
                from .raw_metadata import display
                recovered=display(row['venue'],meta['metadata'])
                row=dict(row,**{k:v for k,v in recovered.items() if v and (k!='period' or row['period']=='unknown')})
        # PostgreSQL detoasts only selected images; no complete book crosses into
        # Python for top-of-book pages. Depth is separately bounded by ladder.
        value=db.execute("""SELECT (image->'raw')-'json_text' raw,image->>'state' state,
            image->>'sync' sync,image->'book_confirmation' confirmation,
            (SELECT jsonb_agg(jsonb_build_object('outcome_id',o->>'outcome_id',
              'asks',CASE WHEN jsonb_typeof(o->'asks')='object' THEN jsonb_build_object('depth',o->'asks'->'depth','count',jsonb_array_length(o->'asks'->'levels'),'top',o->'asks'->'levels'->0) ELSE NULL END,
              'bids',CASE WHEN jsonb_typeof(o->'bids')='object' THEN jsonb_build_object('depth',o->'bids'->'depth','count',jsonb_array_length(o->'bids'->'levels'),'top',o->'bids'->'levels'->0) ELSE NULL END))
             FROM jsonb_array_elements(image->'outcomes') o) outcomes
            FROM current_acquisition_image WHERE source=%s AND event_id=%s AND market_id=%s""",
            (row['venue'],row['event_id'],row['market_id'])).fetchone()
        source_at=value['raw'].get('exchange_at'); observations=[]
        for outcome in value['outcomes'] or []:
            meta=next((s for s in row.get('sides') or [] if s.get('id')==outcome['outcome_id']),{})
            for side in ('asks','bids'):
                ladder=outcome.get(side);top=(ladder or {}).get('top') or {}
                price=top.get('price',{}).get('value')
                representation=('derived_short_ask_from_long_bid' if row['venue']=='polymarket_us' and meta.get('role','').lower()=='short' and side=='asks' else
                    'not_independently_supplied_short_bid' if row['venue']=='polymarket_us' and meta.get('role','').lower()=='short' and side=='bids' else
                    'derived_ask_from_opposite_bid' if row['venue']=='kalshi' and side=='asks' else 'native_ladder')
                observations.append(dict(outcome_id=outcome['outcome_id'],side=side,representation=representation,
                    native_side=meta.get('role',outcome['outcome_id']),label=meta.get('label',outcome['outcome_id']),
                    price=price,units='USD per contract',quantity=top.get('quantity'),line=meta.get('line') if row['venue']=='polymarket_us' and row['family']=='spread' else row['line'],
                    line_meaning='source predicate threshold' if row['venue']=='kalshi' and row['family']=='spread' else 'signed outcome line' if row['family']=='spread' else 'total threshold',
                    levels=(ladder or {}).get('count',0),depth=(ladder or {}).get('depth'),
                    disposition='empty' if ladder and not top else 'unavailable' if ladder is None else
                    'received_unqualified' if valid_price(price,True) else 'invalid_price'))
        provenance=dict(raw=value['raw'],confirmation=value['confirmation'],book_state=value['state'],book_sync=value['sync'])
    else:
        value=db.execute('SELECT outcomes,source_at FROM raw_aggregate_display WHERE kind=%s AND sport=%s AND event_id=%s AND venue=%s AND market_id=%s',
            tuple(row[k] for k in ('kind','sport','event_id','venue','market_id'))).fetchone()
        source_at=value['source_at'];observations=[]
        for index,o in enumerate(value['outcomes']):
            observations.append(dict(outcome_id=o.get('name',str(index)),side='offer',native_side='bookmaker',
                label=o.get('name','Unknown outcome'),price=o.get('price'),units='decimal odds',line=o.get('point'),
                quantity=None,levels=0,depth=None,disposition='received_unqualified' if valid_price(o.get('price'),False) else 'invalid_price'))
        provenance=dict(**source_information(owner,row['venue']),last_received_at=row['received_at'].isoformat(),source_time_is_last_update=True)
    identity={k:row[k] for k in ('kind','venue','sport','event_id','market_id')}
    revision=hashed([identity,row['received_at'].isoformat(),observations,source_at])
    for o in observations:o['id']=hashed([identity,o['outcome_id'],o['side'],o['line']])
    return dict(**identity,id=hashed(identity),revision=revision,title=row['title'],family=row['family'],period=row['period'],
        storage_write_at=row['persisted_at'].isoformat() if row['persisted_at'] else None,
        received_at=row['received_at'].isoformat(),source_at=source_at,price_change_at=None,
        source_time_meaning='native_book_source_time' if native else 'provider_last_update',status=status(row,owner),
        validation=row['disposition'],matching='source_local',financial=dict(state='unavailable',reason='No result bound to this raw input revision'),
        reference_only=row['venue']=='pinnacle',provider=row['venue'] if native else 'the_odds_api',
        observations=observations,provenance=provenance,
        missing_facts=['cross_source_match','calculation_basis'],
        connection_generation=row['connection_generation'],census_generation=row['census_generation'])


def page(db,filters,offset,limit,owner):
    rows=headers(db,filters,offset,limit,owner)
    return [book(db,r,owner) for r in rows]


def depth_page(db,identity,outcome,side,offset,limit):
    if side not in ('asks','bids'):raise ValueError('Unknown ladder')
    row=db.execute("""WITH ladder AS (
      SELECT i.received_at, o->%s->'levels' levels FROM current_acquisition_image i,
      LATERAL jsonb_array_elements(i.image->'outcomes') o
      WHERE source=%s AND event_id=%s AND market_id=%s AND o->>'outcome_id'=%s)
      SELECT received_at,COALESCE(jsonb_array_length(levels),0) total,
      (SELECT jsonb_agg(v) FROM (SELECT v FROM jsonb_array_elements(levels) v OFFSET %s LIMIT %s) part) levels
      FROM ladder""",(side,identity['venue'],identity['event_id'],identity['market_id'],outcome,offset,limit)).fetchone()
    if not row:return None
    return dict(received_at=row['received_at'].isoformat(),total=row['total'],levels=row['levels'] or [],
        next_offset=offset+limit if offset+limit<row['total'] else None)
