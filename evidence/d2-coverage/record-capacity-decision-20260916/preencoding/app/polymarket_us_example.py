"""Finite historical replay by default. Public smoke requires explicit owner opt-in."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import httpx
from app.adapters.polymarket_us import PolymarketUSAdapter, Response, next_market_data
from app.models.core import EvidenceKind, MarketType

ROOT = Path(__file__).resolve().parents[1]

async def run(live=False, output=None):
    historical = ROOT / 'evidence/phase-0'
    if live:
        adapter = PolymarketUSAdapter(max_pages=1, page_size=3, request_cap=5, attempts=1)
        now = datetime.now(timezone.utc)
    else:
        def handler(request):
            path = request.url.path
            name = 'pmus-nfl-events.json' if '/events' in path else 'pmus-tb-cin-book.json' if path.endswith('/book') else 'pmus-tb-market.json'
            return httpx.Response(200, text=(historical / name).read_text())
        adapter = PolymarketUSAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                                      max_pages=1, page_size=3, request_cap=5, attempts=1)
        now = datetime(2026, 9, 11, tzinfo=timezone.utc)
        # Preserve original capture source/receipt, never label replay time as capture.
        manifest = json.loads((historical / 'manifest.json').read_text())
        original_get = adapter._get
        async def replay_get(path, params=None):
            response = await original_get(path, params)
            name = 'pmus-nfl-events.json' if '/events' in path else 'pmus-tb-cin-book.json' if path.endswith('/book') else 'pmus-tb-market.json'
            item = next(x for x in manifest if x['file'] == name)
            restored = Response(response.body, item['source_endpoint'], datetime.fromisoformat(item['retrieved_at_utc']), EvidenceKind.OBSERVATION)
            adapter.responses[-1] = restored
            return restored
        adapter._get = replay_get
    async with adapter:
        await adapter.discover_events()
        markets = await adapter.discover_markets()
        selection = [m for m in markets if m.market_type == MarketType.MONEYLINE
                     and next_market_data(m).get('category') == 'sports'
                     and next_market_data(m).get('active') is True
                     and next_market_data(m).get('closed') is False
                     and next_market_data(m).get('gameStartTime')
                     and datetime.fromisoformat(next_market_data(m)['gameStartTime'].replace('Z', '+00:00')) > now]
        print('NEW PUBLIC REST' if live else 'PRESERVED PHASE 0 REPLAY; historical pregame selection')
        if selection:
            market = await adapter.get_market(selection[0].raw.ref.market_id)
            book = await adapter.get_snapshot(market.raw.ref.market_id)
            rules = await adapter.get_market_rules(market.raw.ref.market_id)
            bbo = await adapter.get_bbo(market.raw.ref.market_id) if live else None
            print(f'event={market.raw.ref.event_id} market={market.raw.ref.market_id} title={market.title}')
            print(f'sides={[(s.native_id, s.label) for s in market.outcomes]}')
            print(f'state={book.state} sync={book.sync} exchange={book.raw.exchange_at} receipt={book.raw.received_at}')
            print(f'source_age_at_receipt={book.raw.source_age_at_receipt}; not transport latency; no age policy applied')
            print('Observed levels only; total exchange depth and executable capacity are unknown.')
            for outcome in book.outcomes:
                for label, ladder in [('bids', outcome.bids), ('asks', outcome.asks)]:
                    print(outcome.outcome_id, label, 'unavailable' if ladder is None else
                          f'levels={len(ladder.levels)} depth={ladder.depth} top={ladder.levels[:1]}')
            print(f'rules_available={rules.rules_text is not None}; bbo={bbo}; compatibility=unknown')
        else:
            print('No pregame moneyline in bounded selection; no wider scan attempted.')
        print(f'HTTP attempts={adapter.requests}; discovery_truncated={adapter.discovery_truncated}')
        if output:
            output.mkdir(parents=True, exist_ok=False)
            records = []
            for i, response in enumerate(adapter.responses):
                filename = f'response-{i+1}.json'
                (output / filename).write_text(response.body)
                records.append({'file': filename, 'source': response.source, 'received_at': response.received_at.isoformat(),
                                'http_status': response.http_status, 'response_headers': dict(response.http_headers),
                                'kind': 'new_public_observation' if live else 'preserved_phase_0_replay'})
            (output / 'provenance.json').write_text(json.dumps(records, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-public', action='store_true')
    parser.add_argument('--owner-confirmed-terms', action='store_true', help='Owner has personally reviewed/accepted applicable retail terms')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.live_public and not args.owner_confirmed_terms:
        parser.error('live run requires owner-confirmed terms; see docs/slice-2.md')
    asyncio.run(run(args.live_public, args.output))
