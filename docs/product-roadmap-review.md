# Prediction Market Edge — product direction and implementation outline

Updated September 15, 2026. Proposed working name; the project directory remains prediction-arb. This document replaces the earlier P1–P8 roadmap with the owner’s expanded scope. Planning only: no implementation, provider subscription, live collection or trading is performed by this review.

## 1. Product definition

A personal prediction-market pricing and opportunity platform that combines external reference data and prediction-market books to estimate our price, detect several kinds of opportunity, and compare their economics after fees and execution assumptions.

The core product has four outputs:

| Output | Question | Primary result |
|---|---|---|
| Arbitrage | Do complementary prediction-market positions produce a positive net payoff across all material settlement outcomes? | Modeled worst-case net profit and ROI, conditional on the specified fills and settlement compatibility. |
| Mispricing | Is a prediction-market contract attractively priced against our estimate? | Net expected profit and return, with model uncertainty and sizing assumptions. |
| Lead/lag | Has reference information moved while a target market has not yet adjusted? | Observed movement/lag signal; net expected trade value only when a validated prediction and execution scenario support it. |
| Maker value | Would a proposed resting order be attractive if filled? | Net expected value conditional on fill; fill probability and adverse-selection estimates separately when supported. |

Arbitrage remains a first-class strategy. Reference pricing is also core from the first expanded vertical slice. The system will learn which strategies are useful rather than assume mispricing, staleness or market making is more profitable.

**Reference universe:** sportsbook lines, external exchange prices, sports schedules/results and other useful evidence. These sources are for calculations only. No sportsbook betting, funding, bet slips or order routes.

**Execution universe:** supported prediction-market venues only. Initial development uses existing Kalshi and Polymarket US capabilities; ProphetX and Novig remain expansion candidates subject to their recorded access/data limitations. Execution research precedes actual orders.

**Working name:** Prediction Market Edge. “Our price” is the user-facing term for the versioned fair-value estimate. The name describes the broader product without claiming that every signal is arbitrage. No repository rename is part of this plan.

## 2. First useful expanded product

Open one NFL moneyline event and see:

- Our estimated probability for each target venue, sources used, disagreement, freshness and recent movement.
- Each supported prediction venue’s bid, ask and usable quantity.
- Separate Arb, Mispriced, Moving markets and Maker scenarios views, with unsupported views explicitly pending.
- Net results and the assumptions behind them; raw price gaps are available in details.
- Saved observations and calculations that can reproduce the screen later.

The first delivery needs one usable external reference source and the existing prediction venues. It does not need every provider, learned weights, an automated market maker or a new frontend framework.

## 3. Starting point and reuse

The current [tracker](/Users/michaelfuscoletti/Desktop/prediction_arb_next_steps.md) records adapters, normalization, event/market matching, settlement assessment, fees, top-of-book detection, depth sizing, PostgreSQL history and the local dashboard as implemented within their documented limits. The September 15 preparation record says the repaired candidate is loaded and ready for an owner-started try. This review did not inspect the running application or perform that try.

Keep these components as the product foundation. The original SDA/Scroll Down outline contributes reusable infrastructure and potentially useful pricing/history concepts:

| Source | Audit and potentially adapt | Integration rule |
|---|---|---|
| SDA | Sports identity/schedules, odds and closing-line history, outcome linkage, backtest/job concepts, selected health and logging patterns. | Use exact source revisions and a runnable extraction example. Keep existing canonical IDs and immutable prediction-market evidence. |
| Scroll Down | Layout/theme, readable loading/error states, API proxy/security patterns, selected UI test and packaging patterns. | Reuse only components that improve the expanded market-watch flow. |
| prediction-arb | Adapters, books, settlement, fees, sizing, capture/replay, collector and dashboard. | Extend existing interfaces rather than duplicate domain logic. |

The earlier review found both repositories archived. Dormant schemas and infrastructure remain audit candidates; this plan does not claim they run, provide live feeds or establish a percentage of reusable code. SDA sports identity can enrich matching; it cannot decide venue contract settlement rules.

FastAPI, Redis, Celery and Next.js are implementation options when a concrete requirement warrants them. Their adoption is not a prerequisite for our-price calculations. Keep long-lived quote processing in the existing async ingestion path; background research jobs can have a separate scheduling mechanism later.

## 4. Data and calculation changes

### Separate reference observations from executable books

Add a reference adapter interface with no execution methods. Preserve provider, underlying bookmaker/exchange, native IDs, event/market terms, both outcome prices, source timestamp, local receipt timestamp, raw payload and entitlement/coverage metadata. Limits/depth are optional and remain unknown when absent.

Match exact period, line and outcome rules before combining prices. Record source families so the same bookmaker supplied through two aggregators is not counted as two independent opinions. Retain every delivered change within the declared collection scope, plus receipt and gap evidence; never claim every upstream change was delivered.

### Make our price a reproducible object

Store target venue, canonical market, estimate time, input receipt IDs, included/excluded source families, de-vig method, model version, probability, source disagreement, freshness and available movement features. A confidence number needs a defined and validated meaning; start with evidence quality and uncertainty explanations.

Begin with a transparent baseline using synchronized two-way lines and proportional margin removal. De-vigging estimates probabilities from bookmaker prices; it does not remove prediction-exchange trading fees. Add alternative methods only through measured comparison.

Exclude the target venue and identified copies of its prices from its estimate. Weighting must address source dependence and stale inputs. Initially disclose simple baseline weights; later learn weights on prior training periods and assess held-out events. Preserve an external-only estimate as a useful comparison. Closing prices and outcomes are evaluation data, never future inputs to an earlier estimate.

### Apply net economics to each strategy

Retain the existing outcome-aware fee engine. Calculate state-specific payouts and charges before aggregating worst-case or expected results. Expected profit is the probability-weighted net cashflow across all modeled outcomes; a binary win probability alone is insufficient when material void/refund outcomes are unresolved.

Use exact venue/product/account/order-role schedules. Do not transfer Polymarket international fees or rebates to Polymarket US. Maker placement does not imply zero fees or a guaranteed rebate. Provider access, fee and commercial claims in the pasted material require current official verification before use; no provider is selected or subscribed here.

Report dollars per contract, total dollars and return on a stated capital denominator distinctly. A 3-cent probability/price difference is not automatically a 3% ROI. Depth walking already prices modeled book impact; avoid charging the same slippage twice. Unknown material costs make final net results unavailable. Separate specified fees, estimated execution costs and conservative reserves.

A maker quote must respect tick size and order behavior; a marketable limit price is not automatically passive. “Value if filled” must not be represented as expected realized profit without fill/selection modeling.

## 5. Revised work packages

E1–E10 are expansion work packages. Existing completed slices retain their historical identities; legacy Slice 14 Crypto.com and Slice 15 Fanatics move behind the first expanded product in this proposed ordering. E9 extends the intent of legacy Slice 16 simulation.

### E1 — shared contracts and targeted reuse audit

**Tasks:** define ReferenceQuote, FairPrice and the four signal records; define units, source-family identities, as-of timestamps, unknown fields and fee inputs. Audit the specific SDA odds/normalization/history modules and Scroll Down components needed for E2–E5. Record source revision, dependencies, extraction cost and a runnable example for selected reuse.

**Result:** a small interface/schema specification and concrete extract/adapt/skip list. Proposed new areas: `app/reference/`, `app/pricing/`, `app/signals/`; retain existing matching, fee and storage APIs.

**Completion check:** one historical or synthetic event flows through the proposed contracts without reference prices becoming executable books. This design work does not wait for an owner live try.

### E2 — one external reference feed and durable history

**Depends on:** E1.

**Tasks:** compare a small provider shortlist for NFL moneyline coverage, both outcome sides, permitted reference use, timestamps, cadence, source identity, history and cost. Pinnacle and a multi-book provider are candidates from the supplied outline, not settled choices. Implement one adapter, normalization/matching and migrations; save non-opportunity quote changes as well as candidate inputs. Use captured or synthetic fixtures while access is unresolved.

**Result:** a reference timeline alongside existing prediction books. Audit SDA schedule/odds reuse before writing its equivalent.

**Completion check:** matching rejects incompatible markets; replay preserves prices, identities, timestamps and gaps. Real-data verification follows available access and explicit collection scope; no invented reference source.

### E3 — our-price baseline

**Depends on:** E2 interfaces/data; fixtures support development before live access.

**Tasks:** implement paired-line validation, proportional de-vigging, stale-source exclusion, source-family deduplication, target-venue exclusion and a transparent baseline consensus. Store source disagreement and reproducible versions. Add movement features only for supported time windows.

**Result:** a target-specific estimated fair probability with an explanation of its inputs.

**Completion check:** deterministic replay; probabilities are valid; missing counterparts, stale inputs and insufficient independent evidence produce an explicit unavailable/degraded estimate. Do not manufacture statistical confidence.

### E4 — net opportunity service

**Depends on:** E3 for mispricing; existing arb implementation can progress independently.

**Tasks:** adapt the current detector/depth/fee modules into a shared service for Arb and Mispricing. Resolve supported settlement, fee, quantity and source-time blockers for a small venue/market set. Calculate net expected results using stated outcome probabilities, and net worst-case results for arbitrage separately. Introduce the common interfaces for later lead/lag and maker scenarios.

**Result:** two independently explainable live-capable signal types; unsupported economic results retain precise reasons.

**Completion check:** focused positive/negative/unknown outcome cases, real fee rounding/grouping, no shared-liquidity double counting, and exact stored calculation replay. Neither positive opportunities nor external blockers resolved by assumption are required outcomes.

### E5 — market-watch screen centered on our price

**Depends on:** E3/E4 contracts; UI development can use isolated fixtures.

**Tasks:** show event, our price, reference movement and prediction-venue book rows. Add separate signal tabs/filters; sort known net values within each strategy. Show basis of size/profit, per-source freshness, excluded inputs and details. Preserve Live/Historical/Synthetic isolation and stable row selection during updates. Adapt useful Scroll Down design elements without requiring a wholesale frontend migration.

**Result:** the owner can compare our price with a venue’s available price and understand the net result.

**Completion check:** one usable event-level walkthrough, including stale inputs, unknown net value and saved reopening. Avoid one combined ranking that treats expected profit and worst-case profit as equivalent.

### E6 — sustained collection for both data universes

**Depends on:** existing prototype stability; reference integration uses E2. Work can overlap E3–E5.

**Tasks:** finish the prepared owner Start/Stop/reopen try; expand to explicitly chosen session durations; refresh discovery/subscriptions; recover and resynchronize after disconnects; keep per-source health and capture-gap records. Bound queues, memory and disk; segment sessions and define retention. Collection can outlive a browser tab. Process failure must leave an interrupted record. Specify startup/autoresume policy before enabling unattended operation.

**Result:** prediction and reference timelines suitable for a useful sports-session view and research.

**Completion check:** an agreed session and recovery path, truthful saved accounting, manual Stop and a practical interface check. No blanket 250 ms gate. Subsecond research requires timestamp/cadence evidence appropriate to that particular claim.

### E7 — lead/lag signals

**Depends on:** E3 and adequate E6 timelines.

**Tasks:** detect source-family movement clusters and target nonresponse; distinguish an unchanged healthy quote from a disconnected feed. Measure source/receipt clock uncertainty and provider batching. Store movement magnitude, observation window and horizon. Validate target response on held-out events with baseline comparisons and multiple-testing controls.

**Result:** observed delayed-response candidates first; predicted movement/net value only when supported by validation and cost modeling.

**Completion check:** injected disconnect and delayed-delivery cases cannot masquerade as target lag. Sampling resolution limits reported lag. The illustrative 820 ms / 84% figures in the attachment are hypotheses/examples, not project measurements.

### E8 — calibration and opportunity research

**Depends on:** E3/E4 and adequate E6 history; includes E7 as it becomes available.

**Tasks:** link results and market-specific settlements; compare baseline sources/models using Brier score, log loss and calibration. Use event-grouped chronological splits and prior-data-only weight fitting. Compare closing-price benchmarks separately from realized outcomes. Report source dependence, uncertainty, coverage and results by sport/market/time-to-start. Track candidate episodes, overlapping liquidity and observation gaps.

**Result:** evidence on which sources and strategies add predictive or economic value after costs.

**Completion check:** a reproducible held-out report; insufficient data is reported explicitly. Apparent closing-line value, modeled EV and realized profit remain distinct. Do not sum correlated/overlapping opportunities into attainable returns.

### E9 — maker value and execution replay

**Depends on:** E4 and sufficient E6/E8 evidence; selected scenario tooling can be built earlier with fixtures.

**Tasks:** generate valid passive quote scenarios, exact maker/taker charges and conditional incentives. Simulate queue uncertainty, partial fills, cancellation delays, reference changes, adverse selection and inventory limits. Assess fair value conditional on being filled, rather than assume unconditional fair value survives selection. Compare take, make and do-nothing scenarios with a stated horizon and capital budget; simulate two-leg arb failures separately.

**Result:** maker-value research and a net execution-feasibility comparison. No order submission.

**Completion check:** favorable hypothetical fills do not establish fill probability; unknown queue position produces ranges/scenarios. Support a concrete execution go/no-go decision with evidence.

### E10 — operating and venue expansion

**Depends on:** a useful E2–E6 loop; execution expansion additionally depends on E9.

**Tasks:** add reference sources based on marginal information value; prediction venues based on access, overlapping markets and independent usable liquidity. Extend sports/spreads/totals with dedicated identity and settlement treatment. Add local unattended operation or hosting with explicit recovery, observability and access requirements. Actual prediction-market orders are a separate authorized project stage.

**Result:** targeted breadth and operation driven by demonstrated needs.

## 6. Delivery order and success

**Begin E1 and E2 now as the next proposed engineering scope.** Reference ingestion and our-price modeling must not wait for completion of an arbitrage-only analytics project. The prepared owner try continues as a separate practical check on the existing collector.

First expanded delivery: E1 → E2 → E3 → E4 → E5, with E6 advancing alongside it. One external reference, existing prediction venues, one market type, visible our price, net arb/mispricing results and replayable history.

Next research delivery: E7/E8, followed by E9 maker/execution feasibility. Expand only where evidence supports E10.

Product success means the owner can inspect an estimate, see why a prediction-market price may be attractive after costs, distinguish strategy and uncertainty, and revisit the supporting evidence. The research then determines which opportunities survive model error and execution friction. No strategy’s profitability is assumed in advance.

Only this roadmap was revised. The original PLAN.md, completion tracker, application, provider accounts, stored evidence and running services were not changed.
