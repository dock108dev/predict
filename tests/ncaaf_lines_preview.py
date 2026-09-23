"""Isolated SYNTHETIC spread/total producer; ordinary owner, UI, Stop and history."""
import asyncio
import json
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from aiohttp import web
from app.dashboard.multi_game_server import create_app
from app.collection.transport_session import ObservationJournal
from tests.mlb_preview import Session as BaseSession,owner as base_owner
from tests.test_ncaaf_lines import fixture,reference


def combined_fixture():
    nba=fixture();college=fixture('NCAAF','total','44.5')
    text=json.dumps(college)
    replacements={v[k]:v[k]+'-total' for c in college[1]['inventory'].values() for kind,k in [('events','id'),('markets','id')] for v in c[kind]}
    for old,new in sorted(replacements.items(),key=lambda x:-len(x[0])):text=text.replace(old,new)
    college=json.loads(text)
    # Re-hash the deliberately renamed SYNTHETIC receipts.
    from tests.test_score_lines import reseal
    for source in college[1]['inventory']:reseal(college,source)
    for source,c in college[1]['inventory'].items():
        dest=nba[1]['inventory'][source]
        # Keep one native event with two market IDs, as in an actual catalog.
        old=c['events'][0]['id'];new=dest['events'][0]['id']
        serialized=json.dumps(college).replace(old,new)
        college=json.loads(serialized)
    for source,c in college[1]['inventory'].items():
        reseal(college,source)
        dest=nba[1]['inventory'][source]
        dest['markets']+=c['markets'];dest['selection']['ids']+=c['selection']['ids']
    nba+=college[2:]
    fcs=fixture(home='AAMU',away='SDAKST')
    text=json.dumps(fcs).replace('SYNTHETIC-NCAAF-game-1','SYNTHETIC-NCAAF-FCS-gap')
    replacements={v[k]:v[k]+'-fcs' for c in fcs[1]['inventory'].values() for kind,k in [('events','id'),('markets','id')] for v in c[kind]}
    for old,new in sorted(replacements.items(),key=lambda x:-len(x[0])):text=text.replace(old,new)
    fcs=json.loads(text)
    for source,c in fcs[1]['inventory'].items():
        reseal(fcs,source)
        for k in ('events','markets'):nba[1]['inventory'][source][k]+=c[k]
        nba[1]['inventory'][source]['selection']['ids']+=c['selection']['ids']
    nba+=fcs[2:]
    return nba


class Session(BaseSession):
    prefix='b5-ncaaf-lines-'
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
    web.run_app(create_app(owner=owner(Path(sys.argv[1])),sessions={}),host='127.0.0.1',port=8804,access_log=None)
