from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Self

from app.models.core import Event, Market, OrderBook, Quote, SettlementProfile, Venue

MarketUpdate = Market | Quote | OrderBook | SettlementProfile


class ReadOnlyAdapter(ABC):
    """Adapters own pagination, native parsing and eventual stream recovery.

    IDs are venue-native. Observations retain raw provenance. stream_markets
    returns an async iterator (not an awaitable); updates are whole observed
    images, not deltas. Unknown IDs raise LookupError. Invalid input raises
    ValueError. Errors/cancellation propagate; never substitute empty success.
    Consumers must honor unknown state/depth/sync. aclose releases resources.
    """

    @property
    @abstractmethod
    def venue(self) -> Venue: ...

    @abstractmethod
    async def discover_events(self) -> tuple[Event, ...]: ...

    @abstractmethod
    async def discover_markets(self, event_id: str | None = None) -> tuple[Market, ...]: ...

    @abstractmethod
    async def get_snapshot(self, market_id: str) -> OrderBook: ...

    @abstractmethod
    def stream_markets(self, market_ids: tuple[str, ...]) -> AsyncIterator[MarketUpdate]: ...

    @abstractmethod
    async def get_market_rules(self, market_id: str) -> SettlementProfile: ...

    async def aclose(self) -> None:
        """Override when an adapter owns sessions or other resources."""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.aclose()
