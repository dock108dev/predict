# Data coverage and limitations

The dashboard supports comparisons only when source observations establish the
same event, participants, outcome, period and line. A configured adapter or a
sport handler does not establish current venue coverage, account entitlement,
liquidity or equivalent settlement terms.

## Comparison sources and references

| Source | Implemented role | Limitation |
| --- | --- | --- |
| Kalshi, Polymarket US | Native listing and book adapters | Live use needs scoped configuration, valid authorization and dedicated credentials; actual market availability varies. |
| Novig, ProphetX | Aggregate observations through The Odds API; separate native adapter code | Aggregate observations do not establish native quantity, execution costs or production access to the direct APIs. |
| Pinnacle, DraftKings, BetMGM | Calculation references | Never comparison legs. A bookmaker price is not automatically a calibrated probability. |
| Public Novig GraphQL | Display-only discovery and dated prices | Does not provide qualified purchase depth or sized opportunities. |

Native discovery, aggregate ingestion, references and sporting results retain
separate identities and clocks. No default configuration continuously polls these
sources, and an empty bounded response does not establish permanent non-support.
See [configuration](configuration.md) for live requirements and
[sport integration](sports-integration.md) for implemented market handlers.

## What calculations require

- Raw comparisons require compatible event/outcome/period/line identity and
  usable observed prices. They do not imply contract-equivalent arbitrage.
- Net and guaranteed-return calculations require applicable settlement and cost
  facts. Missing fees, account charges or exceptional payouts remain unknown.
- EV requires an explicit probability and disclosed basis. Retrospective
  references and manual What-if assumptions do not become live model probabilities.
- Sizing requires supported native units and depth. Displayed aggregate sizes or
  informational estimates do not guarantee fills.
- Sporting outcomes do not substitute for venue payout decisions. Corrections
  and final settlement remain bound to their own source evidence and cutoffs.

## Operational limits

Saved observations prove their recorded time only. Source/receipt timestamps,
stale status and disconnected states stay visible. Local replay and synthetic
recovery tests do not establish real provider uptime, recovery or current prices.
No trade submission, order management, position synchronization or automatic
collection restart is implemented. Remote and shared-user deployment are
unsupported. See [security](security.md) and [failure handling](error-handling.md).

The [dated coverage assessment](coverage-matrix.md) preserves source-specific
research and historical counts. It is not a promise of current availability or a
prerequisite for starting the saved-data dashboard.
