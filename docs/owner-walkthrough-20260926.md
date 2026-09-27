# Formative owner walkthrough — September 26, 2026

Status: initial product-direction feedback received; original navigation task superseded. This is usefulness feedback, not beta acceptance. No application patches during review.

## Exact starting state

Ordinary documented launcher, source checkout `/Users/michaelfuscoletti/Desktop/prediction-arb`, HEAD `521c8d1e9c83cfb5eb88127fd320ae7d682a81e7`, initially clean. Fresh process PID 15958 at http://127.0.0.1:8784; working directory verified. Port 8783 was occupied and left untouched. Idle, no collection session, Start disabled because no valid approval is configured. No credentials or provider requests used.

Selected saved session `5accf9ee-94b9-4b09-8130-6849f842155e`, September 16 at 14:57 UTC: six historical real-observation NFL games. These are not current prices. Browser shows 12 pairs including negative conditional and unavailable results. Historical fee scenarios are not newly qualified economics. Preparation and application source hashes: [evidence](../evidence/owner-walkthrough-20260926/preparation.json), [source manifest](../evidence/owner-walkthrough-20260926/source-manifest.json). All 13 review7 manifest files verified unchanged; retained test results remain bound to their historical candidate.

## Owner task and feedback log

1. Presented: “Find the Lions–Bills game using whichever controls seem natural, then tell me what you tried and anything that felt unclear.” Completion not observed. Owner instead gave initial-screen feedback; do not continue this task as if the screen meets their intended workflow.

Owner wording, on the historical six-game table: “This isn't really what I was expecting at all.” “This is way too admin-y.” “I was expecting more just the opportunities would pop up automatically.” “If we have to, like, simulate that for a little bit, I get it.” “The rest, I guess, is okay.” “Contracts per leg. I don't know that that really is something we need to know.” “Opportunity cards sorted by expected value, not whatever this is.”

Engineering interpretation (not owner wording): the primary product should be an automatically populated opportunity-card feed. Collection configuration, saved-scan selection and sizing mechanics should be secondary. A labeled isolated simulation is acceptable for formative review while real feeds remain unqualified. This does not authorize real automatic collection, recurring jobs, or application patches during review. “The rest ... is okay” is not acceptance of unreviewed functionality. The later EV% clarification below resolves the comparison basis; manual What-if EV remains distinct from sourced model EV and arbitrage return.

Unreviewed: filters, coverage/timestamps, stale/unavailable interpretation, EV/reference distinctions, Details economics, original-input reopening, synthetic active operation/recovery. No beta acceptance inferred.

2. Owner clarification after the card discussion: “100% real data.” “We need to make sure that somewhere in here we're figuring out the real data and what's missing to do that.” “Not just from two sites either, from all four.”

Engineering interpretation: the delivered automatic opportunity feed must use actual data from all four selected venues: Kalshi, Polymarket US, Novig and ProphetX. Simulation is only a temporary formative layout aid, not the delivery target or evidence of source readiness. The existing four-venue requirement is reaffirmed, not a new scope expansion. Track source qualification alongside the presentation package; do not let a two-venue diagnostic or a card mockup stand in for product completion. Real venue prices alone do not supply an independent model probability for expected-value ranking. Unknown fees, size, settlement, freshness and probabilities remain unknown. The subsequent EV% preference resolves ranking; all-four-source readiness remains a separate requirement.

## Subsequent owner scope correction

Owner clarified that analytics and gaming/bookmaker lines are extras for review only if easily available; the core is prediction-market feeds and related math. Analytics/models and bookmaker lines (including Pinnacle) are optional beta extras only when easily available, for owner review. Missing extras do not block beta and need no exclusion decision. Core requirements are the four real prediction-market feeds and their supported math. Keep the EV%-first preference wherever supported EV exists. Without a supported probability, show EV unavailable; continue showing valid price comparisons and fee/size/depth/settlement-aware arbitrage return under its own label. Never relabel arbitrage return or implied probability as model EV, and do not require external analytics to populate the core feed. This scope correction does not imply acceptance of any workflow.

## Remaining beta dependencies and next actors

### Resolved presentation preference: EV percentage

Owner wording: “Why does the amount matter? show everything as EV%s not dollars and cents”. This resolves the earlier ranking question: opportunity cards should lead with EV% and sort highest EV% first, not estimated dollar profit. Dollar/cents results and contracts-per-leg are not primary-feed controls or metrics. Amount matters internally when available size, price depth or fee rounding changes the effective return; preserve those inputs and explain any size-dependent limitation in Details rather than asking the owner to choose a stake before seeing the feed. Use a consistent disclosed return denominator (money committed, including applicable entry costs); unknown probability or material costs mean EV% unavailable, not zero. Do not relabel price, implied probability, arbitrage ROI or a manual scenario as sourced model EV%. Four-venue actual-data delivery remains required. No application changes during review.

| Blocker | Evidence needed | Next actor |
|---|---|---|
| Kalshi historical rules and fees | Effective contract amendment and applicable fee/rounding/settlement-charge scope | Owner may instruct dispatch of prepared inquiry; exchange supplies answer; engineering evaluates |
| Polymarket US applicability and charges | Historical contract/modification coverage and mandatory settlement charge or exemption | Owner may instruct dispatch of prepared inquiry; exchange supplies answer; engineering evaluates |
| Novig/ProphetX | Current nonsecret reply/provisioning status, issued access and exact native contract | Owner reports changes; provider provisions; engineering assesses |
| Actual venue and market breadth | Native IDs, prices, quantities, terms, timestamps, result/payout evidence across required scope | Engineering once prerequisites and bounded collection approval exist |
| Optional analytics/bookmaker extras | Correct source/date/meaning and supported inputs if readily available; missing extras do not block beta | Engineering only as easy supplemental context; no acquisition decision required |
| Joint real-source operation | Supported prerequisites followed by a concrete proposed duration, scope, limits and stop conditions | Engineering proposes; owner decides |
| Usefulness and acceptance | Actual owner tasks and feedback now; later exact qualified-candidate review | Owner with engineering facilitation |

KenPom and NHL analytics remain deferred; MoneyPuck remains dropped. Missing analytics/models and bookmaker lines are optional omissions, not beta gaps; no exclusion decision is needed. No acquisition decision is reopened here. Pinnacle allowance and public-research attempts are consumed. Kalshi/US inquiries remain unsent; older wording suggesting pending replies does not govern. No fresh book run is currently proposed.

## Consolidated engineering package

One consolidated engineering package: implement an automatically populated card feed in ordinary Predict, highest EV% first, with game/sport/market filters and secondary scan, saved-session and sizing controls. Use the existing shared calculation path and preserve original inputs, source age/coverage, unavailable/nonpositive cases and distinct Arb/model/What-if/reference meaning. A labeled isolated simulation is a temporary formative review mode; delivery requires all four real venues and supported related math; references are optional extras. Verify Details, saved reopening, Start/Stop and recovery together. See the [package and completion conditions](data-coverage-plan.md#presentation-and-workflow-package). No application patches have been made by this documentation update; completed B5/B6 engineering is not reopened.

## Later qualified beta review

Requires exact current candidate evidence, usable required prediction-venue and sport/market coverage (or explicit owner exclusions), supported economics, bounded integrated operation and reopening, plus a separate owner acceptance decision. Today's saved review does not satisfy real-source qualification, and the original navigation task and remaining workflows were not reviewed. The EV% decision is resolved. Next action: formative review of the locally completed [card candidate](opportunity-card-handoff.md); the [separate source-readiness workstream](market-data-gaps.md#all-four-venue-readiness) remains open. Final acceptance additionally requires automatic operation, Details, saved reopening, Start/Stop and recovery on the exact candidate, then an explicit owner decision.

## Local card candidate handoff

The consolidated card/workflow package is implemented and offline-verified. [Exact preview, candidate identity, evidence and one-task formative review](opportunity-card-handoff.md). This later engineering update preserves the earlier owner feedback and source decisions. Simulation does not establish real-source participation or owner acceptance; all-four-venue qualification remains open.
