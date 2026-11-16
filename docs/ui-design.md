# Predict desk

## Current comparison interface

**Opportunities** opens on pregame full-game winners, spreads, and totals, including
available alternate lines. Use **Expected value** to compare offers against a
sportsbook estimate or another calculation basis. Use **Arbitrage** to see modeled
payoffs for opposing outcomes. In-game prices and the Live tab require the
`live_enabled` flag, which is off by default. A game leaves the pregame list at
kickoff or when an earlier authoritative state change withdraws it.

Opportunities shows moneyline, spread, and total separately for each game.
Expand a card to see more outcomes for that market. The EV list compares quotes
for the exact outcome. The selected sportsbook, its odds, and other available
book prices appear alongside the fair-odds reference.
When EV is unavailable, the card gives the reason alongside the prices. The
Arbitrage cards align each leg's venue, odds and allocation percentage with the
lowest modeled return. **Positive only** filters the selected calculation. Open a quote to see the
prices, fees, model assumptions, and settlement details available for that offer.
[Calculation basis](benchmark-ev.md) · [Trading fee policy](fee-coverage-policy.md)

## Find and compare games

Use **Find my game** or **Browse odds** to navigate by team or game, including
when a comparison lacks enough inputs to show EV. Browse shows aligned venue
columns for each exact outcome. An unavailable quote is shown as a dash. A
saved capture preserves the original price.

The current board shows only eligible prices. Its notice, **Odds may be delayed
up to 15 minutes**, applies to source timestamps or valid book confirmations.
Some feeds and calculations expire sooner. A list refresh does not extend a
quote's life. **Saved odds** preserves earlier observations.

Open a quote to inspect the price, the same-line reference, and the fee and
settlement evidence. The default EV ranks signed before-fee returns, including
negative returns, when the offer and reference support the estimate. Arbitrage
shows allocation percentages and the lowest modeled return for the settlement
states covered. When only decisive outcomes can be modeled, the before-fee
return is labeled accordingly. Amount and fill assumptions for after-fee
calculations are in **Calculation details**.

On **Browse odds**, the separate trade preview can estimate costs for a chosen
amount where the venue evidence supports it. **Auto-update** controls updates
to the current comparison; pausing it does not prevent prices from expiring.
**Trading fees** explains the venue terms. **Source status** shows collection
problems. [Data and freshness limits](market-data-gaps.md)

## Saved odds and diagnostics

While the desk is waiting for its first prices, **Saved odds** and **Source status**
appear above the filters. **Saved odds** opens the recorded captures available on
this installation. Capture time governs the archived price, freshness, and
applicable fee evidence.
[Open a saved capture](development.md#frozen-replay)

**Raw Odds** shows source-local evidence. **Scanner** uses observed depth for
execution sizing and offers manually selected tickets. Predict does not place
orders. **Admin** contains source, coverage, spending, Stop, and settings
controls. **Admin → Database** is a read-only browser for working and retained
relations. [Raw Odds](raw-prices.md) · [Scanner](scanner-usage.md) ·
[Admin access](security.md)
