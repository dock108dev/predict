"""Separate bounded streaming HTTP measurement client; no acquisition."""
import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import resource
from time import perf_counter, time
from urllib.parse import urlencode
from aiohttp import ClientSession


async def measure(args):
    if not os.environ.get('PREDICT_CI_ISOLATED_ROOT'):raise ValueError('Offline guard required')
    samples=[]
    async with ClientSession() as client:
        async def get(path, phase, capture=False):
            start=perf_counter();response=await client.get(args.url+path,headers={'X-EV08-Sent-At':str(time()),'X-EV08-Dispatch-Monotonic':str(start)})
            headers=perf_counter();count=0;content=sha256();body=bytearray() if capture else None
            async for chunk in response.content.iter_chunked(65536):
                count+=len(chunk);content.update(chunk)
                if capture:
                    if count>32768:raise ValueError('Selected context capacity')
                    body.extend(chunk)
            samples.append(dict(path=path,phase=phase,dispatch_monotonic=start,seconds=perf_counter()-start,headers_seconds=headers-start,
                status=response.status,bytes=count,body_sha256=content.hexdigest()))
            Path(args.out).write_text(json.dumps(dict(samples=samples,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                client='separate process; streaming complete bodies; browser parsing measured separately'),indent=2)+'\n')
            if response.status!=200 or count!=int(response.headers['Content-Length']):raise ValueError('Complete HTTP body failed')
            if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss>=768*1024*1024:raise ValueError('Client process memory cap')
            return json.loads(body) if capture else None
        async def details(phase):
            if not args.fresh_details:return args.details
            context=await get('/__ev08/selected-context','context_binding_'+phase,capture=True)
            return '/api/current/details?'+urlencode(context)
        for _ in range(10):
            for path in ('/api/current','/api/comparison'):await get(path,'ordinary_serial')
            await get(await details('ordinary_serial'),'ordinary_serial')
        for _ in range(3):
            selected=await details('concurrent_four')
            await asyncio.gather(*(get(path,'concurrent_four') for path in ('/api/current','/api/comparison','/api/comparison',selected)))
        if args.burst:
            selected=await details('calculation_burst')
            await asyncio.gather(*(get(path,'calculation_burst') for path in ('/api/comparison?ceiling=500','/api/current',selected)))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--details',required=True);parser.add_argument('--out',required=True);parser.add_argument('--burst',action='store_true');parser.add_argument('--fresh-details',action='store_true')
    asyncio.run(measure(parser.parse_args()))
