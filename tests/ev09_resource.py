"""Bounded full retained-slate admission/delivery overlap, no acquisition."""
import asyncio
import json
from pathlib import Path
import tempfile
import sys
from unittest.mock import patch
from app.collection.current_service import CurrentService
from app.collection.current_policy import DEFAULT
from app.collection.local_ownership import LocalOwnership
from app.collection.continuous import rss
from app.dashboard.current_state import CurrentStore
from app.dashboard.current_contract import snapshot_inputs

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'test-results/ev09-delivery-20261013'

async def main():
    samples=[]
    def sample(phase,store):
        samples.append(dict(phase=phase,highwater_rss_bytes=rss(),
            owners=len(store.encoded_bodies.owners),readers=len(store.encoded_bodies.readers),
            state_revision=store._state['state_revision']))
        if rss()>768*1024*1024:raise AssertionError('Unchanged process resource cap exceeded')
    with tempfile.TemporaryDirectory(prefix='ev09-replay-') as directory:
        root=Path(directory);diagnostics=root/'diagnostics';diagnostics.mkdir()
        hashes={}
        from hashlib import sha256
        for path in (ROOT/'.local/predict-odds/diagnostics').glob('*.json'):
            body=path.read_bytes();(diagnostics/path.name).write_bytes(body);hashes[path.name]=sha256(body).hexdigest()
        service=CurrentService(dict(DEFAULT,enabled=False),directory=root/'service',
            ownership=LocalOwnership(root/'owner'),retained_directory=diagnostics)
        store=CurrentStore(service)
        await service.start(store);await asyncio.wait_for(service.bootstrap_task,300)
        sample('complete retained admission',store)
        if '--native' in sys.argv:
            records=[json.loads(line) for line in (ROOT/'test-results/conservative-recovery-implemented-20261013/final-delivered-observations.jsonl').open()]
            catalogs={r['source']:r for r in records if r['kind']=='catalog'}
            for source,record in catalogs.items():
                with patch('app.collection.current_sink.utc',return_value=store._state['clock_at']):
                    service.sink.commit(service.row('coverage_inventory',source,
                        inventory=dict(service.sink.reducer.inventory,**{source:record['value']['inventory']}),
                        generation=(service.sink.reducer.generation or 0)+1,
                        previous_generation=service.sink.reducer.generation),service.states)
                sample('actual native catalog '+source,store)
            books={}
            for record in records:
                if record['kind']=='admitted_books':
                    for observation in record['value']['observations']:
                        ref=observation['book']['raw']['ref'];books[(record['source'],ref['event_id'],ref['market_id'])]=observation
            for source,catalog in catalogs.items():
                markets={(m['event_id'],m['id']) for m in catalog['value']['inventory']['markets']}
                observations=[o for (venue,event,market),o in books.items() if venue==source and (event,market) in markets]
                if observations:
                    cat=service.sink.reducer.inventory[source]
                    assert all(any(m['id']==o['book']['raw']['ref']['market_id'] and m['event_id']==o['book']['raw']['ref']['event_id'] for m in cat['markets']) for o in observations), (source,'inventory identity')
                    observations=[dict(o,session_id=service.runtime_id) for o in observations]
                    for offset in range(0,len(observations),service.config['markets_per_source']):
                        with patch('app.collection.current_sink.utc',return_value=store._state['clock_at']):
                            service.sink.commit(service.row('prediction_books',source,
                                observations=observations[offset:offset+service.config['markets_per_source']]),service.states)
                    sample('actual native books '+source,store)
        for iteration in range(4):
            reader=store.encoded_transport_snapshot();sample(f'capture {iteration}',store)
            first=True;delivered=0
            class Writer:
                async def write(self,block):
                    nonlocal first,delivered
                    delivered+=len(block)
                    if first:
                        first=False
                        raw=snapshot_inputs(store._state);raw['state_revision']+=1
                        store.commit(raw);del raw
                        sample(f'admission overlap {iteration}',store)
                    await asyncio.sleep(0)
            await reader.write(Writer());sample(f'complete delivery {iteration}: {delivered} bytes',store)
            assert not store.encoded_bodies.readers and not store.encoded_bodies.owners
        await store.close();sample('closed',store)
        result=dict(evidence_class='isolated replay of installed retained aggregate diagnostics; not live-source qualification',
            source_hashes=hashes,provider_requests=0,cap_bytes=768*1024*1024,
            peak_bytes=max(s['highwater_rss_bytes'] for s in samples),samples=samples,
            ownership=store.encoded_bodies.metrics,collection_enabled_in_actual_installation_unchanged=True)
        (REPORT/('resources-native-replay.json' if '--native' in sys.argv else 'resources-replay.json')).write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result))

if __name__=='__main__':asyncio.run(main())
