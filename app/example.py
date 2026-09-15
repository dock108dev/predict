"""Run with python3 -m app.example from the project root."""

import asyncio

from app.adapters.base import ReadOnlyAdapter
from app.adapters.synthetic import SyntheticAdapter
from app.models.core import Market, Quote


async def demonstrate(adapter: ReadOnlyAdapter) -> None:
    async with adapter:
        event = (await adapter.discover_events())[0]
        market = (await adapter.discover_markets(event.raw.ref.event_id))[0]
        market_id = market.raw.ref.market_id
        book = await adapter.get_snapshot(market_id)
        rules = await adapter.get_market_rules(market_id)
        print(f"SYNTHETIC ONLY: {event.title}; venue={adapter.venue}")
        print(f"native event={event.raw.ref.event_id}; market={market_id}; canonical={market.canonical_id}")
        print(f"state={market.state}; sync={book.sync}; exchange_at={book.raw.exchange_at}")
        for outcome in book.outcomes:
            print(f"{outcome.outcome_id}: bid levels={len(outcome.bids.levels)}; "
                  f"depth={outcome.bids.depth}; asks={outcome.asks}; unit={book.quantity_unit}")
        print(f"first price={book.outcomes[0].bids.levels[0].price.value}")
        print(f"overtime={rules.includes_overtime}; cancellation={rules.cancellation_behavior}")
        async for update in adapter.stream_markets((market_id,)):
            if isinstance(update, Quote):
                print(f"quote: bid={update.bid.price.value}; size={update.bid.quantity}; "
                      f"ask={update.ask}; exchange_at={update.raw.exchange_at.isoformat()}")
            elif isinstance(update, Market):
                print(f"market update: state={update.state}; exchange_at={update.raw.exchange_at}")
        print("Complete: finite synthetic demonstration; no live qualification.")


if __name__ == "__main__":
    asyncio.run(demonstrate(SyntheticAdapter()))
