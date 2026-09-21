"""Synthetic native Kalshi only. No retained evidence or credential reads."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import socket
from unittest.mock import patch

from app.collection.delivery_capture import LoopbackTransport

MID='KXNFLGAME-FIXTURE-DET'
EID='KXNFLGAME-FIXTURE'


def inventory(start=None):
    start=start or (datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
    event=dict(event_ticker=EID,series_ticker='KXNFLGAME',title='Detroit vs Buffalo')
    milestone=dict(category='Sports',type='football_game',start_date=start,related_event_tickers=[EID])
    market=dict(ticker=MID,event_ticker=EID,title='Detroit wins',yes_sub_title='Detroit',
        no_sub_title='Not Detroit',status='active',rules_primary='Synthetic full-game winner including overtime')
    return dict(events=[event],milestones=[milestone],cursor=''),dict(markets=[market],cursor='')


def snapshot(seq=1,qty='10'):
    return dict(type='orderbook_snapshot',sid=1,seq=seq,msg=dict(market_ticker=MID,market_id='native-fixture-id',
        yes_dollars_fp=[['0.4',qty]],no_dollars_fp=[['0.5','20']]))


def acknowledgement():return dict(type='subscribed',id=1,msg=dict(channel='orderbook_delta',sid=1))


def rest_book(qty='10'):return dict(orderbook_fp=dict(yes_dollars=[['0.4',qty]],no_dollars=[['0.5','20']]))


class NetworkGuard:
    def __enter__(self):
        from contextlib import ExitStack
        import keyring
        self.stack=ExitStack();original=socket.socket.connect;original_ex=socket.socket.connect_ex
        def allowed(address):
            return isinstance(address,str) or isinstance(address,tuple) and address[0] in ('127.0.0.1','::1')
        def connect(sock,address):
            if not allowed(address):raise AssertionError('external connection blocked')
            return original(sock,address)
        def connect_ex(sock,address):
            if not allowed(address):raise AssertionError('external connection blocked')
            return original_ex(sock,address)
        self.stack.enter_context(patch.object(socket.socket,'connect',connect))
        self.stack.enter_context(patch.object(socket.socket,'connect_ex',connect_ex))
        original_dns=socket.getaddrinfo
        def dns(host,*args,**kwargs):
            if host not in ('127.0.0.1','::1',None):raise AssertionError('external DNS blocked')
            return original_dns(host,*args,**kwargs)
        self.stack.enter_context(patch.object(socket,'getaddrinfo',dns))
        for name in ('get_password','set_password','delete_password','get_credential'):
            self.stack.enter_context(patch.object(keyring,name,side_effect=AssertionError('keyring blocked')))
        from keyring.backends.macOS import Keyring
        for name in ('get_password','set_password','delete_password'):
            self.stack.enter_context(patch.object(Keyring,name,side_effect=AssertionError('keyring backend blocked')))
        return self
    def __exit__(self,*args):return self.stack.__exit__(*args)


class Server:
    def __init__(self,*,busy=False,observe=None):self.busy=busy;self.observe=observe;self.http_calls=0;self.ws_calls=0;self.qty='10';self.tasks=set()
    async def start(self):
        from aiohttp import web
        self.origin=__import__('time').monotonic();self.events,self.markets=inventory()
        if self.observe:self.observe(dict(event='origin',mono=self.origin))
        async def http(request):
            self.http_calls+=1
            path=request.path
            if self.observe:self.observe(dict(event='http',mono=__import__('time').monotonic(),path=path,query=dict(request.query)))
            if path.endswith('/account/limits'):value=dict(read=dict(refill_rate=200,bucket_capacity=400))
            elif path.endswith('/account/endpoint_costs'):value=dict(default_cost=10,endpoint_costs=[])
            elif path.endswith('/events'):value=self.events
            elif path.endswith('/markets'):value=self.markets
            elif path.endswith('/orderbook'):value=rest_book(self.qty)
            else:raise web.HTTPNotFound()
            return web.json_response(value)
        async def ws(request):
            if self.observe:self.observe(dict(event='ws',mono=__import__('time').monotonic(),path=request.path))
            self.ws_calls+=1;socket_=web.WebSocketResponse();await socket_.prepare(request)
            cmd=await socket_.receive_json()
            if cmd['params']['market_tickers']!=[MID]:raise ValueError('fixture selection')
            await socket_.send_json(acknowledgement());await socket_.send_json(snapshot())
            async def send():
                seq=1
                while not socket_.closed:
                    await asyncio.sleep(.125)
                    elapsed=__import__('time').monotonic()-self.origin
                    if self.busy and not 55<=elapsed<110:
                        seq+=1;self.qty=str(10+seq%2)
                        await socket_.send_json(snapshot(seq,self.qty))
            task=asyncio.create_task(send());self.tasks.add(task)
            try:
                async for _ in socket_:pass
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True);self.tasks.discard(task)
            return socket_
        app=web.Application();app.router.add_get('/ws',ws);app.router.add_get('/{tail:.*}',http)
        self.runner=web.AppRunner(app,access_log=None);await self.runner.setup()
        site=web.TCPSite(self.runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        self.endpoints={'kalshi':dict(rest=f'http://127.0.0.1:{port}',ws=f'ws://127.0.0.1:{port}/ws')}
        return LoopbackTransport(self.endpoints)
    async def close(self):
        for t in self.tasks:t.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True);await self.runner.cleanup()
