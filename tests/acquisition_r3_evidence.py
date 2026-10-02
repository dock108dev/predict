"""Exact-duration offline r3 lifecycle; simulated transports and no credentials."""
import asyncio
from datetime import datetime,timezone
import json
from unittest.mock import patch
from tests.test_acquisition_r3 import Fixture,configuration,PACKAGE
from app.collection.native_approval import digest,implementation,validate_approval
from app.collection.venue_access import ENDPOINTS
from app.collection.transport_session import reopen
from app.dashboard.session_history import load,project_rows

async def main():
    out=PACKAGE/('SIMULATED-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'));out.mkdir()
    f=Fixture('oversized')
    with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credential access')):
        o=await f.boot(out)
        spec=configuration();approval=out/'SIMULATED-approval.json'
        approval.write_text(json.dumps(dict(approved=True,implementation_sha256=digest(implementation()),spec_sha256=digest(spec),output=str(o.pilot_output.resolve()),classification='SIMULATED approval only')))
        validate_approval(spec,{**ENDPOINTS,'aggregate':'https://api.the-odds-api.com'},approval,o.pilot_output,consume=True)
        try:
            await f.start(duration=180,fast=False)
            await f.wait(lambda:'polymarket_us' in o.session.discovery.source_stops)
            await f.wait(lambda:len(f.active())==1);await f.images()
            await o.finalizer
            await f.stop_route()
            rows=reopen(o.session.journal.path)['rows'];saved=load(o.session.output)
            assert saved==project_rows(rows,saved['durable_cursor'])
            assert o.session.cleanup_complete and o.error is None
            assert len(saved['aggregate_coverage'])==63 and f.us_calls==1
            assert len(f.odds_calls)==37 and o.session.aggregate.budget.credits==135
            assert len(f.rounds)==6 and all(v==3 for v in f.rounds.values())
            assert any(r['type']=='prediction_book' and r['source']=='kalshi' for r in rows)
            assert not any(r['type']=='prediction_book' and r['source']=='polymarket_us' for r in rows)
            try:validate_approval(spec,{**ENDPOINTS,'aggregate':'https://api.the-odds-api.com'},approval,o.pilot_output)
            except ValueError:pass
            else:raise AssertionError('Consumed approval accepted')
            result=dict(evidence_class='SIMULATED offline transports; original truncated structure plus labeled excess, never a complete live catalog',
                implementation_sha256=digest(implementation()),spec_sha256=digest(spec),session=o.session.sid,
                ordinary_start_stop=True,duration_seconds=180,stop_reason=o.session.reason,exact_reopening=True,required_cells=63,
                aggregate_requests=37,reserved_simulated_credits=135,us_oversized_attempts=1,us_retries=0,
                healthy_kalshi_books=True,aggregate_cycles=f.rounds,cleanup=True,consumed_approval_rejected=True,
                actual_provider_requests=0,actual_credits_spent=0,credential_access=0)
            (out/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(path=str(out),**result)),flush=True)
        finally:await f.close()

if __name__=='__main__':asyncio.run(main())
