"""Compare retained native books before/after catalog role repair in one snapshot."""
import sys,json
from pathlib import Path
from collections import Counter
from types import SimpleNamespace
from datetime import timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,stamp
from app.collection.current_service import prepare_catalog
from app.collection.current_sink import normalized_records

def run(path):
    counts=Counter();advances=[];regressions=[]
    with connect() as db,db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        at=db.execute('select transaction_timestamp() at').fetchone()['at'];end=at+timedelta(hours=72)
        original={r['source']:dict(r['header'],markets=[]) for r in db.execute('select source,header from current_native_catalog_recovery')}
        for r in db.execute('select source,metadata from current_native_market_recovery order by source,market_id'):
            original[r['source']]['markets'].append(r['metadata'])
        from unittest.mock import patch
        with patch('app.collection.native_role_binding.attach_kalshi',return_value=set()):
            baseline=prepare_catalog(original,'kalshi',original['kalshi'],share_metadata=True)
        prepared=prepare_catalog(original,'kalshi',original['kalshi'],share_metadata=True)
        indices=[]
        for cats in (baseline,prepared):
            indices.append(({(v,e['id']):e for v,c in cats.items() for e in c['events']},
                {(v,m['event_id'],m['id']):m for v,c in cats.items() for m in c['markets']}))
        with db.cursor(name='role_replay') as cur:
            cur.itersize=64;cur.execute('select source,event_id,market_id,image from current_acquisition_image order by source,event_id,market_id')
            for r in cur:
                key=(r['source'],r['event_id'],r['market_id']);event=indices[0][0].get(key[:2])
                if not event or not event.get('scheduled_start') or not at<=stamp(event['scheduled_start'])<end:continue
                results=[]
                for events,markets in indices:
                    e=events.get(key[:2]);m=markets.get(key)
                    if not m:results.append(set());continue
                    projection=SimpleNamespace(inventory={key[0]:dict(events=[e],markets=[m])},books={key:dict(book=r['image'])},invalid=set())
                    rows,errors=normalized_records(projection,{key[0]:dict(state='available')},{},dated_annotations=False,clock=at.isoformat(),include_missing=True)
                    results.append({tuple(q['quote']['source'][k] for k in ('native_outcome_id','native_side')) for q in rows if not q.get('offer_missing')})
                before,after=results;counts[key[0]+':books']+=1;counts[key[0]+':before_offers']+=len(before);counts[key[0]+':after_offers']+=len(after)
                if after-before:advances.append(dict(source=key[0],event_id=key[1],market_id=key[2],new_sides=sorted(after-before)))
                if before-after:regressions.append(dict(source=key[0],event_id=key[1],market_id=key[2],lost_sides=sorted(before-after)))
    out=dict(at=at.isoformat(),counts=dict(counts),advanced_books=len(advances),regressed_books=len(regressions),advances=advances,regressions=regressions,provider_requests=0)
    Path(path).write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k not in ('advances','regressions')}))
if __name__=='__main__':run(sys.argv[1])
