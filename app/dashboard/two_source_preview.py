"""Explicit isolated two-source qualification. No approval means no server/access.

The supervisor is a separate process so a blocked credential lookup or event loop
cannot silently extend collection. It never reads credentials itself.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime,timezone
from app.collection.native_approval import digest,implementation
from app.collection.run_spec import preflight,time_value
from app.collection.two_source_policy import validate
from app.collection.venue_access import ENDPOINTS
from app.dashboard.e6_live import save_json


def check_package(spec,approval,output):
    if (Path(output)/'b3-attempt.json').exists():raise ValueError('attempt already consumed')
    validate(spec)
    if spec['mode']!='real':raise ValueError('real launcher cannot use fixture configuration')
    if approval.get('approved') is not True:raise ValueError('Owner approval pending; no credential or network access')
    if approval.get('spec_sha256')!=digest(spec) or approval.get('implementation_sha256')!=digest(implementation()):raise ValueError('candidate/spec changed after approval')
    if approval.get('output')!=str(Path(output).resolve()):raise ValueError('output differs from frozen approval')
    if not preflight(spec)['valid']:raise ValueError('invalid or expired scope')
    if (Path(output)/'b3-attempt.json').exists():raise ValueError('attempt already consumed')


def supervise(process,output,spec,*,clock=time.monotonic,sleep=time.sleep):
    """Independent hard collection guard; post-close offline saving may finish."""
    output=Path(output);marker=output/'b3-attempt.json';bad_since=None
    while process.poll() is None:
        if marker.exists():
            try:
                attempt=json.loads(marker.read_text())
            except json.JSONDecodeError:
                if bad_since is None:bad_since=clock()
                if clock()-bad_since>=1:
                    process.kill();process.wait()
                    save_json(output/'supervisor-stop.json',dict(reason='unreadable_attempt_marker',state='incomplete; no repeat authorized'))
                    return 1
                sleep(.01);continue # exclusive writer is still flushing
            closed=output/'network-closed.json'
            safe=False
            if closed.exists():
                try:
                    c=json.loads(closed.read_text());safe=c.get('attempt_id')==attempt['attempt_id'] and c.get('monotonic',float('inf'))<=attempt['started_monotonic']+90
                except (ValueError,TypeError):safe=False
            if not safe and clock()>=attempt['started_monotonic']+90:
                process.kill();process.wait()
                save_json(output/'supervisor-stop.json',dict(reason='hard_90_second_deadline',attempt_id=attempt['attempt_id'],state='incomplete; verified prefix only',cleanup='process terminated; no graceful cleanup claim'))
                return 1
        elif datetime.now(timezone.utc)>time_value(spec['start_before']):
            process.terminate()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill();process.wait()
            return 0
        sleep(.05)
    return process.returncode


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec',type=Path,required=True);p.add_argument('--approval',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--port',type=int,default=8820)
    p.add_argument('--child',action='store_true',help=argparse.SUPPRESS)
    a=p.parse_args();spec=json.loads(a.spec.read_text());approval=json.loads(a.approval.read_text())
    check_package(spec,approval,a.output)
    if a.port!=8820:raise ValueError('qualification panel port is frozen at 8820')
    if not a.child:
        a.output.mkdir(parents=True,exist_ok=True)
        import fcntl
        with (a.output/'supervisor.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:raise ValueError('qualification supervisor already owns output') from None
            command=[sys.executable,'-m','app.dashboard.two_source_preview','--child','--spec',str(a.spec.resolve()),'--approval',str(a.approval.resolve()),'--output',str(a.output.resolve())]
            child=subprocess.Popen(command,env=dict(os.environ,PREDICT_TWO_SOURCE_PARENT=str(os.getpid())))
            try:raise SystemExit(supervise(child,a.output,spec))
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:child.wait(timeout=3)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
    if os.environ.get('PREDICT_TWO_SOURCE_PARENT')!=str(os.getppid()):raise ValueError('independent supervisor required')
    from aiohttp import web
    from app.collection.two_source import QualificationOwner,QualificationSession
    from app.dashboard.multi_game_server import create_app
    owner=QualificationOwner(a.output/'legacy',pilot_output=a.output,endpoints=ENDPOINTS,product_mode=True,
        session_factory=QualificationSession,native_approval_path=a.approval,spec_factory=lambda:spec)
    web.run_app(create_app(owner=owner,sessions={}),host='127.0.0.1',port=8820)

if __name__=='__main__':main()
