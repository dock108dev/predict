"""Capture a complete ordinary read, retaining errors and exact page bodies."""
import argparse
from pathlib import Path
import json
import time
import httpx

p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--view',default='ev');args=p.parse_args()
root=Path(args.directory);root.mkdir(parents=True,exist_ok=True)
params=dict(view=args.view,filter='all',limit=50,offset=0);start=time.monotonic()
with httpx.Client(timeout=120) as client:
    i=0
    while True:
        r=client.get('http://127.0.0.1:8783/api/boards/slate',params=params)
        if r.status_code!=200:
            (root/'error.txt').write_text(r.text);raise RuntimeError(f'{r.status_code}: {r.text[:500]}')
        value=r.json();(root/f'{i:03}.json').write_bytes(r.content)
        print(json.dumps(dict(page=i,elapsed=time.monotonic()-start,coverage=value['coverage'],errors=len(value['errors']))),flush=True)
        if value['coverage']['complete']:break
        params.update(offset=value['coverage']['next_offset'],read_token=value['read_token'],expected_revision=value['read_revision']);i+=1
