"""Idle, explicit one-shot diagnostic launcher. No beta factory or two-venue loader.

`freeze` only prepares proposed inputs. `serve` stays idle; `start` requires a
separate candidate/spec-bound approval. Offline mode cannot reach real endpoints.
"""
import argparse
import asyncio
from contextlib import nullcontext
import fcntl
import json
import multiprocessing
from multiprocessing.reduction import DupFd
import os
from pathlib import Path
import resource
import shutil
import time

from .continuous import rss
from .delivery_budget import CAP, Clock, MIB
from .delivery_capture import KalshiTransport, Session
from .delivery_manifest import (ROOT, PRODUCTION_ROOT, SCHEMA, digest, packed, read_json,
    specification, executable_manifest, verify, validate_spec, validate_approval, validate_session_spec)
from .delivery_watchdog import Deadlines, terminate, watch, limit_cpu, usage
from .segmented import fsync_dir
from .supervised import PROFILE

OUTER_BYTES=64*1024


def socket_path(spec):
    return '/tmp/predict-delivery-'+digest(spec)[:24]+'.sock'


def load_kalshi():
    """Called in the armed worker only. Never invokes the two-venue loader."""
    from keyring.backends.macOS import Keyring
    from .venue_access import Credential
    try:
        value=Keyring().get_password('prediction-arb.kalshi.production','market-data')
        data=json.loads(value)
        if set(data)!={'key_id','private_key'}:raise ValueError()
        return Credential('kalshi',data)
    except Exception:
        raise ValueError('kalshi_credential_unavailable') from None


def write_once(path, value, *, size=None):
    """Bounded append-only helper write, including partial failure payloads."""
    body=packed(value)
    if len(body)>PROFILE['manifest_bytes'] or size is not None and len(body)>size:
        raise ValueError('helper_record_cap')
    if size:body=body.ljust(size,b' ')
    with Path(path).open('xb',buffering=0) as f:
        if f.write(body)!=len(body):raise OSError('short_helper_write')
        os.fsync(f.fileno())
    fsync_dir(Path(path).parent)


class Attempt:
    """Parent and worker retain the same flock description until worker death."""
    def __init__(self,spec,manifest,approval,anchor):
        self.spec=spec;self.output=Path(spec['output']);self.root=Path(spec['ownership'])
        self.marker=self.root/(spec['attempt']+'.attempt.json')
        self.bound=dict(schema=SCHEMA,attempt=spec['attempt'],candidate=manifest['sha256'],
            spec=digest(spec),output=spec['output'],approval=approval,started=anchor)
        self.lock=None;self.consumed=False;self.created=False

    def acquire(self):
        validate_spec(self.spec)
        self.root.mkdir(parents=True,exist_ok=True)
        self.lock=(self.root/'collector.lock').open('a')
        try:
            fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            write_once(self.marker,self.bound);self.consumed=True
            self.output.mkdir(mode=0o700,exist_ok=False);self.created=True
            if rss()>=192*MIB or shutil.disk_usage(self.output).free<PROFILE['disk_floor']+PROFILE['output']:
                raise ValueError('start_resources')
        except BaseException:
            self.release();raise

    def release(self):
        if self.lock:self.lock.close();self.lock=None

    def helper(self,name,value,*,size=None):
        if not self.created or Path(name).name!=name:raise ValueError('helper_destination')
        used=sum(p.stat().st_size for p in self.output.iterdir() if p.is_file())+self.marker.stat().st_size
        n=size or len(packed(value))
        reserve=0 if name=='launcher-result.json' else OUTER_BYTES
        if used+n+reserve>CAP['helper_bytes']:raise ValueError('helper_joint_cap')
        write_once(self.output/name,value,size=size)

    def failed_start(self):
        if self.consumed:
            # Also works when exclusive output creation failed. Never touches that output.
            retained=self.marker.stat().st_size
            if self.created:retained+=sum(p.stat().st_size for p in self.output.rglob('*') if p.is_file())
            if retained+16384>CAP['helper_bytes']:raise ValueError('failed_start_helper_cap')
            write_once(self.root/(self.spec['attempt']+'.failure.json'),
                       dict(schema=SCHEMA,phase='start_failed',attempt=self.spec['attempt'],
                            retained_bytes=retained+16384,helper_write_bytes=retained+16384,
                            scope='owned marker, new helper output and this fixed failure record; append-only'),size=16384)


class WorkerControl:
    def __init__(self,session,pipe,runtime=None):
        self.session=session;self.pipe=pipe;self.runtime=runtime;self.stopped=False

    def stop(self,message):
        if self.stopped:return
        self.stopped=True
        self.pipe.send(dict(event='stop_received',clock=Clock().anchor(),source=message['source']))
        if self.runtime:self.runtime.before_stop(self.session)
        self.session.stop('direct_stop')


async def collect(spec,manifest,pipe,anchor,runtime=None):
    credential=runtime.load() if runtime else load_kalshi()
    transport=await runtime.transport(credential) if runtime else KalshiTransport(credential)
    output=Path(spec['output'])/'collector';output.mkdir(mode=0o700)
    def closed(mono):pipe.send(dict(event='intake_closed',mono=mono,clock=Clock().anchor()))
    session=Session(output,transport,start_anchor=anchor,external_reserve=CAP['helper_bytes'],on_closed=closed)
    control=WorkerControl(session,pipe,runtime)
    async def commands():
        try:
            while True:
                if pipe.poll():
                    message=pipe.recv()
                    if message.get('action')!='stop':raise ValueError('worker_control')
                    control.stop(message)
                await asyncio.sleep(.01)
        except (OSError,EOFError,ValueError):session.stop('worker_control_lost')
    task=asyncio.create_task(commands())
    try:
        if runtime:runtime.session=session
        # A Stop queued during credential loading must take effect before discovery.
        if pipe.poll():control.stop(pipe.recv())
        def started(_):
            validate_session_spec(read_json(output/'spec.json'),spec)
            pipe.send(dict(event='collecting',clock=Clock().anchor()))
        await session.run(started)
        pipe.send(dict(event='cleanup',clock=Clock().anchor(),closed=session.closed_at,
                       cleanup_finished=session.cleanup_finished,complete=session.complete))
        if runtime:await runtime.before_finalize(session)
        summary,receipt=session.finalize()
        pipe.send(dict(event='finalized',clock=Clock().anchor(),reason=session.reason,
            complete=session.complete,receipt_status=receipt['status'],
            request_counts=session.http.requests.counts,connections=transport.connections,
            primary_kind=session.market.raw.kind.value if session.market else None,resources=usage()))
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True)
        await transport.close()
        if runtime:await runtime.close()
        if session.records and not session.records.history.closed:session.records.history.abort()


def worker(spec,manifest,approval,pipe,anchor,lock_fd,fixture_options=None):
    """No secrets in process arguments. Lock is the already-owned file description."""
    limit_cpu()
    lock=os.fdopen(lock_fd.detach(),'a');runtime=None
    try:
        if not pipe.poll(60) or pipe.recv()!={'action':'armed'}:raise ValueError('supervision_not_armed')
        verify(manifest,spec);validate_approval(approval,manifest,spec)
        marker=read_json(Path(spec['ownership'])/(spec['attempt']+'.attempt.json'))
        if any(marker[k]!=v for k,v in dict(candidate=manifest['sha256'],spec=digest(spec),
                                          output=spec['output'],attempt=spec['attempt']).items()):
            raise ValueError('attempt_binding')
        if spec['mode']=='offline':
            from tests.delivery_launcher_fixture import Runtime
            runtime=Runtime(spec,fixture_options or {})
        guard=runtime.guard() if runtime else nullcontext()
        with guard:
            asyncio.run(collect(spec,manifest,pipe,anchor,runtime))
    except BaseException:
        # No exception text or credential-bearing object crosses the worker boundary.
        try:pipe.send(dict(event='worker_failed',clock=Clock().anchor()))
        except (OSError,EOFError):pass
        raise SystemExit(1) from None
    finally:
        lock.close();pipe.close()


class Launcher:
    def __init__(self,manifest,spec,*,fixture_options=None,watch_clock=None):
        verify(manifest,spec)
        if spec['mode']!='offline' and (fixture_options is not None or watch_clock is not None):
            raise ValueError('offline_injection_only')
        self.manifest=manifest;self.spec=spec;self.fixture_options=fixture_options;self.watch_clock=watch_clock
        self.state='idle';self.events=[];self.process=None;self.guard=None;self.pipe=None;self.guard_pipe=None
        self.attempt=None;self.anchor=None;self.closed=None;self.cleaned=False;self.stop_sent=False;self.monitor=None
        self.done=asyncio.Event();self.result=None;self.failure=None

    def event(self,name,**value):
        row=dict(event=name,clock=Clock().anchor(),**value)
        if len(self.events)>=128 or len(packed(self.events+[row]))>MIB:
            raise ValueError('control_record_cap')
        self.events.append(row)
        return row

    def status(self):
        return dict(schema=SCHEMA,state=self.state,candidate=self.manifest['sha256'],
                    spec=digest(self.spec),attempt=self.spec['attempt'],start_available=self.state=='idle',
                    consumed=self.attempt.consumed if self.attempt else False,
                    result=self.result,events=list(self.events))

    async def start(self,approval):
        if self.state!='idle':raise ValueError('start_unavailable')
        verify(self.manifest,self.spec);validate_approval(approval,self.manifest,self.spec)
        self.state='starting';self.anchor=Clock().anchor();self.event('explicit_start')
        self.attempt=Attempt(self.spec,self.manifest,approval,self.anchor)
        try:
            self.attempt.acquire()
            self.attempt.helper('candidate.json',self.manifest)
            self.attempt.helper('spec.json',self.spec)
            self.attempt.helper('approval.json',approval)
            self.attempt.helper('start.json',self.anchor)
            ctx=multiprocessing.get_context('spawn')
            self.pipe,child=ctx.Pipe()
            self.process=ctx.Process(target=worker,args=(self.spec,self.manifest,approval,child,self.anchor,
                DupFd(self.attempt.lock.fileno()),self.fixture_options))
            self.process.start();child.close()
            self.guard_pipe,guard_child=ctx.Pipe()
            self.guard=ctx.Process(target=watch,args=(self.process.pid,os.getpid(),guard_child,self.anchor['mono']),
                                   kwargs={'clock':self.watch_clock})
            self.guard.start();guard_child.close()
            async with asyncio.timeout(5):
                while not self.guard_pipe.poll():
                    if not self.guard.is_alive():raise ValueError('watchdog_start_failed')
                    await asyncio.sleep(.01)
            armed=self.guard_pipe.recv()
            if armed['event']!='armed':raise ValueError('watchdog_not_armed')
            self.events.append(armed);self.pipe.send({'action':'armed'})
            self.state='active';self.monitor=asyncio.create_task(self.observe())
            if self.stop_sent:self.pipe.send(dict(action='stop',source='owner'))
        except BaseException:
            self.failure='start_failed';self.state='failed'
            if self.process and self.process.pid:terminate(self.process.pid);self.process.join(1)
            if self.guard and self.guard.pid:terminate(self.guard.pid);self.guard.join(1)
            self.attempt.failed_start();self.attempt.release()
            self.done.set()
            raise ValueError('start_failed_attempt_retained') from None
        return self.status()

    def stop(self,source='owner'):
        if self.state=='idle':return dict(stopped=False,reason='not_started')
        if self.stop_sent or self.state in ('finished','failed'):return dict(stopped=True,already_stopped=True)
        self.stop_sent=True
        self.event('stop_sent',source=source,intended=self.anchor['mono']+240 if source=='scheduled' else None)
        if self.state!='starting' and self.process and self.process.is_alive():
            self.pipe.send(dict(action='stop',source=source))
        return dict(stopped=True)

    def worker_event(self,event):
        # Worker protocol uses fixed public fields; never forwards exception strings.
        if len(packed(event))>16384:raise ValueError('worker_message_size')
        self.event('worker',value=event)
        if event['event']=='intake_closed' and self.closed is None:
            self.closed=event['mono'];self.state='finalizing'
        if event['event']=='collecting':self.guard_pipe.send(dict(action='collecting'))
        if event['event']=='cleanup':
            self.cleaned=True
            if not event['complete'] or event['cleanup_finished']-event['closed']>5:self.failure='cleanup_failed'
            # Do not relax intake cutoff while cancellation or transport close is blocked.
            self.guard_pipe.send(dict(action='closed',mono=event['closed']))
        if event['event']=='worker_failed':self.failure='worker_failed'

    async def observe(self):
        last_heartbeat=0
        limits=Deadlines(self.anchor['mono'])
        try:
            while self.process.is_alive():
                now=time.monotonic()
                if now-last_heartbeat>=.25:
                    self.guard_pipe.send(dict(action='heartbeat'));last_heartbeat=now
                while self.pipe.poll():
                    try:self.worker_event(self.pipe.recv())
                    except EOFError:break
                while self.guard_pipe.poll():
                    try:event=self.guard_pipe.recv()
                    except EOFError:break
                    self.event('watchdog',value=event)
                    if event['event']=='scheduled_stop_due':self.stop('scheduled')
                    elif event['event']!='watchdog_resources':
                        self.failure=event['event']
                if not self.guard.is_alive() and self.process.is_alive():
                    self.failure=self.failure or 'watchdog_lost';terminate(self.process.pid);break
                limits.closed=self.closed if self.cleaned else None;limits.stop_sent=self.stop_sent
                action=limits.action(now)
                if action=='direct_stop':self.stop('scheduled')
                elif action:
                    self.failure=action;terminate(self.process.pid);break
                if rss()>=256*MIB:
                    self.failure='launcher_rss';terminate(self.process.pid);break
                await asyncio.sleep(.02)
            self.process.join(1)
            while self.pipe.poll():
                try:self.worker_event(self.pipe.recv())
                except EOFError:break
        except BaseException:
            self.failure=self.failure or 'supervisor_control_failure'
            if self.process.is_alive():terminate(self.process.pid);self.process.join(1)
        finally:
            try:self.guard_pipe.send(dict(action='finished'))
            except (OSError,EOFError):pass
            self.guard.join(1)
            if self.guard.is_alive():terminate(self.guard.pid);self.guard.join(1)
            while self.guard_pipe.poll():
                try:self.event('watchdog',value=self.guard_pipe.recv())
                except EOFError:break
            self.pipe.close();self.guard_pipe.close()
            try:self.finish()
            except BaseException:
                self.failure='outer_accounting_failure';self.state='failed'
            finally:self.attempt.release();self.done.set()

    def finish(self):
        output=Path(self.spec['output']);collector=output/'collector'
        receipt_path=collector/'finalization-resources.json'
        receipt=read_json(receipt_path) if receipt_path.exists() else None
        outer_files=[p for p in output.rglob('*') if p.is_file() and collector not in p.parents]
        helper=sum(p.stat().st_size for p in outer_files)+self.attempt.marker.stat().st_size
        retained=sum(p.stat().st_size for p in output.rglob('*') if p.is_file())+self.attempt.marker.stat().st_size+OUTER_BYTES
        # Complete receipts cover collector only. Interrupted collector writes are unknown.
        writes=receipt['cumulative_application_file_write_bytes']+helper+OUTER_BYTES if receipt else None
        finalized=[x['value'] for x in self.events if x['event']=='worker' and x['value']['event']=='finalized']
        success=(not self.failure and self.process.exitcode==0 and bool(finalized)
                 and finalized[-1]['complete'] and finalized[-1]['receipt_status']=='complete'
                 and finalized[-1]['reason']=='direct_stop' and self.stop_sent)
        self.result=dict(status='complete' if success else 'failed',failure=self.failure,
            exitcode=self.process.exitcode,candidate=self.manifest['sha256'],spec=digest(self.spec),
            retained_bytes=retained,cumulative_write_bytes=writes,helper_write_bytes=helper+OUTER_BYTES,
            incomplete_write_accounting=writes is None,events=self.events,
            receipt_boundary='collector receipt unchanged; launcher/marker/outer report counted separately',
            outer_finished=Clock().anchor(),launcher_resources=usage(),
            incomplete_worker_resources=not bool(finalized))
        if retained>CAP['output'] or helper+OUTER_BYTES>CAP['helper_bytes'] or writes is not None and writes>CAP['write_bytes']:
            raise ValueError('outer_resource_cap')
        self.attempt.helper('launcher-result.json',self.result,size=OUTER_BYTES)
        self.state='finished' if success else 'failed'

    async def close(self):
        if self.monitor and not self.monitor.done():
            self.stop()
            try:await asyncio.wait_for(asyncio.shield(self.monitor),6)
            except TimeoutError:
                self.failure='launcher_closed';terminate(self.process.pid)
                await self.monitor
        if self.attempt:self.attempt.release()


async def serve(manifest,spec,approval_path):
    from aiohttp import web
    launcher=Launcher(manifest,spec)
    path=Path(socket_path(spec))
    if path.exists():raise ValueError('existing_private_control')
    async def status(request):return web.json_response(launcher.status())
    async def start(request):
        try:return web.json_response(await launcher.start(read_json(approval_path)))
        except Exception:return web.json_response(dict(error='start_rejected'),status=422)
    async def stop(request):
        try:return web.json_response(launcher.stop())
        except Exception:return web.json_response(dict(error='stop_control_failed'),status=422)
    app=web.Application(client_max_size=1024)
    app.add_routes([web.get('/status',status),web.post('/start',start),web.post('/stop',stop)])
    runner=web.AppRunner(app,access_log=None);await runner.setup()
    old_umask=os.umask(0o077)
    try:
        site=web.UnixSite(runner,str(path));await site.start();os.chmod(path,0o600)
    finally:os.umask(old_umask)
    print(json.dumps(dict(ready=True,socket=str(path),candidate=manifest['sha256'],idle=True)),flush=True)
    try:await launcher.done.wait()
    finally:
        await launcher.close();await runner.cleanup();path.unlink(missing_ok=True)


async def command(spec,action):
    import aiohttp
    validate_spec(spec)
    async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=socket_path(spec)),
                                     timeout=aiohttp.ClientTimeout(total=10),trust_env=False) as client:
        async with client.request('GET' if action=='status' else 'POST','http://localhost/'+action) as response:
            print(json.dumps(await response.json()),flush=True)
            if response.status!=200:raise ValueError('control_rejected')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['freeze','serve','status','start','stop'])
    p.add_argument('--spec',type=Path,required=True);p.add_argument('--candidate',type=Path)
    p.add_argument('--approval',type=Path)
    a=p.parse_args();spec=read_json(a.spec)
    if a.action=='freeze':
        if not a.candidate:raise ValueError('candidate_path_required')
        write_once(a.candidate,executable_manifest(spec))
    elif a.action=='serve':
        if not a.candidate or not a.approval:raise ValueError('candidate_and_approval_required')
        asyncio.run(serve(read_json(a.candidate),spec,a.approval))
    else:asyncio.run(command(spec,a.action))


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Diagnostic command failed; no automatic retry.') from None
