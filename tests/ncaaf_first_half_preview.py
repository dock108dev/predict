"""Isolated labeled H1 fixture producer through the ordinary product lifecycle."""
import asyncio,json
from pathlib import Path
from datetime import datetime,timezone
from aiohttp import web
from tests.mlb_preview import Session as BaseSession,owner as base_owner
from tests.test_ncaaf_first_half import fixture,reference
from tests.test_ncaaf_lines import fixture as full_fixture,reference as full_reference
from tests.test_score_lines import reseal
from app.collection.transport_session import ObservationJournal
from app.dashboard.multi_game_server import create_app


def combined_fixture():
    base=None
    for family,line,period in [('moneyline',None,'first_half'),('spread','-3','first_half'),('total','20.5','first_half'),('spread','-3','full_game'),('moneyline',None,'unsupported')]:
        rows=full_fixture() if period=='full_game' else fixture(family=family,line=line)
        # Different native market IDs on the same explicitly identified game.
        text=json.dumps(rows)
        ids={c['markets'][0]['id'] for c in rows[1]['inventory'].values()}
        for old in sorted(ids,key=len,reverse=True):text=text.replace(old,old+'-'+period+'-'+family)
        rows=json.loads(text)
        if period=='unsupported':
            for c in rows[1]['inventory'].values():c['markets'][0]['score_review']['descriptor']['winner_structure']='three_way'
        for source in rows[1]['inventory']:reseal(rows,source)
        if base is None:base=rows;continue
        for source,c in rows[1]['inventory'].items():
            base[1]['inventory'][source]['markets']+=c['markets'];base[1]['inventory'][source]['selection']['ids']+=c['selection']['ids']
        base+=rows[2:]
    gap=fixture(home='AAMU',away='SDAKST')
    text=json.dumps(gap).replace('SYNTHETIC-NCAAF-game-1','SYNTHETIC-NCAAF-FCS-gap')
    ids={v['id'] for c in gap[1]['inventory'].values() for kind in ['events','markets'] for v in c[kind]}
    for old in sorted(ids,key=len,reverse=True):text=text.replace(old,old+'-fcs-gap')
    gap=json.loads(text)
    for source,c in gap[1]['inventory'].items():
        reseal(gap,source)
        for kind in ['events','markets']:base[1]['inventory'][source][kind]+=c[kind]
        base[1]['inventory'][source]['selection']['ids']+=c['selection']['ids']
    base+=gap[2:]
    return base


class Session(BaseSession):
    prefix='b5-ncaaf-first-half-'
    async def start(self):
        self.journal=ObservationJournal(self.output/(self.sid+'.jsonl'));self.state='running'
        now=datetime.now(timezone.utc).isoformat()
        for row in combined_fixture():
            row.update(session_id=self.sid,observed_at=now)
            if row['type']=='session_started':row['spec']=self.spec
            if row['type']=='prediction_book':row['book']['raw'].update(received_at=now,exchange_at=now)
            self.append(row)
        for g in self.projection.snapshot()['games']:
            r=(reference if g['product_identity']['period']=='first_half' else full_reference)(g,at=now)
            self.append(dict(type='product_reference',source='reference',session_id=self.sid,observed_at=now,reference=r))
        self.task=asyncio.create_task(self.produce())


def owner(root):return base_owner(root,session_factory=Session)
if __name__=='__main__':
    import sys
    web.run_app(create_app(owner=owner(Path(sys.argv[1])),sessions={}),host='127.0.0.1',port=8808,access_log=None)
