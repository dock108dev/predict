# Failure handling and recovery

Current source behavior, updated September 23, 2026 from clean commit
`1f7c1ce`. These are uncommitted source changes; running processes and retained
qualification candidates are unchanged. Product scope and authorization remain in
[SSOT](ssot.md) and the [Desktop tracker](../../prediction_arb_next_steps.md).
Earlier validation below is explicitly historical.

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
  `tests.test_failure_handling`, `tests.test_b2_product`,
  `tests.test_segmented_collector`.
- 27 tests passed: `tests.test_coverage_failure_handling` (then five tests),
  `tests.test_multi_game`, `tests.test_continuous`.
- Final seven tests passed after publication-order changes:
  `.venv/bin/python -m unittest tests.test_coverage_failure_handling tests.test_b2_product -q`.
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
