"""180-second isolated integrated success rehearsal. No credential access."""
import asyncio
from datetime import datetime, timezone
import json
from unittest.mock import patch
from tests.test_r4_retained import Fixture as VolumeFixture
from tests.test_coverage import pe
from aiohttp import web
from tests.test_native_redesign import configuration
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]/'evidence/native-selectors-20260930'
from app.collection.native_approval import implementation, digest
from app.collection.transport_session import reopen
from app.dashboard.session_history import load, project_rows

class Fixture(VolumeFixture):
    """Initial retained volume; later explicitly synthetic small refresh pages.

    Repeating the 6.15 MB US inventory would exceed the unchanged lifetime cap.
    This fixture demonstrates compact stress followed by useful small refreshes.
    """
    def __init__(self,*args):super().__init__(*args);self.us_generations=0
    async def rest(self,req):
        if req.path=='/v1/events':
            if req.query['offset']=='0':self.us_generations+=1
            if self.us_generations>1:
                e=pe('p');e.update(gameId=1,startTime=self.schedule,markets=[self.us_market('p0')])
                return web.json_response(dict(events=[e]))
        return await super().rest(req)

async def main():
    out=OUT/('SIMULATED-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'));out.mkdir()
    candidate=digest(implementation())
    f=Fixture(True)
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
            assert o.session.discovery.published_generation==3,o.session.discovery.published_generation
            import subprocess,sys
            code='from pathlib import Path; from app.dashboard.session_history import load; from app.collection.native_approval import digest; import sys; print(digest(load(Path(sys.argv[1]))))'
            fresh=subprocess.check_output([sys.executable,'-c',code,str(o.session.output)],text=True).strip()
            assert fresh==digest(saved)
            assert o.session.resources()['peak_rss_bytes']<256*1024*1024
            assert candidate==digest(implementation()),'Candidate changed during rehearsal'
            result=dict(classification='CONTROL ONLY: initial retained r4 catalog volume with two labeled synthetic game substitutions; later small synthetic US game refreshes, repeated retained Kalshi volume, synthetic books and aggregate. Does not prove directed selectors.',
                implementation_sha256=digest(implementation()),spec_sha256=digest(configuration()),duration=180,
                ordinary_start_stop=True,stop_reason=o.session.reason,books=books,native_requests=sum(r['type']=='prediction_discovery_http' for r in rows),discovery_generations=o.session.discovery.published_generation,
                aggregate_requests=len(f.odds_calls),aggregate_cycles=f.rounds,simulated_credits=o.session.aggregate.budget.credits,
                required_cells=len(saved['aggregate_coverage']),details=len(details),exact_reopening=True,fresh_process_reopening=True,cleanup=True,
                resources=o.session.resources(),provider_requests=0,credential_access=0,actual_credits=0)
            (out/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(path=str(out),**result)),flush=True)
        finally:await f.close()

if __name__=='__main__':asyncio.run(main())
