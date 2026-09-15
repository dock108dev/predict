"""Finite in-memory adapter over a packaged invented fixture. No network I/O."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime
from importlib.resources import files
import json

from app.adapters.base import MarketUpdate, ReadOnlyAdapter
from app.models.core import (
    BookLevel, Depth, Event, EvidenceKind, Ladder, Market, MarketState, MarketType,
    NativeRef, OrderBook, Outcome, OutcomeBook, Probability, Quantity, Quote,
    QuoteSide, RawPayload, SettlementProfile, Venue, parse_decimal, text,
)


class SyntheticAdapter(ReadOnlyAdapter):
    def __init__(self) -> None:
        self._json = files("app.fixtures").joinpath("moneyline.json").read_text(encoding="utf-8")
        self._data = json.loads(self._json)
        if self._data.get("synthetic") is not True:
            raise ValueError("only a wholly synthetic fixture is supported")
        self._closed = False

    @property
    def venue(self) -> Venue:
        return Venue.SYNTHETIC

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("adapter is closed")

    def _check_market(self, market_id: str) -> None:
        self._check_open()
        text(market_id, "market_id")
        if market_id != self._data["market_id"]:
            raise LookupError(market_id)

    def _raw(self, *, event_only: bool = False, update: dict | None = None) -> RawPayload:
        data = self._data if update is None else update
        return RawPayload(
            ref=NativeRef(venue=self.venue, event_id=self._data["event_id"],
                          market_id=None if event_only else self._data["market_id"]),
            source="synthetic://moneyline-fixture" if update is None else "synthetic://moneyline-updates",
            received_at=datetime.fromisoformat(data["received_at"]),
            exchange_at=None if data["exchange_at"] is None else datetime.fromisoformat(data["exchange_at"]),
            json_text=self._json if update is None else json.dumps(update),
            kind=EvidenceKind.SYNTHETIC,
        )

    async def discover_events(self) -> tuple[Event, ...]:
        self._check_open()
        return (Event(raw=self._raw(event_only=True), title=self._data["title"],
                      sport=self._data["sport"], league=self._data["league"],
                      participants=tuple(self._data["participants"])),)

    async def discover_markets(self, event_id: str | None = None) -> tuple[Market, ...]:
        self._check_open()
        if event_id is not None:
            text(event_id, "event_id")
            if event_id != self._data["event_id"]:
                raise LookupError(event_id)
        return (Market(raw=self._raw(), title=self._data["title"],
                       market_type=MarketType.MONEYLINE,
                       outcomes=tuple(Outcome(native_id=o["id"], label=o["label"])
                                      for o in self._data["outcomes"])),)

    async def get_snapshot(self, market_id: str) -> OrderBook:
        self._check_market(market_id)

        def ladder(rows: list | None) -> Ladder | None:
            if rows is None:
                return None
            return Ladder(depth=Depth.PARTIAL, levels=tuple(
                BookLevel(price=Probability(value=parse_decimal(price)),
                          quantity=Quantity(value=parse_decimal(size), unit=self._data["quantity_unit"]))
                for price, size in rows
            ))

        return OrderBook(raw=self._raw(), quantity_unit=self._data["quantity_unit"],
                         outcomes=tuple(OutcomeBook(outcome_id=o["id"], bids=ladder(o["bids"]),
                                                    asks=ladder(o["asks"]))
                                        for o in self._data["outcomes"]))

    async def stream_markets(self, market_ids: tuple[str, ...]) -> AsyncIterator[MarketUpdate]:
        self._check_open()
        if not isinstance(market_ids, tuple) or not market_ids:
            raise ValueError("market_ids must be a nonempty tuple")
        for market_id in market_ids:
            self._check_market(market_id)
        if len(set(market_ids)) != len(market_ids):
            raise ValueError("duplicate subscription IDs")
        for update in self._data["updates"]:
            await asyncio.sleep(0)  # Cancellation point; no socket, timer or remote feed.
            self._check_open()
            raw = self._raw(update=update)
            if update["kind"] == "quote":
                size = update["quantity"]
                yield Quote(raw=raw, outcome_id=update["outcome_id"],
                            bid=QuoteSide(price=Probability(value=parse_decimal(update["bid"])),
                                          quantity=None if size is None else Quantity(
                                              value=parse_decimal(size), unit=self._data["quantity_unit"])))
            elif update["kind"] == "market":
                market = (await self.discover_markets())[0]
                yield replace(market, raw=raw, state=MarketState(update["state"]))
            else:
                raise ValueError("unsupported synthetic update kind")

    async def get_market_rules(self, market_id: str) -> SettlementProfile:
        self._check_market(market_id)
        return SettlementProfile(raw=self._raw(), rules_text=self._data["rule_text"],
                                 official_source="synthetic://invented-rules")

    async def aclose(self) -> None:
        self._closed = True
