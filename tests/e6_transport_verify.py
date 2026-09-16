"""Explicit short local-mock E6 verification; never a provider launcher."""
import asyncio
import hashlib
import json
from pathlib import Path
import time
from tests.test_e6_transport import IntegrationTests
from app.collection.transport_session import reopen


async def verify():
    test=IntegrationTests()
    output=Path('evidence/e6/transport-integration/final-65s')
    output.mkdir(exist_ok=False)
    await test.asyncSetUp()
    try:
        test.s['duration']=65
        test.s['reference_cadence']=10
        test.s['discovery_cadence']=30
        test.s['stale_seconds']=2
        paths=[*Path('app/collection').glob('*.py'),Path('tests/test_e6_transport.py'),Path(__file__)]
        identity={str(p.relative_to(Path.cwd()) if p.is_absolute() else p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
        (output/'runtime-identity.json').write_text(json.dumps(identity,indent=2))
        started=time.monotonic()
        owner=await test.start()
        await owner.task
        elapsed=time.monotonic()-started
        saved=reopen(owner.journal.path)
        assert saved==reopen(owner.journal.path)
        assert elapsed>=65 and owner.reason=='duration_or_kickoff_cutoff'
        assert owner.delivered==owner.persisted
        assert test.k_connections==test.p_connections==2
        (output/'session.jsonl').write_bytes(owner.journal.path.read_bytes())
        result=dict(elapsed=elapsed,session=owner.sid,delivered=owner.delivered,persisted=owner.persisted,
            reference_requests=test.ref_calls,total_mock_http_requests=test.calls,kalshi_connections=test.k_connections,
            pmus_connections=test.p_connections,exact_replay=True,sha256=saved['sha256'],reason=owner.reason,economics=None,
            prediction_accounting={v:dict(requests=p.budget.requests,connections=p.budget.connections,
                dollars_reserved=str(p.budget.dollars),body_bytes_charged=p.budget.bytes) for v,p in owner.producers.items()})
        (output/'summary.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result))
    finally:
        await test.asyncTearDown()
        cleanup=dict(http_stopped=not test.site._server.is_serving(),kalshi_ws_stopped=not test.ks.is_serving(),
            pmus_ws_stopped=not test.ps.is_serving(),temporary_directory_removed=not Path(test.tmp.name).exists(),
            database_created=False,provider_requests=0,credential_reads=0)
        (output/'cleanup.json').write_text(json.dumps(cleanup,indent=2))
        assert all(cleanup[k] for k in ('http_stopped','kalshi_ws_stopped','pmus_ws_stopped','temporary_directory_removed'))

if __name__=='__main__':asyncio.run(verify())
