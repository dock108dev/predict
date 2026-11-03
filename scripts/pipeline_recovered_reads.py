"""Bounded ordinary HTTP qualification; release only this probe's read leases."""
import json
from pathlib import Path
import sys,time
from concurrent.futures import ThreadPoolExecutor
import httpx

BASE='http://127.0.0.1:8783'

def read(path,params=None):
    started=time.monotonic()
    try:
        with httpx.Client(timeout=30) as client:
            response=client.get(BASE+path,params=params)
            data=response.json()
        return dict(status=response.status_code,seconds=time.monotonic()-started,bytes=len(response.content),data=data)
    except Exception as exc:return dict(error=type(exc).__name__,seconds=time.monotonic()-started)

def release(tokens):
    with httpx.Client(timeout=5) as client:
        for token in set(tokens):
            if token:
                try:
                    response=client.delete(BASE+'/api/boards/read-lease',params=dict(read_token=token),
                        headers={'Origin':BASE,'Content-Type':'application/json'})
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    print('probe_lease_release_failed:'+type(exc).__name__,file=sys.stderr)

def run(path,folder='test-results/d02-storage-recovery/qualified-live'):
    out=dict(at=time.time(),concurrent=[],pages=[],selected=[]);tokens=[]
    try:
        for _ in range(3):
            with ThreadPoolExecutor(max_workers=2) as pool:
                odds=pool.submit(read,'/api/boards/slate',dict(view='odds',filter='all',limit=50,offset=0))
                dash=pool.submit(read,'/api/boards/dashboard')
                values=dict(odds=odds.result(),dashboard=dash.result())
            summary={}
            for key,value in values.items():
                d=value.pop('data',{});summary[key]=dict(value,coverage=d.get('coverage'),error=d.get('error'),reason=d.get('reason'))
                if key=='odds':tokens.append(d.get('read_token'))
                else:tokens.extend(v.get('read_token') for v in d.get('slates',{}).values())
            out['concurrent'].append(summary);release(tokens);tokens=[]
        params=dict(view='odds',filter='all',limit=50,offset=0);games=[];start=time.monotonic()
        for _ in range(64):
            result=read('/api/boards/slate',params);d=result.pop('data',{})
            out['pages'].append(dict(result,coverage=d.get('coverage'),error=d.get('error'),reason=d.get('reason')))
            if result.get('status')!=200:break
            tokens.append(d.get('read_token'));games.extend(b.get('game_key') for b in d.get('boards',[]));games.extend(e.get('game_key') for e in d.get('errors',[]))
            if d['coverage']['complete']:break
            params.update(offset=d['coverage']['next_offset'],read_token=d['read_token'],expected_revision=d['read_revision'])
        out['traversal']=dict(seconds=time.monotonic()-start,returned=len(games),unique=len(set(games)),complete=d.get('coverage',{}).get('complete'))
        release(tokens);tokens=[]
        from pipeline_delivery_report import load_samples
        sample=load_samples(folder)[-1]
        from pipeline_convergence_report import publication_current
        valid=[p for p in sample['publications'] if publication_current(p,sample)]
        for p in valid[:12]:
            result=read('/api/boards/ev',dict(game=p['game_key'],filter='all'));d=result.pop('data',{})
            tokens.append(d.get('read_token'))
            out['selected'].append(dict(result,game=p['game_key'],validated_sample_at=sample['at'],generation=p['generation'],
                facts={k:d.get(k) for k in ('read_at','calculated_at','background_reasons','calculation_reasons','observation_reasons','comparison_reasons','availability','estimate_availability','error','reason')}))
        Path(path).write_text(json.dumps(out,indent=2)+'\n')
        print(json.dumps({k:v for k,v in out.items() if k!='selected'},indent=2))
    finally:release(tokens)

if __name__=='__main__':run(*sys.argv[1:])
