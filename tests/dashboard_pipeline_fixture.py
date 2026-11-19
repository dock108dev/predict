"""Authored inputs for retained dashboard SQL tests; never packaged by the app.

The production controller owns the queue, refresh, Stop and persistence paths.
Only discovery and book inputs are supplied here, without provider connections.
"""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from app.dashboard.pipeline import Pipeline
from app.depth_example import fixture
from app.models.core import Probability, Quantity, QuoteSide
from app.storage import Store


class FixturePipeline(Pipeline):
    def start(self):
        original = Store.start

        def fixture_start(store, environment, evidence_class, *args, **kwargs):
            return original(store, "synthetic", "synthetic", *args, **kwargs)

        with patch.object(Store, "start", fixture_start):
            return super().start()

    def bootstrap(self, discovery=None):
        data, self.fixture_ladders = fixture()
        self.parents, self.matcher, _, self.contexts, self.rows = data
        self.titles = {row["key"]: row["native"]["title"] for row in self.rows}
        for row in self.rows:
            self.event_titles[(row["venue"], row["native_event_id"])] = (
                "Atlanta vs Pittsburgh · authored storage fixture"
            )
        view = self.tick(0)
        return view if view is not None else self.evaluate()

    def tick(self, number):
        at = datetime.now(timezone.utc)
        price = "0.40" if number % 3 != 2 else "0.55"
        with self.observation_transaction():
            for ladder in self.fixture_ladders:
                observation = ladder.observation
                observation = replace(
                    observation,
                    quote=replace(
                        observation.quote,
                        raw=replace(observation.quote.raw, received_at=at, exchange_at=at),
                        ask=QuoteSide(
                            price=Probability(value=Decimal(price)),
                            quantity=Quantity(value=Decimal("3"), unit="contracts"),
                        ),
                    ),
                )
                self._save_observation(
                    observation,
                    levels=[dict(price=price, quantity="3", provenance="authored SQL fixture")],
                )
                self.books[(observation.quote.raw.ref.venue.value,
                            observation.quote.raw.ref.market_id)] = replace(
                    ladder, observation=observation,
                    levels=((price, "3", "authored SQL fixture"),),
                )
        self.dirty += 1
        return None if self.defer_views else self.evaluate()

    def book(self, number):
        return self.tick(number)

    def depth(self, candidate_id):
        # These fixtures already contain normalized AcquisitionLadder objects.
        with patch("app.dashboard.pipeline.book_ladders", lambda book, **kwargs: [book]):
            return super().depth(candidate_id)


class FixtureSource:
    def __init__(self, controller):
        self.controller = controller

    async def prepare(self):
        return [{}]

    async def venue(self, discovery):
        number = 1
        while not self.controller.stop_event.is_set():
            await asyncio.sleep(0.05)
            if not self.controller.stop_event.is_set():
                self.controller.offer(("book", number))
                number += 1

    async def close(self):
        pass
