# Predict — beta gap assessment

September 20, 2026. **NOT READY FOR BETA SIGNOFF.** This is an assessment and revised delivery proposal, not implementation or live-run authorization.

## Owner correction and acceptance floor

The owner rejected treating the one-market diagnostic as a beta demo: “seems like weve only proved basic functions,” “This needs to expand significantly for a beta signoff,” and “we need at least 4 prediction markets and 2 alt sources before we are ready.” The immediate task is assessing the product against final beta goals. No demo acceptance occurred.

Working interpretation pending the owner's answer: four distinct prediction-market venues and two alternative/reference pricing sources. Four contracts on one exchange do not meet this interpretation. Preferred venue/source identities and whether two bookmakers through one aggregator satisfy the alternative-source requirement remain open. Count provider connections and underlying pricing sources separately; duplicated bookmaker prices are not independent evidence.

The existing planned venue lineup is Kalshi, Polymarket US, ProphetX and Novig. It is a proposed lineup, not confirmation that all four are accessible. References and venue expansion are now beta requirements, superseding earlier optional-reference/deferred-expansion language. Preserve personal-app scope and original-input math; a positive opportunity is not required.

## What is actually delivered

| Area | Evidence-backed current position | Gap to expanded beta |
|---|---|---|
| Calculation/product foundation | Multi-game saved comparisons, sorting/filtering, detail, explicit what-if EV and saved-page research; retained independent reconciliation of 18 Arb rows and 96 EV scenarios | Four-venue current comparisons and integrated reference-based estimates are not established |
| Kalshi | Bounded production captures and native book/recovery work exist; revised one-market offline diagnostic passed | Sustained useful coverage and the completed collector-to-product flow are not established; upstream silence remains unresolved |
| Polymarket US | Bounded production discovery/streaming evidence; earlier finite two-venue session | Completeness unknown; Short purchase depth unsupported in current normalized path; retained coverage decline and daily-use behavior unresolved |
| ProphetX | Real sandbox REST prices, normalization and authenticated transport/recovery | Quantity/value units unresolved; no selection-update frames in retained bounded tests; production access/data not qualified |
| Novig | REST/stream adapter and recovery implemented against offline fixtures | Recorded handoff has no provisioned credentials/live capture; actual wire contract, production access and integration unverified |
| Alternative sources | Saved VegasInsider page / DraftKings-column research; reference records and mock transport | No two current integrated reference feeds demonstrated; saved page and its bookmaker column do not count as two sources |
| Collection/history | Segmented history, exact replay, finite refresh/Stop and resource controls demonstrated within specific runs | Practical session duration, coverage/recovery, outcomes, venue settlement and broader retention remain incomplete |
| Dashboard integration | Existing multi-game product UI and coverage controls | Current diagnostic is separate; the continuous coverage session is not established as feeding current comparison rows; four-plus-two integration missing |
| Advanced research | Contracts/proposals and some scenario/research foundations | Calibrated our-price, validated lead/lag and maker research are not completed capabilities; final beta inclusion needs an explicit scope decision |

This is more than basic functions, but substantially less than the expanded beta. Do not assign an overall completion percentage: several crucial integrations and external dependencies are open.

Evidence: [current tracker](../../prediction_arb_next_steps.md), [offline PASS](../evidence/delivery-launcher-preflight-20260919/final-report.md), [personal-beta report](personal-beta-operation-report.md), [math reconciliation](math-reconciliation-report.md), [ProphetX handoff](slice-3.md), [Novig handoff](slice-5.md), [coverage plan](data-coverage-plan.md), [product roadmap](product-roadmap-review.md).

Source inspection corroborates the gaps: `app/collection/venue_access.py` and `multi_game.py` bind the ordinary collection/comparison path to Kalshi/Polymarket US; `app/dashboard/multi_game_server.py` excludes sessions with `status_coverage` from its ordinary current multi-game dataset branch; `app/collection/odds_http.py` explicitly restricts its provider path to loopback mocks. Existing adapter files alone do not establish product integration.

## Proposed beta exit criteria

These translate the owner's breadth requirement into reviewable product outcomes. They are proposed acceptance details, not a claim that the owner has agreed to every threshold.

1. Four named prediction venues supply actual current production data to the same product for the agreed sport/market universe. Each has discovery counts, usable/unsupported sides, provenance and health. A sandbox, adapter stub or source logo does not count. No requirement that every event list on all four; show unmatched/excluded markets honestly.
2. Two named alternative pricing sources update through a repeatable ingestion path and contribute traceable inputs to estimates. Define whether they are two underlying bookmakers or two separately operated providers. Preserve source dependence, timestamps and missing data; do not label de-vigged consensus as proven true probability.
3. One dashboard supports source coverage, multi-game current comparisons, stable sorting/filtering, details, explicit Start/Stop and reopening saved sessions. No command-line diagnostic is needed for ordinary use.
4. Arb and EV use correct purchase sides, size, fee and settlement assumptions. Show supported net results and explicit conditional/unavailable cases. Independently reconcile representative real inputs across all six sources; do not require a profitable finding or hide near misses.
5. Demonstrate a useful owner-agreed session length with all selected sources operating together, bounded resource use, clear disconnect/stale state and recovery. Propose a staged 30-minute integration check, then one representative football viewing session; these are unapproved targets, not extensions of old run limits. No 24/7 production SLA is implied.
6. Saved observations and calculations reopen exactly; interrupted sessions and gaps remain visible. Sporting results and actual venue settlement stay distinct. Establish the beta's required outcome/history loop and disk policy; deeper backfill can remain deferred if explicitly scoped out.
7. Complete engineering checks, then a fresh owner product review and short-answer feedback. Owner acceptance, requested modifications and remaining limitations are recorded separately. Four-plus-two breadth is necessary but not sufficient for beta signoff.

Scope decisions still needed: exact six sources; sports and market types (current working baseline is NFL pregame full-game winner); session length; reference update cadence/cost; whether lead/lag, calibration or maker research are required for this beta or a later milestone. Do not silently shrink the broader roadmap to Arb only.

## Delivery order and next action

1. **Immediate engineering slice:** specify and implement, under a separate implementation instruction, the shared source-to-dashboard path using the existing collector, history and calculation engine. Begin by connecting coverage-session books to current product comparisons, exposing per-source coverage and removing two-venue assumptions where necessary for the selected lineup. Use retained data and fixtures for development; report this as integration evidence, not live readiness. Avoid another standalone diagnostic milestone unless it answers a named integration blocker.
2. **Concurrent external dependency work:** establish ProphetX production eligibility and resolve units/update semantics; request Novig QA/production provisioning; select the two alternative sources and confirm access. This work should begin now, not after all two-venue collector work is finished.
3. Complete the two additional prediction adapters in the shared runtime and activate the two selected reference paths. Validate normalization, event/period/outcome matching, source-family handling, current estimates and original-input arithmetic.
4. Finish the daily-use history/outcome/settlement work and practical recovery needed by the agreed beta loop. Run a separately scoped six-source integration session, fix observed product blockers, then collect representative session evidence.
5. Offer the beta signoff walkthrough only when the above acceptance scope is implemented and evidenced. Technical previews can happen earlier, explicitly labeled as previews.

Do not wait for external credentials to do independent integration work. Conversely, do not count offline scaffolding as completion of a provider dependency. New live access, spending, outreach and implementation are not performed by this assessment. Existing consumed attempts and limits remain unchanged.

## Where the owner can help

| Dependency | Concrete owner help | Engineering responsibility |
|---|---|---|
| ProphetX | Confirm production account/API approval or help obtain it; forward provider clarification about Trading V4 quantity/value units and selection updates | Prepare precise questions, interpret responses and implement/verify sizing and streaming; do not keep repeating quiet captures |
| Novig | Request issued OAuth client credentials and QA/production provisioning instructions using the [prepared unsent request](novig-access-request.md) | Confirm wire behavior, limits, settlement/fees and integrate the existing adapter |
| Two alternative sources | Name existing subscriptions/access and preferred sources; provide a monthly data budget only if paid access is acceptable | Compare overlap, timestamps, cadence, source independence and cost; recommend the smallest useful arrangement before purchase |
| Beta scope | Confirm sport/market breadth, usual session length and required signal types | Turn answers into concrete acceptance checks and a short ordered implementation backlog |

Credentials belong in the documented local secret store, not chat. Recorded access status is from retained project handoffs; no account or Keychain inspection occurred in this assessment.

Official public documentation checked September 20: [Novig authentication](https://docs.novig.com/api-reference/authentication) requires credentials from Novig; [ProphetX production transition](https://docs.prophetx.co/docs/prophetx-service-api-switch-to-production) requires production keys and API-approved access. [The Odds API](https://the-odds-api.com/) and its [V4 guide](https://the-odds-api.com/liveapi/guides/v4/) are candidate aggregation options, not selected subscriptions or verified account access. Two bookmakers through one aggregator may satisfy pricing breadth if the owner agrees, but do not supply two independent delivery paths.

## Assessment limits

Reviewed current local docs, implementation paths and retained evidence; checked public provider documentation. No tests, live collection, beta launch, account access, credential access, external messages, purchase, commit or push occurred. Prior offline PASS remains valid for its recorded candidate and scope. This document does not requalify a changed candidate or claim current hosted CI.
