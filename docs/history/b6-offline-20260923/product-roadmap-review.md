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

B1 is COMPLETE: the [working source × sport × market/period matrix](b1-coverage-matrix.md) and [B2 implementation handoff](b2-product-integration-handoff.md) are delivered. B2 fixture-backed product integration is COMPLETE ([evidence](../evidence/b2-product-integration-20260920/final-report.md)); B3 is next. B3–B5 resolve data dependencies and expand verified coverage as their work proceeds. Missing source information is tracked in its owning slice, not assumed solved or made a blanket prerequisite. For every cell record available/absent/not-yet-verified, access, native identifiers, discovery, timestamp/delay, quote/depth units, fee/settlement compatibility, integration status, evidence and next action. Missing market listings differ from unfinished engineering.

Support all six sports and every requested family where the sporting format applies. Do not promise all venues list every combination. Useful comparable overlap is required; four connected logos or isolated unmatched samples are insufficient. Unavailable requested cells remain gaps until resolved or explicitly accepted as exclusions by the owner.

Owner decision September 22: “halftime” includes both halves in the longer-term product. Pregame first-half winner, spread and total markets are required for beta and come first, starting with NFL. Second-half markets offered during halftime are later stretch work, not a beta requirement. No in-play collection is authorized. MLB innings and NHL period equivalents are not selected. Futures categories, settlement horizon and participant/season identity remain to define. NCAAB scope is men’s Division I.

## Beta signoff gates

1. **Source breadth:** four selected prediction venues deliver actual current production observations through the product. Both requested reference types are integrated through repeatable usable paths; sandbox/mock/saved one-off pages do not satisfy live source readiness.
2. **Sport/market breadth:** implemented six-sport matrix, supported matching and clear availability/exclusions for winners, spreads, totals, pregame first-half markets and futures. Use historical/offline checks for out-of-season cases, clearly labeled; agree any seasonal live-verification deferral rather than claiming it passed.
3. **Product loop:** one dashboard shows games/markets, all source coverage and health, supported comparable Arb/EV results, filters/sorts, detail, explicit Start/Stop and saved reopening. The ordinary user does not need diagnostic commands.
4. **Economics:** preserve original prices, side orientation, quantity/depth, fee versions, period/line and outcome rules. Unknown material inputs produce conditional/unavailable results. Explain net dollars and ROI basis. Independently reconcile representative real observations for each integrated source and supported market family. Zero and negative results are valid.
5. **Reference honesty:** keep model estimates, delayed Pinnacle, manual what-if inputs and historical research distinct. Show source/receipt/model times, provenance and dependencies. No future-data leakage or claim that removing bookmaker margin establishes true probability.
6. **Practical operation/history:** demonstrate a jointly agreed session length with all selected sources, bounded resources, visible stale/disconnected state, recovery, finalization and exact reopening. Record gaps. Preserve sporting results separately from venue payout/settlement, including pending futures. No 24/7 SLA is required.
7. **Owner decision:** engineering evidence first, then a hybrid product/technical walkthrough and short-answer survey. Record accept, accept with nonblocking changes, revise, or defer in the owner's words and for an explicit scope. Tests are not owner acceptance.

Required duration and numeric coverage/cadence targets will be proposed from available feeds and intended use, not invented as already approved. No further beta signoff demo until these gates are ready; focused engineering previews remain optional.

## Later work

Second-half markets offered at halftime and live/in-play are explicit stretch goals. Calibrated predictive claims, lead/lag strategies, fill-probability/maker research and actual execution are later proposals; do not claim them delivered by basic model/Pinnacle comparisons. These extensions must not displace the confirmed breadth and core product loop.

## Sources and current evidence

See [gap assessment](beta-gap-assessment-20260920.md), [delivery plan](data-coverage-plan.md), [math report](math-reconciliation-report.md), [ProphetX](slice-3.md), [Novig](slice-5.md), and [offline diagnostic PASS](../evidence/delivery-launcher-preflight-20260919/final-report.md).

The previous roadmap is retained in [planning history](history/beta-reset-20260920/README.md). Its optional-reference, NFL-only and deferred-venue instructions do not govern this beta.

## September 21 B4 implementation status

[B4 independent engineering](b4-independent-handoff.md) is offline verified through the ordinary product: distinct model/Pinnacle inputs, conditional EV, original-source replay, explicit local imports and bounded refresh accounting. The authorized NFL Pinnacle sample now supplies 16 actual saved side references (one credit, 499 remaining). Actual reference EV still needs compatible prediction observations and reviewed settlement binding. Model acquisition/independence remain open; KenPom is deferred. [Evidence](../evidence/b4-pinnacle-sample-20260921/final-report.md). All non-NFL comparable market breadth and spread/total/period/futures economics remain B5. B1/B2 and B3 independent engineering are preserved; Novig/ProphetX production access requests are pending. Beta remains NOT READY FOR SIGNOFF.

## September 22 first-half engineering status

**Bounded NFL pregame first-half winner/spread/total engineering COMPLETE, offline verified September 22.** [Handoff](b5-nfl-first-half-handoff.md) · [acceptance and exact identity](../evidence/b5-nfl-first-half-20260922/final-report.md). Ordinary First half Details, period/family filters, tie/equality partitions, conditional Arb/EV, explicit unsupported structures and Stop/exact reopening pass 403 Python tests and two JS suites. Original 18-Arb/96-EV and prior winner/line saved results remain exact. Actual venue/model qualification and full B4/B5 remain open. Pregame first-half W/S/T is required for beta; second-half offered at halftime is stretch. NCAAF first-half engineering is subsequently complete; NBA first-half is subsequently complete; men’s Division I NCAAB first-half is subsequently complete. **Beta NOT READY FOR SIGNOFF.**


## September 22 NCAAF first-half engineering

**Bounded NCAAF pregame first-half winner/spread/total engineering COMPLETE, offline verified September 22.** [Handoff](b5-ncaaf-first-half-handoff.md) · [acceptance and identity](../evidence/b5-ncaaf-first-half-20260922/final-report.md). The six-school 2026 boundary, site/subdivision/game identity, H1 tie/equality partitions, conditional Arb/EV, ordinary filters/Details and Stop/exact reopening are verified. 424 Python tests and two JS suites pass, preserving original 18-Arb/96-EV and prior NFL-H1/winner/line outputs. FCS-only contracts and actual venue/model qualification remain missing. Full B4/B5 open. **NBA first-half engineering is subsequently complete; NCAAB first-half engineering is subsequently complete; see the current update. Beta NOT READY FOR SIGNOFF.**


## September 22 NBA first-half engineering

**Bounded NBA pregame first-half winner/spread/total engineering COMPLETE, offline verified September 22.** [Handoff](b5-nba-first-half-handoff.md) · [acceptance and identity](../evidence/b5-nba-first-half-20260922/final-report.md). Ordinary end-of-second-quarter scope, tie/equality-aware conditional Arb/EV, visible unsupported structures, period/family filters and Stop/exact reopening pass 471 Python tests and two JS suites. Original 18-Arb/96-EV and prior sport/NFL-H1/NCAAF-H1 saved results remain exact. Actual selected venue/model qualification, fractional/three-way winner and exceptional payouts remain open. **NCAAB first-half engineering is subsequently complete; see the current update. Full B4/B5 open; beta NOT READY FOR SIGNOFF.**

## September 22 men’s D1 NCAAB first-half engineering

**Bounded men’s Division I NCAAB pregame first-half winner/spread/total engineering COMPLETE, offline verified September 22.** [Handoff](b5-ncaab-first-half-handoff.md) · [acceptance and exact identity](../evidence/b5-ncaab-first-half-20260922/final-report.md). Four reviewed 2026–2027 schools; explicit first 20-minute half, school/gender/division/tournament/site identity, tie/equality-aware conditional Arb/EV, unsupported structures, filters and Stop/exact reopening pass 494 Python tests and two JS suites. Original18-Arb/96-EV and prior saved outputs remain exact. Actual venue/model qualification, exceptional payouts and broader B4/B5 remain open. **Recommended next: bounded NFL sporting-result and venue-settlement linkage for existing full-game/H1 W/S/T.** [Remaining B5 backlog and next scope](b5-remaining-backlog.md). Broader college rosters, futures definitions and undecided MLB/NHL period equivalents remain visible. **Beta NOT READY FOR SIGNOFF.**
