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
diagnostics; a monitor failure does not authorize another live attempt.

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
sample now restores the previous logging threshold in `finally`, including on
cancellation, matching the aggregate acquisition tools. Sanitized result files
remain the operating diagnostic while suppression is active. These executables
are separate from the dashboard and require their existing exact authorization.

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


## Investigating a failed scan

1. Read `/api/status` and the launcher instance's `server.log` for the failure
   operation and exception class.
2. Preserve the original journal, pending manifest and failure reports. Do not
   rename a pending manifest to make a capture appear complete.
3. Confirm the failed collector process has exited before restarting. Reopen only
   packages accepted by the saved-history verifier.

## Limits and separate follow-up

Stop remains cooperative: per-socket timeouts do not provide a process-wide hard
termination deadline. Do not treat repeating Stop or readable pending files as
proof of successful cleanup or durable completion. Preserve incomplete packages
and runtime diagnostics for investigation; there is no automatic repair, retry of
failed finalization, retention pruning or migration. A failed cleanup blocks another
Start in the same process; confirm process exit before restarting.

The focused shutdown tests are listed in [development](development.md#focused-checks).
