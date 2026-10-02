"""180-second isolated integrated success rehearsal. No credential access."""
import asyncio
from datetime import datetime, timezone
import json
from unittest.mock import patch
from tests.test_native_redesign import Fixture, configuration, OUT
from app.collection.native_approval import implementation, digest
from app.collection.transport_session import reopen
from app.dashboard.session_history import load, project_rows

async def main():
    out=OUT/('SIMULATED-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'));out.mkdir()
    candidate=digest(implementation())
    f=Fixture()
    with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
        o=await f.boot(out)
        try:
            await f.start(duration=180,fast=False)
            await f.native_images();await f.images()
            from urllib.parse import urlencode
            feed=await (await f.client.get('/api/dashboard?view=feed')).json()
            details=[]
            for row in feed['comparisons'][:4]:
                q=urlencode(dict(session=row['session'],hash=row['hash'],cutoff=row['cutoff']))
                details.append((q,await (await f.client.get('/api/calculate?'+q)).json()))
            async def update():
                while not o.session.stop_event.is_set():
                    for connection in list(f.active()):await f.send(connection)
                    await asyncio.sleep(5)
            task=asyncio.create_task(update())
            await o.finalizer;task.cancel();await asyncio.gather(task,return_exceptions=True)
            await f.stop_route()
            assert o.error is None,o.error
            rows=reopen(o.session.journal.path)['rows'];saved=load(o.session.output)
            assert saved==project_rows(rows,saved['durable_cursor'])
            assert o.session.cleanup_complete and not o.session.discovery.source_stops
            assert len(f.odds_calls)==37 and all(v==3 for v in f.rounds.values()) and len(f.rounds)==6
            books={v:sum(r['type']=='prediction_book' and r['source']==v for r in rows) for v in ('kalshi','polymarket_us')}
            assert all(n>2 for n in books.values()),books
            for q,d in details:assert d==await (await f.client.get('/api/calculate?'+q)).json()
            assert candidate==digest(implementation()),'Candidate changed during rehearsal'
            result=dict(classification='SIMULATED successful native runtime; retained championship structures plus labeled large/null/small pages; synthetic supported NFL and aggregate updates',
                implementation_sha256=digest(implementation()),spec_sha256=digest(configuration()),duration=180,
                ordinary_start_stop=True,stop_reason=o.session.reason,books=books,native_requests=len(f.native_calls),
                aggregate_requests=len(f.odds_calls),aggregate_cycles=f.rounds,simulated_credits=o.session.aggregate.budget.credits,
                required_cells=len(saved['aggregate_coverage']),details=len(details),exact_reopening=True,cleanup=True,
                resources=o.session.resources(),provider_requests=0,credential_access=0,actual_credits=0)
            (out/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(path=str(out),**result)),flush=True)
        finally:await f.close()

if __name__=='__main__':asyncio.run(main())
