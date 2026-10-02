"""Exact bounded acquisition rehearsal and inert package checks; loopback only."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch
from aiohttp import web
from tests.test_source_session import UnifiedFixture
from app.collection.native_approval import digest, implementation
from app.collection.transport_session import reopen
from app.dashboard.session_history import load, project_rows
from app.reference.product import SPORT_KEYS

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'evidence/integrated-acquisition-20260929'

def check():
    attempt=json.loads((PACKAGE/'attempt.json').read_text())
    spec=json.loads((PACKAGE/'spec-template.json').read_text())
    reasons=['Exact live Start window and bootstrap identity bindings absent',
        'Evidence-backed complete native series/tag scope absent; synthetic keys are not authority',
        'Fresh quota counters, timestamp and current no-purchase plan evidence absent',
        'Dedicated credential availability unverified; preparation must not inspect credentials',
        'Exact completed spec authorization absent']
    assert not Path(attempt['output']).exists(), 'Proposed destination no longer unused'
    assert len(json.loads((PACKAGE/'scope-63-cells.json').read_text()))==63
    assert sum(len(s['markets']) for s in spec['source_session']['scopes'])==45
    return dict(executable_live=False,executable_offline=True,blockers=reasons,attempt=attempt,
                template_sha256=digest(spec),implementation_sha256=digest(implementation()))

class Fixture(UnifiedFixture):
    names={'NFL':('Buffalo Bills','Detroit Lions'),'NBA':('Boston Celtics','New York Knicks'),
        'MLB':('New York Yankees','Boston Red Sox'),'NHL':('Boston Bruins','New York Rangers'),
        'NCAAF':('Alabama Crimson Tide','Georgia Bulldogs'),'NCAAB':('Duke Blue Devils','North Carolina Tar Heels')}
    def __init__(self):super().__init__();self.sport='NFL';self.requested=[];self.rounds={};self.base_quota=1000
    def event(self):
        home,away=self.names[self.sport]
        return dict(id='simulated-'+self.sport,sport_key=SPORT_KEYS[self.sport],home_team=home,away_team=away,commence_time=self.schedule)
    def body(self):
        event=self.event();event['bookmakers']=[]
        for book in ('novig','prophetx','pinnacle','draftkings','betmgm'):
            markets=[]
            for key in self.requested:
                names=('Over','Under') if key.startswith('totals') else (event['home_team'],event['away_team'])
                outcomes=[dict(name=name,price=('2.1' if self.rounds[self.sport]==1 else '2.2') if book=='novig' else '1.9') for name in names]
                for i,o in enumerate(outcomes):
                    if key.startswith('spreads'):o['point']=-3.5 if i==0 else 3.5
                    if key.startswith('totals'):o['point']=45.5
                markets.append(dict(key=key,last_update=datetime.now(timezone.utc).isoformat(),outcomes=outcomes))
            event['bookmakers'].append(dict(key=book,markets=markets))
        return event
    async def rest(self,req):
        if not req.path.startswith('/v4/'):return await super().rest(req)
        self.sport=next(k for k,v in SPORT_KEYS.items() if '/'+v+'/' in req.path)
        odds=req.path.endswith('/odds')
        self.odds_calls.append((req.path,dict(req.query)))
        if odds:
            self.requested=req.query['markets'].split(',');self.used+=len(self.requested)
            self.rounds[self.sport]=self.rounds.get(self.sport,0)+1
        cost=len(self.requested) if odds else 0
        headers={'x-requests-used':str(self.used),'x-requests-remaining':str(self.base_quota-self.used),'x-requests-last':str(cost)}
        return web.json_response(self.body() if odds else [self.event()],headers=headers)

async def offline():
    out=PACKAGE/('SIMULATED-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    out.mkdir();f=Fixture()
    with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials')):
        o=await f.boot(out)
        template=json.loads((PACKAGE/'spec-template.json').read_text())
        cfg=deepcopy(template['source_session']);cfg['quota_observed_at']=datetime.now(timezone.utc).isoformat()
        cfg['http'].update(initial_used=0,initial_remaining=1000,plan_evidence='SIMULATED no actual account')
        original=o.spec_factory
        def factory():
            v=original();v['prediction']=template['prediction'];v['discovery_cadence']=60
            return v
        o.spec_factory=factory
        try:
            response=await f.client.post('/api/start',json=dict(duration=180,source_settings=cfg),headers=f.origin)
            assert response.status==200,await response.text()
            original_save=o.session.journal.save
            def observed(row):
                original_save(row);f.books+=row['type']=='prediction_book';f.changed.set()
            o.session.journal.save=observed
            await f.native_images()
            await f.wait(lambda:len(o.session.projection.aggregates)>0)
            # Exercise ordinary Details before stopping; cutoffs remain immutable.
            from urllib.parse import urlencode
            feed=await (await f.client.get('/api/dashboard?view=feed')).json()
            details=[]
            for row in feed['comparisons'][:4]:
                q=urlencode(dict(session=row['session'],hash=row['hash'],cutoff=row['cutoff']))
                details.append((q,await (await f.client.get('/api/calculate?'+q)).json()))
            await o.finalizer
            assert o.error is None,o.error
            # Ordinary Stop is idempotent after the automatic duration boundary.
            await f.stop_route()
            rows=reopen(o.session.journal.path)['rows']
            from app.dashboard.session_projection import SessionProjection
            p=SessionProjection()
            for row in rows:
                p.apply(row);snap=p.snapshot(mode='saved');assert snap==project_rows(rows,snap['durable_cursor'])
            for q,d in details:assert d==await (await f.client.get('/api/calculate?'+q)).json()
            saved=load(o.session.output);assert len(saved['aggregate_coverage'])==63
            sid=o.session.sid
            normal=await (await f.client.get('/api/opportunity-history?capture='+sid)).json()
            download=await (await f.client.get('/api/opportunity-history?capture='+sid+'&download=true')).json()
            assert normal==download
            (out/'download.json').write_text(json.dumps(download))
            assert len(f.odds_calls)==36,(len(f.odds_calls),f.rounds)
            assert all(n==3 for n in f.rounds.values()) and len(f.rounds)==6
            assert f.used==135
            assert o.session.aggregate.budget.credits==432
            calls=len(f.odds_calls);await asyncio.sleep(.05);assert len(f.odds_calls)==calls
            report=dict(evidence_class='SIMULATED exact 180s/60s six-sport request control flow',
                session=sid,requests=len(f.odds_calls),simulated_charged_credits=f.used,reserved_credits=432,
                rounds=f.rounds,cutoffs=len(rows),details=len(details),coverage_cells=63,cleanup=o.session.cleanup_complete,
                ordinary_start_stop=True,automatic_deadline=True,exact_reopening=True,exact_history_download=True,
                live_requests=0,credential_access=0,credits_spent=0,
                substitutions=['numeric loopback destinations','synthetic quota and observations','native fixture has NFL catalog only; other native sports unavailable, not qualified'])
            (out/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(dict(path=str(out),**report)),flush=True)
        finally:await f.close()

if __name__=='__main__':
    import sys
    if sys.argv[1:]==['--offline']:asyncio.run(offline())
    elif sys.argv[1:]==['--check']:print(json.dumps(check(),indent=2))
    else:raise SystemExit('Use --check or --offline; no live activation is implemented by this preparation runner')
