"""Replaceable normalized current facts. No envelopes, history, report or retry log.

The normalized adapter record is split into shared event facts, exact selection
facts, one current offer and a shared ordered depth ladder. SQL transactions own
publication; the record read adapter reconstructs only transient finance inputs.
"""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from psycopg.types.json import Jsonb
from psycopg.pq import TransactionStatus
from .store import hashed, encoded, exact_time

VERSION='predict-current-rows-1'
MAX_EVENTS=4096  # Source mappings: supports 500 games across aggregate + two native sources.
MAX_RECORDS=32768
MAX_RECORD_BYTES=128*1024
LOCK=901095
MAX_PIPELINE_COMMANDS=128
EVENT_FIELDS=('id','sport','competition','season','stage','scheduled_start','home','away','participants','title',
    'status','state','shared_provider_ids','game_number','original_start','replacement_game_id','neutral_venue','source_participant_roles','current_occurrence_binding','observed_identity_facts','occurrence_conflict','conflicting_duplicate')


def utc():return datetime.now(timezone.utc).isoformat()


@contextmanager
def _ordered_writes(db):
    """Batch ordered commands without moving any caller-owned read barrier."""
    with db.pipeline() as pipeline:
        pending=0
        def execute(query,params=None):
            nonlocal pending
            cursor=db.execute(query,params)
            pending+=1
            if pending>=MAX_PIPELINE_COMMANDS:
                pipeline.sync();pending=0
            return cursor
        yield execute
        # Deliver delayed SQL errors before the transaction or publication hook.
        pipeline.sync()

def _clockless(value):
    """Dependency identity excludes local receipt/project clocks and body hashes."""
    if isinstance(value,list):return [_clockless(x) for x in value]
    if not isinstance(value,dict):return value
    return {k:_clockless(v) for k,v in value.items() if k not in
        ('received_at','projected_at','observed_at','receipt_sha256','sha256','orientation_evidence','revision','id')}


def contract_id(record):
    q=record['quote'];source=q['source']
    return hashed([q['venue'],source['provider'],source['native_event_id'],source['native_market_id'],source['native_outcome_id'],source.get('native_side','')])


def event_facts(event):
    """Compact exact occurrence witnesses; preserve the resolver's precedence."""
    facts={k:deepcopy(event[k]) for k in EVENT_FIELDS if k in event}
    raw=event.get('_native') or event.get('native_metadata') or {}
    shared=dict(event.get('shared_provider_ids',{}))
    if raw.get('sportradarGameId'):shared['sportradar']=str(raw['sportradarGameId'])
    if shared:facts['shared_provider_ids']=shared
    if 'game_number' not in event and 'gameNumber' in raw:facts['game_number']=deepcopy(raw['gameNumber'])
    original=event.get('original_start') or raw.get('originalStartTime')
    if original is not None:facts['original_start']=deepcopy(original)
    replacement=event.get('replacement_game_id') or raw.get('replacementGameId')
    if raw.get('rescheduledFromGameId') not in (None,0,'0'):
        replacement=replacement or str(raw['rescheduledFromGameId'])
    if replacement is not None:facts['replacement_game_id']=deepcopy(replacement)
    return facts


def prepare(record):
    row=deepcopy(record)
    for key in ('_instrument','_fingerprint'):row.pop(key,None)
    q=row.pop('quote');event=row.pop('event');source=q['source'];venue=q['venue']
    if venue not in ('kalshi','polymarket_us','novig','prophetx','pinnacle'):raise ValueError('current_row_venue')
    if not all(isinstance(source.get(k),str) and source[k] for k in ('provider','native_event_id','native_market_id','native_outcome_id')):raise ValueError('current_row_native_identity')
    event=event_facts(event)
    eid=hashed([source['provider'],source['native_event_id']]);cid=hashed([venue,source['provider'],source['native_event_id'],source['native_market_id'],source['native_outcome_id'],source.get('native_side','')])
    missing=row.pop('offer_missing',False)
    original=q['original']
    if not missing:
        if not Decimal(original['value']).is_finite():raise ValueError('current_row_price_value')
    if not original.get('units') or not original.get('quantity_units'):raise ValueError('current_row_exact_units')
    times=q['times'];received=exact_time(times['received_at']);at=times.get('source_at');order=exact_time(at) if at else None
    depth=q.pop('depth',None)
    if depth is not None:
        if len(depth)>4096:raise ValueError('current_row_depth_capacity')
        for level in depth:
            price,quantity=Decimal(level['price']),Decimal(level['quantity'])
            if not price.is_finite() or not quantity.is_finite():raise ValueError('current_row_depth_value')
            # Decimal odds are stake observations; purchase-contract prices are
            # dollar fractions. Preserve the native [0,1] boundary.
            valid_price=price>=1 if original['units']=='decimal_odds' else 0<=price<=1
            if not valid_price or quantity<=0:raise ValueError('current_row_depth_value')
    q.pop('id',None);q.pop('revision',None)
    q.pop('occurrence_match',None);q.pop('occurrence_link',None)
    q['times']={k:v for k,v in times.items() if k not in ('source_at','received_at')}
    # No receipt/envelope association is required by the current finance owner.
    meta=row.get('comparison_source_metadata',{})
    meta.pop('combined_envelope_id',None)
    native=meta.get('combined_native_binding',{})
    native.pop('catalog_envelope_id',None);native.pop('book_envelope_id',None)
    if len(encoded([event,row,q,depth]))>MAX_RECORD_BYTES:raise ValueError('current_row_record_capacity')
    revision=hashed([_clockless(event),_clockless(row),_clockless(q),depth,at])
    return dict(event_id=eid,contract_id=cid,event=event,contract=row,quote=q,depth=depth,
        source=source,venue=venue,received_at=times['received_at'],received_order=received,source_at=at,source_order=order,
        expires_order=received if event.get('status',event.get('state')) in ('completed','final','settled','cancelled') else exact_time(event['scheduled_start']),revision=revision,missing=missing)


class CurrentRowStore:
    def __init__(self,db):self.db=db

    def upsert_records(self,records,*,scopes=(),authoritative=False,now=None,source_status=None):
        """Replace only admitted exact scopes. A caller must assert completeness.

        scopes are {venue, competition, native_event_id?, native_market_id?,
        source_at?, received_at}. An incomplete/error page supplies no scopes.
        Older authoritative scopes cannot delete newer healthy offers.
        """
        if len(records)>MAX_RECORDS:raise ValueError('current_row_ingress_capacity')
        prepared=[prepare(r) for r in records];changed=0
        with self.db.transaction(), _ordered_writes(self.db) as execute:
            execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            for p in prepared:
                source=p['source'];event=p['event'];eid=p['event_id'];cid=p['contract_id']
                old=execute('SELECT source_order,received_order,revision,price_value,price_units,quantity_units FROM current_offer WHERE contract_id=%s',(cid,)).fetchone()
                if old:
                    original=p['quote']['original']
                    if not p['missing'] and (p['source_order'],p['received_order'])==(old['source_order'],old['received_order']) and (original['value'],original['units'],original['quantity_units'])!=(old['price_value'],old['price_units'],old['quantity_units']):
                        raise ValueError('current_row_equal_clock_price_conflict')
                    # Known source ordering takes precedence; receipt orders unknown clocks.
                    if p['source_order'] is not None and old['source_order'] is not None:
                        if p['source_order']<old['source_order']:continue
                    elif p['source_order'] is None and old['source_order'] is not None:continue
                    elif p['received_order']<old['received_order']:continue
                    if p['received_order']<old['received_order'] and p['source_order']==old['source_order']:continue
                ef=hashed(event);cf=hashed(p['contract'])
                execute('''INSERT INTO current_event VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                  ON CONFLICT(id) DO UPDATE SET facts=excluded.facts,revision=excluded.revision,
                    scheduled_start=excluded.scheduled_start,expires_order=excluded.expires_order
                  WHERE current_event.revision<>excluded.revision''',
                    (eid,source['provider'],source['native_event_id'],event['competition'],event['scheduled_start'],p['expires_order'],Jsonb(event),ef))
                execute('''INSERT INTO current_contract VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                  ON CONFLICT(id) DO UPDATE SET facts=excluded.facts,revision=excluded.revision
                  WHERE current_contract.revision<>excluded.revision''',
                    (cid,eid,p['venue'],source['native_market_id'],source['native_outcome_id'],source.get('native_side',''),Jsonb(p['contract']),cf))
                original=p['quote']['original']
                if p['missing']:
                    execute('DELETE FROM current_offer WHERE contract_id=%s',(cid,))
                    execute('DELETE FROM current_depth WHERE contract_id=%s',(cid,))
                    changed+=int(old is not None)
                    continue
                execute('''INSERT INTO current_offer VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                  ON CONFLICT(contract_id) DO UPDATE SET price_value=excluded.price_value,price_units=excluded.price_units,
                    quantity_units=excluded.quantity_units,source_at=excluded.source_at,source_order=excluded.source_order,
                    received_at=excluded.received_at,received_order=excluded.received_order,facts=excluded.facts,revision=excluded.revision
                  WHERE current_offer.received_order<>excluded.received_order OR current_offer.revision<>excluded.revision''',
                    (cid,original['value'],original['units'],original['quantity_units'],p['source_at'],p['source_order'],
                     p['received_at'],p['received_order'],Jsonb(p['quote']),p['revision']))
                if old is None or old['revision']!=p['revision']:
                    execute('DELETE FROM current_depth WHERE contract_id=%s',(cid,))
                    for i,level in enumerate(p['depth'] or [] if p['venue'] not in ('kalshi','polymarket_us') else []):
                        execute('INSERT INTO current_depth VALUES (%s,%s,%s,%s,%s,%s)',
                            (cid,'asks',i,str(level['price']),str(level['quantity']),original['quantity_units']))
                    changed+=1
            if authoritative:
                incoming={p['contract_id'] for p in prepared}
                for scope in scopes:
                    receipt=exact_time(scope['received_at']);order=exact_time(scope.get('source_at') or scope['received_at'])
                    key=hashed({k:v for k,v in scope.items() if k not in ('source_at','received_at')})
                    prior=execute('SELECT source_order,received_order FROM current_refresh_scope WHERE scope=%s',(key,)).fetchone()
                    if prior and (order,receipt)<(prior['source_order'],prior['received_order']):continue
                    condition=['c.venue=%s','e.competition=%s'];params=[scope['venue'],scope['competition']]
                    for name,owner in (('native_event_id','e'),('native_market_id','c')):
                        if name in scope:condition.append(owner+'.'+name+'=%s');params.append(scope[name])
                    candidates=execute('''SELECT c.id,o.source_order,o.received_order FROM current_contract c
                        JOIN current_event e ON e.id=c.event_id LEFT JOIN current_offer o ON o.contract_id=c.id
                        WHERE '''+' AND '.join(condition),params).fetchall()
                    for candidate in candidates:
                        if candidate['id'] in incoming:continue
                        if candidate['received_order'] is not None and candidate['received_order']>receipt:continue
                        if scope.get('source_at') and candidate['source_order'] is not None and candidate['source_order']>order:continue
                        execute('DELETE FROM current_contract WHERE id=%s',(candidate['id'],));changed+=1
                    execute('''INSERT INTO current_refresh_scope VALUES (%s,%s,%s) ON CONFLICT(scope)
                        DO UPDATE SET source_order=excluded.source_order,received_order=excluded.received_order''',(key,order,receipt))
            if source_status:
                for venue,state in source_status.items():
                    execute('''INSERT INTO current_source_status VALUES (%s,%s,%s) ON CONFLICT(venue)
                      DO UPDATE SET state=excluded.state,received_at=excluded.received_at WHERE current_source_status.state<>excluded.state''',
                      (venue,Jsonb(state),now or utc()))
            # Scope order guards are bounded by current work, never history.
            execute('DELETE FROM current_refresh_scope WHERE received_order<%s', (exact_time(now or utc())-172800,))
            if execute('SELECT count(*) AS n FROM current_refresh_scope').fetchone()['n']>MAX_RECORDS:
                raise ValueError('current_row_scope_capacity')
            self.expire(now=now)
            count=execute('SELECT count(*) AS n FROM current_event').fetchone()['n']
            if count>MAX_EVENTS:raise ValueError('current_row_event_capacity')
        return changed

    def withdraw_native_market(self,venue,native_event_id,native_market_id):
        """Explicit native identity change withdraws the old exact instrument."""
        eid=hashed([venue,native_event_id])
        self.db.execute('DELETE FROM current_contract WHERE venue=%s AND event_id=%s AND native_market_id=%s',(venue,eid,native_market_id))
        self.db.execute('DELETE FROM current_native_book WHERE venue=%s AND event_id=%s AND native_market_id=%s',(venue,eid,native_market_id))

    def expire_out_of_scope(self,venue,competitions,families):
        """Configured scope retirement is deliberate, independent of page absence."""
        with self.db.transaction():
            self.db.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            self.db.execute('''DELETE FROM current_contract c USING current_event e WHERE e.id=c.event_id AND c.venue=%s
                AND (NOT(e.competition=ANY(%s)) OR NOT(c.facts->'market_identity'->>'family'=ANY(%s)))''',(venue,list(competitions),list(families)))
            self.db.execute('DELETE FROM current_event e WHERE NOT EXISTS(SELECT 1 FROM current_contract c WHERE c.event_id=e.id)')

    def replace_native_books(self,books):
        """Replace synchronized exact affected books atomically with the offers."""
        with self.db.transaction(), _ordered_writes(self.db) as execute:
            execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            for book in books:
                raw=book['raw'];ref=raw['ref'];venue=ref['venue'];eid=hashed([venue,ref['event_id']]);market=ref['market_id']
                if book['sync']!='synchronized' or book['state']=='unknown':raise ValueError('current_row_incomplete_book')
                if not execute('SELECT 1 FROM current_event WHERE id=%s',(eid,)).fetchone():continue
                at=raw.get('exchange_at');order=exact_time(at) if at else None;receipt=exact_time(raw['received_at'])
                key=(venue,eid,market)
                old=execute('SELECT source_order,received_order,revision FROM current_native_book WHERE venue=%s AND event_id=%s AND native_market_id=%s',key).fetchone()
                if old:
                    if order is None and old['source_order'] is not None:continue
                    if order is not None and old['source_order'] is not None and order<old['source_order']:continue
                    if order==old['source_order'] and receipt<old['received_order']:continue
                if book['state'] in ('closed','settled','canceled'):
                    self.withdraw_native_market(venue,ref['event_id'],market)
                    continue
                outcomes=[];levels=[]
                for outcome in book['outcomes']:
                    outcomes.append(dict(outcome_id=outcome['outcome_id'],asks=outcome['asks'] is not None,bids=outcome['bids'] is not None))
                    for side in ('asks','bids'):
                        ladder=outcome[side]
                        if ladder is None:continue
                        if len(ladder['levels'])>4096:raise ValueError('current_row_depth_capacity')
                        for i,level in enumerate(ladder['levels']):
                            price=level['price'];quantity=level['quantity']
                            if not Decimal(price['value']).is_finite() or not 0<=Decimal(price['value'])<=1 or not Decimal(quantity['value']).is_finite() or Decimal(quantity['value'])<=0 or quantity['unit']!='contracts':raise ValueError('current_row_depth_value')
                            levels.append((*key,outcome['outcome_id'],side,i,price['value'],price.get('unit',price.get('units','usd_per_contract')),quantity['value'],quantity['unit']))
                revision=hashed([at,book['state'],book['sync'],outcomes,levels])
                if old and (order,receipt)==(old['source_order'],old['received_order']) and old['revision']!=revision:
                    raise ValueError('current_row_equal_clock_book_conflict')
                execute('''INSERT INTO current_native_book VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(venue,event_id,native_market_id) DO UPDATE SET source_at=excluded.source_at,source_order=excluded.source_order,
                    received_at=excluded.received_at,received_order=excluded.received_order,revision=excluded.revision,state=excluded.state,sync=excluded.sync,
                    sequence=excluded.sequence,outcomes=excluded.outcomes WHERE current_native_book.received_order<>excluded.received_order OR current_native_book.revision<>excluded.revision''',
                    (*key,at,order,raw['received_at'],receipt,revision,book['quantity_unit'],book['state'],book['sync'],str(book.get('sequence')),Jsonb(outcomes)))
                if old and old['revision']==revision:continue
                execute('DELETE FROM current_native_depth WHERE venue=%s AND event_id=%s AND native_market_id=%s',key)
                for level in levels:execute('INSERT INTO current_native_depth VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',level)

    def expire(self,*,now=None):
        now=now or utc()
        return self.db.execute('DELETE FROM current_event WHERE expires_order<%s RETURNING id',(exact_time(now),)).fetchall()

    def capture(self,*,include_depth=True):
        # MVCC binds the full frame without holding a writer lock while callers
        # resolve occurrences or build catalogs. Existing caller-owned repeatable
        # read snapshots and writer transactions retain their own transaction.
        owns_transaction=self.db.info.transaction_status==TransactionStatus.IDLE
        with self.db.transaction():
            if owns_transaction:self.db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            epoch=self.db.execute('SELECT epoch FROM current_row_epoch WHERE singleton=true').fetchone()['epoch']
            raw=self.db.execute('''SELECT c.id AS contract_id,e.facts AS event,c.facts AS contract,o.facts AS quote,
                o.source_at,o.received_at,o.revision FROM current_offer o JOIN current_contract c ON c.id=o.contract_id
                JOIN current_event e ON e.id=c.event_id WHERE e.expires_order>=%s ORDER BY c.id''',(exact_time(utc()),)).fetchall()
            if len(raw)>MAX_RECORDS:raise ValueError('current_row_read_capacity')
            levels=self.db.execute('SELECT contract_id,side,level,price_value,quantity_value FROM current_depth ORDER BY contract_id,side,level').fetchall() if include_depth else []
            by_contract={}
            for level in levels:
                if level['side']=='asks':by_contract.setdefault(level['contract_id'],[]).append(dict(price=level['price_value'],quantity=level['quantity_value']))
            native_levels={}
            for level in (self.db.execute("SELECT * FROM current_native_depth WHERE side='asks' ORDER BY venue,event_id,native_market_id,native_outcome_id,level").fetchall() if include_depth else []):
                key=tuple(level[k] for k in ('venue','event_id','native_market_id','native_outcome_id'))
                native_levels.setdefault(key,[]).append(dict(price=level['price_value'],quantity=level['quantity_value']))
            records=[]
            for row in raw:
                q=deepcopy(row['quote']);q.update(id='',revision=1)
                q['times'].update(source_at=row['source_at'],received_at=row['received_at'])
                q['times'].setdefault('projected_at',None)
                if q['venue'] in ('kalshi','polymarket_us'):
                    source=q['source'];key=(q['venue'],hashed([source['provider'],source['native_event_id']]),source['native_market_id'],source['native_outcome_id'])
                    if include_depth:q['depth']=native_levels.get(key,[])
                elif row['contract_id'] in by_contract:q['depth']=by_contract[row['contract_id']]
                records.append(dict(deepcopy(row['contract']),event=deepcopy(row['event']),quote=q))
            statuses={r['venue']:r['state'] for r in self.db.execute('SELECT venue,state FROM current_source_status').fetchall()}
            native={hashed([r['venue'],r['native_event_id'],r['native_market_id']]):r['revision'] for r in self.db.execute('SELECT b.venue,e.native_event_id,b.native_market_id,b.revision FROM current_native_book b JOIN current_event e ON e.id=b.event_id').fetchall()}
            dependencies={r['contract_id']:r['revision'] for r in raw}
            return dict(records=records,epoch=epoch,revision=hashed([epoch,dependencies,native]),source_status=statuses,dependency_revisions=dependencies,native_dependency_revisions=native)

    def hydrate_records(self,records):
        """Fetch only selected execution ask ladders, never a whole slate's depth."""
        if len(records)>MAX_RECORDS:raise ValueError('current_row_read_capacity')
        ids=[contract_id(record) for record in records];depth={}
        rows=self.db.execute('''SELECT c.id AS contract_id,d.level,d.price_value,d.quantity_value FROM current_contract c
          JOIN current_native_depth d ON d.venue=c.venue AND d.event_id=c.event_id
            AND d.native_market_id=c.native_market_id AND d.native_outcome_id=c.native_outcome_id
          WHERE c.id=ANY(%s) AND d.side='asks' ORDER BY c.id,d.level''',(ids,)).fetchall()
        rows+=self.db.execute('SELECT contract_id,level,price_value,quantity_value FROM current_depth WHERE contract_id=ANY(%s) AND side=%s ORDER BY contract_id,level',(ids,'asks')).fetchall()
        for row in rows:depth.setdefault(row['contract_id'],[]).append(dict(price=row['price_value'],quantity=row['quantity_value']))
        out=deepcopy(records)
        for record in out:
            cid=contract_id(record)
            if record['quote']['venue'] in ('kalshi','polymarket_us') or cid in depth:record['quote']['depth']=depth.get(cid,[])
        return out

    def records(self):return self.capture()['records']
