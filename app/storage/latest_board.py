"""One background owner of bounded replaceable compact ordinary board results.

HTTP readers only read these compact rows and committed input/status identities.
Selected typed inputs use the bounded lossless payload codec within the same
total publication budget. Expanded financial reports are never retained here.
"""
import asyncio
from app.collection.background_work import AcquisitionDeferred,optional_cancelled
from contextlib import contextmanager
from threading import RLock
from time import monotonic
from app.diagnostics import failure
from datetime import timedelta
from psycopg.types.json import Jsonb
from psycopg.errors import LockNotAvailable, SerializationFailure, DeadlockDetected

from .store import ROOT, connect, encoded, hashed, stamp
from .current_games import GameStore, engine_binding, observation_binding, utc
from .comparison_board import ReadContext, discover, calculate_current, context_identity, observation_identity
from app.comparison.estimated_policy import load
from app.dashboard.comparison_board import response, financial_responses, entries
from app.comparison.calculation_availability import summary, result_availability
from . import observation_publication as publication
from .slate_reads import CapturedReads
from .board_capture import SOURCE_PREVIOUS, capture_reservation, capture_batches, prioritize_sources, prioritize_pending
from .board_view import board as board, bounded_page as bounded_page
from app.comparison.calculation_control import CalculationStopped, cancellation, checkpoint
from app.comparison.current_dependencies import validation_scope
from app.collection.runtime_status import runtime_identity, source_states

# Full-scope source + retained financial evidence exceeded 192 MiB with only
# 75/180 games calculated. This is a disk publication allowance, not an in-memory
# read allowance: component, per-game, detached-read, RSS and 2 GiB SQL guards
# remain independent. Do not evict valid games to admit their peers.
MAX_BYTES = 512 * 1024 * 1024
LOCK = 903015
_SLATE_READS = CapturedReads()
def marker(db, event_ids=None):
    """Cheap committed identities, including withdrawals independent of quotes."""
    epoch = db.execute('SELECT epoch FROM current_row_epoch WHERE singleton=true').fetchone()['epoch']
    values = []
    for query,params in (
        ('SELECT id,revision,expires_order::text FROM current_event ORDER BY id',None),
        ('SELECT DISTINCT c.event_id FROM current_contract c JOIN current_offer o ON o.contract_id=c.id ORDER BY c.event_id',None),
        ('SELECT id,contract_dependency FROM current_contract WHERE (%s::text[] IS NULL OR event_id=ANY(%s)) ORDER BY id',(event_ids,event_ids)),
        ('SELECT o.contract_id,o.revision,o.source_at FROM current_offer o JOIN current_contract c ON c.id=o.contract_id WHERE (%s::text[] IS NULL OR c.event_id=ANY(%s)) ORDER BY o.contract_id',(event_ids,event_ids)),
        ('SELECT venue,event_id,native_market_id,revision FROM current_native_book WHERE (%s::text[] IS NULL OR event_id=ANY(%s)) ORDER BY venue,event_id,native_market_id',(event_ids,event_ids)),
        ('SELECT venue,state FROM current_source_status ORDER BY venue',None),
    ):
        rows = db.execute(query,params).fetchall()
        if len(rows) > 32768:raise ValueError('board_marker_capacity')
        if query.startswith('SELECT venue,state'):
            rows=[dict(venue=row['venue'],state=publication.health(row['state'])) for row in rows]
        values.append(rows)
    return hashed([epoch, values])


def runtime(db, *, at=None):
    from app.collection.runtime_status import read_runtime
    return read_runtime(db, at=at)


def captured_owner(value):
    """Retain every validation authority field without diagnostic payloads."""
    result={k:value.get(k) for k in ('runtime_id','active','healthy','config','paused_sources','global_stopped','service_state')}
    result['calculations']={k:value.get('calculations',{}).get(k,'running') for k in ('observations','board')}
    return result


def inventory_state(frame, facts, *, owner, at, engine=None, policy=None):
    from .result_inventory import current
    saved=facts.get('result_inventory_dependencies')
    if saved is None:return 'unknown'
    return 'current' if current(frame,saved,engine=engine if engine is not None else engine_binding(),policy=policy if policy is not None else load().revision,
        owner=runtime_identity(owner),at=at) else 'historical'


def _control_barrier(db):
    # The latest control identity survives Stop followed by recovery between
    # HTTP requests. Ordinary collection/publication never writes this table.
    row=db.execute("""SELECT id FROM data_runtime_command
        WHERE action IN ('stop','pause','recover') ORDER BY created_at DESC,id DESC LIMIT 1""").fetchone()
    return row['id'] if row else None


def _slate_authority(epoch, owner, states, control):
    # Receipt clocks and routine diagnostic wording cannot revoke a detached
    # observation. Native resynchronization/recovery does not change permission
    # to read that immutable capture. Unavailability and explicit controls do.
    return hashed(dict(epoch=str(epoch),runtime=runtime_identity(owner),
        sources={key:('collecting' if value.get('state') in ('available','resyncing') else value.get('state'))
            for key,value in states.items()},control=control,
        policy=load().revision,engine=engine_binding(),observations=observation_binding()))


def slate_authority(db, *, stopped=False):
    """Small current revocation check; never recapture prices or publications."""
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        owner=runtime(db)
        epoch=db.execute('SELECT epoch FROM current_row_epoch WHERE singleton=true').fetchone()['epoch']
        committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
        authority=_slate_authority(epoch,owner,source_states(committed,owner),_control_barrier(db))
    return hashed([authority,bool(stopped)])


def read_context(db, *, at=None, owner=None, event_ids=None, resource_guard=None, tolerate_invalid_catalog=False):
    from .current_rows import CurrentRowStore
    owner=owner if owner is not None else runtime(db,at=at)
    started=monotonic()
    frame=CurrentRowStore(db).capture(include_depth=False,event_ids=event_ids,resource_guard=resource_guard)
    # Retain old provider rows in storage and raw history, but do not let a
    # newly rebuilt board promote an inactive aggregate source as current.
    active_provider=owner.get('config',{}).get('aggregate_provider','the_odds_api')
    frame['records']=[r for r in frame['records'] if r['quote']['source']['provider'] not in ('the_odds_api','sportsgameodds')
                      or r['quote']['source']['provider']==active_provider]
    captured_ms=round((monotonic()-started)*1000,3)
    frame['source_status']=source_states(frame['source_status'],owner)
    context=ReadContext(GameStore(db),at=at,frame=frame,resource_guard=resource_guard,tolerate_invalid_catalog=tolerate_invalid_catalog)
    context.timings['sql_row_capture_ms']=captured_ms
    return context


def next_boundary(bundle, at):
    """Every known temporal authority boundary; passing one fails closed on reads."""
    instant = stamp(at); clocks = []
    def add(value, seconds=0):
        if value is not None:
            boundary = stamp(value) + timedelta(seconds=seconds)
            if boundary > instant:clocks.append(boundary)
    def walk(value):
        if isinstance(value, dict):
            for key,item in value.items():
                if key in ('expires_at','effective_to','effective_until','effective_from','model_effective_from','scheduled_ts') and isinstance(item,str):add(item)
                else:walk(item)
        elif isinstance(value,list):
            for item in value:walk(item)
    from app.comparison.modeled_winner import START, END
    add(START);add(END)
    for event,_,q in entries(bundle['state_inputs']):
        walk(q)
        add(event['start_at'])
        add(q['times'].get('source_at'));add(q['times'].get('received_at'))
        add(q['times'].get('source_at'), 15 if q.get('comparison_input_refs',{}).get('phase')=='live' else 900)
        from app.comparison.current_dependencies import references
        values=references(q,bundle['state_inputs']['comparison_profiles'])
        walk(values)
        reference=values.get('reference',{}).get('payload',{})
        for clock in reference.get('source_at',[]):add(clock,900);add(clock,1800)
    return min(clocks).isoformat() if clocks else None


def observation_boundary(bundle, at):
    """Source-only clocks; estimates and benchmark validity do not age prices."""
    instant=stamp(at);clocks=[]
    for event,_,q in entries(bundle['state_inputs']):
        from app.comparison.source_clock import evidence
        source_clock=evidence(q)[0]
        for value,seconds in ((event['start_at'],0),(q['times'].get('source_at'),0),
                              (q['times'].get('received_at'),0),(source_clock,q.get('freshness_policy',{}).get('maximum_age_seconds',900))):
            if value is not None and stamp(value)+timedelta(seconds=seconds)>instant:
                clocks.append(stamp(value)+timedelta(seconds=seconds,microseconds=1 if seconds else 0))
        for key in ('effective_from','effective_until'):
            value=q.get('occurrence_link',{}).get(key)
            if value and stamp(value)>instant:clocks.append(stamp(value))
    return min(clocks).isoformat() if clocks else None


def _selection_payload(observed, bundle, value, policy, context, error=None, dependencies=None):
    observed['calculation_context']=observation_identity(observed,context)
    boards={'odds':response(observed,None,policy,view='odds',filter='all',at=context.at)}
    financial_context=None
    if bundle is not None and value is not None:
        financial_context=value['calculation_context']
        bundle['calculation_context']=financial_context
    financial=bundle if financial_context else observed
    boards.update(financial_responses(financial,value if financial_context else None,policy,at=context.at))
    metrics=boards['ev']['availability']
    codes=[cause['code'] for cause in metrics.get('causes',[])]
    available=dict(state='pending' if error=='background_estimates_pending' else 'unavailable' if error or not metrics['numeric_results'] else 'partial' if metrics['numeric_results']<metrics['total_results'] else 'evaluated',
                   reason_codes=[error] if error else codes,calculated_at=None if value is None else value['calculated_at'])
    if error and error!='background_estimates_pending':
        from app.comparison.calculation_availability import refusal
        state,codes=refusal([error])
        for view in ('ev','arbs'):
            boards[view]['availability']=summary([(observed['game_key'],[q['venue']],dict(state=state,reason_codes=codes,current_opportunity_eligible=False)) for _,_,q in entries(observed['state_inputs'])])
            boards[view]['empty_reason']='Calculations pending' if error=='background_estimates_pending' else 'Estimate unavailable; collected observations remain available'
    from .selected_frame import pack
    if dependencies is None:
        dependencies=publication.manifest(context.publication_frame,observed)
        if financial_context:publication.bind_references(context.publication_frame,dependencies,bundle)
    return dict(publication_runtime=context.publication_runtime,boards=boards,selection_frame_available=True,selected_frame=pack(observed,bundle if financial_context else None,context,dependencies),observation_valid_until=observation_boundary(observed,context.at),
        valid_until=next_boundary(bundle,context.at) if financial_context else None,
        context=financial_context,observation_context=observed['calculation_context'],estimate_availability=available,calculation_error=error,
        observation_binding=context.observation_binding,
        publication_dependencies=dependencies)


def publish(db, *, captured_marker, captured_runtime, status, rows, diagnostics=None):
    """CAS exact price/membership dependencies; unrelated ingress cannot starve it."""
    checkpoint()
    diagnostics={} if diagnostics is None else diagnostics
    def refuse(reason):
        diagnostics['failure']=reason
        return False
    started=monotonic()
    from .current_rows import LOCK as CURRENT_LOCK
    scope=status.get('capture_events')
    def validation(owner):
        committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
        frame=publication.capture(db,source_states(committed,owner),compact='lazy',
            selector=dict(events=scope,occurrences=[],shared=[]) if scope is not None else None)
        checks={row['game_key']:publication.reasons(frame,row['facts']['publication_dependencies'])
            for row in rows if row['facts'].get('publication_dependencies') is not None}
        return frame,checks
    original_packets={}
    def projection(row):
        # Independent unit Originals already have a content-addressed owner.
        # Parent fallback keeps an explicit reference instead of duplicating the
        # compressed payload on every raw-price or financial publication.
        from .grid_packet_store import identity
        for unit in row['facts'].get('result_units',{}).values():
            original=unit['facts'].get('selected_frame')
            if original is None or isinstance(original,dict) and original.get('original_packet'):continue
            packet=encoded(original);key=identity(packet)
            original_packets[key]=packet
            unit['facts']['selected_frame']=dict(original_packet=key,kind='unit')
        from copy import deepcopy
        from app.dashboard.grouped_odds import grid_board
        from .grid_read_packet import pack as pack_grid
        from .dashboard_results import project
        grid=grid_board(deepcopy(row['facts']['boards']['odds']))
        packet=pack_grid(row,grid);dashboard=project(row['facts'])
        sizes=db.execute('SELECT octet_length(%s::jsonb::text) grid,octet_length(%s::jsonb::text) board,octet_length(%s::jsonb::text) selector',
            (Jsonb(grid),Jsonb(row['facts']),Jsonb(row['facts'].get('publication_dependencies',{}).get('selector')))).fetchone()
        return grid,packet,dashboard,sizes['grid']+len(packet)+sizes['selector'],len(encoded(dashboard)),sizes['board']
    # Build immutable views outside the ingress critical section. Rows merged
    # with a newer observation below are the only ones that need rebuilding.
    projections={}
    changed_rows=set()
    # Dependency decoding and candidate validation can be expensive. Do that
    # without blocking synchronous ingress callbacks (and their event loop's
    # heartbeat). Seal against a cheap committed marker under the ingress lock.
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        validated_marker=marker(db,scope)
        validation_owner=runtime(db)
        current,validated_checks=validation(validation_owner)
        merge_priors={r['game_key']:r for r in db.execute(
            'SELECT game_key,xmin::text version,calculated_at,facts FROM latest_board WHERE game_key=ANY(%s)',
            ([r['game_key'] for r in rows],))}
    # Observation/financial owners usually merge separate evidence. Preparing
    # that full immutable view under the ingress lock blocks source admission.
    # Reuse only against the exact row version checked after acquiring the lock;
    # concurrent replacement takes the existing synchronous merge path.
    from copy import deepcopy
    from .selected_frame import preserve_newer_observation
    merge_prepared={}
    merge_started=monotonic()
    for row in rows:
        prior=merge_priors.get(row['game_key'])
        if not prior or not prior['facts'].get('selected_frame') or not row['facts'].get('selected_frame'):continue
        if status.get('observation_only'):
            if not prior['facts'].get('context'):continue
            merged=deepcopy(prior['facts']);preserve_newer_observation(merged,row['facts'])
        else:
            prior_at=prior['facts']['boards']['odds'].get('as_of')
            incoming_at=row['facts']['boards']['odds'].get('as_of')
            if not prior_at or not incoming_at or stamp(prior_at)<=stamp(incoming_at):continue
            merged=deepcopy(row['facts']);preserve_newer_observation(merged,prior['facts'])
        merged_row=dict(row,facts=merged)
        if status.get('observation_only'):merged_row['calculated_at']=prior['calculated_at']
        merge_prepared[row['game_key']]=(prior['version'],merged,projection(merged_row))
    merge_priors.clear()
    projections={row['game_key']:projection(row) for row in rows if row['game_key'] not in merge_prepared}
    diagnostics['merge_prepare_ms']=round((monotonic()-merge_started)*1000,3)
    diagnostics['prepared_merge_hits']=0
    with db.transaction():
        diagnostics['validation_ms']=round((monotonic()-started)*1000,3)
        lock_started=monotonic()
        db.execute('SELECT pg_advisory_xact_lock(%s)',(CURRENT_LOCK,))
        diagnostics['ingress_lock_wait_ms']=round((monotonic()-lock_started)*1000,3)
        from app.collection.runtime_status import AUTHORITY_LOCK
        db.execute('SELECT pg_advisory_xact_lock_shared(%s)',(AUTHORITY_LOCK,))
        now_runtime=runtime(db)
        current_owner=runtime_identity(now_runtime);captured_owner=runtime_identity(captured_runtime)
        if status.get('observation_only'):
            # The independent source owner needs observation authority. An
            # optional worker pause/failure cannot cancel its committed prices.
            current_owner.pop('calculation_state',None);captured_owner.pop('calculation_state',None)
        if current_owner!=captured_owner:return refuse('runtime_authority_changed')
        source_binding=observation_binding()
        if status.get('observation_binding')!=source_binding:return refuse('observation_engine_changed')
        if not status.get('observation_only') and status.get('engine_binding')!=engine_binding():return refuse('calculation_engine_changed')
        committed_marker=marker(db,scope)
        if committed_marker!=validated_marker or runtime_identity(now_runtime)!=runtime_identity(validation_owner):
            # Revalidate, rather than rejecting a harmless unrelated update.
            current,validated_checks=validation(now_runtime)
        if str(status.get('epoch'))!=current['epoch']:return refuse('epoch_changed')
        if scope is not None and status.get('capture_membership')!=hashed(publication.neighborhood(current,
                dict(events=scope,occurrences=[],shared=[]))):return refuse('membership_changed')
        if status.get('scope_complete'):
            from .result_inventory import reconcile_catalog
            reconcile_catalog(db,status['games'],at=status['as_of'])
        prior_keys=sorted({r['game_key'] for r in rows}|{e['game_key'] for e in status.get('observation_errors',[])})
        prior_observations={r['game_key']:r for r in db.execute(
            "SELECT game_key,xmin::text version,calculated_at,facts#>>'{boards,odds,as_of}' AS observation_as_of,"
            "facts->'observation_context' context,facts->'observation_valid_until' boundary,"
            "facts#>>'{estimate_availability,state}' estimate_state FROM latest_board WHERE game_key=ANY(%s)",(prior_keys,)).fetchall()}
        newest={key:r['observation_as_of'] for key,r in prior_observations.items()}
        # A delayed refusal must not replace a newer game's successful status,
        # including a status-only pass with no renderable rows to compare below.
        if any(newest.get(error['game_key']) and status.get('as_of') and
                stamp(newest[error['game_key']])>stamp(status['as_of']) for error in status.get('observation_errors',[])):
            return False
        accepted=[];rejected=[]
        for row in rows:
            saved=row['facts'].get('publication_dependencies')
            if saved is None:
                valid=committed_marker==captured_marker
            else:
                checks=validated_checks[row['game_key']]
                if row.get('_captured_frame') is not None:
                    row['_validation_checks']=checks
                    row['_validation_dependencies']=saved
                # Source snapshots are immutable evidence, not financial action
                # authority. A busy sibling book must not starve every quiet
                # quote in the game. Membership/authority still seals the whole
                # frame; ordinary reads invalidate changed quotes individually.
                valid=not checks['all'] and (status.get('observation_only') or
                    not(any(checks['comparisons'].values()) or any(checks['observations'].values())))
                # A newly completed calculation remains useful captured evidence
                # when individual prices moved during work. It never acquires
                # current financial authority, and cannot replay an older result
                # or bypass membership, metadata, runtime or source controls.
                prior=prior_observations.get(row['game_key'])
                calculated=row.get('calculated_at')
                if (not valid and not checks['all'] and not status.get('observation_only')
                        and calculated and (not prior or not prior['calculated_at']
                            or stamp(calculated)>stamp(prior['calculated_at']))):
                    row['facts']['retained_financial_only']=True
                    changed_rows.add(row['game_key'])
                    valid=True
            if row['facts'].get('observation_binding')!=source_binding:valid=False
            # A slow optional owner cannot replace a newer source publication
            # after time alone changed the eligible current comparator roster.
            prior_at=newest.get(row['game_key']);incoming_at=row['facts']['boards']['odds'].get('as_of')
            if prior_at and incoming_at and stamp(prior_at)>stamp(incoming_at):
                prior=prior_observations[row['game_key']]
                upgrade=(valid and not status.get('observation_only')
                    and ((row.get('calculated_at') and (not prior['calculated_at'] or stamp(row['calculated_at'])>stamp(prior['calculated_at'])))
                        or (prior['estimate_state']=='pending' and prior['context']==row['facts'].get('observation_context')
                            and prior['boundary']==row['facts'].get('observation_valid_until')))
                    and row['facts'].get('estimate_availability',{}).get('state') in ('evaluated','partial','unavailable'))
                if upgrade:
                    prepared=merge_prepared.get(row['game_key'])
                    if prepared and prepared[0]==prior['version'] and not row['facts'].get('retained_financial_only'):
                        row['facts']=prepared[1];diagnostics['prepared_merge_hits']+=1
                    else:
                        newer=db.execute('SELECT facts FROM latest_board WHERE game_key=%s',(row['game_key'],)).fetchone()['facts']
                        preserve_newer_observation(row['facts'],newer)
                    changed_rows.add(row['game_key'])
                else:valid=False
            if valid and status.get('observation_only'):
                prepared=merge_prepared.get(row['game_key']);prior=prior_observations.get(row['game_key'])
                if prepared and prior and prepared[0]==prior['version']:
                    row['facts']=prepared[1];row['calculated_at']=prior['calculated_at']
                    changed_rows.add(row['game_key']);diagnostics['prepared_merge_hits']+=1
                    previous=None
                else:previous=db.execute('SELECT calculated_at,facts FROM latest_board WHERE game_key=%s',(row['game_key'],)).fetchone()
                if previous and previous['facts'].get('context') and previous['facts'].get('selected_frame'):
                    # A new observation cannot erase completed financial evidence.
                    # Keep the two captures and validate finance against its own
                    # dependencies; changed results become last-known on reads.
                    from .selected_frame import preserve_newer_observation
                    retained=previous['facts']
                    preserve_newer_observation(retained,row['facts'])
                    row['facts']=retained;row['calculated_at']=previous['calculated_at']
                    changed_rows.add(row['game_key'])
            (accepted if valid else rejected).append(row)
        diagnostics.update(accepted_rows=len(accepted),rejected_rows=len(rejected),
            accepted_game_keys=[r['game_key'] for r in accepted],rejected_game_keys=[r['game_key'] for r in rejected])
        if not accepted and rows:return refuse('row_dependencies_or_newer_publication')
        rows=accepted
        # Use the same JSONB logical-byte basis for new and retained rows.
        # Stored generated values preserve exact accounting without expanding
        # the entire universe while the source-ingress lock is held.
        prepared=[merge_prepared[row['game_key']][2] if row['game_key'] in merge_prepared and row['facts'] is merge_prepared[row['game_key']][1]
            else projection(row) if row['game_key'] in changed_rows or row['game_key'] not in projections else projections[row['game_key']] for row in rows]
        grid_rows=[p[0] for p in prepared];grid_packets=[p[1] for p in prepared];dashboard_rows=[p[2] for p in prepared]
        grid_size=sum(p[3] for p in prepared);dashboard_size=sum(p[4] for p in prepared);size=sum(p[5] for p in prepared)
        from . import grid_packet_store as packets
        blob_extra=packets.extra_bytes(db,[*grid_packets,*original_packets.values()])
        grid_size-=sum(map(len,grid_packets))
        retained_size=db.execute('''SELECT count(*) n,COALESCE(sum(retained_bytes),0) bytes
            FROM latest_board WHERE NOT(game_key=ANY(%s))''',([r['game_key'] for r in rows],)).fetchone()
        unit_bytes=db.execute('SELECT COALESCE(sum(retained_bytes),0) n FROM current_result_unit').fetchone()['n']
        if unit_bytes+size+retained_size['bytes']+grid_size+packets.retained_bytes(db)+blob_extra+db.execute('SELECT COALESCE(sum(retained_bytes-blob_bytes),0) n FROM current_grid_projection WHERE NOT(game_key=ANY(%s))',([r['game_key'] for r in rows],)).fetchone()['n']>MAX_BYTES:raise ValueError('latest_board_capacity')
        from app.collection.current_storage_policy import require_disk_space,sql_usage,SQL_BYTE_CAP
        require_disk_space(ROOT/'.local/postgres',append_bytes=size+dashboard_size+grid_size+blob_extra)
        if sql_usage(db)+size+dashboard_size+grid_size+blob_extra>=SQL_BYTE_CAP:raise ValueError('current_database_storage_cap')
        for packet in original_packets.values():packets.put(db,packet)
        for row in rows:
            db.execute('''INSERT INTO latest_board (game_key,dependency_revision,economic_revision,calculated_at,facts) VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT(game_key) DO UPDATE SET dependency_revision=excluded.dependency_revision,
                economic_revision=excluded.economic_revision,calculated_at=excluded.calculated_at,facts=excluded.facts
                WHERE latest_board.economic_revision<>excluded.economic_revision OR latest_board.facts<>excluded.facts''',
                (row['game_key'],row['dependency_revision'],row['economic_revision'],row['calculated_at'],Jsonb(row['facts'])))
        for row in rows:
            references={uid:u['facts']['selected_frame']['original_packet']
                for uid,u in row['facts'].get('result_units',{}).items()
                if isinstance(u['facts'].get('selected_frame'),dict) and u['facts']['selected_frame'].get('original_packet')}
            db.execute('DELETE FROM current_result_parent_original WHERE game_key=%s AND NOT(unit_id=ANY(%s))',
                (row['game_key'],list(references)))
            for uid,blob in references.items():
                # Release the old ownership before replacing it so the exact
                # reader grace starts now, not at an earlier projection change.
                db.execute('DELETE FROM current_result_parent_original WHERE game_key=%s AND unit_id=%s AND blob_id<>%s',
                    (row['game_key'],uid,blob))
                db.execute('INSERT INTO current_result_parent_original VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                    (row['game_key'],uid,blob))
        for row,projected in zip(rows,dashboard_rows):
            db.execute('''INSERT INTO latest_dashboard VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT(game_key) DO UPDATE SET dependency_revision=excluded.dependency_revision,
                economic_revision=excluded.economic_revision,calculated_at=excluded.calculated_at,facts=excluded.facts''',
                (row['game_key'],row['dependency_revision'],row['economic_revision'],row['calculated_at'],Jsonb(projected)))
        for row,grid,packet in zip(rows,grid_rows,grid_packets):
            blob_id=packets.put(db,packet)
            db.execute('INSERT INTO current_grid_projection(game_key,facts,read_selector,blob_id,blob_bytes) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(game_key) DO UPDATE SET facts=EXCLUDED.facts,read_packet=NULL,read_selector=EXCLUDED.read_selector,blob_id=EXCLUDED.blob_id,blob_bytes=EXCLUDED.blob_bytes',
                (row['game_key'],Jsonb(grid),Jsonb(row['facts'].get('publication_dependencies',{}).get('selector')),blob_id,len(packet)))
        if scope is not None:
            retained=db.execute('SELECT facts FROM latest_board_status WHERE singleton=true').fetchone()
            if retained:
                prior=retained['facts'];scoped=set(scope)
                def outside(game):
                    members={hashed(member) for member in game['members']}
                    # Expired ingress no longer appears in any planned batch.
                    # Do not keep its orphan catalog entry forever merely
                    # because this pass belongs to a healthy neighboring game.
                    return bool(members.intersection(current['active_events'])) and not members.intersection(scoped)
                old_games=[g for g in prior['games'] if outside(g)]
                old_keys={g['game_key'] for g in old_games}
                status=dict(status,games=old_games+status['games'],
                    observation_errors=[e for e in prior.get('observation_errors',[]) if e['game_key'] in old_keys]+status.get('observation_errors',[]),
                    errors=[e for e in prior.get('errors',[]) if e['game_key'] in old_keys]+status.get('errors',[]),
                    catalog_errors=[e for e in prior.get('catalog_errors',[]) if outside(e)]+status.get('catalog_errors',[]))
                status['scope_complete']=not status['observation_errors'] and not status['catalog_errors']
                status['calculation_scope_complete']=not status.get('observation_only') and status['scope_complete'] and not status['errors']
        # Deletion requires a complete unchanged capture. A later newly admitted
        # game must never be erased by partial older work.
        if committed_marker==captured_marker:
            db.execute('DELETE FROM latest_board WHERE NOT(game_key=ANY(%s))',([g['game_key'] for g in status['games']],))
        else:
            # A resolved occurrence can replace an older source-local group
            # while unrelated ingress changes the global marker. Accepted local
            # proofs cover every old member before withdrawing that old group.
            covered={eid for row in accepted for eid in row['facts']['publication_dependencies']['selector']['events']}
            active=current['active_events']
            games={g['game_key'] for g in status['games']}
            captured_at=status.get('as_of')
            obsolete=db.execute("""SELECT game_key,publication_events members,
                observation_as_of as_of FROM latest_board""").fetchall()
            for old in obsolete:
                members=set(old['members'] or [])
                if (captured_at and old['game_key'] not in games and members and old['as_of'] and stamp(old['as_of'])<=stamp(captured_at)
                        and (members<=covered or not members.intersection(active))):
                    db.execute('DELETE FROM latest_board WHERE game_key=%s',(old['game_key'],))
        db.execute('DELETE FROM latest_dashboard d WHERE NOT EXISTS (SELECT 1 FROM latest_board b WHERE b.game_key=d.game_key)')
        if rejected:
            retained=db.execute('SELECT facts FROM latest_board_status WHERE singleton=true').fetchone()
            if retained:
                # Accepted replacements may just have retired older occurrence
                # rows. A rejection for a different game cannot resurrect those
                # deleted keys through the prior catalog merge.
                existing={r['game_key'] for r in db.execute('SELECT game_key FROM latest_board').fetchall()}
                unavailable={e['game_key'] for e in status.get('observation_errors',[])}
                games={g['game_key']:g for g in retained['facts']['games'] if g['game_key'] in existing|unavailable}
                games.update({g['game_key']:g for g in status['games'] if g['game_key'] in {r['game_key'] for r in accepted}})
                status=dict(status,games=list(games.values()))
        status=dict(status,games=[compact_catalog_game(g) for g in status['games']])
        db.execute('''INSERT INTO latest_board_status VALUES (true,%s,%s)
            ON CONFLICT(singleton) DO UPDATE SET facts=excluded.facts,updated_at=excluded.updated_at''',(Jsonb(status),utc()))
        from .pipeline_generation import outcome,retire_obsolete
        retire_obsolete(db,[g['game_key'] for g in status['games']],
            {eid for row in accepted for eid in row['facts']['publication_dependencies']['selector']['events']},
            current['active_events'],status.get('as_of'))
        for row in accepted:
            if row.get('_generation'):
                outcome(db,row['_generation'],published=True,facts=dict(
                    retained_financial_only=bool(row['facts'].get('retained_financial_only')),
                    validation_ms=diagnostics.get('validation_ms'),ingress_lock_wait_ms=diagnostics.get('ingress_lock_wait_ms'),
                    validated_at=utc(),
                    ingress_lock_held_ms=round((monotonic()-lock_started)*1000-diagnostics['ingress_lock_wait_ms'],3),
                    result_rows={view:len(row['facts']['boards'][view].get('rows',[])) for view in ('ev','arbs')}))
    # This statement follows transaction exit: an upper bound on commit
    # visibility, not the in-transaction publication marker or a lifetime.
    gids=[row['_generation'] for row in accepted if row.get('_generation')]
    if gids:
        db.execute("UPDATE pipeline_generation SET facts=facts || jsonb_build_object('commit_observed_at',clock_timestamp()) WHERE id=ANY(%s)",(gids,))
    # Compute diagnostic expansions from the sealed frames after releasing the
    # ingress lock. They cannot alter the accepted publication or its checks.
    from .pipeline_delivery import validation_witness
    for row in accepted:
        if row.get('_generation') and row.get('_validation_checks') is not None:
            proof=validation_witness(row['_captured_frame'],current,
                row['_validation_dependencies'],row['_validation_checks'])
            db.execute("UPDATE pipeline_generation SET facts=facts || %s WHERE id=%s",
                (Jsonb(dict(validation_witness=proof)),row['_generation']))
    return not rejected



def compact_catalog_game(original):
    """Store distinct navigation meanings; exact contract evidence stays in packets."""
    game=dict(original)
    if 'matches' in game:
        matches={}
        for match in game['matches']:
            meaning={k:v for k,v in match.items() if k!='revision'}
            matches.setdefault(encoded(meaning),meaning)
        game.update(matches=list(matches.values()),
                    match_count=game.get('match_count',len(game['matches'])))
    return game


@validation_scope()
def _reconcile(db, *, at=None, observations_only=False, event_ids=None, reservation_bytes=None, unit_priority=False, refresh_candidates=None):
    """Publish source frames even when optional discovery or finance fails."""
    at=at or utc();policy=load();started=monotonic();timings={};publication_trace={}
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        owner=runtime(db,at=at);source_binding=observation_binding();index=None
        committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
        if event_ids is not None:
            # New possible peers may arrive after planning. Expand and recheck
            # within this exact MVCC snapshot before decoding any contract.
            index=publication.identity_index(db)
            event_ids=sorted({*event_ids,*[r[0] for r in publication.neighborhood(index,
                dict(events=event_ids,occurrences=[],shared=[]))]})
            if reservation_bytes is not None and capture_reservation(db,observations_only=observations_only,event_ids=event_ids)>reservation_bytes:
                return dict(published=False,deferred=True,reason='background_capture_changed')
        captured_marker=marker(db,event_ids)
        publication_frame=publication.capture(db,source_states(committed,owner),
            selector=dict(events=event_ids,occurrences=[],shared=[]) if event_ids is not None else None,identity=index,compact='lazy')
        # The observation owner only needs prior dependency/clock proofs. It
        # never decodes the full optional boards which it deliberately retains.
        previous_query=('SELECT game_key,dependency_revision,economic_revision,calculated_at,'+SOURCE_PREVIOUS+' AS facts FROM latest_board'
            if observations_only else "SELECT game_key,dependency_revision,economic_revision,calculated_at,facts-'boards' AS facts,(facts->'boards')::text AS _boards_text FROM latest_board")
        if event_ids is not None:
            previous_query+=" WHERE publication_events ?| %s"
        previous={r['game_key']:r for r in db.execute(previous_query,(event_ids,) if event_ids is not None else None).fetchall()}
        prior=db.execute('SELECT facts FROM latest_board_status WHERE singleton=true').fetchone()
        dependency_checks_by_game={}
        if prior:
            facts=prior['facts']
            dependency_checks_by_game={key:publication.reasons(publication_frame,r['facts'].get('financial_dependencies',r['facts']['publication_dependencies']) if not observations_only else r['facts']['publication_dependencies'])
                for key,r in previous.items() if r['facts'].get('publication_dependencies')}
            dependency_checks=list(dependency_checks_by_game.values())
            covered_events={eid for row in previous.values() for eid in
                row['facts'].get('publication_dependencies',{}).get('selector',{}).get('events',[])}
            scoped_unchanged=((event_ids is None or set(event_ids)<=covered_events)
                and len(dependency_checks)==len(previous) and all(not (check['all'] or any(check['observations'].values())
                or any(check['comparisons'].values())) for check in dependency_checks)
                and all(r['facts'].get('observation_binding')==source_binding and r['facts'].get('selection_frame_available') for r in previous.values()))
            # Exact neighborhood/quote proofs above already bind every input.
            # The status row belongs to the most recently published component;
            # its marker must not force unchanged sibling games to hydrate again.
            unchanged=(bool(previous) and scoped_unchanged and all(
                r['facts'].get('publication_runtime')==runtime_identity(owner)
                and (observations_only or (
                    (r['facts'].get('context') or {}).get('policy_revision')==policy.revision
                    and (r['facts'].get('context') or {}).get('engine_binding')==engine_binding()
                    and r['facts'].get('estimate_availability',{}).get('state') in ('evaluated','partial','unavailable')
                    and r['facts'].get('calculation_error')!='background_estimates_pending'
                    and r['facts'].get('result_inventory_accounting',{}).get('complete_at_capture',False)))
                for r in previous.values()))
            if unchanged and not unit_priority and all(all(not r['facts'].get(k) or stamp(at)<stamp(r['facts'][k])
                    for k in (('observation_valid_until',) if observations_only else ('valid_until','observation_valid_until'))) for r in previous.values()):
                # Recording follows the read-only snapshot, so this fast path
                # remains a pure validation/reuse and never writes inside it.
                return dict(published=False,unchanged=True,computed=0,reused=len(previous),errors=[],
                    inventory_complete=all(r['facts'].get('result_inventory_accounting',{}).get('complete_at_capture',False) for r in previous.values()),
                    reused_generations=[r['facts']['generation_id'] for r in previous.values()
                        if not observations_only and r['facts'].get('generation_id')])
        context=read_context(db,at=at,owner=owner,event_ids=event_ids,tolerate_invalid_catalog=True)
        timings.update(getattr(context,'timings',{}))
        context.publication_runtime=runtime_identity(owner)
        context.result_owner=owner
        context.result_control=_control_barrier(db)
        publication_frame['control_barrier']=context.result_control
        context.publication_frame=publication_frame
        context.observation_binding=source_binding
        catalog=context.catalog();captured=[];source_errors=[];unchanged_observations=0;unchanged_estimates=0
        valid_games=list(catalog['games']);deferred_games=[]
        selected_game=None
        if unit_priority and not observations_only and valid_games:
            orders={r['game_key']:r['oldest'] for r in db.execute(
                'SELECT game_key,min(visit_order) oldest FROM current_result_work WHERE active GROUP BY game_key')}
            refresh_orders={}
            from .board_capture import refresh_priority
            for candidate in refresh_candidates or []:
                key=candidate['game_key'];rank=refresh_priority(candidate)
                refresh_orders[key]=min(refresh_orders.get(key,rank),rank)
            selected_game=min(valid_games,key=lambda g:(g['game_key'] not in refresh_orders,refresh_orders.get(g['game_key'],(True,0)),
                g['game_key'] not in orders,orders.get(g['game_key'],0),g['game_key']))['game_key']
        context.result_refresh_units={r['unit_id'] for r in refresh_candidates or [] if r['game_key']==selected_game}
        context.result_refresh_orders={r['unit_id']:refresh_priority(r) for r in refresh_candidates or [] if r['game_key']==selected_game}
        invalid_members={tuple(member) for error in context.catalog_errors for member in error['members']}
        valid_members={tuple(member) for game in valid_games for member in game['members']}
        # Keep a prior failed occurrence as an explicitly obsolete frame where
        # no new valid occurrence already covers its members. Never relabel it
        # with the new engine or silently rebind conflicting source facts.
        retained_invalid=[game for game in (prior['facts']['games'] if prior else [])
            if invalid_members.intersection(map(tuple,game['members'])) and not valid_members.intersection(map(tuple,game['members']))]
        catalog['games'].extend(retained_invalid)
        source_errors.extend(dict(game_key=game['game_key'],reason='observation_invalid') for game in retained_invalid)
        for game in valid_games:
            checkpoint()
            if selected_game is not None and game['game_key']!=selected_game:
                deferred_games.append(game['game_key'])
                continue
            old=previous.get(game['game_key']);checks=dependency_checks_by_game.get(game['game_key'])
            deadline=old['facts'].get('observation_valid_until') if old else None
            if (observations_only and old and checks and old['facts'].get('selection_frame_available') and old['facts'].get('observation_binding')==source_binding
                    and not (checks['all'] or any(checks['observations'].values()) or any(checks['comparisons'].values()))
                    and (not deadline or stamp(at)<stamp(deadline))):
                # Validate the exact committed proof before expensive hydration
                # and serialization. Quiet retained games must not delay a live
                # changed pair behind rebuilding the entire historical slate.
                unchanged_observations+=1
                continue
            if (not observations_only and not unit_priority and old and checks and prior
                    and old['facts'].get('publication_runtime')==runtime_identity(owner)
                    and (old['facts'].get('context') or {}).get('engine_binding')==context.engine
                    and (old['facts'].get('context') or {}).get('policy_revision')==policy.revision
                    and not old['facts'].get('calculation_error')
                    and old['facts'].get('estimate_availability',{}).get('state') in ('evaluated','partial','unavailable')
                    and old['facts'].get('result_inventory_accounting',{}).get('complete_at_capture',False)
                    and old['facts'].get('selection_frame_available') and old['facts'].get('observation_binding')==source_binding
                    and not (checks['all'] or any(checks['observations'].values()) or any(checks['comparisons'].values()))
                    and all(not old['facts'].get(k) or stamp(at)<stamp(old['facts'][k])
                        for k in ('valid_until','observation_valid_until'))):
                # Exact dependency and temporal proofs precede normalization.
                # An unrelated changing game must not make every quiet game
                # rebuild its profiles before pending work gets a turn.
                unchanged_estimates+=1
                continue
            try:
                observed=context.observation_bundles(game=game['game_key'],benchmark_venue=policy.benchmark_venue)[0]
            except (KeyError,ValueError,TypeError,IndexError):
                source_errors.append(dict(game_key=game['game_key'],reason='observation_invalid'));continue
            captured.append((game,observed))
        # Detach the selected ladders in the same snapshot as their source facts.
        # Later optional work therefore performs no database hydration after the
        # source publication's commit.
        by_member={tuple(member):observed['records'] for game,observed in captured for member in game['members']}
        context.prepared['groups']=[by_member.get((rows[0]['quote']['source']['provider'],rows[0]['quote']['source']['native_event_id']),rows)
                                    for rows in context.prepared['groups']]
    def status_for(errors,computed=0,reused=0,observation_only=False):
        return dict(version='predict-latest-board-3',input_marker=captured_marker,epoch=context.epoch,
            engine_binding=context.engine,observation_binding=source_binding,policy=policy.to_dict(),runtime=runtime_identity(owner),
            capture_events=event_ids,capture_membership=hashed(publication.neighborhood(publication_frame,
                dict(events=event_ids,occurrences=[],shared=[]))) if event_ids is not None else None,games=catalog['games'],errors=errors,observation_errors=source_errors,catalog_errors=context.catalog_errors,as_of=at,
            scope_complete=not source_errors and not context.catalog_errors,calculation_scope_complete=not observation_only and not deferred_games and not errors and not source_errors and not context.catalog_errors,
            observation_only=observation_only,maximum_games=len(catalog['games']),maximum_bytes=MAX_BYTES,computed=computed,reused=reused,provider_requests=0)
    observations=[];rendered=[]
    for game,observed in captured:
        checkpoint()
        if not observations_only:
            # The completed financial payload renders the same source board.
            # Rendering a discarded pending payload doubles work after capture.
            rendered.append((game,observed))
            continue
        old=previous.get(game['game_key']);checks=dependency_checks_by_game.get(game['game_key'])
        deadline=old['facts'].get('observation_valid_until') if old else None
        if (old and checks and old['facts'].get('selection_frame_available') and old['facts'].get('observation_binding')==source_binding
                and not (checks['all'] or any(checks['observations'].values()) or any(checks['comparisons'].values()))
                and (not deadline or stamp(at)<stamp(deadline))):
            rendered.append((game,observed))
            continue
        try:facts=_selection_payload(observed,None,None,policy,context,'background_estimates_pending')
        except ValueError as exc:
            # Only this bounded projection refusal is local to one game. SQL,
            # process/deadline guards and cancellation must still abort work.
            if str(exc)!='board_compact_response_capacity':raise
            source_errors.append(dict(game_key=game['game_key'],reason=str(exc)))
            continue
        rendered.append((game,observed))
        old=previous.get(game['game_key'])
        deadline=old['facts'].get('observation_valid_until') if old else None
        if old and old['facts'].get('selection_frame_available') and old['facts'].get('observation_binding')==source_binding and old['facts'].get('publication_dependencies')==facts['publication_dependencies'] and (not deadline or stamp(at)<stamp(deadline)):
            # Keep an already evaluated optional board while independent unchanged
            # source observations remain valid. No estimate claim is renewed.
            continue
        observations.append(dict(game_key=game['game_key'],dependency_revision=observed['input_version'],
            economic_revision=hashed(['source',facts['observation_context']]),calculated_at=None,facts=facts))
    captured=rendered
    timings['capture_normalize_render_ms']=round((monotonic()-started)*1000,3)
    publish_started=monotonic()
    membership_changed=set(previous)!={game['game_key'] for game in catalog['games']}
    if observations_only and (observations or source_errors or membership_changed):
        observed_published=publish(db,captured_marker=captured_marker,captured_runtime=owner,
            status=status_for([],observation_only=True),rows=observations,diagnostics=publication_trace)
    else:observed_published=False
    # The financial pass publishes these same observations with its completed
    # result (including explicit failures) below. Publishing a pending copy here
    # duplicated projection, validation and ingress-lock occupancy. Independent
    # source turns still publish without waiting for financial work.
    timings['observation_publish_ms']=round((monotonic()-publish_started)*1000,3)
    calculation_started=monotonic()
    if observations_only:
        return dict(published=observed_published,computed=0,reused=unchanged_observations+len(captured)-len(observations),errors=source_errors,
            reason=publication_trace.get('failure'),timings=timings,publication_trace=publication_trace)
    rows=[];errors=[];computed=0;reused=unchanged_estimates
    for game,observed in captured:
        checkpoint()
        bundle=None;identity=None;error=None;discovery_failure=None
        discovery_started=monotonic()
        try:
            from .discovery_index import prepare
            bundle=prepare(context,game['game_key'],policy,observed)
            identity=context_identity(bundle,policy,context)
        except (CalculationStopped,MemoryError,OSError):raise
        except Exception as exc:
            failure(__name__, 'latest_board_inputs', exc)
            from app.diagnostics import failure_details
            discovery_failure=failure_details(exc)
            bundle=None;error='calculation_inputs_unavailable'
        discovery_elapsed_ms=round((monotonic()-discovery_started)*1000,3)
        context.result_discovery_ms=(bundle or {}).get('_discovery_timings',{}).get('full_discovery_ms',discovery_elapsed_ms)
        timings['discovery_prepare_ms']=round(timings.get('discovery_prepare_ms',0)+discovery_elapsed_ms,3)
        timings['full_discovery_ms']=round(timings.get('full_discovery_ms',0)+context.result_discovery_ms,3)
        economic=hashed(dict(context=identity,observation=observation_identity(observed,context),
            policy=policy.revision,config=owner.get('config',{}),active=owner.get('active',False),error=error))
        from .pipeline_generation import admit,completed,outcome
        from app.dashboard.comparison_board import freshness,quote_key
        dependencies=publication.manifest(context.publication_frame,observed)
        if bundle:publication.bind_references(context.publication_frame,dependencies,bundle)
        applicability=[(quote_key(q),q.get('comparison_input_refs'),
            freshness(q,bundle['state_inputs']['comparison_profiles'],event,stamp(at))['reasons'])
            for event,_,q in entries(bundle['state_inputs'])] if bundle else [error]
        from .pipeline_delivery import witness
        generation=admit(db,game['game_key'],dependencies,context.engine,policy.revision,applicability,
            trace=witness(context.publication_frame,dependencies,at,utc()))
        old=previous.get(game['game_key'])
        if not unit_priority and old and old['facts'].get('selection_frame_available') and old['facts'].get('observation_binding')==source_binding and old['economic_revision']==economic and old['facts'].get('calculation_error')!='background_estimates_pending' and old['facts'].get('estimate_availability',{}).get('state')!='pending' and (old['facts'].get('calculation_error') or old['facts'].get('result_inventory_accounting',{}).get('complete_at_capture',False)):
            # Refresh only conservative temporal metadata. Unchanged economics
            # and source frames keep their original calculation/publication time.
            import json
            old['facts']['boards']=json.loads(old.pop('_boards_text'))
            retained=dict(old,facts=dict(old['facts'],valid_until=next_boundary(bundle,context.at) if bundle else None,
                observation_valid_until=observation_boundary(observed,context.at)))
            retained['_generation']=generation
            completed(db,generation,reused=True)
            rows.append(retained);reused+=1;continue
        value=None
        if bundle is not None:
            try:
                from .result_publication import calculate as calculate_units
                facts=calculate_units(db,observed,bundle,policy,context,calculator=calculate_current)
                value=dict(calculated_at=utc())
                # Compact financial rendering is optional too; malformed model
                # decoration cannot cancel the independent source frame.
                computed+=1
                completed(db,generation)
            except (CalculationStopped,MemoryError,OSError):raise
            except Exception as exc:
                failure(__name__, 'latest_board_calculation', exc)
                error='calculation_failed';value=None
        if value is None:
            error=error or 'calculation_inputs_unavailable'
            facts=_selection_payload(observed,None,None,policy,context,error)
        if discovery_failure is not None:
            facts['discovery_failure']=dict(stage='discovery_index',failure=discovery_failure,
                elapsed_ms=context.result_discovery_ms,inventory='unknown')
        if error:errors.append(dict(game_key=game['game_key'],reason=error))
        facts['generation_id']=generation
        rows.append(dict(_generation=generation,_captured_frame=context.publication_frame,game_key=game['game_key'],dependency_revision=observed['input_version'],
            economic_revision=economic,calculated_at=None if value is None else value['calculated_at'],facts=facts))
    status=status_for(errors,computed,reused)
    timings['calculation_render_ms']=round((monotonic()-calculation_started)*1000,3)
    publish_started=monotonic();publication_trace={}
    published=publish(db,captured_marker=captured_marker,captured_runtime=owner,status=status,rows=rows,diagnostics=publication_trace)
    for row in rows:
        if row.get('_generation') and row['game_key'] not in publication_trace.get('accepted_game_keys',[]):
            outcome(db,row['_generation'],published=False,reason=publication_trace.get('failure') or 'row_dependencies_or_newer_publication',facts=publication_trace)
    timings['financial_publish_ms']=round((monotonic()-publish_started)*1000,3)
    return dict(published=published,computed=computed,reused=reused,errors=errors+source_errors,
        unit_visits=sum(len(r['facts'].get('result_unit_attempts',[])) for r in rows),
        deferred_game_keys=deferred_games,
        inventory_complete=bool(rows) and not deferred_games and not errors and not source_errors and not context.catalog_errors and all(row['facts'].get('result_inventory_accounting',{}).get('complete_at_capture',False) for row in rows),
        reason=publication_trace.get('failure'),timings=timings,publication_trace=publication_trace)


def reconcile(db, *, at=None, observations_only=False, admission=None, turn_seconds=20, progress=None):
    """Incremental SQL → compact board publication with per-neighborhood leases."""
    from app.collection.background_work import BACKGROUND
    from contextlib import ExitStack, nullcontext
    turn_started=monotonic()
    kind='observations' if observations_only else 'estimates'
    if not observations_only and BACKGROUND.acquisition_pressure():raise AcquisitionDeferred('native_acquisition_catching_up')
    planning=capture_reservation(db,observations_only=True,event_ids=[])
    with ExitStack() as planning_owner:
        lease=planning_owner.enter_context(BACKGROUND.claim(kind,planning,source=observations_only))
        if not lease:
            if admission is not None:admission[kind]=dict(state='deferred',reason=lease.reason,
                reserved_bytes=planning,resident_bytes=lease.resident_bytes)
            return lease.deferred()
        with db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            batches=capture_batches(db)
            # Withdrawn events must also retire their obsolete publications, even
            # when no offering remains to seed a neighborhood.
            active={eid for batch in batches for eid in batch}
            saved=db.execute("SELECT publication_events members FROM latest_board").fetchall()
            retired=sorted({eid for row in saved if not active.intersection(row['members'] or []) for eid in row['members'] or []})
            if retired:batches.append(retired)
        # Publish each complete matching component independently for both
        # observations and estimates. Packing unrelated games made a resumed
        # financial turn redo all their hydration before its first publication.
        # Full peer membership and the measured memory reservation stay intact.
        from .pipeline_attempt import enqueue
        enqueue(db,sorted(active),observations_only=observations_only)
        batches=batches or [None]
        cursor=0
        anchor=(admission or {}).get(kind+'_rotation_after')
        if anchor is not None:
            cursor=next((i for i,ids in enumerate(batches) if ids and min(ids)>anchor),0)
        deadline=monotonic()+(5 if observations_only else min(60,max(1,turn_seconds))) if admission is not None else None
        rotation=batches
        rotation_cursor=cursor
        batches=batches[cursor:]+batches[:cursor]
        if not observations_only and admission is None:
            from .board_capture import prioritize_unpublished
            batches=prioritize_unpublished(db,prioritize_pending(db,batches),at or utc())
        if observations_only and admission is not None:
            # A hot component can consume the entire five-second turn. Give
            # ordinary rotation every other turn so quiet corrected schedules
            # and removed routes cannot remain behind continuously ticking books.
            admission['observations_priority_turn']=not admission.get('observations_priority_turn',False)
        window_priority=False
        if admission is not None:
            admission[kind+'_window_turn']=int(admission.get(kind+'_window_turn',0))+1
            window_priority=bool(admission[kind+'_window_turn']%4)
            if window_priority:
                from .board_capture import prioritize_window_waiters
                batches=prioritize_window_waiters(db,batches,at or utc(),observations_only=observations_only)
                if not observations_only and admission[kind+'_window_turn']%4 in (2,3):
                    from .board_capture import prioritize_unit_waiters
                    batches=prioritize_unit_waiters(db,batches,at or utc())
        if observations_only and admission is not None and admission.get('observations_priority_turn'):
            # Apply hot-source precedence last: every hot turn is also a window
            # turn, whose age sort previously erased this priority entirely.
            # Even turns still service oldest attempts and ordinary rotation.
            from .board_capture import prioritize_unpublished
            batches=prioritize_unpublished(db,batches,at or utc())
            batches=prioritize_sources(db,batches,at or utc())
        refresh_candidates=[]
        if not observations_only and admission is not None and admission[kind+'_window_turn']%4==1:
            from .board_capture import refresh_waiters
            refresh_candidates=refresh_waiters(db,at or utc(),engine=engine_binding(),runtime_id=runtime(db,at=at or utc()).get('runtime_id'),enqueue=True)
        result=dict(published=False,unchanged=True,computed=0,reused=0,errors=[],batches=[],provider_requests=0,
            refresh_candidates=len(refresh_candidates),refresh_visits=0,unit_visits=0,no_progress_parent_yields=0,
            setup_seconds=monotonic()-turn_started)
        # Yield only between complete neighborhoods. The live owner resumes
        # after a stable event anchor, so repacking or a changing early game
        # cannot repeatedly restart the queue ahead of independent contexts.
        owns_planning=True
        unit_priority=not observations_only and admission is not None and admission[kind+'_window_turn']%4 in (2,3)
        # A large parent must not wait for an entire event cycle after each
        # bounded unit slice. Re-evaluate global durable order between slices.
        queue=list(batches);batch_index=-1
        while queue:
            batch_index+=1
            if unit_priority:
                from .board_capture import prioritize_unit_waiters
                queue=prioritize_unit_waiters(db,queue,at or utc())
            elif refresh_candidates:
                from .board_capture import prioritize_refresh_waiters
                queue=prioritize_refresh_waiters(queue,refresh_candidates)
            ids=queue.pop(0)
            refreshing=[r for r in refresh_candidates if set(r['events']).intersection(ids or [])]
            checkpoint()
            required=capture_reservation(db,observations_only=observations_only,event_ids=ids)
            first_owned=owns_planning
            if first_owned:
                try:BACKGROUND.resize(kind,required)
                except ValueError as exc:
                    if str(exc) not in ('background_memory_capacity','background_source_capacity'):raise
                    planning_owner.close();first_owned=False;owns_planning=False
            with (nullcontext(lease) if first_owned else BACKGROUND.claim(kind,required,source=observations_only)) as lease:
                state=dict(state='admitted' if lease else 'deferred',reason=lease.reason,
                    reserved_bytes=required,resident_bytes=lease.resident_bytes,events=len(ids or []))
                if admission is not None:admission[kind]=state
                result['batches'].append(state)
                if not lease:
                    result['unchanged']=False
                    result['errors'].append(dict(reason=lease.reason,events=ids))
                    if lease.reason in ('background_work_busy','background_work_turn','native_acquisition_catching_up'):
                        # A shared scheduling refusal says nothing about this
                        # component. Resume here after the other owner runs;
                        # advancing across all refused components resets the
                        # cursor to the first game on every turn.
                        result.update(yielded=True,remaining_batches=len(queue)+1)
                        break
                    continue
                attempt_started=monotonic()
                from .pipeline_attempt import record as record_attempt, scheduled
                from .board_capture import unit_waiter_head
                prior_head=unit_waiter_head(db,ids,at or utc()) if unit_priority else None
                scheduled(db,ids,observations_only=observations_only)
                try:batch=_reconcile(db,at=at,observations_only=observations_only,event_ids=ids,reservation_bytes=required,unit_priority=unit_priority or bool(refreshing),refresh_candidates=refreshing)
                except (LockNotAvailable,SerializationFailure,DeadlockDetected) as exc:
                    # This transaction has rolled back. Keep the component dirty,
                    # record its retry, and rotate so one contested publication
                    # cannot restart every worker turn at the same game.
                    reason='attempt_'+type(exc).__name__
                    state.update(state='retry',reason=reason)
                    batch=dict(published=False,unchanged=False,computed=0,reused=0,
                        reason=reason,errors=[dict(reason=reason,events=ids)])
                except Exception as exc:
                    record_attempt(db,ids,observations_only=observations_only,elapsed=monotonic()-attempt_started,
                        result=dict(reason='attempt_'+type(exc).__name__))
                    raise
                record_attempt(db,ids,observations_only=observations_only,
                    elapsed=monotonic()-attempt_started,result=batch)
                if (admission is not None
                        and not (observations_only and admission.get('observations_priority_turn'))):
                    # Component-local deferral (for example membership expanding
                    # beyond its reservation) consumed this scheduling turn too.
                    # Rotate past it so it cannot pin the ordinary cursor. Shared
                    # lane refusals break above, before any component is attempted.
                    # Hot-source turns must not move the ordinary rotation's
                    # anchor back to the same constantly changing event.
                    admission[kind+'_cursor']=(cursor+batch_index+1)%len(batches)
                    if ids:admission[kind+'_after']=min(ids)
                    # Priority turns have their own ordering and cannot move
                    # the ordinary rotation past quiet components indefinitely.
                    if ids and (not window_priority or ids==rotation[rotation_cursor]):
                        admission[kind+'_rotation_after']=min(ids)
                        rotation_cursor=(rotation_cursor+1)%len(rotation)
                    if progress is not None:progress(admission)
                if batch.get('deferred'):
                    state.update(state='deferred',reason=batch['reason'])
                    result['errors'].append(dict(reason=batch['reason'],events=ids))
                result['published']|=batch.get('published',False)
                result['unchanged']&=batch.get('unchanged',False)
                for key in ('computed','reused'):result[key]+=batch.get(key,0)
                result['unit_visits']+=batch.get('unit_visits',0)
                result['errors'].extend(batch.get('errors',[]))
                visited=set()
                if refreshing:
                    current_orders={(r['game_key'],r['unit_id']):r['visit_order'] for r in db.execute(
                        'SELECT game_key,unit_id,visit_order FROM current_result_work WHERE game_key=ANY(%s)',
                        (list({r['game_key'] for r in refreshing}),))}
                    visited={(r['game_key'],r['unit_id']) for r in refreshing
                        if current_orders.get((r['game_key'],r['unit_id']))!=r['visit_order']}
                    result['refresh_visits']+=len(visited)
                    refresh_candidates=[r for r in refresh_candidates if (r['game_key'],r['unit_id']) not in visited]
                remains=any(set(r['events']).intersection(ids or []) for r in refresh_candidates)
                next_head=unit_waiter_head(db,ids,at or utc()) if unit_priority else None
                unit_advanced=unit_priority and next_head is not None and next_head!=prior_head
                # Retained membership can still rank a parent even when the
                # current catalog cannot select that old unit. Visiting newer
                # siblings is not progress on that waiter. Do not spend the
                # entire turn re-adding the same parent in that case; retain
                # its durable position and retry on the next ordinary turn.
                repeat_parent=unit_advanced or (refreshing and remains and visited)
                if batch.get('computed') and not repeat_parent and ((unit_priority and prior_head==next_head and prior_head is not None) or (refreshing and remains)):
                    result['no_progress_parent_yields']+=1
                if repeat_parent and batch.get('computed') and not batch.get('deferred'):
                    queue.append(ids)
                if deadline is not None and monotonic()>=deadline:
                    result.update(yielded=True,remaining_batches=len(queue))
                    break

        if result['batches'] and all(b['state']=='deferred' for b in result['batches']):
            result.update(deferred=True,reason=result['batches'][0]['reason'])
        result['turn_seconds']=monotonic()-turn_started
        return result


class LatestBoardOwner:
    """Runtime-owned polling; page access never starts or wakes this owner."""
    def __init__(self,service):
        self.service=service;self.closed=False;self.task=None;self.estimate_task=None;self.wake=asyncio.Event();self.last=None;self.error=None
        self.observation_error=None;self.estimate_error=None
        self.progress={}
        self.coverage_task=None;self.coverage_error=None;self.last_coverage=None
        self.admission_status={}
        self.auxiliary_lock=asyncio.Lock()
        self.connections=set();self.connection_lock=RLock();self.drain_task=None
    @contextmanager
    def connection(self):
        # Cooperative Python checkpoints cannot interrupt a blocking SQL query.
        # Keep its connection owned so shutdown can cancel the server operation.
        with connect() as db:
            with self.connection_lock:self.connections.add(db)
            class WorkerConnection:
                def execute(self,*args,**kwargs):
                    checkpoint()
                    return db.execute(*args,**kwargs)
                def __getattr__(self,name):return getattr(db,name)
            try:
                checkpoint()
                yield WorkerConnection()
            finally:
                with self.connection_lock:self.connections.discard(db)
    def cancel_queries(self):
        with self.connection_lock:connections=list(self.connections)
        for db in connections:
            try:db.cancel_safe(timeout=1)
            except Exception as exc:failure(__name__,'latest_board_query_cancel',exc)
    async def start(self):
        self.task=asyncio.create_task(self.run(observations_only=True),name='predict-latest-observation-owner')
        self.estimate_task=asyncio.create_task(self.run(observations_only=False),name='predict-latest-estimate-owner')
        self.coverage_task=asyncio.create_task(self.run_coverage(),name='predict-coverage-owner')
    def coverage_tick(self):
        from app.collection.background_work import BACKGROUND
        if self.closed:return self._coverage_tick()
        return BACKGROUND.requested('coverage',self._coverage_tick)
    def _coverage_tick(self):
        from .coverage_latest import reconcile as reconcile_coverage, LOCK as COVERAGE_LOCK
        with cancellation(lambda:optional_cancelled(self.closed)),self.connection() as db:
            if not db.execute('SELECT pg_try_advisory_lock(%s) AS owned',(COVERAGE_LOCK+1,)).fetchone()['owned']:
                return dict(published=False,reason='another_coverage_owner')
            try:return reconcile_coverage(db)
            finally:db.execute('SELECT pg_advisory_unlock(%s)',(COVERAGE_LOCK+1,))
    async def run_coverage(self):
        from app.collection.background_work import optional_thread
        while not self.closed:
            try:
                from app.collection.coverage_worker import run as coverage_process,MAX_PROCESS_BYTES
                if getattr(self.service,'config',{}).get('rss_bytes',0)>MAX_PROCESS_BYTES:
                    from app.collection.background_work import BACKGROUND
                    if BACKGROUND.acquisition_pressure():raise AcquisitionDeferred('native_acquisition_catching_up')
                    async with self.auxiliary_lock:
                        self.last_coverage=await coverage_process(lambda:self.closed,root=ROOT,wait_for_admission=False)
                else:
                    self.last_coverage=await optional_thread(self.coverage_tick)
                self.coverage_error=None
            except AcquisitionDeferred:
                self.last_coverage=dict(deferred=True,reason='native_acquisition_catching_up')
                # Admission has done no work. Retry outside the shared child
                # lane so an idle census cannot hold financial work for 180s.
                await asyncio.sleep(2)
                continue
            except CalculationStopped:
                if self.closed:return
                raise
            except Exception as exc:
                if self.closed:return
                failure(__name__, 'latest_board_coverage', exc)
                self.coverage_error='background_coverage_unavailable'
            # Independent low-frequency metrics cannot delay source frames or
            # optional estimate publication. Reads never wake this worker.
            # Full-scope Coverage is an expensive census. Leave the auxiliary
            # lane available for financial components between census captures.
            for _ in range(240):
                if self.closed:break
                await asyncio.sleep(.5)
    def tick(self, *, observations_only=False):
        from app.collection.background_work import BACKGROUND
        def run():
            with cancellation(lambda:self.closed if observations_only else optional_cancelled(self.closed)):
                return self._tick(observations_only=observations_only)
        if observations_only or self.closed:return run()
        return BACKGROUND.requested('estimates',run)
    def _tick(self, *, observations_only=False):
        lock=LOCK+1 if observations_only else LOCK
        with self.connection() as db:
            if not db.execute('SELECT pg_try_advisory_lock(%s) AS owned',(lock,)).fetchone()['owned']:return dict(published=False,reason='another_board_owner')
            try:
                return reconcile(db,observations_only=observations_only,admission=self.admission_status)
            finally:db.execute('SELECT pg_advisory_unlock(%s)',(lock,))
    async def run(self, *, observations_only=False):
        from app.collection.background_work import optional_thread,source_thread
        while not self.closed:
            error=None
            try:
                runner=source_thread if observations_only else optional_thread
                from app.collection.coverage_worker import run as auxiliary_process,MAX_PROCESS_BYTES
                if not observations_only and getattr(self.service,'config',{}).get('rss_bytes',0)>MAX_PROCESS_BYTES:
                    import json
                    async with self.auxiliary_lock:
                        self.last=await auxiliary_process(lambda:self.closed,root=ROOT,module='app.collection.financial_worker',
                            arguments=(json.dumps({k:v for k,v in self.admission_status.items() if k.startswith('estimates')}),),
                            on_progress=self.admission_status.update)
                    self.admission_status.update(self.last.pop('worker_admission',{}))
                else:self.last=await runner(self.tick,observations_only=observations_only)
                self.progress['observations' if observations_only else 'estimates']=dict(
                    at=utc(),**{key:self.last.get(key) for key in ('published','unchanged','computed','reused','deferred','reason','unit_visits','no_progress_parent_yields','setup_seconds','turn_seconds','worker_seconds','worker_paused_seconds')},
                    errors=len(self.last.get('errors',[])),batches=len(self.last.get('batches',[])))
            except AcquisitionDeferred:
                self.last=dict(deferred=True,reason='native_acquisition_catching_up')
                self.progress['observations' if observations_only else 'estimates']=dict(
                    at=utc(),published=False,computed=0,reused=0,deferred=True,
                    reason='native_acquisition_catching_up',errors=0,batches=0)
            except (LockNotAvailable, SerializationFailure, DeadlockDetected):
                # Expected concurrent ingress/publication contention is a retry,
                # not loss of source authority. Preserve the component cursor
                # and the captured read's authority while the owner retries.
                self.last=dict(published=False,deferred=True,reason='publication_retry')
                self.progress['observations' if observations_only else 'estimates']=dict(
                    at=utc(),**self.last,computed=0,reused=0,errors=0,batches=0)
            except CalculationStopped:
                if self.closed:return
                raise
            except Exception as exc:
                if self.closed:return
                failure(__name__, 'latest_board_reconciliation', exc)
                error=type(exc).__name__+': latest_board_reconciliation_failed'
            if observations_only:self.observation_error=error
            else:self.estimate_error=error
            self.error=self.observation_error or self.estimate_error
            try:await asyncio.wait_for(self.wake.wait(),timeout=2)
            except TimeoutError:pass
            self.wake.clear()
    async def close(self):
        self.closed=True;self.wake.set()
        from app.collection.background_work import BACKGROUND
        for kind in ('observations','estimates','coverage'):BACKGROUND.cancel(kind)
        tasks=[task for task in (self.task,self.estimate_task,self.coverage_task) if task]
        if tasks:
            async def drain():
                pending=set(tasks)
                while pending:
                    # A streamed cursor may start its next query just after a
                    # cancellation found the connection idle. Keep cancelling
                    # until every owned worker finishes; never detach its thread.
                    await asyncio.to_thread(self.cancel_queries)
                    _,pending=await asyncio.wait(pending,timeout=.05)
                results=await asyncio.gather(*tasks,return_exceptions=True)
                for result in results:
                    if isinstance(result,BaseException):raise result
            if self.drain_task is None:
                self.drain_task=asyncio.create_task(drain())
                self.drain_task.add_done_callback(lambda task:None if task.cancelled() else task.exception())
            # A timed-out caller cannot detach a live SQL thread from its owner.
            await asyncio.wait_for(asyncio.shield(self.drain_task),timeout=self.service.config['cleanup_seconds'])


def _read_mark(name, started):
    from app.dashboard.read_work import TRACE
    trace=TRACE.get()
    if trace:trace.mark(name,started)
    return monotonic()


def snapshot(db, *, at=None, resource_guard=None, game=None, view=None, serialized_boards=False, dashboard=False, window_hours=None):
    """Detached compact database frame; no normalization or financial owner."""
    timed=monotonic()
    if view is not None and view not in ('odds','ev','arbs'):raise ValueError('Unsupported board view')
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        scoped_selector=None;scoped_ids=None;window_keys=None;identity=None
        if window_hours is not None:
            if not serialized_boards or view!='odds' or window_hours!=72:raise ValueError('unsupported_grid_window')
            # Establish one MVCC snapshot and its rolling clock before choosing
            # games. Acquisition/retention scope remains entirely independent.
            catalog_row=db.execute('SELECT facts FROM latest_board_status WHERE singleton=true').fetchone()
            at=at or utc()
            from .dashboard_results import in_window
            window_games=[g for g in (catalog_row['facts']['games'] if catalog_row else [])
                if in_window(g,stamp(at),stamp(at)+timedelta(hours=72))]
            window_keys=[g['game_key'] for g in window_games]
            members={hashed(member) for g in window_games for member in g['members']}
            scoped_selector=dict(events=sorted(members),occurrences=[],shared=[])
            index=publication.identity_index(db)
            scoped_ids=[row[0] for row in publication.neighborhood(index,scoped_selector)]
            identity=index
        if game and not serialized_boards:
            manifest=db.execute("SELECT facts#>'{publication_dependencies,selector}' selector FROM latest_board WHERE game_key=%s",(game,)).fetchone()
            scoped_selector=manifest['selector'] if manifest else None
            if game=='__catalog_only__':scoped_selector=dict(events=[],occurrences=[],shared=[])
            if scoped_selector is not None:
                # Matching still considers every event identity, including new
                # peers. Only its complete selected neighborhood loads contracts.
                if resource_guard is not None:
                    index_bytes=db.execute('SELECT COALESCE(sum(octet_length(facts::text)),0) n FROM current_event').fetchone()['n']
                    resource_guard(int(index_bytes)*8)
                index=publication.identity_index(db)
                scoped_ids=[row[0] for row in publication.neighborhood(index,scoped_selector)]
                del index
        if dashboard and resource_guard is not None:
            resource_guard(db.execute('SELECT COALESCE(sum(octet_length(facts::text)),0)*8 n FROM latest_dashboard WHERE (%s::text IS NULL OR game_key=%s)',(game,game)).fetchone()['n'])
        timed=_read_mark('snapshot_window',timed)
        if resource_guard is not None and not dashboard:
            # Check the committed logical JSON size before decoding the full
            # frame. Measure the same selected-view projection decoded below;
            # other views remain in SQL. Keep the conservative 8x allowance.
            if serialized_boards:
                sizes=db.execute("""SELECT COALESCE(max(octet_length(current_result_read_facts(b.facts,%s)::text)),0) largest_metadata,
                    COALESCE(max(CASE WHEN %s='odds' THEN COALESCE(g.retained_bytes,b.retained_bytes) ELSE octet_length((b.facts->'boards'->%s)::text) END),0) largest
                    FROM latest_board b LEFT JOIN current_grid_projection g USING(game_key)
                    WHERE (%s::text[] IS NULL OR game_key=ANY(%s))""",(view,view,view,window_keys,window_keys)).fetchone()
                other=db.execute('''SELECT COALESCE(sum(n),0) n FROM (
                    SELECT octet_length(facts::text) n FROM current_event
                    UNION ALL SELECT octet_length(ROW(c.id,c.event_id,c.venue,c.native_market_id,c.native_outcome_id,
                        c.native_side,c.revision,c.contract_dependency,c.metric_dependency)::text) FROM current_contract c
                    UNION ALL SELECT octet_length(facts::text) FROM latest_board_status) t''').fetchone()['n']
                contract_batch=db.execute('SELECT COALESCE(max(facts_bytes),0) AS n FROM current_contract').fetchone()['n']
                # Keep every board as text, hydrate only one at a time. Account
                # for libpq/text copies plus that one decoded working graph.
                resource_guard((int(other)+int(contract_batch))*8+
                               64*1024*1024+
                               (int(sizes['largest'])+int(sizes['largest_metadata']))*8)
            else:
                size=db.execute('''SELECT COALESCE(sum(n),0) AS byte_count FROM (
                    SELECT octet_length((CASE WHEN %s::text IS NULL THEN facts ELSE
                        (facts - 'boards') || jsonb_build_object('boards',jsonb_build_object(%s::text,facts->'boards'->%s::text))
                        END)::text) AS n FROM latest_board WHERE (%s::text IS NULL OR game_key=%s)
                    UNION ALL SELECT octet_length(facts::text) FROM current_event
                    UNION ALL SELECT octet_length(facts::text) FROM current_contract WHERE (%s::text[] IS NULL OR event_id=ANY(%s))
                    UNION ALL SELECT octet_length(facts::text) FROM latest_board_status
                ) retained''',(view,view,view,game,game,scoped_ids,scoped_ids)).fetchone()['byte_count']
                resource_guard(int(size)*8)
        timed=_read_mark('snapshot_preflight',timed)
        saved=db.execute('SELECT facts FROM latest_board_status WHERE singleton=true').fetchone()
        # Establish the MVCC snapshot before choosing its read clock. A runtime
        # heartbeat committed between function entry and that first SQL query
        # is healthy, rather than a future heartbeat relative to an early clock.
        at=at or utc()
        status=saved['facts'] if saved else dict(games=[],errors=[],epoch=db.execute('SELECT epoch FROM current_row_epoch WHERE singleton=true').fetchone()['epoch'],policy=load().to_dict())
        if window_keys is not None:
            status=dict(status,games=window_games)
        owner=runtime(db,at=at)
        # Serialized pages already capture the complete immutable dependency
        # proof below. A second scan of all offer/book identities contributes
        # no extra authority and delays the first useful page.
        current=None if serialized_boards else marker(db,scoped_ids)
        from .native_authority import capture as native_authority
        # Native stream proof is consumed only by financial benchmark aging.
        # Price-grid freshness uses its own committed observation dependencies.
        native_proof={} if view=='odds' or game=='__catalog_only__' else native_authority(db,owner)
        if serialized_boards:
            # A client cursor retains the entire libpq result alongside decoded
            # strings. Stream complete rows from the same MVCC snapshot instead.
            with db.cursor(name='predict_slate_boards') as cursor:
                cursor.itersize=8
                cursor.execute("""SELECT b.game_key,b.dependency_revision,b.economic_revision,b.calculated_at,
                    g.blob_id AS _blob_id,CASE WHEN %s='odds' AND g.blob_id IS NULL THEN g.read_packet END AS _read_packet,
                    COALESCE(g.read_selector,b.facts#>'{publication_dependencies,selector}') AS _selector,
                    CASE WHEN %s='odds' AND (g.read_packet IS NOT NULL OR g.blob_id IS NOT NULL) THEN NULL ELSE current_result_read_facts(b.facts,%s)::text END AS _facts_text,
                    CASE WHEN %s='odds' AND (g.read_packet IS NOT NULL OR g.blob_id IS NOT NULL) THEN NULL ELSE
                        (CASE WHEN %s='odds' THEN current_grid_board(b.game_key,b.facts) ELSE b.facts->'boards'->%s END)::text END AS _board_text
                    FROM latest_board b LEFT JOIN current_grid_projection g USING(game_key)
                    WHERE (%s::text[] IS NULL OR b.game_key=ANY(%s))""",(view,view,view,view,view,view,window_keys,window_keys))
                from .slate_reads import CapturedReads,MAX_RETAINED_BYTES
                retained=[];retained_bytes=0
                for row in cursor:
                    packet=row.pop('_read_packet');selector=row.pop('_selector');blob=row.pop('_blob_id')
                    if view!='odds':
                        from .result_publication import attach as attach_units
                        attach_units(db,row,guard=resource_guard,view=view,original_blob=blob,lazy_originals=True)
                    if blob and view=='odds':packet=b'PB1'+blob.encode('ascii')
                    if resource_guard:resource_guard((len(packet) if packet is not None else len(row['_facts_text'])+len(row['_board_text'] or ''))*8)
                    packed=bytes(packet) if packet is not None else CapturedReads.freeze(encoded(row))
                    retained_bytes+=len(packed)+256
                    if retained_bytes>MAX_RETAINED_BYTES:raise ValueError('current_slate_read_capacity')
                    retained.append(dict(game_key=row['game_key'],_packed=packed,_selector=selector))
        elif dashboard:
            retained=db.execute('SELECT * FROM latest_dashboard WHERE (%s::text IS NULL OR game_key=%s)',(game,game)).fetchall()
        elif view is None:
            retained=db.execute('SELECT * FROM latest_board WHERE (%s::text IS NULL OR game_key=%s)',(game,game)).fetchall()
        else:
            # A slate consumes one compact view. Leave the other two in SQL,
            # avoiding their JSON decoding and Python containers on every poll.
            retained=db.execute('''SELECT game_key,dependency_revision,economic_revision,calculated_at,
                (facts - 'boards') || jsonb_build_object('boards',jsonb_build_object(%s::text,facts->'boards'->%s::text)) AS facts
                FROM latest_board WHERE (%s::text IS NULL OR game_key=%s)''',(view,view,game,game)).fetchall()
        timed=_read_mark('snapshot_transfer',timed)
        if not serialized_boards and view!='odds':
            from .result_publication import attach as attach_units
            for row in retained:attach_units(db,row,guard=resource_guard)
        rows={r['game_key']:r for r in retained}
        committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
        states=source_states(committed,owner)
        selected_manifest=next(iter(rows.values())).get('facts',{}).get('publication_dependencies') if game and len(rows)==1 else None
        dependencies=publication.capture(db,states,selector=scoped_selector if scoped_selector is not None else selected_manifest.get('selector') if selected_manifest else None,
            compact='lazy' if serialized_boards else False,resource_guard=resource_guard,identity=identity)
        dependencies['control_barrier']=_control_barrier(db)
        authority=_slate_authority(dependencies['epoch'],owner,states,dependencies['control_barrier'])
        timed=_read_mark('snapshot_dependencies',timed)
    observation_reasons=[];calculation_reasons=[]
    if not saved:observation_reasons.append('background_results_not_published')
    if str(status.get('epoch'))!=dependencies['epoch']:observation_reasons.append('current_dependencies_changed')
    elif status.get('version')!='predict-latest-board-3' and status.get('input_marker')!=current:
        observation_reasons.append('current_dependencies_changed')
    prior_runtime=status.get('runtime',{})
    current_runtime=runtime_identity(owner)
    if any(prior_runtime.get(k)!=current_runtime.get(k) for k in ('runtime_id','active','healthy','config','paused_sources','global_stopped','service_state','observation_state')):
        observation_reasons.append('runtime_authority_changed')
    if current_runtime['observation_state']!='running':observation_reasons.append('background_observations_unavailable')
    source_binding=observation_binding();current_engine=engine_binding();current_policy=load().revision
    if status.get('observation_binding')!=source_binding:observation_reasons.append('matching_binding_changed')
    if not owner.get('active'):
        observation_reasons.append('updates_stopped' if owner.get('healthy') else 'data_runtime_unhealthy')
    if owner.get('calculations',{}).get('board','running')!='running':calculation_reasons.append('background_calculations_unavailable')
    if status.get('engine_binding')!=current_engine:calculation_reasons.append('engine_binding_changed')
    if status['policy']['revision']!=current_policy:calculation_reasons.append('policy_changed')
    reasons=observation_reasons+calculation_reasons
    dependency_reasons={}
    for key,row in (() if serialized_boards else rows.items()):
        saved_dependencies=row['facts'].get('financial_dependencies',row['facts'].get('publication_dependencies')) if view in ('ev','arbs') else row['facts'].get('publication_dependencies')
        checks=publication.reasons(dependencies,saved_dependencies) if saved_dependencies else dict(all=['current_dependencies_changed'],observations={},comparisons={})
        if row['facts'].get('observation_binding')!=source_binding:
            checks['all']=sorted(set([*checks['all'],'matching_binding_changed']))
        if view is None and row['facts'].get('financial_dependencies'):
            checks['financial']=publication.reasons(dependencies,row['facts']['financial_dependencies'])
        if row['facts'].get('result_units'):
            from .result_publication import validate as validate_unit
            checks['units']={uid:validate_unit(dependencies,u['facts'],at=at,owner=owner,engine=current_engine,policy=current_policy,binding=source_binding)
                for uid,u in row['facts']['result_units'].items()}
        checks['inventory_state']=inventory_state(dependencies,row['facts'],owner=owner,at=at,engine=current_engine,policy=current_policy)
        dependency_reasons[key]=checks
    proof=None
    if serialized_boards:
        # Keep the complete MVCC proof, including scoring and source states.
        # Its derived indexes/caches are reconstructed once per requested page.
        proof={k:dependencies[k] for k in ('epoch','events','offers','states','selection_identities','control_barrier')}
        proof.update(books=list(dependencies['books'].values()),active_events=sorted(dependencies['active_events']))
    from app.comparison.current_dependencies import streaming_digest
    proof_revision=None
    if serialized_boards:
        proof_revision=hashed([proof['epoch'],
            sorted((key,event['dependency_revision']) for key,event in proof['events'].items()),
            proof['active_events'],proof['states'],
            sorted((key,row['contract_dependency'],row['metric_dependency'],row['offer_revision'],
                    row['source_at'],row.get('scoring_dependency')) for key,row in proof['offers'].items()),
            proof['books']])
    revision=streaming_digest([current,status.get('as_of'),reasons,status.get('runtime'),
        [source_binding,native_proof,proof_revision] if serialized_boards else dependency_reasons])
    if current is not None and status.get('input_marker')!=current:
        # Summary diagnostics describe pending work, without applying a global
        # stale bit to independent source observations or games.
        reasons=sorted(set([*reasons,'current_dependencies_changed']))
    return dict(native_authority=native_proof,status=status,rows=rows,reasons=reasons,observation_reasons=observation_reasons,
        calculation_reasons=calculation_reasons,dependency_reasons=dependency_reasons,
        source_states=states,at=at,owner=owner,read_revision=revision,read_authority=authority,
        _dependencies=proof,_source_binding=source_binding,_engine_binding=current_engine,_current_policy=load().to_dict())


def selected_dependencies(db, saved, *, stopped=False):
    """Complete selected match neighborhood, including new contracts and peers.

    All family/benchmark contracts and book/receipt revisions are bound, along
    with source health and operational authority. Unrelated game ingress and
    publication clocks do not revoke an otherwise unchanged selection.
    """
    owner=runtime(db)
    if stopped or not owner.get('active') or not owner.get('healthy'):raise ValueError('background_runtime_authority_unavailable')
    committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
    states=source_states(committed,owner)
    frame=publication.capture(db,states,selector=saved.get('selector') if saved else None)
    if not saved or saved.get('version')!=publication.VERSION:raise ValueError('current_inputs_changed_or_removed')
    neighborhood=publication.neighborhood(frame,saved['selector'])
    ids=[row[0] for row in neighborhood]
    offers=[row for row in frame['offers'].values() if row['event_id'] in ids]
    venues={row['venue'] for row in offers}
    authority=_slate_authority(frame['epoch'],owner,{v:states.get(v,{}) for v in venues},_control_barrier(db))
    token=hashed(dict(authority=authority,stopped=bool(stopped),neighborhood=neighborhood,
        offers=offers,books=[row for row in frame['books'].values() if row['event_id'] in ids]))
    return token,ids


def slate(db, policy, *, view, filter, stopped=False, offset=0, limit=25, expected_revision=None,
          read_token=None, read_frames=None, storage=None):
    timed=monotonic()
    if not 0<=offset or not 1<=limit<=50:raise ValueError('slate_page_capacity')
    reads=_SLATE_READS if read_frames is None else read_frames
    context=hashed([policy.to_dict(),view,filter,limit])
    if read_token:
        captured=reads.get(read_token,context=context)
        reads.guard(len(captured.header)*8)
        header=reads.decode(captured.header)
        if not expected_revision or expected_revision!=header['read_revision']:
            raise ValueError('current_slate_read_context_changed')
        reads.authorize(captured,slate_authority(db,stopped=stopped))
    else:
        if offset:raise ValueError('current_slate_read_token_required')
        reads.cleanup();reads.guard()
        frame=snapshot(db,resource_guard=reads.guard,view=view,serialized_boards=True,window_hours=72 if view=='odds' else None);status=frame['status']
        if expected_revision and expected_revision!=frame['read_revision']:raise ValueError('current_slate_changed')
        games=[]
        for original in sorted(status['games'],key=lambda g:(g.get('start_at') or '',g['game_key'])):
            games.append(compact_catalog_game(original))
        records=[];retained=0
        # Keep only the small event index in the page header. Contract/book
        # evidence is scoped to each game's complete matching neighborhood,
        # including new peers, from this same MVCC snapshot.
        proof=frame.get('_dependencies')
        if proof is not None:
            import json
            proof['active_events']=set(proof['active_events'])
            proof['neighborhoods']={}
            offers_by_event={};books_by_event={}
            for offer in proof['offers'].values():offers_by_event.setdefault(offer['event_id'],[]).append(offer)
            for book in proof['books']:books_by_event.setdefault(book['event_id'],[]).append(book)
        for game in games:
            reads.guard()
            key=game['game_key']
            row=frame['rows'].pop(key,None)
            value=dict(game_key=key,row=row,
                dependencies=frame.get('dependency_reasons',{}).get(key))
            if proof is not None and value['row'] is not None:
                row=value['row']
                facts={} if '_packed' in row else json.loads(row['_facts_text']) if '_facts_text' in row else row['facts']
                saved=dict(selector=row['_selector']) if row.get('_selector') is not None else facts.get('publication_dependencies')
                ids=[item[0] for item in publication.neighborhood(proof,saved['selector'])] if saved else []
                offers={offer['id']:offer for key in ids for offer in offers_by_event.get(key,[])}
                value['_proof']=dict(offers=offers,books=[book for key in ids for book in books_by_event.get(key,[])],
                    selection_identities={key:proof['selection_identities'][key] for key in offers if key in proof['selection_identities']})
                del facts,offers
            record=reads.join_record(key,row['_packed'],value.get('_proof')) if row is not None and '_packed' in row else reads.freeze(encoded(value))
            retained+=len(record)+256
            if retained+4096>reads.maximum_bytes:raise ValueError('current_slate_read_capacity')
            reads.guard(len(record));records.append(record)
        header=dict(window_hours=72 if view=='odds' else None,version='predict-comparison-slate-2',view=view,filter=filter,policy=status['policy'],requested_policy=policy.to_dict(),
            sizing_scope='shared_default_selected_details',games=games,stopped=bool(frame['owner'].get('healthy') and not frame['owner'].get('active')),
            as_of=status.get('as_of',frame['at']),read_at=frame['at'],read_revision=frame['read_revision'],epoch=status['epoch'],
            read_expires_at=(stamp(utc())+timedelta(seconds=reads.ttl_seconds)).isoformat(),
            collection=dict(healthy=frame['owner'].get('healthy',False),active=frame['owner'].get('active',False),stopped=bool(frame['owner'].get('global_stopped',False))),
            background=dict(reasons=frame['reasons'],scope_complete=status.get('scope_complete',False)),
            bounds=dict(maximum_games=len(games),maximum_page_games=50,maximum_bytes=8*1024*1024),provider_requests=0,
            _evaluated=view!='odds' and status.get('version') in ('predict-latest-board-1','predict-latest-board-2','predict-latest-board-3'),
            _frame={k:v for k,v in frame.items() if k not in ('rows','dependency_reasons')})
        header['_frame']['status']=dict(games=games,observation_errors=status.get('observation_errors',[]),
            engine_binding=status.get('engine_binding'),policy=status['policy'])
        header['_frame']['owner']=captured_owner(frame['owner'])
        if proof is not None:
            header['_frame']['_dependencies']={key:proof[key] for key in ('epoch','events','states')}
            header['_frame']['_dependencies']['active_events']=sorted(proof['active_events'])
            header['_frame']['_dependencies']['control_barrier']=proof.get('control_barrier')
            del proof,offers_by_event,books_by_event
        authority=hashed([frame['read_authority'],bool(stopped)])
        # Release the full captured SQL frame before retaining the compact view.
        del frame
        from .grid_packet_store import PacketStore
        captured=reads.capture(header,records,context=context,authority=authority,packet_store=PacketStore.from_connection(db) if any(reads.packet_ids(records)) else None)
        # This private first-page header is already decoded. Rehydrating the
        # captured copy here doubles the complete dependency graph at peak RSS.
        header['read_token']=captured.token
    timed=_read_mark('slate_capture',timed)
    games=header['games'];page=games[offset:offset+limit];boards=[];errors=[]
    # All source facts and validation results belong to the first MVCC capture.
    # Render only this page, at that same captured clock, without hydrating the
    # other games or consulting later SQL publications.
    page_frame=header.pop('_frame')
    proof=page_frame.pop('_dependencies',None)
    if proof is not None:proof['active_events']=set(proof['active_events'])
    rendered_bytes=0;rendered_count=0
    for record in captured.records[offset:offset+limit]:
        reads.guard(len(record)*8)
        value=reads.decode(record,packet_store=captured.packet_store)
        if value.get('row') and '_facts_text' in value['row']:
            import json
            value['row']['facts']=json.loads(value['row'].pop('_facts_text'))
        key=value['game_key']
        page_frame['rows']={key:value['row']} if value['row'] is not None else {}
        page_frame['dependency_reasons']={key:value['dependencies']} if value['dependencies'] is not None else {}
        if proof is not None and value['row'] is not None:
            scoped=dict(proof,**value.pop('_proof'))
            scoped['books']={(r['venue'],r['event_id'],r['native_market_id']):r for r in scoped['books']}
            scoped.update(by_event={},neighborhoods={},candidate_sets={})
            for offer in scoped['offers'].values():scoped['by_event'].setdefault(offer['event_id'],[]).append(offer)
            facts=value['row']['facts'];saved=facts.get('financial_dependencies',facts.get('publication_dependencies')) if view!='odds' else facts.get('publication_dependencies')
            checks=publication.reasons(scoped,saved) if saved else dict(all=['current_dependencies_changed'],observations={},comparisons={})
            if facts.get('observation_binding')!=page_frame['_source_binding']:
                checks['all']=sorted(set([*checks['all'],'matching_binding_changed']))
            if facts.get('result_units'):
                from .result_publication import validate as validate_unit
                checks['units']={uid:validate_unit(scoped,u['facts'],at=page_frame['at'],owner=page_frame['owner'],engine=page_frame['_engine_binding'],policy=page_frame['_current_policy']['revision'],binding=page_frame['_source_binding'])
                    for uid,u in facts['result_units'].items()}
            checks['inventory_state']=inventory_state(scoped,facts,owner=page_frame['owner'],at=page_frame['at'],engine=page_frame['_engine_binding'],policy=page_frame['_current_policy']['revision'])
            page_frame['dependency_reasons'][key]=checks
            del scoped
        try:
            rendered=board(page_frame,key,view=view,filter=filter,read_token=captured.token,price_grid=view=='odds')
            boards.append(rendered)
            rendered_bytes+=len(encoded(rendered))
        except ValueError as exc:errors.append(dict(game_key=key,reason=str(exc),
            availability=result_availability(dict(reasons=['calculation_read_failed']))))
        rendered_count+=1
        # Stop before expanding boards that the bounded wire page would discard.
        # The next page resumes this same immutable capture at the exact prefix.
        if rendered_bytes>=2*1024*1024:break
    timed=_read_mark('slate_render',timed)
    evaluated=header.pop('_evaluated')
    reads.guard()
    try:
        out,size=bounded_page(header,boards,errors,offset=offset,limit=limit,evaluated=evaluated,storage=storage,rendered_count=rendered_count)
    except ValueError:
        reads.discard(captured.token)
        raise
    complete=out['coverage']['complete']
    # Recheck after rendering too: a Stop/reset cannot race an expensive capture
    # and leave newly returned pages carrying the withdrawn authority.
    reads.authorize(captured,slate_authority(db,stopped=stopped))
    reads.account(captured,offset=offset,limit=limit,size=size,complete=complete)
    return out,[]
