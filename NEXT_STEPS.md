# Predict next steps — 99% coverage and a usable desk

Updated November 11, 2026. This is the execution queue for the existing main
checkout. The Desktop plan summarizes it. The [product contract](docs/live-comparison-plan-20261104.md),
[coverage definitions](docs/broad-coverage.md#next-version-target--bulk-live-data-and-99-coverage)
and [fee policy](docs/fee-coverage-policy.md) own the product and measurement rules.
The [SGO observation report](docs/sgo-paid-observation-20261111.md) holds the dated
implementation and runtime evidence.

## Goal and current gap

Make EV and Arbitrage useful for daily use on this Mac and reproducible on a
clean macOS profile with its own provider access. Keep NFL, NCAAF, NBA, NCAAB,
MLB and NHL full-game winners, spreads and totals, including available alternate
lines. Measure pregame and supported in-game coverage separately. The active
offer sources are native Kalshi and Polymarket US plus SGO-attributed observations
already supported by the desk. Keep source-local SGO Novig and Kalshi observations
distinct from a native contract or book. Keep the current Rookie account and
existing scope controls. Additional P2P venues, including ProphetX expansion,
Matchbook and Betfair Exchange, are backlog work.

SGO is the selected aggregate. The installed sportsbook basis picks the highest
payout on the same outcome and line from FanDuel, DraftKings, BetMGM and Caesars
with a current complete pair, then proportionally de-vigs the selected book's own
pair. It supplies an indicative before-fee result for matching SGO offers.
Exact direct-venue binding, compatible settlement and applicable fees are still
needed for supported native and after-fee results.

The 10:43 p.m. Eastern census had 44 current offers out of 13,689 published,
20 numeric fees, zero numeric EV and zero eligible current arb pairs. A
separate 10:44 p.m. census published 13,023 of 13,055 stored working price keys
and had two current offers. These are observations of separate reads. The
offered-provider denominator remains unmeasured. Kalshi's official schedule
review expired locally and its renewal fetch returned HTTP 429. Polymarket US
standard sports and eligible Novig pregame fee reviews were active.
[Fee review and coverage census](docs/sgo-paid-observation-20261111.md#fee-verification-deadline-and-live-page-coverage-november-11-10431044-pm-eastern)

The post-cleanup 11:01 p.m. read found 24 current offers out of 15,242,
20 numeric fees, zero EV and zero eligible arb pairs. The new setup
and desk changes are loaded. [Cleanup and installed evidence](docs/sgo-paid-observation-20261111.md#cleanup-harness-and-coverage-planning-november-11-1102-pm-eastern)

## How completion is measured

- Enumerate offered price units independently from the output. Identify source,
  venue, event, market, period, side and exact line. Reconcile pagination and
  withdrawals, and record available, unavailable, inaccessible and unsupported
  cohorts. An incomplete or moving inventory has unknown completeness.
- Require at least 99% for raw acquisition, faithful display and freshness against
  the offered denominator, globally and in each nonempty in-scope
  venue/league/family cohort. Report phases separately and keep every received
  item accounted for with an explicit disposition. Use exact integer counts.
- Track numeric fee coverage against all distinct current displayed offers before
  any EV filter. Target 99%. Count documented zero fees and scoped conservative
  estimates. Report applicable evidence gaps by venue, family and phase.
- Measure published EV against independently enumerated eligible offer/reference
  inputs and published arb payoff coverage against eligible opposing two-leg
  inputs. Target at least 99% calculation and publication coverage for each.
  Also report eligible versus offered opportunities and why inputs did not
  qualify. Report before-fee, fee-adjusted and execution-qualified outcomes
  separately. An empty cohort has no percentage. A fully evaluated slate can
  have zero positive opportunities.
- Carry the whole scoped slate through cold catch-up and the existing two-hour
  steady-state verification window, with samples each minute and at completed
  refresh boundaries. Observe normal discovery on its own schedule when due.
  Record actual source and local timing, budgets, missing populations and
  results per view. Document any provider constraint with a measured ceiling
  and a concrete product choice if the target cannot be reached.

## Remaining work

One market-data and trading-economics lead owns the end-to-end result. Each
slice delivers a working part of the same assignment in the existing checkout.
Use the normal launcher and existing authorization. Preserve private settings,
Stop, source pauses, account balances, reservations and unresolved holds.
[Local workflow](AGENTS.md)

### COV-01 · Measure what is offered and where it is lost

**Engineer** Data platform and integration QA.

- Build on the provider listings, retained originals, Coverage, fee census and
  delivery clocks. Produce a synchronized funnel by source, venue, league,
  family and phase from offered units to received, admitted, current, matched,
  fee-covered and published. Give EV and arb separate independent denominators.
- **Start here.** During normal active NBA and NCAAB acquisition, trace bulk
  source listings and timestamped market data through SQL and both pages.
  Establish where current offers and their counterpart legs are lost. Use
  representative exact rows to diagnose each loss, then apply the fixes to
  the full six-league scope in the same assignment.
- **Done** A reproducible sanitized census shows each count, capture and
  completeness boundary, and reason for every measured deficit. Coverage can
  distinguish unavailable, expired, not offered, outside entitlement, awaiting
  publication and insufficient identity. Extend this measurement to every
  active cohort without dropping tails or out-of-policy inputs from the audit.
  [Coverage contract](docs/broad-coverage.md)

### COV-02 · Keep the full slate current within the account budget

**Engineer** Data platform and runtime reliability.

- Compare provider clocks, due times, receipt, admission and first publication.
  Recover unfair native subscription/deferred queues, slow SQL or publication
  turns and unnecessary refresh spend where evidenced. Preserve independent
  native feeds and pace SGO discovery and active/kickoff refresh against one
  reconciled budget. Continue bounded history and protected accounting.
- Exercise resume, rate and budget waits, cursor rejection, reconnect and
  incomplete admission. Resolve uncertain request charges only from independent
  evidence. Keep 00:00 UTC on the first of the month as the provisional pacing
  boundary. Measure source-age limits against real delivery. SGO documents a
  three-minute Rookie update cadence, and the existing live reference gate uses
  15-second post-start clocks. Polling and SQL improvements cannot guarantee
  faster provider updates. [SGO update cadence](https://sportsgameodds.com/blog/sportsgameodds-faq)
- **Done** Whole-slate counters, actual object spend and representative
  source-to-screen time identify residual losses at each stage. Healthy feeds
  publish independently during waits and recoveries. Use measured remaining
  source and entitlement gaps to determine whether the current scope can meet
  the freshness target. [Operations](docs/sportsgameodds-operations-20261110.md)

### COV-03 · Make the EV and arb inputs match exactly

**Engineer** Comparison and trading economics.

- Bind native events and sides to SGO using independently evidenced shared IDs
  or reviewed exact links. Verify league, participants, kickoff and reschedules,
  period, side, signed line, overtime or shootout, tie/push, void and
  cancellation terms. Keep estimated links visible as such.
- Carry the best-payout, same-book de-vig through verified native offers and
  applicable fee calculations. Preserve quote evidence, both sportsbook prices,
  phase and original clocks in the pinned inspection. Keep the vendor fair odds
  labeled separately with its own line and availability.
- Build opposing sets independently of EV references. Reconcile payouts at one
  documented size, including both fees, rounding and all supported settlement
  states. Distinguish an evaluated zero or negative result from missing legs,
  unknown settlement, stale quotes and unavailable depth.
- **Done** Ordinary EV and Arbitrage pages publish and withdraw exact numeric
  results on real eligible cohorts. Independent arithmetic and disposable
  regression cases cover changed lines, times, payouts, fees and the cases that
  would otherwise yield a false match or false profit.
  [Calculation contract](docs/benchmark-ev.md)

### F08A/F09 · Keep fees effective and make missing fees actionable

**Engineer** Venue integration and trading economics.

- Separate provider effective dates, exact-market applicability, local
  verification freshness and observed changes. Repair Kalshi retrieval from
  the official schedule, market and override evidence using an authorized route.
  Specify how applicable standing terms are carried forward while scheduled
  checks run and what evidence invalidates them. Show the last successful
  verification and its status. Preserve frozen historical captures.
- Verify Polymarket US standard sports renewal and its price-range and rounding
  cases. Preserve the eligible Novig pregame policy. For Novig live, obtain the
  signed read access and exact-market terms needed for F03, or quantify the
  affected live fee gap. Use scoped, documented estimates where supported.
- **Done** A routine recheck interruption has a documented, explainable outcome.
  Changed terms, missing exact-market evidence and account overrides are handled
  explicitly. Running fee coverage meets the defined measure, or the census
  quantifies the exact outstanding dependency. [Fee validation](docs/fee-coverage-validation-20261110.md)

### UX-01 · Make first use and daily use understandable

**Engineer** Product frontend and local setup.

- Provide a reproducible clean-profile path on macOS. A user can start in replay
  without credentials, understand its status, then configure their own supported
  read-only sources, account limits, sports, time zone, odds format and default
  EV basis. Validate configuration without exposing secrets or dispatching paid
  collection just to browse. Keep recovery and Stop easy to find.
- Keep EV and Arbitrage focused on offers, prices and a meaningful result or
  one useful explanation. Keep diagnostics and full math in the drawer or
  Admin. Make a filtered-empty page, no current compatible pair, no positive
  result and blocked or stale data distinguishable. Preserve keyboard/focus,
  390px layout, filters, original evidence and explicit Use latest prices.
- **Done** A clean profile and the existing local profile both complete setup,
  find a matchup, inspect a price, compare EV and opposing legs, handle no-data
  or renewal states and recover. Document the supported setup and scope with
  repository-relative instructions. [Setup guide](docs/configuration.md)

### VERIFY-01 · Prove the result on the installed desk

**Engineer** Integration QA with the lead.

- Run the registered targeted fixtures and the supported migration/install checks.
  Integrate on main, verify both owners and use the synchronized full-slate census.
  Observe actual pregame and in-game activity, routine restart and independent
  feed recovery. Verify changed-price adoption and pinned evidence on desktop
  and mobile, including one meaningful EV result and one eligible arb payoff
  wherever the sources supply the inputs.
- **Done** Deliver dated counts and gap reasons, independently reconciled
  calculations, real desktop/mobile journeys and a clean-profile walkthrough.
  Report verified percentages, external constraints and any remaining
  incomplete engineering explicitly. Owner review follows the engineer-led
  result. [Evidence record](docs/sgo-paid-observation-20261111.md)

## Backlog

Additional exchanges and execution venues, Circa or Pinnacle acquisition under
a different entitlement, broader player props/partials, independent probability
research and a hosted or shared-account product. These are separate decisions
from making the existing local EV and Arbitrage desk useful.
