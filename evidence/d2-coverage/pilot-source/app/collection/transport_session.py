"""Explicit E6 observation owner; prediction-first activation and exact durable replay."""
from app.diagnostics import failure
import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4
from app.dashboard.bounds import CaptureQueue
from app.reference.records import packed
from .odds_http import HTTPPolicy, OddsHTTP, BudgetStop, utc
from .prediction_producer import PredictionProducer
from .run_spec import preflight, time_value, reference_enabled


class StorageFailure(OSError):
    """Sanitized first failure; OS-visible bytes are not a durability receipt."""
    def __init__(self, stage):
        self.stage=stage
        super().__init__('storage failure at '+stage)


class ObservationJournal:
    """Bounded fsynced E6 observations; untouched E2 synthetic schema is not relabeled."""
    def __init__(self, path):
        self.path=Path(path); self.previous='0'*64; self.bytes=0; self.count=0
        self.failed=None; self.attempted=0; self.stage='idle'; self.terminal_acknowledged=False
        # No buffered close may silently retry a failed write/flush.
        self.file=self.path.open('xb',buffering=0)
        import fcntl
        try:
            fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BaseException:
            try:self.file.close()
            except OSError as exc:failure(__name__, 'journal_lock_cleanup', exc)
            raise
    def save(self, row):
        if self.failed:raise self.failed
        payload=packed(row)
        digest=sha256((self.previous+payload).encode()).hexdigest()
        body=(packed(dict(previous=self.previous,sha256=digest,row=row))+'\n').encode()
        if self.bytes+len(body)>32*1024*1024 or self.count>=4096:
            raise BudgetStop('observation_storage_cap')
        self.attempted+=1
        try:
            self.stage='write'
            if self.file.write(body)!=len(body):raise OSError('short write')
            self.stage='flush'; self.file.flush()
            self.stage='fsync'; os.fsync(self.file.fileno())
        except OSError:
            self.failed=StorageFailure(self.stage)
            raise self.failed from None
        self.stage='acknowledged' 
        self.previous=digest; self.bytes+=len(body); self.count+=1
        self.terminal_acknowledged=row.get('type')=='session_finished'
    def close(self):
        try:self.file.close()
        except OSError:
            self.failed=self.failed or StorageFailure('close')
            raise self.failed from None


def reopen(path):
    path=Path(path)
    if path.stat().st_size>32*1024*1024: raise ValueError('saved byte cap')
    previous='0'*64; rows=[]
    with path.open('rb') as stream:
        for line in stream:
            if len(rows)>=4096 or not line.endswith(b'\n'):raise ValueError('incomplete or overbound journal')
            value=json.loads(line); row=value['row']
            digest=sha256((previous+packed(row)).encode()).hexdigest()
            if value['previous']!=previous or value['sha256']!=digest:raise ValueError('saved hash chain mismatch')
            previous=digest; rows.append(row)
    return dict(format='e6-transport-observations-1',rows=rows,sha256=previous,
                state='complete' if rows and rows[-1]['type']=='session_finished' else 'interrupted',
                economics=None,qualification='bounded observation journal; no economic qualification')


def reference_identity(record, spec):
    if not record['complete'] or record['status']!=200:
        return False,'incomplete_or_http_error'
    try:
        def unique(items):
            result={}
            for key,value in items:
                if key in result:raise ValueError('duplicate key')
                result[key]=value
            return result
        body=json.loads(base64.b64decode(record['body_b64']),parse_float=Decimal,object_pairs_hook=unique,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
        row=spec['sources']['the_odds_api']
        if body['id']!=row['event_id'] or body['sport_key']!='americanfootball_nfl':return False,'wrong_event'
        if time_value(body['commence_time'])!=time_value(spec['scheduled_start']):return False,'changed_schedule'
        if datetime.now(timezone.utc)>=time_value(body['commence_time']):return False,'kickoff_cutoff'
        if body.get('phase') not in (None,'pregame') or body.get('status') not in (None,'scheduled'):return False,'phase_changed'
        names=[body['home_team'],body['away_team']]
        if len(set(names))!=2 or {row['participant_mapping'].get(x) for x in names}!=set(spec['participants']):return False,'missing_mapping'
        books=body['bookmakers']
        if len(books)!=1 or books[0]['key']!='pinnacle':return False,'wrong_book'
        markets=books[0]['markets']
        if len(markets)!=1 or markets[0]['key']!='h2h':return False,'wrong_market'
        outcomes=markets[0]['outcomes']
        if len(outcomes)!=2 or {o['name'] for o in outcomes}!=set(names):return False,'incomplete_pair'
        if any(isinstance(o['price'],bool) or not Decimal(str(o['price'])).is_finite() or Decimal(str(o['price']))<=1 for o in outcomes):return False,'invalid_odds'
        return True,'identity_validated; pairing_lineage_economics_unqualified'
    except (KeyError,ValueError,TypeError,ArithmeticError):return False,'malformed_snapshot'


class TransportSession:
    def __init__(self, spec, output, endpoints, *, credentials=None, budgets=None):
        self.spec=deepcopy(spec); self.output=Path(output); self.endpoints=deepcopy(endpoints)
        self.credentials=credentials; self.budgets=budgets or {}
        self.state='idle'; self.stop_event=asyncio.Event(); self.task=None; self.reason=None
        self.health={s:'idle' for s in ('reference','kalshi','polymarket_us')}
        if not reference_enabled(spec):self.health.pop('reference')
        self.producers={}; self.reference=None; self.journal=None
        self.queue=CaptureQueue(48,4*1024*1024); self.delivered=0; self.persisted=0; self.ingress_bytes=0
        self.sid=str(uuid4()); self.closing=False; self.persistence_error=None; self.last_reference=None
        self.intake_closed=False
        self.counts=dict(received=0,accepted=0,write_attempted=0,durably_acknowledged=0,rejected=0)
        self.failure_report='not_attempted'; self.cleanup_complete=False; self.cleanup_errors=[]

    def accounting(self):
        return dict(self.counts,unresolved=self.counts['accepted']-self.counts['durably_acknowledged'],
                    queue_pending=self.queue.qsize(),queue_drained=self.persisted,
                    journal_write_attempted=self.journal.attempted if self.journal else 0,
                    journal_durably_acknowledged=self.journal.count if self.journal else 0,
                    journal_unresolved=(self.journal.attempted-self.journal.count) if self.journal else 0,
                    confirmed_byte_offset=self.journal.bytes if self.journal else 0,
                    confirmed_chain=self.journal.previous if self.journal else None,
                    total_upstream=None,lost=None)

    def storage_failed(self, stage):
        if self.persistence_error is None:
            self.persistence_error='Storage failure at '+stage+'; durability of unacknowledged work is unknown.'
        self.intake_closed=True; self.reason='storage_failure'; self.stop_event.set()
        self.health={v:'ineligible' for v in self.health}

    def report_failure(self):
        # Supplemental and best effort, never another append to the primary journal.
        if self.failure_report!='not_attempted':return
        self.failure_report='unavailable'
        try:
            from app.dashboard.e6_live import save_json
            save_json(self.output/'storage-failure.json',dict(format='e6-runtime-storage-failure-1',
                session=self.sid,error=self.persistence_error,accounting=self.accounting(),
                primary_journal=str(self.journal.path) if self.journal else None,
                primary_journal_completion=('acknowledged' if self.journal and self.journal.terminal_acknowledged else 'not_acknowledged'),cleanup_complete=self.cleanup_complete,
                provenance='supplemental runtime report; not primary journal or recovery evidence'))
            self.failure_report='saved'
        except Exception as exc:
            failure(__name__, 'storage_failure_report', exc)

    async def close_resources(self):
        resources=list(self.producers.items())
        if self.reference:resources.append(('reference',self.reference))
        results=await asyncio.gather(*(p.aclose() for _,p in resources),return_exceptions=True)
        for (name,_),result in zip(resources,results):
            if isinstance(result,BaseException):
                self.cleanup_errors.append(name+':'+type(result).__name__)
                failure(__name__, 'resource_close', result)

    def emit(self,source,record):
        self.counts['received']+=1
        if self.intake_closed:
            self.counts['rejected']+=1
            return False
        row=dict(record,source=source,session_id=self.sid,ingress_id=str(uuid4()),observed_at=utc(),
                 health=deepcopy(self.health),economics=None)
        n=len(packed(row).encode())
        if self.delivered>=2048 or self.ingress_bytes+n>16*1024*1024:
            self.counts['rejected']+=1
            self.request_stop('session_ingress_cap');raise BudgetStop('session_ingress_cap')
        # Write-ahead before queueing. Queue failures retain the delivered record.
        self.counts['accepted']+=1
        before=self.journal.attempted
        try:self.journal.save(row)
        except OSError as exc:
            self.storage_failed(getattr(exc,'stage','write'))
            raise
        finally:self.counts['write_attempted']+=self.journal.attempted-before
        self.counts['durably_acknowledged']+=1
        self.delivered+=1; self.ingress_bytes+=n
        try:self.queue.put_nowait(row)
        except asyncio.QueueFull:
            self.request_stop('queue_capacity');raise

    def set_health(self, source, value):
        if self.persistence_error:return
        if self.health[source]!=value:
            self.health[source]=value
            self.emit(source,dict(type='source_health',state=value))

    def request_stop(self, reason):
        self.reason=self.reason or reason; self.stop_event.set()

    async def start(self):
        result=preflight(self.spec)
        if not result['valid']:raise ValueError(packed(result['errors']))
        if datetime.now(timezone.utc)<time_value(self.spec['start_after']):raise ValueError('before explicit start window')
        if self.state!='idle':raise ValueError('session already started')
        # Constructors validate all destinations before a file or connection is opened.
        def ref_sink(row):self.emit('reference',row)
        if reference_enabled(self.spec):
            p=dict(self.spec['http'])
            for key in ('dollars','dollars_per_credit'):p[key]=Decimal(p[key])
            key_options={}
            if self.spec['mode']=='real':
                import os
                key_options=dict(real_key=os.environ.get('ODDS_API_KEY'))
                if not key_options['real_key']:raise ValueError('optional ODDS_API_KEY unavailable')
            self.reference=OddsHTTP(self.endpoints['reference'],self.spec['sources']['the_odds_api']['event_id'],HTTPPolicy(**p),ref_sink,**key_options)
        if self.spec['mode']=='real' and self.credentials is None:
            from .venue_access import load_credentials
            self.credentials=load_credentials()
        self.producers={v:PredictionProducer(v,self.spec,self.endpoints[v]['rest'],self.endpoints[v]['ws'],self.emit,self.set_health,
                        credential=(self.credentials or {}).get(v),budget=self.budgets.get(v)) for v in ('kalshi','polymarket_us')}
        self.output.mkdir(parents=True,exist_ok=True)
        try:
            self.journal=ObservationJournal(self.output/(self.sid+'.jsonl'))
            self.emit('session',dict(type='session_started',spec=self.spec,provenance=('real venue observation; economics unqualified' if self.spec['mode']=='real' else 'local mock; fabricated protocol and identified retained metadata')))
        except OSError as exc:
            self.storage_failed(getattr(exc,'stage','open'))
            await self.close_resources()
            if self.journal:
                try:self.journal.close()
                except OSError:pass
            self.cleanup_complete=not self.cleanup_errors;self.state='failed';self.report_failure()
            raise
        self.state='running'; self.task=asyncio.create_task(self.run())
        return self.sid

    async def consume(self):
        while not self.closing or not self.queue.empty():
            try:row=await asyncio.wait_for(self.queue.get(),.1)
            except TimeoutError:continue
            # The fsynced write-ahead record is the primary observation store here.
            self.persisted+=1; self.queue.task_done()

    async def pause(self,seconds):
        try:await asyncio.wait_for(self.stop_event.wait(),seconds)
        except TimeoutError:pass

    async def references(self):
        retries=0
        while not self.stop_event.is_set():
            self.set_health('reference','awaiting_snapshot')
            result=await self.reference.request()
            valid,reason=reference_identity(result,self.spec)
            self.emit('reference',dict(type='reference_validation',receipt_sha256=result['body_sha256'],valid_identity=valid,reason=reason))
            self.last_reference=asyncio.get_running_loop().time() if valid else None
            self.set_health('reference','connected' if valid else 'ineligible')
            if self.reference.budget.reason:raise BudgetStop(self.reference.budget.reason)
            if result['status'] in (429,500,502,503,504):
                retries+=1
                if retries>self.spec['http']['retries']:raise BudgetStop('retry_cap')
                wait=self.spec['http']['backoff']*2**(retries-1)
                values=[v for k,v in result['headers'] if k=='retry-after']
                if values:
                    if len(values)!=1 or not values[0].isdigit():raise BudgetStop('invalid_retry_after')
                    wait=max(wait,int(values[0]))
                if wait>30:raise BudgetStop('retry_after_exceeds_bound')
                await self.pause(wait);continue
            if not valid:raise BudgetStop(reason)
            retries=0
            await self.pause(self.spec['reference_cadence'])

    async def optional_references(self):
        try:await self.references()
        except asyncio.CancelledError:raise
        except Exception as exc:
            self.set_health('reference','unavailable')
            self.emit('reference',dict(type='reference_stopped',reason=type(exc).__name__))

    async def freshness(self):
        while not self.stop_event.is_set():
            await self.pause(min(.1,self.spec['stale_seconds']))
            if self.last_reference is not None and asyncio.get_running_loop().time()-self.last_reference>self.spec['stale_seconds']:
                self.set_health('reference','stale')

    async def discoveries(self):
        while not self.stop_event.is_set():
            await self.pause(self.spec['discovery_cadence'])
            if self.stop_event.is_set():break
            for producer in self.producers.values():
                await producer.discover()

    async def run(self):
        tasks=[]; consumer=asyncio.create_task(self.consume())
        async def guarded(coro):
            try:await coro
            except asyncio.CancelledError:raise
            except Exception as exc:
                failure(__name__, 'producer', exc)
                self.request_stop('producer_failure:'+type(exc).__name__)
            else:
                if not self.stop_event.is_set():self.request_stop('producer_ended')
        try:
            # Deadline includes bounded discovery, connections and backoff.
            seconds=min(self.spec['duration'],(time_value(self.spec['scheduled_start'])-datetime.now(timezone.utc)).total_seconds())
            if getattr(self, 'started_monotonic', None) is not None:
                import time
                seconds=max(0, seconds-(time.monotonic()-self.started_monotonic))
            async with asyncio.timeout(seconds):
                discovery_tasks=[asyncio.create_task(p.discover()) for p in self.producers.values()]
                try:
                    group=asyncio.gather(*discovery_tasks)
                    stopper=asyncio.create_task(self.stop_event.wait())
                    try:
                        await asyncio.wait((group,stopper),return_when=asyncio.FIRST_COMPLETED)
                        if self.stop_event.is_set():return
                        markets=await group
                    finally:
                        stopper.cancel();group.cancel()
                        await asyncio.gather(stopper,group,return_exceptions=True)
                finally:
                    for task in discovery_tasks:task.cancel()
                    await asyncio.gather(*discovery_tasks,return_exceptions=True)
                tasks=[asyncio.create_task(guarded(p.run(m))) for p,m in zip(self.producers.values(),markets)]
                tasks += [asyncio.create_task(guarded(self.discoveries()))]
                if self.reference:
                    tasks += [asyncio.create_task(self.optional_references()),asyncio.create_task(guarded(self.freshness()))]
                await self.stop_event.wait()
        except asyncio.CancelledError:
            self.request_stop('cancelled')
            raise
        except TimeoutError:self.request_stop('duration_or_kickoff_cutoff')
        except Exception as exc:
            failure(__name__, 'discovery', exc)
            self.request_stop('discovery_failure:'+type(exc).__name__)
        finally:
            self.state='stopping'
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            await self.close_resources()
            self.closing=True; await consumer
            try:
                if not self.persistence_error:self.journal.save(dict(type='session_finished',session_id=self.sid,observed_at=utc(),reason=self.reason,
                    delivered=self.delivered,persisted=self.persisted,ingress_accounting=dict(self.counts,unresolved=self.counts['accepted']-self.counts['durably_acknowledged']),health=self.health,accounting=self.reference.budget.snapshot() if self.reference else None,
                    cleanup_errors=list(self.cleanup_errors),prediction_accounting={v:dict(requests=p.budget.requests,connections=p.budget.connections,
                        dollars_reserved=str(p.budget.dollars),body_bytes_charged=p.budget.bytes) for v,p in self.producers.items()},economics=None))
            except (OSError,BudgetStop) as exc:self.storage_failed(getattr(exc,'stage','terminal'))
            finally:
                self.intake_closed=True
                try:self.journal.close()
                except OSError as exc:self.storage_failed(getattr(exc,'stage','close'))
                self.cleanup_complete=not self.cleanup_errors
                self.state='failed' if self.persistence_error or self.cleanup_errors else 'stopped'
                if self.persistence_error:self.report_failure()

    async def stop(self):
        if self.state=='idle':return
        self.request_stop('manual_stop')
        if self.task:await self.task
