"""Offline replay of the preserved Kalshi public capture. No account access."""
import asyncio
from datetime import datetime
import json
from pathlib import Path

import httpx
from app.adapters.kalshi import KalshiAdapter, quotes


async def main():
    root = Path(__file__).resolve().parents[1] / 'evidence/slice-4/public-20260912'
    report = json.loads((root / 'report.json').read_text())
    records = iter(report['responses'])
    clock = [datetime.fromisoformat(report['started_at'])]

    def handler(request):
        record = next(records)
        if str(request.url) != record['source']:
            raise ValueError('replay request differs from captured source')
        clock[0] = datetime.fromisoformat(record['received_at'])
        return httpx.Response(200, text=(root / record['file']).read_text())

    async def no_sleep(_):
        pass

    async with KalshiAdapter(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            series=('KXNFLGAME',), max_pages=1, page_size=5, sleep=no_sleep, now=lambda: clock[0]) as adapter:
        events = await adapter.discover_events()
        markets = await adapter.discover_markets(events[0].raw.ref.event_id)
        rules = await adapter.get_market_rules(markets[0].raw.ref.market_id)
        book = await adapter.get_snapshot(markets[0].raw.ref.market_id)
        fees = await adapter.get_fee_metadata(events[0].raw.ref.event_id)
        print('Historical Kalshi replay; not current prices or trading qualification')
        print(events[0].title, 'scheduled', events[0].scheduled_start.isoformat())
        print('Market:', book.raw.ref.market_id, 'metadata status:', markets[0].state)
        print('Native book:', book.sync, 'depth:', book.outcomes[0].bids.depth,
              'source timestamp:', book.raw.exchange_at, 'receipt:', book.raw.received_at.isoformat())
        for q in quotes(book):
            print(q.outcome_id, 'bid', q.bid.price.value if q.bid else None,
                  'derived ask', q.ask.price.value if q.ask else None)
        print('Rules:', rules.official_source, 'effective fee:', fees['effective_fee'])


if __name__ == '__main__':
    asyncio.run(main())
