"""Isolated explicit Start/Stop for one frozen live attempt; never a beta factory."""
import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import time

from .supervised import NAME, PROFILE
from .venue_access import ENDPOINTS, REFERENCES, Credential, endpoint

ROOT = Path(__file__).resolve().parents[2]


def validate_live_endpoints(endpoints):
    if set(endpoints) != set(ENDPOINTS):
        raise ValueError('exactly the two established venues required')
    for venue in ENDPOINTS:
        if set(endpoints[venue]) != {'rest', 'ws'}:
            raise ValueError('unexpected destination field')
        for kind, value in endpoints[venue].items():
            endpoint(venue, kind, value)


def validate_live(spec, endpoints, credentials=None, *, require_credentials=False):
    from .run_spec import preflight
    validate_live_endpoints(endpoints)
    if spec.get('supervised_profile') != NAME or spec.get('mode') != 'real' or spec.get('reference_enabled', False):
        raise ValueError('isolated real prediction-only profile required')
    if spec.get('duration') != 300 or spec.get('discovery_cadence') != 120:
        raise ValueError('frozen duration and refresh required')
    for venue in ENDPOINTS:
        if spec.get('sources', {}).get(venue, {}).get('credential_reference') != REFERENCES[venue]:
            raise ValueError('existing project credential reference required')
    if not preflight(spec, supervised_live=True)['valid']:
        raise ValueError('live specification preflight failed')
    if credentials is not None or require_credentials:
        if not isinstance(credentials, dict) or set(credentials) != set(ENDPOINTS):
            raise ValueError('both dedicated project credentials required')
        for venue, credential in credentials.items():
            if type(credential) is not Credential or credential.venue != venue:
                raise ValueError('invalid dedicated credential object')


def identity():
    from .segmented import digest_file
    paths = sorted(p for base in ('app', 'tests') for p in (ROOT/base).rglob('*')
                   if p.is_file() and p.suffix in ('.py', '.json', '.js', '.html', '.css'))
    files = {str(p.relative_to(ROOT)): digest_file(p) for p in paths}
    return dict(files=files, sha256=sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest())


def verify_candidate(path):
    expected = json.loads(Path(path).read_text())
    if identity() != expected:
        raise ValueError('frozen candidate changed')
    return expected['sha256']


def socket_path(output):
    return '/tmp/predict-supervised-'+sha256(str(Path(output).resolve()).encode()).hexdigest()[:20]+'.sock'


class Control:
    def __init__(self, owner, candidate):
        self.owner = owner
        self.candidate = candidate
        self.events = []
        self.finished = asyncio.Event()
        self.final_result = None

    def event(self, action):
        s = self.owner.session
        record = dict(action=action, utc=datetime.now(timezone.utc).isoformat(), monotonic=time.monotonic(),
                      elapsed=(time.monotonic()-s.started_monotonic if s and s.started_monotonic else None))
        self.events.append(record)
        return record

    async def stop(self):
        s = self.owner.session
        record = self.event('explicit_stop')
        if s and not s.stop_event.is_set():
            self.before_stop = dict(coverage=s.status_coverage(), discovery=s.discovery.status(), resources=s.resources())
            await self.owner.stop()
            record['intake_closed'] = s.intake_closed
        else:
            record['already_stopped'] = True
        return record

    def status(self):
        o = self.owner; s = o.session
        return dict(active=o.active(), session=s.sid if s else None, reason=s.reason if s else None,
                    elapsed=time.monotonic()-s.started_monotonic if s and s.started_monotonic else None,
                    start_available=not (o.pilot_output/'attempt.json').exists() and not o.active(),
                    coverage=s.status_coverage() if s and hasattr(s, 'discovery') else None,
                    discovery=s.discovery.status() if s and hasattr(s, 'discovery') else None,
                    events=self.events, final_result=self.final_result)

    async def finalize(self):
        await self.owner.finalizer
        s = self.owner.session
        from .finalization import write_supplement
        result = dict(candidate=self.candidate, session=s.sid, events=self.events,
            before_stop=getattr(self, 'before_stop', None), finalization=self.owner.mock_result,
            accounting=s.accounting(), resources=s.resources(), coverage=s.status_coverage(),
            discovery=s.discovery.status(), snapshots=s.snapshots, inventory=s.discovery.inventory,
            ever_market_ids={v:{k:sorted(ids) for k,ids in p.ever.items()} for v,p in s.producers.items()},
            connection_attempts=s.connection_attempts,
            task_done=s.task.done(), owner_released=self.owner.owner_lock is None,
            all_group_tasks_done=all(g['task'].done() for p in s.producers.values() for g in p.groups.values() if 'task' in g),
            all_streams_closed=all(g['producer'].stream is None or g['producer'].stream.closed for p in s.producers.values() for g in p.groups.values()),
            collection_seconds=s.collection_seconds, result_prepared_utc=datetime.now(timezone.utc).isoformat(),
            result_prepared_elapsed=time.monotonic()-s.started_monotonic)
        receipt = write_supplement(self.owner.pilot_output, s.journal.history, result,
                                   started=s.started_monotonic, closed=s.closed_at)
        self.final_result=dict(reason=s.reason,
            outcome=self.owner.mock_result['status'] if receipt['status']=='complete' else 'failed',
            owner_released=result['owner_released'], resources=receipt,
            receipt_write_finished_elapsed=time.monotonic()-s.started_monotonic)
        self.finished.set()


async def serve(output, candidate_path):
    from aiohttp import web
    from app.dashboard.coverage_owner import CoverageOwner
    from app.collection.continuous import rss
    from app.dashboard.e6_live import save_json
    candidate = verify_candidate(candidate_path)
    if shutil.disk_usage(output.parent).free < PROFILE['disk_floor']+PROFILE['output'] or rss() >= 192*1024**2:
        raise ValueError('insufficient reserved resources')
    output.mkdir(exist_ok=False)
    os.chmod(output, 0o700)
    owner = CoverageOwner(output/'saved', pilot_output=output, endpoints=ENDPOINTS,
                          profile_name=NAME, supervised_live=True)
    control = Control(owner, candidate)
    tasks = set()
    async def status(request): return web.json_response(control.status())
    async def start(request):
        verify_candidate(candidate_path)
        control.event('explicit_start')
        try:
            sid = await owner.start(duration=300)
        except Exception as exc:
            save_json(output/'start-failure.json',dict(error=type(exc).__name__,events=control.events,attempt_consumed=(output/'attempt.json').exists()))
            return web.json_response(dict(error='Start failed; evidence retained; no retry'), status=422)
        control.events.append(dict(action='start_clock',monotonic=owner.session.started_monotonic,utc=datetime.now(timezone.utc).isoformat()))
        async def finish_once():
            try: await control.finalize()
            finally: control.finished.set()
        task=asyncio.create_task(finish_once());tasks.add(task)
        return web.json_response(dict(session=sid,started_monotonic=owner.session.started_monotonic,candidate=candidate))
    async def stop(request): return web.json_response(await control.stop())
    app=web.Application(client_max_size=1024)
    app.add_routes([web.get('/status',status),web.post('/start',start),web.post('/stop',stop)])
    runner=web.AppRunner(app,access_log=None);await runner.setup()
    path=socket_path(output)
    if Path(path).exists(): raise ValueError('existing control socket; not replaced')
    site=web.UnixSite(runner,path);await site.start();os.chmod(path,0o600)
    save_json(output/'ready.json',dict(pid=os.getpid(),socket=path,candidate=candidate,profile=dict(PROFILE),
                                     free_disk=shutil.disk_usage(output).free,rss=rss(),idle=True))
    print(json.dumps(dict(ready=True,socket=path)),flush=True)
    try:
        await control.finished.wait()
        await asyncio.gather(*tasks)
    finally:
        if owner.active():
            await owner.stop();await owner.finalizer
        await runner.cleanup()
        Path(path).unlink(missing_ok=True)


async def command(output, action):
    import aiohttp
    async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=socket_path(output))) as client:
        async with client.request('GET' if action=='status' else 'POST','http://localhost/'+action) as response:
            result=await response.json()
            print(json.dumps(result),flush=True)
            if response.status!=200:raise SystemExit(1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['serve','status','start','stop'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--candidate',type=Path)
    args=parser.parse_args()
    if args.action=='serve':
        if not args.candidate:parser.error('--candidate is required for serve')
        asyncio.run(serve(args.output.resolve(),args.candidate.resolve()))
    else:asyncio.run(command(args.output.resolve(),args.action))


if __name__=='__main__':main()
