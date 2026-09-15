"""One supervised run, a hard independent deadline and bounded worker handoff."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from time import monotonic
from app.dashboard.bounds import CaptureQueue
from app.dashboard.pipeline import Pipeline
from app.dashboard.live import LiveSource

DEFAULTS=dict(seconds=60,markets=2,receipts=1000,storage_bytes=128*1024*1024)


def limits_for(values):
    if set(values)-{'seconds','markets','receipts'}:raise ValueError('Unknown scan option')
    result={**DEFAULTS,**values}
    for k,lo,hi in [('seconds',5,60),('markets',1,4),('receipts',10,1000)]:
        if type(result[k]) is not int or not lo<=result[k]<=hi:raise ValueError('Invalid scan limit')
    return result


class Controller:
    def __init__(self,pipeline_factory=Pipeline,source_factory=LiveSource):
        self.pipeline_factory=pipeline_factory;self.source_factory=source_factory
        self.task=None;self.sid=None;self.state='idle';self.view={};self.status={};self.error=None;self.depth_result=None
        self.depth_busy=False;self.limits=dict(DEFAULTS);self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='capture-worker')
        self.compute_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='view-compute')
        self.refresh_task=None;self.refresh_writer=None;self.stop_budget=None;self.generation=0;self.eligibility_epoch=0;self.published_sequence=0;self.refresh_accounting={};self.refresh_samples=[]
        self.stop_event=asyncio.Event();self.queue=CaptureQueue();self.messages=0;self.network_bytes=0;self.accepting=False
        self.stop_record=None;self.later_causes=[];self.ledger=[];self.rejections={};self.inflight=False;self.producers_closed=False;self.depth_task=None;self.stop_clock=None;self.finalized_at=None;self.producers_closed_at=None
        self.reason='';self.mode='live';self.started_at=None;self.worker=None;self.writer_task=None

    async def work(self,fn,*args):
        item_id=getattr(self,'active_item_id',None)
        def owned():
            if self.worker:
                self.worker.capture_item_id=item_id
                if hasattr(self.worker,'set_deadline'):
                    self.worker.set_deadline(self.stop_clock+(10 if fn.__name__ in ('finish','failure_journal','close_resources') else 8.5) if self.stop_clock else None)
            return fn(*args)
        return await asyncio.shield(asyncio.get_running_loop().run_in_executor(self.executor,owned))

    def health(self,venue,state,note):
        if state!='connected':self.invalidate_eligibility()
        self.status[venue]=dict(state=state,note=note,at=datetime.now(timezone.utc).isoformat())

    def invalidate_eligibility(self):
        from app.dashboard.views import age_view
        self.eligibility_epoch+=1
        self.view=age_view(self.view,active=False)
        self.depth_result=None

    def offer(self,item):
        if item[0]=='disconnect':self.invalidate_eligibility()
        rejection='acceptance_closed'
        if self.accepting:
            try:
                if len(self.ledger)>=1024:raise OverflowError('item limit')
                self.queue.put_nowait(item)
                self.ledger.append(dict(id=len(self.ledger),object_id=id(item),kind=item[0],state='accepted'))
                return True
            except (asyncio.QueueFull,OverflowError):
                rejection=self.queue.last_rejection or 'item_limit'
                self.request_stop('Backpressure: bounded queue filled; capture gap recorded',initiator='capacity')
        self.rejections[rejection]=self.rejections.get(rejection,0)+1
        return False

    def request_stop(self,reason,initiator=None):
        self.accepting=False
        self.invalidate_eligibility()
        record=dict(reason=reason,at=datetime.now(timezone.utc).isoformat(),initiator=initiator or ('owner' if reason in ('Stopped by you','Stopped by owner') else 'controller'))
        if self.stop_record is None:
            self.stop_record=record;self.reason=reason;self.stop_clock=monotonic()
            if self.stop_budget:self.stop_budget.stop(self.stop_clock)
        elif reason!=self.reason and not any(x['reason']==reason for x in self.later_causes):self.later_causes.append(record)
        self.stop_event.set()
        if self.state in ('starting','scanning'):self.state='stopping'

    async def start(self,mode,values):
        if self.task and not self.task.done():raise RuntimeError('A scan is already running or stopping')
        if mode not in ('live','synthetic'):raise ValueError('Choose Live or Synthetic demo')
        self.limits=limits_for(values);self.mode=mode;self.state='starting';self.error=None;self.depth_result=None
        from app.dashboard.refresh import StopBudget
        self.stop_budget=StopBudget();self.refresh_writer=None;self.refresh_samples=[]
        self.generation+=1;self.published_sequence=0;self.refresh_task=None
        self.refresh_accounting=dict(submitted=0,completed=0,published=0,discarded=0,failed=0,max_inflight=0,pending_signal=False)
        self.sid=None;self.view={};self.status={};self.queue=CaptureQueue();self.stop_event=asyncio.Event()
        self.messages=0;self.network_bytes=0;self.accepting=True;self.reason='';self.started_at=datetime.now(timezone.utc).isoformat()
        self.stop_record=None;self.stop_clock=None;self.later_causes=[];self.ledger=[];self.rejections={};self.producers_closed=False;self.depth_task=None;self.producers_closed_at=None;self.finalized_at=None
        self.task=asyncio.create_task(self._run())
        return dict(state=self.state)

    async def _deadline(self):
        await asyncio.sleep(self.limits['seconds']);self.request_stop('Scan deadline reached',initiator='deadline')

    async def _consume(self):
        while not (self.producers_closed and self.queue.empty()):
            if self.stop_clock is not None and monotonic()-self.stop_clock>=8.5:
                self.request_stop('Drain budget exhausted',initiator='drain');return
            try:item=await asyncio.wait_for(self.queue.get(),.025)
            except TimeoutError:
                if not self.stop_event.is_set():
                    try:await self._refresh()
                    except Exception:
                        self.error='Persistence or calculation failed. Scan stopped; coverage is incomplete.'
                        self.request_stop(self.error,initiator='writer');return
                continue
            row=next((r for r in self.ledger if r['object_id']==id(item) and r['state']=='accepted'),None)
            if row:row['state']='inflight'
            self.active_item_id=row['id'] if row else None
            kind,value=item;self.inflight=True
            try:
                if kind=='book':view=await self.work(self.worker.book,value)
                elif kind=='disconnect':view=await self.work(self.worker.disconnect,*value)
                elif kind=='demo':view=await self.work(self.worker.synthetic_tick,value)
                else:
                    await self.work(self.worker.store.event,self.sid,'gap',value);view=None
                if row:row['state']='processed'
                if view:self.view=view
                # No full view calculation for each observation; receipts retain all inputs.
                if not self.stop_event.is_set():await self._refresh()
            except Exception:
                if row and row['state']!='processed':row['state']='unprocessed'
                self.error='Persistence or calculation failed. Scan stopped; coverage is incomplete.'
                self.request_stop(self.error,initiator='writer');return
            finally:self.active_item_id=None;self.inflight=False;self.queue.task_done()

    def publish_refresh(self,result,generation,epoch):
        if (not result or generation!=self.generation or result['sid']!=self.sid
            or epoch!=self.eligibility_epoch or self.stop_event.is_set()
            or result['view']['sequence']<=self.published_sequence):
            self.refresh_accounting['discarded']+=1
            return False
        self.view=result['view'];self.published_sequence=self.view['sequence']
        self.refresh_accounting['published']+=1
        return True

    async def _compute_refresh(self,snapshot,generation,epoch):
        from app.dashboard.refresh import compute
        submitted=monotonic()
        try:
            if self.refresh_writer:
                import pickle
                result=await asyncio.shield(asyncio.get_running_loop().run_in_executor(self.compute_executor,self.refresh_writer.run,snapshot))
                saved=pickle.loads(result)
            else:
                result=await asyncio.shield(asyncio.get_running_loop().run_in_executor(self.compute_executor,compute,snapshot))
                saved=await self.work(self.worker.persist_refresh,result)
            computed=monotonic()
            published=monotonic()
            self.refresh_accounting['completed']+=1
            if saved:
                accepted=self.publish_refresh(saved,generation,epoch)
                if self.refresh_writer:
                    from app.dashboard.refresh import complete_sample
                    self.refresh_samples.append(complete_sample(saved['sample'],submitted,
                        saved['sample']['compute_finished_at'],published,accepted))
                else:
                    await self.work(self.worker.record_publication,saved['view']['sequence'],submitted,computed,published,accepted)
        except Exception:
            self.refresh_accounting['failed']+=1
            self.error='Persistence or calculation failed. Scan stopped; coverage is incomplete.'
            self.request_stop(self.error,initiator='compute')

    async def _refresh(self,force=False):
        if not hasattr(self.worker,'snapshot'):
            if hasattr(self.worker,'refresh'):
                view=await self.work(self.worker.refresh,force)
                if view:self.view=view
            return
        if self.refresh_task:
            if force:await asyncio.shield(self.refresh_task)
            elif not self.refresh_task.done():
                self.refresh_accounting['pending_signal']=True
                return
        if self.error:return
        generation=self.generation;epoch=self.eligibility_epoch
        snapshot=await self.work(self.worker.snapshot,force)
        self.refresh_accounting['pending_signal']=False
        if snapshot is None:return
        self.refresh_accounting['submitted']+=1;self.refresh_accounting['max_inflight']=1
        self.refresh_task=asyncio.create_task(self._compute_refresh(snapshot,generation,epoch))
        if force:await asyncio.shield(self.refresh_task)

    async def _demo(self):
        self.health('kalshi','connected','Invented prices · no venue connection')
        self.health('polymarket_us','connected','Invented prices · no venue connection')
        n=1
        while not self.stop_event.is_set():
            await asyncio.sleep(2);self.offer(('demo',n));n+=1

    async def _run(self):
        timer=asyncio.create_task(self._deadline());producers=[];source=None;failed=False
        self.worker=self.pipeline_factory(self.mode,self.limits)
        self.worker.defer_views=True
        try:
            self.sid=await self.work(self.worker.start)
            if self.stop_event.is_set():return
            if self.mode=='live':
                source=self.source_factory(self)
                # Deadline interrupts quiet discovery as well as quiet streams.
                discovery=asyncio.create_task(source.prepare())
                waiter=asyncio.create_task(self.stop_event.wait())
                done,_=await asyncio.wait({discovery,waiter},return_when=asyncio.FIRST_COMPLETED)
                waiter.cancel();await asyncio.gather(waiter,return_exceptions=True)
                if discovery not in done:
                    discovery.cancel();await asyncio.gather(discovery,return_exceptions=True);return
                data=discovery.result()
                self.view=await self.work(self.worker.bootstrap,data)
                if not self.stop_event.is_set():producers=[asyncio.create_task(source.venue(d)) for d in data]
            else:
                self.view=await self.work(self.worker.synthetic_bootstrap)
                if not self.stop_event.is_set():producers=[asyncio.create_task(self._demo())]
            if hasattr(self.worker,'refresh_config'):
                from app.dashboard.refresh import RefreshWriter
                config=await self.work(self.worker.refresh_config)
                self.refresh_writer=RefreshWriter(**config,stop_budget=self.stop_budget)
            if not self.stop_event.is_set():self.state='scanning'
            self.writer_task=asyncio.create_task(self._consume())
            await self.stop_event.wait()
        except asyncio.CancelledError:
            self.request_stop('Application shutdown')
        except Exception:
            self.error='Scan could not continue. Check venue status and saved coverage.';self.request_stop(self.error,initiator='run');failed=True
        finally:
            self.request_stop(self.reason or 'Stopped')
            self.state='stopping';timer.cancel()
            for task in producers:task.cancel()
            closing=asyncio.create_task(source.close()) if source else None
            pending=[timer,*producers]+([closing] if closing else [])
            _,unfinished=await asyncio.wait(pending,timeout=1.5)
            if unfinished:
                for task in unfinished:task.cancel()
            results=await asyncio.gather(*pending,return_exceptions=True)
            if unfinished or any(isinstance(x,Exception) for x in results):
                self.error='Producer closure failed';self.request_stop(self.error,initiator='producer')
            self.producers_closed=True;self.producers_closed_at=monotonic()
            if self.writer_task:await self.writer_task
            # A cancelled HTTP await cannot cancel the actual worker operation.
            if self.depth_task:await asyncio.gather(self.depth_task,return_exceptions=True)
            if self.refresh_task:await asyncio.shield(self.refresh_task)
            try:
                if self.sid:
                    unprocessed=sum(r['state']!='processed' for r in self.ledger)
                    self.worker.shutdown=dict(first_stop=self.stop_record,later_causes=self.later_causes,
                        messages=self.messages,accepted=len(self.ledger),processed=len(self.ledger)-unprocessed,unprocessed=unprocessed,
                        rejected=sum(self.rejections.values()),rejections=self.rejections,
                        items=[{k:v for k,v in r.items() if k!='object_id'} for r in self.ledger])
                    if not self.error and (self.stop_clock is None or monotonic()-self.stop_clock<8.5):
                        try:await self._refresh(True)
                        except Exception:
                            self.error='Final view persistence failed; coverage is incomplete.'
                            self.request_stop(self.error,initiator='finalization')
                    if self.refresh_writer:
                        await asyncio.shield(asyncio.get_running_loop().run_in_executor(self.compute_executor,self.refresh_writer.close))
                    self.worker.shutdown['refresh_work']=dict(self.refresh_accounting,settled=self.refresh_task is None or self.refresh_task.done())
                    await self.work(self.worker.finish,self.reason,unprocessed,failed or bool(self.error))
                    if self.error:await self.work(self.worker.failure_journal,'PersistenceFailure')
            except Exception:
                self.error='Database unavailable. Session remains incomplete; failure journal saved.'
                await self.work(self.worker.failure_journal,'PersistenceFailure')
            finally:
                if self.refresh_writer:
                    await asyncio.shield(asyncio.get_running_loop().run_in_executor(self.compute_executor,self.refresh_writer.close))
                if hasattr(self.worker,'close_resources'):await self.work(self.worker.close_resources)
            for v in ('kalshi','polymarket_us'):self.health(v,'stopped','Scan stopped; prices are saved observations')
            self.finalized_at=monotonic();self.state='failed' if self.error else 'stopped'

    async def depth(self,cid):
        if self.state!='scanning':raise ValueError('Start a scan to calculate current depth, or view a saved result')
        if self.depth_busy:raise RuntimeError('A depth calculation is already running')
        if not self.queue.empty() or self.inflight:raise RuntimeError('Capture is behind; retry depth when caught up')
        self.depth_busy=True
        async def calculate():
            try:
                result=await self.work(self.worker.depth,cid)
                if not self.stop_event.is_set():self.depth_result=result
                return result
            finally:self.depth_busy=False
        self.depth_task=asyncio.create_task(calculate())
        return await asyncio.shield(self.depth_task)

    async def close(self):
        if self.task and not self.task.done():
            self.request_stop('Application shutdown');await self.task
        self.executor.shutdown(wait=False,cancel_futures=True)
        self.compute_executor.shutdown(wait=False,cancel_futures=True)
