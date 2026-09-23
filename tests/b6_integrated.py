"""Finite, explicit offline B6 workload. No production launcher imports this file.

Four native fixture adapters plus explicitly annotated B5 synthetic projection
inputs share the ordinary collector/journal/queue, dashboard and calculation path.
The latter are NOT asserted to be native listing or wire qualification.
"""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

import httpx
from aiohttp import web, ClientSession
from aiohttp.test_utils import TestServer
from app.adapters.prophetx import Client, Credentials, ProphetXAdapter
from app.collection.continuous import ContinuousSession
from app.collection.native_product import REFERENCES
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
from app.dashboard import product_view, session_history
from app.dashboard.bounds import retained_bytes
from app.models.core import EvidenceKind
from app.reference.product import emit_references
from tests.segmented_collector_fixture import Fixture
from tests.b3_fixture import factory as novig_factory
from tests.test_b3_native import configuration as base_configuration
from tests.test_b4_reference import references

CASES=['NBA:full_game','NFL:first_half','NCAAF:first_half','NCAAB:first_half',
       'MLB:full_game','NHL:full_game','MLB:first_5','NHL:period_2',
       'NBA:league_champion','NBA:conference_champion']

def case_rows(case):
    sport,period=case.split(':')
    if period.endswith('champion'):
        from tests.test_b5_futures import fixture
        return fixture(category=period,overlap=True)
    if period=='first_half':
        import importlib
        return importlib.import_module('tests.test_b5_'+sport.lower()+'_first_half').fixture(family='total',line='20.5' if sport.endswith('F') or sport=='NFL' else '100.5')
    if period in ('first_5','period_2'):
        from tests.test_b5_periods import fixture
        return fixture(sport,period,'moneyline')
    if sport in ('MLB','NHL'):
        from tests.test_b5_diamond_ice_resolution import fixture
        return fixture(sport)[0]
    from tests.test_b5_score_lines import fixture
    return fixture(sport)

def configuration():
    value=base_configuration()
    # Fewer polls, not a raised request allowance. Discovery at 60/120 seconds.
    for c in value['native_sources'].values():
        if c['state']=='enabled':c['poll_seconds']=30
    value['native_sources']['prophetx']=dict(state='enabled',environment='sandbox',
        credential_reference=REFERENCES['prophetx']['sandbox'],tournament_ids=['999'],
        poll_seconds=30,event_cap=1,market_cap=2)
    return value

def digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

def calculations_at(snapshot):
    # Completion is package metadata, not a mathematical input: the same live
    # prefix becomes 'saved' only once its enclosing package is finalized.
    return {g['id']:{k:v for k,v in product_view.calculate(snapshot,g,{}).items()
                     if k!='state'} for g in snapshot['games']}

def save(path,value):
    Path(path).write_text(json.dumps(value,indent=2,default=str))

class NativeFixture(Fixture):
    async def rest(self,req):
        response=await super().rest(req);data=json.loads(response.text)
        if req.path=='/trade-api/v2/markets':
            for m in data['markets']:m.update(rules_primary='SYNTHETIC normal winner; begins within 48 hours; tie $0.50',rules_secondary='Synthetic test terms only')
        if req.path in ('/v1/markets','/v1/events'):
            markets=data.get('markets',[])+[m for e in data.get('events',[]) for m in e.get('markets',[])]
            for m in markets:m.update(description='SYNTHETIC normal winner; rescheduled to a date within two days; tie $0.50',feeCoefficient='0.06')
        return web.json_response(data)

    async def adapters(self,venue,config,observer):
        if venue=='novig':return await novig_factory(self)(venue,config,observer)
        assert venue=='prophetx'
        def handler(req):
            if req.url.path.endswith('/auth/login'):
                return httpx.Response(200,json={'data':{'access_token':'synthetic-access','refresh_token':'synthetic-refresh'}})
            if req.url.path.endswith('/mm/get_sport_events'):
                return httpx.Response(200,json={'data':{'sport_events':[dict(event_id=999,name='SYNTHETIC Detroit Lions vs Buffalo Bills',sport_name='American Football',tournament_name='NFL',scheduled=self.schedule,status='not_started',competitors=[dict(name='Detroit Lions'),dict(name='Buffalo Bills')])]}})
            if req.url.path.endswith('/v4/mm/get_multiple_markets'):
                selections=[[dict(outcome_id=1,strike_id='synthetic-det',name='Detroit Lions',price='110',quantity='100')],[dict(outcome_id=2,strike_id='synthetic-buf',name='Buffalo Bills',price='-120',quantity='100')]]
                return httpx.Response(200,json={'data':{'999':[dict(id=7,name='SYNTHETIC full-game winner',type='moneyline',sub_type='moneyline',status='active',selections=selections)]}})
            raise AssertionError('No external fixture route: '+req.url.path)
        class SyntheticClient(Client):
            async def request(self,*a,**kw):
                return replace(await super().request(*a,**kw),kind=EvidenceKind.SYNTHETIC)
        client=SyntheticClient(Credentials('sandbox','synthetic-key','synthetic-secret'),
            http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),request_budget=30,
            byte_budget=2_000_000,retries=0,observer=observer)
        return [ProphetXAdapter(client,tournament_ids=['999'])]

class Runtime:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.fixture=NativeFixture();self.case=CASES[0];self.samples=[];self.results=[]

    async def open(self,port=8816):
        f=self.fixture
        feeds=web.Application();feeds.router.add_get('/ws',f.ws);feeds.router.add_get('/{path:.*}',f.rest)
        f.server=TestServer(feeds);await f.server.start_server();url=str(f.server.make_url('/')).rstrip('/')
        f.endpoints={v:dict(rest=url,ws=url.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
        runtime=self
        class Session(ContinuousSession):
            native_adapter_factory=staticmethod(f.adapters)
            def emit(self,source,record):
                if record['type']=='coverage_inventory':
                    record=deepcopy(record)
                    for v,c in runtime.extra[1]['inventory'].items():
                        if v not in ('kalshi','polymarket_us'):continue
                        target=record['inventory'][v]
                        target['events']+=deepcopy(c['events']);target['markets']+=deepcopy(c['markets'])
                        target['selection']['ids']+=list(c['selection']['ids'])
                        # Keep subscription telemetry native-only. The B5 inputs
                        # are explicit reviewed projection fixtures, not wires.
                return super().emit(source,record)
            async def start(self):
                runtime.extra=case_rows(runtime.case)
                await super().start();original=self.journal.save
                def observed(row):
                    original(row);f.books+=row['type']=='prediction_book';f.changed.set()
                self.journal.save=observed
        self.owner=CoverageOwner(self.root/'legacy',pilot_output=self.root/'sessions',
            endpoints=f.endpoints,product_mode=True,spec_factory=configuration,session_factory=Session)
        f.owner=self.owner
        self.runner=web.AppRunner(create_app(owner=self.owner,sessions={}));await self.runner.setup()
        await web.TCPSite(self.runner,'127.0.0.1',port).start()
        self.url=f'http://127.0.0.1:{port}'
        self.http=ClientSession(headers={'Origin':self.url})

    async def request(self,path,body=None):
        async with (self.http.get(self.url+path) if body is None else self.http.post(self.url+path,json=body)) as response:
            value=await response.json()
            if response.status!=200:raise AssertionError((path,response.status,value))
            return value

    async def annotated_books(self,metadata=False):
        s=self.owner.session;at=datetime.now(timezone.utc).isoformat()
        for original in self.extra[2:]:
            if original['source'] not in ('kalshi','polymarket_us'):continue
            if original['type']=='source_health' and original['state']!='connected':continue
            if not metadata and original['type']!='prediction_book':continue
            row=deepcopy(original)
            # Preserve raw originals; date the newly generated synthetic receipt.
            if row['type']=='prediction_book':
                # B5's older transport-free fixtures rely on listing-state
                # fallback. Native-source sessions deliberately prohibit that.
                # Supply an explicitly active SYNTHETIC book instead; never
                # weaken the production unknown-state rule.
                row['book']['state']='active'
                row['book']['raw']['received_at']=at
                row['book']['raw']['exchange_at']=at
                for packet in row['packets']:
                    packet['normalized']['received_at']=at
            row['b6_input']='synthetic B5 reviewed projection fixture; not native wire'
            s.emit(row['source'],row)
        await s.queue.join()

    async def run_segment(self,index,duration=180):
        self.case=CASES[index%len(CASES)];start=time.monotonic()
        before=await self.request('/api/status');assert before['state']=='idle' or not self.owner.active()
        sid=(await self.request('/api/start',dict(duration=duration)))['session']
        s=self.owner.session;f=self.fixture
        await f.wait(lambda:len(f.active())==2 and s.discovery.generation>=1)
        await f.images();await self.annotated_books(metadata=True)
        snap=self.owner.current_snapshot();assert len(snap['sources'])==4
        g=next(g for g in snap['games'] if g['product_identity']['competition']=='NFL' and g['product_identity']['period']=='full_game')
        emit_references(s,references(g,datetime.now(timezone.utc).isoformat()));await s.queue.join()
        expected_ids=sorted(g['id'] for g in self.owner.current_snapshot()['games'])
        assert any(g.get('score_reviews') for g in self.owner.current_snapshot()['games']),(self.case,'B5 case missing')
        reviewed=[g for g in self.owner.current_snapshot()['games'] if g.get('score_reviews')]
        assert any(c['profit'] is not None for g in reviewed for c in product_view.calculate(self.owner.current_snapshot(),g,{})['candidates']),'No B5 calculation supported'
        assert len(expected_ids)>=2,(self.case,expected_ids)
        tick=0;faults=[];last_sample=0
        while time.monotonic()-start < duration-.7 and not s.task.done():
            elapsed=time.monotonic()-start
            # Quiet Kalshi window and a separate dropped PMUS connection; other
            # sources continue. Reconnected Kalshi/US streams require new images.
            for c in list(f.active()):
                if index==0 and 35<=elapsed<75 and c['venue']=='kalshi':continue
                if index==1 and 40<=elapsed<45 and c['venue']=='polymarket_us' and not faults:
                    await c['socket'].close();faults.append(dict(kind='disconnect',at=elapsed));continue
                await f.send(c)
            await self.annotated_books()
            if tick==10:
                emit_references(s,references(g,datetime.now(timezone.utc).isoformat()));await s.queue.join()
            snap=self.owner.current_snapshot()
            ids=sorted(g['id'] for g in snap['games']);assert ids==expected_ids,(self.case,'unstable groups',ids,expected_ids)
            board=await self.request('/api/dashboard')
            assert len({r['id'] for r in board['rows']})==len(board['rows'])
            self.samples.append(dict(segment=index,case=self.case,elapsed=elapsed,
                resources=s.resources(),state_bytes=retained_bytes(s.projection.__dict__),
                catalog=len(snap['market_catalog']),groups=len(snap['games']),rows=len(board['rows']),
                sources=snap['sources'],coverage=s.status_coverage(),references=len(snap['references'])))
            save(self.root/'progress.json',dict(segment=index,elapsed=elapsed,case=self.case,samples=len(self.samples)))
            tick+=1
            await asyncio.sleep(min(5,max(0,duration-.7-(time.monotonic()-start))))
        assert not s.task.done(),('early termination',s.reason)
        frozen=self.owner.current_snapshot();cutoff=frozen['durable_cursor'];frozen=self.owner.cutoffs[cutoff]
        calculations=calculations_at(frozen)
        stop=time.monotonic();await self.request('/api/stop',{});await self.owner.finalizer
        assert self.owner.error is None,self.owner.error
        assert s.cleanup_complete and not f.active()
        reopened=session_history.load(s.output,cutoff)
        for k in ('games','points','sources','references','market_catalog'):assert frozen[k]==reopened[k],k
        recalculated=calculations_at(reopened)
        if calculations!=recalculated:
            save(s.output/'calculation-mismatch.json',dict(before=calculations,after=recalculated))
        assert calculations==recalculated
        oracle=dict(session=sid,cutoff=cutoff,snapshot_fields={k:reopened[k] for k in ('games','points','sources','references','market_catalog')},calculations=calculations)
        save(s.output/'b6-oracle.json',oracle)
        result=dict(index=index,case=self.case,session=sid,cutoff=cutoff,seconds=time.monotonic()-start,
            stop_finalize_seconds=time.monotonic()-stop,collection_seconds=s.collection_seconds,
            cleanup_complete=s.cleanup_complete,reason=s.reason,resources=s.resources(),accounting=s.accounting(),
            folder_bytes=sum(p.stat().st_size for p in s.output.iterdir() if p.is_file()),
            snapshot_sha256=digest(oracle['snapshot_fields']),calculation_sha256=digest(calculations),faults=faults)
        self.results.append(result);save(self.root/'segments.json',self.results);save(self.root/'measurements.json',self.samples)
        print(json.dumps({k:result[k] for k in ('index','case','seconds','reason','stop_finalize_seconds')}),flush=True)
        # Clear only disposable in-memory fixture connection bookkeeping.
        f.connections=[]

    async def close(self):
        await self.http.close();await self.runner.cleanup();await self.fixture.close()

async def main():
    root=Path(sys.argv[1]);duration=int(sys.argv[2]) if len(sys.argv)>2 else 180
    count=int(sys.argv[3]) if len(sys.argv)>3 else 10
    assert 1<=duration<=180 and 1<=count<=10
    runtime=Runtime(root)
    with patch('app.collection.native_product.load_native_secret',side_effect=AssertionError('B6 credential access forbidden')):
        await runtime.open()
        try:
            for i in range(count):await runtime.run_segment(i,duration)
            # A fresh owner/process replay is a separate command after this exit.
        finally:await runtime.close()

if __name__=='__main__':asyncio.run(main())
