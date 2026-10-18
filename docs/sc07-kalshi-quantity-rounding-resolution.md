# SC07 — Kalshi personal website quantity and rounding

> October 17, 2026 status: Historical source review. Current work follows the [read-only data handoff](sc07-ready-handoff.md). The provider inquiry is unsent and is not queued.

October17, 2026. **No new operative website rule was established.** The three
target facts remain unsupported for standard personal website entry on
`KXNFLGAME-26OCT18HOUJAC-JAC`, buy YES, Jacksonville wins. Owner channel and
authorization are resolved; no repeat question is pending.

| Required fact | Current disposition | Exact missing specification |
| --- | --- | --- |
| Minimum positive contract quantity | Unsupported | Affirmative personal-website minimum for this contract; API `0.01` representation is insufficient |
| Quantity increment / V2 equivalence | Unsupported | Explicit website contract increment, or authoritative website→V2 regime mapping with the positive minimum separately specified |
| Operative balance/fee rounding | Unsupported | Website-specific accounting specification or explicit mapping to the applicable legal precision branch, including per-order accumulated partial-fill treatment |

Retained API documentation supports six-decimal fee computation, separate
`0.0001`/`0.01` balance alignment branches and per-order accumulation. Neither
generic membership terminology, no-intermediary setup, displayed cents, dollar
entry steps nor illustrative fills selects the operative website branch.
Actual future fills are not required for pretrade modeling.
[Retained rounding source](../test-results/sc07/source-review/primary/kalshi-rounding.md)
and [V2 input schema](../test-results/sc07-hou-jac/source/kalshi-create-order-v2.md)
keep their original retrieval clocks and channel scope.

The new bounded route was declared before retrieval: Member Agreement for an
explicit channel mapping, the personally linked fee-schedule PDF for an
independent rounding specification, and the unfetched Limit Order Purchase
article for stated quantity constraints. Limits were three public GETs,
20 seconds/2MiB per response, 6MiB total and eight minutes, with no retries,
redirects, authentication or browser navigation. Two requests occurred at
14:05:00–14:05:01 UTC: Member Agreement returned429 with a34,219-byte security
checkpoint; Limit Order Purchase returned403 with17bytes. The fee PDF was skipped
before dispatch after the same-host refusal. No PDF or usable financial
specification was obtained; complete refusal-body capture is not a successful
document retrieval. The pass closed at14:05:02, without using the remaining slot.
[Plan, exact URLs, original responses, clocks and hashes](../test-results/sc07-quantity-rounding/research/retrievals.json).

A supported browser was available in the tooling inventory. No venue page was
opened to retry or work around the refusals. This is not an owner denial or a
claim that browser tooling remains unavailable.

The [ready-to-send provider inquiry](sc07-kalshi-quantity-rounding-inquiry.md)
asks only these three rules, their selected personal-website applicability,
effective version and exceptions, distinguishing display values from operative
accounting. It remains unsent; no contact, login, account lookup or transaction
occurred.

No application, model, facet, expiry or catalog change is justified. The existing
financial owner requires explicit balance precision and retains both branches;
no default was selected. The installed source/engine/assets are unchanged, so no
restart or new behavior test is needed. The existing63-test/22-optimized-test
evidence remains applicable; focused checks cover documents, retained hashes,
unchanged loaded identities and protection/resources.

[Current bindings and closeout](../test-results/sc07-quantity-rounding/manifest.json)
retain the latest separate SQL/readiness snapshots and unchanged original wording.
The consumed three-request fee operation, selected fee regime, OT/tie linkage,
price band/face and US retail facts are preserved. Stale active handoff text now
states that fee authorization/acquisition are completed. Historical receipts and
original clocks were not rewritten.

Complete mandatory charges, exceptional joint cashflows, complete applicable
models and exact destinations remain separate SC07 dependencies. This slice
opens no genuine window: `entry_blocked_not_started`, zero declarations and null
T0/cutoff. Aggregate uncertainty/holds and hosted CI/owner SC08/Q04 stay separate.

**Current next action:** deliver the [read-only collected-data loop](sc07-ready-handoff.md). The retained source questions are optional future modeling evidence.
