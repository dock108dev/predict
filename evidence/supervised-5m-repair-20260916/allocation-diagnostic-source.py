import gc,json,resource,signal,tracemalloc,time
from pathlib import Path
from app.dashboard.bounds import retained_bytes
from tests.supervised_fixture import Representative
from app.collection.continuous import rss
signal.alarm(120)
resource.setrlimit(resource.RLIMIT_CPU,(120,120))
resource.setrlimit(resource.RLIMIT_FSIZE,(4*1024**2,4*1024**2))
gc.collect();tracemalloc.start(10)
f=Representative()
fixture=retained_bytes(dict(catalog=f.catalog,snapshots=f.snapshots,us_images=f.us_images,delta_templates=f.delta_templates))
gc.collect();baseline=tracemalloc.get_traced_memory();samples=[]
# Deliberately disable cyclic GC for only 12 accounting calls to expose
# ownership of temporaries; this is diagnostic, not an RSS qualification.
gc.disable()
for i in range(12):
    n=retained_bytes(f.catalog)
    samples.append(dict(call=i+1,traced=tracemalloc.get_traced_memory(),rss=rss()))
    if rss()>256*1024**2:raise RuntimeError('diagnostic ceiling')
snapshot=tracemalloc.take_snapshot();before=tracemalloc.get_traced_memory();gc.enable();collected=gc.collect();after=tracemalloc.get_traced_memory()
result=dict(fixture_retained_bytes=fixture,baseline=baseline,samples=samples,before_gc=before,after_gc=after,collected=collected,top=[str(x) for x in snapshot.statistics('lineno')[:15]],rss=rss(),note='same-process fixture; diagnostic GC disabled for 12 calls only; no collector run')
Path('evidence/supervised-5m-repair-20260916/allocation-diagnostic.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
