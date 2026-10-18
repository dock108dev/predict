"""Bounded SC03 selected/adopted frames, latest state and explicit replacement.

Detached two-leg capture only; no SQL, provider access or durable reports here.
The HTTP adapter supplies a fresh read-only SQL capture before publication.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import RLock, Event
from time import monotonic, perf_counter
from uuid import uuid4

from .current_dependencies import digest, instant
from .calculation_control import cancellation, CalculationStopped
from .scanner_finance import dependencies, opportunity_identity
from .scanner_destinations import Destinations
from .estimated_policy import RequestedTradePolicy
from app.storage.store import encoded

VERSION = 'predict-selected-ticket-1'
MAX_CLIENTS = 64
MAX_FRAMES = 128
MAX_BYTES = 16 * 1024**2
MAX_FRAME_BYTES = 256 * 1024
MAX_CAPTURE_BYTES = 2 * 1024**2
MAX_RESPONSE_BYTES = 1024 * 1024
TTL_SECONDS = 120
MAX_CALCULATIONS = 2
MAX_QUEUE = 4
DEADLINE_SECONDS = 2
SELECTOR_FIELDS = {'server_id', 'epoch', 'opportunity_id', 'row_id', 'dependency_revision',
                   'economic_revision', 'pair_id', 'engine_binding', 'readiness_policy_revision', 'discovery_policy_revision'}


def selector(projection, row):
    return dict(server_id=projection.server_id, epoch=projection.epoch,
                opportunity_id=row['opportunity_id'], row_id=row['id'],pair_id=row['pair_id'],
                dependency_revision=row['dependency_revision'], economic_revision=row['economic_revision'],
                engine_binding=projection.frame['engine_binding'],
                readiness_policy_revision=projection.frame['policy_revision'],
                discovery_policy_revision=projection.policy.revision)


class TicketError(ValueError):
    pass


class Tickets:
    def __init__(self, projection, *, calculate=None, fresh=None, fresh_selected=None, stopped=None, destinations=None,
                 clock=None, timer=monotonic, allow_authored=False, current_selected=None, collection_stopped=None):
        if calculate is None:
            from .scanner_ticket_finance import calculate
        self.projection=projection; self.calculate=calculate; self.fresh=fresh; self.fresh_selected=fresh_selected
        self.stopped=stopped or (lambda:projection.stopped)
        self.collection_stopped=collection_stopped or self.stopped
        self.destinations=destinations or Destinations(); self.clock=clock or projection.clock
        self.allow_authored=allow_authored
        self.current_selected=current_selected
        self.timer=timer; self.lock=RLock(); self.clients={}; self.jobs={}; self.closed=False
        self.executor=ThreadPoolExecutor(max_workers=MAX_CALCULATIONS, thread_name_prefix='predict-ticket')

    def cleanup(self):
        with self.lock:
            now=self.timer()
            for key, slot in list(self.clients.items()):
                if now>=slot['ttl']:
                    slot['cancel'].set(); del self.clients[key]

    def _bytes(self):
        return sum(len(encoded({k:(v.to_dict() if k=='policy' else v) for k,v in slot.items() if k not in ('cancel','ttl')}))
                   for slot in self.clients.values())

    def _get(self, client, ticket):
        self.cleanup()
        slot=self.clients.get(client)
        if slot is None or slot['ticket_id']!=ticket:raise TicketError('ticket_expired_or_disconnected')
        return slot

    def _capture(self, selected, *, initial=False, snapshot=None):
        if snapshot is None and self.current_selected is not None:
            snapshot=self.current_selected(selected)
        p=self.projection
        with p.lock:
            if self.closed or self.collection_stopped() or p.stopped:return None, 'stopped'
            if self.stopped():return None, 'temporarily_unavailable'
            if selected['row_id'] not in tuple(selected['opportunity_id']+':'+c for c in ('covered_outcome_arb','conditional_hedge','ev')):
                return None,'binding_changed'
            if selected['server_id']!=p.server_id or selected['epoch']!=p.epoch:
                return None, 'obsolete_epoch'
            frame, inputs = (p.frame,p.inputs) if snapshot is None else snapshot
            if not frame:return None,'temporarily_unavailable'
            if frame['epoch']!=selected['epoch']:return None,'obsolete_epoch'
            if frame['engine_binding']!=selected['engine_binding'] or frame['policy_revision']!=selected['readiness_policy_revision'] or p.policy.revision!=selected['discovery_policy_revision']:
                return None,'binding_changed'
            by_id={i['id']:i for i in frame['instruments']}
            matches=[pair for pair in frame['pairs'] if pair['id']==selected['pair_id'] and all(k in by_id for k in pair['legs']) and
                     opportunity_identity([by_id[k] for k in pair['legs']])==selected['opportunity_id']]
            if len(matches)!=1:return None,'withdrawn' if not matches else 'binding_changed'
            pair=matches[0]
            if instant(self.clock())>=instant(pair['expires_at']):return None,'expired'
            if pair['input_check']['state']!='ready':return None,'temporarily_unavailable'
            if any(k not in inputs for k in pair['legs']):return None,'temporarily_unavailable'
            instruments={k:by_id[k] for k in pair['legs']}; x={k:inputs[k] for k in pair['legs']}
            dep=dependencies(pair,instruments,x,p.policy,frame['engine_binding'])
            row=p.rows.get(selected['row_id'])
            if initial and (row is None or row['opportunity_id']!=selected['opportunity_id'] or
                            row['dependency_revision']!=selected['dependency_revision'] or
                            row['economic_revision']!=selected['economic_revision'] or dep!=selected['dependency_revision']):
                raise TicketError('selection_revisions_changed')
            value=dict(pair=pair,instruments=instruments,inputs=x,dependency_revision=dep,
                discovery=deepcopy(row),engine_binding=frame['engine_binding'],
                readiness_policy_revision=frame['policy_revision'],generation=p.generation,
                input_revision=frame['input_revision'],readiness_revision=frame['revision'],
                sql_post_commit_observation=deepcopy(p.sql_observation))
            if len(encoded(value))>MAX_CAPTURE_BYTES:raise TicketError('ticket_capture_capacity')
            return deepcopy(value),None

    def _latest(self, slot, capture=None, reason=None):
        if capture is None and reason is None:capture,reason=self._capture(slot['selection'])
        return dict(state=reason or 'available', dependency_revision=None if capture is None else capture['dependency_revision'],
            discovery=None if capture is None else capture['discovery'], checked_at=self.clock(),
            input_revision=None if capture is None else capture['input_revision'])

    def _status(self, slot, latest):
        selected=slot['selected']; replacement=slot['replacement']; why=latest['state']
        if why!='available':
            return ('withdrawn' if why in ('withdrawn','obsolete_epoch','binding_changed') else why),False
        current = replacement or selected
        if current and instant(self.clock())>=instant(current['expires_at']):return 'expired',False
        if current is None:return 'temporarily_unavailable',False
        category=slot['selection']['row_id'].rsplit(':',1)[-1]
        if category not in [r['category'] for r in current['result']['categories'] if r.get('current',True)]:return 'no_longer_qualifying',False
        if replacement is not None or selected['dependency_revision']!=latest['dependency_revision']:
            return 'revised',False
        ready=selected['ready'] and selected['policy_revision']==slot['policy'].revision and not slot.get('reason')
        return ('unchanged' if ready else 'temporarily_unavailable'),ready

    def _wire(self, slot, latest=None):
        latest=latest or self._latest(slot)
        state,ready=self._status(slot,latest)
        a=slot['selected'];b=slot['replacement']
        changes=[]
        if a and b:
            for key in ('policy_revision','dependency_revision'):
                if a[key]!=b[key]:changes.append(dict(field=key,before=a[key],after=b[key]))
            for key in ('funding','metrics','manual_legs','categories','states'):
                before=a['result'].get(key);after=b['result'].get(key)
                if before!=after:changes.append(dict(field=key,before=before,after=after))
        out=dict(version=VERSION,client_id=slot['client_id'],ticket_id=slot['ticket_id'],sequence=slot['sequence'],
            selection=slot['selection'],state=state,reason=slot.get('reason'),ready_for_manual_action=ready,
            unavailable_reasons=sorted(set(([slot['reason']] if slot.get('reason') else []) +
                ([d['reason'] for d in (b or a)['destinations'] if d['reason']] if b or a else []) +
                ((b or a)['result'].get('reasons',[]) if b or a else []))),
            selected_frame=deepcopy(a),latest=latest,replacement_frame=deepcopy(b),changes=changes,
            revalidated_at=slot.get('revalidated_at'),ttl_seconds=TTL_SECONDS,provider_requests=0,
            limits=dict(frames=MAX_FRAMES,total_bytes=MAX_BYTES,frame_bytes=MAX_FRAME_BYTES,
                        capture_bytes=MAX_CAPTURE_BYTES,response_bytes=MAX_RESPONSE_BYTES,
                        concurrent_calculations=MAX_CALCULATIONS,queue=MAX_QUEUE,deadline_seconds=DEADLINE_SECONDS))
        if len(encoded(out))>MAX_RESPONSE_BYTES:raise TicketError('ticket_response_capacity')
        return out

    def inspect(self, client, ticket):
        with self.lock:return self._wire(self._get(client,ticket))

    def _policy(self, amount):
        p=self.projection.policy
        fields={k:getattr(p,k) for k in RequestedTradePolicy.__dataclass_fields__ if hasattr(p,k)}
        fields.update(version='predict-estimate-policy-3',sizing_mode='requested_trade')
        if amount is not None:
            if not isinstance(amount,str) or len(amount)>32:raise TicketError('amount_exact_string_required')
            fields['capital_ceiling_usd']=amount
        return RequestedTradePolicy(**fields)

    def prepare(self, command, *, snapshot=None):
        if not isinstance(command,dict):raise TicketError('ticket_command_invalid')
        op=command.get('operation');allowed={'client_id','sequence','operation','selection','ticket_id','amount','replacement_frame_id'}
        if set(command)-allowed or op not in ('select','revalidate','adopt','close'):raise TicketError('ticket_command_invalid')
        valid={'select':{'selection','amount'},'revalidate':{'ticket_id','amount'},'adopt':{'ticket_id','replacement_frame_id'},'close':{'ticket_id'}}
        if set(command)-({'client_id','sequence','operation'}|valid[op]):raise TicketError('ticket_command_invalid')
        client=command.get('client_id');seq=command.get('sequence')
        if not isinstance(client,str) or not 16<=len(client)<=64 or not all(c.isalnum() or c in '-_' for c in client):raise TicketError('ticket_client_invalid')
        if type(seq) is not int or not 0<seq<2**53:raise TicketError('ticket_sequence_invalid')
        with self.lock:
            self.cleanup();previous=self.clients.get(client)
            import shutil, resource, sys
            from pathlib import Path
            rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
            if shutil.disk_usage(Path(__file__).resolve()).free<1024**3 or rss>=768*1024**2:
                raise TicketError('ticket_process_or_disk_guard')
            if previous and seq<=previous['sequence']:raise TicketError('ticket_superseded')
            if op=='select':
                selected=command.get('selection')
                if not isinstance(selected,dict) or set(selected)!=SELECTOR_FIELDS or any(not isinstance(v,str) or len(v)>256 for v in selected.values()):raise TicketError('ticket_selection_invalid')
                _,selection_reason=self._capture(selected,initial=True)
                if selection_reason:raise TicketError('selection_'+selection_reason)
                if previous is None and len(self.clients)>=MAX_CLIENTS:raise TicketError('ticket_client_capacity')
                policy=self._policy(command.get('amount'))
                slot=dict(client_id=client,ticket_id=str(uuid4()),selection=deepcopy(selected),selected=None,replacement=None,
                    policy=policy,sequence=seq,cancel=Event(),ttl=self.timer()+TTL_SECONDS,reason=None)
            else:
                slot=self._get(client,command.get('ticket_id'))
                policy=self._policy(command.get('amount')) if op=='revalidate' else slot['policy']
            if op=='adopt':
                candidate=slot['replacement']; capture,reason=self._capture(slot['selection'],snapshot=snapshot)
                if candidate is None or candidate['id']!=command.get('replacement_frame_id') or reason or capture['dependency_revision']!=candidate['dependency_revision']:
                    raise TicketError('replacement_no_longer_current')
                if candidate['policy_revision']!=slot['policy'].revision:raise TicketError('replacement_amount_changed')
            if op in ('select','revalidate') and len(self.jobs)>=MAX_CALCULATIONS+MAX_QUEUE:
                raise TicketError('ticket_calculation_capacity')
            if previous:previous['cancel'].set()
            if op=='revalidate':slot['replacement']=None
            slot.update(sequence=seq,policy=policy,cancel=Event(),ttl=self.timer()+TTL_SECONDS,reason=None)
            self.clients[client]=slot
            if op=='close':
                slot['cancel'].set();del self.clients[client]
                return None,dict(version=VERSION,state='closed',client_id=client,ticket_id=slot['ticket_id'],sequence=seq,provider_requests=0)
            if op=='adopt':
                slot['selected']=slot['replacement'];slot['replacement']=None
                return None,self._wire(slot)
            job=dict(slot=slot,sequence=seq,cancel=slot['cancel'],initial=op=='select',policy=policy,started=perf_counter())
            key=str(uuid4());self.jobs[key]=job
            future=self.executor.submit(self._run,job)
            def done(_):
                with self.lock:self.jobs.pop(key,None)
            future.add_done_callback(done)
            return (future,job),None

    def _cancelled(self,job):
        slot=job['slot']
        return (self.closed or job['cancel'].is_set() or self.stopped() or
                self.timer()>=slot['ttl'] or perf_counter()-job['started']>=DEADLINE_SECONDS)

    def _fresh(self, capture):
        # Explicit legacy fixture injection stays available. The ordinary HTTP
        # owner supplies only the bounded selected-pair SQL capture callback.
        if self.fresh:return self.fresh()
        if self.fresh_selected:return self.fresh_selected(capture)
        return None

    def _run(self,job):
        slot=job['slot'];started=perf_counter()
        try:
            with cancellation(lambda:self._cancelled(job)):
                capture_start=perf_counter();capture,reason=self._capture(slot['selection'],initial=job['initial'])
                capture_ms=(perf_counter()-capture_start)*1000
                if reason:return self._finish(job,None,None,reason)
                old=slot['selected']
                if old and old['dependency_revision']==capture['dependency_revision'] and old['policy_revision']==job['policy'].revision:
                    value=deepcopy(old);calculation_ms=0
                else:
                    at=self.clock();calculation_start=perf_counter()
                    result=self.calculate(capture['pair'],capture['instruments'],capture['inputs'],at=at,policy=job['policy'])
                    calculation_ms=(perf_counter()-calculation_start)*1000
                    destinations=[self.destinations.resolve(capture['instruments'][k]) for k in sorted(capture['pair']['legs'])]
                    value=dict(id=str(uuid4()),dependency_revision=capture['dependency_revision'],
                        economic_revision=digest(result),policy_revision=job['policy'].revision,
                        engine_binding=capture['engine_binding'],readiness_policy_revision=capture['readiness_policy_revision'],
                        calculation_started_at=at,calculated_at=self.clock(),expires_at=capture['pair']['expires_at'],
                        source_clocks=[capture['instruments'][k]['clocks'] for k in sorted(capture['pair']['legs'])],
                        source_model_inputs={k:dict(quote=capture['inputs'][k]['quote'],profiles=capture['inputs'][k]['profiles']) for k in sorted(capture['pair']['legs'])},
                        result=result,destinations=destinations,ready=bool(result['settlement_complete'] and all(d['state']=='verified' and (self.allow_authored or d['provenance']['evidence_class']=='reviewed_source') for d in destinations)),
                        causal=dict(input_revision=capture['input_revision'],readiness_revision=capture['readiness_revision'],
                            sql_post_commit_observation=capture['sql_post_commit_observation']),
                        timing=dict(capture_ms=capture_ms,calculation_ms=calculation_ms))
                    if len(encoded(value))>MAX_FRAME_BYTES:raise TicketError('ticket_frame_capacity')
                # The fresh SQL capture finishes before publishing. Compare exact
                # pair dependency so unrelated-event churn cannot starve selection.
                fresh_start=perf_counter();snapshot=self._fresh(capture)
                current,reason=self._capture(slot['selection'],snapshot=snapshot)
                validation_ms=(perf_counter()-fresh_start)*1000
                if current and (current['generation']!=capture['generation'] or current['dependency_revision']!=capture['dependency_revision']):
                    value=None;reason='dependencies_changed_during_calculation'
                if self._cancelled(job):raise CalculationStopped()
                return self._finish(job,value,current,reason,timing=dict(capture_ms=capture_ms,calculation_ms=calculation_ms,
                    validation_ms=validation_ms,total_backend_ms=(perf_counter()-started)*1000))
        except CalculationStopped:
            if job['cancel'].is_set():raise TicketError('ticket_superseded') from None
            reason=('stopped' if self.closed or self.collection_stopped() or self.projection.stopped else
                    'temporarily_unavailable' if self.stopped() else 'calculation_deadline')
            return self._finish(job,None,None,reason)
        except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
            reason=str(exc)
            if len(reason)>160 or not all(c.isalnum() or c in '_; :.-' for c in reason):reason=type(exc).__name__
            return self._finish(job,None,None,'ticket_calculation_unavailable:'+reason)

    def _finish(self,job,value,capture,reason,timing=None):
        slot=job['slot']
        with self.lock:
            if self.clients.get(slot['client_id']) is not slot or slot['sequence']!=job['sequence'] or job['cancel'].is_set():raise TicketError('ticket_superseded')
            if value is not None:
                boundary,boundary_reason=self._capture(slot['selection'])
                if boundary_reason or boundary['generation']!=capture['generation'] or boundary['dependency_revision']!=value['dependency_revision']:
                    value=None;reason=boundary_reason or 'dependencies_changed_before_publication'
            if value is not None:
                if job['initial']:slot['selected']=value
                elif slot['selected'] is None or value['id']!=slot['selected']['id']:slot['replacement']=value
                else:slot['replacement']=None
            slot['reason']=reason;slot['revalidated_at']=self.clock()
            if self._bytes()>MAX_BYTES:
                slot['selected']=None;slot['replacement']=None;slot['reason']='ticket_total_capacity'
                reason='temporarily_unavailable'
            latest=self._latest(slot,capture,reason)
            if latest['state'] not in ('available','stopped','expired','withdrawn','obsolete_epoch','binding_changed'):
                latest['state']='temporarily_unavailable'
            result=self._wire(slot,latest)
            result['timing']=timing
            return result

    async def command(self,command):
        if isinstance(command,dict) and command.get('operation')=='adopt' and (self.fresh or self.fresh_selected):
            cancelled=Event();started=perf_counter()
            def adopt():
                try:
                    with cancellation(lambda:self.closed or self.stopped() or cancelled.is_set() or perf_counter()-started>=DEADLINE_SECONDS):
                        with self.lock:
                            slot=self._get(command.get('client_id'),command.get('ticket_id'))
                            selected=deepcopy(slot['selection'])
                        capture,reason=self._capture(selected)
                        if reason:raise TicketError('replacement_no_longer_current')
                        snapshot=self._fresh(capture)
                        if self.closed or self.stopped() or cancelled.is_set() or perf_counter()-started>=DEADLINE_SECONDS:
                            raise TicketError('ticket_adoption_cancelled')
                        return self.prepare(command,snapshot=snapshot)[1]
                except CalculationStopped:
                    raise TicketError('ticket_adoption_cancelled') from None
            with self.lock:
                if len(self.jobs)>=MAX_CALCULATIONS+MAX_QUEUE:raise TicketError('ticket_calculation_capacity')
                key=str(uuid4());self.jobs[key]=dict(cancel=cancelled)
                future=self.executor.submit(adopt)
                def done(_):
                    with self.lock:self.jobs.pop(key,None)
                future.add_done_callback(done)
            try:return await asyncio.wrap_future(future)
            except asyncio.CancelledError:
                cancelled.set();future.cancel();raise
        task,result=self.prepare(command)
        if task is None:return result
        future,job=task
        try:return await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            job['cancel'].set();future.cancel();raise

    async def close(self):
        self.closed=True
        with self.lock:
            for slot in self.clients.values():slot['cancel'].set()
            for job in self.jobs.values():job['cancel'].set()
            self.clients.clear()
        await asyncio.to_thread(self.executor.shutdown,wait=True,cancel_futures=True)
