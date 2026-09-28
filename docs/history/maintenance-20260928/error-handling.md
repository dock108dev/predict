# Historical engineering record

These dated results describe their original source candidates. Use the current
[project documentation](../../../README.md) for supported behavior and commands.

# Failure handling and recovery

This guide describes collection cleanup, saved-session failures and recovery. See [configuration](../../configuration.md) for run prerequisites and [module ownership](../../ssot.md) for authoritative components. Dated validation records below describe their original candidates.

## September 28 source maintenance

This source change follows the consumed supervised attempt
`860107f6-56ff-44fe-9fd0-088ceaabe2a6`. It changes the working source, not that
attempt's sealed candidate or retained evidence. No new collection or application
restart is part of this maintenance. Earlier validation below remains historical.

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
native REST venues. A failed stream no longer skips the REST client or later
resources, and a second failure cannot replace the first. A resource returning
cancellation counts as failed cleanup. Collector shutdown then records the failure
in its existing `cleanup_errors`, rejects completion publication and blocks a
subsequent Start. An active primary exception or cancellation survives secondary
stream-finalization errors; sticky close failures remain observable when the owner
closes resources. No process-wide forced termination was introduced.

Native group-task failures still isolate the disconnected source and await the
existing Stop/deadline, but now emit `native_stream_task` diagnostics. Optional
reference failures still mark that source unavailable without stopping the other
sources, and emit `optional_reference` diagnostics. A failed projection callback
emits `acknowledged_projection` on each occurrence and retains `projection_error`.
The journal acknowledgement remains valid: failure to project already-persisted
data is not a storage failure. The existing current-snapshot path rebuilds flat
projections from the acknowledged journal prefix; segmented sessions remain
unavailable until verified reconciliation. No stale replacement results are added.

For these events, inspect the existing local server log and `/api/status` cleanup
fields using the incident steps below. Logs contain operation, exception class and
traceback locations, never exception messages or provider payloads. Keep the
original journal and pending files. A close failure requires confirming process
exit before restart; repeating Stop does not certify that failed socket's closure.

The repository pattern scan covered Python, browser assets, scripts and CI;
context review prioritized active collection, HTTP/saved readers, storage,
projection and adapter ownership. Existing retry budgets, unavailable financial
inputs, input-validation responses, stale-book rejection, disconnected-source
isolation and expected cancellation during task joins remain deliberate. This is
not exhaustive fault injection of every historical entry point.

Validation for this source pass used temporary synthetic state, retained read-only
fixtures and local mocks:

- 80 tests passed across `test_kalshi`, `test_kalshi_expiry`,
  `test_polymarket_us_stream`, `test_e6_transport`, `test_native_integration` and
  `test_native_continuation`.
- 50 tests passed across `test_novig` and `test_prophetx`.
- Nine tests passed across `test_coverage_failure_handling` and
  `test_product_integration`.
- 29 tests passed across `test_continuous` and `test_failure_handling`, including
  nine new fault-injection tests. The final US-stream/failure-handling check also
  passed (29 tests, overlapping the groups above).
- `.venv/bin/python -m compileall -q app tests/test_failure_handling.py`, document
  link checks and `git diff --check` passed. Existing asyncio timing diagnostics
  remained visible. Full CI, database integration, browser and live checks were
  not run; no credential access, release or owner acceptance is implied.

## Current coverage-owner maintenance

The current `CoverageOwner` now enforces prior cleanup failure at Start itself,
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
Replay, publication and secondary failure-report errors now log safe operation,
exception class and traceback locations, and set runtime state to `failed`.
The existing best-effort `finalization-failure.json` remains; failure to write it
does not erase the original runtime failure. A directory-fsync error after rename
can leave a manifest alongside a failure marker. Saved readers reject that marker;
if storage also prevents recording it, retained bytes alone cannot establish the
failed fsync's durability. Preserve the runtime log and package for investigation.

Saved-package read failures keep the affected capture visibly incomplete with
empty results and a fixed browser message. Raw exception text (including paths or
provider content) is no longer included in these messages. The local log records
`saved_package_read`, `saved_history_read` or `resolution_history_read`;
resolution lookup continues to list unavailable session IDs. Other valid saved
captures remain usable. This does not change ordinary input-validation messages.

The September 23 repository scan covered application Python, browser code,
launchers and CI suppression/error patterns. Context review followed the current
HTTP, collector, startup, finalization and saved-reader boundaries, with adapter,
reference and historical storage recovery checks. Changes target the demonstrated
gaps above; this is not exhaustive fault injection of every historical entry point.
Bounded retries, disconnected/unavailable venue health, unknown financial inputs,
optional references and credential-safe verifier summaries remain intentional.
No warning filters, automatic retries of failed finalization, new external calls,
or changes to acquisition authorization were added.


## Implemented behavior

The personal-beta owner finalizes only after the collection task returns. Known
storage failures and resource-close failures prevent completed-catalog publication.
An incomplete journal also fails finalization. Finalization writes and fsyncs
`manifest.pending.json`, then renames it to `manifest.json` only after success.
A failed write/flush/fsync can leave readable bytes in the pending file; those bytes
are not a completion receipt. Failed exports, replay or publication set the runtime
state to `failed`, with a safe error on `/api/status`. Original files remain available
for investigation; finalization does not automatically retry or replace them.

Transport resource closure attempts every producer and optional reference client.
Returned exceptions are recorded as source plus exception type in `cleanup_errors`,
logged, and included in the terminal journal row when that row can be saved.
A close failure leaves `cleanup_complete=false` and runtime state `failed`.
The multi-game owner blocks another Start in that process to avoid overlapping
unconfirmed resources. A complete journal is a record of collection termination,
not proof of successful resource closure or economic qualification.

A terminal journal capacity exception now follows the storage-failure path, just
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
locations are logged. This behavior was tested with mocks, not a database.

## Deliberate resilience retained

Repository searches covered catches, default/status conversions, retries, warning
suppression, task cleanup, API wrappers, browser requests and launchers. Contextual
review followed the current owner/transport/journal path and the historical storage,
controller and adapter recovery boundaries. This is not a claim that every legacy
path received fault injection.

- Bounded REST retries, stream reconnection and invalidated/unsynchronized books
  remain. A transport interruption must not promote stale prices to usable data.
- Cancellation is propagated by producer/collection owners. Gathered cancellation
  results for tasks deliberately cancelled during shutdown remain expected.
- Optional reference failures retain unavailable health and stop records. They do
  not manufacture reference probabilities or require stopping prediction-only work.
- Fee, depth, settlement and identity validation retain explicit unavailable results
  and reasons. Unknown inputs remain unknown, and negative/zero outputs remain valid.
- Recovery retains torn-journal/partial-output distinctions. Historical verifiers
  keep credential-safe failure summaries, and the one-attempt mode remains separate
  from the repeatable personal-beta mode.
- Existing third-party warnings remain visible; this pass adds no warning filters.

## Operating a failure

1. Read `/api/status` for `error`, `state`, `cleanup_complete` and `cleanup_errors`.
   Use the existing Stop control if a scan is still active. A failed saved-data route
   does not imply that the collection task stopped.
2. Inspect the launcher's local log, normally
   `.local/opportunity-board-beta/server.log` (`poc` uses
   `.local/opportunity-board/server.log`). Match the operation and frame locations
   to the source revision running that process. Do not enable raw provider logging
   or copy credentials/private payloads into incident reports.
3. Preserve the session folder, journal and any pending manifest. Absence of a
   published manifest means the scan is not a completed catalog entry. Do not rename
   a pending manifest manually or infer fsync success from readable JSON.
4. Resolve storage/configuration failures before an explicit new Start. For a close
   failure, stop the identified application process and confirm its exit before
   restarting. The launcher does not force-kill unrelated processes. A new process
   does not repair the failed capture; retained recovery tools require their own
   documented scope and authorization.

## Limits and separate follow-up

Existing cleanup still depends on cooperative asynchronous tasks and client close
implementations. This pass records returned close failures; it does not introduce
an enforced process-wide shutdown deadline or claim a bound for a stuck close.
Defining escalation for uncooperative tasks/processes is a separate lifecycle change.
Publication uses a fsynced file and rename but does not fsync the directory; power-loss
persistence of directory entries is not guaranteed. Runtime error state is not a
new persistent incident index, and historical dashboards do not all expose the new
multi-game status fields. Historical API exception classification remains coarse.

No real collection, credential lookup, database migration, service restart,
packaging, release, commit or push was performed. Live reliability and owner
acceptance are not established by these tests.

## September 23 validation

All checks used disposable synthetic state, retained read-only fixtures or loopback
HTTP/WebSocket servers. No credentials, provider requests or owner-state writes.

- 25 tests passed: `tests.test_coverage_failure_handling` (initial four tests),
  `tests.test_failure_handling`, `tests.test_product_integration`,
  `tests.test_segmented_collector`.
- 27 tests passed: `tests.test_coverage_failure_handling` (then five tests),
  `tests.test_multi_game`, `tests.test_continuous`.
- Final seven tests passed after publication-order changes:
  `.venv/bin/python -m unittest tests.test_coverage_failure_handling tests.test_product_integration -q`.
  This includes six new tests covering direct Start, startup cancellation and
  secondary cleanup failure, flat replay/fsync/cap failures, safe saved-read
  errors, segmented secondary-report failure and segmented output-cap failure,
  plus existing successful Start/Stop/reopening in both formats.
- Python compilation of both changed application modules and the new test module,
  local document link validation and `git diff --check` passed.

Existing aiohttp AppKey and asyncio slow-task warnings remained visible. No full
CI matrix, database integration, live collection, browser walkthrough, packaging
or release qualification was run.

## Historical September 16 validation

- Initial focused run: 17 tests passed across failure injection, existing storage
  failure handling, personal-beta two-cycle lifecycle and dashboard security.
- Follow-up run after the terminal-cap and manifest guards: 38 tests passed across
  `tests.test_failure_handling`, `tests.test_multi_game` and
  `tests.test_e6_transport`. Transport fixtures use local HTTP/WebSocket servers and
  disposable journals; no provider endpoints are used.
- Final targeted reruns passed: all 8 failure-injection tests (including lock cleanup)
  and the personal-beta two-cycle lifecycle test.
- `node tests/test_dashboard_failures.cjs` passed: failed refresh clears old results
  and the current label. JavaScript syntax and Python compilation of changed modules
  passed; `git diff --check` passed.

Existing aiohttp AppKey and asyncio slow-task warnings appeared. No full CI matrix,
real database integration, live smoke test or browser walkthrough was run.
