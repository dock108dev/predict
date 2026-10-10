"""Loopback comparison transport shared by retained synthetic suites."""

from datetime import datetime, timezone

from tests.opportunity_card_preview import TermsFixture


class ComparisonFixture(TermsFixture):
    async def send(self, c, mid=None):
        if c["venue"] == "kalshi":
            return await super().send(c, mid)
        if c["closed"] or self.owner.session.stop_event.is_set():
            return False
        before = self.books
        c["seq"] += 1
        mid = mid or c["command"]["subscribe"]["marketSlugs"][0]
        price = "0.48" if c["seq"] % 2 else "0.49"
        body = dict(
            requestId=c["command"]["subscribe"]["requestId"],
            subscriptionType="SUBSCRIPTION_TYPE_MARKET_DATA",
            marketData=dict(
                marketSlug=mid,
                bids=[dict(px=dict(value="0.43", currency="USD"), qty="120.75")],
                offers=[
                    dict(
                        px=dict(value=price, currency="USD"),
                        qty=str(100 + c["seq"]) + ".25",
                    )
                ],
                state="MARKET_STATE_OPEN",
                transactTime=datetime.now(timezone.utc).isoformat(),
            ),
        )
        c["images"].add(mid)
        await c["socket"].send_json(body)
        await self.wait(
            lambda: self.books > before or self.owner.session.stop_event.is_set()
        )
        await self.owner.session.queue.join()
        return self.books > before
