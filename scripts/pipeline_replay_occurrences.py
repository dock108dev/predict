"""Fixed retained-cohort occurrence comparison; never writes or acquires."""
import sys,json,inspect,textwrap
from pathlib import Path
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect
from app.storage.board_capture import capture_batches
from app.storage.current_rows import CurrentRowStore
from app.storage.comparison_board import _records
import app.comparison.occurrence_matching as matching

def run(path):
    source=textwrap.dedent(inspect.getsource(matching.OccurrenceResolver.resolve))
    namespace=dict(vars(matching))
    exec(source.replace('metadata_local.add(k)','pass'),namespace)
    before_resolve=namespace['resolve'];counts=Counter();advances=[];regressions=[];examples=[]
    with connect() as db,db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        at=db.execute('select transaction_timestamp()::text at').fetchone()['at']
        for ids in capture_batches(db):
            records=_records(CurrentRowStore(db).capture(include_depth=False,event_ids=ids)['records'],at)
            if not records:continue
            # Restrict by the same ordinary upcoming schedule, including all lines.
            from datetime import timedelta
            from app.storage.store import stamp
            records=[r for r in records if stamp(r['event']['scheduled_start'])<stamp(at)+timedelta(hours=72)]
            if not records:continue
            before=before_resolve(matching.OccurrenceResolver(),records,clock=at)
            after=matching.OccurrenceResolver().resolve(records,clock=at)
            for a,b in zip(before,after):
                key=[b['quote']['source'][k] for k in ('provider','native_event_id','native_market_id','native_outcome_id','native_side')]
                old=a['quote']['occurrence_match'];new=b['quote']['occurrence_match']
                counts['records']+=1;counts['before_'+old['status']]+=1;counts['after_'+new['status']]+=1
                if old['status']!='matched' and new['status']=='matched':advances.append(key)
                if old['status']=='matched' and new['status']!='matched':regressions.append(key)
                if key[1]=='171837' and len(examples)<2:
                    examples.append(dict(identity=key,before=old,after=new,source_season=b['event']['season'],source_stage=b['event']['stage'],verified=b['verified']))
    value=dict(at=at,counts=dict(counts),advanced=len(advances),regressed=len(regressions),
        advanced_events=sorted({tuple(k[:2]) for k in advances}),advances=advances,regressions=regressions,examples=examples,provider_requests=0)
    Path(path).write_text(json.dumps(value,indent=2))
    print(json.dumps({k:v for k,v in value.items() if k not in ('advances','regressions','examples')}))
if __name__=='__main__':run(sys.argv[1])
