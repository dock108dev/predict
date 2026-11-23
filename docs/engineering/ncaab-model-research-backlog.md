# NCAAB model research backlog

Status: deferred backlog, recorded November 22, 2026. Phase 2 engineering is complete. This plan does not enable feeds, backfills, subscriptions, schema changes or model-based rankings. See the [phase 2 completion record](phase2-20261122/queue.md).

## Goal and first deliverable

Determine whether the owner's NCAAB models improve probability estimates and whether those improvements identify useful opportunities through accessible markets. Correct arithmetic, model accuracy and trading returns are separate findings. Start with a few useful sources and make more easy to add.

The first deliverable is a reproducible report joining **saved pregame forecasts to NCAAB game logs**, comparing each model, the existing market reference and a simple combined estimate. A plain inspection table is sufficient.

## Foundation and budget

Reuse the collector, canonical event/contract identities, original receipts, frozen calculations, research outcomes, exact inspection and offline export. Preserve the selected :20/:50 discovery and first-observation/T−10 policy, passive browser reads, Stop, source pauses and account/quota/reservation/hold guards.

The working envelope is $50/week including $30/week SGO. Reconcile hosting and other existing costs before treating the nominal $20 remainder as available. Inventory subscriptions already owned before selecting new spend. Research is capped at 128 MiB; the November 22, 8:13:50 PM Eastern installed observation had 10,225,788 unreserved bytes. Physical disk is a separate limit. Size this expansion before activation without consuming protected late reservations, deleting unique evidence or silently raising caps.

## 1 Inventory sources and access

For each source record current-season coverage, account/access method, native outputs, update cadence, historical/as-of availability, source timestamps, incremental requests/cost and dependencies on other models or market prices. Website subscriptions and API access may differ.

| Candidate | First question |
| --- | --- |
| KenPom | What ratings, archives and matchup predictions are available through the existing account's API/export/web access? |
| Nate Silver / Silver Bulletin COOPER | Are current-season NCAAB predictions available with usable update times and historical snapshots? |
| Sagarin | Is there a current-season feed? The public page inspected during planning held final 2022–23 ratings; retrieval time does not establish freshness. |
| Other NCAAB models already owned | Does the source add information or coverage beyond the initial models? |
| DataGolf | Retain as a future golf candidate, outside the NCAAB blend. |

Use structured APIs/exports where available. Firecrawl is an extraction option for useful authenticated tables. Validate access and output with a bounded sample. Preserve the original artifact, parsed values and publication/collection times; check numeric extraction against the source. Reuse shared ratings across games and books, fetching a new version when the source updates. Set freshness deliberately: Firecrawl's documented default cache can return older pages. A T−10 fetch is not automatically a T−10 model update.

Deliver a source matrix with one traceable sample per selected source and explicit available, stale, missing and unsupported states.

## 2 Establish NCAAB game logs

Game logs are required for accuracy. Final outcomes provide scoring labels; earlier game statistics can provide historical inputs for calibration or future models. A later final score is a valid label, but later-revised ratings or statistics cannot be backdated into an earlier forecast.

Audit the existing bounded final-team-score/result adapter first. Outcomes for retained research games do not establish comprehensive NCAAB historical coverage. Choose the smallest source extension needed for the declared evaluation games.

Minimum records:

- Canonical/provider game and team IDs, competition, season, home/away teams, venue/home/neutral status, scheduled start and schedule revisions. Resolve aliases explicitly; similarly named schools and men's/women's competitions stay distinct.
- Status, final team scores, margin and total; period, regulation and overtime scores where supplied. Mark missing detail when a contract cannot be settled from the result. Preserve cancellations and postponements.
- Source publication/update time when known, our first observation and recording times, original artifact/hash, result revision and append-only corrections. Deduplicate games across sources and reschedules.

Add team box-score logs where available: possessions/tempo, shooting attempts/makes, free throws, rebounds and turnovers. Separate reported values from documented, versioned derivations. Player logs, injuries/lineups and play-by-play are later depth; they need not block initial team-model accuracy.

Deliver a declared game population with matched result revisions, coverage counts and missing/conflicting/unresolved cases. Distinguish actual sourced history from fixtures. Historical forecasts without reliable as-of provenance cannot support prospective accuracy claims.

## 3 Freeze forecasts and derive supported probabilities

Save each source's actual forecast at first observation and T−10 with its update time, our observation time, original artifact, canonical matchup/site, units and model/calibration version. Keep native forecasts, derived probabilities, the conservative screen and coherent market reference separately named. New models must not replace historical calculations.

Native win probabilities can support moneyline scoring. Rankings, expected margins and projected scores do not alone establish spread/total probabilities. Fit margin/total error distributions on earlier games and validate on later games. Integer lines require win/loss/push probabilities; probabilities must sum to one under the supported contract rules. Unsupported alternate tails remain unavailable rather than extrapolated without evidence.

Preserve provider/book, exact side/points, period, overtime and settlement rules. Track each book's changing main designation while −4.5 and −5.5 remain different bets. Retain alternate quotes for supported cross-line evaluation and plots without claiming a model probability for every line.

## 4 Measure accuracy before learning ensemble weights

Declare eligible games and chronological training/validation/test periods before selecting opportunities. Fit weights, recalibration and error distributions only on earlier data; score untouched later games. Handle season transitions and version each fitted model and data cutoff.

Retain compact prediction/result records for every sampled game, including negative/negative EV and missing-source cases. Detailed opportunity records can keep the existing positive-at-either-checkpoint rule. This neutral population supports calibration and identifies bets positive under a new model but omitted by today's screen. Size the additional retention before activation.

Compare individual models, a simple combination of compatible estimates and the coherent market-reference baseline on identical games and information cutoffs. Report common-coverage comparisons alongside full-population coverage. Examine shared inputs and correlated errors; agreement is not automatically independent evidence. Learn a more complex blend only when later-game evaluation supports it.

| Question | Measurements |
| --- | --- |
| Win probability quality | Brier score, log loss and calibration bins with observed win frequency, game counts and uncertainty; hit rate is supplementary. |
| Score, margin and total accuracy | Margin/total MAE and RMSE; team-score error where the source supports it. |
| Spread/total probability quality | Probability scores and calibration with push handling, using supported native or validated derived distributions. |
| Does combining models help? | Held-out differences versus individual models and the market baseline, with coverage and uncertainty. |

Treat games as the dependent sampling units: many books, sides, checkpoints and alternate lines are not independent predictive wins. Report exclusions and missing forecasts/results. Later result corrections produce revised evaluations.

## 5 Assess obtainable opportunities

Use the existing exact fee/cashflow engine for supported contracts. Show game, book, side/line/price, each model's estimate, combination, market reference, source age, calculated EV and eventual result. Keep measured accuracy alongside estimates rather than labelling them true odds.

Separate quoted opportunities, paper returns, closing-price comparison, executable capacity, actual fills and realized returns. Assess credible edge, costs, opportunity frequency, usable stake capacity and uncertainty together. Closing-price improvement is supporting evidence, not proof of profit or calibration. Automated betting and profit thresholds are outside this backlog's engineering acceptance.

## Acceptance for a selected implementation

- Trace a real NCAAB forecast and game log through source, identity, as-of prediction, result revision and offline scoring.
- Account for every eligible evaluation game, including missing/nonpositive cases, and reproduce the common comparison population.
- Check probability scores, margin/total errors, cashflows and supported push behavior against independent examples. Verify that future information cannot enter an earlier forecast.
- Reproduce individual and simple combined results from exports, with game counts, uncertainty and unsupported coverage visible.
- Measure storage/request costs within selected allocations and existing guards; inspection makes no acquisition calls. Disabling a model preserves its evidence.
- Use focused checks for changed owners and the two-minute private-beta pipeline; add no broad public-user journeys or removal-only tests.

## References

- [KenPom API](https://kenpom.com/api-documentation.php)
- [COOPER methodology](https://www.natesilver.net/p/introducing-cooper-silver-bulletins)
- [Sagarin basketball](https://sagarin.com/sports/cbsend.htm)
- [Firecrawl scrape and freshness](https://docs.firecrawl.dev/features/scrape)
- [Current checkpoint policy](../ev-checkpoint-experiment.md)
- [Research operations](phase2-20261122/research.md)

