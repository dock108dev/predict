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
from tests.test_b5_mlb_lines import fixture,reference


def combined_fixture():
    nba=fixture();college=fixture('MLB','total','8.5')
    text=json.dumps(college)
    replacements={v[k]:v[k]+'-total' for c in college[1]['inventory'].values() for kind,k in [('events','id'),('markets','id')] for v in c[kind]}
    for old,new in sorted(replacements.items(),key=lambda x:-len(x[0])):text=text.replace(old,new)
    college=json.loads(text)
    # Re-hash the deliberately renamed SYNTHETIC receipts.
    from tests.test_b5_score_lines import reseal
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
    # An explicitly labeled unsupported pitcher condition remains visible.
    gap=fixture()
    text=json.dumps(gap).replace('SYNTHETIC-MLB-game-1','SYNTHETIC-MLB-listed-pitcher-gap')
    replacements={v[k]:v[k]+'-listed' for c in gap[1]['inventory'].values() for kind,k in [('events','id'),('markets','id')] for v in c[kind]}
    for old,new in sorted(replacements.items(),key=lambda x:-len(x[0])):text=text.replace(old,new)
    gap=json.loads(text)
    # A different date is a separate game, not a conflicting duplicate identity.
    from app.normalization.mlb_lines import event_key,EVENT_FIELDS
    for source,c in gap[1]['inventory'].items():
        e=c['events'][0];e.update(original_start='2026-10-05T17:00:00Z',scheduled_start='2026-10-05T17:00:00Z',title='SYNTHETIC MLB listed-pitcher unsupported example')
        r=c['markets'][0]['score_review'];r['event_binding']=event_key(e);r['descriptor']['pitcher_conditions']='listed_pitchers'
        meta=next(v['market'] for v in gap if v['type']=='market_selected' and v['source']==source)
        native=json.loads(meta['raw']['json_text']);native['SYNTHETIC_mlb_event']={k:e[k] for k in EVENT_FIELDS};meta['raw']['json_text']=json.dumps(native)
        reseal(gap,source)
        for k in ('events','markets'):nba[1]['inventory'][source][k]+=c[k]
        nba[1]['inventory'][source]['selection']['ids']+=c['selection']['ids']
    nba+=gap[2:]
    return nba


class Session(BaseSession):
    prefix='b5-mlb-lines-'
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
    web.run_app(create_app(owner=owner(Path(sys.argv[1])),sessions={}),host='127.0.0.1',port=8805,access_log=None)
