# Predict next steps — Pregame Opportunities

Deliver a daily-use pregame desk on the existing `main` checkout and a
reproducible clean macOS setup. Cover NFL, NCAAF, NBA, NCAAB, MLB and NHL
full-game winners, spreads and totals, including available alternate lines.
Apply the 99% targets in the [coverage contract](docs/broad-coverage.md).
Keep explicit Stop and source pauses, account limits, reserves, and unresolved
holds. [Product contract](docs/live-comparison-plan-20261104.md) ·
[Local workflow](AGENTS.md)

The [pregame checkpoint](docs/pregame-checkpoint-20261112.md) records the installed
EV and arb witnesses, the Washington–Giants event census, and the cleanup.
The broader product assignment remains paused for the data-architecture
discussion. The complete Washington–Giants audit found 34 of 231 offered
sides on the active connections and 8 current on the desk. The full-slate
offered denominator remains unknown.

## Remaining work

### COV-01 · Measure what is offered and where it is lost

**Engineer:** Data platform and integration QA.

Enumerate independent native and aggregate inventories by league, family,
venue, period and exact side. Reconcile acquired, admitted, current,
displayed and priced-with-fee counts with synchronized clocks. Record
discovery completeness, pagination boundaries, roster exclusions and
working-to-desk delay. Aggregate paid inventories depend on resolution of
the interrupted request. Keep incomplete cohorts unknown. Deliver the
per-cohort coverage record with explicit reasons for residual gaps.

### COV-02 · Keep the full slate current within the account budget

**Engineer:** Runtime reliability and provider integration.

Measure native roster rotation, source-clock freshness and working-to-desk
delivery under representative load. Use the findings to improve where the
local roster or publication is the bottleneck. Measure the existing public
main-line poll and the guarded SGO priority cadence independently.
SGO needs an attributable charge or zero-charge record for its two held
objects before paid polls can resume. Preserve the monthly pacing boundary
at 00:00 UTC on the first and the existing spending guards. Verify expiry,
replacement, cold catch-up, independent reconnect and naturally due
discovery. Deliver clocks and measured coverage through the ordinary desk.
[Operations](docs/sportsgameodds-operations-20261110.md)

### COV-03 · Make the EV and arb inputs match exactly

**Engineer:** Comparison and trading economics.

Trace eligible full-game EV through exact occurrence, predicate, signed line,
sportsbook jurisdiction and applicable rules. Verify overtime, tie, push,
void and cancellation treatment with authoritative evidence. Where evidence
is missing, retain the ordinary price and a specific reason. Independently
reconcile reference pairs and the exact two-leg arb populations, including
whole claims, fees, all evidenced states and execution depth. Deliver
published numerators and eligible denominators for each calculation basis.
[Calculation contract](docs/benchmark-ev.md)

### F08A/F09 · Keep fees effective and make missing fees actionable

**Engineer:** Venue integration and trading economics.

Measure numeric fees on all current displayed offers by venue, league and
family. Verify recheck interruption, effective changes and scoped
exceptions for Kalshi, Polymarket US standard sports, and eligible Novig
pregame. Where the 99% target falls short, record the exact uncovered cohort
and missing evidence. [Fee policy](docs/fee-coverage-policy.md) ·
[Fee validation](docs/fee-coverage-validation-20261110.md)

### UX-01 · Make first use and daily use understandable

**Engineer:** Product frontend and local setup.

Recheck the installed journey on desktop and 390px after the data changes.
Exercise Find my game, both rankings, an alternate exact line, return
navigation, pinned inspection, coherent replacement, and clean-profile
practice. Verify the retained Detroit–Washington Over 205.5 explanation
alongside ordinary current data when present. Deliver dated screenshots
that label current, retained and fixture evidence.

### VERIFY-01 · Prove the result on the installed desk

**Engineer:** Integration QA with the engineering lead.

Integrate on `main` and verify both running processes. Observe representative
polls and a kickoff boundary. Independently reproduce a current before-fee
estimate and modeled arb payoff in the UI when qualifying inputs appear.
Run affected calculation, SQL, browser and package checks. Report exact
99% results against each applicable denominator, the observation window,
and any external dependencies. Owner review follows engineering verification.

## Backlog

Live calculation and coverage expansion, additional exchanges and execution
venues, Circa or Pinnacle acquisition under
a different entitlement, broader player props/partials, independent probability
research and a hosted or shared-account product. These are separate decisions
from making the existing local EV and Arbitrage desk useful.
