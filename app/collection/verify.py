"""Reproducible isolated synthetic checks; no owner connection helper."""
import argparse
import asyncio
import json
from pathlib import Path
import resource
from time import monotonic
from app.collection.environment import Environment
from app.collection.storage import Repository
from app.collection.session import Session,checked
from app.collection.synthetic import WallClock

async def run(seconds,output):
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    from hashlib import sha256
    import subprocess
    files={str(p):sha256(p.read_bytes()).hexdigest() for p in Path('app/collection').rglob('*') if p.is_file() and '__pycache__' not in str(p)}
    (out/'runtime-implementation.json').write_text(json.dumps(dict(head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),files=files),indent=2))
    env=Environment.create();db=env.connect()
    try:
        limits=checked(dict(seconds=seconds) if seconds==900 else dict(seconds=seconds,prediction_poll=1,reference_poll=2,discovery_poll=2,calculation_poll=2))
        session=Session(Repository(db,out,limits),WallClock(),out,limits)
        await session.start()
        samples=[]
        while not session.task.done():
            status=session.status();status.pop('view',None)
            status['rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            samples.append(status)
            await asyncio.sleep(min(10,seconds))
        await session.task
        (out/'resource-samples.json').write_text(json.dumps(samples,indent=2))
        result=session.status();print(json.dumps(result,default=str))
        assert result['state']=='completed',result['reason']
        assert result['delivered']==result['persisted']
        assert result['calculations']>0
        assert result['wall_seconds']>=seconds
        from app.collection.reopen import reopen
        replayed=await asyncio.to_thread(reopen,out/session.sid)
        (out/'replay-verification.json').write_text(json.dumps(dict(session=session.sid,exact_replays=replayed['calculations'],counts=replayed['counts'],health_contexts=sum(x.get('session_context') is not None for x in replayed['snapshots']))))
        if seconds==900:
            from app.reference.records import ReferenceGap
            gaps=[r for r in session.repo.refs.records() if isinstance(r,ReferenceGap)]
            assert any(r.reason=='transport_failure' for r in gaps)
            assert any(r.recovery=='fresh_snapshot' for r in gaps)
    finally:db.close();env.remove(out/'cleanup')

def main():
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=900);p.add_argument('--output',required=True);args=p.parse_args()
    asyncio.run(run(args.seconds,args.output))
if __name__=='__main__':main()
