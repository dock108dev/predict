# Predict private beta product scope

October 1, 2026. This document owns current product scope under the [authoritative tracker](../../prediction_arb_next_steps.md). [Acceptance](beta-coverage-acceptance.md) defines the workflow gate; [candidate verification](../evidence/private-beta-workflow-20261001-v1/README.md) owns readiness evidence. Older definitions below are historical.

Predict helps the owner find and inspect useful cross-venue prices, then trade manually outside the app. Beta/V1 covers configured authorized collection, exact matching, useful raw comparisons, sport/venue/market filters, fixed-cutoff Details, timestamps and source health, settlement/fee explanations, supported informational sizing, persistent watches, Stop, history, downloads and exact saved reopening. Preserve the accepted layout and shared implementation.

Kalshi and Polymarket US remain native; Novig and ProphetX use The Odds API. All four are intended participants. Actual availability varies by venue and market. Prioritize full-game winner/spread/total and other supported useful overlap. The six sports, 63 requirements and 252 source records remain the broader roadmap and factual ledger, without a numeric beta coverage gate or a requirement that every seasonal/niche cell be available.

Missing costs, probabilities or settlement facts affect the calculations that use them. Keep valid raw prices available. Supported EV retains EV%-first ordering and its probability basis; raw differences, conditional arbitrage and What-if EV are distinct. Pinnacle, DraftKings and BetMGM remain reference-only. Size/depth estimates identify their native units and assumptions and do not guarantee execution.

Engineering readiness is evaluated by the [workflow checklist](../evidence/private-beta-workflow-20261001-v1/README.md). Owner acceptance follows a directed walkthrough and remains separate. Retained observations are historical; isolated fixtures are engineering evidence. Further live collection requires fresh applicable authority and exact candidate binding. No acquisition campaign or automatic follow-up is the default next action.

V2 includes automated trading, submission/orchestration, fills/positions synchronization, execution reconciliation and automated order timing. Direct Novig/ProphetX trading access, complete private account economics, independent probability model development and commercial validation are later work unless explicitly needed for a selected calculation.

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
