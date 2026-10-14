"""Isolated retained-slate temporal completion and actual Stop evidence."""
import argparse
import asyncio
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import resource
from time import perf_counter
from aiohttp import web, ClientSession
from app.dashboard.current_state import CURRENT_KEY
from app.dashboard.current_contract import packed, stamp, quotes_of
from app.dashboard.multi_game_server import create_app
from tests.ev07_fixture_runtime import FixtureBoundary
from tests.current_fixture import InjectedTestProvider
from tests.test_current_state import owner
from tests.ev08_sustained import observation_digest


def write(out,name,value):out.joinpath(name).write_text(json.dumps(value,indent=2)+'\n')


async def run(args):
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    started=perf_counter()
    with FixtureBoundary() as boundary:
        raw=json.loads(Path(args.retained).read_bytes())
        initial=observation_digest(raw)
        app=create_app(owner=owner(),sessions={},current_provider=InjectedTestProvider(raw));store=app[CURRENT_KEY]
        frozen_mono=perf_counter();store.monotonic=lambda:frozen_mono;store._age_origin=frozen_mono
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        url='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
        write(out,'startup.json',dict(listener_seconds=perf_counter()-started,filesystem_cache_controlled=False,
            complete_state_bytes=len(packed(store._state)),kernel_highwater_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
        if args.stop:
            from app.collection.current_service import CurrentService
            from app.collection.current_policy import DEFAULT
            from app.collection.local_ownership import LocalOwnership
            class OfflineWorker:
                def __init__(self,service,venue):self.closed=False;self.metrics={'requests':0,'acquisition_refused':True}
                async def run(self):await asyncio.Event().wait()
                async def close(self):self.closed=True
            service=CurrentService(config=dict(DEFAULT,aggregate_enabled=False),directory=out/'authored-authority',
                ownership=LocalOwnership(out/'authored-owner.lock'),worker_factory=OfflineWorker)
            service.runtime_id=store._state['runtime_id']
            await service.start(store)
            store.provider=service
            # This explicit authored provider retains synthetic admission only.
            service.allow_synthetic=True
        old=store._state;before_clocks=observation_digest(old)
        assert before_clocks==initial
        quote=next(q for e in old['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)
            if q['calculations']['net_ev']['eligible'])
        held=store.create(dict(schema=old['schema'],runtime_id=old['runtime_id'],state_revision=old['state_revision'],
            quote_id=quote['id'],quote_revision=quote['revision'],client_id='temporal-probe'))
        token=held['selection_id'];frozen=sha256(packed(held['review'])).hexdigest();del held,quote,raw
        lag=[];running=True
        async def sample():
            target=perf_counter()+.05
            while running:
                await asyncio.sleep(max(0,target-perf_counter()))
                lag.append(max(0,perf_counter()-target));target=perf_counter()+.05
        sampler=asyncio.create_task(sample())
        # Advance economic time, retain real monotonic lease time. No source
        # observation, input epoch or price revision is changed by this seam.
        store.monotonic=perf_counter;store._age_origin=perf_counter()
        store._clock_origin=stamp(old['clock_at'])+timedelta(seconds=901)
        tick=perf_counter();store.refresh_age()
        revoked=store._economic_invalidated
        requests=[]
        try:
            async with ClientSession() as client:
                for path in ('/api/current','/api/current/changes?runtime_id='+old['runtime_id']+'&state_revision='+str(old['state_revision']),
                             '/api/comparison','/api/arbs','/api/current/details?runtime_id='+old['runtime_id']+'&state_revision='+str(old['state_revision'])+'&quote_id=missing'):
                    for _ in range(3):
                        sent=perf_counter()
                        async with client.get(url+path) as response:
                            value=await response.json();status=response.status
                        requests.append(dict(route=path.split('?')[0],status=status,complete_refusal_seconds=perf_counter()-sent))
                        assert status==503 and value['error']=='temporal_pending',(status,value)
                        assert not any(key in value for key in ('rows','events','pairs'))
            assert revoked
            if args.stop:
                while store.temporal.metrics['units']<200:await asyncio.sleep(.001)
                iterator=store.temporal.iterator;driver=store.temporal.driver
                assert iterator is not None and iterator.gi_frame is not None
                pool=store.encoded_bodies
                body=pool.encode({'owned':'x'*100000});reader=pool.payload(body,adopt=True)
                blocked=asyncio.Event()
                class Writer:
                    async def write(self,chunk):blocked.set();await asyncio.Event().wait()
                writing=asyncio.create_task(reader.write(Writer()));await blocked.wait()
                stop_tick=perf_counter();await store.close()
                await asyncio.gather(writing,return_exceptions=True)
                assert iterator.gi_frame is None and driver.done()
                assert store._state is old and not pool.owners and not pool.readers
                assert store.temporal.active is None and store.temporal.pending is None
                await asyncio.sleep(.03);assert store._state is old
                await asyncio.sleep(.06);running=False
                sampler.cancel();await asyncio.gather(sampler,return_exceptions=True)
                result=dict(actual_iterator_closed=True,future_done=True,staging_released=True,
                    files=0,readers=0,active=0,pending=0,no_post_stop_publication=True,stop_seconds=perf_counter()-stop_tick,
                    actual_source_lifecycle=True,source_dispatch=False,health_acknowledgements=service.sink.sequence,
                    stopped_source_health=store._shutdown_health,ownership_released=service.ownership.file is None,
                    service_cleanup_complete=service.cleanup_complete)
            else:
                await asyncio.wait_for(asyncio.shield(store.temporal.driver),600)
                assert store.temporal.failure is None,store.temporal.failure
                assert not store._economic_invalidated
                await asyncio.sleep(.06);running=False
                sampler.cancel();await asyncio.gather(sampler,return_exceptions=True)
                state=store._state
                assert state['state_revision']>old['state_revision']
                assert state['comparison_profiles'] is old['comparison_profiles']
                assert observation_digest(state)==initial
                assert sha256(packed(store.get(token)['review'])).hexdigest()==frozen
                body=packed(state);size=len(body);wire_hash=sha256(body).hexdigest();del body
                assert size<64*1024*1024
                write(out,'oracle-input.json',dict(clock_at=state['clock_at'],state_revision=state['state_revision'],expected_sha256=wire_hash))
                result=dict(complete=True,seconds=perf_counter()-tick,state_bytes=size,sha256=wire_hash,
                    original_observations_preserved=True,frozen_lease_preserved=True,
                    runtime_id=state['runtime_id'],input_epoch=store._input_epoch,calculation_clock_at=state['clock_at'])
            result.update(requests=requests,refusal_samples=len(requests),refusal_failures=0,
                temporal_metrics=dict(store.temporal.metrics),loop_lag_boundary='listener through final temporal publication or Stop plus final scheduling turn; excludes startup and proof encoding',loop_lag_samples=len(lag),loop_lag_max_seconds=max(lag,default=0),
                kernel_highwater_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                evidence_class='authored original 150-game/2000-quote temporal boundary; refusals are not completed estimate latency',
                provider_requests=0,forbidden_calls=boundary.calls,network=boundary.network)
            write(out,'result.json',result)
        finally:
            running=False;sampler.cancel();await asyncio.gather(sampler,return_exceptions=True)
            try:await runner.cleanup()
            finally:write(out,'cleanup.json',dict(closed=store.closed,files=len(store.encoded_bodies.owners),readers=len(store.encoded_bodies.readers),
                temporal_driver_done=store.temporal.driver is None or store.temporal.driver.done(),
                active=store.temporal.active is not None,pending=store.temporal.pending is not None,
                forbidden_calls=boundary.calls))
    print(json.dumps(dict(status='passed',mode='stop' if args.stop else 'complete',peak=result['kernel_highwater_bytes'])))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);parser.add_argument('--retained',required=True);parser.add_argument('--stop',action='store_true')
    asyncio.run(run(parser.parse_args()))
