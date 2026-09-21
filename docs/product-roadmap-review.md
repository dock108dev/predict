# Predict — beta product definition

Updated September 20, 2026. **NOT READY FOR BETA SIGNOFF.** This document owns current product scope; [delivery plan](data-coverage-plan.md) owns engineering order and the [Desktop tracker](../../prediction_arb_next_steps.md) owns status/next action. Older E/D/slice reports are evidence for their recorded work, not competing roadmaps.

## Product goal

A personal read-only sports prediction-market dashboard: compare real purchasable prices across venues, inspect fee/size/settlement-aware arbitrage and model/reference-based EV, understand missing coverage, and return to saved observations. Useful breadth and ordinary operation are the beta goal. No profitability quota, automated trading or generic production-hardening program.

## Confirmed beta scope

| Dimension | Required scope |
|---|---|
| Prediction venues | At least four: Kalshi, Novig, Polymarket US and ProphetX (owner-selected September 21) |
| Independent reference | Power-index/model-derived line or probability, in the style of 538; provider(s) to select for adequate coverage |
| Bookmaker reference | Free delayed Pinnacle data; actual access route, delay and coverage to verify |
| Sports | NFL, NBA, MLB, NHL, NCAAF, NCAAB |
| Markets | Win/loss, spreads, totals, halftime, futures |
| Core timing | Current pregame prediction prices; explicitly delayed Pinnacle reference; dated model outputs |
| Stretch | Live/in-play markets; not a core beta signoff requirement |

Polymarket means Polymarket US in the existing product; international Polymarket is not interchangeable. ProphetX is owner-selected for slot four as of September 21; selection does not qualify its production access. Alternatives must be assessed on access, usable coverage, economics and data effort.

The model reference and Pinnacle have different roles. A strength rating alone is not a moneyline probability, spread distribution, total or futures probability. Where conversion is needed, specify and validate the method, input dates and limitations. Do not invent model support for a market. Sport-specific model providers may be necessary; expose their identity separately.

Pinnacle delay is acceptable by owner direction. Unknown delay must remain unknown; never assume a fixed 15-minute delay. Delayed odds can support labeled estimates/comparisons without pretending to be an executable venue or synchronized live fair value. Do not replace the free-data requirement with a paid plan silently.

## Coverage contract

B1 is COMPLETE: the [working source × sport × market/period matrix](b1-coverage-matrix.md) and [B2 implementation handoff](b2-product-integration-handoff.md) are delivered. B2 fixture-backed product integration is COMPLETE ([evidence](../evidence/b2-product-integration-20260920/final-report.md)); B3 is next. B3–B5 resolve data dependencies and expand verified coverage as their work proceeds. Missing source information is tracked in its owning slice, not assumed solved or made a blanket prerequisite. For every cell record available/absent/not-yet-verified, access, native identifiers, discovery, timestamp/delay, quote/depth units, fee/settlement compatibility, integration status, evidence and next action. Missing market listings differ from unfinished engineering.

Support all six sports and every requested family where the sporting format applies. Do not promise all venues list every combination. Useful comparable overlap is required; four connected logos or isolated unmatched samples are insufficient. Unavailable requested cells remain gaps until resolved or explicitly accepted as exclusions by the owner.

Clarify exact halftime semantics, including first-half/second-half bets versus opportunities evaluated at halftime. MLB has innings and NHL periods; do not silently call first-five innings or a period “halftime.” Define futures categories, settlement horizon and participant/season identity. NCAAB men's/women's competition coverage remains to specify. Pregame first-half prices do not require in-play collection; newly offered second-half prices at halftime may, so resolve that boundary explicitly.

## Beta signoff gates

1. **Source breadth:** four selected prediction venues deliver actual current production observations through the product. Both requested reference types are integrated through repeatable usable paths; sandbox/mock/saved one-off pages do not satisfy live source readiness.
2. **Sport/market breadth:** implemented six-sport matrix, supported matching and clear availability/exclusions for winners, spreads, totals, halftime and futures. Use historical/offline checks for out-of-season cases, clearly labeled; agree any seasonal live-verification deferral rather than claiming it passed.
3. **Product loop:** one dashboard shows games/markets, all source coverage and health, supported comparable Arb/EV results, filters/sorts, detail, explicit Start/Stop and saved reopening. The ordinary user does not need diagnostic commands.
4. **Economics:** preserve original prices, side orientation, quantity/depth, fee versions, period/line and outcome rules. Unknown material inputs produce conditional/unavailable results. Explain net dollars and ROI basis. Independently reconcile representative real observations for each integrated source and supported market family. Zero and negative results are valid.
5. **Reference honesty:** keep model estimates, delayed Pinnacle, manual what-if inputs and historical research distinct. Show source/receipt/model times, provenance and dependencies. No future-data leakage or claim that removing bookmaker margin establishes true probability.
6. **Practical operation/history:** demonstrate a jointly agreed session length with all selected sources, bounded resources, visible stale/disconnected state, recovery, finalization and exact reopening. Record gaps. Preserve sporting results separately from venue payout/settlement, including pending futures. No 24/7 SLA is required.
7. **Owner decision:** engineering evidence first, then a hybrid product/technical walkthrough and short-answer survey. Record accept, accept with nonblocking changes, revise, or defer in the owner's words and for an explicit scope. Tests are not owner acceptance.

Required duration and numeric coverage/cadence targets will be proposed from available feeds and intended use, not invented as already approved. No further beta signoff demo until these gates are ready; focused engineering previews remain optional.

## Later work

Live/in-play is the explicit stretch goal. Calibrated predictive claims, lead/lag strategies, fill-probability/maker research and actual execution are later proposals; do not claim them delivered by basic model/Pinnacle comparisons. These extensions must not displace the confirmed breadth and core product loop.

## Sources and current evidence

See [gap assessment](beta-gap-assessment-20260920.md), [delivery plan](data-coverage-plan.md), [math report](math-reconciliation-report.md), [ProphetX](slice-3.md), [Novig](slice-5.md), and [offline diagnostic PASS](../evidence/delivery-launcher-preflight-20260919/final-report.md).

The previous roadmap is retained in [planning history](history/beta-reset-20260920/README.md). Its optional-reference, NFL-only and deferred-venue instructions do not govern this beta.

## September 21 B4 implementation status

[B4 independent engineering](b4-independent-handoff.md) is offline verified through the ordinary product: distinct model/Pinnacle inputs, conditional EV, original-source replay, explicit local imports and bounded refresh accounting. The authorized NFL Pinnacle sample now supplies 16 actual saved side references (one credit, 499 remaining). Actual reference EV still needs compatible prediction observations and reviewed settlement binding. Model acquisition/independence remain open; KenPom is deferred. [Evidence](../evidence/b4-pinnacle-sample-20260921/final-report.md). All non-NFL comparable market breadth and spread/total/period/futures economics remain B5. B1/B2 and B3 independent engineering are preserved; Novig/ProphetX production access requests are pending. Beta remains NOT READY FOR SIGNOFF.
