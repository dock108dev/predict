"""Bounded owner-local market-stream verification; credentials never written.

Run with --public-evidence pointing to an existing successful public smoke folder.
Prompts on a real terminal only. No environment, browser or credential-store search.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import getpass
import hashlib
import json
from pathlib import Path
import sys

from app.models.core import EvidenceKind
from app.adapters.polymarket_us import Response, decode, parse_market, next_market_data
from app.adapters.polymarket_us_stream import RuntimeSigner, AuthenticatedTransport, MarketStream


def load_market(directory):
    records = json.loads((directory / 'provenance.json').read_text())
    detail = next(r for r in records if '/v1/market/slug/' in r['source'])
    catalog = next(r for r in records if '/events' in r['source'])
    response = Response((directory / detail['file']).read_text(), detail['source'],
                        datetime.fromisoformat(detail['received_at']))
    data = decode(response.body)['market']
    events = decode((directory / catalog['file']).read_text())['events']
    event = next(e for e in events if any(str(m['id']) == str(data['id']) for m in e.get('markets', [])))
    return parse_market(response, data, str(event['id']))


def save_stream_evidence(directory, stream, market, exercise):
    """Only fixed lifecycle fields and market frames; never transport/header objects."""
    records = []
    for i, response in enumerate(stream.responses):
        # Drop unexpected credential/account-bearing messages rather than risk
        # persisting them. Known market data is retained byte-for-byte as JSON text.
        try:
            if not isinstance(response.body, str):
                raise ValueError("expected text frame")
            data = decode(response.body)
            encoded_keys = set()
            def keys(value):
                if isinstance(value, dict):
                    for key, child in value.items():
                        encoded_keys.add(key.lower().replace('_', '').replace('-', ''))
                        keys(child)
                elif isinstance(value, list):
                    for child in value: keys(child)
            keys(data)
            sensitive = {'authorization','signature','secret','secretkey','apikey','apikeyid',
                         'accesskey','accesstoken','refreshtoken','accountid','userid','email',
                         'password','balance','positions','orders'}
            if encoded_keys & sensitive or not set(data) <= {'requestId','subscriptionType','marketData','heartbeat'}:
                records.append({'message_index':i,'retained':False,'reason':'unsupported_envelope_or_sensitive_fields',
                                'top_level_field_types':{key:type(value).__name__ for key,value in data.items()}})
                continue
        except (ValueError, TypeError):
            records.append({'message_index':i,'retained':False,'reason':'invalid_json'})
            continue
        name = f'market-frame-{i+1:03d}.json'
        (directory / name).write_text(response.body)
        records.append({'file':name,'received_at':response.received_at.isoformat(),
                        'source':response.source,'sha256':hashlib.sha256(response.body.encode()).hexdigest()})
    result = {'evidence_kind':'synthetic_transport_test' if stream.kind == EvidenceKind.SYNTHETIC else 'live_authenticated_market_stream', 'market_id':market.raw.ref.market_id,
              'market_slug':next_market_data(market)['slug'], 'events':stream.events,
              'diagnostics':stream.diagnostics, 'exercise':exercise,
              'messages':records, 'qualification':'current_subscription_advertised_window_only_freshness_and_depth_separate'}
    (directory/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


async def verify(market, signer, directory, *, factory=None, disconnect_after=10,
                 cancel_after=25, duration=30, stale_seconds=5,
                 kind=EvidenceKind.OBSERVATION, retry_sleep=asyncio.sleep, on_observation=None):
    native = next_market_data(market)
    start = datetime.fromisoformat(native['gameStartTime'].replace('Z','+00:00'))
    if native.get('category') != 'sports' or native.get('marketType') != 'moneyline' or start <= datetime.now(timezone.utc):
        raise ValueError('a current pregame sports moneyline is required')
    directory.mkdir(parents=True, exist_ok=False)
    transport = factory or AuthenticatedTransport(signer, allow_connection=True)
    exercise = {'local_disconnect_requested':False,'local_disconnect_completed':False,
                'cancellation_requested':False,'cancellation_propagated':False}
    timers = []
    connections = 0
    async def connect():
        nonlocal connections
        socket = await transport()
        connections += 1
        if connections == 1:
            async def disconnect():
                await asyncio.sleep(disconnect_after)
                exercise['local_disconnect_requested'] = True
                stream.record('deliberate_local_disconnect')
                await asyncio.wait_for(socket.close(), 2)
                exercise['local_disconnect_completed'] = True
            timers.append(asyncio.create_task(disconnect()))
        return socket
    stream = MarketStream([market],connect,max_messages=50,max_connections=2,
                          duration=duration,stale_seconds=stale_seconds,kind=kind,sleep=retry_sleep)
    async def consume():
        async for observation in stream.run():
            if on_observation is not None:
                await on_observation(observation, connections)
    task = asyncio.create_task(consume())
    try:
        done, _ = await asyncio.wait({task}, timeout=cancel_after)
        if not done:
            exercise['cancellation_requested'] = True
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            exercise['cancellation_propagated'] = True
    finally:
        if not task.done():
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
        for timer in timers:
            timer.cancel()
        await asyncio.gather(*timers, return_exceptions=True)
        await stream.aclose()
        result = save_stream_evidence(directory,stream,market,exercise)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-evidence',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--keychain',action='store_true',help='Explicitly load this project retail API entry from macOS Keychain')
    args=parser.parse_args()
    if not args.keychain and not sys.stdin.isatty():
        parser.error('Use an interactive local terminal for hidden credential entry.')
    market=load_market(args.public_evidence)
    try:
        if args.keychain:
            from keyring.backends.macOS import Keyring
            credentials=json.loads(Keyring().get_password('prediction-arb.polymarket-us','retail-api'))
            signer=RuntimeSigner(credentials['key_id'],credentials['secret_key'])
            del credentials
        else:
            key_id=getpass.getpass('Polymarket US Key ID (hidden): ')
            secret=getpass.getpass('Polymarket US Secret Key (hidden): ')
            signer=RuntimeSigner(key_id,secret)
            del key_id,secret
        result=asyncio.run(verify(market,signer,args.output))
        print('Bounded verification finished. Review result.json; no synchronization guarantee inferred.')
        print('Market frames retained:',sum('file' in m for m in result['messages']))
    except Exception:
        print('Verification did not complete; credentials and exception details suppressed.',file=sys.stderr)
        raise SystemExit(1) from None

if __name__ == '__main__':main()
