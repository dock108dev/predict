# Data limitations

The current pipeline accepts six leagues and supported winner, spread, total and
period representations. The default configuration selects NFL. Each calculation
still needs exact applicable contract, quantity, fee, source and model facts;
configuration support cannot guarantee venue listings or usable estimates.
Native and aggregate sources have independent access, timing and availability.

- Titles alone cannot establish a match. Participants, event identity, period,
  line, orientation and material settlement terms must agree. Sporting identity
  and payout identity remain separate.
- Original quote time, receipt time, socket health and browser connection are
  distinct. Persistence, replay and recalculation do not renew quote freshness.
- A benchmark uses both original outcomes from the selected sportsbook. Missing,
  crossed or stale originals withhold dependent EV rather than substitute a book.
- Modeled fees, payout recipes, quantity grids and provisional tie/noncompletion
  probabilities are explicit assumptions. Content has bounded effective intervals
  and expiry in `app/fixtures/estimated-content-v1.json`; strictly bound profiles
  and `app/comparison/modeled_winner.py` have separate applicability checks. The
  legacy recipes retain their October 16, 2026 expiry. The Novig NFLWIN revision-2
  model ends October 29 at 00:00 UTC (October 28 at 20:00 Eastern). None is a
  continuously refreshed terms feed. Expired or unmatched content refuses
  affected estimates while preserving authentic original prices.
- Native NO and Short retain their original predicates and collateral requirements.
  Unsupported Short collateral, unknown depth or exceptional payouts can withhold
  calculations even when the original numerical price is visible.
- Conditional EV and decisive opposing margin do not establish profit in every
  modeled state. Actual fills, grades and additional account charges remain unknown.
- Empty source responses describe that request, not universal non-support. Fixtures
  describe their authored or retained inputs, not present coverage.
- The aggregate ledger preserves unresolved exposure. Missing account evidence can
  block dispatch instead of implying a usable balance.

The app has no order execution, cloud deployment or universal sport/market model.
Current sports rows expire automatically; separately retained research packages
have no automatic pruning. See [calculations](benchmark-ev.md),
[sport handlers](sports-integration.md), [architecture](architecture.md) and
[operation](configuration.md).
