"""Read-only retained-session reconciliation; write only this task's new evidence."""
import json
import subprocess
from types import ModuleType
from hashlib import sha256
from pathlib import Path
from app.dashboard import session_history
from app.dashboard.price_comparison import comparisons
from app.dashboard.opportunity_history import build_history, validate_watch, observations
from app.dashboard.decision_support import size_report

BASE=Path('evidence/commercial-engineering-20260929')
SID='b2391410-91d5-4c1a-aa19-cf5c94f6ae87'
FOLDER=Path('evidence/live-freshness-run-'+SID)/SID
OBS=Path('evidence/live-freshness-observation-'+SID)

def hashes(root):return {str(p):sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
def subset(old,new,path=''):
    if isinstance(old,dict):
        for k,v in old.items():subset(v,new[k],path+'/'+k)
    elif isinstance(old,list):
        assert len(old)==len(new),path
        for i,(a,b) in enumerate(zip(old,new)):subset(a,b,path+'/'+str(i))
    else:assert old==new,(path,old,new)

def main():
    before={**hashes(FOLDER),**hashes(OBS)}
    original=json.loads((OBS/'reopened.json').read_text())
    snap=session_history.load(FOLDER,original['durable_cursor'])
    current=comparisons(snap,{'quantity':'100'})
    baseline=ModuleType('entry_price_comparison')
    exec(subprocess.check_output(['git','show','HEAD:app/dashboard/price_comparison.py'],text=True),baseline.__dict__)
    entry=baseline.comparisons(snap,{'quantity':'100'})
    subset(entry,current)
    prior_link_corrections=[]
    def reconcile_links(old,expected):
        if isinstance(old,dict):
            for k,v in old.items():
                if k=='url' and v!=expected[k]:
                    prior_link_corrections.append(dict(old=v,entry_source=expected[k]))
                    old[k]=expected[k]
                else:reconcile_links(v,expected[k])
        elif isinstance(old,list):
            for a,b in zip(old,expected):reconcile_links(a,b)
    reconcile_links(original['comparisons'],entry)
    subset(original['comparisons'],current)
    assert len(current)==8
    assert all(r['settlement_status']=='INCOMPATIBLE' and r['net'] is None for r in current)
    assert all('two weeks' in ' '.join(r['decision']['settlement']) and '48 hours' in ' '.join(r['decision']['settlement']) for r in current)
    watches=[validate_watch(dict(name='Retained '+metric,metric=metric,threshold='.03' if metric=='raw_gap' else '0',quantity='100',filters={})) for metric in ('raw_gap','arb_return','ev')]
    report=build_history(FOLDER,watches)
    assert report['coverage']['complete'],report['coverage']
    assert not any(i['active'] for i in report['items'])
    assert not any(i['qualifying_observations'] for i in report['items'] if i['metric']!='raw_gap')
    # Rebuild once from disk: no sidecar/restart duplication, no later inputs.
    assert report==build_history(FOLDER,watches)
    checked=0
    for item in report['items']:
        point=item['last_observed_point']
        exact=session_history.load(FOLDER,point['cutoff'])
        w=next(w for w in watches if w['id']==item['watch'])
        row=next(o for o in observations(exact,w) if o['id']==item['id'])
        assert row['reasons']==item['reasons']
        checked+=1
    game=next(g for g in snap['games'] if g['id']==current[0]['game_id'])
    sized=size_report(snap,game,dict(sizes=['1','10','100','.5'],ceiling='100',scenario='cent'))
    assert all(c['profit'] is None for s in sized['sizes'] for c in s['candidates'])
    after={**hashes(FOLDER),**hashes(OBS)}
    assert before==after
    (BASE/'retained-history.json').write_text(json.dumps(report,indent=2))
    (BASE/'retained-size-example.json').write_text(json.dumps(sized,indent=2))
    summary=dict(original_files_preserved=len(before),original_hashes=before,entry_source_comparison_fields_exact=True,original_comparison_fields_exact_except_preexisting_links=True,preexisting_link_corrections=prior_link_corrections,comparisons=8,history_items_traced=checked,coverage=report['coverage'],qualified_observations_by_metric={m:sum(i['qualifying_observations'] for i in report['items'] if i['metric']==m) for m in ('raw_gap','arb_return','ev')},net_still_unavailable=True,history_rebuild_exact=True)
    (BASE/'retained-audit.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k!='original_hashes'},indent=2),flush=True)

if __name__=='__main__':main()
