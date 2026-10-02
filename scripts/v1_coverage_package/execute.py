"""One approved supervised launch/control; owned children closed within 240s."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
import launch
PACKAGE=Path(__file__).resolve().parent

def execute():
    spec,output=launch.prepared(True)
    began=time.monotonic();children=[];outcome='interrupted'
    with (PACKAGE/'supervisor-attempt.json').open('x') as f:
        json.dump(dict(consumed=True,attempt_id=json.loads((PACKAGE/'attempt.json').read_text())['attempt_id'],supervised_seconds=240),f);f.flush();os.fsync(f.fileno())
    # All children are owned here; never signal another app/server.
    try:
        with open(os.devnull,'wb') as log:
            server=subprocess.Popen([sys.executable,str(PACKAGE/'launch.py'),'--serve'],stdout=log,stderr=log,env=dict(os.environ,PYTHONUNBUFFERED='1'));children.append(server)
            # Ready signal is written by the actual launcher's app startup hook.
            while not (PACKAGE/'server-ready.json').exists():
                if server.poll() is not None:raise ValueError('Owned launcher failed')
                if time.monotonic()-began>=15:raise TimeoutError('Owned launcher startup deadline')
                time.sleep(.05)
            with open(os.devnull,'wb') as ctl:
                worker=subprocess.Popen([sys.executable,str(PACKAGE/'control.py'),'--run'],stdout=ctl,stderr=ctl);children.append(worker)
                code=worker.wait(timeout=max(.01,237-(time.monotonic()-began)))
                outcome='control_complete' if code==0 else 'control_failed'
    except (Exception,KeyboardInterrupt) as exc:outcome=type(exc).__name__
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=max(.01,min(1,239-time.monotonic()+began)))
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=1)
        with (PACKAGE/'supervisor-result.json').open('x') as f:json.dump(dict(outcome=outcome,elapsed_seconds=time.monotonic()-began,children_reaped=all(c.poll() is not None for c in children),unused_budget='expires; never refunded or reused'),f)
    if outcome!='control_complete':raise SystemExit('Supervised collection ended: '+outcome+'; never retry')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',action='store_true');a=p.parse_args()
    if a.run:execute()
    else:launch.prepared(False);print('PASS: unused sealed package, no activation/provider/credential access')
if __name__=='__main__':main()
