"""Ordinary bounded pages and Dashboard/Scanner timing; no acquisition."""
import json,sys,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.pipeline_recovered_reads import read,release
out=dict(at=time.time(),concurrent=[],pages=[]);tokens=[]
try:
    for _ in range(3):
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls={name:pool.submit(read,path,params) for name,path,params in [('odds','/api/boards/slate',dict(view='odds',filter='all',limit=50,offset=0)),('dashboard','/api/boards/dashboard',None)]}
            pair={}
            for name,call in calls.items():
                r=call.result();d=r.pop('data',{});pair[name]=dict(r,coverage=d.get('coverage'),error=d.get('error'),reason=d.get('reason'))
                tokens.append(d.get('read_token'));tokens.extend(v.get('read_token') for v in d.get('slates',{}).values())
        out['concurrent'].append(pair);release(tokens);tokens=[]
    params=dict(view='odds',filter='all',limit=50,offset=0);started=time.monotonic();games=[]
    for _ in range(64):
        r=read('/api/boards/slate',params);d=r.pop('data',{});out['pages'].append(dict(r,coverage=d.get('coverage'),error=d.get('error'),reason=d.get('reason')))
        tokens.append(d.get('read_token'))
        if r.get('status')!=200:break
        games.extend(b['game_key'] for b in d.get('boards',[]));games.extend(e['game_key'] for e in d.get('errors',[]))
        if d['coverage']['complete']:break
        params.update(offset=d['coverage']['next_offset'],read_token=d['read_token'],expected_revision=d['read_revision'])
    out['traversal']=dict(seconds=time.monotonic()-started,returned=len(games),unique=len(set(games)),complete=d.get('coverage',{}).get('complete'))
    r=read('/api/scanner');d=r.pop('data',{});out['scanner']=dict(r,coverage=d.get('coverage'),availability=d.get('availability'),errors=d.get('errors'))
    Path(sys.argv[1]).write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
finally:release(tokens)
