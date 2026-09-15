# Slice 13B — personal-prototype backend checked

**Complete for the owner's revised personal-prototype backend scope. Strict performance qualification is deferred.** The owner is using this alone to prove that the product works and asked to push extreme performance logic and testing to later. [Owner direction](owner-scope.md) and the [current plan](../../../docs/slice-13-follow-up-plan.md) define the active scope.

The original frozen 250 ms gate did not pass. [Its results](summary.json) and every earlier measurement remain unchanged; they are not reclassified as passing. Completion here refers to the explicitly revised functional scope, not that former performance contract, a new live-feed run or owner acceptance.

## Working loop and checks

- The actual Controller and disposable PostgreSQL passed Start → updated synthetic view → Stop → saved reopening, including historical ineligibility and exact replay.
- 365 offline tests passed. All 42 PostgreSQL/storage tests and JavaScript syntax passed. [Verification and exact identities](verification.json), [storage/lifecycle log](personal-prototype-checks.log), [offline log](final-offline.log).
- The earlier 28 supported sessions and 18 expected fault scenarios use identical application source. Their capture, throughput and shutdown checks pass; the timing gates do not. The final source identity additionally includes the new end-to-end integration test. [Matrix](final-matrix/measurements.json), [faults](final-faults/measurements.json).
- All original 734 evidence/PLAN artifacts are preserved. Disposable clusters were removed. No owner app restart, owner database access, venue request, new live scan, trading, publishing, commit or push occurred. 13C was not started.

## Architecture and concurrency ownership

Capture owns its mutable pipeline state and database connection. A snapshot freezes market/matcher/fee state, evaluation time, observations and exact committed receipt identities into internal immutable bytes. Original input times are preserved. One compute/view worker owns its own connection, receives only immutable snapshots and returns immutable result bytes. One pending evaluation signal coalesces intermediate evaluation requests; it does not discard observations or hold a growing snapshot queue.

View persistence reads session scope without the capture writer lock because the controller exclusively owns lifecycle and waits for the view worker before finishing the session. Other storage writers use a NO KEY UPDATE row lock, preserving their serialization while permitting independent foreign-key references. Snapshot observations/receipt bindings come from committed state. No connection or mutable pipeline is shared across workers.

Session, invalidation epoch and sequence guards reject stale/out-of-order publication. Disconnect and Stop immediately remove current eligibility; request-time freshness still uses the original timestamps. One bounded depth request stays on the capture owner, with new requests refused behind capture. Stop closes producers, drains accepted work, waits for compute/publication/depth, closes both connections on their owners and then finalizes. The view connection checks the shared stop budget before each SQL operation. Cancelling an await is not treated as cancelling a worker.

Artifact compilation builds the identical tree format bottom-up and reuses shared objects within one call. Prepared writes are deduplicated only inside the outer publication transaction, with the write set cleared on rollback. Independent readback and exact replay remain in place. Targeted tests cover concurrent capture/snapshot consistency, old-session/out-of-order completions, disconnect, Stop during compute/depth, compute/publication failure, bounded pending work, rollback and connection ownership.

## Measurements and resource bounds

Capture remains bounded to 48 queued items / 1 MiB. Snapshot bytes are capped at 8 MiB, result bytes at 32 MiB, and decoded snapshot/result object checks at 64 MiB apiece. There is one in-flight refresh chain, one pending signal and no pending snapshot queue. Artifact compilation retains no cross-call object cache. Final exhaustive memory/stress experiments were deferred under the revised scope; enforced bounds, prior capture-memory evidence and targeted boundary tests remain distinct from such qualification.

The original baseline and successive `smoke*`, `matrix1`, and `final-matrix` directories preserve before/after candidates. The full run records snapshot/scheduling, detector, view preparation, artifact preparation, database persistence and publication timing separately. Input age and coalesced evaluations remain separate. Discarded completions do not count as actual current-view publications. No slow samples were removed and no duplicate views were introduced to pass cadence.

Ordinary input spacing, scheduling and expensive-work variability still cause misses against the deferred 250 ms maximum. This is a useful future baseline, not a reason to keep optimizing ahead of the owner's first useful prototype. The next small implementation is truthful saved-status/coverage presentation in 13C, followed by separately authorized supervised owner use.
