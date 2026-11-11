# SportsGameOdds free-tier evaluation and future options

November 10, 2026 · Planning only · Owner: market data and trading economics engineer

## Assessment outcome

The engineering comparison is complete: [pivot assessment](sportsgameodds-pivot-decision-20261110.md). The owner confirmed the previously identified coverage, replacement-reference and useful-schedule questions affirmatively, so the revised recommendation is to pivot. Subscription and production cutover remain owner decisions; the plan below preserves the evaluation context.

## Updated direction after the initial sample

**Owner decision:** Always retain the direct Kalshi and Polymarket US
implementations. An aggregate feed may complement them for comparison, audit,
market discovery and other data uses; evaluating it is not an investigation into
retiring those direct connections.

**Decision under evaluation:** Pivot now or run the existing system live for
a while before reconsidering. A paid SportsGameOdds pivot replaces The Odds API
and therefore the Pinnacle feed obtained through it. Assess a viable replacement
reference and the broader paid-tier sportsbook and P2P data for EV tuning, as
well as migration effort, freshness, cost and object limits. Actual paid-plan
coverage must be verified. A period of live operation is an option, not an
invented prerequisite or mandatory waiting period.

The owner clarified that the primary question is whether SportsGameOdds would
make the large datasets Predict needs cleaner and easier to collect, integrate,
operate and use. The provider's fair-odds field is a useful independent
comparison and baseline alongside whatever estimate Predict ultimately uses;
establishing which probability estimate is most accurate is not the immediate
objective. The initial sample and its arithmetic remain useful evidence, not a
requirement to conduct an extended prediction-accuracy study before assessing
the provider. [Initial evaluation](sportsgameodds-free-evaluation-20261110.md)

### Next engineering evaluation

**Database and common-format comparison:** Trace the actual database owners,
tables, indexes, writes, reads, retention and cleanup used by the current
aggregate and retained native pipelines. Compare a concrete SportsGameOdds
design where games and multiple books arrive in one schema: identify joins,
identity mappings, duplicated records, write amplification, processing queues
and maintenance that could realistically disappear or shrink, and what new
payload, indexing, storage or migration costs could appear. Assess the impact
on throughput, latency, disk growth and recovery with existing evidence and
representative disposable replay or synthetic fixtures where useful. Distinguish
measured results from projections and paid-tier unknowns. Show which independent
native stores, market/contract matching, provenance, original timestamps,
availability, fees, settlement and depth remain necessary. A shared schema does
not by itself guarantee identical contracts or eliminate database persistence.
Include a side-by-side current/proposed flow and practical migration approach;
preserve existing data and avoid a production migration during this evaluation.

1. Trace the current The Odds API path from collection through normalization,
   matching, storage and publication. Identify concrete complexity and operating
   costs, including repeated requests, source-specific mapping, retention,
   freshness and accounting. Distinguish unavoidable product requirements from
   provider-specific code; do not count lines of code as the outcome.
2. Using the existing free captures and suitably bounded additional free samples
   if needed, inspect the SportsGameOdds event and odds structure, batching,
   pagination, alternate lines, IDs, book coverage, timestamps and availability.
   Assess payload size, parsing, memory, storage, update behavior and failure
   handling at the scale required. Clearly distinguish direct measurements,
   extrapolations and unknown paid-tier behavior. Use disposable synthetic or
   replayed scale fixtures where useful, without presenting them as live coverage.
3. Map the same six leagues and three families through both source designs.
   Identify what the unified feed could remove or simplify, what adapters and
   matching would still be needed, and what remains dependent on native Kalshi
   and Polymarket US feeds for depth, audit, contract semantics or freshness.
   Assess the potential of paid-tier P2P venues and US sportsbooks as a much
   broader dataset for comparing and tuning EV references. The provider lists
   many such venues, but actual paid-plan coverage, availability and usable
   markets must be verified; do not assume every P2P venue is covered. Preserve
   venue-specific financial and settlement correctness.
4. Model realistic schedules and costs from observed slate sizes and object
   accounting, including 28–31 day months, reserve, mixed cadences and bursts.
   Compare current The Odds API usage units and actual account terms separately;
   do not claim savings, five-times-faster coverage or a viable Rookie schedule
   without evidence. Record tradeoffs and the questions a paid trial could resolve.
5. Show where the vendor's fair-odds field and its line, availability and clock
   limitations fit as a clearly attributed comparison. If recommending a pivot,
   propose a viable replacement for the departing Pinnacle reference without
   silently substituting it. Reuse initial Pinnacle
   examples; further model calibration and longitudinal outcome research are
   optional later work, not a gate for evaluating data engineering simplicity.

Deliver a practical side-by-side assessment and a concrete proposed integration
shape: likely code and operational simplifications, remaining complexity,
coverage and performance evidence, budget scenarios, risks, unknowns and a
recommendation. Build a small local prototype or focused tests when they answer
the engineering question; preserve existing behavior and free quota. A paid
subscription, production source cutover and broader venue rollout remain later
decisions. Preserve the earlier sections below as the original experiment's
context; this updated direction governs the next evaluation.

## Original experiment: goal and scope

Use the owner's free SportsGameOdds account to explore bookmaker prices and
develop and assess a defensible fair-odds estimate alongside the existing
Pinnacle reference. Answer whether the feed and estimate improve Predict enough
to justify a later paid subscription. Pinnacle is a comparison baseline, not a
required permanent reference or the only acceptable definition of fair odds.
Do not treat this plan as a decision to buy a plan, replace The Odds API, add
production venues, change the live benchmark, or remove native feeds.

The existing fee-coverage validation
remains open and its paused work and evidence remain in [NEXT_STEPS](../NEXT_STEPS.md).
Use the sole existing checkout and preserve Stops, source pauses, settings,
credentials and all account, quota and hold records. Existing authorized The
Odds API operation continues under its own guards. Avoid new paid collection
solely for this experiment; use existing current or recorded Pinnacle data first.

## What is known and what needs measurement

- The vendor lists Amateur at 2,500 objects/month, 10 requests/minute, a
  10-minute update frequency, eight leagues and nine bookmakers. Its published
  list does not include Pinnacle, Circa or the P2P venues of interest. Confirm
  the account's actual entitlement and returned fields; a free paid-tier trial
  must not be silently treated as the free plan.
- One returned event is an object on each request; even an empty response has a
  minimum charge. Query batching lowers requests, not objects. Check account
  usage and reset behavior; rate limits can vary by account. [Limits](https://sportsgameodds.com/docs/info/rate-limiting)
- On November 10 at approximately 3:30 p.m. Eastern, the existing six-league
  aggregate responses held 187 games, of which 111 began within 72 hours.
  At 56 refreshes/day and a constant 30-day slate, these imply 314,160 and
  186,480 returned objects respectively. This is a scenario using The Odds API
  event counts, not observed SportsGameOdds usage or a monthly projection.
  A 100,000-object Rookie allowance permits about 59.5 events per refresh on
  that schedule before other calls. Three-minute updates need five times as many
  objects for the same returned slate.
- Rookie is advertised as 100,000 objects/month and three-minute updates. The
  vendor has described $99/month billed annually and $149 month-to-month;
  confirm checkout, commitment, trial and tax before any later decision.
  [Pricing](https://sportsgameodds.com/pricing) ·
  [Vendor pricing comparison](https://sportsgameodds.com/blog/7-sport-betting-odds-api-providers)
- SportsGameOdds documents a regression/median, margin-removed consensus, with
  `fairOddsAvailable` and a potentially different fair line. Its contributor
  composition and exact matching for each outcome require investigation; do
  not assume it is independent of the offer under evaluation or calibrated.
  [Consensus methodology](https://sportsgameodds.com/docs/info/consensus-odds)

## SGO-01 · Establish free access and inspect actual data

1. Use the owner's provided test key privately from the conversation or an
   existing protected credential mechanism. Do not put it in source, docs,
   committed fixtures, shell history, URLs in logs, screenshots or reports.
   Prefer the `x-api-key` header. Check plan, available usage and reset before
   collecting. Record nonsecret entitlement and usage only. If the key is no
   longer available, request it through a private credential path; do not invent it.
2. Start with a few selected active NBA and/or other available games, not a
   scheduled six-league sweep. Use `/v2/events` with supported league, event,
   market, time and pagination filters verified against the current endpoint
   documentation. Track objects before and after, response pagination, empty
   responses, update clocks and payload size. Cache each response and reuse it.
   Stay inside the account's actual free quota and rate limits, with enough
   headroom for a useful comparison; stop and report quota or authorization
   problems instead of retrying aggressively.
3. Inventory actual available bookmakers, games and both sides of full-game
   winner, spread and total markets. Record market line, source update time,
   availability, fair odds/line and whether the free plan exposes those fields.
   Verify differences between advertised coverage and returned data. Include
   in-game samples when available; an absence is a finding, not a fabricated value.

Reference: [Quickstart](https://sportsgameodds.com/docs/basics/quickstart),
[events endpoint](https://sportsgameodds.com/docs/endpoints/getEvents),
[odds structure](https://sportsgameodds.com/docs/data-types/odds), and the
owner-provided API reference. The reference describes `data`, `nextCursor`,
`oddID`, `byBookmaker` and `includeAltLines`; verify exact schema and current
parameters in official docs before implementing.

## SGO-02 · Compare fair-odds candidates against Pinnacle

Use timestamped observations of the same game, exact outcome, line, phase,
period and settlement meaning. Align observations in time and display each
source's original clock and age; do not imply simultaneous prices where they
were not. The app currently uses a two-sided, proportional no-vig named
benchmark; its decisive conditional probabilities and settlement limitations
are documented in [benchmark EV](benchmark-ev.md#named-benchmark).

Compare at least: (1) existing Pinnacle pair and no-vig probability, (2)
SportsGameOdds fair odds when available and directly comparable, (3) an
independently calculated no-vig estimate from available two-sided books, and
(4) a transparent multi-book median or other simple candidate. Evaluate
additional reputable books if actually available, but do not call a book sharp
solely because of its name or location. Show available contributors, sample
size, missing or stale sides, vig method, spread/total line and differences in
probability points and resulting illustrative EV. Consider leave-one-out
estimates to prevent an evaluated venue from influencing its own benchmark.

Keep estimates and raw prices separate. Reject mismatched lines, ambiguous
contracts, insufficient or stale inputs and incompatible settlement; flag
fallbacks explicitly. Test reproducible arithmetic and representative missing,
stale, outlier and differing-line cases with disposable fixtures. Inspect real
examples, disagreement and coverage; do not equate agreement with Pinnacle
with truth. Preserve raw nonsecret snapshots and enough provenance to reproduce
results. Over time, assess closing-line comparisons and settled outcomes with
appropriate samples; do not promise better accuracy from elapsed time alone.
Free-plan history limitations may require collecting observations prospectively.

## SGO-03 · Report findings and prepare the decision

Provide a compact, reviewable report of available books and markets, usage,
matched-sample size and exclusions, timestamp differences, fair-odds and EV
comparisons, examples, limitations, and any reproducible failures. Include an
evidence-based recommendation: continue free experimentation, evaluate Rookie,
or retain the existing source. Free-plan coverage cannot establish Rookie's
P2P coverage, freshness or access to particular sharp books. Do not make paid
subscription or migration contingent on arbitrary targets; present tradeoffs
and remaining uncertainty.

## Later, if a paid plan is chosen

- Confirm account price, annual versus monthly billing, terms, P2P and bookmaker
  entitlements, Polymarket US identity, event/market coverage, timestamps,
  executable side, price precision, contract rules and available depth. Listing
  a venue alone does not establish useful or complete live coverage.
- Use measured event returns and real slate variation to model daily and monthly
  objects, reserves, 28–31 day months and bursts. Design a budget-aware schedule
  that prioritizes live and imminent games, refreshes distant games less often,
  avoids duplicate event fetches and respects Stop, pauses, quota and 429s.
  Measure the tradeoff between coverage, price age and object use. Do not assume
  three-minute access implies every game can be refreshed every three minutes.
- Compare acquisition, reliability, ongoing cost and coverage against the
  existing The Odds API; validate migration in parallel before any cutover.
  Design support for more venues with venue-specific fees, settlement, matching
  and sizing. Evaluate native Kalshi and Polymarket US feeds as audit/reference,
  execution-depth or reconciliation sources, including discrepancies and source
  clocks. Both direct connections are permanent parts of the intended design.
- Any eventual production integration must preserve live financial semantics,
  source provenance and user controls; no unsupported inference from a vendor
  fair price or rounded top-of-book quote should be promoted to executable EV.

## Handoff

The initial SGO-01 through SGO-03 sample is recorded in the evaluation report.
Continue with the updated engineering evaluation above. Report genuine access,
quota or missing-data limitations; keep paid subscription, production source
replacement and expanded P2P integration as later owner decisions.
