# Predict — current Beta/V1 and V2 scope

**Current beta coverage acceptance — October 1 owner decision:** at least **48/63** exact eligible valid retained price pairs (76.19%), fixed denominator; 51/63 optional if straightforward. All four comparison venues must continue contributing useful comparisons. Sport/family/period distribution and separate freshness/runtime qualification remain visible. Once this gate and the ordinary V1 workflow pass, close beta coverage and carry remaining cells as visible post-beta limitations. Metadata, reference-only prices and synthetic fixtures never count. No collection authority changes. [Acceptance accounting and backlog](beta-coverage-acceptance.md). This decision supersedes older statements requiring all 63 before beta. Economics remains optional for dependent calculations; automated execution is V2.


Updated October 1, 2026. **Beta/V1: data ingestion and comparison for manual trading. V2: automated trading and execution.** The owner will place trades manually initially. Full V1 coverage/data qualification remains open; no beta signoff is claimed. [Current tracker](../../prediction_arb_next_steps.md) · [every remaining gate reconciled](full-scope-engineering-reconciliation.md).

## Beta/V1 completion contract

- Reliable data pulls and independent updates from Kalshi, Polymarket US, Novig and ProphetX. Kalshi/US use existing native integrations; Novig/ProphetX use existing aggregate observations without native trading access.
- Correct event, outcome, period and line matching across NFL, NBA, MLB, NHL, NCAAF and men’s Division I NCAAB and 63 required cells: full-game W/S/T (18), football/basketball pregame H1 W/S/T (12), MLB cumulative F3/F5/F6/regulation9 W/S/T (12), NHL individual P1/P2/P3 W/S/T (9), current-season conference/league championships (12). Exact participants, season/stage, game number and award predicates apply where necessary. All venues need not list all cells; useful actual overlap is required, and exclusions/seasonal deferrals need explicit owner agreement.
- Useful price comparisons, honest source and receipt timestamps, stale-data handling and source health. Source data timing/recovery matters for manual decisions; automated order-path timing is V2. Keep the existing freshness safeguards and accepted readable layout; no performance project without a concrete data problem.
- Clear differences in settlement terms and supported fee estimates. Show effective public fee versions, ranges/assumptions and unknowns. Incompatible contracts may have useful price comparisons when their differences are explicit; unknown outcome/period/line identity cannot be presented as a valid match.
- Details, filters, informational watches, explicit Start/Stop, history, downloads and exact reopening at the original cutoff. Watches never submit trades.
- Informational depth/sizing where supported, with cutoff, native units, quantity domain, cost assumptions and limitations. Visible depth is not a promise of fills or guaranteed execution. Unsupported sizing is withheld without suppressing valid raw prices.

Pinnacle, DraftKings and BetMGM remain optional reference-only sources, never comparison/trading legs. Models, sportsbook-derived estimates, manual scenarios and historical research retain separate labels. Preserve the EV%-first preference where supported EV exists; absent inputs leave EV unavailable, while valid raw comparisons remain usable. Guaranteed arbitrage, complete net economics, an EV model, profitable opportunities and actual account activity are not universal V1 gates.

## Calculation-specific inputs

Account classification, private/program rates, actual fills/positions, execution-specific charges, fractional scales and complete settlement cashflows are required only if a particular displayed calculation depends on them. Withhold or label that calculation and explain the missing input; keep otherwise valid comparisons, Details and lifecycle usable. Explicit hypothetical allocations/fills/positions remain supported scenario inputs and need no actual trade or account export. Unknown costs or incompatible contracts cannot support a guaranteed-profit claim.

The account-document request is **stopped as a prerequisite** and preserved solely as [optional calculation qualification or V2 work](source-dependent-external-facts.md). No response or broad account access is requested.

## V2 — deferred

Automated order submission, execution orchestration, fills/positions synchronization, execution reconciliation and automated-trading timing qualification are outside Beta/V1. Direct Novig/ProphetX trading integrations remain deferred. Preserve existing implementation, decoders, tests and evidence; do not delete or requalify them merely to change scope.

## Current completion boundary and next work

No remaining reproduced defect exists in the October 1 verified supported paths. Completed math, transport, lifecycle, replay and accepted layout remain closed unless a concrete failure is found. Full six-sport/63-cell actual comparable coverage still has exact listing/locator/identity gaps; historical/offline evidence remains distinct from current provider evidence. Resolve these data/matching gaps through existing bindings, keeping unsupported offerings explicit. The [reconciliation](full-scope-engineering-reconciliation.md) splits all 15 fact categories referenced by the 252 source cells into V1, dependent calculations and V2.

Owner walkthroughs and commercial validation remain deferred. Existing historical approvals and consumed attempts are preserved; no new collection, acquisition package, credentials, outreach, trading or recurring run is authorized by this documentation update.

---

## Preserved earlier product definitions — superseded by the scope above

# Predict — beta product definition

Updated September 29, 2026. **NOT READY FOR BETA SIGNOFF.** This document owns current product scope; [delivery plan](data-coverage-plan.md) describes engineering order and implementation status. Older implementation reports are evidence for their recorded work, not competing roadmaps.

## First priority — engineering for paid usefulness

September 29 owner update: complete [E1–E5](commercial-value-engineering.md) before another general owner walkthrough or fresh live qualification attempt. Deliver understandable comparability/economics, intended-size comparisons using existing fee/depth code, saved watchlists with in-app signals, and auditable opportunity history, then verify the integrated ordinary-app workflow. Status: planned, not implemented by this documentation update. Engineering completion does not prove profitable opportunities or customer demand.

The September 28 two-venue supervised session already demonstrated four games/eight comparisons, ordinary Stop, event links and saved reopening; the [Desktop tracker](../../prediction_arb_next_steps.md) retains exact results. The earlier description of this experience as merely planned is superseded. Settlement/economics, real recovery and full beta qualification remain open. Preserve the accepted readable comparison experience and the existing all-four/six-sport scope below. Missing Novig/ProphetX evidence or optional models must not block independent local engineering. Further Kalshi/US outreach remains withdrawn; this update starts no collection.

## Product goal

A personal read-only sports prediction-market dashboard: compare real purchasable prices across venues, inspect fee/size/settlement-aware arbitrage and model/reference-based EV, understand missing coverage, and return to saved observations. The core is all four real prediction-market feeds and supported related math. Analytics/models and bookmaker lines are extra review data only if easily available; their absence does not block beta. Useful breadth and ordinary operation are the beta goal. No profitability quota, automated trading or generic production-hardening program.

## Opportunity-card experience — resolved owner feedback

The landing experience is an automatically populated simple card feed ranked highest **EV%** first. EV% replaces dollar-profit emphasis. Keep game, sport and market filters accessible; scan configuration, contracts-per-leg and saved-session selection belong in secondary controls or Details. The ranking preference is resolved; do not ask again.

EV% uses expected net profit divided by money committed including applicable entry costs, with the calculation's size, depth and fees preserved. Disclose denominator, evaluated size, rounding and limitations in Details. Missing probabilities or material costs mean unavailable EV, never an invented value or zero. Keep sourced model EV, manual **What-if EV%**, delayed Pinnacle estimates and **Arbitrage return %** distinct; arbitrage return is not an EV substitute. Do not mix these into an unlabeled ranking. Negative and zero results remain valid, and unavailable rows carry reasons without a numeric rank.

The delivered feed uses **100% real data from all four selected venues**. A visibly labeled isolated simulation is only a temporary formative card review aid, never source qualification or beta acceptance. Automatically appearing cards do not authorize automatic collection, recurring jobs or use of an old consumed allowance. [Consolidated engineering package](data-coverage-plan.md#presentation-and-workflow-package).

Keep the EV%-first preference wherever supported EV exists. Without a supported probability, show EV unavailable; continue showing valid price comparisons and fee/size/depth/settlement-aware arbitrage return under its own label. Never relabel arbitrage return or implied probability as model EV, and do not require external analytics to populate the core feed.

## Confirmed beta scope

| Dimension | Required scope |
|---|---|
| Prediction venues | All four selected venues: Kalshi, Polymarket US, Novig and ProphetX |
| Optional analytics/model data | Extra owner-review data only if easily available; not required beta coverage |
| Optional bookmaker lines | Including free delayed Pinnacle, only if easily available; not a beta gate |
| Sports | NFL, NBA, MLB, NHL, NCAAF, NCAAB |
| Markets | Win/loss, spreads, totals, pregame first-half winner/spread/total, futures |
| Core timing | Current pregame prediction prices; explicitly delayed Pinnacle reference; dated model outputs |
| Stretch | Second-half markets offered at halftime and live/in-play; not beta requirements |

Polymarket means Polymarket US in the existing product; international Polymarket is not interchangeable. ProphetX is owner-selected for slot four as of September 21; selection does not qualify its production access. Any substitution or exclusion requires explicit owner agreement; no selection decision is open.

The model reference and Pinnacle have different roles. A strength rating alone is not a moneyline probability, spread distribution, total or futures probability. Where conversion is needed, specify and validate the method, input dates and limitations. Do not invent model support for a market. Sport-specific model providers may be necessary; expose their identity separately.

Pinnacle delay is acceptable by owner direction. Unknown delay must remain unknown; never assume a fixed 15-minute delay. Delayed odds can support labeled estimates/comparisons without pretending to be an executable venue or synchronized live fair value. Do not replace the free-data requirement with a paid plan silently.

## Coverage contract

The shared product, venue adapters, reference handling and selected sport/market
calculations are implemented and verified offline. The [coverage matrix](coverage-matrix.md)
separates those capabilities from actual source evidence. [Integrated offline
validation](offline-integration.md) is complete. Native source qualification and
beta signoff remain open.

Support all six sports and every requested family where the sporting format applies. Do not promise all venues list every combination. Useful comparable overlap is required; four connected logos or isolated unmatched samples are insufficient. Unavailable requested cells remain gaps until resolved or explicitly accepted as exclusions by the owner.

Owner decision September 22: “halftime” includes both halves in the longer-term product. Pregame first-half winner, spread and total markets are required for beta and come first, starting with NFL. Second-half markets offered during halftime are later stretch work, not a beta requirement. No in-play collection is authorized. Selected equivalents are MLB cumulative first 3, first 5, first 6 and regulation 9 innings, and NHL individual periods 1, 2 and 3. Current-season conference and league championships are selected, with explicit season, field and settlement horizon. These owner decisions are resolved and implemented. NCAAB scope is men’s Division I.

## Beta signoff gates

1. **Source breadth:** four selected prediction venues deliver actual current production observations through the product. Optional analytics/bookmaker extras need honest provenance when shown, but are not a source-readiness gate. Sandbox/mock/saved one-off pages do not satisfy required prediction-feed readiness.
2. **Sport/market breadth:** implemented six-sport matrix, supported matching and clear availability/exclusions for winners, spreads, totals, pregame first-half markets and futures. Use historical/offline checks for out-of-season cases, clearly labeled; agree any seasonal live-verification deferral rather than claiming it passed.
3. **Product loop:** the ordinary app automatically populates EV%-ranked cards with simple filters, visible source age/health and unavailable reasons, accessible Details, secondary configuration/history, explicit Start/Stop and saved reopening. The ordinary user does not need diagnostic commands.
4. **Economics:** preserve original prices, side orientation, quantity/depth, fee versions, period/line and outcome rules. Unknown material inputs produce conditional/unavailable results. Lead with EV%; disclose net-dollar arithmetic, evaluated size and return denominator in Details. Missing probabilities or material costs leave primary EV unavailable; conditional scenarios remain separately labeled. Independently reconcile representative real observations for each integrated source and supported market family. Zero and negative results are valid.
5. **Optional-data honesty:** when included, keep model estimates, delayed Pinnacle, manual what-if inputs and historical research distinct. Show source/receipt/model times, provenance and dependencies. No future-data leakage or claim that removing bookmaker margin establishes true probability.
6. **Practical operation/history:** demonstrate a jointly agreed session length with all selected sources, bounded resources, visible stale/disconnected state, recovery, finalization and exact reopening. Record gaps. Preserve sporting results separately from venue payout/settlement, including pending futures. No 24/7 SLA is required.
7. **Owner decision:** engineering evidence first, then a hybrid product/technical walkthrough and short-answer survey. Record accept, accept with nonblocking changes, revise, or defer in the owner's words and for an explicit scope. Tests are not owner acceptance.

The owner authorized a 30-minute offline target, segmented to preserve existing 180-second limits. Real-source duration and coverage/cadence targets still require an exact separately approved scope based on available feeds. No further beta signoff demo until these gates are ready; focused engineering previews remain optional.

## Later work

Second-half markets offered at halftime and live/in-play are explicit stretch goals. Calibrated predictive claims, lead/lag strategies, fill-probability/maker research and actual execution are later proposals; do not claim them delivered by basic model/Pinnacle comparisons. These extensions must not displace the confirmed breadth and core product loop.

## Sources and current evidence

See [gap assessment](beta-gap-assessment-20260920.md), [delivery plan](data-coverage-plan.md), [math report](math-reconciliation-report.md), [ProphetX](slice-3.md), [Novig](slice-5.md), and [offline diagnostic PASS](../evidence/delivery-launcher-preflight-20260919/final-report.md).

The previous roadmap is retained in [planning history](history/beta-reset-20260920/README.md). Its optional-reference, NFL-only and deferred-venue instructions do not govern this beta.

## Current engineering and remaining qualification

[Sports integration](sports-integration.md) covers the selected full-game,
first-half, baseball/hockey period and championship markets. [Native data
dependencies](market-data-gaps.md) remain open.

One historical NFL Pinnacle sample contains 16 side references, with delay unknown.
Compatible prediction observations, native settlement and independent model inputs
remain unqualified. MoneyPuck is dropped; NHL analytics and KenPom are deferred.
Novig/ProphetX requests were reported sent; current replies and provisioning are unconfirmed. The original US inquiry was sent and its supplied reply reconciled; US follow-up and Kalshi outreach are withdrawn. Use the owner-authorized provisional economics in [provider decisions](provider-evidence-action-package.md). Request only missing status/nonsecret details; engineering interprets exchange answers. NHL/KenPom and other analytics/bookmaker gaps are optional-data limitations, not beta blockers; no exclusion decision is needed. Owner feedback on September 26 is formative only; the navigation task and remaining workflows were not reviewed.

See the [delivery plan](data-coverage-plan.md) for the current handoff and
[retained planning snapshots](history/beta-reset-20260920/README.md) for earlier records.

## Local card candidate handoff

The consolidated card/workflow package is implemented and offline-verified. [Exact preview, candidate identity, evidence and one-task formative review](opportunity-card-handoff.md). This later engineering update preserves the earlier owner feedback and source decisions. Simulation does not establish real-source participation or owner acceptance; all-four-venue qualification remains open.
