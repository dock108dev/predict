# Predict — beta product definition

Updated September 22, 2026. **NOT READY FOR BETA SIGNOFF.** This document owns current product scope; [delivery plan](data-coverage-plan.md) owns engineering order and the [Desktop tracker](../../prediction_arb_next_steps.md) owns status/next action. Older E/D/slice reports are evidence for their recorded work, not competing roadmaps.

## Product goal

A personal read-only sports prediction-market dashboard: compare real purchasable prices across venues, inspect fee/size/settlement-aware arbitrage and model/reference-based EV, understand missing coverage, and return to saved observations. Useful breadth and ordinary operation are the beta goal. No profitability quota, automated trading or generic production-hardening program.

## Confirmed beta scope

| Dimension | Required scope |
|---|---|
| Prediction venues | At least four: Kalshi, Novig, Polymarket US and ProphetX (owner-selected September 21) |
| Independent reference | Power-index/model-derived line or probability, in the style of 538; provider(s) to select for adequate coverage |
| Bookmaker reference | Free delayed Pinnacle data; actual access route, delay and coverage to verify |
| Sports | NFL, NBA, MLB, NHL, NCAAF, NCAAB |
| Markets | Win/loss, spreads, totals, pregame first-half winner/spread/total, futures |
| Core timing | Current pregame prediction prices; explicitly delayed Pinnacle reference; dated model outputs |
| Stretch | Second-half markets offered at halftime and live/in-play; not beta requirements |

Polymarket means Polymarket US in the existing product; international Polymarket is not interchangeable. ProphetX is owner-selected for slot four as of September 21; selection does not qualify its production access. Alternatives must be assessed on access, usable coverage, economics and data effort.

The model reference and Pinnacle have different roles. A strength rating alone is not a moneyline probability, spread distribution, total or futures probability. Where conversion is needed, specify and validate the method, input dates and limitations. Do not invent model support for a market. Sport-specific model providers may be necessary; expose their identity separately.

Pinnacle delay is acceptable by owner direction. Unknown delay must remain unknown; never assume a fixed 15-minute delay. Delayed odds can support labeled estimates/comparisons without pretending to be an executable venue or synchronized live fair value. Do not replace the free-data requirement with a paid plan silently.

## Coverage contract

B1/B2 and independent B3/B4/B5 engineering are complete. The [coverage matrix](b1-coverage-matrix.md) distinguishes reviewed fixture capabilities from actual source evidence. B6 offline integrated readiness is COMPLETE; see the [B6 handoff](b6-offline-integrated-handoff.md). Full B3/B4/B5/B6 and beta signoff remain open for actual-source criteria. Missing listings, native rules, dated model distributions and source economics remain precise qualification work, not reasons to repeat finished engineering.

Support all six sports and every requested family where the sporting format applies. Do not promise all venues list every combination. Useful comparable overlap is required; four connected logos or isolated unmatched samples are insufficient. Unavailable requested cells remain gaps until resolved or explicitly accepted as exclusions by the owner.

Owner decision September 22: “halftime” includes both halves in the longer-term product. Pregame first-half winner, spread and total markets are required for beta and come first, starting with NFL. Second-half markets offered during halftime are later stretch work, not a beta requirement. No in-play collection is authorized. Selected equivalents are MLB cumulative first 3, first 5, first 6 and regulation 9 innings, and NHL individual periods 1, 2 and 3. Current-season conference and league championships are selected, with explicit season, field and settlement horizon. These owner decisions are resolved and implemented. NCAAB scope is men’s Division I.

## Beta signoff gates

1. **Source breadth:** four selected prediction venues deliver actual current production observations through the product. Both requested reference types are integrated through repeatable usable paths; sandbox/mock/saved one-off pages do not satisfy live source readiness.
2. **Sport/market breadth:** implemented six-sport matrix, supported matching and clear availability/exclusions for winners, spreads, totals, pregame first-half markets and futures. Use historical/offline checks for out-of-season cases, clearly labeled; agree any seasonal live-verification deferral rather than claiming it passed.
3. **Product loop:** one dashboard shows games/markets, all source coverage and health, supported comparable Arb/EV results, filters/sorts, detail, explicit Start/Stop and saved reopening. The ordinary user does not need diagnostic commands.
4. **Economics:** preserve original prices, side orientation, quantity/depth, fee versions, period/line and outcome rules. Unknown material inputs produce conditional/unavailable results. Explain net dollars and ROI basis. Independently reconcile representative real observations for each integrated source and supported market family. Zero and negative results are valid.
5. **Reference honesty:** keep model estimates, delayed Pinnacle, manual what-if inputs and historical research distinct. Show source/receipt/model times, provenance and dependencies. No future-data leakage or claim that removing bookmaker margin establishes true probability.
6. **Practical operation/history:** demonstrate a jointly agreed session length with all selected sources, bounded resources, visible stale/disconnected state, recovery, finalization and exact reopening. Record gaps. Preserve sporting results separately from venue payout/settlement, including pending futures. No 24/7 SLA is required.
7. **Owner decision:** engineering evidence first, then a hybrid product/technical walkthrough and short-answer survey. Record accept, accept with nonblocking changes, revise, or defer in the owner's words and for an explicit scope. Tests are not owner acceptance.

The owner authorized a 30-minute offline target, segmented to preserve existing 180-second limits. Real-source duration and coverage/cadence targets still require an exact separately approved scope based on available feeds. No further beta signoff demo until these gates are ready; focused engineering previews remain optional.

## Later work

Second-half markets offered at halftime and live/in-play are explicit stretch goals. Calibrated predictive claims, lead/lag strategies, fill-probability/maker research and actual execution are later proposals; do not claim them delivered by basic model/Pinnacle comparisons. These extensions must not displace the confirmed breadth and core product loop.

## Sources and current evidence

See [gap assessment](beta-gap-assessment-20260920.md), [delivery plan](data-coverage-plan.md), [math report](math-reconciliation-report.md), [ProphetX](slice-3.md), [Novig](slice-5.md), and [offline diagnostic PASS](../evidence/delivery-launcher-preflight-20260919/final-report.md).

The previous roadmap is retained in [planning history](history/beta-reset-20260920/README.md). Its optional-reference, NFL-only and deferred-venue instructions do not govern this beta.

## Current engineering and remaining qualification

Independent B5 is complete across the selected six-sport full-game, first-half, baseball/hockey period and championship scope. [B5 handoff](b5-independent-engineering-handoff.md) and [remaining native dependencies](b5-remaining-backlog.md) replace historical sport-by-sport next actions. B6 integrates those capabilities through ordinary collection, viewing and saved history; its evidence establishes offline behavior only.

The single retained NFL Pinnacle h2h sample contains 16 side references (one authorized credit consumed; 499 recorded remaining at that attempt). It remains historical, with delay unknown. Compatible prediction books, reviewed native settlement and actual independent model inputs remain unqualified. MoneyPuck is dropped; NHL analytics and KenPom are deferred. Novig/ProphetX provider responses remain pending in current records; no new access inspection or outreach occurred.

[Pre-B6 document snapshots](history/b6-offline-20260923/README.md) preserve superseded roadmap wording and earlier engineering milestones. Next actual work is the separately approvable [bounded real-data proposal](b6-next-real-milestone.md), not owner beta acceptance.
