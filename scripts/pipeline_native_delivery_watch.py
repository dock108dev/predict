"""Fixed native cohort observation with bounded incremental generation evidence.

Each sample validates all offered events in one MVCC snapshot. Observed lifetimes
are bounds; a valid commit marker alone is never a measured useful lifetime.
"""
import argparse
from collections import Counter,defaultdict
import gzip
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.pipeline_convergence_watch import snapshot
from scripts.pipeline_convergence_report import publication_current


def run(folder,cohort,seconds,interval,resume=False):
    folder=Path(folder);folder.mkdir(exist_ok=resume)
    original=json.loads(Path(cohort).read_text());ids={r['source_event_id'] for r in original['rows']}
    identity_file=folder/'historical-identities.json'
    if resume and set(json.loads(identity_file.read_text()))!=ids:raise ValueError('resume_cohort_changed')
    if not resume:identity_file.write_text(json.dumps(sorted(ids)))
    previous={};generations={};summaries=[];written=0;initial=None;start=time.monotonic();engine=runtime=None
    if resume:
        from datetime import datetime,timezone
        from app.storage.store import stamp
        from scripts.pipeline_delivery_report import load_samples
        prior=load_samples(folder)
        if not prior:raise ValueError('resume_samples_required')
        engine=prior[0]['engine'];runtime=prior[0]['runtime']['runtime_id']
        initial={r['id'] for r in prior[0]['events']};summaries=[s['summary'] for s in prior]
        generations={g['id']:g for s in prior for g in s['generations']}
        written=sum(p.stat().st_size for p in folder.glob('sample-*.json*'))
        start-=(datetime.now(timezone.utc)-stamp(prior[0]['at'])).total_seconds()
        del prior
    for i in range(len(summaries),601):
        tick=time.monotonic()
        v=snapshot(include_fields=True)
        if engine is None:engine=v['engine'];runtime=v['runtime']['runtime_id']
        if engine!=v['engine'] or runtime!=v['runtime']['runtime_id']:raise ValueError('qualification_identity_changed')
        current={r['id'] for r in v['events']}
        if initial is None:initial=current
        rows={r['id']:r for r in v.pop('field_rows')};counts=Counter();by_event=defaultdict(Counter);witnesses=[]
        have_previous=bool(previous)
        for cid in rows.keys()|previous.keys():
            row=rows.get(cid);old=previous.get(cid);eid=(row or old)['event_id']
            if row is None or old is None:
                category='added' if row else 'removed';diff={}
            else:
                diff={k:dict(before=old.get(k),after=value) for k,value in row.items() if old.get(k)!=value}
                if not diff:continue
                keys=set(diff)
                category=('price_or_depth' if keys & {'price_value','price_units','depth_revision'} else
                    'contract_or_rules' if keys & {'contract_dependency','metric_dependency'} else
                    'state_or_sync' if keys & {'state','sync'} else
                    'receipt_only' if keys<= {'received_at','book_received_at'} else 'source_clock_or_revision')
            counts[category]+=1;by_event[eid][category]+=1
            if len(witnesses)<32:witnesses.append(dict(id=cid,event_id=eid,classification=category,fields=diff))
        previous=rows
        fresh=[]
        for g in v['generations']:
            if g['engine']!=engine:continue
            if generations.get(g['id'])!=g:fresh.append(g);generations[g['id']]=g
        v['generations']=fresh
        valid=[p for p in v['publications'] if publication_current(p,v)]
        valid_ids={eid for p in valid for eid in p['publication_events'] or []}
        changed=[eid for eid,c in by_event.items() if have_previous and any(k!='receipt_only' for k in c)]
        summary=dict(sample=i,at=v['at'],elapsed_seconds=round(time.monotonic()-start,3),
            sample_seconds=round(time.monotonic()-tick,3),database_bytes=v.pop('database_bytes'),
            runtime=v['runtime'],engine=engine,offered=len(current),initial=len(initial),
            retired_ids=sorted(initial-current),arrival_ids=sorted(current-initial),
            original_offered=sorted(ids&current),original_absent=sorted(ids-current),
            original_current=sorted(ids&valid_ids),current_events=len(current&valid_ids),
            changed_events=changed,field_comparison_available=have_previous,field_changes=dict(counts),event_changes={k:dict(c) for k,c in by_event.items()},reads=[])
        v.update(summary=summary,field_observation=dict(at=v['at'],changes=witnesses,limit=32))
        data=gzip.compress(json.dumps(v,default=str).encode(),compresslevel=1);written+=len(data)
        if written>256*1024*1024:raise ValueError('observer_256MiB_cap')
        (folder/f'sample-{i:03}.json.gz').write_bytes(data);summaries.append(summary)
        (folder/'summary.json').write_text(json.dumps(summaries,default=str))
        print(json.dumps(dict(sample=i,elapsed=summary['elapsed_seconds'],original_current=len(ids&valid_ids),
            offered=len(current),current=summary['current_events'],healthy=v['runtime']['healthy'],bytes=written)),flush=True)
        if time.monotonic()-start>=seconds:break
        time.sleep(max(.1,interval-(time.monotonic()-tick)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder');p.add_argument('--cohort',default='test-results/d02-native-delivery/original-68.json')
    p.add_argument('--seconds',type=int,default=1205);p.add_argument('--interval',type=float,default=5)
    p.add_argument('--resume',action='store_true',help='Append with the same runtime/engine; seconds is total elapsed duration')
    a=p.parse_args();run(a.folder,a.cohort,a.seconds,a.interval,a.resume)
