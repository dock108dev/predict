# Slice 13 follow-up — reliable bounded capture and truthful session status

Prepared September 14, 2026 UTC (September 13 New York). **Planning only; implementation and new live collection have not started.**

The next engineering implementation is a Slice 13 follow-up, divided into 13A–13E below. These are local follow-up labels, not a renumbering of the original roadmap. Slice 14 remains the Crypto.com adapter. The deliverable is a bounded Kalshi/Polymarket US scan that handles measured bursts, stops predictably, and accurately explains what was saved. Always-on collection and profit sorting are subsequent work.

## Review findings and evidence

- The [current tracker](/Users/michaelfuscoletti/Desktop/prediction_arb_next_steps.md) records two owner-review sessions ending on queue overflow, each with 32 queued observations unprocessed. The recorded session IDs are `ed06c7d1-ae22-4ed8-8b90-bec4e22e2917` and `c93f79fe-d2c0-4c33-bf97-7ba5fe61a17f`. Manual Stop and on-demand depth were not established by that review.
- The [saved review evidence](/Users/michaelfuscoletti/Desktop/prediction-arb/evidence/slice-13-owner-review/20260914T002407Z-readiness-and-saved-sessions.json) directly contains the complete/gap mismatch for a reviewed saved session. It also contains a separate synthetic runtime snapshot; its runtime block must not be presented as the reviewed production session or today's runtime state.
- Source inspection confirms `Controller.offer()` stops acceptance on a full 32-entry queue. `_consume()` exits when the stop event is set, leaving queued work behind. Finalization passes the remaining count to `Pipeline.finish()`, which records a gap but selects `complete` whenever its separate failure flag is false. Overflow does not itself set that flag. This explains the status mismatch, but does not establish why arrival rate exceeded processing capacity in the owner run.
- Every `Pipeline.book()` saves normalized observations and then recalculates and persists the complete detector/view. Depth uses the same one-thread executor. Both are plausible contributors to backlog; neither is a measured root cause yet. Existing tests establish the overflow stop, not successful burst absorption and draining with real storage.
- Additional directly observed code risks belong in this repair: stop reasons can overwrite one another; the saved view displays runtime message counts from the active controller; the session picker reads lifecycle state without coverage; all finalizations currently emit a `gap`, even clean bounded shutdowns. Historical detail can display the original `current` evidence class without explaining that this is capture provenance.
- Current file check: the Slice 13 manifest hash remains `35fd07e7a1f8c5284d5d75e5d67fe7630546976c54f06a86cfe1b6863bfaf931`. Of its 55 entries, 54 still match; the mutable Desktop tracker differs, consistent with later review edits. Preserve the historical manifest and record a fresh implementation identity later. No current runtime or database state was queried for this plan.

## Sequence and exit gates

| Follow-up | Deliverable | Dependency / exit gate |
|---|---|---|
| 13A | Reproduction, queue accounting and measured bottleneck | Reproduce the failure with controllable input and real disposable storage; save baseline measurements. |
| 13B | Bounded capture throughput and deterministic shutdown | Preserve accepted work within declared limits; account for every omission; no unbounded queue or shutdown. |
| 13C | Consistent lifecycle, coverage and saved-session presentation | Database, API, picker, banner and details agree, including old sessions with contradictory status. |
| 13D | Offline, database and browser regression evidence | All relevant gates pass on one identified candidate before production verification. |
| 13E | Supervised production verification and owner handoff | Manual Stop, deadline, saved reopening and depth are evidenced within a fixed budget; stop at review. |

13A precedes throughput decisions. The status contract in 13C can be designed alongside 13A, but must be verified against the final shutdown implementation. 13D gates 13E. A failed gate ends dependent verification; preserve the failure and repair on a fresh candidate.

## 13A — diagnose and account for capture work

**Tasks and proposed solution**

1. Add a bounded fixture producer that emits book updates, bursts, disconnects and quiet intervals. Use retained source data where suitable, but label accelerated replay as historical/replay evidence. Reproduce a 32-item backlog and overflow without contacting venues. Do not claim the old sessions' precise arrival timing is known if it was not retained.
2. Measure bootstrap time, input rate, queue entries and estimated bytes, high-water marks, oldest queued age, worker queue wait, receipt persistence, calculation/view persistence and depth duration. Measure both the default two markets per venue and supported maximum four.
3. Separate units: wire messages, offered book/control items, accepted items, rejected items, processed items and retained per-side observations. A wire message is not one observation. Assign stable item IDs and receipt bindings so shutdown can reconcile accepted items with their persisted or explicitly unprocessed disposition.
4. Benchmark the current pipeline with real PostgreSQL in a disposable project database, including slow writes and depth requests. Record environment, fixture identities, rates, durations and bounded sample statistics. Select a reproducible burst envelope from measurements before implementing the fix; do not tune the acceptance fixture merely to pass.

**Acceptance:** a failing reproduction plus baseline report identifies which stages consume time and explains all item counts. Unknown upstream messages or loss remain unknown. Metrics never retain secrets, signed headers or credential material.

**Likely files:** `app/dashboard/controller.py`, `pipeline.py`, `live.py`, `tests/test_dashboard.py`, `integration_tests/test_dashboard_storage.py`; a new bounded replay/benchmark helper and new evidence directory.

## 13B — repair throughput and shutdown

**Tasks and proposed solution**

1. Preserve immutable observations through the existing storage layer. First reduce measured redundant work: reuse a normalized image within a book operation, use small bounded transaction batches where beneficial, and batch detector/view refreshes at an explicit maximum interval. Start by testing a 250 ms refresh interval; retain every accepted observation even when intermediate views are not calculated. Record the actual evaluation cadence and skipped evaluations; do not claim intermediate opportunity detection or duration. Do not silently coalesce raw capture or adapter delta reconstruction.
2. Keep a bounded queue with both item and byte limits. Derive final capacity from measured burst size and worker drain rate, publish the chosen memory ceiling, and enforce it before accepting items. Increasing 32 alone is not sufficient evidence of a repair. If measured persistence still cannot support the chosen input envelope, report that limit and keep overload as an explicit incomplete stop; do not expand this slice into Redis or a new durable streaming service.
3. Give capture priority over on-demand depth. Allow at most one bounded depth request and refuse/defer new depth work when capture is behind. If measurement requires a separate compute worker, pass an immutable, versioned snapshot and serialize any database write back through its owning writer. Never share a live connection or mutable pipeline state across threads. Bind depth to its actual input receipt IDs and timestamps.
4. Separate stop-requested, producers-closed, draining and finalized states. On owner Stop, deadline or overload: disable acceptance immediately, invalidate live eligibility, cancel/close subscriptions, then drain accepted items within a declared budget. Proposed target: close producers within 2 seconds and finish saving within 10 seconds after Stop under the supported test envelope. Budget includes in-flight work and finalization. If work cannot complete safely, expose failure/incomplete coverage rather than pretending a thread was cancelled.
5. Preserve the first stop trigger, timestamp and initiator; append later shutdown/failure reasons separately. Repeated Stop must be idempotent. Finalize once, after any database-using depth operation has settled. Prevent a new scan until shutdown finishes. On database failure, retain a sanitized journal with accepted/committed/unprocessed counts and the last durable item identity where known.
6. Enforce receipt, raw/normalized payload, byte and scan-time bounds during drain. Receipt/storage exhaustion can prevent draining, and must produce explicit unprocessed counts. Do not extend the network collection window to save backlog. Ensure transaction rollback does not leave in-memory receipt counts, sequence IDs or current-book bindings ahead of durable state.

**Acceptance:** the agreed burst envelope produces no rejected accepted-work path, no unexplained loss and a drained queue on clean stops. Overload beyond the envelope still stops within bounds, accounts for rejected and remaining work, and cannot produce a complete-coverage label. Quiet streams, Stop during discovery, Stop during depth and database failures remain responsive.

## 13C — truthful status across storage and the dashboard

**Tasks and proposed solution**

1. Keep lifecycle separate from capture coverage. Reuse existing database states `running`, `complete`, `interrupted`, `failed`; add a versioned coverage summary using existing metadata/events unless a schema change is justified. A successfully finalized session is not proof of continuous venue coverage.
2. Use this terminal mapping for new sessions:

| Condition | Stored lifecycle | Primary display / coverage |
|---|---|---|
| Owner Stop or deadline, all accepted items saved, no known capture gaps | `complete` | Stopped by you / Time limit reached; accepted observations saved within the bounded scope. |
| Queue overflow, rejected items, or exhausted drain budget | `interrupted` | Stopped with capture gaps; show rejected and unprocessed counts. |
| Persistence/calculation failure | `failed` when persistable | Scan failed; coverage incomplete; journal availability if applicable. |
| Runtime gone without a reliable final record | Preserve existing record pending explicit recovery | Incomplete / coverage unknown; never imply resumed collection. |

3. A successfully drained scan can still contain disconnect or upstream reconstruction gaps. Retain these independently and show “Saved with gaps” or “Coverage unknown” as applicable. Record normal bounded endings as shutdown/limit events, not invented gap events. Do not interpret `continuous_coverage=false` or a legacy zero-queue shutdown by itself as proof that accepted observations were lost.
4. Build one shared session-summary projection for the picker and saved details. Evaluate all relevant coverage events, not just the current 100-event display window. For legacy `complete` sessions with explicit backlog/overflow, derive “Saved with capture gaps” without rewriting immutable historical records. Missing legacy counters stay unknown. Distinguish original stored lifecycle from the corrected display interpretation in expandable evidence.
5. Expose stop reason, time, queue/drain status and coverage while stopping and after stopping. Persist final session-specific message and observation counters; reopening one session must not borrow counters from another live or synthetic run. Show “Captured from a live feed” for provenance and “Saved observations; not live” for present eligibility. Keep original technical evidence class available with that explanation.
6. Preserve Live/Historical/Synthetic isolation, Decimal strings, per-leg freshness and disconnect invalidation. Unknown net profit, fees, settlement and sizing remain unknown. No ranking work is needed for this follow-up.

**Acceptance:** the two recorded legacy failure patterns show capture gaps; a clean shutdown shows a bounded ending; a missing summary shows unknown coverage. Database/API/UI reasons and counts agree. Historical/synthetic results never become current opportunities.

**Likely files:** `controller.py`, `pipeline.py`, `repository.py`, `server.py`, `views.py`, `static/app.js`, `static/index.html`, `static/style.css`; storage changes only where existing APIs cannot represent the contract.

## 13D — regression and evidence package

- Test an accepted burst, overflow, byte/receipt limits, manual Stop with backlog, quiet deadline, discovery cancellation, disconnect/resync, repeated Stop, reason precedence and Stop during depth. Assert actual accounting and terminal states, not only that a stop event was set.
- Use disposable PostgreSQL to verify transactions, rollback counters, write/lock failures, interrupted finalization, failure journals, exact calculation replay and reopening legacy gap sessions. Preserve owner sessions and original evidence; any migration needs independent rollback/restore verification with scanning stopped.
- Verify responsive controls, stopping/saving/failure labels, session-specific counts, old gap sessions, no stale cross-session depth result, and clear saved provenance in desktop and 390 px layouts. Exercise unknown profits and a zero-qualified-result screen.
- Run the offline suite, relevant PostgreSQL integration suites, all existing examples and JavaScript syntax validation once on the final candidate. Run database examples serially with capture stopped. Record actual new results; historical counts of 340 offline and 32 integration tests are a baseline, not this candidate's result.
- Save new reproduction inputs, measurements, test/browser evidence and a manifest under `evidence/slice-13-follow-up/`. Identify source files, original plan hash and preserved historical artifacts. Keep technical qualification and owner acceptance as separate fields.

**Acceptance:** all required checks pass; any residual bottleneck is quantified and within the declared bounded envelope. No new live scan starts merely because documentation was prepared.

## 13E — bounded production verification after implementation is authorized

Proposed finite verification budget: at most three supervised live starts, each at most 60 seconds, using the existing default two-market-per-venue NFL scope and existing 1,000 message/receipt and 128 MiB limits. Total network collection is at most 180 seconds. Existing credentials are used only through existing read-only adapters; no new accounts or venue access expansion. This plan does not start those runs.

1. Run one ordinary 60-second deadline scan with current discovery. Record selected identifiers, coverage, queue/rate/worker measurements, final disposition and replay results. Require zero unexplained/rejected/unprocessed items for the clean-run gate.
2. Run a second scan and trigger manual Stop after current updates are visible, targeting roughly 20 seconds and always within 60. Verify the owner/API stop reason, immediate loss of current eligibility, subscription closure, bounded drain and Historical reopening with matching counts. A test operator's manual Stop is technical evidence; owner-operated Stop and feedback are recorded separately.
3. Use the third scan to exercise on-demand depth while capture is active and verify Stop during or after that request. A supported “No sized result” is valid when inputs are unknown. Save/reopen the corresponding result; do not manufacture quantities or profitable results to exercise the screen.

Stop on the first required failure and save sanitized evidence. No silent extra live attempts. If discovery finds no usable overlapping markets or a venue is unavailable, record that limitation and leave the corresponding production gate pending; offline positives do not satisfy it. Recheck identity after repairs before any newly scoped verification.

**Done:** one identified implementation passes 13A–13D and the available 13E gates, with any pending production gate explicitly preventing a full completion claim. Hand off the Live → inspect/depth → manual Stop → Historical loop for owner review. Leave collection stopped. Zero qualified opportunities is an acceptable economic result and does not excuse capture gaps.

## After this follow-up

1. **Sustained supervised collection:** separately scope longer observation windows, measured throughput headroom, periodic discovery and metadata refresh, status changes, reconnect/resync, per-venue coverage, disk/retention budgets and controlled recovery. Always-on/autostart behavior needs its own explicit implementation scope; a clean 60-second run does not qualify it.
2. **Profit sorting:** separately add server-side Decimal sorting, stable tie-breaking and unknowns last, preserving distinct qualified/conditional/diagnostic groups. Known conditional values can be sortable as conditional values; supported fee applicability, compatible settlement and sizing are prerequisites for a qualified ranking. Sorting itself does not resolve those unknowns.
3. **Roadmap expansion:** Slice 14 Crypto.com, Slice 15 Fanatics and Slice 16 execution replay remain separately scoped. ProphetX and Novig limitations stay visible. Trading remains deferred.

**Concrete next engineering task:** implement 13A first, then carry the measured repair through 13B–13E within its agreed boundaries. The present task changes documentation only.
