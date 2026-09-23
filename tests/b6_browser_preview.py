"""Idle-first ordinary UI backed by B6's isolated four-source runtime."""
import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import patch
from tests.b6_integrated import Runtime,save
from tests.test_b5_diamond_ice_resolution import rec
from tests.test_b4_reference import references
from app.reference.product import emit_references
from datetime import datetime,timezone

async def main():
    root=Path(sys.argv[1]);runtime=Runtime(root)
    runtime.case=sys.argv[2] if len(sys.argv)>2 else 'MLB:first_5'
    prepared=set()
    with patch('app.collection.native_product.load_native_secret',side_effect=AssertionError('offline fixture only')):
        await runtime.open(8817)
        print(runtime.url+' · idle, explicit browser Start',flush=True)
        try:
            while True:
                await asyncio.sleep(2)
                o=runtime.owner;s=o.session
                if not s or not o.active() or s.stop_event.is_set():continue
                if s.discovery.generation<1 or len(runtime.fixture.active())!=2:continue
                for c in list(runtime.fixture.active()):await runtime.fixture.send(c)
                await runtime.annotated_books(metadata=s.sid not in prepared)
                if s.sid in prepared:continue
                snapshot=o.current_snapshot()
                native=next(g for g in snapshot['games'] if g['product_identity']['competition']=='NFL' and g['product_identity']['period']=='full_game')
                emit_references(s,references(native,datetime.now(timezone.utc).isoformat()));await s.queue.join()
                snapshot=o.current_snapshot();g=next(g for g in snapshot['games'] if g.get('score_reviews'))
                e=runtime.extra[1]['inventory']['kalshi']['events'][0]
                period=g['product_identity']['period'];changes={}
                if period=='season':
                    changes=dict(period=period,completion='official_championship_awarded',award_basis='declared_by_governing_body',winning_state=e['states'][0]['id'])
                elif period!='full_game':
                    from app.normalization.score_periods import PERIODS
                    start,end=PERIODS[e['competition']][period]
                    changes=dict(period=period,score_scope=period+'_only',score_representation='official_segment_score',completion=period+'_definitively_completed',segment_start=start,segment_end=end,pitcher_conditions='action')
                a=rec(snapshot,g,e,status='pending',minute=0,**changes)
                b=rec(snapshot,g,e,'venue',minute=1,period=period)
                c=rec(snapshot,g,e,minute=2,supersedes=[a['id']],**changes)
                d=rec(snapshot,g,e,'venue',minute=3,supersedes=[b['id']],period=period,status='settled',payout=dict(kind='fraction',value='0',fee_treatment='unknown'))
                f=rec(snapshot,g,e,minute=4,home_score=6,**changes)
                z=rec(snapshot,g,e,minute=5,supersedes=[c['id'],f['id']],home_score=4,**changes)
                save(root/'prepared-resolution.json',[a,b,c,d,f,z])
                save(root/'prediction-target.json',dict(session=s.sid,game=g['id'],cutoff=snapshot['durable_cursor']))
                prepared.add(s.sid)
        finally:await runtime.close()

if __name__=='__main__':asyncio.run(main())
