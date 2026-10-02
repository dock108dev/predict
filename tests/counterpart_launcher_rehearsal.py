"""OFFLINE full 180s ordinary control rehearsal; real URLs are prohibited."""
import asyncio,importlib.util,json,sys,time
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from aiohttp import web
from tests.test_counterpart_completion import RetainedTransport as Fixture,PACKAGE,configuration
from app.collection.native_approval import digest,implementation
from app.collection.transport_session import reopen
from app.collection.source_session import verify_rows
from app.dashboard.session_history import load,project_rows

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/v1-counterpart-completion-20261001-v1'

async def main():
    folder=OUT/('OFFLINE-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'));folder.mkdir()
    f=Fixture();began=time.monotonic()
    with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
        o=await f.boot(folder)
        # Exact script code, isolated package files and actual ordinary routes.
        sys.path.insert(0,str(PACKAGE))
        import launch,control
        launch.PACKAGE=folder;control.PACKAGE=folder
        spec=configuration();attempt=dict(attempt_id='7b71bf9c-86c5-45d6-87f5-cbd8b98bd0b3',output=str(o.pilot_output.resolve()))
        for name in ('launch.py','control.py','AUTHORIZATION.txt'):(folder/name).write_bytes((PACKAGE/name).read_bytes())
        (folder/'execute.py').write_bytes((PACKAGE/'execute-child.py').read_bytes())
        (folder/'run-spec.json').write_text(json.dumps(spec));(folder/'attempt.json').write_text(json.dumps(attempt))
        hashes={n:sha256((folder/n).read_bytes()).hexdigest() for n in ('launch.py','control.py','execute.py','AUTHORIZATION.txt','run-spec.json','attempt.json')}
        identity=dict(implementation_sha256=digest(implementation()),spec_sha256=digest(spec),attempt_id=attempt['attempt_id'],output=attempt['output'],file_hashes=hashes)
        (folder/'identity.json').write_text(json.dumps(identity))
        (folder/'approval.json').write_text(json.dumps(dict(approved=True,**identity,classification='OFFLINE synthetic approval; no live authority')))
        o.pilot_output.rmdir() # Empty OFFLINE owner-created destination only.
        captured={}
        from app.dashboard.coverage_owner import CoverageOwner
        from aiohttp.test_utils import TestClient,TestServer
        await f.client.close()
        def fixture_owner(*args,**kwargs):
            # Only transport and evidence mode substitution; run the actual launcher.
            kwargs['endpoints']=f.endpoints
            kwargs['spec_factory']=lambda:dict(spec,mode='mock')
            kwargs['native_approval_path']=None
            captured['owner']=CoverageOwner(*args,**kwargs)
            return captured['owner']
        with patch.object(launch,'validate_approval',return_value=None),patch('app.dashboard.coverage_owner.CoverageOwner',side_effect=fixture_owner),patch('aiohttp.web.run_app',side_effect=lambda app,**kw:captured.update(app=app)),patch.object(sys,'argv',['launch.py','--serve']):
            launch.main()
        o=captured['owner'];f.owner=o
        f.client=TestClient(TestServer(captured['app']));await f.client.start_server()
        f.origin={'Origin':str(f.client.make_url('/')).rstrip('/')}
        loop=asyncio.get_running_loop()
        async def request(path,method,payload):
            if path=='/probe-binding':return dict(status=200,body=identity)
            response=await f.client.request(method,path,json=payload if method=='POST' else None,headers=f.origin)
            return dict(status=response.status,body=await response.json())
        def wire(path,method='GET',payload=None):return asyncio.run_coroutine_threadsafe(request(path,method,payload),loop).result(timeout=15)
        async def pump():
            while o.session is None:await asyncio.sleep(.05)
            original=o.session.journal.save
            def save(row):original(row);f.books+=row['type']=='prediction_book';f.changed.set()
            o.session.journal.save=save
            while len(f.active())<2 and not o.session.stop_event.is_set():await asyncio.sleep(.05)
            if o.session.stop_event.is_set():return
            await f.images()
            while not o.session.stop_event.is_set():
                for c in f.active():await f.send(c)
                await asyncio.sleep(1)
        pumping=asyncio.create_task(pump())
        try:
            with patch.object(launch,'validate_approval',return_value=None),patch.object(control,'request',side_effect=wire):await asyncio.to_thread(control.run)
            assert identity['implementation_sha256']==digest(implementation()),'Candidate changed during rehearsal'
            assert o.error is None,o.error
            rows=reopen(o.session.journal.path)['rows'];saved=load(o.session.output)
            assert saved==project_rows(rows,saved['durable_cursor'])
            assert o.session.cleanup_complete
            assert len(f.odds_calls)<=7 and o.session.aggregate.budget.credits<=8
            assert sum(r['type']=='prediction_book' and r['source']=='kalshi' for r in rows)>2
            assert sum(r['type']=='prediction_book' and r['source']=='polymarket_us' for r in rows)>2
            from app.dashboard.session_projection import SessionProjection
            projector=SessionProjection();has_pair=False
            for row in rows:
                projector.apply(row)
                if row['type']=='prediction_book' and projector.snapshot(mode='saved')['manual_comparisons']:has_pair=True
            assert has_pair, 'No valid retained counterpart cutoff'
            assert not saved['manual_comparisons'], 'Stop must not leave disconnected current pairs'
            assert not f.award_rounds
            import subprocess
            code='from app.dashboard.session_history import load;from app.dashboard.session_projection import stable;import sys;print(stable(load(sys.argv[1])))'
            fresh=await asyncio.to_thread(subprocess.check_output,[sys.executable,'-c',code,str(o.session.output)],text=True)
            assert fresh.strip()==__import__('app.dashboard.session_projection',fromlist=['stable']).stable(saved)
            result=dict(classification='OFFLINE exact script/control and ordinary owner Start/Stop; retained selected predicate IDs/terms; explicitly synthetic schedules, envelopes, quota, aggregate prices and WS books; loopback only',
                implementation_sha256=digest(implementation()),spec_sha256=digest(spec),duration=180,elapsed_seconds=time.monotonic()-began,
                operations=dict(aggregate=len(f.odds_calls),kalshi=sum(p.startswith('/trade-api') for p,q in f.native_calls),us=sum(p.startswith('/v1') for p,q in f.native_calls)),
                simulated_reserved_credits=o.session.aggregate.budget.credits,actual_provider_requests=0,actual_credit_use=0,credential_access=0,
                automatic_deadline=o.session.reason,ordinary_control=True,actual_launcher_main=True,synthetic_schedule_and_envelope_packaging=True,cleanup=o.session.cleanup_complete,
                exact_reopening=True,fresh_process_reopening=True,both_native_streams_and_independent_updates=True,raw_replay=verify_rows(rows),resources=o.session.resources(),unused_budget='expires; never a retry allowance')
            (folder/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(path=str(folder),**result)),flush=True)
        finally:
            pumping.cancel();await asyncio.gather(pumping,return_exceptions=True);await f.close()

if __name__=='__main__':asyncio.run(main())
