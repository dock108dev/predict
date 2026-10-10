"""Fixed disposable six-sport projection; same-ID lineage and coverage oracle."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import resource
import sys
import tempfile
import unittest
from app.collection.current_policy import DEFAULT
from app.collection.current_service import CurrentService
from app.collection.current_sink import LatestStateSink
from app.collection.local_ownership import LocalOwnership
from app.comparison.coverage import SPORTS, current_rows, aggregate_observation
from app.dashboard.current_state import CurrentStore
from app.reference.product import SPORT_KEYS
from tests.test_comparison_event_links import body, EVENT


async def workload():
    started=datetime.now(timezone.utc)
    source=(started-timedelta(seconds=1)).isoformat()
    with tempfile.TemporaryDirectory(prefix='predict-data-authored-') as d:
        root=Path(d)
        config=dict(DEFAULT,enabled=False,aggregate_enabled=False,aggregate_sports=list(SPORTS))
        service=CurrentService(config=config,directory=root/'state',ownership=LocalOwnership(root/'ownership'))
        store=CurrentStore(service);service.store=store
        service.sink=LatestStateSink(store,service.initial_state());service.dispatch=True
        for v in ('novig','prophetx'):
            service.states[v]=dict(state='budget_delayed',reason_code='authored',reason='Authored comparison input',next_due_at=None)
        before=None;largest=0;revisions={}
        try:
            for cycle in range(4):
                for sport_index,sport in enumerate(SPORTS):
                    payload=json.loads(body())
                    event=payload[0];event['sport_key']=SPORT_KEYS[sport]
                    event['id']=EVENT if sport=='NFL' else 'authored:'+sport+':one'
                    event['commence_time']='2026-10-09T00:15:00Z' if cycle==0 else '2026-10-09T00:18:00Z'
                    # Unresolved provider slots still remain visible for other sports.
                    if sport!='NFL':event.update(home_team='CONTROLLED '+sport+' HOME',away_team='CONTROLLED '+sport+' AWAY')
                    base=event['bookmakers'][0];base['last_update']=source
                    for market in base['markets']:
                        if sport!='NFL':
                            market['outcomes'][0]['name']=event['home_team'];market['outcomes'][1]['name']=event['away_team']
                    event['bookmakers']=[dict(deepcopy(base),key=v) for v in ('novig','prophetx','pinnacle')]
                    encoded=json.dumps(payload).encode()
                    received=(started+timedelta(milliseconds=cycle*6+sport_index)).isoformat()
                    service.sink.commit(dict(type='current_aggregate',sport=sport,body=encoded,received_at=received),service.states)
                    aggregate_observation(service.coverage,encoded,sport,received)
                snapshot=store.snapshot();index=store.index(snapshot)
                largest=max(largest,len(json.dumps(snapshot).encode()))
                nfl={q['quote']['id']:q for q in index.values() if q['event']['league']=='NFL'}
                if before is None:before=deepcopy(nfl)
                else:
                    if set(nfl)!=set(before):raise AssertionError('Schedule split current quote lineage')
                    for id_,row in nfl.items():
                        if row['quote']['times']['source_at']!=source:raise AssertionError('Receipt renewed source clock')
                        if row['quote']['revision']<before[id_]['quote']['revision']:raise AssertionError('Revision regressed')
                revisions.update({q['quote']['id']:q['quote']['revision'] for q in index.values()})
            coverage=service.coverage.snapshot(current_rows(index),sports=['NFL'])
            if coverage['totals']!=dict(admitted_quotes=24,displayed_quotes=4,filtered_quotes=20):raise AssertionError(coverage['totals'])
            # Successful empty catalog retires old NCAAB rows without touching NHL.
            received=(started+timedelta(milliseconds=25)).isoformat()
            service.sink.commit(dict(type='current_aggregate',sport='NCAAB',body=b'[]',received_at=received),service.states)
            aggregate_observation(service.coverage,b'[]','NCAAB',received)
            final=store.index(store.snapshot())
            if len(final)!=20 or any(r['event']['league']=='NCAAB' for r in final.values()):raise AssertionError('Empty query failed retirement')
            if sum(r['event']['league']=='NHL' for r in final.values())!=4:raise AssertionError('Unrelated healthy inventory erased')
            peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
            if peak>768*1024*1024:raise AssertionError('Existing 768 MiB ceiling exceeded')
            if store.subscribers or store.leases:raise AssertionError('Unexpected retained stream/review ownership')
            return dict(version='comparison-data-resource-1',evidence_class='authored offline disposable fixed workload',
                cycles=4,sports=6,aggregate_inputs=25,peak_quotes=24,final_quotes=20,largest_snapshot_bytes=largest,
                peak_rss_bytes=peak,rss_ceiling_bytes=768*1024*1024,source_clock_preserved=True,
                same_ID_time_shift_preserved=True,empty_query_retirement=True,provider_requests=0,
                elapsed_seconds=(datetime.now(timezone.utc)-started).total_seconds())
        finally:await store.close()


class DataIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_projection_lineage_empty_retirement_and_reconciled_views(self):
        result=await workload()
        self.assertEqual(result['peak_quotes'],24);self.assertEqual(result['final_quotes'],20)
        self.assertLess(result['largest_snapshot_bytes'],64*1024*1024)

if __name__=='__main__':
    print(json.dumps(asyncio.run(workload()),sort_keys=True))
