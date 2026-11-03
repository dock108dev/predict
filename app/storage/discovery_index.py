"""Bounded structural unit plans. Never retain executable prices or profiles.

Every lookup proves the entire captured occurrence, including ineligible peers.
Only execution price/depth/receipt fields are excluded; those are reconstructed
by the ordinary producer for each selected unit. Reference inputs stay exact.
Transferred plans are hints only: every lookup reconstructs the complete proof.
"""
from collections import OrderedDict
from copy import deepcopy
import json
from threading import RLock
from time import monotonic
from .store import encoded, hashed, stamp
from .current_rows import contract_id

MAX_BYTES = 6 * 1024 * 1024
MAX_ENTRIES = 512
TTL_SECONDS = 7200
_CACHE = OrderedDict()
_LOCK = RLock()
_MISSES = OrderedDict()
_TRANSFER_STATE = 'process_lifetime'


def clear():
    with _LOCK:
        _CACHE.clear()
        _OCCURRENCES.clear()
        _MISSES.clear()


def structural_record(record):
    value=deepcopy(record)
    q=value['quote']
    audit=q.get('occurrence_match')
    if audit:
        audit.pop('revision',None)
        for member in audit['members']:member.pop('evidence_sha256',None)
    if q['venue']=='pinnacle':return value
    metadata=value.get('comparison_source_metadata',{})
    # This metadata clock is receipt evidence, not an input to occurrence,
    # group or predicate construction. The selected producer receives it fresh.
    metadata.pop('observed_at',None)
    # These inputs do not determine connected-group membership. They still pass
    # the full normalizer/profile producer and capture validator on every unit.
    for key in ('depth','times','revision','provider_clocks','book_confirmation','observed_book'):
        q.pop(key,None)
    if 'provenance' in q:
        for key in ('sha256','receipt_sha256'):q['provenance'].pop(key,None)
    q['original'].pop('value',None)
    q['original'].pop('native_value',None)
    return value


def temporal_partition(value, at):
    """Bind both sides of EVERY known applicability boundary, even unselected."""
    instant=stamp(at);result=[]
    def walk(item):
        if isinstance(item,dict):
            for key,v in item.items():
                if key in ('expires_at','effective_to','effective_until','effective_from','model_effective_from','scheduled_ts','observed_at') and isinstance(v,str):
                    result.append((key,v,instant>=stamp(v)))
                else:walk(v)
        elif isinstance(item,list):
            for v in item:walk(v)
    walk(value)
    return result


def prepare(context, game, policy, observed):
    """Discover once; warm paths construct no full financial neighborhood."""
    from .comparison_board import discover
    from . import result_dependencies as dependencies
    from .latest_board import next_boundary
    started=monotonic()
    rows=next(b['records'] for b in context.catalog_bundles() if b['game_key']==game)
    registries=context.normalization_registries()
    rules,selected=registries.detached()
    from app.comparison.modeled_winner import START,END
    structural=[hashed(structural_record(r)) for r in rows]
    temporal=[temporal_partition(structural_record(r),context.at) for r in rows]
    frame=getattr(context,'publication_frame',None)
    if frame is not None:
        from . import result_inventory as inventory
        event_ids=sorted({hashed([r['quote']['source']['provider'],r['quote']['source']['native_event_id']]) for r in rows})
        events=[frame['events'][eid] for eid in event_ids if eid in frame['events']]
        selector=dict(events=event_ids,occurrences=[[e['pair'],e['start']] for e in events],shared=[v for e in events for v in e['shared']])
        universe=inventory.proof(frame,selector,engine=context.engine,policy=policy.revision,owner=context.publication_runtime)
    else:
        # Authored non-SQL callers still prove the complete resolver universe,
        # including peers that were rejected or resolved into a different game.
        universe=[hashed(structural_record(r)) for group in context.prepared['groups'] for r in group]
    dependency_key=hashed(dict(version=2,epoch=context.epoch,game=game,rows=structural,
        universe=universe,
        engine=context.engine,policy=policy.revision,registry=registries.binding,
        authority=context.publication_runtime,control=context.result_control))
    key=hashed([dependency_key,[temporal,temporal_partition([rules,selected],context.at),
            [stamp(context.at)>=stamp(boundary) for boundary in (START,END)]]])
    now=monotonic()
    expired=0;evicted=0
    with _LOCK:
        for old in list(_CACHE):
            if now-_CACHE[old]['created']>=TTL_SECONDS:
                _CACHE.pop(old);expired+=1;_MISSES[old]='ttl_expired'
        saved=_CACHE.get(key)
        miss=_MISSES.get(key,'cold_after_'+_TRANSFER_STATE) if saved is None else (
            'backward_clock' if stamp(context.at)<stamp(saved['captured_at']) else 'temporal_boundary')
        if saved is None and any(v.get('game')==game for v in _CACHE.values()):
            miss='temporal_invalidated' if any(v.get('dependency_key')==dependency_key for v in _CACHE.values()) else 'dependency_invalidated'
        if saved and stamp(context.at)>=stamp(saved['captured_at']) and (not saved['boundary'] or stamp(context.at)<stamp(saved['boundary'])):
            _CACHE.move_to_end(key);plan=deepcopy(saved['plan']);miss=None
        else:plan=None
    lookup_ms=round((monotonic()-started)*1000,3)
    full_ms=partition_ms=0
    if plan is None:
        full_started=monotonic()
        bundle=discover(context.store,benchmark_venue=policy.benchmark_venue,context=context,game=game)[0]
        full_ms=round((monotonic()-full_started)*1000,3)
        partition_started=monotonic()
        partitions=dependencies.partitions(bundle)
        from app.dashboard.comparison_board import entries
        groups={g['id']:set() for _,g,_ in entries(bundle['state_inputs'])}
        for _,group,q in entries(bundle['state_inputs']):groups[group['id']].add(contract_id(dict(quote=q)))
        plan=dict(units=partitions,contracts={u['id']:sorted(set().union(*(groups[g] for g in u['groups']))) for u in partitions})
        partition_ms=round((monotonic()-partition_started)*1000,3)
        saved=dict(plan=plan,game=game,dependency_key=dependency_key,created=now,captured_at=context.at,boundary=next_boundary(bundle,context.at))
        size=len(encoded(saved))
        if size<=MAX_BYTES:
            with _LOCK:
                _CACHE[key]=deepcopy(saved)
                while len(_CACHE)>MAX_ENTRIES or sum(len(encoded(v)) for v in _CACHE.values())>MAX_BYTES:
                    old,_=_CACHE.popitem(last=False);evicted+=1;_MISSES[old]='evicted'
                while len(_MISSES)>MAX_ENTRIES:_MISSES.popitem(last=False)
        else:miss='oversize_not_retained'
        reused=False
    else:
        # Parent scaffolding carries source observations only. Child calculations
        # always hydrate a new complete selected unit through the normal producer.
        bundle=dict(observed,state_inputs=deepcopy(observed['state_inputs']))
        reused=True
    bundle['_discovery_plan']=plan
    # Parent assembly identity must not depend on whether discovery was cold
    # (full financial profiles) or warm (observation scaffolding). Selected
    # children still bind their freshly reconstructed financial applicability.
    from .comparison_board import context_identity
    identity=context_identity(observed,policy,context)
    bundle['_discovery_context']=dict(identity,context_id=hashed([identity,key]))
    bundle['_discovery_reused']=reused
    bundle['_discovery_timings']=dict(discovery_index_ms=lookup_ms,full_discovery_ms=full_ms,partition_discovery_ms=partition_ms)
    with _LOCK:
        bundle['_discovery_timings'].update(discovery_miss_reason=miss,discovery_expired_entries=expired,
            discovery_evicted_entries=evicted,discovery_plan_entries=len(_CACHE),
            discovery_plan_payload_bytes=sum(len(encoded(v)) for v in _CACHE.values()),
            discovery_occurrence_entries=len(_OCCURRENCES),
            discovery_occurrence_payload_bytes=sum(len(v[1]) for v in _OCCURRENCES.values()))
    return bundle


def hydrate(context, bundle, unit, policy):
    """Build selected profiles/depth with the FULL captured context still visible."""
    ids=bundle['_discovery_plan']['contracts'][unit['id']]
    db=context.store.db
    if db is None:
        values=context.bundles(benchmark_venue=policy.benchmark_venue,game=bundle['game_key'],unit_contracts=ids)
    else:
        from . import observation_publication as publication
        from psycopg.pq import TransactionStatus
        expected=getattr(context,'publication_frame',None)
        if expected is None:raise ValueError('result_discovery_capture_required')
        events=sorted({expected['offers'][cid]['event_id'] for cid in ids})
        owns=db.info.transaction_status==TransactionStatus.IDLE
        # Depth must share a snapshot with the proof of its selected prices and
        # book revision. Seal validation alone cannot catch update/revert races
        # if a ladder from an intervening version was mixed into an old capture.
        with db.transaction():
            if owns:db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            elif db.execute('SHOW transaction_isolation').fetchone()['transaction_isolation'] not in ('repeatable read','serializable'):
                raise ValueError('result_discovery_snapshot_required')
            capture_started=monotonic()
            current=publication.capture(db,context.source_status,
                selector=dict(events=events,occurrences=[],shared=[]),compact='lazy',resource_guard=context.resource_guard)
            if current['epoch']!=expected['epoch'] or any(publication.own(current,cid)!=publication.own(expected,cid) for cid in ids):
                raise ValueError('result_discovery_hydration_changed')
            capture_ms=round((monotonic()-capture_started)*1000,3)
            values=context.bundles(benchmark_venue=policy.benchmark_venue,game=bundle['game_key'],unit_contracts=ids)
            for value in values:value['input_stage_timings']['selected_dependency_capture_ms']=capture_ms
    if len(values)!=1:raise ValueError('result_discovery_occurrence_changed')
    selected=values[0]
    from .result_dependencies import slice_bundle
    result=slice_bundle(selected,unit)
    # Detect an incompatible group projection before a manifest or calculation.
    from app.dashboard.comparison_board import entries
    actual={contract_id(dict(quote=q)) for _,_,q in entries(result['state_inputs'])}
    if actual!=set(ids):raise ValueError('result_discovery_membership_changed')
    return result


_OCCURRENCES = OrderedDict()
OCCURRENCE_BYTES = 2 * 1024 * 1024


def resolve(records, *, at, engine, epoch):
    """Reuse structural projection; rebuild the occurrence audit's receipt proof.

    Resolver membership is a function of the complete ordered input and reviewed
    edges. No record's executable quote is cached. A peer's latest evidence hash
    is refreshed in every member's audit and the audit revision is recalculated.
    """
    from app.comparison.occurrence_matching import OccurrenceResolver
    from app.comparison.event_links import digest
    resolver=OccurrenceResolver()
    edges=[dict(id=e.id,active=e.active(stamp(at)),observed=stamp(e.observed_at)<=stamp(at),
        effective=stamp(e.effective_from)<=stamp(at)) for e in resolver.links.edges]
    structural=[hashed(structural_record(r)) for r in records]
    key=hashed([epoch,engine,edges,structural])
    now=monotonic()
    with _LOCK:
        for old in list(_OCCURRENCES):
            if now-_OCCURRENCES[old][0]>=TTL_SECONDS:_OCCURRENCES.pop(old)
        found=_OCCURRENCES.get(key)
        if found:_OCCURRENCES.move_to_end(key)
    if found:
        saved=json.loads(found[1])
        evidence={(r['quote']['source']['provider'],r['quote']['source']['native_event_id']):r['quote']['provenance'].get('sha256') for r in records}
        out=[]
        for record,projection in zip(records,saved['changes']):
            value=deepcopy(record)
            value.update(projection['set'])
            for field in projection['remove']:value.pop(field,None)
            q=deepcopy(record['quote']);q.pop('occurrence_link',None)
            q['occurrence_match']=deepcopy(saved['audits'][projection['audit']])
            q['occurrence_match'].update(original_event=deepcopy(record['event']),
                original_market_identity=deepcopy(record['market_identity']),original_selection=deepcopy(record['selection']))
            for member in q['occurrence_match']['members']:
                member['evidence_sha256']=evidence[(member['provider'],member['native_event_id'])]
            q['occurrence_match']['revision']=digest({k:v for k,v in q['occurrence_match'].items() if k!='revision'})
            link=projection['link']
            if link is not None:q['occurrence_link']=link
            out.append(dict(value,quote=q))
        return out,True
    out=resolver.resolve(records,clock=at)
    # Cache only resolver edits, with one audit per source event. Native terms,
    # original events and receipts stay in the caller's capture. Duplicating
    # every record's full audit can exhaust the bound before a large event is
    # reusable, even when the actual structural projection is small.
    projections=[];audits={};size=32
    for original,r in zip(records,out):
        source=r['quote']['source'];audit_key=hashed([source['provider'],source['native_event_id']])
        if audit_key not in audits:
            audit={k:v for k,v in r['quote']['occurrence_match'].items()
                if k not in ('original_event','original_market_identity','original_selection','revision')}
            raw_audit=encoded(audit);size+=len(raw_audit)+len(audit_key)+4
            if size>OCCURRENCE_BYTES:return out,False
            audits[audit_key]=audit
        projection=encoded(dict(set={k:v for k,v in r.items() if k!='quote' and (k not in original or original[k]!=v)},
            remove=[k for k in original if k!='quote' and k not in r],audit=audit_key,link=r['quote'].get('occurrence_link')))
        size+=len(projection)+1
        if size>OCCURRENCE_BYTES:return out,False
        projections.append(projection)
    raw=b'{"audits":'+encoded(audits)+b',"changes":['+b','.join(projections)+b']}'
    if len(raw)<=OCCURRENCE_BYTES:
        with _LOCK:
            _OCCURRENCES[key]=(now,raw)
            while len(_OCCURRENCES)>MAX_ENTRIES or sum(len(v[1]) for v in _OCCURRENCES.values())>OCCURRENCE_BYTES:
                _OCCURRENCES.popitem(last=False)
    return out,False


TRANSFER_BYTES = 9 * 1024 * 1024


def load_transfer(path):
    """Read a bounded atomic artifact under the financial owner's SQL lock.

    No pickle or executable inputs. Imported entries still undergo the exact
    lookup proof and temporal checks. Missing/partial/old artifacts rebuild.
    """
    import time
    global _TRANSFER_STATE
    _TRANSFER_STATE='transfer_missing_or_invalid'
    clear()
    try:
        with path.open('rb') as stream:raw=stream.read(TRANSFER_BYTES+1)
        if len(raw)>TRANSFER_BYTES:return 'transfer_capacity'
        value=json.loads(raw)
        age=time.time()-value['saved_at']
        if value['version']!=2 or not 0<=age<TTL_SECONDS:return 'transfer_expired'
        plans=value['plans'];occurrences=value['occurrences']
        if len(plans)>MAX_ENTRIES or len(occurrences)>MAX_ENTRIES:return 'transfer_capacity'
        if sum(len(encoded(v)) for _,v in plans)>MAX_BYTES:return 'transfer_capacity'
        if sum(len(v[1].encode()) for _,v in occurrences)>OCCURRENCE_BYTES:return 'transfer_capacity'
        now=monotonic()
        with _LOCK:
            for key,v in plans:
                v['created']=now-v.pop('age')-age
                if now-v['created']<TTL_SECONDS:_CACHE[key]=v
            for key,(entry_age,raw) in occurrences:
                if entry_age+age<TTL_SECONDS:_OCCURRENCES[key]=(now-entry_age-age,raw.encode())
        _TRANSFER_STATE='validated_transfer'
        return 'transferred'
    except (OSError,ValueError,KeyError,TypeError):
        clear()
        return 'transfer_missing_or_invalid'


def save_transfer(path):
    """One replaceable file plus one temporary file; bounded even after a crash."""
    import os
    import time
    now=monotonic()
    with _LOCK:
        plans=[[k,dict(v,age=now-v['created'])] for k,v in _CACHE.items() if now-v['created']<TTL_SECONDS]
        for _,v in plans:v.pop('created',None)
        occurrences=[[k,[now-v[0],v[1].decode()]] for k,v in _OCCURRENCES.items() if now-v[0]<TTL_SECONDS]
        raw=encoded(dict(version=2,saved_at=time.time(),plans=plans,occurrences=occurrences))
    if len(raw)>TRANSFER_BYTES:return False
    temporary=path.with_suffix('.tmp')
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        with temporary.open('wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        temporary.replace(path)
        return True
    except OSError:
        return False
    finally:
        temporary.unlink(missing_ok=True)
