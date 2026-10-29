# Failure handling and recovery

The ordinary app reports current source issues and guarded recovery through `/admin`. Stop revokes dispatch and closes workers before releasing ownership. Recovery preserves spend, reservations, uncertain charges and due times; it does not reset accounting. The saved-session behavior below applies to the separate retained collectors.

The shared HTTP router distinguishes explicit public validation messages from
internal failures. `PublicRequestError` is reserved for authored safe validation
text. Other `ValueError` subclasses return a fixed 422 and log only the operation,
exception class and traceback locations. Do not copy arbitrary exception messages
into this public class. Duplicate query fields and non-object Admin bodies are
rejected before their handlers can act. See [local security](security.md).

Collection stops on persistence or unconfirmed resource cleanup failures. A saved
journal is not a completion receipt; only successful finalization publishes a
completed package. Use `/api/status` to distinguish stopping, saving and failed
states. Other valid saved captures remain available.

## Ordinary app and data runtime

The data runtime logs heartbeat/ownership failures as `data_runtime_heartbeat`,
withdraws dispatch through source shutdown, and exits failed. A secondary status
write logs `data_runtime_failure_status`; inability to persist a failure does not
make the last heartbeat healthy indefinitely. The app reader fails closed when
runtime storage is unavailable and logs `data_runtime_read`. Control submission
failure logs `data_runtime_submit`. A failure reading an already submitted
control's acknowledgment returns HTTP 503 `data_runtime_control_unknown` and logs
`data_runtime_control_result`. Inspect Admin and the data log before retrying:
the control may already have applied. The reader never resubmits it automatically.

Runtime shutdown attempts finite-operation, task, source, board, scanner, store,
database-connection and ownership cleanup despite an earlier failure. Every
failure logs a `data_runtime_*` operation and marks the process failed; the first
cleanup exception is re-raised after remaining attempts. Startup preserves its
original error or cancellation if cleanup also fails. Terminal status is best
effort when storage is unavailable. Cleanup remains cooperative and does not
establish a process-wide termination deadline.

A stopped scanner, observation, estimate or Coverage task is observed once and
marked unavailable without stopping independent healthy sources. Periodic board
and Coverage failures retain unavailable status and log `latest_board_*` on each
failure. Optional calculation failures continue to preserve independent source
observations. Cooperative calculation cancellation propagates through optional
financial work; expected cancellation during owner shutdown is normal.
Scanner reconciliation failures log `scanner_reconciliation` and publish the
fixed reason `scanner_reconciliation_failed`, excluding provider/storage exception
messages. Failed withdrawal of a scanner publication logs
`scanner_failure_withdrawal`; heartbeat, dependency and expiry checks still guard
read eligibility. Publication and selected-proof read failures log
`scanner_publication_read` and `scanner_selection_capture` and withhold authority.

Retained read workers log unexpected errors as `retained_read_worker`, even after
request cancellation or timeout. Their completion futures carry errors as data,
preventing detached asyncio diagnostics from exposing raw exception text. Expected
cooperative cancellation is quiet. Capacity stays charged until a launched thread
exits; failure to start a thread releases its lane and reservation immediately.

Optional scanner commit measurements run inside a savepoint. A failed SQL probe
rolls back that savepoint, logs `scanner_commit_probe`, and leaves the accepted
ingress transaction able to commit. No measurement is published for that failure.
Post-commit listener errors log `scanner_commit_listener` without undoing the
already committed data or skipping other listeners. Ingress transaction failures
still propagate and produce no successful-commit measurement.

Inspect `.local/predict-data-runtime/data.log` and the app instance's
`server.log` (normally `.local/opportunity-board-beta/server.log`) alongside
Admin. The data process boundary logs `data_runtime_process` and exits with code
1 for an unexpected startup/shutdown exception, suppressing raw traceback output. Diagnostic records use the safe
operation/class/frame format described below. These changes introduce no provider
retries, accounting recovery or automatic collection authority.

## Disposable calculation workers

Coverage and financial subprocesses keep the existing memory, reply-size and
wall-clock bounds. Unexpected calculation failures return a fixed worker error
and a safe exception-class/frame record. The parent logs `calculation_worker`
before reporting `coverage_worker_failed`; raw database exception messages never
enter that status. Child stderr remains discarded because third-party tracebacks
can contain private payloads. Failures before the child error boundary or abrupt
process death therefore have only the parent's generic failure, not child frames.

Stop and repeated cancellation join a shielded cleanup operation: a suspended
child is continued, terminated, then killed after the existing three-second wait
if needed. The owner waits for exit and consumes the reply reader. Cleanup errors
log `calculation_worker_cleanup`; they fail otherwise successful work and do not
replace an active primary exception or cancellation. OS-level termination failure
still means closure is unconfirmed; there is no new forced process-wide deadline.

`app.owned_work.joined_thread` is the shared completion policy for checkpoint/
accounting `owned_thread` work and raw dashboard reads. It returns failures internally as data,
preventing Python's detached-shield diagnostics from exposing exception messages.
Cancellation waits for actual completion; a concurrent failure logs
`owned_thread_after_cancellation` and cancellation still propagates. Without
cancellation, the original error propagates. Cancellation is not confirmation
that a write rolled back: inspect retained accounting/receipts before retrying.

Expected financial lock contention, serialization conflicts and deadlocks retain
explicit deferred results. They do not trigger provider retries or claim a
publication succeeded. Acquisition-pressure deferral, absent-process signal races
and optional-source isolation remain deliberate resilience.

## Aggregate admission and local contention

Aggregate diagnostics identify scheduled admission, reservation, transport,
accounting, decoding, normalization, database ingress and offered inventory.
`last_processing_failure` includes runtime, attempt, sport, receipt time/hash and
exception class; the data log records safe traceback locations without response
content, credentials or exception messages. A generic historical
`aggregate_admission_failed` does not establish malformed provider data.

A rolled-back PostgreSQL lock timeout, deadlock or serialization conflict retries
only the exact local ingress transaction, with cooperative backpressure. It never
requests the provider again, changes receipt/source clocks or releases uncertainty.
Stop revokes pending work before another attempt and before commit. Other database
errors remain terminal. Admin exposes retrying versus terminal worker behavior;
SQL prices are distinguished from the diagnostic cache.

Guarded `database_ingress_lock_retry` repair binds a confirmed response receipt to
an exact candidate and disposable SQL contention/Stop verification. It preserves
attempts, held credits, balances and due times. An evidenced OS restart may require
the existing clock-epoch transition and free accounting bootstrap independently.
A local repair is not authority to resolve an uncertain paid charge.

A transient failed OS boot-evidence read can also leave
`clock_continuity_unknown` after the OS probe recovers. Owned startup now restores
continuity only when fresh evidence proves the original boot ID/start, original
suspend-inclusive clock progression and unchanged current account window. The
ledger records `os_evidenced_continuity_restored` with
`existing_accounting_only` authority. This is a local accounting preparation:
attempts, holds, balances and due times are preserved, no new accounting epoch is
created, and no provider request is made. It can run outside collection hours;
ordinary paid collection still waits for 09:00 Eastern. Missing or contradictory
clock evidence, uncovered attempts and incompatible windows continue to refuse.
Do not clear the pause or edit the ledger manually to bypass that proof. See the
[repair evidence](acquisition.md#recovery-from-an-interrupted-os-clock-check).

## Socket and resource cleanup

Kalshi and Polymarket US streams retain socket-close failures (including timeout
and cancellation returned by the close operation) as exception classes in
`cleanup_errors`. Stop cancellation waits for an already-running bounded close
before propagating; a confirmed successful close is not a cleanup failure. The
shared `app.cleanup.close_outcome` captures close errors as results so shielded
tasks cannot leak raw exception details through asyncio logging. Streams log
`stream_connection_close` through the safe diagnostics helper, invalidate book
state, and stop reconnecting when closure is unconfirmed. Repeated `aclose()` calls
continue to raise a fixed, safe `OSError`; a detached socket reference or a closed
flag cannot turn the earlier failure into success. Existing cooperative socket
close timeouts remain three seconds for Kalshi and two seconds for US.

The shared `app.cleanup.close_all` attempts all supplied closes, logs each returned
failure as `owned_resource_close`, and raises the first failure in resource order.
It is used by native adapters, prediction producers, grouped stream venues and
native REST venues. A failed stream does not skip the REST client or later
resources, and a second failure cannot replace the first. A resource returning
cancellation counts as failed cleanup. Collector shutdown then records the failure
in its existing `cleanup_errors`, rejects completion publication and blocks a
subsequent Start. An active primary exception or cancellation survives secondary
stream-finalization errors; sticky close failures remain observable when the owner
closes resources. There is no process-wide forced termination.

Native group-task failures still isolate the disconnected source and await the
existing Stop/deadline, and emit `native_stream_task` diagnostics. Optional
reference failures still mark that source unavailable without stopping the other
sources, and emit `optional_reference` diagnostics. A failed projection callback
emits `acknowledged_projection` on each occurrence and retains `projection_error`.
The journal acknowledgement remains valid: failure to project already-persisted
data is not a storage failure. The existing current-snapshot path rebuilds flat
projections from the acknowledged journal prefix; segmented sessions remain
unavailable until verified reconciliation. No stale replacement results are added.

For these events, inspect the existing local server log and `/api/status` cleanup
fields. Logs contain operation, exception class and
traceback locations, never exception messages or provider payloads. Keep the
original journal and pending files. A close failure requires confirming process
exit before restart; repeating Stop does not certify that failed socket's closure.

## Startup and finalization

The continuous collector treats a failed or prematurely ended resource monitor
as a scan failure. It closes intake and requests Stop with
`resource_monitor_failure:<exception class>`, logs `resource_monitor`, and marks
the runtime failed after resource shutdown. Flat and segmented owners refuse a
completion manifest for this failure, even if the terminal journal was written.
Normal monitor cancellation during Stop is expected. Preserve the journal and
diagnostics so a failed capture can be investigated before collection restarts.

`CoverageOwner` enforces prior cleanup failure at Start itself,
before opening the collector lock or accessing configuration. Hiding/disabling the
browser button is not the enforcement boundary. Startup errors and cancellation
attempt collector Stop and lock release, then propagate the original exception.
A secondary Stop/release error is logged safely and recorded in `cleanup_errors`
when a session exists, preventing another Start in that process.

Flat coverage finalization retains replay/report diagnostics, but publishes no
completion manifest when replay fails, memory reservation prevents replay,
the terminal record is unacknowledged, or cleanup is incomplete. It writes/fsyncs
`manifest.pending.json`, checks the output cap including that file, then renames
it. Write/fsync/cap failures leave original data and any pending file intact.
The runtime state becomes `failed`; readable pending JSON is not a receipt.

Segmented finalization also checks the output cap before manifest publication.
Replay, publication and secondary failure-report errors log safe operation,
exception class and traceback locations, and set runtime state to `failed`.
The existing best-effort `finalization-failure.json` remains; failure to write it
does not erase the original runtime failure. A directory-fsync error after rename
can leave a manifest alongside a failure marker. Saved readers reject that marker;
if storage also prevents recording it, retained bytes alone cannot establish the
failed fsync's durability. Preserve the runtime log and package for investigation.

Saved-package read failures keep the affected capture visibly incomplete with
empty results and a fixed browser message. Raw exception text (including paths or
provider content) is excluded in these messages. The local log records
`saved_package_read`, `saved_history_read` or `resolution_history_read`;
resolution lookup continues to list unavailable session IDs. Other valid saved
captures remain usable. This does not change ordinary input-validation messages.


## Diagnostics and persistence

Shielded opportunity-history workers return failures as data and log
`opportunity_history_build`, including after browser/request cancellation. The
worker retains its concurrency slot until it finishes, then releases it. This
avoids raw exception logging from detached shielded tasks on newer Python
runtimes. An attached request still receives the normal safe API failure.
Arithmetic errors use a fixed HTTP 422 calculation message and log
`dashboard_arithmetic`; ordinary input-validation responses remain unchanged.

Product discovery-refresh failures retain their existing partial/failed status
and source isolation, with `product_discovery_refresh` logged for each occurrence.
Isolated replay failures log `coverage_isolated_replay` and withhold completion.
Collector-lock errors and secondary close errors log `coverage_owner_lock` and
`coverage_owner_lock_cleanup`; secondary errors do not replace the safe lock
rejection.

Novig unsubscribe failures log `novig_unsubscribe` and still attempt socket
closure. Unsubscribe is best effort because confirmed socket closure ends the
subscription. Actual Novig close failures log `stream_connection_close`, remain
sticky in `cleanup_errors`, prohibit reconnecting, and cause later `aclose()`
calls to raise a safe error even after the socket reference is detached. Socket
closure uses the shared bounded close-result helper with a two-second timeout.
An active primary exception/cancellation survives secondary finalization errors.

Injected reference refresh retains request/credit reservations on failure and
cancellation, marks its ledger entry failed, stops acquisition and publishes no
cache entry. Failure-report writes are best effort; a secondary write failure
logs `reference_refresh_failure_report` and preserves the original exception or
cancellation. Missing failure-report persistence never refunds reserved credits.

The dedicated authenticated sample tools temporarily suppress standard logging
to prevent credential-bearing URLs from third-party HTTP logs. The Pinnacle
sample restores the previous logging threshold in `finally`, including on
cancellation, matching the aggregate acquisition tools. Sanitized result files
remain the operating diagnostic while suppression is active. These executables
are separate from the dashboard and have their own request budgets and
consumed-attempt checks.

Transport resource closure attempts every producer and optional reference client.
Returned exceptions are recorded as source plus exception type in `cleanup_errors`,
logged, and included in the terminal journal row when that row can be saved.
A close failure leaves `cleanup_complete=false` and runtime state `failed`.
The multi-game owner blocks another Start in that process to avoid overlapping
unconfirmed resources. A complete journal is a record of collection termination,
not proof of successful resource closure or economic qualification.

A terminal journal capacity exception follows the storage-failure path, just
like a terminal write failure. The first storage failure closes intake and makes
source health ineligible. Accepted, attempted and acknowledged counts remain
separate; unresolved durability stays unknown. The supplemental storage report is
best effort and never appends to the failed primary journal. If that report also
fails, its failure is logged and the original storage status remains available.

`app.diagnostics.failure` logs an operation, exception class and traceback frame
locations (basename, line and function). It excludes messages, exception chains,
source lines, frame locals, request URLs and bodies. Current dashboard unexpected
errors, scan startup/finalization, transport producer/discovery/close failures and
supplemental report failures use it. Repeated events are emitted individually;
there is no new filter or deduplication. Unexpected dashboard errors retain the
safe HTTP 503 response. Existing HTTP security and input-validation responses are
unchanged. Invalid saved selections never load substitute observations.

The list clears prior result rows and removes its current-data label when refresh
fails. Refresh remains the reconnect control. Cleanup failure has an explicit
resource-closure-unconfirmed label. A failed request never initiates another scan.

Journal lock acquisition failure closes the newly opened file; a secondary close
failure is logged without masking the original lock error.

The older PostgreSQL `Store.ingest` preserves its original exception even when
both database failure recording and the local fallback journal fail; both failure
locations are logged. Database recovery requires separate integration checks.


## Deliberate non-fatal handling

Optional financial decoration, unavailable source data and post-commit measurement
failures remain isolated from independent observations. Browser session-storage
restoration remains best effort: unavailable/corrupt display preferences use the
ordinary defaults without authorizing collection. Read timeouts and browser
disconnects retain worker ownership until actual completion. A failed current
resident-memory sample uses the existing peak-RSS sampler rather than zero.
Existing bounded issue counters and source-status surfaces remain in place;
there is no new global logging or warning suppression.

## Investigating a failed scan

1. Read `/api/status` and the launcher instance's `server.log` for the failure
   operation and exception class.
2. Preserve the original journal, pending manifest and failure reports. Do not
   rename a pending manifest to make a capture appear complete.
3. Confirm the failed collector process has exited before restarting. Reopen only
   packages accepted by the saved-history verifier.

## Recovery limits

Stop remains cooperative: per-socket timeouts do not provide a process-wide hard
termination deadline. Do not treat repeating Stop or readable pending files as
proof of successful cleanup or durable completion. Preserve incomplete packages
and runtime diagnostics for investigation; there is no automatic repair, retry of
failed finalization, retention pruning or migration. A failed cleanup blocks another
Start in the same process; confirm process exit before restarting.

The focused shutdown tests are listed in [development](development.md#focused-checks).
