"""Isolated labeled resolution journal; all activity is local fixture ingestion."""
import asyncio,json
from pathlib import Path
from aiohttp import web
from tests.mlb_preview import Session as BaseSession,owner as base_owner
from tests.test_ncaab_resolution import fixture,rec
from app.collection.transport_session import ObservationJournal
from app.dashboard.multi_game_server import create_app


def sequence(s,g,e):
    a=rec(s,g,e,status='pending',minute=0)
    b=rec(s,g,e,'venue',status='pending',minute=1)
    c=rec(s,g,e,minute=2,home=53,supersedes=[a['id']])
    d=rec(s,g,e,'venue',minute=3,supersedes=[b['id']])
    f=rec(s,g,e,minute=4,home=57)
    corrected=rec(s,g,e,minute=5,home=48,supersedes=[c['id'],f['id']])
    return [a,b,c,d,f,corrected]


class Session(BaseSession):
    prefix='b5-ncaab-resolution-'
    period='first_half'
    async def start(self):
        self.journal=ObservationJournal(self.output/(self.sid+'.jsonl'));self.state='running';self.queue=asyncio.Queue()
        rows,_,_,e=fixture('moneyline',self.period)
        for row in rows:
            row['session_id']=self.sid
            if row['type']=='session_started':row['spec']=self.spec
            self.append(row)
        s=self.projection.snapshot();g=s['games'][0];self.target=s;self.game=g
        self.records=sequence(s,g,e)
        (self.output/'prepared-resolution.json').write_text(json.dumps(self.records,indent=2))
        self.task=asyncio.create_task(self.produce())
    def emit(self,source,value):
        if self.stop_event.is_set():return False
        self.append(dict(value,source=source,session_id=self.sid,observed_at=value['resolution']['received_at']))
        return True


def owner(root,period='first_half'):
    class PeriodSession(Session):pass
    PeriodSession.period=period
    return base_owner(root,session_factory=PeriodSession)
if __name__=='__main__':
    import sys
    web.run_app(create_app(owner=owner(Path(sys.argv[1]),sys.argv[2] if len(sys.argv)>2 else 'first_half'),sessions={}),host='127.0.0.1',port=8814,access_log=None)
