# Admin API: predict-admin-1

`GET /api/admin/status` and compatible `GET /api/admin/current` project local
source, quota and issue state. Reading them does not dispatch provider requests,
consume credits or trigger recovery. `/admin` is a separate operator surface,
not hosted authentication.

`POST /api/admin/current` uses the shared same-origin JSON boundary and service
ownership rules for pause, Stop, guarded recovery and explicit aggregate refresh.
Refresh chooses its own sport scope without changing automatic scope or scheduled
due times; it uses the same ledger and affordability checks. Recovery preserves
spend, reservations, consumed attempts, uncertain charges and due times.
Native-only configuration stays aggregate-disabled during recovery.

## Conservative accounting recovery

The supported owned action is `recover_accounting`, with exact `runtime_id`, `candidate_digest`, `recovery_id`, and `covered_attempts` hashes. An inactive safely finished aggregate worker, exact expired uncertainty, current unchanged account/reset/credential evidence and ordinary ownership/resource/clock/cleanup gates are required. It makes one bounded no-retry independent `/v4/sports` balance observation. The transaction creates separate versioned authority and evidence; the original charge remains unresolved. Native collection remains independent. Failed evidence or an unrelated pause cannot be cleared by this action.

Quota projections add `held_uncertain_credits`, `covered_uncertain_attempts`, `recovery_authority`, `independent_balance`, `recovery_probes`, and `blocking_reason`. `reserved` includes all unresolved/reserved exposure and any confirmed charge whose inclusion in the latest balance is unproven. `available` subtracts that exposure and the existing reserve from the latest authenticated remaining balance. Original receipt/charge provenance and independent balance provenance remain separate. During an active owned request, the projected blocking reason applies to starting another dispatch; that request can still finish and reconcile through the ownership-bound lifecycle. No GET starts an observation or extends coverage. See [operation and recovery](../configuration.md#storage-and-recovery).

## Issues and resource bounds

Issues use provider/category/code plus exact scope/attempt/affected venues for
deduplication. First occurrence is preserved; last time/count advance. Different
attempts or affected venues remain distinct. Retention is bounded by configured
record and byte limits (defaults: 200 records and 1 MiB).

Persistence uses private temporary files, fsync and atomic replacement. Failure
blocks safe recovery rather than inventing clean state. Returned advice is
regenerated from the local safe vocabulary; credentials and raw provider payloads
are excluded. Historical issues retain their recorded provenance and cannot
become a current observation.

Current operation shares the [current state contract](predict-current-1.md).
See [configuration](../configuration.md), [security](../security.md) and
[failure recovery](../error-handling.md) for supported controls and limits.
