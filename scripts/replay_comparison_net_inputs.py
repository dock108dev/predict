"""Bounded redacted retained receipt replay. Never starts source workers."""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from aiohttp import web
from app.collection.current_policy import DEFAULT
from app.collection.current_service import CurrentService
from app.collection.current_sink import LatestStateSink
from app.dashboard.current_state import CurrentStore, CURRENT_KEY, CurrentStateProvider
from app.dashboard.current_contract import snapshot_inputs
from app.dashboard.multi_game_server import create_app


def replay(path, event_id):
    retained = json.loads(Path(path).read_text())
    events = [e for e in retained['replay'] if e['id'] == event_id]
    if len(events) != 1:
        raise ValueError('Exactly one retained event required')
    body = json.dumps(events, sort_keys=True, separators=(',', ':')).encode()
    service = CurrentService(config=dict(DEFAULT, enabled=False, aggregate_enabled=False))
    envelope = service.initial_state()
    envelope.update(runtime_id=str(uuid4()), clock_at=retained['received_at'], projected_at=retained['received_at'])
    class Initial(CurrentStateProvider):
        def initial_state(self):return deepcopy(envelope)
    store = CurrentStore(Initial(), monotonic=lambda: 0)
    sink = LatestStateSink(store, envelope)
    states = {v:dict(s, state='available', reason_code='retained_receipt_replay', reason='Dated retained receipt replay') for v,s in service.states.items()}
    with patch('app.collection.current_sink.utc', return_value=retained['received_at']):
        sink.commit(dict(type='current_aggregate',sport=retained['sport'],body=body,received_at=retained['received_at']), states)
    return store.snapshot(), dict(evidence_class='dated_redacted_retained_replay',sport=retained['sport'],
        original_received_at=retained['received_at'], original_response_sha256=retained['body_sha256'],
        retained_receipt_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        bounded_replay_sha256=hashlib.sha256(body).hexdigest(), event_id=event_id,
        source_requests=0,charges=0,profiles=len(store._state.get('comparison_profiles',{})),sink_metrics=sink.metrics)


async def serve(raw):
    class Retained(CurrentStateProvider):
        def initial_state(self):return snapshot_inputs(raw)
    # Owner catalog is authored UI routing only; source receipt payload stays real.
    from tests.test_current_state import owner
    app=create_app(owner=owner(),sessions={},current_provider=Retained())
    app[CURRENT_KEY].monotonic=lambda:0
    app[CURRENT_KEY]._age_origin=0
    @web.middleware
    async def banner(request, handler):
        response=await handler(request)
        if request.path in ('/','/ev','/arbs') and isinstance(response,web.FileResponse):
            text=re.sub(r'(<body[^>]*>)',r'\1<div style="padding:8px;background:#493b16;color:white">DATED RETAINED REPLAY • frozen receipt clock • acquisition disabled • account fee applicability unverified</div>',response._path.read_text(),count=1)
            return web.Response(text=text,content_type='text/html',headers={k:v for k,v in response.headers.items() if k.lower()!='content-length'})
        return response
    app.middlewares.append(banner)
    runner=web.AppRunner(app);await runner.setup()
    site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
    print('RETAINED_PREVIEW_URL=http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1]),flush=True)
    try:await asyncio.Event().wait()
    finally:await runner.cleanup()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('receipt');parser.add_argument('event_id');parser.add_argument('--output',required=True);parser.add_argument('--serve',action='store_true')
    args=parser.parse_args();raw,report=replay(args.receipt,args.event_id)
    Path(args.output).write_text(json.dumps(dict(report=report,snapshot=raw),indent=2)+'\n')
    print(json.dumps(report),flush=True)
    if args.serve:asyncio.run(serve(raw))


if __name__=='__main__':main()
