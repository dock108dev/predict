# Predict — expanded beta delivery plan

Updated September 20, 2026. This plan implements the owner's [current beta scope](product-roadmap-review.md). **Beta not ready.** No B1–B7 package is complete merely because an earlier D/E/slice component passed.

## B1 — working coverage map and integration scope — COMPLETE

Delivered September 20, 2026: [source × sport × market/period matrix](b1-coverage-matrix.md) and [concrete B2 implementation handoff](b2-product-integration-handoff.md). The assessment covers all six sports, four prediction-source slots and both reference types, with production/sandbox/fixture/documentation evidence separated, explicit unknowns, source recommendations and an owning-slice dependency ledger.

Recommend ProphetX for the fourth venue; owner selection and production access remain B3 dependencies. The Odds API's documented free tier and website-sourced Pinnacle listing are a promising B4 route, not verified account entitlement or known delay. Sport-specific model candidates and their output/independence gaps are recorded. B5 owns final halftime/period, futures and NCAAB definitions. These unresolved data questions do not make B1 incomplete or block B2.

B1 included code-path inspection, retained-evidence review, targeted official public research and document reconciliation. No B2 implementation, beta launch, credential/account access or new authenticated collection occurred.

## Missing-data work belongs to the slice that uses it

| Slice | Unresolved data/information to address during that slice | If unavailable |
|---|---|---|
| B3: prediction venues | Novig provisioning and wire samples; fourth-venue selection/access; ProphetX size/update semantics if chosen; US Short depth and source-specific discovery/fees/terms | Mark the affected source/side incomplete, request precise owner/provider help, continue other integration work |
| B4: references | Free delayed Pinnacle route and actual delay/coverage; current power-index provider(s), sport coverage and usable probability/line outputs | Keep missing inputs explicit; continue reference plumbing and independently supported calculations; do not silently substitute paid data or another reference type |
| B5: sport/market breadth | Native IDs/listings, half/period definitions, futures categories, NCAAB competition scope, result/settlement sources and seasonal samples | Resolve the relevant definition before implementing that mapping; continue independent sports/families; label unavailable samples and seek an explicit exclusion only if needed for beta signoff |
| B6: integrated use | Actual joint coverage/cadence, session length, provider limits and resource measurements | Scope the run from available evidence; leave unmet beta criteria open rather than pretending all data problems were solved |

The [B1 dependency ledger](b1-coverage-matrix.md#owning-slice-dependency-ledger-and-owner-help) records current evidence, exact owner assistance and completion checks. Maintain each dependency's current evidence, next action, engineering/owner/provider responsibility and completion check. Unknowns are work items, not assumptions of success and not a blanket project stop. The four-plus-two/six-sport beta floor stays unchanged while slices progress.

## B2 — connect collection to the product — NEXT

Implement the [B2 handoff](b2-product-integration-handoff.md), including its versioned projection contract, exact module changes and focused acceptance checks. Reuse `ContinuousSession`, `CoverageOwner`, native adapters, journals, canonical matching and the existing calculation engine/UI. Connect coverage-session observations to current comparison rows in `multi_game_server.py`; remove hardcoded two-venue/event/side assumptions through reusable identities. Keep per-source catalogs (including unmatched markets), health, exclusions and fresh/current versus saved data visible. Preserve Start/Stop ownership and history.

Exit: retained-data and fixture integration shows multiple venue combinations, model/reference roles, correct period/line isolation, unavailable-source behavior, current updates, Stop and reopening through one ordinary UI. Fixtures prove integration only. B2 can proceed while access for B3/B4 is pending.

## B3 — four prediction venues

Finish shared-runtime ingestion for the selected fourth venue and Novig; extend Kalshi/US coverage to the confirmed universe. Qualify actual production discovery/books, usable sides/depth, terms/fees and recovery within a newly scoped live allowance. Keep US Short depth and coverage limitations explicit. For ProphetX if selected, resolve quantity/value semantics and actual update delivery before sized comparisons.

Exit: each of four venues has observed production input, integrated health/history and useful comparison participation; source-specific gaps are visible. Offline adapters do not count. No inference of full exchange delivery from short samples.

## B4 — model reference and free delayed Pinnacle

Implement repeatable acquisition for the selected power-index/model provider(s) and the verified free Pinnacle path. Retain model version/as-of time, source time where available, receipt time, actual delay evidence, native prices, source family and market identity. Derive supported estimates transparently and show unresolved mappings. Preserve delayed estimates as delayed; no live-quality timing prerequisite merely to display correct labeled arithmetic.

Exit: both requested reference types appear in game/market details and supported EV calculations with reproducible original inputs. No forced win-probability conversion from raw team ranks; no invented spread/total/futures forecasts. Unsupported model-market cells stay explicit beta gaps for decision.

## B5 — six-sport market coverage and usable history

Build sport/competition/season/team identities and family-specific normalization/matching for moneyline, spread, total, agreed halftime/period scope and futures. Handle line changes, pushes, ties, overtime rules, postponed events and multi-outcome settlement where relevant. Preserve raw data and exact calculation basis. Complete result/settlement linkage, pending futures handling, storage bounds and saved-session operation needed for actual use.

Exit: coverage matrix reconciles implementation and evidence for every requested family/sport; unsupported listings are not mistaken for bugs or silently removed from scope. In-season real samples and explicitly labeled out-of-season fixtures/history are distinguished. Owner agreement is required for any beta exclusion, not for routine implementation choices.

## B6 — integrated engineering readiness

Run focused original-input math checks and an ordinary six-source dashboard flow across representative supported markets. Propose an initial 30-minute integration session and then a representative viewing session; these durations require their own reviewed resource/live scope and are not approved by this plan. Demonstrate updates, freshness/gaps, disconnect recovery, useful comparisons, Stop/finalization, interrupted history and exact saved reopening. Finish with a short acceptance matrix of pass/fail/not-tested and concrete blockers.

Exit: agreed beta criteria met with no hidden source/sport/market exclusions. No profitability requirement, blanket low-latency SLA or production-hardening detour.

## B7 — owner beta review

Only after engineering readiness, guide one short action at a time through the product, offer technical drilldown, record modifications verbatim and finish with a short-answer survey on utility, clarity, trust, changes and explicit verdict. Keep engineering PASS, owner acceptance and future live expansion/release separate.

## Scope and execution boundaries

The B1 request authorizes the completed assessment and documentation handoff only. B2 implementation, beta launch, new collection, account/credential access, spending, outreach and trading were not performed. B2 remains the next engineering task. Independent engineering can be instructed without waiting for every provider. Preserve existing work/evidence and consumed attempts; any changed source/runtime requires applicable new verification. No automatic reuse or reset of historical run allowances.

## Retained foundation

D1 inventory, D3a segmented replay, bounded two-venue live results, one-market diagnostic PASS, saved multi-game calculations, normalization/matching/fees/depth and reference scaffolding remain reusable. Their old next actions are superseded. See [gap assessment](beta-gap-assessment-20260920.md) and [planning snapshots](history/beta-reset-20260920/README.md).
