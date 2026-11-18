# Predict desk

## Current comparison interface

Open `/` directly on the ticket board. Each ticket shows game, league, kickoff,
pick and exact line, venue, Posted odds, After fees, Fair odds, Net EV, Opportunity
Score, and Compare prices. The game title opens that game's current comparisons.
Use the general notice **Odds may be delayed.** Source and receipt clocks remain
in fee/calculation details.

The normal interface has no unit-size, calculation-mode or execution-depth
controls, progress states, placeholder quotes or missing-calculation cells. Only
complete qualifying opportunities appear. Empty results are distinct from a failed
read. A failed refresh leaves the rendered board intact.

Search, league, market and venue controls filter the SQL list. Equivalent bets
are grouped before pagination; the best Net EV venue represents each exact bet.
Opportunity Score orders tickets, with unrounded Net EV and stable identity as
ties. Default main lines require positive evidence; unknown and alternate lines
stay outside the default. Browse can include alternate lines, and exact bet and
quote links remain inspectable.

## Find and compare games

`/browse-odds` reads complete calculated bets, including nonpositive EV. Game
links open `/game?game_key=...`. Compare prices reads `bet_id` and shows actual
quoted, complete venues ordered by Net EV. The selected row is copied compactly
so background updates cannot change an inspected calculation. Closing inspection
returns to the current board. Kickoff refreshes remove the game without another
source response.

Desktop tickets use a pricing body and a perforated metric stub. At 390 px the
stub stacks under the bet; controls wrap and minimum touch targets remain 44 px.

## Saved odds and diagnostics

Arbitrage and replay use separate research views. Practice examples are labeled
simulated and do not require provider access. Saved captures preserve their
original evidence. Their modeled execution and settlement details do not impose
eligibility controls on the current pregame board. Admin owns collection controls
and operational failures. Account connections and broader execution modeling
remain backlog work.
