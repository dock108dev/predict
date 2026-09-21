"""Explicitly opted-in, finite read-only verification; separate Keychain entries.

Run --help. Authentication and subscription responses never enter evidence.
"""
import argparse
import asyncio
from contextlib import aclosing
from datetime import datetime, timezone
from getpass import getpass
import hashlib
import json
from pathlib import Path
import sys

from app.adapters.prophetx import Client, Credentials, ProphetXAdapter, decode
from app.adapters.prophetx_stream import Stream

SENSITIVE = {'access_token', 'refresh_token', 'access_key', 'secret_key', 'authorization',
             'auth', 'user_data', 'user_id', 'account_id', 'password', 'email', 'phone',
             'socket_id', 'token', 'secret', 'key'}


def safe_market(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in SENSITIVE:
                raise ValueError('unexpected sensitive field in market evidence')
            safe_market(child)
    elif isinstance(value, list):
        for child in value:
            safe_market(child)


class Evidence:
    def __init__(self, path, limit):
        self.path, self.remaining = path, limit
        self.path.mkdir(parents=True, exist_ok=False)
        self.count = 0
        self.records = []

    def retain(self, response, *, stream=False):
        value = decode(response.body)
        safe_market(value)
        if stream:
            from app.adapters.prophetx_stream import frame
            import base64
            env, data = frame(response.body)
            if env.get('event') != 'market_selections':
                raise ValueError('not market-only evidence')
            safe_market(data)
            safe_market(decode(base64.b64decode(data['payload'], validate=True)))
        payload = response.body.encode()
        if len(payload) > self.remaining:
            raise ValueError('storage budget exhausted')
        self.remaining -= len(payload)
        self.count += 1
        name = f'market-{self.count:03}.json'
        (self.path/name).write_bytes(payload)
        self.records.append({'file':name,'source':response.source,
            'received_at':response.received_at.isoformat(),'sha256':hashlib.sha256(payload).hexdigest()})


def credentials(environment):
    import os
    prefix = 'PROPHETX_' + environment.upper() + '_'
    names = (prefix + 'ACCESS_KEY', prefix + 'SECRET_KEY')
    local = {}
    env_file = Path(__file__).resolve().parents[1] / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            key, separator, value = line.partition('=')
            if separator and key.strip() in names:
                local[key.strip()] = value.strip().strip('"').strip("'")
    # Use one complete source, never mix credentials across sources/environments.
    source = os.environ if any(name in os.environ for name in names) else local
    if any(name in source for name in names):
        if not all(source.get(name) for name in names):
            raise ValueError('incomplete environment-scoped credentials')
        return Credentials(environment, source[names[0]], source[names[1]])
    from keyring.backends.macOS import Keyring
    value = Keyring().get_password('prediction-arb.prophetx.'+environment, 'trading-api')
    if value is None:
        raise ValueError('project credential missing; use --configure-keychain on a local terminal')
    values = json.loads(value)
    if values.get('environment') != environment:
        raise ValueError('credential environment mismatch')
    return Credentials(environment, values['access_key'], values['secret_key'])


async def run(args):
    creds = credentials(args.environment)
    path = Path(args.output) / (args.environment+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    evidence = Evidence(path, 5_000_000)
    result = {'environment':args.environment,'classification':args.environment+' observation',
        'budgets':{'rest_attempts':20,'seconds':90,'frames':200,'storage_bytes':5_000_000,'events':1,'markets':3,'connections':2},
        'authentication':False,'catalog':False,'initial_image':False,'reconnect_image':False,
        'disconnect_requested':False,'cancellation_propagated':False,'changed_selection_window':False}
    client = Client(creds,request_budget=20,byte_budget=5_000_000,observer=evidence.retain)
    adapter = ProphetXAdapter(client)
    stream = None
    try:
        async with asyncio.timeout(90):
            await client.authenticate()
            result['authentication']=True
            tournaments=await adapter.discover_tournaments()
            result['catalog']=True
            if args.tournament is None:
                result['tournaments']=[{'id':x['id'],'name':x['name']} for x in tournaments]
                result['stop']='catalog complete; select a returned sports tournament ID'
                return result
            if args.tournament not in {str(x['id']) for x in tournaments}:
                raise ValueError('tournament not in returned catalog')
            adapter.tournament_ids=(args.tournament,)
            events=await adapter.discover_events()
            now=datetime.now(timezone.utc)
            candidates=[x for x in events if x.scheduled_start is not None and x.scheduled_start>now
                and next((r.get('status') for r in decode(x.raw.json_text)['data']['sport_events'] if str(r.get('event_id'))==x.raw.ref.event_id),None)=='not_started']
            if args.event:
                candidates=[x for x in candidates if x.raw.ref.event_id==args.event]
            if not candidates:
                result['stop']='no qualifying pregame event in bounded catalog';return result
            event=min(candidates,key=lambda x:x.scheduled_start)
            result['event_id']=event.raw.ref.event_id
            await adapter.discover_price_ladder()
            markets=await adapter.discover_markets(event.raw.ref.event_id)
            selected=tuple(x.raw.ref.market_id for x in markets if x.market_type.value=='moneyline' and x.outcomes and adapter.markets[x.raw.ref.market_id][2].get('sub_type')=='moneyline')[:3]
            if not selected:
                result['stop']='no representative moneyline selections; no wider scan';return result
            result['markets']=list(selected)
            stream=Stream(adapter,selected,duration=60,message_budget=200,byte_budget=2_000_000,reconnects=1,observer=lambda r:evidence.retain(r,stream=True))
            adapter.stream=stream
            recovered = asyncio.Event()
            prior_windows = {}
            async def consume():
                async with aclosing(stream.updates()) as iterator:
                    async for value in iterator:
                        if value.native_windows is None:continue
                        mid = value.raw.ref.market_id
                        prior = prior_windows.get(mid)
                        window = tuple(tuple((x.strike_id, x.price, x.quantity) for x in group) for group in value.native_windows)
                        if prior is not None and prior != window:
                            result['changed_selection_window'] = True
                        prior_windows[mid] = window
                        if stream.generation==1:result['initial_image']=True
                        if stream.generation==2:
                            result['reconnect_image']=True
                            recovered.set()
            task=asyncio.create_task(consume())
            try:
                done,_=await asyncio.wait({task},timeout=25)
                if not done:
                    result['disconnect_requested']=True
                    await stream.disconnect()
                    # Exercise session refresh explicitly without logging response.
                    await client.authenticate(force=True)
                    recovery_wait=asyncio.create_task(recovered.wait())
                    try:
                        done,_=await asyncio.wait({task,recovery_wait},timeout=25,return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        recovery_wait.cancel()
                        await asyncio.gather(recovery_wait,return_exceptions=True)
                if task in done:await task
            finally:
                if not task.done():
                    task.cancel()
                    try:await task
                    except asyncio.CancelledError:result['cancellation_propagated']=True
            result['stop']='bounded capture completed'
    except Exception as exc:
        result['stop']='verification stopped'
        result['error_class']=type(exc).__name__
    finally:
        await adapter.aclose()
        result['rest']=client.diagnostics
        result['stream']=[] if stream is None else stream.diagnostics
        result['frames']=0 if stream is None else stream.messages
        result['frame_counts']={} if stream is None else stream.frame_counts
        result['filtered_markets']=0 if stream is None else stream.filtered_markets
        result['market_data_delivery_verified']=result['initial_image'] and result['reconnect_image']
        result['transport_closed']=stream is None or stream.health=='disconnected'
        result['records']=evidence.records
        result['price_convention']='American_odds; corroborated Trading V4 REST/sandbox UI'
        result['quantity_unit_verified']=False
        (path/'result.json').write_text(json.dumps(result,indent=2))
        print('Evidence:',path)
    return result


def ResponseLike(raw):
    from app.adapters.prophetx import Response
    return Response(raw.json_text,raw.source,raw.received_at,raw.kind)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--environment',choices=['sandbox','production'],default='sandbox')
    parser.add_argument('--configure-keychain',action='store_true')
    parser.add_argument('--tournament')
    parser.add_argument('--event')
    parser.add_argument('--output',default='evidence/slice-3/live')
    args=parser.parse_args()
    if args.configure_keychain:
        if not sys.stdin.isatty():parser.error('hidden credential entry requires a local terminal')
        from keyring.backends.macOS import Keyring
        data={'environment':args.environment,'access_key':getpass('Access key: '),'secret_key':getpass('Secret key: ')}
        Credentials(args.environment,data['access_key'],data['secret_key'])
        Keyring().set_password('prediction-arb.prophetx.'+args.environment,'trading-api',json.dumps(data))
        print('Saved environment-specific project credential.');return
    if not args.live:parser.error('live requests require --live; use app.prophetx_example offline')
    try:result=asyncio.run(run(args))
    except Exception as exc:
        print('Verification unavailable:',type(exc).__name__,'(details suppressed).',file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps({k:v for k,v in result.items() if k in ('environment','authentication','catalog','stop','initial_image','reconnect_image','market_data_delivery_verified')},indent=2))
    if not result['authentication'] or result.get('error_class'):raise SystemExit(1)

if __name__=='__main__':main()
