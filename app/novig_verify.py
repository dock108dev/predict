"""Explicit opt-in private bounded NBX verification. No orders or account reads."""
import argparse
import asyncio
from contextlib import aclosing
from dataclasses import asdict
import getpass
import hashlib
import json
import os
from pathlib import Path
from app.adapters.novig import NovigAdapter
from app.adapters.novig_stream import MarketStream
from app.models.core import OrderBook


def credentials(environment):
    from keyring.backends.macOS import Keyring
    keyring=Keyring(); service='prediction-arb.novig.'+environment
    return tuple(keyring.get_password(service,k) for k in ('client_id','client_secret'))


def write(path,data):
    path.write_text(json.dumps(data,default=str,indent=2)); path.chmod(0o600)


async def verify(args):
    out=Path(args.output).resolve(); out.mkdir(parents=True,exist_ok=False); out.chmod(0o700)
    report={'environment':args.environment,'kind':'live-verification-attempt','qualified':False,
            'limits':{'requests':30,'markets':2,'events':5,'duration_seconds':60,
                      'messages':100,'rest_bytes':8_000_000,'stream_bytes':2_000_000},
            'status':'started','initial_envelope':'unverified REST DTO compatibility',
            'ordering_guarantees':'unknown','depth':'unknown'}
    client_id,secret=credentials(args.environment)
    if not client_id or not secret:
        report.update(status='blocked',dependency='Novig-issued '+args.environment+' OAuth client_id and client_secret in dedicated Keychain')
        write(out/'report.json',report); return report
    a=NovigAdapter(environment=args.environment,client_id=client_id,client_secret=secret)
    stream=None
    try:
        async with asyncio.timeout(60), a:
            events=await a.discover_events()
            if not events: raise LookupError('no bounded pregame events')
            markets=await a.discover_markets(events[0].raw.ref.event_id)
            if not markets: raise LookupError('no bounded markets')
            for n,m in enumerate(markets):
                write(out/f'normalized-rest-{n}.json',asdict(await a.get_snapshot(m.raw.ref.market_id)))
            stream=MarketStream(a,list(markets),duration=35,max_messages=100,reconnect_after=10,reconnects=1)
            accepted=0; recovered_update=False; first_connection_ticks=None
            async with aclosing(stream.run()) as updates:
                async for update in updates:
                    accepted+=1
                    # Early completion requires a fresh image plus a real update on connection 2.
                    if stream.connections==1: first_connection_ticks=stream.ticks
                    if stream.connections==2 and stream.initial_images>=2*len(markets) and stream.ticks>(first_connection_ticks or 0):
                        recovered_update=True
                        break
            report.update(status='bounded capture complete',normalized_updates=accepted,
                sufficient_candidate_evidence=recovered_update)
    except Exception as exc:
        # Keep exception class only: transport errors can contain sensitive request details.
        report.update(status='stopped',error_type=type(exc).__name__)
    finally:
        if stream: await stream.aclose()
        await a.aclose()
        for n,r in enumerate(a.responses):
            if any(s and s in r.body for s in (client_id,secret)):
                report['status']='stopped: credential-like response omitted'; continue
            write(out/f'rest-{n:03}.json',asdict(r))
        if stream:
            for n,r in enumerate(stream.frames):
                if any(s and s in r.body for s in (client_id,secret)): continue
                write(out/f'frame-{n:03}.json',asdict(r))
            report.update(connections=stream.connections,initial_books=stream.initial_images,
                order_ticks=stream.ticks,messages=stream.messages,stream_bytes=stream.bytes,
                cleanup_verified=stream.closed and stream.ws is None)
        report.update(requests=a.requests,http_statuses=a.http_statuses,rest_bytes=a.bytes,
            token_issuances=a.renewals,discovery_truncated=a.truncated)
        write(out/'report.json',report)
        write(out/'manifest.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()})
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--environment',choices=('qa','production'),required=True)
    p.add_argument('--live',action='store_true',help='explicitly opt into bounded authenticated read-only capture')
    p.add_argument('--output',help='new private evidence directory, required for live capture')
    p.add_argument('--setup-keychain',action='store_true',help='enter venue-issued credentials locally with hidden input')
    args=p.parse_args()
    if args.setup_keychain:
        if args.live: p.error('setup and live verification are separate operations')
        from keyring.backends.macOS import Keyring
        k=Keyring(); service='prediction-arb.novig.'+args.environment
        values={name:getpass.getpass('Novig '+args.environment+' '+name+': ') for name in ('client_id','client_secret')}
        if any(not v.strip() for v in values.values()): p.error('nonempty credentials required')
        for name,value in values.items(): k.set_password(service,name,value)
        print('Dedicated environment credentials saved to Keychain.'); return
    if not args.live or not args.output: p.error('--live and --output are required; default performs no network requests')
    report=asyncio.run(verify(args)); print(json.dumps(report,indent=2))

if __name__=='__main__': main()
