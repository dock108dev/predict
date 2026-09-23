"""Transport-free NHL fixture in the ordinary UI. Inherits real owner Stop/cutoffs.

Only the synthetic producer/finalizer are substituted; no account or network client.
"""
import asyncio
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from copy import deepcopy
from aiohttp import web
from app.dashboard.coverage_owner import CoverageOwner,spec
from app.dashboard.multi_game_server import create_app
from app.dashboard.session_projection import SessionProjection
from app.dashboard.session_history import load
from app.dashboard.e6_live import save_json,digest
from app.collection.transport_session import ObservationJournal,reopen
from tests.test_nhl import fixture,reference

class Session:
    def __init__(self,spec,output,endpoints):
        self.sid='b5-nhl-'+str(uuid4());self.spec=spec;self.output=output;self.projection=SessionProjection()
        self.state='idle';self.stop_event=asyncio.Event();self.reason=None;self.cleanup_complete=False
        self.persistence_error=None;self.cleanup_errors=[];self.segmented_history=False;self.projection_error=None
    async def start(self):
        self.journal=ObservationJournal(self.output/(self.sid+'.jsonl'));self.state='running'
        rows=fixture();now=datetime.now(timezone.utc).isoformat()
        for row in rows:
            row.update(session_id=self.sid,observed_at=now)
            if row['type']=='session_started':row['spec']=self.spec
            if row['type']=='prediction_book':row['book']['raw']['received_at']=now
            self.append(row)
        g=next(g for g in self.projection.snapshot()['games'] if set(g['sources'])=={'kalshi','polymarket_us'})
        for ref in [reference(g,at=now),reference(g,kind='rating',at=now),reference(g,semantics=False,at=now)]:
            self.append(dict(type='product_reference',source='reference',session_id=self.sid,observed_at=now,reference=ref))
        self.task=asyncio.create_task(self.produce())
    def append(self,row):
        if self.stop_event.is_set():raise ValueError('Fixture stopped')
        self.journal.save(row);self.projection.apply(row)
    def request_stop(self,reason):self.reason=reason;self.stop_event.set()
    async def produce(self):
        try:await asyncio.wait_for(self.stop_event.wait(),self.spec['duration'])
        except TimeoutError:self.reason='duration_cutoff';self.stop_event.set()
        self.state='stopped';self.cleanup_complete=True
        # Freeze at the last synthetic receipt; never assert a fresh book at Stop.
        row=dict(type='session_finished',source='session',session_id=self.sid,observed_at=self.projection.last,reason=self.reason)
        self.journal.save(row);self.projection.apply(row);self.journal.close()

class Owner(CoverageOwner):
    async def finish(self,folder):
        try:
            await self.session.task;s=self.session
            save_json(folder/'report.json',dict(cleanup_complete=True,outcome=dict(status='complete'),session=s.sid,reason=s.reason,fixture=True))
            save_json(folder/'replay.json',dict(verified=True,fixture=True,note='Synthetic projection replay, not native venue qualification'))
            names=['run-spec.json','aggregate-limits.json','report.json','replay.json',s.sid+'.jsonl']
            save_json(folder/'manifest.json',dict(files={n:digest(folder/n) for n in names},journal_chain=reopen(s.journal.path)['sha256']))
            assert load(folder)['games']==s.projection.snapshot()['games']
        finally:self.release()

def owner(root):
    def config():
        value=spec();value.update(mode='mock',reference_enabled=False);return value
    endpoints={v:dict(rest='http://127.0.0.1:1',ws='ws://127.0.0.1:1/ws') for v in ('kalshi','polymarket_us')}
    return Owner(root/'legacy',pilot_output=root/'sessions',product_mode=True,spec_factory=config,session_factory=Session,endpoints=endpoints)

if __name__=='__main__':
    import sys
    web.run_app(create_app(owner=owner(Path(sys.argv[1])),sessions={}),host='127.0.0.1',port=8797,access_log=None)
