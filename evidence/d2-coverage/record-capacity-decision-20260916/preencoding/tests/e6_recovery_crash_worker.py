"""Disposable localhost producers. Parent kills this process; never production access."""
import asyncio,json,sys
from pathlib import Path
from tests.test_e6_transport import IntegrationTests
from app.collection.transport_session import TransportSession

async def main(output,phase):
    import fcntl
    lock=(output.parent/'owner.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    fixture=IntegrationTests();await fixture.asyncSetUp()
    fixture.s.update(reference_enabled=False,duration=120,discovery_cadence=90,stale_seconds=20)
    fixture.s['prediction']['connections']=3
    owner=TransportSession(fixture.s,output,fixture.endpoints);fixture.owner=owner
    await owner.start()
    folder=Path(output)
    # All URLs come from freshly bound local test servers; no credential loader is used.
    for _ in range(1000):
        if phase=='before_image' and all(p.adapter for p in owner.producers.values()):break
        if phase in ('books','torn','reconnect','finalization') and all(v=='connected' for v in owner.health.values()) and all(p.budget.connections>=2 for p in owner.producers.values()):break
        await asyncio.sleep(.005)
    if phase=='reconnect':
        for _ in range(1000):
            if owner.health['kalshi']=='connected' and owner.producers['kalshi'].budget.connections>=2:break
            await asyncio.sleep(.005)
        await owner.producers['kalshi'].interrupt_connection()
    if phase=='finalization':await owner.stop()
    if phase=='torn':
        # Simulate an OS-visible partial append after already fsynced records.
        owner.journal.file.write(b'{"previous":"torn-write');owner.journal.file.flush()
        import os;os.fsync(owner.journal.file.fileno())
    (folder/'ready.json').write_text(json.dumps(dict(pid=__import__('os').getpid(),phase=phase,journal=str(owner.journal.path),session=owner.sid,endpoints=fixture.endpoints)))
    await asyncio.Event().wait()

if __name__=='__main__':asyncio.run(main(Path(sys.argv[1]),sys.argv[2]))
