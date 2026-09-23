"""Isolated ordinary fixture session for the integrated B5 acceptance."""
import asyncio,json
from pathlib import Path
from aiohttp import web
from tests.b5_ncaab_resolution_preview import Session as BaseSession
from tests.b5_mlb_preview import owner as base_owner
from tests.test_b5_diamond_ice_resolution import fixture as game_fixture,rec
from tests.test_b5_periods import fixture as period_fixture
from tests.test_b5_futures import fixture as future_fixture
from app.collection.transport_session import ObservationJournal
from app.dashboard.multi_game_server import create_app


def rows_for(case):
    if case=='futures':return future_fixture(overlap=True)
    if case in ('MLB','NHL'):return game_fixture(case)[0]
    sport,period=case.split(':');return period_fixture(sport,period,'moneyline')

class Session(BaseSession):
    prefix='b5-independent-'
    case='MLB'
    async def start(self):
        self.journal=ObservationJournal(self.output/(self.sid+'.jsonl'));self.state='running';self.queue=asyncio.Queue()
        rows=rows_for(self.case)
        for row in rows:
            row['session_id']=self.sid
            if row['type']=='session_started':row['spec']=self.spec
            self.append(row)
        s=self.projection.snapshot();g=s['games'][0];e=rows[1]['inventory']['kalshi']['events'][0];self.target=s;self.game=g
        period=g['product_identity']['period'];changes={}
        if self.case=='futures':changes=dict(period='season',completion='official_championship_awarded',award_basis='declared_by_governing_body',winning_state=e['states'][0]['id'])
        elif period!='full_game':
            from app.normalization.score_periods import PERIODS
            start,end=PERIODS[e['competition']][period];changes=dict(period=period,score_scope=period+'_only',score_representation='official_segment_score',completion=period+'_definitively_completed',segment_start=start,segment_end=end,pitcher_conditions='action')
        a=rec(s,g,e,status='pending',minute=0,**changes);b=rec(s,g,e,'venue',minute=1,period=period)
        c=rec(s,g,e,minute=2,supersedes=[a['id']],**changes);d=rec(s,g,e,'venue',minute=3,supersedes=[b['id']],period=period,status='settled',payout=dict(kind='fraction',value='0',fee_treatment='unknown'))
        f=rec(s,g,e,minute=4,home_score=6,**changes)
        corrected=dict(changes)
        if self.case=='futures':corrected['winning_state']=e['states'][1]['id']
        z=rec(s,g,e,minute=5,supersedes=[c['id'],f['id']],home_score=4,**corrected)
        self.records=[a,b,c,d,f,z];(self.output/'prepared-resolution.json').write_text(json.dumps(self.records,indent=2));self.task=asyncio.create_task(self.produce())

if __name__=='__main__':
    import sys
    Session.case=sys.argv[2]
    web.run_app(create_app(owner=base_owner(Path(sys.argv[1]),session_factory=Session),sessions={}),host='127.0.0.1',port=8815,access_log=None)
