"""One bounded, disposable full-scope Coverage process; never an acquirer."""
import asyncio
import json
import logging
import os
import signal
from pathlib import Path
import sys
import time

MAX_PROCESS_BYTES=1024*1024*1024
MAX_REPLY_BYTES=64*1024
MAX_SECONDS=180


def resume_arguments(module, arguments):
    """Resume ordinary financial rotation from its last committed component."""
    if module!='app.collection.financial_worker' or not arguments:return arguments
    admission=json.loads(arguments[0])
    if admission:return arguments
    from app.storage.store import connect
    with connect() as db,db.transaction():
        db.execute('SET TRANSACTION READ ONLY')
        row=db.execute('''SELECT publication_events FROM latest_board
            WHERE calculated_at IS NOT NULL ORDER BY calculated_at::timestamptz DESC,game_key LIMIT 1''').fetchone()
    if row and row['publication_events']:
        admission['estimates_after']=min(row['publication_events'])
        admission['estimates_rotation_after']=admission['estimates_after']
    return (json.dumps(admission),*arguments[1:])


async def run(stopped, *, root, module=None, arguments=(), on_progress=None, wait_for_admission=True):
    from .background_work import BACKGROUND,AcquisitionDeferred
    start=time.monotonic()
    coverage=module in (None,__name__)
    ordinary=module=='app.collection.ordinary_worker'
    if stopped():return dict(published=False,reason='updates_stopped')
    # A census deferred at admission otherwise waits the entire two-minute
    # publication interval, phase-locking with recurring raw-input bursts. Wait
    # for an admissible slot without launching CPU work; this wait consumes the
    # same total deadline as the child, and Stop remains immediately observable.
    # Ordinary publication is the delivery path, not optional census work.
    # It has its own bounded, lower-priority process and no event-loop GIL.
    # Suspending it until a persistently busy socket drains starves every
    # source, including already-admitted API receipts. Keep all child memory,
    # deadline, Stop and ingress capacity guards; only optional work waits.
    while coverage and BACKGROUND.acquisition_pressure():
        if not wait_for_admission:raise AcquisitionDeferred('native_acquisition_catching_up')
        if stopped():return dict(published=False,reason='updates_stopped')
        if time.monotonic()-start>MAX_SECONDS:raise AcquisitionDeferred('native_acquisition_catching_up')
        await asyncio.sleep(.05)
    if not (coverage or ordinary) and BACKGROUND.acquisition_pressure():raise AcquisitionDeferred('native_acquisition_catching_up')
    admission_seconds=time.monotonic()-start
    arguments=await asyncio.to_thread(resume_arguments,module,arguments)
    if stopped():return dict(published=False,reason='updates_stopped')
    if time.monotonic()-start>MAX_SECONDS:raise ValueError('coverage_worker_deadline')
    if ordinary and hasattr(signal,'SIGUSR1'):arguments=(*arguments,'--cooperative-pause')
    process=await asyncio.create_subprocess_exec(sys.executable,'-m',module or __name__,str(root),str(os.getpid()),*arguments,
        cwd=str(Path(__file__).resolve().parents[2]),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
    cooperative=module in ('app.collection.financial_worker','app.collection.ordinary_worker') and hasattr(signal,'SIGUSR1')
    ready=False
    async def bounded_reply():
        nonlocal ready
        chunks=[];size=0;pending=b''
        while size<=MAX_REPLY_BYTES:
            chunk=await process.stdout.read(min(8192,MAX_REPLY_BYTES+1-size))
            if not chunk:break
            size+=len(chunk);pending+=chunk
            while b'\n' in pending:
                line,pending=pending.split(b'\n',1)
                if cooperative and line==b'{"worker_ready": "cooperative_pause"}':
                    ready=True;continue
                if on_progress is not None:
                    try:value=json.loads(line)
                    except (ValueError,UnicodeError):value=None
                    if isinstance(value,dict) and set(value)=={'worker_progress'}:
                        cursor=value['worker_progress']
                        if not isinstance(cursor,dict) or set(cursor)-{'estimates_cursor','estimates_after','estimates_rotation_after','estimates_window_turn'}:
                            raise ValueError('coverage_worker_invalid_progress')
                        on_progress(cursor);continue
                chunks.append(line+b'\n')
        if size>MAX_REPLY_BYTES:raise ValueError('coverage_worker_reply_capacity')
        chunks.append(pending)
        return b''.join(chunks)
    reply=asyncio.create_task(bounded_reply())
    pausable=coverage and hasattr(signal,'SIGSTOP')
    paused=False;pause_started=None;paused_seconds=0;pauses=0
    try:
        while not reply.done():
            if stopped():return dict(published=False,reason='updates_stopped')
            if time.monotonic()-start>MAX_SECONDS:raise ValueError('coverage_worker_deadline')
            pressure=not ordinary and BACKGROUND.critical_acquisition_pressure()
            if cooperative:
                if ready and pressure!=paused:
                    try:process.send_signal(signal.SIGUSR1 if pressure else signal.SIGUSR2)
                    except ProcessLookupError:pass
                    if pressure:pause_started=time.monotonic();pauses+=1
                    else:paused_seconds+=time.monotonic()-pause_started
                    paused=pressure
            elif pausable:
                if pressure and not paused:
                    try:process.send_signal(signal.SIGSTOP)
                    except ProcessLookupError:pass
                    else:paused=True;pause_started=time.monotonic();pauses+=1
                elif paused and not pressure:
                    try:process.send_signal(signal.SIGCONT)
                    except ProcessLookupError:pass
                    paused_seconds+=time.monotonic()-pause_started;paused=False
            elif pressure:
                # Match the calculation thread's bounded ingress grace without
                # ever sleeping on the event loop or extending the child lease.
                pressure_deadline=time.monotonic()+2
                while BACKGROUND.critical_acquisition_pressure() and time.monotonic()<pressure_deadline:
                    if stopped():return dict(published=False,reason='updates_stopped')
                    if time.monotonic()-start>MAX_SECONDS:raise ValueError('coverage_worker_deadline')
                    await asyncio.sleep(.01)
                if BACKGROUND.critical_acquisition_pressure():raise AcquisitionDeferred('native_acquisition_catching_up')
            await asyncio.wait({reply},timeout=.1)
        body=await reply
        if len(body)>MAX_REPLY_BYTES:raise ValueError('coverage_worker_reply_capacity')
        await asyncio.wait_for(process.wait(),5)
        if process.returncode:raise ValueError('coverage_worker_failed')
        result=json.loads(body)
        if not isinstance(result,dict):raise ValueError('coverage_worker_invalid')
        if result.get('worker_error'):
            # Only our child-authored safe frame record crosses the diagnostic
            # boundary. Never expose exception messages through owner status.
            logging.getLogger(__name__).error('calculation_worker failed; diagnostic=%s',
                json.dumps(result.get('worker_failure', {}),ensure_ascii=True))
            raise ValueError('coverage_worker_failed')
        if pausable or cooperative:result.update(worker_pauses=pauses,worker_paused_seconds=paused_seconds,
            worker_pause_mode='transaction_safe_checkpoints' if cooperative else 'process_suspension')
        result['worker_admission_wait_seconds']=round(admission_seconds,6)
        return result
    finally:
        primary=sys.exception()
        async def cleanup():
            # A stopped child cannot handle termination until continued. Stop and
            # the unchanged wall-clock deadline always retain ownership through exit.
            try:
                if paused and not cooperative:
                    try:process.send_signal(signal.SIGCONT)
                    except ProcessLookupError:pass
                if process.returncode is None:
                    try:process.terminate()
                    except ProcessLookupError:pass
                    try:await asyncio.wait_for(process.wait(),3)
                    except TimeoutError:
                        try:process.kill()
                        except ProcessLookupError:pass
                        await process.wait()
            finally:
                if not reply.done():reply.cancel()
                await asyncio.gather(reply,return_exceptions=True)

        # Repeated cancellation must not detach a child or its reply reader.
        async def cleanup_outcome():
            try:await cleanup()
            except BaseException as exc:return exc
            return None
        task=asyncio.create_task(cleanup_outcome())
        cancelled=None
        while not task.done():
            try:await asyncio.shield(task)
            except asyncio.CancelledError as exc:cancelled=cancelled or exc
            except BaseException:break
        error=None if task.cancelled() else task.result()
        if task.cancelled():error=asyncio.CancelledError()
        if error is not None:
            from app.diagnostics import failure
            failure(__name__,'calculation_worker_cleanup',error)
            if primary is None and cancelled is None:raise error
        if cancelled is not None and primary is None:raise cancelled


def main():
    from app.storage import store
    store.ROOT=Path(sys.argv[1])
    parent=int(sys.argv[2]);start=time.monotonic()
    if hasattr(os,'nice'):os.nice(10)
    from app.collection.continuous import rss
    from app.collection.background_work import BACKGROUND
    from app.comparison.calculation_control import cancellation
    from app.storage.coverage_latest import reconcile,LOCK
    BACKGROUND.limit=MAX_PROCESS_BYTES
    BACKGROUND.runway=0  # This process owns no source or acquisition objects.
    def guard():
        if os.getppid()!=parent:return True
        if time.monotonic()-start>MAX_SECONDS:raise ValueError('coverage_worker_deadline')
        if rss()>=MAX_PROCESS_BYTES:raise ValueError('coverage_worker_memory_capacity')
        return False
    try:
        with cancellation(guard),store.connect() as db:
            if not db.execute('SELECT pg_try_advisory_lock(%s) owned',(LOCK+1,)).fetchone()['owned']:
                result=dict(published=False,reason='another_coverage_owner')
            else:
                try:result=reconcile(db)
                finally:db.execute('SELECT pg_advisory_unlock(%s)',(LOCK+1,))
        result.update(worker_pid=os.getpid(),worker_peak_rss_bytes=rss(),worker_maximum_bytes=MAX_PROCESS_BYTES,
            worker_seconds=time.monotonic()-start,provider_requests=0)
    except Exception as exc:
        from app.diagnostics import failure_details
        result=dict(worker_error='coverage_worker_failed',worker_failure=failure_details(exc),provider_requests=0)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
