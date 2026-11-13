"""Atomic complete metadata recovery. Never restore a book's connection authority."""
from dataclasses import asdict
from datetime import datetime,timezone,timedelta
import json
from psycopg.types.json import Jsonb
from app.storage.store import connect,encoded
from app.storage.recovery_codec import freeze,thaw
from app.storage import native_market_metadata
from app.models.core import Market,RawPayload,NativeRef,Venue,EvidenceKind,MarketType,MarketState,Outcome


def encode(market):
    return json.loads(json.dumps(asdict(market),default=lambda x:x.isoformat() if isinstance(x,datetime) else str(x)))


def decode(value,source):
    value=dict(value);raw=dict(value['raw']);ref=dict(raw['ref'])
    if ref['venue']!=source:raise ValueError('recovery_source_conflict')
    ref['venue']=Venue(ref['venue']);raw['ref']=NativeRef(**ref)
    raw['kind']=EvidenceKind(raw['kind'])
    for k in ('received_at','exchange_at'):
        if raw.get(k) is not None:raw[k]=datetime.fromisoformat(raw[k])
    value.update(raw=RawPayload(**raw),market_type=MarketType(value['market_type']),state=MarketState(value['state']),outcomes=tuple(Outcome(**o) for o in value['outcomes']))
    return Market(**value)


def storage_parts(market,parsed,*,shared_native=False):
    return storage_values(market, encode(parsed) if parsed is not None else None, shared_native=shared_native)


def storage_values(market,value,*,shared_native=False):
    # Keep observation fields on their own TOAST value. A new receipt changes
    # these exact fields even when the complete native catalog payload repeats.
    meta=dict(market)
    if shared_native:
        meta.pop('_native')
    receipt={k:meta.pop(k) for k in ('provenance','occurrences','inventory_recovery_disposition') if k in meta}
    fields=dict(metadata=receipt)
    if value is not None:
        raw=dict(value['raw'])
        value=dict(value,raw=raw)
        fields['raw']={k:raw.pop(k) for k in ('received_at','exchange_at') if k in raw}
        # Locally constructed parser wire ends in the receipt digest; retain
        # both literal substrings. Unknown layouts stay intact in the body.
        wire=raw.get('json_text')
        if isinstance(wire,str):
            marker=wire.rfind(', "source_receipt_sha256": "')
            if marker>=0 and len(wire)-marker<128:
                fields['wire_suffix']=wire[marker:]
                layout=None
                if shared_native and wire.startswith('{"market": '):
                    # The old compressed metadata encoder sorted keys, while
                    # the adapter's saved wire still carries provider order.
                    # Derive the layout from that exact string before deciding
                    # whether it is a lossless reference to this native body.
                    try:
                        native=json.loads(wire[len('{"market": '):marker])
                    except ValueError:
                        native=None
                    if (isinstance(native,dict) and encoded(native)==encoded(market['_native'])
                            and wire[:marker]=='{"market": '+json.dumps(native)):
                        layout=native_market_metadata.wire_layout(native)
                if layout is not None:
                    # Regenerate this exact parser envelope from the retained
                    # native body, its original object order and receipt suffix.
                    raw.pop('json_text')
                    fields['wire_layout']=layout
                else:
                    raw['json_text']=wire[:marker]
    return freeze(meta),freeze(value),freeze(fields)


def market_value(metadata,fields,native_body=None):
    value=thaw(metadata)
    if native_body is not None:
        value=dict(value,_native=json.loads(native_body))
    if fields is not None:value=dict(value,**thaw(fields)['metadata'])
    return value


def parsed_value(parsed,fields,native_body=None):
    value=thaw(parsed)
    if value is not None and fields is not None:
        fields=thaw(fields);raw=dict(value['raw'],**fields['raw'])
        if 'wire_layout' in fields:
            if native_body is None:
                raise ValueError('native_recovery_wire_body_missing')
            ordered=native_market_metadata.order_for_wire(json.loads(native_body),fields['wire_layout'])
            raw['json_text']='{"market": '+json.dumps(ordered)
        if 'wire_suffix' in fields:raw['json_text']+=fields['wire_suffix']
        value=dict(value,raw=raw)
    return value


def save(source,scope,catalog,parsed):
    ids=[m['id'] for m in catalog['markets']]
    if len(ids)!=len(set(ids)):raise ValueError('native_recovery_duplicate_market')
    stats=dict(roster=len(ids),unchanged=0,payload_changes=0,receipt_only=0,new_or_large=0,writes=0,
               new=0,oversized_existing=0,legacy_conversions=0,
               suspected_absent=sum(m.get('inventory_recovery_disposition')=='suspected_absent' for m in catalog['markets']))
    with connect() as db,db.transaction():
        native_market_metadata.hold(db)
        db.execute('INSERT INTO current_native_catalog_recovery (source,scope,header) VALUES (%s,%s,%s) ON CONFLICT(source) DO UPDATE SET scope=EXCLUDED.scope,header=CASE WHEN current_native_catalog_recovery.header=EXCLUDED.header THEN current_native_catalog_recovery.header ELSE EXCLUDED.header END,saved_at=now()',
                   (source,scope,Jsonb({k:v for k,v in catalog.items() if k!='markets'})))
        retired=db.execute('DELETE FROM current_native_market_recovery WHERE source=%s AND NOT(market_id=ANY(%s))',
                   (source,[m['id'] for m in catalog['markets']]))
        stats['retired']=retired.rowcount
        with db.cursor() as cur:
          for offset in range(0,len(ids),32):
            batch=catalog['markets'][offset:offset+32]
            # Skip equal retained rows before an UPSERT can lock/write their
            # heap tuples. Never recode an unchanged legacy catalog wholesale.
            # Cap the comparison read; exceptional values use the exact upsert.
            prior={r['market_id']:r for r in db.execute(
                'SELECT r.* FROM unnest(%s::text[]) AS wanted(mid) CROSS JOIN LATERAL ('
                'SELECT market_id,metadata,parsed,receipt_fields,metadata_id FROM current_native_market_recovery '
                'WHERE source=%s AND market_id=wanted.mid AND octet_length(metadata::text)+'
                'COALESCE(octet_length(parsed::text),0)+COALESCE(octet_length(receipt_fields::text),0)<=262144 LIMIT 1) r',
                ([m['id'] for m in batch],source))}
            unchecked=[m['id'] for m in batch if m['id'] not in prior]
            oversized={r['market_id'] for r in db.execute(
                'SELECT market_id FROM current_native_market_recovery WHERE source=%s AND market_id=ANY(%s)',
                (source,unchecked))} if unchecked else set()
            jobs=[];bodies={}
            for m in batch:
                mid=m['id'];old=prior.get(mid);obj=parsed.get(mid)
                native=m.get('_native')
                metadata_id=native_market_metadata.body_id(native) if isinstance(native,dict) else None
                if old and old['receipt_fields'] is None and metadata_id is None:
                    if (encoded(thaw(old['metadata']))==encoded(m) and
                        encoded(thaw(old['parsed']))==encoded(encode(obj) if obj is not None else None)):
                        stats['unchanged']+=1;continue
                meta,body,receipt=storage_parts(m,obj,shared_native=metadata_id is not None)
                if old and old['receipt_fields'] is not None:
                    # The compressed packet includes a checked digest; canonical
                    # comparison also preserves scalar types in uncompressed rows.
                    same_body=(metadata_id==old['metadata_id'] and encoded(meta)==encoded(old['metadata'])
                               and encoded(body)==encoded(old['parsed']))
                    if same_body and encoded(receipt)==encoded(old['receipt_fields']):
                        stats['unchanged']+=1;continue
                    stats['receipt_only' if same_body else 'payload_changes']+=1
                elif old:
                    stats['legacy_conversions']+=1
                    stats['payload_changes']+=1
                else:
                    stats['oversized_existing' if mid in oversized else 'new']+=1
                    stats['new_or_large']+=1
                if metadata_id is not None:
                    bodies[metadata_id]=native
                jobs.append((source,mid,Jsonb(meta),Jsonb(body) if body is not None else None,Jsonb(receipt),metadata_id))
            if not jobs:continue
            native_market_metadata.put(db,bodies)
            cur.executemany('INSERT INTO current_native_market_recovery (source,market_id,metadata,parsed,receipt_fields,metadata_id) VALUES (%s,%s,%s,%s,%s,%s) '
                'ON CONFLICT(source,market_id) DO UPDATE SET '
                'metadata=CASE WHEN current_native_market_recovery.metadata=EXCLUDED.metadata THEN current_native_market_recovery.metadata ELSE EXCLUDED.metadata END, '
                'receipt_fields=CASE WHEN current_native_market_recovery.receipt_fields=EXCLUDED.receipt_fields THEN current_native_market_recovery.receipt_fields ELSE EXCLUDED.receipt_fields END, '
                'parsed=CASE WHEN current_native_market_recovery.parsed IS NOT DISTINCT FROM EXCLUDED.parsed THEN current_native_market_recovery.parsed ELSE EXCLUDED.parsed END, '
                'metadata_id=EXCLUDED.metadata_id '
                'WHERE (current_native_market_recovery.metadata,current_native_market_recovery.parsed,current_native_market_recovery.receipt_fields,current_native_market_recovery.metadata_id) '
                'IS DISTINCT FROM (EXCLUDED.metadata,EXCLUDED.parsed,EXCLUDED.receipt_fields,EXCLUDED.metadata_id)',
                jobs)
            stats['writes']+=cur.rowcount
    return stats


def expired_event(event, now):
    start=event.get('scheduled_start')
    if not start:return False
    try:stamp=datetime.fromisoformat(start)
    except (ValueError,TypeError):return False
    return stamp.tzinfo is not None and stamp<now-timedelta(hours=24)


def retire_expired_catalog(catalog, now=None):
    """Bound resident metadata by the existing game retention window.

    This is time retirement, not inference from missing listings or trading
    status. Durable records remain intact; unknown starts stay visible.
    """
    now=now or datetime.now(timezone.utc)
    expired={e['id'] for e in catalog.get('events',[]) if expired_event(e,now)}
    before=len(catalog.get('markets',[]))
    catalog['markets']=[m for m in catalog.get('markets',[]) if m['event_id'] not in expired]
    catalog['events']=[e for e in catalog.get('events',[]) if e['id'] not in expired]
    return before-len(catalog['markets'])


def load(source,scope):
    with connect() as db,db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        head=db.execute('SELECT header,saved_at FROM current_native_catalog_recovery WHERE source=%s AND scope=%s',(source,scope)).fetchone()
        if not head:return None
        from .current_native_catalog import CatalogStrings, detach_event_packaging
        catalog=detach_event_packaging(head['header']);catalog['markets']=[];parsed={}
        events={e['id']:e for e in catalog['events']};now=datetime.now(timezone.utc)
        strings = CatalogStrings()
        with db.cursor(name='native_recovery') as rows:
            rows.itersize = 64
            rows.execute(native_market_metadata.RECOVERY_ROWS + ' WHERE r.source=%s ORDER BY r.market_id', (source,))
            for row in rows:
                market=market_value(row['metadata'],row['receipt_fields'],row['native_body'])
                event=events.get(market['event_id'],{});start=event.get('scheduled_start');native=market.get('_native',{})
                if expired_event(event,now):continue
                market=strings.compact(market);catalog['markets'].append(market)
                if (not row['parsed'] or native.get('closed') is True or native.get('status') in ('closed','settled','finalized')
                        or start and datetime.fromisoformat(start)<now-timedelta(hours=24)):continue
                parsed[market['id']]=decode(parsed_value(row['parsed'],row['receipt_fields'],row['native_body']),source)
        retire_expired_catalog(catalog,now)
        return catalog,parsed,head['saved_at'].isoformat()


def retain_absent(previous,current):
    """Missing from one moving pass is suspicion, never source withdrawal."""
    existing={m['id'] for m in current['markets']};events={e['id'] for e in current['events']}
    kept=[]
    now=datetime.now(timezone.utc)
    previous_events={e['id']:e for e in previous.get('events',[])}
    for market in previous.get('markets',[]):
        if market['id'] in existing:continue
        if expired_event(previous_events.get(market['event_id'],{}),now):continue
        retained=dict(market,inventory_recovery_disposition='suspected_absent')
        current['markets'].append(retained);kept.append(market['id'])
    required={m['event_id'] for m in current['markets']}-events
    current['events'].extend(e for e in previous.get('events',[]) if e['id'] in required)
    return set(kept)
