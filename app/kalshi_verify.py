"""Explicit finite read-only production capture; no secrets in evidence."""
import argparse
import asyncio
from contextlib import aclosing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from app.adapters.kalshi import KalshiAdapter, quotes
from app.adapters.kalshi_stream import AuthenticatedTransport, MarketStream, keychain_signer
from app.models.core import BookSync


async def verify(output, authenticated=False, seconds=30):
    output.mkdir(parents=True, exist_ok=False)
    report = {'kind': 'live_read_only', 'authenticated_requested': authenticated,
              'stream_verified': False, 'limits': {'REST_attempts': 24, 'stream_seconds': seconds,
              'connections': 2, 'messages': 500}, 'started_at': datetime.now(timezone.utc).isoformat()}
    adapter = KalshiAdapter(series=('KXNFLGAME',), max_pages=1, page_size=5, max_requests=24)
    try:
        async with adapter:
            events = await adapter.discover_events()
            report['events'] = [e.raw.ref.event_id for e in events]
            if not events:
                report['result'] = 'no_verified_pregame_event_in_bounded_page'
                return
            # Closest scheduled game in this bounded page, not an inferred ticker date.
            event = min(events, key=lambda e: e.scheduled_start)
            markets = await adapter.discover_markets(event.raw.ref.event_id)
            report['markets'] = [m.raw.ref.market_id for m in markets]
            if not markets:
                report['result'] = 'no_markets'
                return
            market = markets[0]
            mid = market.raw.ref.market_id
            rules = await adapter.get_market_rules(mid)
            book = await adapter.get_snapshot(mid)
            await adapter.get_fee_metadata(event.raw.ref.event_id)
            report.update(result='REST_verified', selected_market=mid,
                schedule=event.scheduled_start.isoformat(), rules_present=bool(rules.rules_text),
                rule_link=rules.official_source, rest_sync=book.sync.value,
                source_timestamp=book.raw.exchange_at, depth=[o.bids.depth.value if o.bids else None for o in book.outcomes],
                level_counts=[len(o.bids.levels) if o.bids else None for o in book.outcomes],
                quotes=[{'outcome': q.outcome_id, 'bid': str(q.bid.price.value) if q.bid else None,
                         'ask': str(q.ask.price.value) if q.ask else None} for q in quotes(book)])
            if authenticated:
                try:
                    factory = AuthenticatedTransport(keychain_signer())
                except (RuntimeError, ValueError):
                    report['stream_dependency'] = 'dedicated_project_keychain_credential'
                else:
                    stream = MarketStream(list(markets[:2]), factory, duration=seconds,
                                          reconnect_after_seconds=seconds / 3, max_connections=2)
                    observations = []
                    async with aclosing(stream.run()) as updates:
                        async for update in updates:
                            observations.append({'sync': update.sync.value, 'sequence': update.sequence,
                                'source_progress': update.source_time_progress.value})
                    frames = [{'generation': g, 'received_at': t.isoformat(), 'body': b}
                              for g, t, b in stream.engine.frames]
                    (output / 'stream.json').write_text(json.dumps(frames, indent=2))
                    report['stream'] = {'diagnostics': stream.diagnostics, 'observations': observations,
                                        'reason': stream.reason, 'health': stream.transport_health}
                    types = [json.loads(f['body'])['type'] for f in frames]
                    snapshot_markets = {}
                    for saved in frames:
                        frame = json.loads(saved['body'])
                        if frame['type'] == 'orderbook_snapshot':
                            snapshot_markets.setdefault(saved['generation'], set()).add(frame['msg']['market_ticker'])
                    report['recovery_snapshots_generations'] = sorted(snapshot_markets)
                    expected = {m.raw.ref.market_id for m in markets[:2]}
                    report['qualification'] = {
                        'initial_snapshot': snapshot_markets.get(1) == expected,
                        'delta_reconstruction_observed': 'orderbook_delta' in types,
                        'fresh_subscription_recovery': snapshot_markets.get(2) == expected,
                        'no_protocol_or_transport_failures': not any(d['event'] == 'connection_or_protocol_failure' for d in stream.diagnostics),
                        'cleanup': stream.closed and stream.connection is None,
                    }
                    report['stream_verified'] = all(report['qualification'].values())
    except Exception as exc:
        report['failure_type'] = type(exc).__name__
        report['result'] = 'failed'
        raise
    finally:
        report['REST_attempts'] = adapter.requests
        report['discovery_truncated'] = adapter.discovery_truncated
        records = []
        for i, response in enumerate(adapter.responses):
            name = f'rest-{i:02d}.json'
            (output / name).write_text(response.body)
            records.append({'file': name, 'source': response.source, 'received_at': response.received_at.isoformat()})
        report['responses'] = records
        (output / 'report.json').write_text(json.dumps(report, indent=2))
        files = {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in output.iterdir() if p.is_file()}
        (output / 'manifest.json').write_text(json.dumps(files, indent=2))
        print(json.dumps({k: report[k] for k in ('result', 'REST_attempts', 'stream_verified') if k in report}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public', action='store_true', help='explicit public read-only request opt-in')
    parser.add_argument('--keychain', action='store_true', help='also run authenticated bounded stream')
    parser.add_argument('--seconds', type=int, default=30, choices=range(10, 61))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cancel-from', type=Path, help='test one-connection cancellation using saved discovery')
    args = parser.parse_args()
    if args.cancel_from:
        if not args.keychain:
            parser.error('--cancel-from requires --keychain')
        asyncio.run(verify_cancellation(args.output, args.cancel_from))
        return
    if not args.public:
        parser.error('--public is required to make live requests')
    asyncio.run(verify(args.output, args.keychain, args.seconds))


async def verify_cancellation(output, capture):
    """One authenticated connection using saved discovery; cancel after first image.

    No REST calls. Maximum ten seconds, one connection, twenty received messages.
    """
    from app.adapters.kalshi import Response, parse_market
    output.mkdir(parents=True, exist_ok=False)
    report = json.loads((capture / 'report.json').read_text())
    record = report['responses'][2]
    response = Response((capture / record['file']).read_text(), record['source'],
                        datetime.fromisoformat(record['received_at']))
    native = json.loads(response.body)['markets'][0]
    market = parse_market(response, native, native['event_ticker'], 'KXNFLGAME')
    stream = MarketStream([market], AuthenticatedTransport(keychain_signer()),
                          duration=10, max_connections=1, max_messages=20)
    ready = asyncio.Event()
    async def consume():
        async with aclosing(stream.run()) as updates:
            async for book in updates:
                if book.sync == BookSync.SYNCHRONIZED:
                    ready.set()
    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(ready.wait(), 10)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        result = {'snapshot_received': True, 'cancelled': task.cancelled(),
                  'closed': stream.closed, 'connection_released': stream.connection is None,
                  'cached_books_invalidated': all(b.sync == BookSync.UNSYNCHRONIZED for b in stream.engine.last.values()),
                  'REST_attempts': 0, 'max_connections': 1, 'max_seconds': 10}
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await stream.aclose()
    (output / 'report.json').write_text(json.dumps(result, indent=2))
    frames = [{'generation': g, 'received_at': t.isoformat(), 'body': b} for g,t,b in stream.engine.frames]
    (output / 'stream.json').write_text(json.dumps(frames, indent=2))
    (output / 'manifest.json').write_text(json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                                    for p in output.iterdir() if p.is_file()}, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
