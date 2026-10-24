"""Direct current-row SQL ingress and bounded ordinary lifecycle status."""
import asyncio
from copy import deepcopy
from pathlib import Path
from app.storage.current_games import utc
from app.storage.store import connect,Store
from .current_storage_policy import SQL_BYTE_CAP,sql_usage,require_disk_space


class NativeAdmissionError(ValueError):
    """Bounded native identity diagnostics, never provider bodies or credentials."""
    def __init__(self, code, diagnostic):
        super().__init__(code)
        self.diagnostic=dict(diagnostic,reason_code=code)


def native_identity(book, source, candidate, index, total):
    import re
    def identifier(value):
        return value if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_:.+/-]{1,256}',value) else None
    ref=book['raw']['ref']
    return dict(source=source,event_id=identifier(ref.get('event_id')),market_id=identifier(ref.get('market_id')),
        book_venue=ref.get('venue') if ref.get('venue') in ('kalshi','polymarket_us') else None,
        catalog_generation=candidate.generation if type(candidate.generation) is int else identifier(candidate.generation),batch_index=index,batch_size=total,
        sync=book.get('sync') if book.get('sync') in ('synchronized','unsynchronized','resyncing','unknown') else 'invalid',
        state=book.get('state') if book.get('state') in ('active','unknown','closed','paused','settled') else 'invalid',
        quantity_unit=book.get('quantity_unit') if book.get('quantity_unit') in ('contracts','usd') else 'invalid',
        outcome_ids=[identifier(o.get('outcome_id')) for o in book['outcomes']][:16],
        source_at=identifier(book['raw'].get('exchange_at')),received_at=identifier(book['raw'].get('received_at')),
        sequence=identifier(book.get('sequence')))



class DatabaseIngressSink:
    """Direct synchronous SQL publication; no durable feed or retry queue."""
    acknowledgment='saved-current-row-transaction'
    def __init__(self,store,config):
        from app.dashboard.session_projection import SessionProjection
        self.reducer=SessionProjection();self.store=store;self.config=config
        self.sequence=0;self.metrics=dict(admitted_observations=0,rejected_observations=0)
        self.exclusions=[];self.error=None

    def commit(self,row,states):
        return self.finish(self.prepare(row,states), states)

    async def commit_async(self,row,states,revoked):
        from .background_work import ingress_thread
        prepared = await ingress_thread(self.prepare, row, states, revoked)
        if revoked.is_set():raise asyncio.CancelledError()
        return self.finish(prepared, states)

    def finish(self,prepared,states):
        from app.dashboard.current_contract import snapshot_inputs
        candidate,now,changed=prepared
        self.reducer=candidate;self.error=None
        raw=snapshot_inputs(self.store._state);raw.update(source_status=deepcopy(states),clock_at=now,projected_at=now,state_revision=raw['state_revision']+1)
        if getattr(self.store,'_source_stopping',False):self.store.admit_shutdown_health(states)
        else:self.store.commit(raw)
        self.sequence+=1;self.metrics['admitted_observations']+=1
        return dict(service_sequence=self.sequence,current_rows_changed=changed,acknowledgment=self.acknowledgment)

    def prepare(self,row,states,revoked=None):
        from app.storage.current_rows import CurrentRowStore
        from app.dashboard.current_contract import packed
        from copy import deepcopy
        now=utc()
        try:
            if row['type'] not in ('current_aggregate_records','coverage_inventory','prediction_book','prediction_books','source_health'):
                raise ValueError('current_ingress_type_unsupported: use admitted current records or native observations')
            if 'body' in row or 'batches' in row:
                raise ValueError('current_ingress_raw_payload_unsupported: use admitted current records')
            if len(packed(row))>self.config['ingress_bytes']:raise ValueError('Current ingress observation capacity')
            candidate=deepcopy(self.reducer);records=[];scopes=[];withdraw=set()
            if row['type']=='current_aggregate_records':
                records=row['records']
                scopes=[dict(venue=v,competition=row['sport'],received_at=row['received_at']) for v in row['complete_venues']]
            else:
                observations=row['observations'] if row['type']=='prediction_books' else [row]
                retained_books={}
                if row['type']=='coverage_inventory':
                    from .current_native_catalog import book_material
                    def materials(inventory):
                        result={}
                        for s,c in inventory.items():
                            events={e['id']:e for e in c['events']}
                            for m in c['markets']:
                                if m['event_id'] in events:
                                    result[(s,m['event_id'],m['id'])]=book_material(s,events[m['event_id']],m)
                        return result
                    old_materials=materials(self.reducer.inventory)
                    new_materials=materials(row['inventory'])
                    for s,c in row['inventory'].items():
                        for m in c['markets']:
                            key=(s,m['event_id'],m['id'])
                            if key in old_materials:
                                if new_materials.get(key)!=old_materials[key]:withdraw.add(key)
                                elif key in candidate.books:retained_books[key]=candidate.books[key]
                for index,observation in enumerate(observations):
                    if observation['type']=='prediction_book':
                        book=observation['book'];ref=book['raw']['ref']
                        market=next((m for m in candidate.inventory.get(row['source'],{}).get('markets',[]) if m['id']==ref['market_id'] and m['event_id']==ref['event_id']),None)
                        def reject(code):raise NativeAdmissionError(code,native_identity(book,row['source'],candidate,index,len(observations)))
                        if market is None:reject('native_market_not_in_catalog')
                        if ref['venue']!=row['source']:reject('native_book_source_mismatch')
                        if book['sync']!='synchronized':reject('native_book_not_synchronized')
                        if book['state']=='unknown':reject('native_book_state_unknown')
                        if book['quantity_unit']!='contracts':reject('native_book_quantity_unit_invalid')
                        if {o['outcome_id'] for o in book['outcomes']}!={side['id'] for side in market['sides']}:reject('native_book_outcomes_incomplete')
                        if book.get('book_confirmation'):
                            from .current_confirmation import validate
                            validate(book['book_confirmation'],ref,book)
                        from app.dashboard.current_contract import bounded_decimal,stamp
                        stamp(book['raw']['received_at']);stamp(book['raw'].get('exchange_at'),True)
                        for outcome in book['outcomes']:
                            for side in ('asks','bids'):
                                ladder=outcome[side]
                                if ladder is None:continue
                                if len(ladder['levels'])>4096:raise ValueError('Current book level bound')
                                for level in ladder['levels']:
                                    if not 0<=bounded_decimal(level['price']['value'])<=1 or bounded_decimal(level['quantity']['value'])<=0 or level['quantity']['unit']!='contracts':raise ValueError('Invalid current native level')
                    candidate.reduce_observation(observation)
                # Legacy session membership also binds derived season/stage and
                # canonical matching. A counterpart catalog changing those facts
                # cannot invalidate an unchanged physical source image. Reuse its
                # exact original clocks under the newly checked metadata; never
                # carry an image across changed native terms/sides/schedule.
                candidate.books.update(retained_books)
                for key in withdraw:candidate.books.pop(key,None);candidate.metadata.pop(key,None);candidate.invalid.discard(key)
                if row['type']!='source_health':
                    from app.comparison.combined_native import normalize
                    for source,inventory in candidate.inventory.items():
                        if source!=row['source']:continue
                        selected={tuple(o['book']['raw']['ref'][k] for k in ('event_id','market_id')) for o in observations if o['type']=='prediction_book'}
                        catalog=dict(id='transient-current-catalog',record=dict(source=source,value=dict(inventory=inventory)))
                        books=[]
                        for key,observation in candidate.books.items():
                            if key[0]!=source or selected and (key[1],key[2]) not in selected:continue
                            books.append(dict(id='transient-current-book',record=dict(retained_at=observation['book']['raw']['received_at'],value=dict(observations=[observation]))))
                            event=next((e for e in inventory['events'] if e['id']==key[1]),None)
                            if event:
                                scopes.append(dict(venue=source,competition=event['competition'],native_event_id=key[1],native_market_id=key[2],
                                    received_at=observation['book']['raw']['received_at'],source_at=observation['book']['raw'].get('exchange_at')))
                        native,errors=normalize(catalog,books,at=now,include_missing=True);records.extend(native);self.exclusions=errors[:200]
            with connect() as db:
                require_disk_space(Path(__file__).resolve().parents[2]/'.local/postgres')
                if sql_usage(db)>=SQL_BYTE_CAP:raise ValueError('current_database_storage_cap')
                rows=CurrentRowStore(db)
                from app.storage.scanner_publication import transaction as published_transaction
                with published_transaction(db):
                    # Linearize ingress with persisted Stop/pause, independently
                    # of heartbeat writes. A waiting old command cannot revive it.
                    if revoked is not None:
                        from .runtime_status import AUTHORITY_LOCK
                        db.execute('SELECT pg_advisory_xact_lock_shared(%s)', (AUTHORITY_LOCK,))
                        owner=db.execute('SELECT runtime_id,global_stopped,paused_sources FROM data_runtime WHERE singleton').fetchone()
                        if row['type']!='source_health' and (revoked.is_set() or owner and
                            (str(owner['runtime_id'])!=self.store.provider.runtime_id or owner['global_stopped'] or row['source'] in owner['paused_sources'])):
                            raise asyncio.CancelledError()
                    changed=rows.upsert_records(records,scopes=scopes,authoritative=bool(scopes),source_status=states,now=now)
                    if row['type'] in ('prediction_book','prediction_books'):rows.replace_native_books([o['book'] for o in observations])
                    if row['type']=='coverage_inventory':
                        # A catalog identity change invalidates an already-held book;
                        # absence on a partial discovery page alone is not removal.
                        memberships=candidate.memberships();prior_memberships=self.reducer.memberships()
                        for key,prior in prior_memberships.items():
                            if key not in memberships or memberships[key]==prior or key in retained_books:continue
                            withdraw.add(key)
                    for key in withdraw:rows.withdraw_native_market(*key)
                    if revoked is not None and revoked.is_set():raise asyncio.CancelledError()
            return candidate,now,changed
        except Exception as exc:
            self.error=type(exc).__name__+': '+str(exc)[:160];self.metrics['rejected_observations']+=1
            raise


class DatabasePipeline:
    """Current-row startup, expiry and Stop for the independent data owner."""
    def __init__(self,service):
        self.service=service;self.closed=False;self.task=None
        self.error=None;self.wake=asyncio.Event();self.used=None
    async def start(self):
        from app.storage.current_rows import CurrentRowStore
        from .current_policy import aggregate_scope, native_scope, native_markets
        try:
            with connect() as db:
                Store(db).migrate();rows=CurrentRowStore(db)
                with db.transaction():
                    # Process restart reconciles committed current facts. Exact
                    # runtime/result bindings invalidate old selection authority;
                    # neither an app nor data restart resets the data epoch.
                    for venue in ('kalshi','polymarket_us','novig','prophetx','pinnacle'):
                        native=venue in ('kalshi','polymarket_us')
                        rows.expire_out_of_scope(venue,native_scope(self.service.config) if native else aggregate_scope(self.service.config),
                            native_markets(self.service.config) if native else self.service.config['families'])
                    rows.expire()
            self.error=None
            self.task=asyncio.create_task(self.run_maintenance(),name='predict-current-expiry')
        except Exception as exc:
            self.error=type(exc).__name__+': '+str(exc)[:160]
            raise
    def tick(self):
        # Deliberately no journal, diagnostic, cursor, snapshot or publication path.
        if not self.closed:
            from app.storage.current_rows import CurrentRowStore
            with connect() as db:
                CurrentRowStore(db).expire();self.used=sql_usage(db)
        return 0
    async def run_maintenance(self):
        failures=0
        while not self.closed:
            try:await asyncio.wait_for(self.wake.wait(),timeout=60)
            except TimeoutError:pass
            self.wake.clear()
            if self.closed:break
            try:
                await asyncio.to_thread(self.tick);failures=0;self.error=None
            except Exception as exc:
                self.error=type(exc).__name__+': '+str(exc)[:160];failures+=1
                if failures>=3:return
    async def close(self):
        self.closed=True;self.wake.set()
        if self.task:
            try:await asyncio.wait_for(asyncio.shield(self.task),timeout=self.service.config['cleanup_seconds'])
            except TimeoutError:return False
        return True
    def status(self):
        error=getattr(self.service.sink,'error',None) or self.error
        used=self.used
        return dict(database='prediction_arb',socket='.local/pgsocket',schema='012_current_rows.sql',
            state='unavailable' if error else 'available',error=error,backlog_bytes=0,imported_records=0,
            pending_calculations=0,busy=False,sql_byte_cap=SQL_BYTE_CAP,sql_bytes=used,
            observation_representation='current event/contract/offer/shared depth upserts; transient calculations',
            journal_byte_cap=0,journal_segment_byte_cap=0,finite_failure_limit=0)
