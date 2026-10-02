"""Retained 180s r2 rehearsal; production destinations never opened."""
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from tests.test_acquisition_r2 import Fixture,PACKAGE,configuration
from app.collection.native_approval import validate_approval,digest,implementation
from app.collection.venue_access import ENDPOINTS
from app.collection.transport_session import reopen
from app.dashboard.session_history import load,project_rows
from app.dashboard.session_projection import SessionProjection

async def main():
    out=PACKAGE/('SIMULATED-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'));out.mkdir()
    f=Fixture()
    with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
        o=await f.boot(out)
        # Exact production approval validation and durable consumption, all offline.
        # This synthetic approval is confined to this explicitly SIMULATED output.
        real=configuration();approval=out/'SIMULATED-approval.json'
        approval.write_text(json.dumps(dict(approved=True,spec_sha256=digest(real),implementation_sha256=digest(implementation()),output=str(o.pilot_output.resolve()),classification='SIMULATED test authorization; never live authority')))
        validate_approval(real,{**ENDPOINTS,'aggregate':'https://api.the-odds-api.com'},approval,o.pilot_output,consume=True)
        try:
            await f.start(duration=180,fast=False);await f.native_images()
            await f.wait(lambda:bool(o.session.projection.aggregates))
            feed=await (await f.client.get('/api/dashboard?view=feed')).json();details=[]
            for row in feed['comparisons'][:4]:
                q=urlencode(dict(session=row['session'],hash=row['hash'],cutoff=row['cutoff']))
                details.append((q,await (await f.client.get('/api/calculate?'+q)).json()))
            await o.finalizer;assert o.error is None,o.error
            await f.stop_route()
            rows=reopen(o.session.journal.path)['rows'];p=SessionProjection()
            for row in rows:
                p.apply(row);snapshot=p.snapshot(mode='saved');assert snapshot==project_rows(rows,snapshot['durable_cursor'])
            for q,d in details:assert d==await (await f.client.get('/api/calculate?'+q)).json()
            saved=load(o.session.output);assert len(saved['aggregate_coverage'])==63
            sid=o.session.sid
            a=await (await f.client.get('/api/opportunity-history?capture='+sid)).json()
            b=await (await f.client.get('/api/opportunity-history?capture='+sid+'&download=true')).json();assert a==b
            (out/'download.json').write_text(json.dumps(b))
            dispatch=[r for r in rows if r['type']=='aggregate_dispatch'];receipts=[r for r in rows if r['type']=='aggregate_http']
            paid=[r for r in receipts if r['request']['path'].endswith('/odds')]
            independent_sum=sum(len(set(r['request']['params']['markets'].split(','))) for r in paid)
            charged=sum(int(dict(r['headers'])['x-requests-last']) for r in receipts)
            assert len(dispatch)==len(receipts)==37 and len(paid)==18
            assert independent_sum==charged==o.session.aggregate.budget.credits==135
            assert all(v==3 for v in f.rounds.values()) and len(f.rounds)==6
            assert receipts[0]['request']['path']=='/v4/sports'
            assert sum(r['type']=='aggregate_quota_baseline' for r in rows)==1
            assert o.session.cleanup_complete
            before=len(f.odds_calls);await asyncio.sleep(.05);assert before==len(f.odds_calls)
            try:validate_approval(real,{**ENDPOINTS,'aggregate':'https://api.the-odds-api.com'},approval,o.pilot_output)
            except ValueError:pass
            else:raise AssertionError('Consumed attempt reused')
            result=dict(evidence_class='SIMULATED isolated ordinary flow; not live evidence',session=sid,
                exact_immutable_spec_sha256=digest(real),implementation_sha256=digest(implementation()),
                startup_requests=1,free_event_discoveries=18,paid_requests=18,total_requests=37,
                independent_request_market_sum=independent_sum,header_charge_sum=charged,reserved_credits=135,
                cycles=f.rounds,cutoffs=len(rows),exact_details=len(details),coverage_cells=63,
                ordinary_start_stop=True,automatic_deadline=True,consumed_approval_rejected=True,quota_obtained_in_startup=True,
                exact_reopening=True,exact_history_download=True,cleanup=True,actual_credits_spent=0,credential_access=0,
                live_api_requests=0,substitutions=['numeric loopback endpoints','mock mode after offline production approval gate','fabricated native NFL catalog and six-sport aggregate observations; broader native bindings not qualified'])
            (out/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(path=str(out),**result)),flush=True)
        finally:await f.close()

if __name__=='__main__':asyncio.run(main())
