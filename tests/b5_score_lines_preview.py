"""Isolated SYNTHETIC spread/total producer; ordinary owner, UI, Stop and history."""
import asyncio
import json
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from aiohttp import web
from app.dashboard.multi_game_server import create_app
from app.collection.transport_session import ObservationJournal
from tests.b5_mlb_preview import Session as BaseSession,owner as base_owner
from tests.test_b5_score_lines import fixture,reference


def combined_fixture():
    nba=fixture();college=fixture('NCAAB','total','150.5')
    text=json.dumps(college)
    replacements={v[k]:v[k]+'-college' for c in college[1]['inventory'].values() for kind,k in [('events','id'),('markets','id')] for v in c[kind]}
    for old,new in sorted(replacements.items(),key=lambda x:-len(x[0])):text=text.replace(old,new)
    college=json.loads(text)
    # Re-hash the deliberately renamed SYNTHETIC receipts.
    from tests.test_b5_score_lines import reseal
    for source in college[1]['inventory']:reseal(college,source)
    for source,c in college[1]['inventory'].items():
        dest=nba[1]['inventory'][source]
        for k in ('events','markets'):dest[k]+=c[k]
        dest['selection']['ids']+=c['selection']['ids']
    nba+=college[2:]
    return nba


class Session(BaseSession):
    prefix='b5-score-lines-'
    async def start(self):
        self.journal=ObservationJournal(self.output/(self.sid+'.jsonl'));self.state='running'
        rows=combined_fixture();now=datetime.now(timezone.utc).isoformat()
        for row in rows:
            row.update(session_id=self.sid,observed_at=now)
            if row['type']=='session_started':row['spec']=self.spec
            if row['type']=='prediction_book':
                row['book']['raw'].update(received_at=now,exchange_at=now)
            self.append(row)
        for g in self.projection.snapshot()['games']:
            # Model probabilities are explicitly synthetic and retain exact identity.
            r=reference(g,at=now)
            self.append(dict(type='product_reference',source='reference',session_id=self.sid,observed_at=now,reference=r))
        self.task=asyncio.create_task(self.produce())


def owner(root):return base_owner(root,session_factory=Session)
if __name__=='__main__':
    import sys
    web.run_app(create_app(owner=owner(Path(sys.argv[1])),sessions={}),host='127.0.0.1',port=8802,access_log=None)
