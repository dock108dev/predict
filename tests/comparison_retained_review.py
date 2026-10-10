"""Explicit isolated retained-source review through ordinary admission/routes.

No owner configuration, credentials, source workers, quota or live clock renewal.
Original retained source clocks stay unchanged. Never a launcher fallback.
"""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4
from aiohttp import web
from app.collection.current_policy import DEFAULT, candidate
from app.collection.current_sink import LatestStateSink
from app.dashboard.current_contract import snapshot_inputs
from app.dashboard.current_state import CurrentStateProvider, CurrentStore, CURRENT_KEY, unavailable
from app.dashboard.multi_game_server import create_app
from tests.test_current_state import owner

ROOT = Path(__file__).resolve().parents[1]


class RetainedProvider(CurrentStateProvider):
    def __init__(self, raw):
        self.raw=raw
        self.closed=False
        self.runtime_id=raw['runtime_id']
        self.digest=candidate()[0]

    def initial_state(self):return deepcopy(self.raw)
    async def close(self):self.closed=True
    def status(self):
        return dict(runtime_id=self.runtime_id,candidate_digest=self.digest,
            dispatch_enabled=False,ownership_held=False,cleanup_complete=True,
            cleanup_errors=[],odds_api_requests=0,
            state='retained_review',reason='Dated retained inputs; acquisition disabled; original source clocks unchanged')


def retained_inputs(*, historical=False):
    receipt=json.loads((ROOT/'app/fixtures/comparison-retained-aggregate-v1.json').read_text())
    envelope=unavailable();envelope['runtime_id']=str(uuid4())
    if historical:envelope['clock_at']=envelope['projected_at']=receipt['received_at']
    states={v:dict(state='budget_delayed' if v in ('novig','prophetx') else 'stopped',
        reason_code='retained_review',reason='Dated retained inputs only; acquisition disabled',next_due_at=None)
        for v in envelope['source_status']}
    envelope['source_status']=deepcopy(states)
    provider=RetainedProvider(envelope)
    store=CurrentStore(provider,monotonic=lambda:0)
    sink=LatestStateSink(store,envelope,dict(DEFAULT,enabled=False))
    from unittest.mock import patch
    from contextlib import nullcontext
    boundary=patch('app.collection.current_sink.utc',return_value=receipt['received_at']) if historical else nullcontext()
    with boundary:
        sink.commit(dict(type='current_aggregate',sport=receipt['sport'],
            body=json.dumps(receipt['replay']).encode(),received_at=receipt['received_at']),states)
    raw=snapshot_inputs(store._state)
    if historical:raw['clock_at']=raw['projected_at']=receipt['received_at']
    native=json.loads((ROOT/'app/fixtures/comparison-retained-native-v1.json').read_text())['snapshot']
    raw['events'].extend(deepcopy(native['events']))
    from app.collection.current_comparison_inputs import attach
    raw['comparison_profiles']=attach(raw)
    return raw


async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=57639)
    parser.add_argument('--historical',action='store_true',help='Dated historical evaluation boundary, not current data')
    parser.add_argument('--saved',type=Path,help='Read-only stopped current snapshot, preserving every original price and clock')
    args=parser.parse_args()
    if args.saved:
        raw=snapshot_inputs(json.loads(args.saved.read_text()))
        raw['runtime_id']=str(uuid4())
        from datetime import datetime, timezone
        raw['clock_at']=raw['projected_at']=datetime.now(timezone.utc).isoformat()
        from app.collection.current_comparison_inputs import attach
        raw['comparison_profiles']=attach(raw)
    else:
        raw=retained_inputs(historical=args.historical)
    provider=RetainedProvider(raw)
    application=create_app(owner=owner(),sessions={},current_provider=provider)
    store=application[CURRENT_KEY];store.monotonic=lambda:0;store._age_origin=0
    @web.middleware
    async def retained_banner(request, handler):
        response=await handler(request)
        if isinstance(response,web.FileResponse) and response._path.suffix=='.html':
            response=web.Response(text=response._path.read_text(),content_type='text/html',headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-type','content-length')})
        if response.content_type=='text/html' and response.body:
            import re
            response.text=re.sub(r'(<body[^>]*>)', r'\1<div style="padding:8px;background:#493b16;color:white">DATED RETAINED SOURCE REVIEW · acquisition disabled · original clocks retained · '+('historical evaluation boundary' if args.historical else 'expired prices remain withheld')+'</div>',response.text,count=1)
        return response
    application.middlewares.append(retained_banner)
    runner=web.AppRunner(application);await runner.setup()
    site=web.TCPSite(runner,'127.0.0.1',args.port);await site.start()
    print(json.dumps(dict(url='http://127.0.0.1:'+str(args.port),**provider.status())),flush=True)
    try:await asyncio.Event().wait()
    finally:await runner.cleanup()


if __name__=='__main__':asyncio.run(main())
