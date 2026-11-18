# Predict desk

## Current comparison interface

**Opportunities** at `/` and `/ev` opens on the pregame ticketboard using a
$100 maximum upfront commitment, public retail fees, and a decisive completed-game
estimate. The basis is visible before the tickets. Each comparison discloses its
fill and settlement assumptions.
Main-line tickets are ranked by Opportunity Score, which uses modeled win
chance and after-fee payoff. Net EV gives the modeled return per dollar.

**Compare prices** opens the exact published quote and its unit in a desktop
drawer or a full-screen view on mobile. It shows the reference book's original
prices, Predict's no-vig fair odds and the qualified venues in Net EV order.
Indicative offers show the evidence they need. Use **Calculation and
settlement details** to see the outlay, modeled fill or stake, fee timing,
settlement returns, and source clocks.

**Arbitrage** shows both legs and the lowest modeled payoff over the supported
settlement states. The stake budget excludes entry fees and reserves. **Total
cash committed** includes them. Open the calculation for outcomes outside the
model. In-game prices and the Live tab require the `live_enabled` flag, which
is off by default. A game
leaves the pregame list at kickoff or when an earlier authoritative state
change withdraws it.
[Calculation basis](benchmark-ev.md) · [Trading fee policy](fee-coverage-policy.md)

## Find and compare games

Use **Browse odds** to find a game, market, venue, or alternate line. It works
when the board has no qualifying offers. Browse
shows aligned venue columns for each exact outcome. Select **No quote** to
read what Predict knows about the missing price for that venue and line.
Saved and retained prices are labeled when available.

Each Browse card shows the league and scheduled kickoff, including the time
zone, even when its outcomes are collapsed. Use **Open game** to see the
matchup or **Open line** to pin a specific outcome. Swiping across the matrix
leaves the venue filters alone. **Back** restores the Browse filters and
position. If the game or quote has left the results, the desk explains the
change and returns to the closest available results.

The desk says **Odds may be delayed.** Pregame shows the latest published
prices and calculations for eligible games until kickoff. Quote inspection
shows when each price was observed. Live uses separate freshness rules.
**Saved odds** preserves earlier observations.

Open a Browse quote to inspect its posted price, any verified fee, and the
reference, fill, and settlement evidence. The trade preview starts with the
default $100 basis and supports adjusting the amount for that
quote. **Auto-update** controls Browse list updates. **Trading fees** explains
the venue terms. Admin's **Sources** view shows collection problems.
[Data and freshness limits](market-data-gaps.md)

## Saved odds and diagnostics

**Saved odds** opens the recorded captures available on this installation.
Capture time governs the archived price, freshness, and applicable fee evidence.
[Open a saved capture](development.md#frozen-replay)

**Try a practice example** opens labeled fictional offers and opposing legs
without a capture. The practice EV ticket shows its own unit and leaves the
user's saved Opportunities unit available on return.

**Raw Odds** shows source-local evidence. **Scanner** uses observed depth for
execution sizing and offers manually selected tickets. Predict does not place
orders. **Admin** contains source, coverage, spending, Stop, and settings
controls. **Admin → Database** is a read-only browser for working and retained
relations. [Raw Odds](raw-prices.md) · [Scanner](scanner-usage.md) ·
[Admin access](security.md)
