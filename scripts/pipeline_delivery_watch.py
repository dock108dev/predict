"""Bounded prospective live evidence; no provider dispatch or control changes.

Sixty-one samples at most, 256 MiB total. Field observations use their own short
SQL snapshot; publication validation uses the existing coherent snapshot helper.
Sampling gaps cannot be called exact source receipt-to-use latency.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect
from scripts.pipeline_convergence_watch import snapshot
from scripts.pipeline_convergence_report import publication_current


def fields():
    with connect() as db,db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        rows=db.execute('''SELECT c.id,c.event_id,o.price_value,o.price_units,o.source_at,o.received_at,
            c.contract_dependency,c.metric_dependency,o.revision,
            b.depth_revision,b.state,b.sync,b.received_at book_received_at
            FROM current_contract c JOIN current_offer o ON o.contract_id=c.id
            JOIN current_event e ON e.id=c.event_id LEFT JOIN current_native_book b
            ON b.venue=c.venue AND b.event_id=c.event_id AND b.native_market_id=c.native_market_id
            WHERE e.scheduled_start::timestamptz>=now() AND e.scheduled_start::timestamptz<now()+interval '72 hours' ''').fetchall()
        return dict(at=db.execute('SELECT transaction_timestamp() at').fetchone()['at'],
            database_bytes=db.execute('SELECT pg_database_size(current_database()) n').fetchone()['n'],rows={r['id']:r for r in rows})


def run(folder,seconds=1800,interval=30):
    folder=Path(folder);folder.mkdir(exist_ok=False)
    previous=None;start=time.monotonic();written=0;initial=None;arrivals=set();summaries=[]
    historical=json.loads(Path('test-results/d02-changing/historical-34.json').read_text())
    historical_ids={r['source_event_id'] for r in historical['rows']}
    (folder/'historical-identities.json').write_text(json.dumps(sorted(historical_ids)))
    for i in range(61):
        try:
            v=snapshot();f=fields();current={r['id'] for r in v['events']}
            if initial is None:initial=current
            arrivals.update(current-initial)
            valid=[p for p in v['publications'] if publication_current(p,v)]
            valid_events={e for p in valid for e in p['publication_events'] or []}
            changes=[];counts=Counter();changed_events=set()
            if previous:
                for cid,row in f['rows'].items():
                    old=previous['rows'].get(cid)
                    if old is None:counts['added']+=1;continue
                    diff={k:dict(before=old.get(k),after=value) for k,value in row.items() if old.get(k)!=value}
                    if not diff:continue
                    kind='receipt_only' if set(diff)<={'received_at','book_received_at'} else 'dependency_change'
                    counts[kind]+=1
                    if kind=='dependency_change':changed_events.add(row['event_id'])
                    if len(changes)<32:changes.append(dict(id=cid,event_id=row['event_id'],classification=kind,fields=diff))
                counts['removed']=len(previous['rows'].keys()-f['rows'].keys())
            reads=[]
            if valid:
                from urllib.parse import urlencode
                game=valid[i%len(valid)]['game_key'];t=time.monotonic()
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8783/api/boards/ev?'+urlencode(dict(game=game,filter='all')),timeout=15) as response:
                        body=response.read(2*1024*1024)
                        reads.append(dict(game_key=game,status=response.status,read_at=time.time(),seconds=time.monotonic()-t,bytes=len(body)))
                except Exception as exc:reads.append(dict(game_key=game,error=type(exc).__name__,seconds=time.monotonic()-t))
            pending=[a for a in v['attempts'] if a['branch']=='metrics' and a['disposition']!='passed' and a['event_id'] in current]
            summary=dict(sample=i,at=v['at'],elapsed_seconds=round(time.monotonic()-start,2),database_bytes=f['database_bytes'],
                runtime=v['runtime'],engine=v['engine'],offered=len(current),initial=len(initial),retired_ids=sorted(initial-current),
                arrival_ids=sorted(arrivals),historical_still_offered=sorted(current&historical_ids),historical_retired=sorted(historical_ids-current),
                current_events=len(current&valid_events),historical_current=sorted(historical_ids&valid_events),
                changed_events=sorted(changed_events),field_changes=dict(counts),pending=len(pending),
                oldest_pending=min((a['first_attempt'] for a in pending),default=None),
                generations=dict(Counter(g['disposition'] for g in v['generations'])),reads=reads)
            v.update(summary=summary,field_observation=dict(at=f['at'],changes=changes,limit=32))
            data=json.dumps(v,default=str).encode()
            if written+len(data)>256*1024*1024:raise ValueError('observer_256MiB_cap')
            (folder/f'sample-{i:03}.json').write_bytes(data);written+=len(data)
            summaries.append(summary);(folder/'summary.json').write_text(json.dumps(summaries,indent=2,default=str))
            print(json.dumps(summary,default=str),flush=True);previous=f
        except Exception as exc:
            print(json.dumps(dict(sample_error=type(exc).__name__,at=time.time())),flush=True)
            if isinstance(exc,ValueError):break
        if time.monotonic()-start>=seconds:break
        time.sleep(interval)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder');p.add_argument('--seconds',type=int,default=1800)
    a=p.parse_args();run(a.folder,a.seconds)
