# October 1 failure-handling source maintenance

Base Git revision: `57a09b00d357827e436b5568793775716732a1cc`; initially clean
checkout. Read README, development/SSOT guidance, the current Desktop tracker,
failure-handling decisions and the private-beta workflow candidate before edits.
The recorded beta application hash is
`2b3b9330e5749572681ad28c073396aa2411bb685fee157546b8ab51f69ae193`.
That candidate and its verification artifacts remain historical and unchanged;
these source edits do not inherit its runtime or owner qualification.

## Implemented behavior

- A dead resource monitor previously left collection running without active
  disk/RSS checks. Failure, premature return or unexpected cancellation now
  closes intake, requests Stop, logs safe diagnostics and leaves runtime failed.
  Neither flat nor segmented owner publishes a completion manifest for it.
- A shielded history build could lose diagnostics after request cancellation and
  newer asyncio could print private exception details. Its worker now returns
  errors as data, logs safe locations, retains its concurrency slot until done,
  and gives an attached request its normal error response.
- Novig unsubscribe stays best effort with safe logging. Actual socket-close
  failures use bounded close results and remain sticky after detachment; failed
  closure prevents reconnecting. Secondary cleanup preserves primary failures.
- Reference refresh cancellation previously bypassed ledger failure state, and
  secondary report errors could mask the original failure. Reservations now
  survive cancellation; reporting cannot replace the primary exception.
- Pinnacle's dedicated sample no longer leaves process-wide logging disabled
  after returning or cancellation. Credential-safe suppression is retained
  during its authenticated transport, with the original threshold restored.
- Arithmetic API failures use a fixed safe message. Product discovery refresh,
  isolated replay and collector-lock cleanup now emit safe diagnostic events.

Repository searches covered Python handlers, collection/worker tasks, adapters,
storage/recovery, research/calculation fallbacks, browser catches and executable
scripts, including logging suppression and warning/static-analysis patterns.
Context review concentrated on the current CoverageOwner/router and their shared
dependencies. Older synthetic/PostgreSQL and sealed acquisition paths were
reviewed as separate modes; this is not exhaustive runtime certification of them.

Intentional resilience retained: optional reference/source isolation, bounded
transport retries, stale/invalid-data exclusion, saved-package incomplete states,
best-effort supplemental failure reports, Stop cancellation, credential-safe
sample logging suppression and harmless browser settings fallback. These remain
distinct from successful persistence, fresh quotes or authorized collection.

## Validation actually run

All checks used existing dependencies, temporary synthetic state, retained
read-only fixtures and mocked/local transports; no provider operation occurred.

- `tests.test_abend_handling`, `tests.test_novig`,
  `tests.test_pinnacle_sample`: **39 passed** on the final source.
- `tests.test_abend_handling` plus `tests.test_coverage_failure_handling`:
  **13 passed** before the later Novig/sample tests were added. The eight existing
  coverage failure cases passed alongside the then-five new cases; the eight
  coverage cases also passed again separately after all source edits.
- `tests.test_failure_handling`, `tests.test_reference_integration`,
  `tests.test_dashboard_security`, `tests.test_ssot_policy`,
  `tests.test_multi_game`, `tests.test_opportunity_board`,
  `tests.test_personal_beta`: **64 passed**.
- A separate group including `tests.test_continuous` ran **55 tests: 53 passed,
  two failed**. Both failures reproduced by loading the original HEAD collector
  in a fresh Python process, without modifying the checkout:
  `Lifecycle.test_single_refresh_and_complete_market_queries_before_selection`
  expected one Kalshi market and found zero;
  `FullLocalTransport.test_unmocked_discovery_to_grouped_sockets_and_manual_stop`
  expected 24 Kalshi markets and found zero. These are baseline failures; their
  fixture/admission reconciliation remains a separate follow-up. The test suite
  as a whole is not reported green.
- Python compile checks for `app` and the edited tests, shell syntax for
  `scripts/check-ci`, and `git diff --check` passed. The new failure regressions
  and Novig tests were added to the focused CI script.

## Operating guidance and limits

The current operating source of truth is [failure handling](../error-handling.md);
README and [development](../development.md) link the behavior and checks.
Inspect `/api/status`, the launcher `server.log` and retained journals after a
failure. A terminal record or pending manifest alone is not successful completion.
Normal shutdown and per-socket timeouts remain cooperative; there is no new
process-wide hard termination, automatic retry, migration or artifact repair.

No application restart, live collection, credential access, spending, owner-data
migration, full CI matrix, PostgreSQL integration, browser walkthrough, packaging,
signing, commit, push or release was performed. Source validation does not imply
owner acceptance or new qualification of the frozen beta candidate. The two
baseline discovery regressions and separately authorized runtime/owner checks
remain open.
