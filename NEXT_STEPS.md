# Predict next steps

The selected product priority is **My Bets plus opportunity logging**, for both
EV and arb trades. The local implementation preserves original signals, actual
price/stake/fee corrections, quote history, closing comparisons and reported cash
results. See [the journal contract](docs/bet-journal.md). A month of actual use
should separate opportunity discovery, prices obtained, comparable closes and
realized results; missing observations remain missing. Local frozen snapshots
cannot establish ongoing live closing performance. Hosted installation and
operating evidence remain separate from local verification.

The active assignment is the simplified current-row pregame dashboard. The
[shipped contract](docs/current-pregame.md) owns the data flow and API;
[math](docs/benchmark-ev.md), [fees](docs/fee-coverage-policy.md),
[UI](docs/ui-design.md) and [operations](docs/hetzner.md) describe current behavior.

Complete local and hosted verification on the same final candidate: normal
receipt → admission → calculation → complete current row → browser. Verify the
owner's one-second receipt/admission-to-queryable target separately from polling
and browser delivery. Run required CI, clean-package and image/Compose checks,
deploy through the authorized workflow, and verify installed revisions.

Preserve six-league/full-game winner-spread-total scope, source pauses and Stop,
account windows, limits, reservations and unresolved holds. Incomplete references
or genuinely unavailable mandatory fee facts stay internal diagnostic exclusions.
Do not turn a historical coverage target or execution requirement into an
additional dashboard completion gate.

## Backlog

Optional read-only account connections; broader execution/depth and slippage
modeling; automated execution and position-aware settlement; player props/partials;
additional sources and independent probability research. Existing practice,
historical and modeled Arbitrage views retain their separate evidence contracts.
