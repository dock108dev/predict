"""Independent process supervisor for the offline diagnostic qualification.

The CLI runs synthetic fixtures only. A stalled collector is terminated at the
fixed 300-second intake boundary, leaving an explicitly incomplete history.
"""
import argparse
import asyncio
import json
import multiprocessing
import os
from pathlib import Path
import resource
import time

from .delivery_budget import Clock, CAP, MIB
from .delivery_capture import DiagnosticOwner, Session


def worker(output,ownership,attempt,pipe,stall,candidate):
    from tests.delivery_fixture import NetworkGuard, Server
    resource.setrlimit(resource.RLIMIT_CPU,(600,600))
    owner=DiagnosticOwner(output,ownership,attempt)
    async def run():
        from .supervised_live import identity
        if identity()!=candidate:raise ValueError('frozen diagnostic candidate changed')
        owner.acquire();server=Server(busy=True);session=None
        try:
            transport=await server.start();session=Session(output,transport)
            async def controls():
                while True:
                    if pipe.poll():
                        action=pipe.recv()
                        if action['action']=='stop':
                            if stall:
                                pipe.send(dict(event='stall_entered',clock=Clock().anchor()))
                                time.sleep(360)  # Deliberately block collector loop past cutoff.
                            session.stop('direct_stop')
                    await asyncio.sleep(.01)
            control=asyncio.create_task(controls())
            try:
                def started(origin):
                    session.records.metadata('candidate.json',candidate)
                    pipe.send(dict(event='started',mono=origin,clock=Clock().anchor()))
                await session.run(started)
            finally:control.cancel();await asyncio.gather(control,return_exceptions=True)
            pipe.send(dict(event='closed',mono=session.closed_at,cleanup_finished=session.cleanup_finished))
            await server.close()
            summary,receipt=session.finalize()
            pipe.send(dict(event='finished',reason=session.reason,complete=session.complete,
                receipt=receipt,books=session.book_counts,accounting=session.records.accounting()))
        except BaseException as exc:
            pipe.send(dict(event='failed',error=type(exc).__name__+':'+str(exc)))
            if session and session.records and not session.records.history.closed:session.records.history.abort()
            raise
        finally:owner.release()
    with NetworkGuard():asyncio.run(run())


def supervise(output,ownership,attempt,*,stall=False,notify=None):
    """One call = one consumed major lifecycle run; no restart/retry logic."""
    output=Path(output);ctx=multiprocessing.get_context('spawn');parent,child=ctx.Pipe()
    from .supervised_live import identity
    candidate=identity()
    process=ctx.Process(target=worker,args=(output,ownership,attempt,child,stall,candidate))
    before=time.monotonic();events=[];started=None;closed=None;sent=False;cutoff=False
    process.start();child.close()
    try:
        while process.is_alive():
            if parent.poll(.05):
                try:event=parent.recv()
                except EOFError:break
                events.append(event)
                if notify:notify(event)
                if event['event']=='started':started=event['mono']
                if event['event']=='closed':closed=event['mono']
            now=time.monotonic()
            if started is not None and not sent and now>=started+240:
                event=dict(action='stop',intended=started+240,clock=Clock().anchor())
                parent.send(event);events.append(dict(event='direct_stop_sent',**event));sent=True
            if started is not None and closed is None and now>=started+300:
                events.append(dict(event='independent_cutoff',clock=Clock().anchor()))
                process.terminate();cutoff=True;break
            if closed is not None and now>=closed+300:
                events.append(dict(event='finalization_cutoff',clock=Clock().anchor()));process.terminate();cutoff=True;break
            if started is None and now-before>60:
                process.terminate();events.append(dict(event='startup_process_failure'));break
            if now-before>=660:process.terminate();break
        process.join(1)
        if process.is_alive():process.kill();process.join(1)
        while parent.poll():
            try:events.append(parent.recv())
            except EOFError:break
    finally:
        if process.is_alive():process.kill();process.join(1)
        parent.close()
    # Outside the receipt's boundary, inside the same attempt output budget.
    result=dict(events=events,exitcode=process.exitcode,cutoff=cutoff,
        wall_seconds=time.monotonic()-before,clock=Clock().anchor(),
        helper_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if __import__('sys').platform=='darwin' else 1024))
    if output.exists():
        retained=sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
        receipt_path=output/'finalization-resources.json'
        writes=json.loads(receipt_path.read_text())['cumulative_application_file_write_bytes'] if receipt_path.exists() else None
        marker=Path(ownership)/(attempt+'.attempt.json');marker_bytes=marker.stat().st_size if marker.exists() else 0
        result['outer_accounting']=dict(receipt_boundary='collector receipt excludes later supervisor and shared attempt marker',
            helper_payload_bytes=16384,attempt_marker_bytes=marker_bytes,
            retained_bytes_including_helper_and_marker=retained+16384+marker_bytes,
            cumulative_writes_including_helper_and_marker=writes+16384+marker_bytes if writes is not None else None,
            interrupted_write_accounting='unknown' if writes is None else 'complete')
        body=json.dumps(result,indent=2).encode()
        if len(body)>16384:raise ValueError('helper_output_cap')
        if retained+16384+marker_bytes>CAP['output'] or (writes is not None and writes+16384+marker_bytes>CAP['write_bytes']):raise ValueError('joint_output_cap')
        with (output/'supervisor.json').open('xb') as f:f.write(body.ljust(16384,b' '));f.flush();os.fsync(f.fileno())
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--ownership',type=Path,required=True);p.add_argument('--attempt',required=True)
    p.add_argument('--fixture-stall',action='store_true');a=p.parse_args()
    result=supervise(a.output,a.ownership,a.attempt,stall=a.fixture_stall)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
