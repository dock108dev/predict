"""Independent compare-and-seal for complete result dependency units."""
from time import monotonic
from psycopg.types.json import Jsonb

from .store import encoded, hashed, stamp, ROOT
from . import result_dependencies as dependencies
from . import observation_publication as publication
from .current_games import engine_binding, observation_binding, utc
from app.comparison.calculation_control import checkpoint

MAX_BYTES = 128 * 1024 * 1024
MAX_TURN_SECONDS = 8


def invalid(checks):
    return bool(checks['all'] or any(checks['observations'].values())
                or any(checks['comparisons'].values()))


def validate(frame, facts, *, at, owner, engine, policy, binding=None):
    from .latest_board import runtime_identity
    checks=dependencies.reasons(frame,facts['publication_dependencies'],at=at)
    if facts['publication_runtime']!=runtime_identity(owner):checks['all'].append('runtime_authority_changed')
    if not owner.get('healthy'):checks['all'].append('data_runtime_unhealthy')
    if not owner.get('active'):checks['all'].append('updates_stopped')
    if owner.get('calculations',{}).get('board','running')!='running':checks['all'].append('background_calculations_unavailable')
    if facts.get('authority_control')!=frame.get('control_barrier'):checks['all'].append('publication_authority_changed')
    context=facts.get('context') or {}
    if context.get('engine_binding')!=engine:checks['all'].append('engine_binding_changed')
    if context.get('policy_revision')!=policy:checks['all'].append('policy_changed')
    if facts.get('observation_binding')!=(binding if binding is not None else observation_binding()):checks['all'].append('matching_binding_changed')
    return checks


def seal(db, game_key, facts, *, calculated_at, work_version=None):
    """Reject stale work; no sibling unit is replaced or granted authority."""
    from .latest_board import runtime, source_states, load, engine_binding
    from .current_rows import LOCK
    from app.collection.runtime_status import AUTHORITY_LOCK
    from app.collection.current_storage_policy import require_disk_space, sql_usage, SQL_BYTE_CAP
    checkpoint()
    saved=facts['publication_dependencies'];unit=saved['result_unit']
    size=len(encoded(facts))
    if size>8*1024*1024:raise ValueError('result_unit_capacity')
    started=monotonic();timing={}
    with db.transaction():
        db.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
        acquired=monotonic();timing['ingress_lock_wait_ms']=round((acquired-started)*1000,3)
        db.execute('SELECT pg_advisory_xact_lock_shared(%s)',(AUTHORITY_LOCK,))
        checkpoint()
        now=utc();owner=runtime(db,at=now)
        committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status')}
        frame=publication.capture(db,source_states(committed,owner),selector=saved['selector'],compact='lazy')
        from .latest_board import _control_barrier
        frame['control_barrier']=_control_barrier(db)
        checks=validate(frame,facts,at=now,owner=owner,engine=engine_binding(),policy=load().revision)
        timing['validation_ms']=round((monotonic()-acquired)*1000,3)
        if invalid(checks):return dict(published=False,checks=checks,timing=timing)
        from .result_inventory import acknowledge
        if work_version is not None:
            work=db.execute('SELECT pending_version FROM current_result_work WHERE game_key=%s AND unit_id=%s FOR UPDATE',
                (game_key,unit['id'])).fetchone()
            if work is None or work['pending_version']!=work_version:
                return dict(published=False,reason='newer_pending_result_version',timing=timing)
        previous=db.execute('SELECT captured_at,generation_id FROM current_result_unit WHERE game_key=%s AND unit_id=%s',
                            (game_key,unit['id'])).fetchone()
        if previous and previous['captured_at']>=stamp(unit['captured_at']):
            if previous['generation_id']==facts.get('unit_generation_id'):
                acknowledge(db,game_key,unit['id'],work_version)
            return dict(published=False,reason='newer_or_equal_result_unit')
        retained=db.execute('SELECT COALESCE(sum(retained_bytes),0) n FROM current_result_unit WHERE NOT(game_key=%s AND unit_id=%s)',
                            (game_key,unit['id'])).fetchone()['n']
        if retained+size>MAX_BYTES:
            # Reclaim only redundant out-of-window working copies before
            # refusing new eligible work. Parent/captured Originals survive; obsolete authority is reclaimed too.
            prune(db)
            retained=db.execute('SELECT COALESCE(sum(retained_bytes),0) n FROM current_result_unit WHERE NOT(game_key=%s AND unit_id=%s)',
                (game_key,unit['id'])).fetchone()['n']
            if retained+size>MAX_BYTES:raise ValueError('result_unit_retention_capacity')
        from .latest_board import MAX_BYTES as PUBLICATION_BYTES
        from .grid_packet_store import retained_bytes as packet_bytes, extra_bytes, put
        original=encoded(facts['selected_frame']) if facts.get('selected_frame') is not None else None
        additional=extra_bytes(db,[original]) if original else 0
        other=db.execute('SELECT COALESCE(sum(retained_bytes),0) n FROM latest_board').fetchone()['n']
        other+=db.execute('SELECT COALESCE(sum(retained_bytes-blob_bytes),0) n FROM current_grid_projection').fetchone()['n']
        if retained+size+other+packet_bytes(db)+additional>PUBLICATION_BYTES:raise ValueError('latest_board_capacity')
        require_disk_space(ROOT/'.local/postgres',append_bytes=size+additional)
        if sql_usage(db)+size+additional>=SQL_BYTE_CAP:raise ValueError('current_database_storage_cap')
        checkpoint()
        original_id=put(db,original) if original else None
        generation=facts.get('unit_generation_id') or hashed([game_key,saved,facts['context']])
        db.execute('''INSERT INTO current_result_unit(game_key,unit_id,captured_at,calculated_at,generation_id,facts,original_blob_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(game_key,unit_id) DO UPDATE SET
            captured_at=excluded.captured_at,calculated_at=excluded.calculated_at,
            published_at=clock_timestamp(),generation_id=excluded.generation_id,facts=excluded.facts,original_blob_id=excluded.original_blob_id''',
            (game_key,unit['id'],unit['captured_at'],calculated_at,generation,Jsonb(facts),original_id))
        acknowledge(db,game_key,unit['id'],work_version)
        from .pipeline_generation import outcome
        timing['lock_held_lower_bound_ms']=round((monotonic()-acquired)*1000,3)
        outcome(db,generation,published=True,facts=dict(unit_id=unit['id'],captured_at=unit['captured_at'],timing=timing))
    return dict(published=True,generation_id=generation,commit_observed_at=utc(),timing=timing)


def prune(db):
    """Working projection only; captured reader evidence has independent leases."""
    db.execute("DELETE FROM current_result_unit WHERE published_at<clock_timestamp()-interval '2 hours'")
    from datetime import timedelta
    instant=stamp(utc())
    from .latest_board import runtime
    owner=runtime(db,at=instant.isoformat())
    live_runtime=owner.get('runtime_id') if owner.get('healthy') else None
    # Unknown/missing schedules do not establish a withdrawal. Every recorded
    # source must still exist and be outside the current window. The exact unit
    # generation must also remain in its parent, with Original evidence.
    db.execute("""WITH outside AS MATERIALIZED (
        SELECT i.game_key FROM current_result_inventory i
        WHERE jsonb_array_length(i.events)>0 AND NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(i.events) m(event_id)
            LEFT JOIN current_event e ON e.id=m.event_id
            WHERE e.id IS NULL OR NULLIF(e.scheduled_start,'') IS NULL
                OR (e.scheduled_start::timestamptz >= %s AND e.scheduled_start::timestamptz < %s))),
        candidates AS MATERIALIZED (
            SELECT r.game_key,r.unit_id,r.generation_id FROM current_result_unit r
            LEFT JOIN outside o USING(game_key)
            WHERE o.game_key IS NOT NULL
                OR r.facts#>>'{context,engine_binding}'<>%s
                OR (%s::text IS NOT NULL AND r.facts#>>'{publication_runtime,runtime_id}'<>%s)),
        preserved AS MATERIALIZED (
            SELECT b.game_key,u.key unit_id,u.value->>'generation_id' generation_id
            FROM latest_board b JOIN (SELECT DISTINCT game_key FROM candidates) c USING(game_key)
            CROSS JOIN LATERAL jsonb_each(b.facts->'result_units') u
            WHERE u.value->'facts' ? 'selected_frame')
        DELETE FROM current_result_unit r USING preserved p,candidates c
        WHERE r.game_key=c.game_key AND r.unit_id=c.unit_id AND r.generation_id=c.generation_id
            AND r.game_key=p.game_key AND r.unit_id=p.unit_id AND r.generation_id=p.generation_id""",
        (instant,instant+timedelta(hours=72),engine_binding(),live_runtime,live_runtime))


def calculate(db, observed, bundle, policy, context, *, calculator=None):
    """Calculate and seal each independent closure before starting its sibling."""
    from .latest_board import _selection_payload, next_boundary
    from .comparison_board import calculate_current, context_identity
    from app.comparison.calculation_control import CalculationStopped
    from app.diagnostics import failure, failure_details
    from copy import deepcopy
    calculator=calculator or calculate_current
    discovery_started=monotonic()
    plan=bundle.get('_discovery_plan')
    partitions=plan['units'] if plan else dependencies.partitions(bundle)
    discovery_ms=round((monotonic()-discovery_started)*1000,3)
    from .pipeline_generation import admit, completed, outcome
    names={u['id']:bundle['game_key']+'#result:'+u['id'] for u in partitions}
    retained={r['unit_id']:r for r in db.execute('SELECT * FROM current_result_unit WHERE game_key=%s',
                                               (bundle['game_key'],))}
    units={};attempts=[]
    # Discovery completeness is identical for all slices of this coherent
    # capture. Build it once, while retaining every candidate for every unit.
    manifest_started=monotonic()
    complete=publication.manifest(context.publication_frame,bundle)
    complete_roster=dependencies.roster(context.publication_frame,complete['selector'])
    manifest_ms=round((monotonic()-manifest_started)*1000,3)
    from . import result_inventory as inventory
    inventory_proof=inventory.proof(context.publication_frame,complete['selector'],engine=context.engine,policy=policy.revision,
        owner=context.publication_runtime)
    inventory_revision=inventory.record(db,bundle,partitions,inventory_proof)
    partitions=inventory.ordered(db,bundle['game_key'],partitions)
    refreshing=getattr(context,'result_refresh_units',set())
    refresh_orders=getattr(context,'result_refresh_orders',{})
    if refreshing:partitions.sort(key=lambda unit:(unit['id'] not in refreshing,refresh_orders.get(unit['id'],(True,0))))
    turn_started=monotonic()
    for index,unit in enumerate(partitions):
        checkpoint()
        if index and monotonic()-turn_started>=MAX_TURN_SECONDS:
            # Publish/reuse completed closures now; resume oldest unit attempts
            # on a later ordinary turn instead of consuming the child lifetime.
            for pending in partitions[index:]:
                prior=retained.get(pending['id'])
                if prior:
                    units[pending['id']]=dict(facts=prior['facts'],calculated_at=prior['calculated_at'].isoformat(),generation_id=prior['generation_id'])
            break
        prior=retained.get(unit['id'])
        work_version=inventory.visit(db,bundle['game_key'],unit['id'])
        if prior and not invalid(validate(context.publication_frame,prior['facts'],at=context.at,
                owner=context.result_owner,engine=context.engine,policy=policy.revision)):
            units[unit['id']]=dict(facts=prior['facts'],calculated_at=prior['calculated_at'].isoformat(),
                                  generation_id=prior['generation_id'])
            seal(db,bundle['game_key'],prior['facts'],calculated_at=prior['calculated_at'],work_version=work_version)
            completed(db,prior['generation_id'],reused=True)
            attempts.append(dict(unit_id=unit['id'],reused=True,published=False))
            continue
        capture_started=monotonic()
        try:
            if plan:
                from .discovery_index import hydrate
                sliced=hydrate(context,bundle,unit,policy)
            else:
                sliced=dependencies.slice_bundle(bundle,unit)
            manifest=dependencies.capture(context.publication_frame,bundle,unit,complete=complete,complete_roster=complete_roster,sliced=sliced)
        except (CalculationStopped,MemoryError,OSError):raise
        except Exception as exc:
            # A changing selected book consumes its durable visit, but must not
            # abort fair work on independent siblings or acquire a result seal.
            diagnostic=admit(db,names[unit['id']]+'#discovery',dict(complete,discovery_unit=unit),context.engine,policy.revision,[])
            evidence=dict(stage='selected_unit_hydration',failure=failure_details(exc),
                unit_id=unit['id'],elapsed_ms=round((monotonic()-capture_started)*1000,3))
            outcome(db,diagnostic,published=False,reason='result_unit_hydration_failed',facts=evidence)
            attempts.append(dict(unit_id=unit['id'],published=False,reason='result_unit_hydration_failed'))
            if prior:
                units[unit['id']]=dict(facts=prior['facts'],calculated_at=prior['calculated_at'].isoformat(),generation_id=prior['generation_id'])
            continue
        stages=dict(partition_discovery_ms=discovery_ms,complete_manifest_ms=manifest_ms,refresh_priority=unit['id'] in refreshing,
            discovery_index_reused=bundle.get('_discovery_reused',False),
            full_discovery_ms=getattr(context,'result_discovery_ms',None),
            unit_capture_ms=round((monotonic()-capture_started)*1000,3))
        stages.update(bundle.get('_discovery_timings',{}))
        stages.update(sliced.get('input_stage_timings',{}))
        generation=admit(db,names[unit['id']],manifest,context.engine,policy.revision,[])
        try:
            calculation_started=monotonic()
            value=calculator(sliced,policy,context=context)
            stages['unit_calculation_ms']=round((monotonic()-calculation_started)*1000,3)
            rendering_started=monotonic()
            facts=_selection_payload(deepcopy(sliced),sliced,value,policy,context,dependencies=manifest)
            completed(db,generation)
            facts['unit_generation_id']=generation
            facts['authority_control']=getattr(context,'result_control',None)
            facts['boards'].pop('odds',None)
            facts['inventory_revision']=inventory_revision
            from .dashboard_results import project
            facts['dashboard_boards']=project(facts)['boards']
            stages['unit_render_ms']=round((monotonic()-rendering_started)*1000,3)
            # Sealed facts must stay identical to their retained parent copy.
            # Post-seal timing belongs to the generation diagnostic, not a
            # mutation of evidence already serialized by seal().
            facts['unit_stage_timings']=dict(stages)
            seal_started=monotonic()
            result=seal(db,bundle['game_key'],facts,calculated_at=value['calculated_at'],work_version=work_version)
            stages['unit_seal_ms']=round((monotonic()-seal_started)*1000,3)
            result['stage_timings']=stages
            if not result['published']:
                outcome(db,generation,published=False,reason=result.get('reason') or 'result_dependencies_changed',facts=result)
            else:
                db.execute('UPDATE pipeline_generation SET facts=facts||%s WHERE id=%s',(Jsonb(result),generation))
            attempts.append(dict(unit_id=unit['id'],**result))
            # Invalid work remains visibly historical; it cannot erase a
            # previously sealed sibling or acquire authority from one.
            if result['published']:
                units[unit['id']]=dict(facts=facts,calculated_at=value['calculated_at'],generation_id=result['generation_id'])
            elif prior:
                units[unit['id']]=dict(facts=prior['facts'],calculated_at=prior['calculated_at'].isoformat(),generation_id=prior['generation_id'])
            else:
                facts['retained_financial_only']=True
                units[unit['id']]=dict(facts=facts,calculated_at=value['calculated_at'],generation_id=None)
        except (CalculationStopped,MemoryError,OSError):raise
        except Exception as exc:
            # This optional unit failed; valid siblings still get their turn.
            failure(__name__,'result_unit_calculation',exc)
            outcome(db,generation,published=False,reason='result_unit_calculation_failed',
                    facts=dict(failure=failure_details(exc),stage_timings=stages))
            attempts.append(dict(unit_id=unit['id'],published=False,reason='result_unit_calculation_failed'))
            if prior:
                units[unit['id']]=dict(facts=prior['facts'],calculated_at=prior['calculated_at'].isoformat(),generation_id=prior['generation_id'])
    if not units:raise ValueError('result_units_unavailable')
    facts=_selection_payload(observed,None,None,policy,context,'background_estimates_pending')
    facts['result_units']=units
    facts['result_unit_inventory']=partitions
    facts['result_inventory_revision']=inventory_revision
    facts['result_inventory_dependencies']=inventory_proof
    facts['result_inventory_discovered_at']=bundle['as_of']
    facts['result_unit_attempts']=attempts
    facts['discovery_index_reused']=bundle.get('_discovery_reused',False)
    current_at_capture=sum(bool(u.get('generation_id')) and not invalid(validate(context.publication_frame,u['facts'],
        at=context.at,owner=context.result_owner,engine=context.engine,policy=policy.revision)) for u in units.values())
    facts['result_inventory_accounting']=dict(known=len(partitions),retained=len(units),
        current_at_capture=current_at_capture,complete_at_capture=current_at_capture==len(partitions))
    facts['calculation_error']=None
    facts['context']=context_identity(bundle,policy,context)
    facts['valid_until']=next_boundary(bundle,context.at)
    facts['estimate_availability']=dict(state='partial' if len(units)==len(partitions) and all(u.get('generation_id') for u in units.values()) else 'pending',reason_codes=[],calculated_at=utc())
    # Display assembly does not recalculate or renew any unit's captured clocks.
    from app.dashboard.comparison_board import expand_price_fields,compact_price_fields
    from app.comparison.calculation_availability import combine
    for view in ('ev','arbs'):
        boards=[expand_price_fields(deepcopy(u['facts']['boards'][view])) for u in units.values()]
        out=expand_price_fields(facts['boards'][view])
        out['rows']=[r for b in boards for r in b['rows']]
        out['prices']=[p for b in boards for p in b['prices']]
        out['availability']=combine([b['availability'] for b in boards],games=1,evaluated=True)
        compact_price_fields(out)
    return facts


def attach(db, row, *, guard=None, view=None, original_blob=None, lazy_originals=False):
    """Overlay independently committed units in the caller's MVCC read frame.

    Their inputs are copied or retained by immutable packet leases. Replacement
    preserves exact Originals independently of the current publication.
    """
    import json
    projection="(facts-'boards') || jsonb_build_object('boards',jsonb_build_object(%s::text,facts->'boards'->%s::text))" if view else 'facts'
    if lazy_originals:
        projection="CASE WHEN original_blob_id IS NULL THEN ("+projection+") ELSE (("+projection+")-'selected_frame') || jsonb_build_object('selected_frame',jsonb_build_object('original_packet',original_blob_id,'kind','unit')) END"
    args=(view,view,view,view,row['game_key']) if view and lazy_originals else (view,view,row['game_key']) if view else (row['game_key'],)
    size=db.execute('SELECT COALESCE(sum(octet_length(('+projection+')::text)),0) n FROM current_result_unit WHERE game_key=%s',
                    args).fetchone()['n']
    if guard:guard(int(size)*8)
    values=db.execute('SELECT unit_id,captured_at,calculated_at,generation_id,'+projection+' AS facts FROM current_result_unit WHERE game_key=%s',
                      args).fetchall()
    discovered=db.execute('SELECT discovered_at,revision,dependencies,units FROM current_result_inventory WHERE game_key=%s',
                          (row['game_key'],)).fetchone()
    text='_facts_text' in row
    facts=json.loads(row['_facts_text']) if text else row['facts']
    def restore_originals(children):
        if lazy_originals:return
        pointers={u['facts']['selected_frame']['original_packet']:u['facts']
            for u in children.values() if isinstance(u['facts'].get('selected_frame'),dict)
            and u['facts']['selected_frame'].get('original_packet')}
        if not pointers:return
        size=db.execute('SELECT COALESCE(sum(retained_bytes),0) n FROM current_grid_blob WHERE id=ANY(%s)',
            (list(pointers),)).fetchone()['n']
        if guard:guard(int(size)*8)
        packets={p['id']:json.loads(bytes(p['packet'])) for p in db.execute(
            'SELECT id,packet FROM current_grid_blob WHERE id=ANY(%s)',(list(pointers),))}
        if set(packets)!=set(pointers):raise ValueError('current_slate_read_expired')
        for child in children.values():
            payload=child['facts'].get('selected_frame')
            if isinstance(payload,dict) and payload.get('original_packet'):
                child['facts']['selected_frame']=packets[payload['original_packet']]
    newest=max(values,key=lambda u:u['captured_at']) if values else None
    inventory=discovered['units'] if discovered else newest['facts'].get('unit_inventory') if newest else None
    if lazy_originals and original_blob and facts.get('selected_frame') is not None:
        facts['selected_frame']=dict(original_packet=original_blob,kind='parent')
        row['_original_packets']=[original_blob]
    if inventory is None:
        restore_originals(facts.get('result_units',{}))
        if text:row['_facts_text']=encoded(facts).decode()
        else:row['facts']=facts
        return row
    wanted={u['id'] for u in inventory}
    retained={k:v for k,v in facts.get('result_units',{}).items() if k in wanted}
    if view:
        for value in retained.values():
            value['facts']['boards']={view:value['facts']['boards'][view]}
    for value in values:
        if value['unit_id'] in wanted:
            retained[value['unit_id']]=dict(facts=value['facts'],calculated_at=value['calculated_at'].isoformat(),
                generation_id=value['generation_id'])
    restore_originals(retained)
    facts.update(result_units=retained,result_unit_inventory=inventory)
    if discovered:
        facts['result_inventory_revision']=discovered['revision']
        facts['result_inventory_dependencies']=discovered['dependencies']
        facts['result_inventory_discovered_at']=discovered['discovered_at'].isoformat()
    if lazy_originals:
        if original_blob and facts.get('selected_frame') is not None:
            facts['selected_frame']=dict(original_packet=original_blob,kind='parent')
        packets=[]
        for f in [facts]+[v['facts'] for v in retained.values()]:
            payload=f.get('selected_frame')
            if isinstance(payload,dict) and payload.get('original_packet'):packets.append(payload['original_packet'])
        row['_original_packets']=sorted(set(packets))
    if text:
        row['_facts_text']=encoded(facts).decode()
        # Result rendering uses the complete independently captured children.
        # The merged parent board is redundant once at least one child exists;
        # keep it only for the all-pending source-only fallback.
        if view and retained:row['_board_text']=None
    else:row['facts']=facts
    return row
