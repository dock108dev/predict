"""Child process with localhost producers; stdout is the independent test observer."""
import asyncio,json,sys,time,os
from pathlib import Path
from unittest.mock import patch
from tests.test_e6_transport import IntegrationTests
from tests.e6_storage_faults import FaultFile,FsyncFault
from app.collection.transport_session import TransportSession
from app.dashboard import e6_live
from app.collection.recovery import inspect

async def run(output,mode):
    fixture=IntegrationTests();await fixture.asyncSetUp()
    fixture.s.update(reference_enabled=False,duration=(.15 if mode=='deadline' else 8),discovery_cadence=90,stale_seconds=20)
    o=TransportSession(fixture.s,output,fixture.endpoints);fixture.owner=o
    observer=dict(received=0,rejected=0);checkpoint={};book_writes=0;original_emit=o.emit
    def emit(source,row):
        observer['received']+=1
        if o.intake_closed:observer['rejected']+=1
        return original_emit(source,row)
    o.emit=emit
    # Queued records are already fsynced. Hold their bookkeeping consumer until failure.
    normal_consume=o.consume
    async def held_consume():
        await o.stop_event.wait();await normal_consume()
    o.consume=held_consume
    output.mkdir(parents=True)
    e6_live.save_json(output/'run-spec.json',fixture.s)
    await o.start()
    file=o.journal.file;original_write=file.write;original_fsync=os.fsync
    terminal=mode in ('terminal','deadline')
    def write(body):
        nonlocal book_writes
        row=json.loads(body)['row']
        if row['type']=='prediction_book':book_writes+=1
        trigger=(row['type']=='session_finished') if terminal else (row['type']=='prediction_book' and book_writes==3)
        if trigger and not checkpoint and mode not in ('export','manifest'):
            existing=o.journal.path.read_bytes()
            checkpoint.update(records=len(existing.splitlines()),bytes=len(existing),queue_pending=o.queue.qsize(),
                              at=time.monotonic(),record_type=row['type'],stop_reason_before_failure=o.reason)
            fault='disk_full' if mode in ('terminal','race','deadline') else ('partial' if mode=='report' else mode)
            if mode=='race':
                o.request_stop('manual_stop');o.request_stop('duration_or_kickoff_cutoff')
            o.journal.file=FaultFile(file,fault)
            return o.journal.file.write(body)
        return original_write(body)
    # The wrapper is armed only after session metadata is durably acknowledged.
    class Armed:
        def __getattr__(self,name):return getattr(file,name)
        def write(self,body):return write(body)
        def flush(self):return o.journal.file.flush() if o.journal.file is not self else file.flush()
    o.journal.file=Armed()
    def fsync(fd):
        if mode=='fsync' and checkpoint and not file.closed and fd==file.fileno():raise OSError('injected fsync')
        return original_fsync(fd)
    save=e6_live.save_json
    def save_json(path,value):
        if (mode=='export' and path.name=='saved-observations.json') or (mode=='manifest' and path.name=='manifest.pending.json'):
            checkpoint.update(records=len(o.journal.path.read_bytes().splitlines()),bytes=o.journal.path.stat().st_size,
                              queue_pending=o.queue.qsize(),at=time.monotonic(),record_type=path.name)
            # Partial finalization file stays separate from primary journal.
            with path.open('xb') as f:f.write(b'{"partial":')
            raise OSError('injected finalization')
        if mode=='report' and path.name=='storage-failure.json':raise OSError('injected report failure')
        return save(path,value)
    owner=e6_live.Owner(output.parent);owner.session=o
    async def stopping():
        if mode in ('terminal','export','manifest'):
            for _ in range(1000):
                if all(h=='connected' for h in o.health.values()):break
                await asyncio.sleep(.005)
            o.request_stop('manual_stop')
    with patch('os.fsync',fsync),patch.object(e6_live,'save_json',save_json):
        owner.finalizer=asyncio.create_task(owner.finish(output))
        await stopping()
        await asyncio.wait_for(owner.finalizer,10)
    elapsed=time.monotonic()-checkpoint['at'];checkpoint.pop('at')
    assert o.state=='failed' and o.reason=='storage_failure'
    assert o.journal.file.closed and o.cleanup_complete
    assert o.queue.empty() and o.queue.bytes==0
    assert all(not p.stream or p.stream.connection is None for p in o.producers.values())
    a=o.accounting()
    assert a['received']==observer['received'] and a['rejected']==observer['rejected']
    expected_durable=checkpoint['records']-(1 if mode in ('export','manifest') else 0)
    assert a['durably_acknowledged']==expected_durable,(a,checkpoint)
    assert a['unresolved']==(0 if mode in ('terminal','deadline','export','manifest') else 1)
    assert elapsed<6,elapsed
    raw=o.journal.path.read_bytes();report,saved=inspect(o.journal.path)
    assert raw==o.journal.path.read_bytes()
    assert report['counts']['ingress']==expected_durable+(1 if mode in ('flush','fsync') else 0)
    assert report['excluded_trailing_bytes']==(23 if mode in ('short','partial','report') else 0)
    assert not (output/'manifest.json').exists()
    assert o.failure_report==('unavailable' if mode=='report' else 'saved')
    result=dict(mode=mode,session=o.sid,checkpoint=checkpoint,accounting=a,observer=observer,shutdown_seconds=elapsed,
                state=o.state,reason=o.reason,failure_report=o.failure_report,recovery=report,
                journal=str(o.journal.path),cleanup_complete=True,resources_closed=True,api=owner.status())
    await fixture.asyncTearDown()
    return result

if __name__=='__main__':
    with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credential access forbidden')):
        result=asyncio.run(run(Path(sys.argv[1]),sys.argv[2]))
    print(json.dumps(result))
    sys.exit(3) # Explicit failed-storage runtime outcome, not successful capture.
