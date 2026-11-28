"""Choose one bounded turn from the latest complete native book images."""

from heapq import nsmallest


def book_publication_order(
    pending_books,
    pending_since,
    derived_served,
    pending_clocks,
    pending_prices,
    derived_prices,
    price_changes,
    *,
    limit,
    now,
    wall,
):
    """Interleave overdue or least-served books with eligible fresh books."""

    def waiting_rank(market):
        arrived = pending_since.get(market, 0)
        if now - arrived >= 2:
            return (0, arrived, 0)
        return (1, derived_served.get(market, -1), arrived)

    def fresh(market):
        clock = pending_clocks.get(market)
        return clock is not None and 0 <= wall - clock <= 30

    def established_change(market):
        return pending_prices[market] != derived_prices.get(market) and (
            market in derived_prices or market in price_changes
        )

    def fresh_rank(market):
        current = fresh(market)
        clock = pending_clocks[market] if current else 0
        return (
            not current,
            not established_change(market),
            -clock,
            waiting_rank(market),
        )

    # Keep bounded prefixes. Coalescing preserves arrival order, and a recent
    # source clock leaves more time for SQL admission before freshness expires.
    oldest = nsmallest(limit, pending_books, key=waiting_rank)
    eligible = (
        market
        for market in pending_prices
        if fresh(market) or established_change(market)
    )
    hot = iter(nsmallest(limit, eligible, key=fresh_rank))
    scheduled = set()
    ordered = []
    for market in oldest:
        if market in scheduled:
            continue
        ordered.append(market)
        scheduled.add(market)
        for recent in hot:
            if recent not in scheduled:
                ordered.append(recent)
                scheduled.add(recent)
                break
        if len(ordered) >= limit:
            break
    return ordered[:limit]
