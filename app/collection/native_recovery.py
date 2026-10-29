"""Atomic complete metadata recovery. Never restore a book's connection authority."""
from dataclasses import asdict
from datetime import datetime,timezone
import json
from psycopg.types.json import Jsonb
from app.storage.store import connect
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


def save(source,scope,catalog,parsed):
    with connect() as db,db.transaction():
        db.execute('INSERT INTO current_native_catalog_recovery (source,scope,header) VALUES (%s,%s,%s) ON CONFLICT(source) DO UPDATE SET scope=EXCLUDED.scope,header=EXCLUDED.header,saved_at=now()',
                   (source,scope,Jsonb({k:v for k,v in catalog.items() if k!='markets'})))
        db.execute('DELETE FROM current_native_market_recovery WHERE source=%s',(source,))
        with db.cursor() as cur:
            cur.executemany('INSERT INTO current_native_market_recovery VALUES (%s,%s,%s,%s)',
                ((source,m['id'],Jsonb(m),Jsonb(encode(parsed[m['id']])) if m['id'] in parsed else None) for m in catalog['markets']))


def load(source,scope):
    with connect() as db,db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        head=db.execute('SELECT header,saved_at FROM current_native_catalog_recovery WHERE source=%s AND scope=%s',(source,scope)).fetchone()
        if not head:return None
        from .current_native_catalog import detach_event_packaging
        catalog=detach_event_packaging(head['header']);catalog['markets']=[];parsed={}
        events={e['id']:e for e in catalog['events']};now=datetime.now(timezone.utc)
        for row in db.execute('SELECT metadata,parsed FROM current_native_market_recovery WHERE source=%s ORDER BY market_id',(source,)):
            market=row['metadata'];catalog['markets'].append(market)
            event=events.get(market['event_id'],{});start=event.get('scheduled_start');native=market.get('_native',{})
            if (not row['parsed'] or native.get('closed') is True or native.get('status') in ('closed','settled','finalized')
                    or start and datetime.fromisoformat(start)<=now):continue
            parsed[market['id']]=decode(row['parsed'],source)
        return catalog,parsed,head['saved_at'].isoformat()


def retain_absent(previous,current):
    """Missing from one moving pass is suspicion, never source withdrawal."""
    existing={m['id'] for m in current['markets']};events={e['id'] for e in current['events']}
    kept=[]
    for market in previous.get('markets',[]):
        if market['id'] in existing:continue
        retained=dict(market,inventory_recovery_disposition='suspected_absent')
        current['markets'].append(retained);kept.append(market['id'])
    required={m['event_id'] for m in current['markets']}-events
    current['events'].extend(e for e in previous.get('events',[]) if e['id'] in required)
    return set(kept)
