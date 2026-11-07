# L03 — grouped live ranking and pinned inspection

You are the senior full-stack/API engineer for Predict. Work in the existing
`prediction-arb` main checkout. Read AGENTS.md,
`docs/live-comparison-plan-20261104.md`, the queue, L01/L02 outcomes and Desktop
next steps. Preserve dirty prototype work and protected state. No worktree or
commit/push. Inspect current sources and complete L01/L02 integration gaps needed
for this slice; do not infer completion from historical docs.

Read `L01-publication-contract.md` and `L02-financial-contract.md` in this
directory. Integrate the delivered `/api/comparison-current`, cursor `/updates`,
exact `/selection` and bounded lease/immutable-details contract. Roots assemble
multiple coherent matching components: assembly time is not a source clock;
`evidence_result_id` identifies the selected exact member. An expiry/control/policy
cursor change can invalidate results without a new root generation.

Default after-fee ranking uses current numeric `conditional_return_percent` in
the supported common risk basis. Consume `metric_status`, `current_authority`,
`price_current` and typed reasons. `conservative_return_percent` and its benchmark
are separate owner-authorized estimates, not verified account fees; expose them
only in an explicitly labeled estimate basis, never as an implicit fallback into
the default rank. Preserve `reference_calculation`, full member evidence and
price/economic revisions, including null economics while finance is pending.
Kalshi membership/intermediary facts and ProphetX account terms remain external
inputs; do not manufacture them. Account-authorized public-schedule estimates
remain useful independently of those missing facts.

L01/L02 are integrated, not fully qualified for sustained currentness. Native
latency tails and storage-maintenance interruptions remain engineering concerns.
Distinguish these from missing financial input support. The latest handoff records
31 held credits / 12 unresolved attempts; inspect current accounting and preserve
all protected exposure before any operational action.

Deliver the current ordinary read contract and group the entire filtered
comparison universe by exact display outcome before pagination. Return all
relevant source offers together, including unavailable finance and distinct
native instruments. Preserve separate predicates, periods, signed lines and
occurrences; display grouping never creates settlement qualification.

Rank outcomes by their maximum eligible exact after-trade-fee EV and identify
the source setting the score. Never substitute gross, missing-as-zero, incompatible
fee sizing or stale/model-expired values. Use deterministic ties; retain zero,
negative and unranked outcomes. Preserve useful search/league/family filters and
ordinary Markets navigation. Provide accurate counts, typed per-source states,
Pinnacle reference bindings and bounded coherent pagination through replacement.

Provide a revision-bound selected Math & fees context independent of the rolling
list. A material relevant replacement yields old/latest change facts; opening a
new row uses what was actually clicked. Use latest prices atomically adopts the
newest compatible selection and every dependent field. Handle missing/expired/
removed rows, policy changes, stale responses and source withdrawal explicitly.
Identical confirmations should not trigger endless notices. Release bounded
leases when closed/replaced and retain required protected evidence.

Verify whole-universe rank against an independent exact oracle, complete grouped
pagination without source splitting, ties, negative/unknown values, source and
reference-only updates, expiry and coherent read retries. Check old/new concurrent
responses and pinned/adopted inspection identities. Test realistic broad volume
and report useful-page latency against the existing two-second target. Ordinary
reads must not dispatch acquisition or mutate account/quota/due state. Build and
restart app/data as needed; update contracts, queue and next steps for L04.
