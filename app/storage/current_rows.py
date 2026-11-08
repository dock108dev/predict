"""Replaceable normalized current facts. No envelopes, history, report or retry log.

The normalized adapter record is split into shared event facts, exact selection
facts, one current offer and a shared ordered depth ladder. SQL transactions own
publication; the record read adapter reconstructs only transient finance inputs.
"""
from copy import deepcopy
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone, timedelta
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
    'status','state','shared_provider_ids','game_number','original_start','replacement_game_id','neutral_venue','source_participant_roles','native_role_evidence','current_occurrence_binding','observed_identity_facts','occurrence_conflict','conflicting_duplicate','schedule_metadata','schedule_conflict')


def utc():return datetime.now(timezone.utc).isoformat()


def event_retention(event,quote,at):
    # Storage lifetime is separate from the existing quote freshness policy.
    # Only a source-evidenced post-start phase can retain a started occurrence;
    # old pregame observations never extend their own deadline.
    from app.comparison.game_phase import price_phase
    phase=price_phase(event,quote,at)
    start=datetime.fromisoformat(event['scheduled_start'].replace('Z','+00:00'))
    if phase['state'] in ('live','suspended','final'):
        return exact_time((start+timedelta(hours=24)).isoformat())
    return exact_time(event['scheduled_start'])


def _evidence_order(source, confirmation):
    clocks=[exact_time(v) for v in (source,None if confirmation is None else confirmation['confirmed_at']) if v is not None]
    return max(clocks) if clocks else None


@contextmanager
def _ordered_writes(db):
    """Batch ordered commands without moving any caller-owned read barrier."""
    with ExitStack() as stack:
        pipeline=stack.enter_context(db.pipeline())
        pending=0
        def execute(query,params=None,*,synchronous=False):
            nonlocal pending,pipeline
            if query.lstrip().upper().startswith('SELECT'):
                # Leave pipeline protocol for reads. Large bound-array SELECTs
                # can deadlock in pipeline mode on the installed libpq/server
                # pairing even with an explicit Sync before and after them.
                stack.close()
                cursor=db.execute(query,params)
                pipeline=stack.enter_context(db.pipeline());pending=0
                return cursor
            # Large JSON bind values can fill libpq's pipeline buffers while
            # the server waits for the next message. Send these synchronously
            # between existing ordered barriers; no sports fact is dropped.
            if synchronous or params and any(isinstance(value,Jsonb) and len(encoded(value.obj))>32*1024 for value in params):
                stack.close()
                cursor=db.execute(query,params)
                pipeline=stack.enter_context(db.pipeline());pending=0
                return cursor
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


class _OfferBatch:
    """Bounded SQL messages after sequential evidence admission, under its lock.

    Duplicate identities and explicit deletions flush the earlier writes first.
    JSON numeric clocks travel as decimal strings, never floating point.
    """
    fields=('contract_id','price_value','price_units','quantity_units','source_at',
            'source_order','received_at','received_order','facts','revision')

    def __init__(self,execute):
        self.execute=execute;self.rows=[];self.keys=set();self.size=0

    def append(self,values):
        value=dict(zip(self.fields,values))
        for field in ('source_order','received_order'):
            if value[field] is not None:value[field]=str(value[field])
        size=len(encoded(value))
        if value['contract_id'] in self.keys or len(self.rows)>=16 or self.size+size>32768:self.flush()
        self.rows.append(value);self.keys.add(value['contract_id']);self.size+=size

    def flush(self):
        if not self.rows:return
        self.execute('''INSERT INTO current_offer
          (contract_id,price_value,price_units,quantity_units,source_at,source_order,received_at,received_order,facts,revision)
          SELECT * FROM jsonb_to_recordset(%s) AS v(contract_id text,price_value text,price_units text,quantity_units text,
            source_at text,source_order numeric,received_at text,received_order numeric,facts jsonb,revision text)
          ON CONFLICT(contract_id) DO UPDATE SET price_value=excluded.price_value,price_units=excluded.price_units,
            quantity_units=excluded.quantity_units,source_at=excluded.source_at,source_order=excluded.source_order,
            received_at=excluded.received_at,received_order=excluded.received_order,facts=excluded.facts,revision=excluded.revision
          WHERE current_offer.received_order<>excluded.received_order OR current_offer.revision<>excluded.revision''',
          (Jsonb(self.rows),),synchronous=True)
        self.rows=[];self.keys=set();self.size=0


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


def project_contract(event,contract,received_at):
    """Restore the exact native observation clock from its shared quote row."""
    from .schedule_metadata import project
    value=project(event,contract)
    meta=value.get('comparison_source_metadata',{})
    if meta.get('observed_at_from_quote_receipt') is True:
        meta.pop('observed_at_from_quote_receipt')
        meta['observed_at']=received_at
    return value


def prepare(record, *, batch_events=None):
    # Only EVENT_FIELDS survive storage. Copying the full native event (often
    # packaging many markets) just to discard it repeated per price and side.
    # event_facts detaches every retained field and keeps its native witnesses.
    row={k:v for k,v in record.items() if k!='event'}
    if batch_events is None:row=deepcopy(row)
    else:
        # Private normalized batch; copy every path mutated below. Nested
        # source inputs serve this one SQL job and never become a global cache.
        row['quote']=dict(row['quote'])
        if 'comparison_source_metadata' in row:
            meta=dict(row['comparison_source_metadata']);row['comparison_source_metadata']=meta
            if 'combined_native_binding' in meta:meta['combined_native_binding']=dict(meta['combined_native_binding'])
    for key in ('_instrument','_fingerprint'):row.pop(key,None)
    q=row.pop('quote');event=record['event'];source=q['source'];venue=q['venue']
    if venue not in ('kalshi','polymarket_us','novig','prophetx','pinnacle'):raise ValueError('current_row_venue')
    if not all(isinstance(source.get(k),str) and source[k] for k in ('provider','native_event_id','native_market_id','native_outcome_id')):raise ValueError('current_row_native_identity')
    from .schedule_metadata import binding, witness
    key=id(event);entry=batch_events.get(key) if batch_events is not None else None
    if entry is None:
        original_event=event;event=event_facts(event)
        event_revision=hashed(event);event_clockless=_clockless(event)
        schedule=binding(event) if witness(event) else None
        if batch_events is not None:batch_events[key]=(original_event,event,event_revision,event_clockless,schedule)
    else:_,event,event_revision,event_clockless,schedule=entry
    if schedule is not None:row.setdefault('comparison_source_metadata',{})['schedule_binding']=schedule
    eid=hashed([source['provider'],source['native_event_id']]);cid=hashed([venue,source['provider'],source['native_event_id'],source['native_market_id'],source['native_outcome_id'],source.get('native_side','')])
    missing=row.pop('offer_missing',False)
    original=q['original']
    if not missing:
        if not Decimal(original['value']).is_finite():raise ValueError('current_row_price_value')
    if not original.get('units') or not original.get('quantity_units'):raise ValueError('current_row_exact_units')
    times=q['times'];received=exact_time(times['received_at']);at=times.get('source_at');order=exact_time(at) if at else None
    if q.get('book_confirmation'):
        from app.collection.current_confirmation import validate
        validate(q['book_confirmation'],dict(venue=venue,event_id=source['native_event_id'],market_id=source['native_market_id']))
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
    expires=event_retention(event,q,times['received_at'])
    q['times']={k:v for k,v in times.items() if k not in ('source_at','received_at')}
    # No receipt/envelope association is required by the current finance owner.
    meta=row.get('comparison_source_metadata',{})
    meta.pop('combined_envelope_id',None)
    native=meta.get('combined_native_binding',{})
    native.pop('catalog_envelope_id',None);native.pop('book_envelope_id',None)
    if len(encoded([event,row,q,depth]))>MAX_RECORD_BYTES:raise ValueError('current_row_record_capacity')
    revision=hashed([event_clockless,_clockless(row),_clockless(q),depth,at])
    # Current native normalization explicitly stamps this field with the quote
    # receipt. Store that clock once, in the offer, so every price update does
    # not rewrite an otherwise unchanged multi-kilobyte contract and its TOAST.
    # Independent metadata clocks retain their literal value.
    if (venue in ('kalshi','polymarket_us') and meta.get('combined_native_binding')
            and meta.get('observed_at')==times['received_at']):
        meta.pop('observed_at');meta['observed_at_from_quote_receipt']=True
    return dict(event_id=eid,contract_id=cid,event=event,event_revision=event_revision,
        contract=row,contract_revision=hashed(row),quote=q,depth=depth,
        source=source,venue=venue,received_at=times['received_at'],received_order=received,source_at=at,source_order=order,
        expires_order=expires,revision=revision,missing=missing)


class CurrentRowStore:
    def __init__(self,db):self.db=db

    def restore_schedule_bindings(self,snapshot,*,path,snapshot_sha256,now=None):
        """Bounded explicit recovery of lost metadata, never restore old offers.

        A retained capture must match the entire current raw contract exactly.
        Its event witness is an upper bound on source observation time, labelled
        separately from provider/metadata receipts. Current schedule authority
        must come from a strictly later ordinary native metadata response.
        """
        from .schedule_metadata import retained_binding
        events=snapshot['current_event'];contracts=snapshot['current_contract']
        if len(events)>MAX_EVENTS or len(contracts)>MAX_RECORDS or len(encoded(snapshot))>96*1024*1024:
            raise ValueError('schedule_snapshot_capacity')
        if len(snapshot_sha256)!=64 or not path or len(path)>1024:raise ValueError('schedule_snapshot_provenance')
        captured_at=snapshot['observed_at'];exact_time(captured_at)
        prior_events={row['id']:row for row in events};changed=[]
        with self.db.transaction():
            self.db.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            for captured in contracts:
                prior=prior_events.get(captured['event_id'])
                if prior is None or prior['revision']!=hashed(prior['facts']) or captured['revision']!=hashed(captured['facts']):continue
                row=self.db.execute('''SELECT c.facts,e.facts AS event,e.provider,e.native_event_id,e.expires_order
                    FROM current_contract c JOIN current_event e ON e.id=c.event_id WHERE c.id=%s''',(captured['id'],)).fetchone()
                if (row is None or row['expires_order']<exact_time(now or utc()) or row['facts']!=captured['facts']
                        or row['provider']!=prior['provider'] or row['native_event_id']!=prior['native_event_id']):continue
                support=retained_binding(prior['facts'],row['event'],row['facts'],captured_at=captured_at,
                    path=path,snapshot_sha256=snapshot_sha256,contract_revision=captured['revision'])
                if support is None:continue
                facts=deepcopy(row['facts']);facts.setdefault('comparison_source_metadata',{})['schedule_binding']=support
                if len(encoded([row['event'],facts]))>MAX_RECORD_BYTES:continue
                self.db.execute('UPDATE current_contract SET facts=%s,revision=%s WHERE id=%s',
                    (Jsonb(facts),hashed(facts),captured['id']))
                changed.append(captured['id'])
        return changed

    def upsert_records(self,records,*,scopes=(),authoritative=False,now=None,source_status=None,material_rows=None):
        """Replace only admitted exact scopes. A caller must assert completeness.

        scopes are {venue, competition, native_event_id?, native_market_id?,
        source_at?, received_at}. An incomplete/error page supplies no scopes.
        Older authoritative scopes cannot delete newer healthy offers.
        """
        return self._upsert_prepared([prepare(r) for r in records],scopes=scopes,
            authoritative=authoritative,now=now,source_status=source_status,material_rows=material_rows)

    def _upsert_prepared(self,prepared,*,scopes=(),authoritative=False,now=None,source_status=None,material_rows=None):
        """Internal prepare() results, optionally produced by the owned CPU worker."""
        changed=0
        with self.db.transaction(), _ordered_writes(self.db) as execute:
            execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            # The writer lock makes these batch reads stable. Update the local
            # views after each accepted write so duplicate identities retain
            # exactly the sequential read-after-write conflict semantics.
            old_offers={r['contract_id']:r for r in execute(
                "SELECT contract_id,source_at,source_order,received_order,revision,price_value,price_units,quantity_units,facts->'book_confirmation' AS confirmation FROM current_offer WHERE contract_id=ANY(%s)",
                (list({p['contract_id'] for p in prepared}),)).fetchall()}
            old_events={r['id']:r for r in execute('SELECT id,facts,expires_order,revision FROM current_event WHERE id=ANY(%s)',
                (list({p['event_id'] for p in prepared}),)).fetchall()}
            old_contracts={r['id']:r['revision'] for r in execute('SELECT id,revision FROM current_contract WHERE id=ANY(%s)',
                (list({p['contract_id'] for p in prepared}),)).fetchall()}
            # Native ladders live in current_native_depth. Avoid a DELETE for
            # every changing native side when no legacy per-contract rows exist.
            # Read under the same writer lock; retained legacy rows still get
            # removed when their accepted replacement is committed.
            native_legacy_depth={r['contract_id'] for r in execute(
                'SELECT DISTINCT contract_id FROM current_depth WHERE contract_id=ANY(%s)',
                (list({p['contract_id'] for p in prepared if p['venue'] in ('kalshi','polymarket_us')}),)).fetchall()}
            offers=_OfferBatch(execute)
            for p in prepared:
                source=p['source'];event=p['event'];eid=p['event_id'];cid=p['contract_id']
                from .schedule_metadata import choose, witness
                old=old_offers.get(cid)
                price_admitted=True
                if old:
                    original=p['quote']['original']
                    if not p['missing'] and (p['source_order'],p['received_order'])==(old['source_order'],old['received_order']) and (original['value'],original['units'],original['quantity_units'])!=(old['price_value'],old['price_units'],old['quantity_units']):
                        raise ValueError('current_row_equal_clock_price_conflict')
                    incoming=_evidence_order(p['source_at'],p['quote'].get('book_confirmation'))
                    previous=_evidence_order(old['source_at'],old['confirmation'])
                    if incoming is not None and previous is not None:
                        if incoming<previous:price_admitted=False
                    elif incoming is None and previous is not None:price_admitted=False
                    elif p['received_order']<old['received_order']:price_admitted=False
                    if p['received_order']<old['received_order'] and p['source_order']==old['source_order']:price_admitted=False
                if not price_admitted and material_rows is not None:material_rows.order_refusals+=1
                if not price_admitted and not witness(event):continue
                prior_event=old_events.get(eid)
                # Metadata admission is independent of price-source ordering.
                # Never extend an expired offering around an old retained book.
                if prior_event and prior_event['expires_order']<exact_time(now or utc()) and p['expires_order']<=prior_event['expires_order']:continue
                # prepare() already detached and validated this exact metadata.
                # Identical non-conflicted events need no repeated witness/core
                # hashing for every outcome in a native batch. Changed metadata
                # still goes through the full independent schedule owner.
                incoming_revision=p.get('event_revision') or hashed(event)
                if not (prior_event and prior_event['revision']==incoming_revision and not event.get('schedule_conflict')):
                    event=choose(prior_event['facts'] if prior_event else None,event,observed_at=now or utc())
                phase_quote=dict(p['quote'],times=dict(p['quote']['times'],source_at=p['source_at'],received_at=p['received_at']))
                expiry=event_retention(event,phase_quote,now or utc())
                # A sibling's older pregame quote cannot retire an occurrence
                # already retained by post-start evidence. This retains storage
                # only; each offer still needs its own current lifecycle proof.
                if prior_event and prior_event['facts']['scheduled_start']==event['scheduled_start']:
                    expiry=max(expiry,prior_event['expires_order'])
                ef=incoming_revision if event is p['event'] else prior_event['revision'] if prior_event and event is prior_event['facts'] else hashed(event)
                if prior_event is None or prior_event['revision']!=ef or prior_event['expires_order']!=expiry:
                    execute('''INSERT INTO current_event VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                      ON CONFLICT(id) DO UPDATE SET facts=excluded.facts,revision=excluded.revision,
                        scheduled_start=excluded.scheduled_start,expires_order=excluded.expires_order
                      WHERE current_event.revision<>excluded.revision OR current_event.expires_order<>excluded.expires_order''',
                        (eid,source['provider'],source['native_event_id'],event['competition'],event['scheduled_start'],expiry,Jsonb(event),ef))
                    old_events[eid]=dict(facts=event,revision=ef,expires_order=
                        expiry)
                if not price_admitted:continue
                if material_rows is not None:material_rows.observe(p,old,event)
                cf=p.get('contract_revision') or hashed(p['contract'])
                if old_contracts.get(cid)!=cf:
                    if material_rows is not None:
                        if cid in old_contracts:material_rows.contract_updates+=1
                        else:material_rows.contract_inserts+=1
                    execute('''INSERT INTO current_contract VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                      ON CONFLICT(id) DO UPDATE SET facts=excluded.facts,revision=excluded.revision
                      WHERE current_contract.revision<>excluded.revision''',
                        (cid,eid,p['venue'],source['native_market_id'],source['native_outcome_id'],source.get('native_side',''),Jsonb(p['contract']),cf))
                    old_contracts[cid]=cf
                original=p['quote']['original']
                if p['missing']:
                    if old is not None:
                        offers.flush()
                        execute('DELETE FROM current_offer WHERE contract_id=%s',(cid,))
                    if p['venue'] not in ('kalshi','polymarket_us') or cid in native_legacy_depth:
                        execute('DELETE FROM current_depth WHERE contract_id=%s',(cid,))
                    changed+=int(old is not None)
                    old_offers.pop(cid,None)
                    continue
                offers.append((cid,original['value'],original['units'],original['quantity_units'],p['source_at'],p['source_order'],
                     p['received_at'],p['received_order'],p['quote'],p['revision']))
                old_offers[cid]=dict(source_at=p['source_at'],source_order=p['source_order'],received_order=p['received_order'],
                    revision=p['revision'],price_value=original['value'],price_units=original['units'],quantity_units=original['quantity_units'],
                    confirmation=p['quote'].get('book_confirmation'))
                if old is None or old['revision']!=p['revision']:
                    if p['venue'] not in ('kalshi','polymarket_us') or cid in native_legacy_depth:
                        execute('DELETE FROM current_depth WHERE contract_id=%s',(cid,))
                    for i,level in enumerate(p['depth'] or [] if p['venue'] not in ('kalshi','polymarket_us') else []):
                        execute('INSERT INTO current_depth VALUES (%s,%s,%s,%s,%s,%s)',
                            (cid,'asks',i,str(level['price']),str(level['quantity']),original['quantity_units']))
                    changed+=1
            offers.flush()
            if authoritative:
                incoming={p['contract_id'] for p in prepared}
                # Native book batches have disjoint exact market scopes. Read
                # their guards and membership together rather than forcing two
                # pipeline round trips per market. General overlapping aggregate
                # scopes retain their sequential read-after-write path.
                scope_keys=[hashed({k:v for k,v in s.items() if k not in ('source_at','received_at')}) for s in scopes]
                bulk=bool(scopes) and len(set(scope_keys))==len(scope_keys) and all(
                    s.get('venue') in ('kalshi','polymarket_us') and s.get('native_event_id') and s.get('native_market_id') for s in scopes)
                if bulk:
                    prior_scopes={r['scope']:r for r in execute('SELECT scope,source_order,received_order FROM current_refresh_scope WHERE scope=ANY(%s)',(scope_keys,)).fetchall()}
                    by_scope={key:[] for key in scope_keys}
                    query='''SELECT w.scope,c.id,o.source_order,o.received_order FROM
                        unnest(%s::text[],%s::text[],%s::text[],%s::text[],%s::text[])
                        AS w(scope,venue,competition,event_id,market_id)
                        JOIN current_event e ON e.native_event_id=w.event_id AND e.competition=w.competition
                        JOIN current_contract c ON c.event_id=e.id AND c.venue=w.venue AND c.native_market_id=w.market_id
                        LEFT JOIN current_offer o ON o.contract_id=c.id'''
                    for candidate in execute(query,(scope_keys,*[[s[k] for s in scopes] for k in ('venue','competition','native_event_id','native_market_id')])).fetchall():
                        by_scope[candidate['scope']].append(candidate)
                scope_updates=[]
                for scope,key in zip(scopes,scope_keys):
                    receipt=exact_time(scope['received_at']);order=exact_time(scope.get('source_at') or scope['received_at'])
                    prior=prior_scopes.get(key) if bulk else execute('SELECT source_order,received_order FROM current_refresh_scope WHERE scope=%s',(key,)).fetchone()
                    if prior and (order,receipt)<(prior['source_order'],prior['received_order']):continue
                    condition=['c.venue=%s','e.competition=%s'];params=[scope['venue'],scope['competition']]
                    if 'aggregate_route' in scope:
                        route=scope['aggregate_route']
                        if route not in ('featured','alternate') or scope['venue'] not in ('novig','prophetx','pinnacle'):
                            raise ValueError('aggregate_refresh_route')
                        condition.append("c.native_market_id "+('LIKE' if route=='alternate' else 'NOT LIKE')+" 'alternate:%%'")
                    for name,owner in (('native_event_id','e'),('native_market_id','c')):
                        if name in scope:condition.append(owner+'.'+name+'=%s');params.append(scope[name])
                    candidates=by_scope[key] if bulk else execute('''SELECT c.id,o.source_order,o.received_order FROM current_contract c
                        JOIN current_event e ON e.id=c.event_id LEFT JOIN current_offer o ON o.contract_id=c.id
                        WHERE '''+' AND '.join(condition),params).fetchall()
                    for candidate in candidates:
                        if candidate['id'] in incoming:continue
                        if candidate['received_order'] is not None and candidate['received_order']>receipt:continue
                        if scope.get('source_at') and candidate['source_order'] is not None and candidate['source_order']>order:continue
                        if material_rows is not None:
                            material_rows.scope_retirements+=1
                            material_rows.scope_offer_retirements+=int(candidate['received_order'] is not None)
                        execute('DELETE FROM current_contract WHERE id=%s',(candidate['id'],));changed+=1
                    if bulk:
                        scope_updates.append((key,order,receipt))
                    else:
                        execute('INSERT INTO current_refresh_scope VALUES (%s,%s,%s) ON CONFLICT(scope) '
                            'DO UPDATE SET source_order=excluded.source_order,received_order=excluded.received_order',(key,order,receipt))
                if scope_updates:
                    # Bulk keys are unique. The guard above still compares each
                    # scope's original source and receipt order under LOCK.
                    execute("""INSERT INTO current_refresh_scope SELECT * FROM unnest(%s::text[],%s::numeric[],%s::numeric[])
                        ON CONFLICT(scope) DO UPDATE SET source_order=excluded.source_order,received_order=excluded.received_order
                        WHERE (current_refresh_scope.source_order,current_refresh_scope.received_order)
                           IS DISTINCT FROM (excluded.source_order,excluded.received_order)""",tuple(map(list,zip(*scope_updates))))
            if source_status:
                lost=[(venue,state.get('state','unavailable')) for venue,state in source_status.items()
                      if state.get('state') not in ('available','budget_delayed')]
                if lost:
                    # One join invalidates all unavailable venues atomically.
                    # Repeat the test even on the same health state so an offer
                    # newly admitted by another writer cannot regain continuity.
                    execute("""UPDATE current_offer o SET facts=jsonb_set(o.facts,'{state}',to_jsonb(lost.state)),
                        revision=encode(sha256(convert_to(o.revision||lost.state,'UTF8')),'hex')
                        FROM current_contract c JOIN unnest(%s::text[],%s::text[]) lost(venue,state) ON c.venue=lost.venue
                        WHERE c.id=o.contract_id AND o.facts->>'state' IN ('available','budget_delayed')""",
                        tuple(map(list,zip(*lost))))
                for venue,state in source_status.items():
                    execute('''INSERT INTO current_source_status VALUES (%s,%s,%s) ON CONFLICT(venue)
                      DO UPDATE SET state=excluded.state,received_at=excluded.received_at WHERE current_source_status.state<>excluded.state''',
                      (venue,Jsonb(state),now or utc()))
            # Scope order guards are bounded by current work, never history.
            execute('DELETE FROM current_refresh_scope WHERE received_order<%s', (exact_time(now or utc())-172800,))
            self.expire(now=now)
        return changed

    def withdraw_native_market(self,venue,native_event_id,native_market_id):
        """Explicit native identity change withdraws the old exact instrument."""
        self.withdraw_native_markets([(venue,native_event_id,native_market_id)])

    def withdraw_native_markets(self,keys, *, reimaging=False, deferred=False, measure=False):
        """One atomic set operation for an exact catalog delta, never a source wipe."""
        keys=sorted(set(keys))
        if not keys:return
        values=([k[0] for k in keys],[hashed([k[0],k[1]]) for k in keys],[k[2] for k in keys])
        with self.db.transaction():
            self.db.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            tables=('current_contract','current_native_book')
            if reimaging:
                self.db.execute("""UPDATE current_offer o SET
                    facts=jsonb_set(o.facts,'{state}','"resyncing"'::jsonb),
                    revision=encode(sha256(convert_to(o.revision||'resyncing','UTF8')),'hex')
                    FROM current_contract c JOIN unnest(%s::text[],%s::text[],%s::text[])
                    AS wanted(venue,event_id,native_market_id) USING(venue,event_id,native_market_id)
                    WHERE o.contract_id=c.id AND o.facts->>'state' IN ('available','budget_delayed')""",values)
                tables=('current_native_book',)
            counts=dict(keys=len(keys),contracts=0,offers=0,books=0)
            if deferred:
                # Membership and all offers/depth disappear together. The
                # detached body is invisible to independent contract readers.
                retired=self.db.execute("""UPDATE current_contract_storage AS c SET active=false
                    FROM unnest(%s::text[],%s::text[],%s::text[]) AS wanted(venue,event_id,market_id)
                    WHERE c.active AND c.venue=wanted.venue AND c.event_id=wanted.event_id
                    AND c.native_market_id=wanted.market_id RETURNING c.id""",values).fetchall()
                ids=[r['id'] for r in retired]
                counts.update(contracts=len(ids),deferred_bodies=len(ids))
                counts['offers']=self.db.execute('DELETE FROM current_offer WHERE contract_id=ANY(%s)',(ids,)).rowcount
                self.db.execute('DELETE FROM current_depth WHERE contract_id=ANY(%s)',(ids,))
                tables=('current_native_book',)
            for table in tables:
                delete='DELETE FROM '+table+' AS c USING unnest(%s::text[],%s::text[],%s::text[]) AS wanted(venue,event_id,market_id) '+\
                    'WHERE c.venue=wanted.venue AND c.event_id=wanted.event_id AND c.native_market_id=wanted.market_id'
                if measure and table=='current_contract':
                    # The deleting CTE and the count see the same pre-delete
                    # statement snapshot, including offers removed by cascade.
                    counted=self.db.execute('WITH retired AS ('+delete+' RETURNING c.id) '
                        'SELECT count(*) contracts,count(o.contract_id) offers FROM retired r '
                        'LEFT JOIN current_offer o ON o.contract_id=r.id',values).fetchone()
                    counts.update(counted)
                else:
                    result=self.db.execute(delete,values)
                    if table=='current_native_book':counts['books']=result.rowcount
            return counts

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
            keys=[(b['raw']['ref']['venue'],hashed([b['raw']['ref']['venue'],b['raw']['ref']['event_id']]),b['raw']['ref']['market_id']) for b in books]
            events={r['id'] for r in execute('SELECT id FROM current_event WHERE id=ANY(%s)',(list({k[1] for k in keys}),)).fetchall()}
            prior={(r['venue'],r['event_id'],r['native_market_id']):r for r in execute(
                'SELECT b.venue,b.event_id,b.native_market_id,b.source_at,b.source_order,b.received_order,b.revision,b.confirmation,b.depth_revision '
                'FROM current_native_book b JOIN unnest(%s::text[],%s::text[],%s::text[]) wanted(venue,event_id,native_market_id) '
                'USING(venue,event_id,native_market_id)',([k[0] for k in keys],[k[1] for k in keys],[k[2] for k in keys])).fetchall()}
            from .native_ladder_batch import LadderBatch
            pending_ladders=LadderBatch(execute)
            for book in books:
                raw=book['raw'];ref=raw['ref'];venue=ref['venue'];eid=hashed([venue,ref['event_id']]);market=ref['market_id']
                if book['sync']!='synchronized' or book['state']=='unknown':raise ValueError('current_row_incomplete_book')
                if eid not in events:continue
                at=raw.get('exchange_at');order=exact_time(at) if at else None;receipt=exact_time(raw['received_at'])
                confirmation=book.get('book_confirmation')
                if confirmation:
                    from app.collection.current_confirmation import validate
                    validate(confirmation,ref,book)
                key=(venue,eid,market)
                old=prior.get(key)
                if old:
                    incoming=_evidence_order(at,confirmation);previous=_evidence_order(old['source_at'],old['confirmation'])
                    if incoming is None and previous is not None:continue
                    if incoming is not None and previous is not None and incoming<previous:continue
                    if receipt<old['received_order']:continue
                    if order==old['source_order'] and receipt<old['received_order']:continue
                if book['state'] in ('closed','settled','canceled'):
                    pending_ladders.flush()
                    self.withdraw_native_market(venue,ref['event_id'],market)
                    prior.pop(key,None)
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
                depth_revision=hashed(levels)
                revision=hashed([at,book['state'],book['sync'],outcomes,levels])
                if old and (order,receipt)==(old['source_order'],old['received_order']) and old['revision']!=revision:
                    raise ValueError('current_row_equal_clock_book_conflict')
                execute('''INSERT INTO current_native_book VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(venue,event_id,native_market_id) DO UPDATE SET source_at=excluded.source_at,source_order=excluded.source_order,
                    received_at=excluded.received_at,received_order=excluded.received_order,revision=excluded.revision,state=excluded.state,sync=excluded.sync,
                    sequence=excluded.sequence,outcomes=excluded.outcomes,confirmation=excluded.confirmation,depth_revision=excluded.depth_revision
                    WHERE current_native_book.received_order<>excluded.received_order OR current_native_book.revision<>excluded.revision OR current_native_book.confirmation IS DISTINCT FROM excluded.confirmation OR current_native_book.depth_revision IS DISTINCT FROM excluded.depth_revision''',
                    (*key,at,order,raw['received_at'],receipt,revision,book['quantity_unit'],book['state'],book['sync'],str(book.get('sequence')),Jsonb(outcomes),Jsonb(confirmation) if confirmation else None,depth_revision))
                prior[key]=dict(source_at=at,source_order=order,received_order=receipt,revision=revision,confirmation=confirmation,depth_revision=depth_revision)
                if old and old['depth_revision']==depth_revision:continue
                # One exact side image; rank shifts mutate one compact value,
                # not every following level. The header/depth revision above is
                # unchanged and commits atomically with these complete ladders.
                ladders={}
                for level in levels:
                    ladders.setdefault((level[3],level[4]),[]).append(list(level[6:]))
                pending_ladders.append(key,ladders)
            pending_ladders.flush()

    def expire(self,*,now=None):
        now=now or utc()
        with self.db.transaction():
            self.db.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            return self.db.execute('DELETE FROM current_event WHERE expires_order<%s RETURNING id',(exact_time(now),)).fetchall()

    def capture(self,*,include_depth=True,event_ids=None,resource_guard=None,contract_ids=None):
        # MVCC binds the full frame without holding a writer lock while callers
        # resolve occurrences or build catalogs. Existing caller-owned repeatable
        # read snapshots and writer transactions retain their own transaction.
        owns_transaction=self.db.info.transaction_status==TransactionStatus.IDLE
        with self.db.transaction():
            if owns_transaction:self.db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            if event_ids is not None and not event_ids:raise ValueError('current_row_read_capacity')
            epoch=self.db.execute('SELECT epoch FROM current_row_epoch WHERE singleton=true').fetchone()['epoch']
            if resource_guard is not None:
                size=self.db.execute('''SELECT COALESCE(sum(octet_length(e.facts::text)+octet_length(c.facts::text)+octet_length(o.facts::text)),0) n
                    FROM current_offer o JOIN current_contract c ON c.id=o.contract_id JOIN current_event e ON e.id=c.event_id
                    WHERE (%s::text[] IS NULL OR c.event_id=ANY(%s))''',(event_ids,event_ids)).fetchone()['n']
                resource_guard(int(size)*8)
            # One exact event witness per event, not one JSON serialization and
            # decode for every quoted contract in its neighborhood. Both reads
            # remain in the caller's coherent MVCC frame; returned records still
            # own independent copies so a consumer cannot mutate a sibling.
            events={r['id']:r['facts'] for r in self.db.execute('''SELECT id,facts FROM current_event
                WHERE expires_order>=%s AND (%s::text[] IS NULL OR id=ANY(%s))''',
                (exact_time(utc()),event_ids,event_ids))}
            raw=self.db.execute('''SELECT c.id AS contract_id,c.event_id,c.facts AS contract,o.facts AS quote,
                o.source_at,o.received_at,o.revision FROM current_offer o JOIN current_contract c ON c.id=o.contract_id
                WHERE c.event_id=ANY(%s) AND (%s::text[] IS NULL OR c.id=ANY(%s)) ORDER BY c.id''',(list(events),contract_ids,contract_ids)).fetchall()
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
                event=events[row['event_id']]
                records.append(dict(project_contract(event,row['contract'],row['received_at']),event=deepcopy(event),quote=q))
            statuses={r['venue']:r['state'] for r in self.db.execute('SELECT venue,state FROM current_source_status').fetchall()}
            native={hashed([r['venue'],r['native_event_id'],r['native_market_id']]):r['revision'] for r in self.db.execute('''SELECT b.venue,e.native_event_id,b.native_market_id,b.revision FROM current_native_book b
                JOIN current_event e ON e.id=b.event_id WHERE (%s::text[] IS NULL OR b.event_id=ANY(%s))''',(event_ids,event_ids)).fetchall()}
            dependencies={r['contract_id']:r['revision'] for r in raw}
            return dict(records=records,epoch=epoch,revision=hashed([epoch,dependencies,native]),source_status=statuses,dependency_revisions=dependencies,native_dependency_revisions=native)

    def hydrate_records(self,records,*,resource_guard=None):
        """Fetch only selected execution ask ladders, never a whole slate's depth."""
        ids=[contract_id(record) for record in records];depth={}
        if resource_guard is not None:
            native=self.db.execute('''SELECT COALESCE(sum(jsonb_array_length(d.levels)),0) n FROM current_contract c JOIN current_native_ladder d
                ON d.venue=c.venue AND d.event_id=c.event_id AND d.native_market_id=c.native_market_id
                AND d.native_outcome_id=c.native_outcome_id WHERE c.id=ANY(%s) AND d.side='asks' ''',(ids,)).fetchone()['n']
            aggregate=self.db.execute("SELECT count(*) n FROM current_depth WHERE contract_id=ANY(%s) AND side='asks'",(ids,)).fetchone()['n']
            resource_guard(16*1024*1024+(native+aggregate)*2048+len(encoded(records))*8)
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
