"""Offline representative r4 catalog-volume rehearsal with labeled supported fixtures."""
import asyncio
from datetime import datetime,timezone
import json
from unittest.mock import patch
from tests.test_r4_retained import Fixture,DERIVED
from app.collection.native_approval import digest,implementation
from app.collection.transport_session import reopen
from app.dashboard.session_history import load,project_rows

async def main():
    out=DERIVED/('SIMULATED-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'));out.mkdir()
    identity=digest(implementation());f=Fixture(True)
    with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
        o=await f.boot(out)
        try:
            await f.start(duration=60);await f.native_images()
            for c in list(f.active()):await f.send(c)
            await f.wait(lambda:o.session.aggregate.health=='completed')
            from urllib.parse import urlencode
            feed=await (await f.client.get('/api/dashboard?view=feed')).json();details=[]
            for r in feed['comparisons'][:4]:
                q=urlencode(dict(session=r['session'],hash=r['hash'],cutoff=r['cutoff']));details.append((q,await (await f.client.get('/api/calculate?'+q)).json()))
            await f.stop_route();assert o.error is None,o.error
            rs=reopen(o.session.journal.path)['rows'];saved=load(o.session.output)
            assert saved==project_rows(rs,saved['durable_cursor'])
            for q,d in details:assert d==await (await f.client.get('/api/calculate?'+q)).json()
            counts={v:sum(r['type']=='prediction_book' and r['source']==v for r in rs) for v in ('kalshi','polymarket_us')};assert all(n>=2 for n in counts.values())
            assert len(f.odds_calls)==37 and o.session.aggregate.budget.credits==135
            assert o.session.cleanup_complete and not o.session.discovery.source_stops
            assert identity==digest(implementation())
            result=dict(classification='OFFLINE: captured r4 catalog bytes, two explicitly synthetic supported event substitutions and synthetic market/books/aggregate. No real-source qualification.',implementation_sha256=identity,native_books=counts,aggregate_requests=37,aggregate_simulated_credits=135,aggregate_cycles=f.rounds,required_cells=len(saved['aggregate_coverage']),details=len(details),exact_reopening=True,ordinary_stop=True,cleanup=True,resources=o.session.resources(),actual_provider_requests=0,actual_credits=0,credential_access=0)
            (out/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(path=str(out),**result)),flush=True)
        finally:await f.close()
if __name__=='__main__':asyncio.run(main())
