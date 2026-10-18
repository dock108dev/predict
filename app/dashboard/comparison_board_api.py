"""Current-row comparison reads and transient financial calculation endpoints."""
import asyncio
from aiohttp import web
from app.storage.store import connect, encoded, stamp
from app.storage.current_games import utc
from app.storage.comparison_board import discover, calculate_current, context_identity, observation_identity
from app.comparison.estimated_policy import load
from .query_policy import calculation_policy
from .comparison_board import details, entries, quote_key, freshness, price, benchmark
from .local_security import PublicRequestError, public_reason
from .comparison_slate import MAX_BYTES
from app.comparison.calculation_availability import result_availability
from app.storage.latest_board import snapshot, board, read_context, selected_dependencies
from app.storage.slate_reads import CapturedReads

from .read_work import ReadWork, Trace, TRACE, stage, database_deadline, ReadDeadline, TimedResponse

SLATE_READS = web.AppKey('comparison_slate_reads', CapturedReads)
READ_WORK = web.AppKey('comparison_read_work', ReadWork)


PUBLIC_READ_REASONS = frozenset((
    'current_inputs_changed_or_removed', 'current_selection_removed',
    'background_runtime_authority_unavailable', 'background_calculation_unavailable',
    'background_observation_unavailable', 'estimate_unavailable',
    'current_slate_read_expired', 'current_slate_read_capacity',
    'current_slate_read_authority_changed', 'current_slate_read_context_changed',
    'current_slate_read_token_required', 'current_slate_changed',
    'slate_page_capacity', 'slate_response_byte_capacity', 'board_response_byte_capacity',
    'current_read_memory_capacity',
))


def mount(app,provider):
    from .scanner_api import mount as mount_scanner
    mount_scanner(app,provider)
    work=ReadWork();app[READ_WORK]=work
    read_frames=CapturedReads()
    read_frames.guard=work.guard
    app[SLATE_READS]=read_frames
    async def captured_reads_lifecycle(_app):
        async def expire():
            while True:
                await asyncio.sleep(5)
                read_frames.cleanup()
        cleanup=asyncio.create_task(expire())
        try:yield
        finally:
            cleanup.cancel()
            try:await cleanup
            except asyncio.CancelledError:pass
            await work.close()
            read_frames.clear()
    app.cleanup_ctx.append(captured_reads_lifecycle)
    def stopped():return provider.closed or provider.closing or not provider.dispatch
    def read(req,p):
        view=req.match_info['view']
        if view=='coverage':
            from app.storage.coverage_latest import read as coverage_read
            with connect() as db:
                database_deadline(db)
                return coverage_read(db,resource_guard=work.guard,**{k:req.query[k] for k in ('league','venue','market','period') if req.query.get(k)})
        if view=='readiness':
            from copy import deepcopy
            from app.comparison.scanner_readiness import Selection
            from app.storage.scanner_readiness import read as readiness_read
            selected=Selection(**{k:tuple(req.query[k].split(',')) for k in req.query})
            states=deepcopy(provider.states)
            if stopped():
                states={v:dict(state='stopped') for v in selected.venues}
            with connect() as db:
                database_deadline(db)
                return readiness_read(db,config=deepcopy(provider.config),authority=provider.config.get('authority'),
                                      at=utc(),selection=selected,source_status=states)
        with connect() as db:
            database_deadline(db)
            if view=='slate':
                from .comparison_slate import read as slate_read
                storage=provider.database.status()
                out=slate_read(db,p,view=req.query.get('view','odds'),filter=req.query.get('filter','positive'),stopped=stopped(),offset=int(req.query.get('offset','0')),limit=int(req.query.get('limit','25')),expected_revision=req.query.get('expected_revision'),read_token=req.query.get('read_token'),read_frames=read_frames,storage=storage)[0]
                out['storage']=storage
                return out
            with stage('database_snapshot'):
                latest=snapshot(db,game=req.query.get('game') if req.query.get('game','').startswith('combined:') and view in ('inputs','details') else None,resource_guard=work.guard)
            if view=='games':
                return dict(version='predict-board-catalog-2',games=latest['status']['games'],
                    limits=dict(maximum_games=500),read_revision=latest['read_revision'],
                    epoch=latest['status']['epoch'],stopped=not latest['owner'].get('active'),provider_requests=0)
            game=req.query['game']
            candidates=[g for g in latest['status']['games'] if g['game_key']==game or ':' in game and list(game.split(':',1)) in g['members']]
            if len(candidates)!=1:raise ValueError('current_inputs_changed_or_removed')
            game=candidates[0]['game_key']
            if view not in ('details','inputs'):
                return board(latest,game,view=view,filter=req.query.get('filter','positive'))
            if view=='details' and (not latest['owner'].get('active') or 'background_calculations_unavailable' in latest['reasons']):
                raise ValueError('background_runtime_authority_unavailable')
            saved=latest['rows'].get(game)
            if saved is None:raise ValueError('background_calculation_unavailable')
            selection_identity=saved['facts'].get('observation_context',saved['facts']['context']) if view=='inputs' else saved['facts']['context']
            if selection_identity is None:raise ValueError('estimate_unavailable')
            if req.query.get('context_id')!=selection_identity['context_id']:raise ValueError('current_inputs_changed_or_removed')
            with db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                with stage('dependency_capture'):
                    dependency=saved['facts'].get('publication_dependencies')
                    captured_dependency,event_ids=selected_dependencies(db,dependency,stopped=stopped())
                with stage('database_capture_and_prepare'):
                    context=read_context(db,event_ids=event_ids,resource_guard=work.guard)
                base=load()
                if view=='inputs':
                    with stage('selected_bundle'):
                        bundle=context.observation_bundles(game=game,benchmark_venue=base.benchmark_venue)[0]
                    with stage('identity_verification'):
                        identity=observation_identity(bundle,context)
                        if identity!=selection_identity:raise ValueError('current_inputs_changed_or_removed')
                else:
                    selected=discover(context.store,benchmark_venue=base.benchmark_venue,context=context,game=game)[0]
                    if context_identity(selected,base,context)!=selection_identity:raise ValueError('current_inputs_changed_or_removed')
                    bundle=selected if p.benchmark_venue==base.benchmark_venue else discover(context.store,benchmark_venue=p.benchmark_venue,context=context,game=game)[0]
                    identity=context_identity(bundle,p,context)
                bundle['calculation_context']=identity
        # Captured typed inputs are detached before any financial calculation.
        if view=='inputs':
            quote=req.query.get('quote')
            selected=next(((e,g,q) for e,g,q in entries(bundle['state_inputs']) if quote_key(q)==quote),None)
            if selected is None:raise ValueError('current_selection_removed')
            event,group,q=selected
            observed=price(q)
            out=dict(quote_revision=observed['quote_revision'],observation_revision=observed['observation_revision'],version='predict-board-inputs-2',game_key=bundle['game_key'],quote_id=quote,calculation_context=identity,evidence=dict(event=event['title'],event_metadata={k:event[k] for k in ('sport','league','title','start_at','participants')},market={k:group[k] for k in ('market','period','period_boundary','line','anchor_participant')},selection=q['binding']['selection'],source=q['source'],original=q['original'],times=q['times'],native_contract=q.get('native_contract'),book_confirmation=q.get('book_confirmation'),provenance=q.get('provenance'),depth=observed['observed_depth']['levels'],observed_depth=observed['observed_depth'],provider_clocks=q.get('provider_clocks'),source_state=q['state'],quote_revision=q['revision'],observation_revision=observed['observation_revision'],freshness=freshness(q,{},bundle['state_inputs']['events'][0],stamp(context.at),financial=False),estimate_availability=saved['facts'].get('estimate_availability'),benchmark=benchmark(bundle,context.at),benchmark_reason=bundle.get('benchmark_reason'),representation=bundle['representation']),provider_requests=0)
        elif view=='details':
            value=calculate_current(bundle,p,context=context,details=True,selected_quote=req.query.get('quote'),selected_pair=req.query.get('pair'))
            out=details(value,quote=req.query.get('quote'),pair=req.query.get('pair'),at=utc(),current=bundle['state_inputs'],stopped=stopped())
            out['selection_context']=selection_identity
            out['original_inputs_identity'].update(context_id=selection_identity['context_id'],policy_revision=selection_identity['policy_revision'])
            with stage('dependency_verification'),connect() as verify,verify.transaction():
                verify.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                database_deadline(verify)
                if selected_dependencies(verify,dependency,stopped=stopped())[0]!=captured_dependency:
                    raise ValueError('current_inputs_changed_or_removed')
        if view=='inputs':
            with stage('dependency_verification'),connect() as verify,verify.transaction():
                verify.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                database_deadline(verify)
                if selected_dependencies(verify,dependency,stopped=stopped())[0]!=captured_dependency:
                    raise ValueError('current_inputs_changed_or_removed')
        if len(encoded(out))>MAX_BYTES:raise ValueError('board_response_byte_capacity')
        return out
    def controlled_read(req,p):
        from app.comparison.calculation_control import cancellation,checkpoint,CalculationStopped
        from time import monotonic
        initially_stopped=stopped()
        next_control_check=0
        def cancelled():
            nonlocal next_control_check
            if TRACE.get().stopped():return True
            now=monotonic()
            if now>=next_control_check:
                next_control_check=now+.05
                if not initially_stopped and stopped():return True
            return False
        with cancellation(cancelled):
            out=read(req,p)
            try:
                # Always check the final boundary, even when capture completed
                # inside the 50 ms checkpoint polling interval.
                if not initially_stopped and stopped():raise CalculationStopped('saved_calculation_stopped')
                checkpoint()
            except BaseException:
                if req.match_info['view']=='slate':read_frames.discard(out.get('read_token'))
                raise
            return out
    async def handle(req):
        view=req.match_info['view']
        if view=='history' or req.query.get('history')=='true' or req.query.get('result_id'):
            return web.json_response(dict(error='sports_history_unavailable',reason='Ordinary sports history was retired; select a current comparison.',provider_requests=0),status=410)
        allowed={'game','amount','ceiling','buffer','sizing_mode','benchmark_venue','benchmark_method','filter','context_id','quote','pair'}
        if view=='slate':allowed=(allowed-{'game','context_id','quote','pair'})|{'view','offset','limit','expected_revision','read_token'}
        if view=='readiness':allowed={'venues','sports','leagues','markets','periods'}
        if view=='coverage':allowed={'league','venue','market','period'}
        if view not in ('coverage','readiness','games','slate','odds','ev','arbs','details','inputs') or set(req.query)-allowed:raise PublicRequestError('Unsupported current comparison query')
        if view=='games' and req.query:raise PublicRequestError('Catalog does not accept calculation settings')
        if view not in ('coverage','readiness','games','slate') and not 1<=len(req.query.get('game',''))<=256:raise PublicRequestError('Exact bounded occurrence required')
        if view=='slate' and req.query.get('view','odds') not in ('odds','ev','arbs'):raise PublicRequestError('Unsupported slate view')
        if req.query.get('filter','positive') not in ('positive','all','hedges'):raise PublicRequestError('Unsupported comparison filter')
        if view in ('details','inputs') and not req.query.get('context_id'):raise PublicRequestError('Expected current context required')
        if any(len(v)>256 for v in req.query.values()):raise PublicRequestError('Comparison query value capacity')
        if view=='readiness':
            from app.comparison.scanner_readiness import Selection
            try:Selection(**{k:tuple(req.query[k].split(',')) for k in req.query})
            except ValueError as exc:raise PublicRequestError(str(exc)) from None
        p=None if view in ('coverage','readiness') else calculation_policy(req.query,load())
        trace=Trace('selected' if view in ('inputs','details') else 'ordinary')
        token=TRACE.set(trace)
        def reply(value, *, status):return TimedResponse(trace=trace,body=encoded(value),content_type='application/json',status=status)
        try:
            def render():
                out=controlled_read(req,p)
                with stage('serialization'):
                    body=encoded(out)
                    if len(body)>MAX_BYTES:raise ValueError('board_response_byte_capacity')
                return body
            body=await work.run(view in ('inputs','details'),render,trace)
            trace.values['outcome']='success'
            timing=', '.join(f"{key};dur={value}" for key,value in trace.values['stages_ms'].items())
            return TimedResponse(trace=trace,body=body,content_type='application/json',headers={'Server-Timing':timing})
        except ReadDeadline as exc:
            busy=str(exc)=='current_read_busy'
            return reply(dict(error=str(exc),reason=str(exc),provider_requests=0),status=429 if busy else 504)
        except ValueError as exc:
            trace.values['outcome']='refused'
            reason=public_reason(exc,allowed=PUBLIC_READ_REASONS,fallback='current_inputs_unavailable',
                operation='comparison_read_refused',logger=__name__)
            return reply(dict(error='current_inputs_unavailable',reason=reason,availability=result_availability(dict(reasons=['calculation_read_failed'])),provider_requests=0),status=409)
        except Exception as exc:
            from app.comparison.calculation_control import CalculationStopped
            if isinstance(exc,CalculationStopped):
                read_frames.clear()
                return reply(dict(error='current_read_stopped',reason='Updates stopped during calculation; reopen the current view.',provider_requests=0),status=409)
            return reply(dict(error='database_unavailable',reason=type(exc).__name__,availability=result_availability(dict(reasons=['calculation_read_failed'])),provider_requests=0),status=503)
        finally:TRACE.reset(token)
    async def diagnostics(req):return web.json_response(work.diagnostics())
    app.router.add_get('/api/boards/read-diagnostics',diagnostics)
    app.router.add_get('/api/boards/{view}',handle)
    async def coverage_handle(req):
        # The ordinary lane, timeout and cancellation owner also bound Coverage.
        clone=req.clone();clone.match_info['view']='coverage'
        return await handle(clone)
    app.router.add_get('/api/coverage',coverage_handle)
