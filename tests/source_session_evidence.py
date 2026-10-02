"""Retain an ordinary-app loop on isolated mock transports. No real collection."""
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from tests.test_source_session import UnifiedFixture
from app.dashboard.session_history import load,project_rows
from app.collection.transport_session import reopen

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/unified-session-20260929'

async def main():
    destination=OUT/('SIMULATED-'+datetime.now(timezone.utc).strftime('%H%M%S%f'))
    destination.mkdir(parents=True)
    f=UnifiedFixture()
    with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credential access')):
        owner=await f.boot(destination)
        try:
            await f.start_route();await f.native_images()
            await f.wait(lambda:bool(owner.session.projection.aggregates))
            snapshot=owner.current_snapshot();c=f.client
            d=await (await c.get('/api/dashboard?view=feed')).json()
            (destination/'ordinary-dashboard.json').write_text(json.dumps(d,indent=2))
            details=[]
            for row in d['comparisons']:
                q=urlencode(dict(session=row['session'],hash=row['hash'],cutoff=row['cutoff']))
                details.append((q,await (await c.get('/api/calculate?'+q)).json()))
            await f.send(f.active()[0]);f.quote='2.4'
            await f.wait(lambda:any(r['original']['decimal_odds']=='2.4' for r in owner.session.projection.aggregates.values()))
            await f.stop_route();assert owner.error is None,owner.error
            for i,(query,detail) in enumerate(details):
                actual=await (await c.get('/api/calculate?'+query)).json()
                if detail!=actual:
                    (destination/('detail-difference-'+str(i)+'.json')).write_text(json.dumps(dict(expected=detail,actual=actual),indent=2))
                assert detail==actual
            sid=owner.session.sid
            history=await (await c.get('/api/opportunity-history?capture='+sid+'&download=true')).json()
            (destination/'downloaded-history.json').write_text(json.dumps(history,indent=2))
            rows=reopen(owner.session.journal.path)['rows']
            from app.dashboard.session_projection import SessionProjection
            p=SessionProjection();cutoffs=[]
            for row in rows:
                p.apply(row);snap=p.snapshot(mode='saved')
                assert snap==project_rows(rows,snap['durable_cursor'])
                cutoffs.append(snap['durable_cursor'])
            (destination/'cutoffs.json').write_text(json.dumps(cutoffs,indent=2))
            (destination/'scope-63-cells.json').write_text(json.dumps(load(owner.session.output)['aggregate_coverage'],indent=2))
            summary=dict(evidence_class='SIMULATED ordinary source-session sequence, numeric loopback transports only',
                session=sid,cutoffs=len(cutoffs),exact_details=len(details),aggregate_requests=len(f.odds_calls),
                real_requests=0,credential_access=0,credits_spent=0,cleanup_complete=owner.session.cleanup_complete,
                sources=owner.session.spec['source_session']['roles'],history_download_exact=history==await (await c.get('/api/opportunity-history?capture='+sid)).json())
            (destination/'verification.json').write_text(json.dumps(summary,indent=2));print(json.dumps(dict(path=str(destination),**summary)))
        finally:await f.close()

if __name__=='__main__':asyncio.run(main())
