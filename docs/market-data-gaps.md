# Data limitations

Implemented adapters and market handlers do not guarantee that a venue currently
lists a sport, event or market. The default current scope is NFL; configuration
also permits NCAAF, NBA, NCAAB, MLB and NHL. Native and aggregate sources have
independent access, timing and availability constraints.

Matched titles are insufficient: participants, event identity, period, line,
outcome orientation and material settlement terms must agree. Raw corresponding
prices can remain useful while net-return or EV calculations are unavailable.

- Quote receipt age, provider source time, socket health and browser connection
  are distinct. A healthy connection does not establish a fresh price.
- Arbitrage percentages describe the displayed gross conditional outcome basis.
  Unknown fees, refunds, exceptional outcomes or depth can prevent net economics.
- Gross benchmark EV uses an exact matched Pinnacle reference; modeled and actual
  net EV have additional probability, cost and payout requirements. Manual inputs
  and retained observations do not automatically establish those dependencies.
- Saved fixtures and synthetic controls establish only their recorded inputs;
  they do not establish present venue coverage.
- The shared aggregate ledger reserves credits and preserves uncertain charges.
  Missing or stale account observations can delay dispatch rather than imply a
  usable balance.

See [calculation basis](benchmark-ev.md), [sport integration](sports-integration.md), [architecture](architecture.md)
and [configuration](configuration.md) for supported paths.
