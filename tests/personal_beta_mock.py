"""Local-only retained-observation producer for the bounded beta UI test.
No transport or credential construction. Captures are explicitly mock, in a separate folder.
"""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from app.collection.transport_session import ObservationJournal,reopen
from app.dashboard.e6_live import save_json
from app.dashboard.multi_game import configuration,MultiOwner

BASE=Path('evidence/multi-game/sessions/5c9b7dca-a813-4d77-80f5-0691d06068eb')
from app.collection.native_replay import verify_native_saved

def verify_local_replay(saved):
    # Replayed source records retain their original observation provenance.
    original=deepcopy(saved);original['rows'][0]['spec']['mode']='real'
    return verify_native_saved(original)

class LocalSession:
    def __init__(self,spec,output,endpoints):
        self.sid=str(uuid4());self.spec=deepcopy(spec);self.spec['mode']='mock';self.output=output
        self.state='idle';self.journal=None;self.cleanup_complete=False;self.stop_event=asyncio.Event();self.reason=None
    async def start(self):
        self.journal=ObservationJournal(self.output/'local.jsonl');self.state='running'
        self.journal.save(dict(type='session_started',spec=self.spec,observed_at=datetime.now(timezone.utc).isoformat(),ingress_id='local-start'))
        self.task=asyncio.create_task(self.produce())
    def request_stop(self,reason):self.reason=reason;self.stop_event.set()
    async def produce(self):
        try:
            await asyncio.wait_for(self.stop_event.wait(),timeout=.8)
        except TimeoutError:pass
        saved=reopen(BASE/'observations.jsonl');selection=deepcopy(next(r for r in saved['rows'] if r['type']=='multi_game_selection'))
        selection['games']=selection['games'][:self.max_games];selection['coverage']['selected']=len(selection['games'])
        self.discovery=SimpleNamespace(coverage=selection['coverage'])
        save_json(self.output/'selection.json',dict(games=selection['games'],coverage=selection['coverage']))
        self.journal.save(selection)
        for r in saved['rows'][1:-1]:
            if r['type']!='multi_game_selection':self.journal.save(r)
        try:await asyncio.wait_for(self.stop_event.wait(),timeout=self.spec['duration'])
        except TimeoutError:self.reason='duration_or_kickoff_cutoff'
        self.journal.save(dict(type='session_finished',observed_at=datetime.now(timezone.utc).isoformat(),reason=self.reason,ingress_id='local-finished'))
        self.journal.close();self.cleanup_complete=True;self.state='stopped'

def owner(output):return MultiOwner(output,spec_factory=configuration,personal_beta=True,session_factory=LocalSession)

if __name__=='__main__':
    from aiohttp import web
    from unittest.mock import patch
    from app.dashboard.multi_game_server import create_app
    out=Path('evidence/personal-beta/local-sessions');out.mkdir(exist_ok=True)
    with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credentials in local test')),patch('app.collection.native_replay.verify_native_saved',verify_local_replay):
        web.run_app(create_app(owner=owner(out)),host='127.0.0.1',port=8784,access_log=None)
