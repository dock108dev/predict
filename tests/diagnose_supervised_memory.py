"""Bounded diagnostic only; deliberately retains the original cohosted harness."""
import asyncio,gc,ipaddress,json,resource,signal,socket,time,tracemalloc
from pathlib import Path
from unittest.mock import patch
from tests.supervised_fixture import Representative
from app.collection.segmented import SegmentedReader
from app.collection.continuous import rss
from app.collection.supervised import native_state
from app.dashboard.bounds import retained_bytes

async def run(out):
    f=Representative();result={}; original=SegmentedReader.rows
    def sample():
        snap=tracemalloc.take_snapshot()
        return dict(rss=rss(),traced=tracemalloc.get_traced_memory(),top=[str(x) for x in snap.statistics('lineno')[:25]])
    def rows(reader):
        if 'collection' not in result:
            result['collection']=sample();tracemalloc.reset_peak()
        yield from original(reader)
    tracemalloc.start(1)
    try:
        with patch.object(SegmentedReader,'rows',rows):
            o=await f.start(out);s=o.session
            feed=asyncio.create_task(f.traffic())
            until=time.monotonic()+20
            while time.monotonic()<until and not s.stop_event.is_set():
                if rss()>=256*1024**2:raise RuntimeError('diagnostic RSS ceiling')
                await asyncio.sleep(.1)
            await o.stop();await feed;await o.finalizer
            result['finalization']=sample()
            result['outcome']=o.mock_result
            result['retained_components']={
                'fixture':retained_bytes(dict(catalog=f.catalog,snapshots=f.snapshots,us_images=f.us_images,delta_templates=f.delta_templates,connections=f.connections,rest=f.rest_calls)),
                'discovery':retained_bytes(dict(pages=s.discovery.pages,inventory=s.discovery.inventory,markets=s.discovery.markets,partial=s.discovery.partial)),
                'native':retained_bytes([native_state(g['producer'].stream) for p in s.producers.values() for g in p.groups.values() if g.get('producer') and g['producer'].stream]),
            }
            result['after_gc_before']=tracemalloc.get_traced_memory();gc.collect();result['after_gc']=sample()
    finally:
        await f.close()
        result['rss_peak']=rss()
        (out/'diagnostic.json').write_text(json.dumps(result,indent=2,default=str)+'\n')

if __name__=='__main__':
    signal.alarm(120);resource.setrlimit(resource.RLIMIT_CPU,(120,120));resource.setrlimit(resource.RLIMIT_FSIZE,(32*1024**2,32*1024**2))
    out=Path('evidence/supervised-5m-repair-20260916/cohost-diagnostic');out.mkdir(exist_ok=False)
    original=socket.socket.connect
    def connect(s,a):
        assert ipaddress.ip_address(a[0]).is_loopback
        return original(s,a)
    with patch('socket.socket.connect',connect),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials blocked')):
        asyncio.run(run(out))
