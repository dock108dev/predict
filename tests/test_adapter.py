import asyncio
from importlib.resources import files
from unittest.mock import patch
import unittest

from app.adapters.base import ReadOnlyAdapter
from app.adapters.synthetic import SyntheticAdapter
from app.example import demonstrate
from app.models.core import BookSync, EvidenceKind, MarketState, Quote


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_synthetic_contract_without_network(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            async with SyntheticAdapter() as adapter:
                self.assertIsInstance(adapter, ReadOnlyAdapter)
                events = await adapter.discover_events()
                markets = await adapter.discover_markets(events[0].raw.ref.event_id)
                market = markets[0]
                mid = market.raw.ref.market_id
                book = await adapter.get_snapshot(mid)
                rules = await adapter.get_market_rules(mid)
                updates = [update async for update in adapter.stream_markets((mid,))]
                self.assertEqual(len(updates), 2)
                self.assertIsInstance(updates[0], Quote)
                self.assertIsNone(updates[0].bid.quantity)
                self.assertIsNone(updates[0].ask)
                self.assertIsNotNone(updates[0].raw.exchange_at)
                self.assertEqual(updates[1].state, MarketState.SUSPENDED)
                self.assertIsNone(updates[1].raw.exchange_at)
                self.assertEqual(book.sync, BookSync.UNKNOWN)
                self.assertIsNone(book.outcomes[0].asks)
                self.assertEqual(book.raw.ref, market.raw.ref)
                self.assertEqual(rules.raw.ref, market.raw.ref)
                for item in (events[0], market, book, rules, *updates):
                    self.assertEqual(item.raw.kind, EvidenceKind.SYNTHETIC)
                    self.assertEqual(item.raw.received_at.utcoffset().total_seconds(), 0)
                original = files("app.fixtures").joinpath("moneyline.json").read_text(encoding="utf-8")
                self.assertEqual(book.raw.json_text, original)

    async def test_bad_ids_and_subscriptions_fail(self):
        async with SyntheticAdapter() as adapter:
            for operation in (adapter.discover_markets, adapter.get_snapshot, adapter.get_market_rules):
                with self.assertRaises(LookupError):
                    await operation("not-present")
            mid = (await adapter.discover_markets())[0].raw.ref.market_id
            for invalid in ((), (mid, mid), mid):
                with self.assertRaises(ValueError):
                    _ = [u async for u in adapter.stream_markets(invalid)]
            with self.assertRaises(LookupError):
                _ = [u async for u in adapter.stream_markets(("not-present",))]

    async def test_context_closes_on_failure(self):
        adapter = SyntheticAdapter()
        with self.assertRaises(RuntimeError):
            async with adapter:
                raise RuntimeError("consumer failed")
        with self.assertRaises(RuntimeError):
            await adapter.discover_events()
        await adapter.aclose()  # Idempotent cleanup.

    async def test_stream_cancellation_propagates(self):
        async with SyntheticAdapter() as adapter:
            mid = (await adapter.discover_markets())[0].raw.ref.market_id
            stream = adapter.stream_markets((mid,))
            pending = asyncio.create_task(anext(stream))
            await asyncio.sleep(0)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            await stream.aclose()

    async def test_example_runs_against_abstract_contract(self):
        with patch("builtins.print") as output:
            await demonstrate(SyntheticAdapter())
        self.assertIn("no live qualification", output.call_args.args[0])

    def test_read_only_surface(self):
        expected = {"venue", "discover_events", "discover_markets", "get_snapshot",
                    "stream_markets", "get_market_rules", "aclose"}
        public = {name for name in vars(ReadOnlyAdapter) if not name.startswith("_")}
        self.assertEqual(public, expected)
        with self.assertRaises(TypeError):
            ReadOnlyAdapter()
