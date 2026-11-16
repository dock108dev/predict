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
Arbitrage cards align each leg's venue and odds and show funding, lowest payout,
and worst profit or loss together. **Positive only** sits beside the calculation
basis it filters. Open a quote to see the
prices, fees, model assumptions, and settlement details available for that offer.
[Calculation basis](benchmark-ev.md) · [Trading fee policy](fee-coverage-policy.md)

## Find and compare games

Use **Find my game** or **Browse odds** to navigate by team or game, including
when a comparison lacks enough inputs to show EV. Browse shows aligned venue
columns for each exact outcome. An unavailable quote is shown as a dash. A
saved capture preserves the original price.

The SportsGameOdds-backed pregame desk keeps the latest posted price until the
source replaces or withdraws it or the game leaves pregame. **Auto-update** is on
by default. It applies updates in place and keeps the open trade preview on the
same selection and stake. With Auto-update off, use **Refresh list** or reload
to read the latest board. The collector runs independently of this choice.

The trade preview starts with a $10 maximum upfront cost and shows the modeled
fee at that size, including when it applies. **Trading fees** explains each
venue's terms. Execution and qualified financial calculations still require
the corresponding current evidence. Saved captures preserve their own fee
terms and calculations. **Source status** links to collection information when
the data worker is stopped or unavailable. [Data and freshness limits](market-data-gaps.md)

American odds are the default. The **Decimal** option changes display formatting
without changing ranking or calculation inputs. On a narrow screen, the
game table keeps the outcome column in place. The button above it moves to
more odds columns. Dialogs support keyboard focus, Escape, and return to the
opening control.

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
