"""One background owner of bounded replaceable compact ordinary board results.

HTTP readers only read these compact rows and committed input/status identities.
Expanded states, ladders and financial reports are never retained here.
"""
import asyncio
from app.diagnostics import failure
from copy import deepcopy
from datetime import timedelta
from psycopg.types.json import Jsonb

from .store import ROOT, connect, encoded, hashed, stamp
from .current_games import GameStore, engine_binding, observation_binding, utc
from .comparison_board import ReadContext, discover, calculate_current, context_identity, observation_identity
from app.comparison.estimated_policy import load
from app.dashboard.comparison_board import response, entries, freshness, age_observation, age_gross_comparison, odds_rows, compact_odds
from app.comparison.calculation_availability import summary, combine, result_availability
from . import observation_publication as publication
from .slate_reads import CapturedReads
from app.comparison.calculation_control import CalculationStopped, cancellation, checkpoint

MAX_BYTES = 64 * 1024 * 1024
MAX_GAMES = 500
LOCK = 903015
_SLATE_READS = CapturedReads()
SOURCE_PREVIOUS = """jsonb_build_object(
    'publication_dependencies',facts->'publication_dependencies',
    'observation_binding',facts->'observation_binding',
    'observation_valid_until',facts->'observation_valid_until',
    'valid_until',facts->'valid_until')"""


def capture_reservation(db, *, observations_only=False):
    """Bound decoded captures before reading JSON or hydrated depth rows."""
    previous=SOURCE_PREVIOUS if observations_only else 'facts'
    size=db.execute('''SELECT COALESCE(sum(n),0) AS n FROM (
        SELECT octet_length(facts::text) n FROM current_event
        UNION ALL SELECT octet_length(facts::text) FROM current_contract
        UNION ALL SELECT octet_length(facts::text) FROM current_offer
        UNION ALL SELECT octet_length(('''+previous+''')::text) FROM latest_board) inputs''').fetchone()['n']
    # Native ask rows are later hydrated per occurrence from the same bounded
    # tables. Include their Python containers and exact decimal strings too.
    depth=db.execute('''SELECT COALESCE(sum(n),0) AS n FROM (
        SELECT octet_length(price_value)+octet_length(quantity_value)+256 n FROM current_native_depth WHERE side='asks'
        UNION ALL SELECT octet_length(price_value)+octet_length(quantity_value)+256 FROM current_depth WHERE side='asks') levels''').fetchone()['n']
    return int(size)*8+int(depth)+32*1024*1024


def marker(db):
    """Cheap committed identities, including withdrawals independent of quotes."""
    epoch = db.execute('SELECT epoch FROM current_row_epoch WHERE singleton=true').fetchone()['epoch']
    values = []
    for query in (
        'SELECT id,revision,expires_order::text FROM current_event ORDER BY id',
        'SELECT id,revision FROM current_contract ORDER BY id',
        'SELECT contract_id,revision,received_at FROM current_offer ORDER BY contract_id',
        'SELECT venue,event_id,native_market_id,revision,received_at FROM current_native_book ORDER BY venue,event_id,native_market_id',
        'SELECT venue,state FROM current_source_status ORDER BY venue',
    ):
        rows = db.execute(query).fetchall()
        if len(rows) > 32768:raise ValueError('board_marker_capacity')
        if query.startswith('SELECT venue,state'):
            rows=[dict(venue=row['venue'],state=publication.health(row['state'])) for row in rows]
        values.append(rows)
    return hashed([epoch, values])


def runtime(db, *, at=None):
    from app.collection.runtime_status import read_runtime
    return read_runtime(db, at=at)


def runtime_identity(value):
    # Runtime revision also describes routine source receipt/status clocks. Those
    # clocks are not authority to invalidate every unchanged source observation.
    return dict(**{k:value.get(k) for k in ('runtime_id','active','healthy','config','paused_sources','global_stopped','service_state')},
        observation_state=value.get('calculations',{}).get('observations','running'),
        calculation_state=value.get('calculations',{}).get('board','running'))


def _control_barrier(db):
    # The latest control identity survives Stop followed by recovery between
    # HTTP requests. Ordinary collection/publication never writes this table.
    row=db.execute("""SELECT id FROM data_runtime_command
        WHERE action IN ('stop','pause','recover') ORDER BY created_at DESC,id DESC LIMIT 1""").fetchone()
    return row['id'] if row else None


def _slate_authority(epoch, owner, states, control):
    # Receipt clocks and routine diagnostic wording cannot revoke a detached
    # observation. Actual source availability and operational authority can.
    return hashed(dict(epoch=str(epoch),runtime=runtime_identity(owner),
        sources={key:value.get('state') for key,value in states.items()},control=control,
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


def source_states(committed, owner):
    """Committed ingress beats a delayed heartbeat; explicit controls still win."""
    states=dict(owner.get('states',{}));states.update(committed)
    for venue,state in list(states.items()):
        if not owner.get('healthy'):
            states[venue]=dict(state,state='unavailable',reason_code='data_runtime_unhealthy')
        elif not owner.get('active') or venue in owner.get('paused_sources',[]):
            states[venue]=dict(state,state='stopped',reason_code='updates_stopped')
    return states


def read_context(db, *, at=None, owner=None, event_ids=None, resource_guard=None, tolerate_invalid_catalog=False):
    from .current_rows import CurrentRowStore
    owner=owner if owner is not None else runtime(db,at=at)
    frame=CurrentRowStore(db).capture(include_depth=False,event_ids=event_ids,resource_guard=resource_guard)
    frame['source_status']=source_states(frame['source_status'],owner)
    return ReadContext(GameStore(db),at=at,frame=frame,resource_guard=resource_guard,tolerate_invalid_catalog=tolerate_invalid_catalog)


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


def _selection_payload(observed, bundle, value, policy, context, error=None):
    observed['calculation_context']=observation_identity(observed,context)
    boards={'odds':response(observed,None,policy,view='odds',filter='all',at=context.at)}
    financial_context=None
    if bundle is not None and value is not None:
        financial_context=value['calculation_context']
        bundle['calculation_context']=financial_context
    financial=bundle if financial_context else observed
    for view in ('ev','arbs'):
        boards[view]=response(financial,value if financial_context else None,policy,view=view,filter='all',at=context.at)
    metrics=boards['ev']['availability']
    codes=[cause['code'] for cause in metrics.get('causes',[])]
    available=dict(state='unavailable' if error or not metrics['numeric_results'] else 'partial' if metrics['numeric_results']<metrics['total_results'] else 'evaluated',
                   reason_codes=[error] if error else codes,calculated_at=None if value is None else value['calculated_at'])
    if error:
        for view in ('ev','arbs'):
            boards[view]['availability']=summary([],failures=[(observed['game_key'],error)])
            boards[view]['empty_reason']='Estimate unavailable; collected observations remain available'
    return dict(boards=boards,observation_valid_until=observation_boundary(observed,context.at),
        valid_until=next_boundary(bundle,context.at) if financial_context else None,
        context=financial_context,observation_context=observed['calculation_context'],estimate_availability=available,calculation_error=error,
        observation_binding=context.observation_binding,
        publication_dependencies=publication.manifest(context.publication_frame,observed))


def publish(db, *, captured_marker, captured_runtime, status, rows):
    """CAS exact price/membership dependencies; unrelated ingress cannot starve it."""
    checkpoint()
    from .current_rows import LOCK as CURRENT_LOCK
    with db.transaction():
        db.execute('SELECT pg_advisory_xact_lock(%s)',(CURRENT_LOCK,))
        db.execute('SELECT revision FROM data_runtime WHERE singleton=true FOR SHARE').fetchone()
        now_runtime=runtime(db)
        current_owner=runtime_identity(now_runtime);captured_owner=runtime_identity(captured_runtime)
        if status.get('observation_only'):
            # The independent source owner needs observation authority. An
            # optional worker pause/failure cannot cancel its committed prices.
            current_owner.pop('calculation_state',None);captured_owner.pop('calculation_state',None)
        if current_owner!=captured_owner:return False
        source_binding=observation_binding()
        if status.get('observation_binding')!=source_binding:return False
        if not status.get('observation_only') and status.get('engine_binding')!=engine_binding():return False
        committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
        current=publication.capture(db,source_states(committed,now_runtime))
        if str(status.get('epoch'))!=current['epoch']:return False
        newest={r['game_key']:r['observation_as_of'] for r in db.execute(
            "SELECT game_key,facts->'boards'->'odds'->>'as_of' AS observation_as_of FROM latest_board").fetchall()}
        accepted=[];rejected=[]
        for row in rows:
            saved=row['facts'].get('publication_dependencies')
            if saved is None:
                valid=marker(db)==captured_marker
            else:
                checks=publication.reasons(current,saved)
                valid=not(checks['all'] or any(checks['comparisons'].values()) or any(checks['observations'].values()))
            if row['facts'].get('observation_binding')!=source_binding:valid=False
            # A slow optional owner cannot replace a newer source publication
            # after time alone changed the eligible current comparator roster.
            prior_at=newest.get(row['game_key']);incoming_at=row['facts']['boards']['odds'].get('as_of')
            if prior_at and incoming_at and stamp(prior_at)>stamp(incoming_at):valid=False
            (accepted if valid else rejected).append(row)
        if not accepted and rows:return False
        rows=accepted
        size=sum(len(encoded(row['facts'])) for row in rows)
        if len(rows)>MAX_GAMES or size>MAX_BYTES:raise ValueError('latest_board_capacity')
        from app.collection.current_storage_policy import require_disk_space,sql_usage,SQL_BYTE_CAP
        require_disk_space(ROOT/'.local/postgres',append_bytes=size)
        if sql_usage(db)+size>=SQL_BYTE_CAP:raise ValueError('current_database_storage_cap')
        for row in rows:
            db.execute('''INSERT INTO latest_board VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT(game_key) DO UPDATE SET dependency_revision=excluded.dependency_revision,
                economic_revision=excluded.economic_revision,calculated_at=excluded.calculated_at,facts=excluded.facts
                WHERE latest_board.economic_revision<>excluded.economic_revision OR latest_board.facts<>excluded.facts''',
                (row['game_key'],row['dependency_revision'],row['economic_revision'],row['calculated_at'],Jsonb(row['facts'])))
        # Deletion requires a complete unchanged capture. A later newly admitted
        # game must never be erased by partial older work.
        if marker(db)==captured_marker:
            db.execute('DELETE FROM latest_board WHERE NOT(game_key=ANY(%s))',([g['game_key'] for g in status['games']],))
        else:
            # A resolved occurrence can replace an older source-local group
            # while unrelated ingress changes the global marker. Accepted local
            # proofs cover every old member before withdrawing that old group.
            covered={eid for row in accepted for eid in row['facts']['publication_dependencies']['selector']['events']}
            active={offer['event_id'] for offer in current['offers'].values()}
            games={g['game_key'] for g in status['games']}
            captured_at=status.get('as_of')
            obsolete=db.execute("""SELECT game_key,facts#>'{publication_dependencies,selector,events}' members,
                facts#>>'{boards,odds,as_of}' as_of FROM latest_board""").fetchall()
            for old in obsolete:
                members=set(old['members'] or [])
                if (captured_at and old['game_key'] not in games and members and old['as_of'] and stamp(old['as_of'])<=stamp(captured_at)
                        and (members<=covered or not members.intersection(active))):
                    db.execute('DELETE FROM latest_board WHERE game_key=%s',(old['game_key'],))
        if rejected:
            retained=db.execute('SELECT facts FROM latest_board_status WHERE singleton=true').fetchone()
            if retained:
                games={g['game_key']:g for g in retained['facts']['games']}
                games.update({g['game_key']:g for g in status['games'] if g['game_key'] in {r['game_key'] for r in accepted}})
                status=dict(status,games=list(games.values()))
        db.execute('''INSERT INTO latest_board_status VALUES (true,%s,%s)
            ON CONFLICT(singleton) DO UPDATE SET facts=excluded.facts,updated_at=excluded.updated_at''',(Jsonb(status),utc()))
        return not rejected


def reconcile(db, *, at=None, observations_only=False):
    """Publish source frames even when optional discovery or finance fails."""
    at=at or utc();policy=load()
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        owner=runtime(db,at=at);captured_marker=marker(db);source_binding=observation_binding()
        committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
        publication_frame=publication.capture(db,source_states(committed,owner))
        # The observation owner only needs prior dependency/clock proofs. It
        # never decodes the full optional boards which it deliberately retains.
        previous_query=('SELECT game_key,dependency_revision,economic_revision,calculated_at,'+SOURCE_PREVIOUS+' AS facts FROM latest_board'
            if observations_only else 'SELECT * FROM latest_board')
        previous={r['game_key']:r for r in db.execute(previous_query).fetchall()}
        prior=db.execute('SELECT facts FROM latest_board_status WHERE singleton=true').fetchone()
        dependency_checks_by_game={}
        if prior:
            facts=prior['facts']
            dependency_checks_by_game={key:publication.reasons(publication_frame,r['facts']['publication_dependencies'])
                for key,r in previous.items() if r['facts'].get('publication_dependencies')}
            dependency_checks=list(dependency_checks_by_game.values())
            scoped_unchanged=(len(dependency_checks)==len(previous) and all(not (check['all'] or any(check['observations'].values())
                or any(check['comparisons'].values())) for check in dependency_checks)
                and all(r['facts'].get('observation_binding')==source_binding for r in previous.values()))
            unchanged=(facts.get('input_marker')==captured_marker and facts.get('runtime')==runtime_identity(owner)
                and facts.get('engine_binding')==engine_binding() and facts.get('policy',{}).get('revision')==policy.revision
                and facts.get('version')=='predict-latest-board-3' and (observations_only or not facts.get('observation_only'))
                and (observations_only or not facts.get('errors')) and not facts.get('observation_errors') and not facts.get('catalog_errors') and scoped_unchanged)
            if unchanged and all(all(not r['facts'].get(k) or stamp(at)<stamp(r['facts'][k])
                    for k in (('observation_valid_until',) if observations_only else ('valid_until','observation_valid_until'))) for r in previous.values()):
                return dict(published=False,unchanged=True,computed=0,reused=len(previous),errors=[])
        context=read_context(db,at=at,owner=owner,tolerate_invalid_catalog=True)
        context.publication_frame=publication_frame
        context.observation_binding=source_binding
        catalog=context.catalog();captured=[];source_errors=[];unchanged_observations=0
        valid_games=list(catalog['games'])
        invalid_members={tuple(member) for error in context.catalog_errors for member in error['members']}
        valid_members={tuple(member) for game in valid_games for member in game['members']}
        # Keep a prior failed occurrence as an explicitly obsolete frame where
        # no new valid occurrence already covers its members. Never relabel it
        # with the new engine or silently rebind conflicting source facts.
        retained_invalid=[game for game in (prior['facts']['games'] if prior else [])
            if invalid_members.intersection(map(tuple,game['members'])) and not valid_members.intersection(map(tuple,game['members']))]
        catalog['games'].extend(retained_invalid)
        if len(catalog['games'])>MAX_GAMES:raise ValueError('board_catalog_capacity')
        source_errors.extend(dict(game_key=game['game_key'],reason='observation_invalid') for game in retained_invalid)
        for game in valid_games:
            checkpoint()
            old=previous.get(game['game_key']);checks=dependency_checks_by_game.get(game['game_key'])
            deadline=old['facts'].get('observation_valid_until') if old else None
            if (observations_only and old and checks and old['facts'].get('observation_binding')==source_binding
                    and not (checks['all'] or any(checks['observations'].values()) or any(checks['comparisons'].values()))
                    and (not deadline or stamp(at)<stamp(deadline))):
                # Validate the exact committed proof before expensive hydration
                # and serialization. Quiet retained games must not delay a live
                # changed pair behind rebuilding the entire historical slate.
                unchanged_observations+=1
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
            games=catalog['games'],errors=errors,observation_errors=source_errors,catalog_errors=context.catalog_errors,as_of=at,
            scope_complete=not source_errors and not context.catalog_errors,calculation_scope_complete=not observation_only and not errors and not source_errors and not context.catalog_errors,
            observation_only=observation_only,maximum_games=MAX_GAMES,maximum_bytes=MAX_BYTES,computed=computed,reused=reused,provider_requests=0)
    observations=[]
    for game,observed in captured:
        checkpoint()
        facts=_selection_payload(observed,None,None,policy,context,'background_estimates_pending')
        old=previous.get(game['game_key'])
        deadline=old['facts'].get('observation_valid_until') if old else None
        if old and old['facts'].get('observation_binding')==source_binding and old['facts'].get('publication_dependencies')==facts['publication_dependencies'] and (not deadline or stamp(at)<stamp(deadline)):
            # Keep an already evaluated optional board while independent unchanged
            # source observations remain valid. No estimate claim is renewed.
            continue
        observations.append(dict(game_key=game['game_key'],dependency_revision=observed['input_version'],
            economic_revision=hashed(['source',facts['observation_context']]),calculated_at=None,facts=facts))
    if observations:
        observed_published=publish(db,captured_marker=captured_marker,captured_runtime=owner,
            status=status_for([],observation_only=True),rows=observations)
    else:observed_published=False
    if observations_only:
        return dict(published=observed_published,computed=0,reused=unchanged_observations+len(captured)-len(observations),errors=source_errors)
    rows=[];errors=[];computed=0;reused=0
    for game,observed in captured:
        checkpoint()
        bundle=None;identity=None;error=None
        try:
            bundle=discover(context.store,benchmark_venue=policy.benchmark_venue,context=context,game=game['game_key'])[0]
            identity=context_identity(bundle,policy,context)
        except CalculationStopped:raise
        except Exception as exc:
            failure(__name__, 'latest_board_inputs', exc)
            bundle=None;error='calculation_inputs_unavailable'
        economic=hashed(dict(context=identity,observation=observation_identity(observed,context),
            policy=policy.revision,config=owner.get('config',{}),active=owner.get('active',False),error=error))
        old=previous.get(game['game_key'])
        if old and old['facts'].get('observation_binding')==source_binding and old['economic_revision']==economic and not old['facts'].get('calculation_error'):
            # Refresh only conservative temporal metadata. Unchanged economics
            # and source frames keep their original calculation/publication time.
            retained=dict(old,facts=dict(old['facts'],valid_until=next_boundary(bundle,context.at) if bundle else None,
                observation_valid_until=observation_boundary(observed,context.at)))
            rows.append(retained);reused+=1;continue
        value=None
        if bundle is not None:
            try:
                value=calculate_current(bundle,policy,context=context)
                # Compact financial rendering is optional too; malformed model
                # decoration cannot cancel the independent source frame.
                facts=_selection_payload(observed,bundle,value,policy,context)
                computed+=1
            except CalculationStopped:raise
            except Exception as exc:
                failure(__name__, 'latest_board_calculation', exc)
                error='calculation_failed';value=None
        if value is None:
            error=error or 'calculation_inputs_unavailable'
            facts=_selection_payload(observed,None,None,policy,context,error)
        if error:errors.append(dict(game_key=game['game_key'],reason=error))
        rows.append(dict(game_key=game['game_key'],dependency_revision=observed['input_version'],
            economic_revision=economic,calculated_at=None if value is None else value['calculated_at'],facts=facts))
    status=status_for(errors,computed,reused)
    return dict(published=publish(db,captured_marker=captured_marker,captured_runtime=owner,status=status,rows=rows),computed=computed,reused=reused,errors=errors+source_errors)


class LatestBoardOwner:
    """Runtime-owned polling; page access never starts or wakes this owner."""
    def __init__(self,service):
        self.service=service;self.closed=False;self.task=None;self.estimate_task=None;self.wake=asyncio.Event();self.last=None;self.error=None
        self.observation_error=None;self.estimate_error=None
        self.coverage_task=None;self.coverage_error=None;self.last_coverage=None
        self.admission_status={}
    async def start(self):
        self.task=asyncio.create_task(self.run(observations_only=True),name='predict-latest-observation-owner')
        self.estimate_task=asyncio.create_task(self.run(observations_only=False),name='predict-latest-estimate-owner')
        self.coverage_task=asyncio.create_task(self.run_coverage(),name='predict-coverage-owner')
    def coverage_tick(self):
        from .coverage_latest import reconcile as reconcile_coverage, LOCK as COVERAGE_LOCK
        with cancellation(lambda:self.closed),connect() as db:
            if not db.execute('SELECT pg_try_advisory_lock(%s) AS owned',(COVERAGE_LOCK+1,)).fetchone()['owned']:
                return dict(published=False,reason='another_coverage_owner')
            try:return reconcile_coverage(db)
            finally:db.execute('SELECT pg_advisory_unlock(%s)',(COVERAGE_LOCK+1,))
    async def run_coverage(self):
        while not self.closed:
            try:
                self.last_coverage=await asyncio.to_thread(self.coverage_tick)
                self.coverage_error=None
            except CalculationStopped:
                if self.closed:return
                raise
            except Exception as exc:
                failure(__name__, 'latest_board_coverage', exc)
                self.coverage_error='background_coverage_unavailable'
            # Independent low-frequency metrics cannot delay source frames or
            # optional estimate publication. Reads never wake this worker.
            for _ in range(10):
                if self.closed:break
                await asyncio.sleep(.5)
    def tick(self, *, observations_only=False):
        with cancellation(lambda:self.closed):
            return self._tick(observations_only=observations_only)
    def _tick(self, *, observations_only=False):
        lock=LOCK+1 if observations_only else LOCK
        with connect() as db:
            if not db.execute('SELECT pg_try_advisory_lock(%s) AS owned',(lock,)).fetchone()['owned']:return dict(published=False,reason='another_board_owner')
            try:
                from app.collection.background_work import BACKGROUND
                kind='observations' if observations_only else 'estimates'
                required=capture_reservation(db,observations_only=observations_only)
                with BACKGROUND.claim(kind,required,source=observations_only) as lease:
                    self.admission_status[kind]=dict(state='admitted' if lease else 'deferred',reason=lease.reason,
                        reserved_bytes=required,resident_bytes=lease.resident_bytes)
                    if not lease:return lease.deferred()
                    return reconcile(db,observations_only=observations_only)
            finally:db.execute('SELECT pg_advisory_unlock(%s)',(lock,))
    async def run(self, *, observations_only=False):
        while not self.closed:
            error=None
            try:self.last=await asyncio.to_thread(self.tick,observations_only=observations_only)
            except CalculationStopped:
                if self.closed:return
                raise
            except Exception as exc:
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
        if tasks:await asyncio.wait_for(asyncio.shield(asyncio.gather(*tasks)),timeout=self.service.config['cleanup_seconds'])


def snapshot(db, *, at=None, resource_guard=None, game=None, view=None):
    """Detached compact database frame; no normalization or financial owner."""
    if view is not None and view not in ('odds','ev','arbs'):raise ValueError('Unsupported board view')
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if resource_guard is not None:
            # Check the committed logical JSON size before decoding the full
            # frame. Leave conservative room for Python objects and rendering.
            size=db.execute('''SELECT COALESCE(sum(n),0) AS byte_count FROM (
                SELECT octet_length(facts::text) AS n FROM latest_board WHERE (%s::text IS NULL OR game_key=%s)
                UNION ALL SELECT octet_length(facts::text) FROM current_event
                UNION ALL SELECT octet_length(facts::text) FROM current_contract
                UNION ALL SELECT octet_length(facts::text) FROM latest_board_status
            ) retained''',(game,game)).fetchone()['byte_count']
            resource_guard(int(size)*8)
        saved=db.execute('SELECT facts FROM latest_board_status WHERE singleton=true').fetchone()
        # Establish the MVCC snapshot before choosing its read clock. A runtime
        # heartbeat committed between function entry and that first SQL query
        # is healthy, rather than a future heartbeat relative to an early clock.
        at=at or utc()
        status=saved['facts'] if saved else dict(games=[],errors=[],epoch=db.execute('SELECT epoch FROM current_row_epoch WHERE singleton=true').fetchone()['epoch'],policy=load().to_dict())
        owner=runtime(db,at=at);current=marker(db)
        if view is None:
            retained=db.execute('SELECT * FROM latest_board WHERE (%s::text IS NULL OR game_key=%s)',(game,game)).fetchall()
        else:
            # A slate consumes one compact view. Leave the other two in SQL,
            # avoiding their JSON decoding and Python containers on every poll.
            retained=db.execute('''SELECT game_key,dependency_revision,economic_revision,calculated_at,
                (facts - 'boards') || jsonb_build_object('boards',jsonb_build_object(%s::text,facts->'boards'->%s::text)) AS facts
                FROM latest_board WHERE (%s::text IS NULL OR game_key=%s)''',(view,view,game,game)).fetchall()
        rows={r['game_key']:r for r in retained}
        committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
        states=source_states(committed,owner)
        selected_manifest=next(iter(rows.values()))['facts'].get('publication_dependencies') if game and len(rows)==1 else None
        dependencies=publication.capture(db,states,selector=selected_manifest.get('selector') if selected_manifest else None)
        authority=_slate_authority(dependencies['epoch'],owner,states,_control_barrier(db))
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
    source_binding=observation_binding()
    if status.get('observation_binding')!=source_binding:observation_reasons.append('matching_binding_changed')
    if not owner.get('active'):
        observation_reasons.append('updates_stopped' if owner.get('healthy') else 'data_runtime_unhealthy')
    if owner.get('calculations',{}).get('board','running')!='running':calculation_reasons.append('background_calculations_unavailable')
    if status.get('engine_binding')!=engine_binding():calculation_reasons.append('engine_binding_changed')
    if status['policy']['revision']!=load().revision:calculation_reasons.append('policy_changed')
    reasons=observation_reasons+calculation_reasons
    dependency_reasons={}
    for key,row in rows.items():
        saved_dependencies=row['facts'].get('publication_dependencies')
        checks=publication.reasons(dependencies,saved_dependencies) if saved_dependencies else dict(all=['current_dependencies_changed'],observations={},comparisons={})
        if row['facts'].get('observation_binding')!=source_binding:
            checks['all']=sorted(set([*checks['all'],'matching_binding_changed']))
        dependency_reasons[key]=checks
    revision=hashed([current,status.get('as_of'),reasons,status.get('runtime'),dependency_reasons])
    if status.get('input_marker')!=current:
        # Summary diagnostics describe pending work, without applying a global
        # stale bit to independent source observations or games.
        reasons=sorted(set([*reasons,'current_dependencies_changed']))
    return dict(status=status,rows=rows,reasons=reasons,observation_reasons=observation_reasons,
        calculation_reasons=calculation_reasons,dependency_reasons=dependency_reasons,
        source_states=states,at=at,owner=owner,read_revision=revision,read_authority=authority)


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


def _withdraw(board, reasons):
    if not reasons:return
    board.update(status='historical',delivery_state='pending' if 'current_dependencies_changed' in reasons else 'stopped' if 'updates_stopped' in reasons else 'unavailable')
    items=[]
    for row in board['rows']:
        row['ranking_eligible']=False
        classification=row.get('classification',{})
        for key in ('main_positive_eligible','positive_rule_sensitive_eligible'):classification[key]=False
        f=row.setdefault('freshness',dict(status='historical',reasons=[]));f.update(status='historical',reasons=sorted(set(f['reasons']+reasons)))
        if board['view']!='odds':
            row['availability']=result_availability(row,pair=board['view']=='arbs')
            items.append((board['game_key'],[l['venue'] for l in row.get('legs',[])] if board['view']=='arbs' else [row['venue']],row['availability']))
    if board['view']!='odds':board['availability']=summary(items)


def board(frame, game_key, *, view, filter):
    row=frame['rows'].get(game_key)
    if row is None:
        error=next((e['reason'] for e in frame['status'].get('observation_errors',[]) if e['game_key']==game_key),None)
        raise ValueError(error or 'background_observation_unavailable')
    output=deepcopy(row['facts']['boards'][view]);source_reasons=list(frame.get('observation_reasons',frame['reasons']))
    local=frame.get('dependency_reasons',{}).get(game_key,dict(all=[],observations={},comparisons={}))
    source_reasons=sorted(set([*source_reasons,*local['all']]))
    comparison_reasons=sorted(set([*source_reasons,*[reason for values in local['comparisons'].values() for reason in values]]))
    calculation_reasons=list(frame.get('calculation_reasons',[]))
    if any(local['observations'].values()) or any(local['comparisons'].values()):
        calculation_reasons.append('current_dependencies_changed')
    deadline=row['facts'].get('valid_until')
    if deadline and stamp(frame['at'])>=stamp(deadline):calculation_reasons.append('calculation_authority_boundary')
    states=frame.get('source_states',frame['owner'].get('states',{}))
    for q in output['prices']:
        event=q.get('event') or next(g for g in frame['status']['games'] if g['game_key']==game_key)
        from .current_rows import contract_id
        own_reasons=sorted(set([*source_reasons,*local['observations'].get(contract_id(dict(quote=q)),[])]))
        if view=='odds':age_observation(q,event,frame['at'],source_states=states,publication_reasons=own_reasons)
        else:
            state=states.get(q['venue'],{}).get('state',q['source_state'])
            f=freshness(dict(q,state=state),{},event,stamp(frame['at']),financial=False)
            f['reasons']=sorted(set(f['reasons']+own_reasons));f['status']='historical' if f['reasons'] else 'current'
            q['freshness']=f;q['source_state']=state
            health=states.get(q['venue'],{})
            q['source_health']=dict(q.get('source_health',{}),**{k:health[k] for k in ('state','reason_code','reason') if k in health})
    if view=='odds':
        for q in output['prices']:
            cid=contract_id(dict(quote=q))
            peer_reasons=sorted(set([*source_reasons,*local['observations'].get(cid,[]),*local['comparisons'].get(cid,[])]))
            for field in ('gross_comparison','current_comparison'):
                if field in q:
                    age_gross_comparison(q[field],frame['at'],source_states=states,
                        publication_reasons=peer_reasons,captured_rows=output['prices'])
    reasons=source_reasons+calculation_reasons
    if view=='odds':
        output['rows']=odds_rows(output['prices'])
        statuses={q['freshness']['status'] for q in output['prices']}
        output['status']='mixed' if len(statuses)>1 else next(iter(statuses),'historical')
        output['delivery_state']='pending' if any(q.get('observation_display',{}).get('state')=='pending' for q in output['prices']) or 'current_dependencies_changed' in comparison_reasons else 'stopped' if 'updates_stopped' in source_reasons else 'unavailable' if 'data_runtime_unhealthy' in source_reasons else 'complete'
    else:_withdraw(output,reasons)
    estimate=deepcopy(row['facts'].get('estimate_availability',dict(state='evaluated',reason_codes=[])))
    if reasons:estimate.update(state='last_known' if estimate['state'] in ('evaluated','partial') else 'unavailable',reason_codes=sorted(set(estimate['reason_codes']+reasons)))
    output.update(filter=filter,read_at=frame['at'],sizing_scope='shared_default_selected_details',
        economic_revision=row['economic_revision'],calculated_at=row['calculated_at'],background_reasons=source_reasons if view=='odds' else reasons,
        observation_reasons=sorted(set([*source_reasons,*[reason for values in local['observations'].values() for reason in values]])),
        comparison_reasons=comparison_reasons,calculation_reasons=calculation_reasons,estimate_availability=estimate,
        collection=dict(healthy=frame['owner'].get('healthy',False),active=frame['owner'].get('active',False),
                        stopped=bool(frame['owner'].get('global_stopped',False)),
                        sources=frame.get('source_states',frame['owner'].get('states',{}))))
    if view!='odds' and filter!='all':
        key='positive_rule_sensitive_eligible' if filter=='hedges' else 'main_positive_eligible'
        output['rows']=[r for r in output['rows'] if r.get('classification',{}).get(key)]
    if not output['rows'] and reasons:output['empty_reason']='Latest results await background reconciliation' if 'current_dependencies_changed' in reasons else 'Only last-known estimates available; see All comparisons'
    return compact_odds(output)


def slate(db, policy, *, view, filter, stopped=False, offset=0, limit=25, expected_revision=None,
          read_token=None, read_frames=None, storage=None):
    if not 0<=offset<500 or not 1<=limit<=50:raise ValueError('slate_page_capacity')
    reads=_SLATE_READS if read_frames is None else read_frames
    context=hashed([policy.to_dict(),view,filter,limit])
    if read_token:
        captured=reads.get(read_token,context=context)
        header=reads.decode(captured.header)
        if not expected_revision or expected_revision!=header['read_revision']:
            raise ValueError('current_slate_read_context_changed')
        reads.authorize(captured,slate_authority(db,stopped=stopped))
    else:
        if offset:raise ValueError('current_slate_read_token_required')
        reads.cleanup();reads.guard()
        frame=snapshot(db,resource_guard=reads.guard,view=view);status=frame['status']
        if expected_revision and expected_revision!=frame['read_revision']:raise ValueError('current_slate_changed')
        games=sorted(status['games'],key=lambda g:(g.get('start_at') or '',g['game_key']))
        if len(games)>MAX_GAMES:raise ValueError('slate_page_capacity')
        records=[];retained=0
        for game in games:
            reads.guard()
            try:value=dict(board=board(frame,game['game_key'],view=view,filter=filter))
            except ValueError as exc:value=dict(error=dict(game_key=game['game_key'],reason=str(exc),availability=result_availability(dict(reasons=['calculation_read_failed']))))
            record=encoded(value);retained+=len(record)+256
            if retained+4096>reads.maximum_bytes:raise ValueError('current_slate_read_capacity')
            reads.guard(len(record));records.append(record)
        header=dict(version='predict-comparison-slate-2',view=view,filter=filter,policy=status['policy'],requested_policy=policy.to_dict(),
            sizing_scope='shared_default_selected_details',games=games,stopped=bool(frame['owner'].get('healthy') and not frame['owner'].get('active')),
            as_of=status.get('as_of',frame['at']),read_at=frame['at'],read_revision=frame['read_revision'],epoch=status['epoch'],
            read_expires_at=(stamp(utc())+timedelta(seconds=reads.ttl_seconds)).isoformat(),
            collection=dict(healthy=frame['owner'].get('healthy',False),active=frame['owner'].get('active',False),stopped=bool(frame['owner'].get('global_stopped',False))),
            background=dict(reasons=frame['reasons'],scope_complete=status.get('scope_complete',False)),
            bounds=dict(maximum_games=500,maximum_page_games=50,maximum_bytes=8*1024*1024),provider_requests=0,
            _evaluated=view!='odds' and status.get('version') in ('predict-latest-board-1','predict-latest-board-2','predict-latest-board-3'))
        authority=hashed([frame['read_authority'],bool(stopped)])
        # Release the full captured SQL frame before retaining the compact view.
        del frame
        captured=reads.capture(header,records,context=context,authority=authority)
        header=reads.decode(captured.header)
    games=header['games'];page=games[offset:offset+limit];boards=[];errors=[]
    for record in captured.records[offset:offset+limit]:
        reads.guard(len(record)*8)
        value=reads.decode(record)
        if 'board' in value:boards.append(value['board'])
        else:errors.append(value['error'])
    end=offset+len(page);complete=end>=len(games)
    evaluated=header.pop('_evaluated')
    out=dict(header,boards=boards,errors=errors,
        coverage=dict(total_games=len(games),offset=offset,limit=limit,returned_games=len(page),next_offset=None if complete else end,complete=complete))
    if storage is not None:out['storage']=storage
    out['availability']=combine([b['availability'] for b in boards],games=len(page),failures=[(e['game_key'],'calculation_read_failed') for e in errors],evaluated=evaluated)
    reads.guard()
    size=len(encoded(out))
    if size>8*1024*1024:
        reads.discard(captured.token)
        raise ValueError('slate_response_byte_capacity')
    # Recheck after rendering too: a Stop/reset cannot race an expensive capture
    # and leave newly returned pages carrying the withdrawn authority.
    reads.authorize(captured,slate_authority(db,stopped=stopped))
    reads.account(captured,offset=offset,limit=limit,size=size,complete=complete)
    return out,[]
