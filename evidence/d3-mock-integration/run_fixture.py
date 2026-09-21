"""Fresh-process local collector evidence. Run from repo with PYTHONPATH=."""
import asyncio
from collections import Counter
from hashlib import sha256
import ipaddress
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch
from app.collection.segmented import SegmentedReader, digest_file, POLICY
from app.collection.continuous import rss
from tests.segmented_collector_fixture import Fixture

ROOT=Path('evidence/d3-mock-integration')

async def exercise(scenario, output):
    f=Fixture(kalshi_markets=21 if scenario=='resource-stop' else 1)
    o=await f.start(output)
    s=o.session;checkpoints=[]
    try:
        if scenario=='busy-refresh-stop':
            await f.at_local(1019)
            prior_connections=s.connection_attempts
            def checkpoint(stage):
                checkpoints.append(dict(stage=stage,logical=s.delivered,
                    published=s.discovery.published_generation,
                    applied={v:p.applied_generation for v,p in s.producers.items()}))
            s.journal.history.fault=checkpoint
            await s.discovery.discover(force=True)
            await f.wait(lambda:all(p.applied_generation==2 for p in s.producers.values()))
            assert s.connection_attempts==prior_connections
            await f.busy(2300)
            before_stop=dict(coverage=s.status_coverage(),active_fixture_sockets=len(f.active()),
                logical=s.delivered,connection_attempts=s.connection_attempts,frames=f.frames,books=f.books)
            assert len(f.active())==2 and all(x['usable']>0 for x in before_stop['coverage'].values())
            await o.stop()
        elif scenario=='resource-stop':
            await f.busy(4096)
            before_stop=dict(intended_stop_issued=False,logical=s.delivered,reason=s.reason)
            assert s.reason=='offline_segment_cap'
        elif scenario=='stop-at-rotation':
            await f.at_local(1019)
            before_stop=dict(coverage=s.status_coverage(),active_fixture_sockets=len(f.active()),logical=s.delivered)
            def pending_stop(stage):
                checkpoints.append(dict(stage=stage,logical=s.delivered,published=s.discovery.published_generation))
                if stage=='seal_fsynced':
                    s.request_stop('manual_stop');asyncio.create_task(o.stop())
            s.journal.history.fault=pending_stop
            await s.discovery.discover(force=True)
        elif scenario=='rotation-failure':
            await f.at_local(1023)
            before_stop=dict(coverage=s.status_coverage(),active_fixture_sockets=len(f.active()),logical=s.delivered)
            def fail(stage):
                if stage=='manifest_fsynced':raise OSError('isolated injected publication failure')
            s.journal.history.fault=fail
            await f.send(f.active()[0])
        else:raise ValueError('unknown scenario')
        await o.finalizer
        if scenario=='rotation-failure':
            assert o.mock_result['status']=='failed' and not s.journal.terminal_acknowledged
        else:
            assert o.mock_result['status']=='complete',o.mock_result
            replay=json.loads((s.output/'replay.json').read_text())
            assert replay['sequence_sha256']==f.sequence.hexdigest()
            assert replay['counts']['prediction_book']==f.books
        assert s.queue.qsize()==0 and s.cleanup_complete and o.owner_lock is None
        artifacts={str(p.relative_to(output)):dict(bytes=p.stat().st_size,sha256=digest_file(p)) for p in output.rglob('*') if p.is_file()}
        history=s.journal.history.accounting()
        state=SegmentedReader(s.output/'history').inspect()
        result=dict(scenario=scenario,classification='new synthetic local native observations; not real venue data or repeated historical IDs',
            session=s.sid,before_stop=before_stop,checkpoints=checkpoints,outcome=o.mock_result,
            resources=s.resources(),accounting=s.accounting(),coverage=s.status_coverage(),discovery=s.discovery.status(),
            observer_rows=f.rows,observer_books=f.books,observer_packets=f.books*2,observer_frames=f.frames,
            observer_sequence_sha256=f.sequence.hexdigest(),history_inspection=state,
            same_collector=type(s).__module__+'.'+type(s).__name__,same_owner=type(o).__module__+'.'+type(o).__name__,
            production_mode_selected=False,fixture_connections=len(f.connections),rest_requests=len(f.rest_calls),
            policy=POLICY,files=artifacts,total_output_bytes=sum(x['bytes'] for x in artifacts.values()),
            metadata_bytes=sum(x['bytes'] for name,x in artifacts.items() if '/history/' not in name),
            rss_peak=rss())
        return result
    finally:await f.close()

if __name__=='__main__':
    scenario=sys.argv[1];output=ROOT/'qualified'/scenario;output.mkdir(parents=True,exist_ok=False)
    original=socket.socket.connect;destinations=Counter()
    def local_connect(sock,address):
        if not isinstance(address,tuple) or not ipaddress.ip_address(address[0]).is_loopback:
            raise AssertionError('non-loopback connection blocked')
        destinations[address[0]]+=1
        return original(sock,address)
    with patch('socket.socket.connect',local_connect),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials blocked')):
        result=asyncio.run(exercise(scenario,output))
    result['connected_addresses']=dict(destinations)
    paths=sorted(p for base in ('app','tests') for p in Path(base).rglob('*') if p.is_file() and p.suffix in ('.py','.json','.js','.html','.css'))
    paths.append(Path(__file__))
    hashes={str(p):digest_file(p) for p in paths}
    result['source_sha256']=hashes
    result['candidate_identity_sha256']=sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    (ROOT/(scenario+'-result.json')).write_text(json.dumps(result,indent=2))
    print(json.dumps({k:result[k] for k in ('scenario','session','outcome','accounting','total_output_bytes','candidate_identity_sha256')},indent=2))
