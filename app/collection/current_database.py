"""Direct current-row SQL ingress and bounded ordinary lifecycle status."""
import asyncio
from copy import deepcopy
from pathlib import Path
from app.storage.current_games import utc
from app.storage.store import connect,Store
from .current_storage_policy import SQL_BYTE_CAP,sql_usage,require_disk_space



class DatabaseIngressSink:
    """Direct synchronous SQL publication; no durable feed or retry queue."""
    acknowledgment='saved-current-row-transaction'
    def __init__(self,store,config):
        from app.dashboard.session_projection import SessionProjection
        self.reducer=SessionProjection();self.store=store;self.config=config
        self.sequence=0;self.metrics=dict(admitted_observations=0,rejected_observations=0)
        self.exclusions=[];self.error=None

    def commit(self,row,states):
        from app.storage.current_rows import CurrentRowStore
        from app.dashboard.current_contract import snapshot_inputs,packed
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
                if row['type']=='coverage_inventory':
                    def material(m):
                        b=m.get('v1_raw_binding',{})
                        return [m.get('sides'),m.get('terms'),m.get('native_scope_binding'),
                            b.get('identity'),b.get('source_predicate'),b.get('settlement')]
                    old_markets={(s,m['event_id'],m['id']):m for s,c in self.reducer.inventory.items() for m in c['markets']}
                    for s,c in row['inventory'].items():
                        for m in c['markets']:
                            key=(s,m['event_id'],m['id'])
                            if key in old_markets and material(m)!=material(old_markets[key]):withdraw.add(key)
                for observation in observations:
                    if observation['type']=='prediction_book':
                        book=observation['book'];ref=book['raw']['ref']
                        market=next((m for m in candidate.inventory.get(row['source'],{}).get('markets',[]) if m['id']==ref['market_id'] and m['event_id']==ref['event_id']),None)
                        if market is None or ref['venue']!=row['source'] or book['sync']!='synchronized' or book['state']=='unknown' or book['quantity_unit']!='contracts':raise ValueError('Unadmitted current book identity or units')
                        if {o['outcome_id'] for o in book['outcomes']}!={side['id'] for side in market['sides']}:raise ValueError('Incomplete current outcome set')
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
                with db.transaction():
                    changed=rows.upsert_records(records,scopes=scopes,authoritative=bool(scopes),source_status=states,now=now)
                    if row['type'] in ('prediction_book','prediction_books'):rows.replace_native_books([o['book'] for o in observations])
                    if row['type']=='coverage_inventory':
                        # A catalog identity change invalidates an already-held book;
                        # absence on a partial discovery page alone is not removal.
                        memberships=candidate.memberships();prior_memberships=self.reducer.memberships()
                        for key,prior in prior_memberships.items():
                            if key[0]!=row['source'] or key not in memberships or memberships[key]==prior:continue
                            withdraw.add(key)
                    for key in withdraw:rows.withdraw_native_market(*key)
            self.reducer=candidate;self.error=None
            raw=snapshot_inputs(self.store._state);raw.update(source_status=deepcopy(states),clock_at=now,projected_at=now,state_revision=raw['state_revision']+1)
            if getattr(self.store,'_source_stopping',False):self.store.admit_shutdown_health(states)
            else:self.store.commit(raw)
            self.sequence+=1;self.metrics['admitted_observations']+=1
            return dict(service_sequence=self.sequence,current_rows_changed=changed,acknowledgment=self.acknowledgment)
        except Exception as exc:
            self.error=type(exc).__name__+': '+str(exc)[:160];self.metrics['rejected_observations']+=1
            raise


class DatabasePipeline:
    """Current-row startup, expiry and Stop; finance belongs to request reads."""
    def __init__(self,service):
        self.service=service;self.closed=False;self.task=None
        self.error=None;self.wake=asyncio.Event()
    async def start(self):
        from app.storage.current_rows import CurrentRowStore
        from .current_policy import aggregate_scope
        from uuid import uuid4
        try:
            with connect() as db:
                Store(db).migrate();rows=CurrentRowStore(db)
                with db.transaction():
                    # A reopened process cannot revive an earlier Details context.
                    # This generation has no authority over source price clocks.
                    db.execute('UPDATE current_row_epoch SET epoch=%s WHERE singleton=true',(str(uuid4()),))
                    for venue in ('kalshi','polymarket_us','novig','prophetx','pinnacle'):
                        rows.expire_out_of_scope(venue,self.service.config['sports'] if venue in ('kalshi','polymarket_us') else aggregate_scope(self.service.config),self.service.config['families'])
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
            with connect() as db:CurrentRowStore(db).expire()
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
        try:
            with connect() as db:used=sql_usage(db)
        except Exception as exc:used=None;error=type(exc).__name__
        return dict(database='prediction_arb',socket='.local/pgsocket',schema='012_current_rows.sql',
            state='unavailable' if error else 'available',error=error,backlog_bytes=0,imported_records=0,
            pending_calculations=0,busy=False,sql_byte_cap=SQL_BYTE_CAP,sql_bytes=used,
            observation_representation='current event/contract/offer/shared depth upserts; transient calculations',
            journal_byte_cap=0,journal_segment_byte_cap=0,finite_failure_limit=0)
