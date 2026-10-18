"""Independent test-only data/app processes for the two-event DA working loop.

Requires the maintained disposable SQL cluster. No credentials, source adapters,
external network, owner data, or production model authority are used.
"""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import signal
import sys
from unittest.mock import patch
from uuid import uuid4

import psycopg
from aiohttp import web
from app.storage.payload_codec import payload_row
from app.storage.current_rows import CurrentRowStore
from app.storage.scanner_publication import transaction
from tests.sc06_fixture import AuthoredAdapters, Clock, native_books, records
from tests.test_da_separation_sql import FixtureService


async def run(args):
    assert args.socket.startswith('/tmp/predict-pg-')
    assert args.database.startswith('prediction_arb_da_')
    def connect():
        return psycopg.connect(host=args.socket,port=55432,user='prediction_arb',dbname=args.database,
            autocommit=True,row_factory=payload_row,connect_timeout=5)
    with connect() as db:
        assert str(db.execute('show data_directory').fetchone()['data_directory']).startswith('/tmp/predict-pg-')
    from app.collection.data_runtime import DataRuntime
    from app.collection.local_ownership import LocalOwnership
    from app.collection.runtime_client import RuntimeClient
    from app.dashboard.scanner_api import Scanner, mount
    from app.dashboard.scanner_client_api import mount as mount_client
    from app.comparison.scanner_destinations import Destinations
    from tests.test_sc03_tickets import catalog
    clock=Clock();clock.started=args.fixture_start;stopped=asyncio.Event()
    loop=asyncio.get_running_loop()
    for name in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(name,stopped.set)
    with AuthoredAdapters(),patch('app.collection.runtime_client.load',return_value=FixtureService().config):
        if args.role=='data':
            class Source(FixtureService):
                async def start(self,store):
                    await super().start(store)
                    with connect() as db:
                        if not db.execute('SELECT count(*) n FROM current_event').fetchone()['n']:
                            fixture=records(2,at=clock())
                            with transaction(db):
                                rows=CurrentRowStore(db);rows.upsert_records(fixture,now=clock(),source_status=self.states)
                                rows.replace_native_books(native_books(fixture))
                                db.execute('INSERT INTO da_fixture_dispatch VALUES(%s,1)',(self.runtime_id,))
                async def recover(self,runtime_id,candidate_digest):
                    assert runtime_id==self.runtime_id and candidate_digest==self.digest
                    self.closed=False;self.closing=False;self.dispatch=True
            runtime=DataRuntime(Source(),connector=connect,
                owner=LocalOwnership(Path(args.directory)/'data-owner'),
                scanner_factory=lambda service:Scanner(service,connector=connect,clock=clock,durable=True,
                    summary_path=Path(args.directory)/'summaries'))
            try:
                await runtime.start()
                print(json.dumps(dict(role='data',runtime_id=runtime.service.runtime_id)),flush=True)
                await stopped.wait()
            finally:await runtime.close()
            return
        app=web.Application();provider=RuntimeClient(connector=connect)
        scanner=mount(app,provider);scanner.connector=connect;scanner.clock=clock;scanner.projection.clock=clock
        scanner.tickets.allow_authored=True;scanner.tickets.clock=clock
        scanner.start()
        scanner.tickets.destinations=Destinations(catalog(scanner.projection.frame['instruments']))
        mount_client(app)
        # Any accidental HTTP shared evaluator call is a hard fixture failure.
        def forbidden(*args,**kwargs):raise AssertionError('App performed shared finance')
        from app.comparison import scanner_projection
        scanner_projection.evaluate=forbidden
        scanner.projection.evaluator=forbidden
        async def receipt():
            with connect() as db:
                row=db.execute('SELECT publication,runtime_revision,payload FROM scanner_latest WHERE singleton').fetchone()
                owner=provider.runtime()
                return dict(provider_requests=0,publication=None if row is None else row['publication'],
                    published_runtime_revision=None if row is None else row['runtime_revision'],
                    runtime_id=owner['runtime_id'],epoch=db.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch'])
        async def wait_new(previous):
            for _ in range(100):
                scanner.refresh()
                value=await receipt()
                identity=lambda item:(item['publication'],item['published_runtime_revision'],item['epoch'])
                if scanner.healthy and (previous is None or identity(value)!=identity(previous)):return value
                await asyncio.sleep(.05)
            with connect() as db:
                latest=db.execute('SELECT runtime_revision,publication,payload FROM scanner_latest WHERE singleton').fetchone()
                owner=provider.runtime()
            raise ValueError('Fixture background owner did not reconcile: '+json.dumps(dict(
                before=previous,publication=latest['publication'],healthy=scanner.healthy,
                reason=getattr(scanner,'unavailable_reason',None),runtime_active=owner['active'],
                runtime_revision=owner['revision'],published_runtime_revision=latest['runtime_revision'],
                stopped=latest['payload']['stopped'],deadline=latest['payload']['deadline'],
                errors=latest['payload']['errors'])))
        async def control(req):
            value=await req.json();action=value.get('action');before=await receipt()
            if action=='change':
                with connect() as db:
                    row=deepcopy(next(r for r in CurrentRowStore(db).capture(include_depth=True)['records'] if r['quote']['venue']=='kalshi'))
                    row['quote']['original'].update(value='0.25',native_value='0.25');row['quote']['depth'][0]['price']='0.25'
                    row['quote']['times'].update(source_at=clock(),received_at=clock())
                    with transaction(db):
                        rows=CurrentRowStore(db);rows.upsert_records([row],now=clock(),source_status=provider.states);rows.replace_native_books(native_books([row]))
                return web.json_response(await wait_new(before))
            if action=='reopen':
                await provider.recover(provider.runtime_id,provider.digest)
                return web.json_response(await wait_new(before))
            if action=='epoch':
                with connect() as db:
                    with transaction(db):db.execute('UPDATE current_row_epoch SET epoch=%s',(uuid4().hex,))
                return web.json_response(await wait_new(before))
            return web.json_response(await receipt())
        async def stop(req):
            ack=await provider.stop();return web.json_response(dict(stopped=True,**ack))
        root=Path(__file__).resolve().parents[1];assets=root/'app/dashboard/opportunity_static/current'
        async def asset(req):
            if req.match_info['name'] not in ('scanner.js','scanner.css','board-client.js'):raise web.HTTPNotFound()
            return web.FileResponse(assets/req.match_info['name'])
        async def shell(req):
            return web.Response(text=(assets/'scanner.html').read_text().replace('<body>',
                '<body><p>DA disposable two-event fixture · authored source/models/destinations · zero provider requests</p>'),content_type='text/html')
        app.router.add_post('/__test/state',control);app.router.add_post('/api/admin/current',stop)
        app.router.add_get('/current/assets/{name}',asset);app.router.add_get('/{tail:.*}',shell)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        print(json.dumps(dict(role='app',url=f'http://127.0.0.1:{port}')),flush=True)
        try:await stopped.wait()
        finally:await runner.cleanup();await provider.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('role',choices=('data','app'))
    for name in ('socket','database','directory'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--fixture-start',type=float,required=True)
    options=parser.parse_args()
    try:asyncio.run(run(options))
    except Exception as exc:
        print(json.dumps(dict(error=type(exc).__name__,reason=str(exc))),file=sys.stderr,flush=True)
        raise
