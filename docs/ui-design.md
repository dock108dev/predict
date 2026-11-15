# Predict desk

## Current comparison interface

**Opportunities** opens on pregame full-game winners, spreads, and totals, including
available alternate lines. Use **Expected value** to compare offers against a
sportsbook estimate or another calculation basis. Use **Arbitrage** to see modeled
payoffs for opposing outcomes. In-game prices and the Live tab require the
`live_enabled` flag, which is off by default. A game leaves the pregame list at
kickoff or when an earlier authoritative state change withdraws it.

The EV list groups quotes for the exact outcome. The selected sportsbook, its
odds, and other available book prices appear alongside the fair-odds reference.
**Positive only** filters the selected calculation basis. Open a quote to see the
prices, fees, model assumptions, and settlement details available for that offer.
[Calculation basis](benchmark-ev.md) · [Trading fee policy](fee-coverage-policy.md)

## Find and compare games

Use **Find my game** or **Browse odds** to navigate by team or game, including
when a comparison lacks enough inputs to show EV. Browse shows aligned venue
columns for each exact outcome. An unavailable quote is shown as a dash. A
retained price can be labeled **Last known**.

The desk updates visible prices in place. **Refresh list** applies the latest
ranking and adds newly qualifying games. Open details keep the selected quote and
its evidence pinned while the list changes. **Use latest prices** adopts a
coherent update when one is available. If a first read fails, use **Retry**.
**Source status** links to collection information when the data worker is stopped
or unavailable. [Data and freshness limits](market-data-gaps.md)

American odds are the default. The **Decimal** option changes display formatting
without changing ranking or calculation inputs. The game table scrolls within
narrow windows. Dialogs support keyboard focus, Escape, and return to the
opening control.

## Saved odds and diagnostics

**Saved odds** opens the recorded captures available on this installation. Capture
time governs the archived price, freshness, and applicable fee evidence.
[Open a saved capture](development.md#frozen-replay)

**Raw Odds** shows source-local evidence. **Scanner** uses observed depth for
execution sizing and offers manually selected tickets. Predict does not place
orders. **Admin** contains source, coverage, spending, Stop, and settings
controls. **Admin → Database** is a read-only browser for working and retained
relations. [Raw Odds](raw-prices.md) · [Scanner](scanner-usage.md) ·
[Admin access](security.md)
