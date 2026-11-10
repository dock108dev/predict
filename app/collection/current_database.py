"""Direct current-row SQL ingress and bounded ordinary lifecycle status."""
import asyncio
from copy import deepcopy
from pathlib import Path
from time import monotonic
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



def normalize_storage_batch(catalog, images, at, prepare_records, *, detached=False):
    from app.comparison.combined_native import normalize
    records,errors=normalize(catalog,images,at=at,include_missing=True,owned=True)
    if prepare_records:
        from app.storage.current_rows import prepare
        batch_events={} if detached else None
        records=[prepare(record,batch_events=batch_events) for record in records]
    return records,errors


def normalize_current(catalog, books, *, at, revoked=None, executor=None, current_images=None, prepare_records=False):
    """Normalize the complete roster in bounded, independent instrument chunks."""
    inventory=catalog['record']['value']['inventory']
    indexed={}
    for envelope in books:
        for obs in envelope['record']['value']['observations']:
            ref=obs['book']['raw']['ref']
            indexed.setdefault((ref['event_id'],ref['market_id']),[]).append(envelope)
    records=[];errors=[]
    for start in range(0,len(inventory['markets']),256):
        if revoked is not None and revoked.is_set():raise asyncio.CancelledError()
        markets=inventory['markets'][start:start+256]
        events={m['event_id'] for m in markets}
        selected=dict(inventory,markets=markets,events=[e for e in inventory['events'] if e['id'] in events])
        part=dict(catalog,record=dict(catalog['record'],value=dict(catalog['record']['value'],inventory=selected)))
        images=[b for m in markets for b in indexed.get((m['event_id'],m['id']),[])]
        if current_images is not None:
            source=catalog['record']['source']
            for market in markets:
                key=(source,market['event_id'],market['id'])
                if key not in current_images:continue
                observation=current_images[key]
                images.append(dict(id='transient-current-book',record=dict(
                    retained_at=observation['book']['raw']['received_at'],value=dict(observations=[observation]))))
        if executor is None:rows,excluded=normalize_storage_batch(part,images,at,prepare_records)
        else:
            # Only detached public metadata/images cross this CPU boundary. The
            # serialized parent retains SQL, cancellation and publication authority.
            rows,excluded=executor.submit(normalize_storage_batch,part,images,at,prepare_records,detached=True).result()
            if revoked is not None and revoked.is_set():raise asyncio.CancelledError()
        records.extend(rows);errors.extend(excluded[:max(0,200-len(errors))])
    return records,errors


def utc_between(start,now,end):
    from app.storage.store import exact_time
    return exact_time(start)<=exact_time(now) and (end is None or exact_time(now)<exact_time(end))


class DatabaseIngressSink:
    """Direct synchronous SQL publication; no durable feed or retry queue."""
    acknowledgment='saved-current-row-transaction'
    def __init__(self,store,config,*,process_normalization=False):
        from app.dashboard.session_projection import SessionProjection
        from .current_book_images import CurrentBookImages
        self.reducer=SessionProjection();self.reducer.bulk_current=True;self.store=store;self.config=config
        self.reducer.books=CurrentBookImages()
        self.sequence=0;self.metrics=dict(admitted_observations=0,rejected_observations=0)
        self.exclusions=[];self.error=None;self.error_details=None
        self.normalizer=None
        from threading import Lock
        self.normalizer_lock=Lock()
        self.process_normalization=process_normalization
        self._catalog_index_owner=None
        self._catalog_indexes=None

    def catalog_indexes(self,inventory):
        """Share immutable lookup structure for exactly one adopted catalog.

        Price commits replace book entries, not inventory. Catalog adoption
        replaces inventory, invalidating all event and market lookup references.
        Concurrent preparation keeps its own returned pair, even on replacement.
        """
        with self.normalizer_lock:
            if self._catalog_index_owner is not inventory:
                indexes=({(s,m['event_id'],m['id']):m for s,c in inventory.items() for m in c['markets']},
                         {(s,e['id']):e for s,c in inventory.items() for e in c['events']})
                self._catalog_indexes=indexes
                self._catalog_index_owner=inventory
            return self._catalog_indexes

    def normalization_executor(self):
        with self.normalizer_lock:
            if self.normalizer is None:
                from concurrent.futures import ProcessPoolExecutor
                from multiprocessing import get_context
                self.normalizer=ProcessPoolExecutor(max_workers=2,mp_context=get_context('spawn'))
            return self.normalizer

    def precompute_books(self,source,books,revoked):
        """CPU-only preparation from immutable generation-bound catalog inputs."""
        base=self.reducer
        inventory=base.inventory.get(source)
        if inventory is None:return None  # Ordinary admission supplies the error.
        selected={(b['raw']['ref']['event_id'],b['raw']['ref']['market_id']) for b in books}
        market_index,event_index=self.catalog_indexes(base.inventory)
        markets=[market_index[(source,eid,mid)] for eid,mid in sorted(selected) if (source,eid,mid) in market_index]
        events={m['event_id'] for m in markets}
        part=dict(inventory,markets=markets,events=[event_index[(source,eid)] for eid in sorted(events) if (source,eid) in event_index])
        catalog=dict(id='transient-current-catalog',record=dict(source=source,value=dict(inventory=part)))
        images=[dict(id='transient-current-book',record=dict(retained_at=b['raw']['received_at'],
            value=dict(observations=[dict(type='prediction_book',source=source,book=b,
                observed_at=b['raw']['received_at'],packets=[])]))) for b in books]
        at=utc()
        from app.storage.store import exact_time
        records,errors=normalize_current(catalog,images,at=at,revoked=revoked,
            executor=self.normalization_executor(),prepare_records=True)
        future=[r['event']['scheduled_start'] for r in records
                if exact_time(r['event']['scheduled_start'])>exact_time(at)]
        return dict(generation=base.generation,source=source,records=records,errors=errors,
            prepared_at=at,next_phase_at=min(future,key=exact_time) if future else None)

    def close(self):
        if self.normalizer is not None:
            self.normalizer.shutdown(wait=True,cancel_futures=True)
            self.normalizer=None

    def commit(self,row,states):
        return self.finish(self.prepare(row,states), states)

    async def commit_async(self,row,states,revoked,*,precomputed=None):
        from .background_work import ingress_thread
        from psycopg.errors import LockNotAvailable, DeadlockDetected, SerializationFailure, QueryCanceled
        retries = 0
        while True:
            if revoked.is_set():raise asyncio.CancelledError()
            try:
                prepared = await ingress_thread(self.prepare, row, states, revoked, **(dict(precomputed=precomputed) if precomputed is not None else {}))
                break
            except (LockNotAvailable, DeadlockDetected, SerializationFailure, QueryCanceled) as exc:
                if isinstance(exc, QueryCanceled):
                    # A native depth statement can time out after the offers were
                    # staged. Retry the rolled-back image once, under the same guard.
                    if retries or row.get('type') not in ('prediction_book', 'prediction_books') or revoked.is_set():
                        raise
                # PostgreSQL rolled back the entire transaction. Retain this exact
                # already-received image; never redispatch a paid request.
                from app.diagnostics import failure
                failure(__name__, 'current_ingress_transaction_retry', exc)
                retries += 1
                self.metrics['rejected_observations']-=1  # rolled back and pending, not rejected
                self.metrics.update(transaction_retries=self.metrics.get('transaction_retries',0)+1,
                    admission_state='retrying',retry_reason=type(exc).__name__)
                await asyncio.sleep(min(retries * .1, 2))
        self.metrics.update(admission_state='receiving',retry_reason=None)
        if revoked.is_set():raise asyncio.CancelledError()
        return self.finish(prepared, states)

    def finish(self,prepared,states):
        from app.dashboard.current_contract import snapshot_inputs
        candidate,now,changed=prepared
        self.reducer=candidate
        raw=snapshot_inputs(self.store._state);raw.update(source_status=deepcopy(states),clock_at=now,projected_at=now,state_revision=raw['state_revision']+1)
        if getattr(self.store,'_source_stopping',False):self.store.admit_shutdown_health(states)
        else:self.store.commit(raw)
        admitted=candidate.__dict__.pop('_material_admission',None)
        if admitted:
            source=admitted.pop('source')
            totals=self.metrics.setdefault('native_material_admissions',{}).setdefault(source,{})
            for name,n in dict(admitted,batches=1).items():totals[name]=totals.get(name,0)+n
        self.error=None;self.error_details=None
        self.sequence+=1;self.metrics['admitted_observations']+=1
        return dict(service_sequence=self.sequence,current_rows_changed=changed,acknowledgment=self.acknowledgment)

    def prepare(self,row,states,revoked=None,*,precomputed=None):
        return self._prepare(row,states,revoked,precomputed=precomputed)

    def _prepare(self,row,states,revoked=None,*,precomputed=None):
        from app.storage.current_rows import CurrentRowStore
        from app.dashboard.current_contract import packed
        from copy import deepcopy
        now=utc()
        from time import monotonic
        started=monotonic();last=started;active='validation_and_reduction';timings={}
        def phase(name):
            nonlocal last,active
            tick=monotonic();timings[active]=timings.get(active,0)+tick-last
            last=tick;active=name
            self.metrics['preparation']=dict(source=row.get('source'),type=row['type'],
                phase=name,phase_started=tick,seconds=tick-started,timings=dict(timings))
        phase(active)
        try:
            if row['type'] not in ('current_aggregate_records','coverage_inventory','prediction_book','prediction_books','source_health','native_market_invalid','novig_native_records'):
                raise ValueError('current_ingress_type_unsupported: use admitted current records or native observations')
            if 'body' in row or 'batches' in row:
                raise ValueError('current_ingress_raw_payload_unsupported: use admitted current records')
            if row['type']!='coverage_inventory' and len(packed(row))>self.config['ingress_bytes']:raise ValueError('Current ingress observation capacity')
            if row['type']=='novig_native_records':
                candidate=self.reducer
            elif row['type'] in ('prediction_book','prediction_books','source_health','current_aggregate_records','coverage_inventory','native_market_invalid'):
                # Immutable catalog/unchanged images are shared until adoption.
                # These reducers replace map entries rather than mutating them.
                from copy import copy
                candidate=copy(self.reducer)
                candidate.books=self.reducer.books.copy()
                for name in ('metadata','health','sizes','book_evidence'):
                    setattr(candidate,name,dict(getattr(self.reducer,name)))
                candidate.invalid=set(self.reducer.invalid)
            else:
                candidate=deepcopy(self.reducer)
            records=[];scopes=[];withdraw=set();storage_prepared=False
            deferred_keys=set();catalog_turnover={}
            if row['type']=='novig_native_records':
                from .novig_v3_current import MAX_MARKETS, identity
                records=row['records']
                if row['source']!='novig' or len(records)>2*MAX_MARKETS or len(row['withdrawn'])>MAX_MARKETS:
                    raise ValueError('novig_current_ingress_bound')
                for record in records:
                    q=record['quote']; source=q['source']
                    if (q['venue']!='novig' or source['provider']!='novig'
                            or q['novig_runtime_id']!=row['session_id'] or not q['novig_v3_evidence']):
                        raise ValueError('novig_current_ingress_identity')
                withdraw={('novig',identity(eid),identity(mid)) for eid,mid in row['withdrawn']}
            elif row['type']=='native_market_invalid':
                markets=row.get('markets') or [(row['event_id'],row['market_id'])]
                if len(markets)>128:raise ValueError('native_invalidation_batch_capacity')
                for event_id,market_id in markets:
                    key=(row['source'],event_id,market_id)
                    candidate.books.pop(key,None);candidate.metadata.pop(key,None);candidate.invalid.add(key)
                    withdraw.add(key)
            elif row['type']=='current_aggregate_records':
                records=row['records']
                scopes=[dict(venue=v,competition=row['sport'],received_at=row['received_at'],aggregate_route='featured') for v in row['complete_venues']]
            else:
                observations=row['observations'] if row['type']=='prediction_books' else [row]
                retained_books=set()
                catalog_refresh=None
                if row['type']=='coverage_inventory':
                    from .current_catalog_delta import changes
                    delta=row.get('catalog_delta')
                    if delta is None:delta=changes(self.reducer.inventory,row['inventory'])
                    retained_books=delta['retained'] & set(candidate.books)
                    withdraw.update(delta['withdraw'])
                    catalog_refresh=delta['refresh'] & retained_books
                    self.metrics['catalog_delta']=dict(retained=len(retained_books),withdrawn=len(withdraw),recalculated=len(catalog_refresh))
                    if row.get('defer_catalog_refresh'):
                        # Revoke old derived rows atomically with new metadata,
                        # then let the ordinary fair book queue recalculate them.
                        # Original packed images remain owned by the reducer.
                        deferred_keys=catalog_refresh
                        withdraw.update(catalog_refresh)
                        self.metrics['catalog_delta'].update(recalculated=0,deferred=len(catalog_refresh))
                        catalog_refresh=set()
                market_lookup,_=self.catalog_indexes(candidate.inventory)
                for index,observation in enumerate(observations):
                    if observation['type']=='prediction_book':
                        book=observation['book'];ref=book['raw']['ref']
                        market=market_lookup.get((row['source'],ref['event_id'],ref['market_id']))
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
                    if observation['type']=='prediction_book' and book['state']=='active':
                        # Current ingress already checked the complete synchronized
                        # image; SQL below still checks this owner's Stop/revocation.
                        # A legacy session-health row is not required to resume it.
                        candidate.invalid.discard((row['source'],ref['event_id'],ref['market_id']))
                # Legacy session membership also binds derived season/stage and
                # canonical matching. A counterpart catalog changing those facts
                # cannot invalidate an unchanged physical source image. Reuse its
                # exact original clocks under the newly checked metadata; never
                # carry an image across changed native terms/sides/schedule.
                candidate.books.retain_from(self.reducer.books,retained_books)
                for key in withdraw-retained_books:candidate.books.pop(key,None);candidate.metadata.pop(key,None);candidate.invalid.discard(key)
                if row['type']!='source_health':
                    for source,inventory in candidate.inventory.items():
                        if catalog_refresh is not None:
                            selected={(key[1],key[2]) for key in catalog_refresh if key[0]==source}
                            if not selected:continue
                        else:
                            if source!=row['source']:continue
                            selected={tuple(o['book']['raw']['ref'][k] for k in ('event_id','market_id')) for o in observations if o['type']=='prediction_book'}
                        market_index,event_index=self.catalog_indexes(candidate.inventory)
                        if selected:
                            events={eid for eid,_ in selected}
                            relevant=dict(inventory,
                                events=[event_index[(source,eid)] for eid in sorted(events) if (source,eid) in event_index],
                                markets=[market_index[(source,eid,mid)] for eid,mid in sorted(selected) if (source,eid,mid) in market_index])
                        else:relevant=inventory
                        catalog=dict(id='transient-current-catalog',record=dict(source=source,value=dict(inventory=relevant)))
                        books=[]
                        # reduce_observation already transferred these exact books
                        # into the candidate. The last image per key is the same
                        # one a retained-map decode would return.
                        incoming={(source,o['book']['raw']['ref']['event_id'],o['book']['raw']['ref']['market_id']):o for o in observations if o['type']=='prediction_book'}
                        book_keys=((source,eid,mid) for eid,mid in selected) if selected else candidate.books
                        for key in book_keys:
                            if key not in candidate.books or key[0]!=source:continue
                            observation=incoming.get(key) or candidate.books[key]
                            event=event_index.get(key[:2])
                            if event:
                                scopes.append(dict(venue=source,competition=event['competition'],native_event_id=key[1],native_market_id=key[2],
                                    received_at=observation['book']['raw']['received_at'],source_at=observation['book']['raw'].get('exchange_at')))
                        phase('normalization')
                        if (precomputed is not None and row['type']=='prediction_books'
                                and precomputed['source']==source and precomputed['generation']==self.reducer.generation
                                and utc_between(precomputed['prepared_at'],now,precomputed['next_phase_at'])):
                            native,errors=precomputed['records'],precomputed['errors'];storage_prepared=True
                            self.metrics['precomputed_admissions']=self.metrics.get('precomputed_admissions',0)+1
                        else:
                            if precomputed is not None:
                                self.metrics['precomputed_generation_retries']=self.metrics.get('precomputed_generation_retries',0)+1
                            executor=self.normalization_executor() if self.process_normalization else None
                            storage_prepared=executor is not None
                            native,errors=normalize_current(catalog,books,at=now,revoked=revoked,executor=executor,
                                current_images=candidate.books,prepare_records=storage_prepared)
                        records.extend(native);self.exclusions=errors[:200]
            phase('sql_admission')
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
                            (str(owner['runtime_id'])!=self.store.provider.runtime_id or owner['global_stopped']
                             or row['source'] in owner['paused_sources'] or row['type']=='novig_native_records'
                             and 'the_odds_api' in owner['paused_sources'])):
                            raise asyncio.CancelledError()
                    if row['type']=='current_aggregate_records' and 'raw_payload' in row:
                        from psycopg.types.json import Jsonb
                        from app.comparison.offered_scope import aggregate_inventory
                        raw_batch=dict(events=row['raw_payload'],dispositions=[dict(venue=v,family=f,**aggregate_inventory(row['raw_payload'],v,f,records))
                            for v in ('novig','prophetx','pinnacle') for f in ('moneyline','spread','total')])
                        db.execute('INSERT INTO current_acquisition_aggregate VALUES (%s,%s,%s) '
                            'ON CONFLICT (sport) DO UPDATE SET received_at=EXCLUDED.received_at,payload=EXCLUDED.payload '
                            'WHERE current_acquisition_aggregate.received_at<=EXCLUDED.received_at',
                            (row['sport'],row['received_at'],Jsonb(raw_batch)))
                    admit=rows._upsert_prepared if storage_prepared else rows.upsert_records
                    from app.storage.native_admission_metrics import MaterialRows
                    material_rows=MaterialRows() if row['type'] in ('prediction_books','prediction_book') else None
                    changed=admit(records,scopes=scopes,authoritative=bool(scopes),source_status=states,now=now,
                                  **({'material_rows':material_rows} if material_rows is not None else {}))
                    phase('native_depth')
                    if row['type'] in ('prediction_book','prediction_books'):rows.replace_native_books([o['book'] for o in observations])
                    if row['type']=='coverage_inventory':
                        # A catalog identity change invalidates an already-held book;
                        # absence on a partial discovery page alone is not removal.
                        memberships=candidate.memberships();prior_memberships=self.reducer.memberships()
                        for key,prior in prior_memberships.items():
                            if key not in memberships or memberships[key]==prior or key in retained_books:continue
                            withdraw.add(key)
                    reimaging=delta.get('reimaging',set()) if row['type']=='coverage_inventory' else set()
                    if row['type']=='coverage_inventory':
                        # Prior inactive bodies get one catalog interval. A
                        # restart, partial readmission or retirement cannot
                        # accumulate historical bodies behind the active view.
                        db.execute('DELETE FROM current_contract_storage WHERE NOT active')
                        for reason,keys in (('derived_refresh',deferred_keys),('reimage',reimaging),
                                            ('retirement_or_native_change',withdraw-reimaging-deferred_keys)):
                            if keys:catalog_turnover[reason]=rows.withdraw_native_markets(keys,reimaging=reason=='reimage',deferred=reason=='derived_refresh',measure=True)
                    else:rows.withdraw_native_markets(withdraw)
                    if revoked is not None and revoked.is_set():raise asyncio.CancelledError()
                    phase('commit_observation')
            if row['type']=='coverage_inventory':
                self.metrics['catalog_storage_turnover']=dict(at=utc(),source=row['source'],generation=row['generation'],reasons=catalog_turnover)
            if material_rows is not None:
                candidate._material_admission=dict(material_rows.counts(utc()),source=row['source'],books=len(observations),normalized=len(records))
            phase('complete')
            self.metrics['recent_preparations']=(self.metrics.get('recent_preparations',[])+[
                dict(self.metrics['preparation'],records=len(records),scopes=len(scopes),withdrawn=len(withdraw))])[-32:]
            return candidate,now,changed
        except Exception as exc:
            from app.diagnostics import failure_details
            self.error=type(exc).__name__;self.error_details=failure_details(exc);self.metrics['rejected_observations']+=1
            raise


class DatabasePipeline:
    """Current-row startup, expiry and Stop for the independent data owner."""
    def __init__(self,service):
        self.service=service;self.closed=False;self.task=None
        self.error=None;self.error_details=None;self.wake=asyncio.Event();self.used=None;self.maintenance=None
        self.maintenance_failures=0;self.maintenance_last_success_at=None
        self.last_compaction_check=0
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
            from app.diagnostics import failure_details
            self.error=type(exc).__name__;self.error_details=failure_details(exc)
            raise
    def tick(self):
        # Deliberately no journal, diagnostic, cursor, snapshot or publication path.
        if not self.closed:
            from app.storage.current_rows import CurrentRowStore
            with connect() as db:
                # Expiry contention must not starve independent committed
                # retention/reclamation. Preserve its error after that work.
                expiry_error=None
                try:CurrentRowStore(db).expire()
                except Exception as exc:expiry_error=exc
                from app.storage.storage_maintenance import maintain
                # Frequent in-place reuse must not multiply expensive whole-
                # database compaction scans or monopolize the publication lock.
                compact=monotonic()-self.last_compaction_check>=60 or bool((self.maintenance or {}).get('continue_compaction'))
                self.maintenance=maintain(db,collecting=True,compact=compact)
                if compact and self.maintenance.get('state')!='busy':
                    self.last_compaction_check=monotonic()
                if expiry_error is not None:raise expiry_error
                self.used=sql_usage(db)
                if self.maintenance.get('state')!='busy':
                    self.error=None;self.error_details=None;self.maintenance_failures=0
                    self.maintenance_last_success_at=utc()
        return 0
    async def run_maintenance(self):
        while not self.closed:
            try:await asyncio.wait_for(self.wake.wait(),timeout=15)
            except TimeoutError:pass
            self.wake.clear()
            if self.closed:break
            try:
                await asyncio.to_thread(self.tick)
            except Exception as exc:
                from app.diagnostics import failure_details
                self.error=type(exc).__name__;self.error_details=failure_details(exc)
                self.maintenance_failures+=1
                # No paid work or immediate retries. The next maintenance turn
                # must be able to prove recovery after a transient lock failure.
    async def close(self):
        self.closed=True;self.wake.set()
        if self.task:
            try:await asyncio.wait_for(asyncio.shield(self.task),timeout=self.service.config['cleanup_seconds'])
            except TimeoutError:return False
        return True
    def status(self):
        error=getattr(self.service.sink,'error',None) or self.error
        ingress=getattr(self.service.sink,'error',None)
        used=self.used
        return dict(database='prediction_arb',socket='.local/pgsocket',schema='012_current_rows.sql',
            state='unavailable' if error else 'available',error='database_unavailable' if error else None,
            failure_owner='ingress' if ingress else 'maintenance' if self.error else None,
            ingress_failure=getattr(self.service.sink,'error_details',None) if ingress else None,
            maintenance_failure=self.error_details,maintenance_failures=self.maintenance_failures,
            maintenance_last_success_at=self.maintenance_last_success_at,
            maintenance=self.maintenance,backlog_bytes=0,imported_records=0,
            pending_calculations=0,busy=False,sql_byte_cap=SQL_BYTE_CAP,sql_bytes=used,
            observation_representation='current event/contract/offer/shared depth upserts; transient calculations',
            journal_byte_cap=0,journal_segment_byte_cap=0,finite_failure_limit=0)
