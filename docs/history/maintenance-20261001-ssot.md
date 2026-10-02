# October 1 SSOT source maintenance

Base Git revision: `57a09b00d357827e436b5568793775716732a1cc`. This pass
builds on the uncommitted October 1 failure-handling and security work. README,
Desktop tracker, frozen candidate, current SSOT/architecture guidance and earlier
maintenance decisions were checked before editing.

Frozen beta app hash:
`2b3b9330e5749572681ad28c073396aa2411bb685fee157546b8ab51f69ae193`.
Current source app hash, using that candidate's sorted app-manifest recipe:
`de3286ce2e492a5a5e888d69db82779351322c3824f9484ef7238c40e58deeb9`.
Ten app files differ from the frozen candidate, including the preceding two
maintenance passes. This pass newly changes `dashboard/__main__.py` and
`dashboard/product_view.py`, and simplifies `dashboard/multi_game_server.py`.
The frozen candidate, prepared packages and their evidence were not edited.

## Relevant authoritative domains

Domain: Application routing and entry points

SSOT module/file: `app/dashboard/multi_game_server.py`, launched by
`app/dashboard/opportunity_board.py`; managed process identity is owned by
`scripts/opportunity-board`.

Why this is authoritative: the ordinary factory selects the current file-backed
product owner; both the public factory and generic module command now delegate
to it. The managed launcher validates its own command and process birth record.

Known callers: launcher, `python -m app.dashboard`, native/two-source previews,
browser API controls, retained dashboard fixtures.

Domain: Configuration, lifecycle and source authorization

SSOT module/file: `app/dashboard/multi_game.configuration`,
`app/dashboard/coverage_owner.py`, `app/collection/native_approval.py`.

Why this is authoritative: current owner configuration, resource finalization,
declared Start controls and exact native authority are enforced here. Instance
source settings require an explicitly configured isolated aggregate transport.

Known callers: router, previews, QualificationOwner, collector fixture harnesses.

Domain: Browser trust boundary and request validation

SSOT module/file: `app/dashboard/local_security.py`,
`app/dashboard/query_policy.py`.

Why this is authoritative: shared Host/Origin checks, body limits/deadline,
selector catalog, scalar bounds and manual-input basis rules govern supported
routes and direct product selectors.

Known callers: router middleware/imports/controls, product view, ordinary ranking,
retrospective ranking; see the distinct distribution contract in `docs/ssot.md`.

Domain: Ingestion and durable state

SSOT module/file: `app/collection/continuous.py`, `coverage.py`,
`app/dashboard/session_projection.py`.

Why this is authoritative: current collection shares native source handlers and
reduces acknowledged journal rows into the product snapshot.

Known callers: CoverageOwner, native producers, session history, product view.

Domain: Persistence and saved reopening

SSOT module/file: `app/collection/transport_session.py`, `segmented.py`,
`native_replay.py`, `app/dashboard/session_history.py`.

Why this is authoritative: readers validate original journal identities and
select the recorded format before projection. Historical `multi_game.saved_rows`
is still required for older catalog/research packages.

Known callers: finalization, saved catalog, frozen details, resolution and research.

Domain: Conditional calculations and combined-feed presentation

SSOT module/file: `app/dashboard/product_view.py`,
`multi_game.game_calculation`, `app/opportunities/board.py`, `score_lines.py`,
`app/dashboard/opportunity_feed.py`.

Why this is authoritative: list/detail calculations share depth, fees and payoff
engines; `combine` alone assigns feed groups and percentage ordering. Direct
`view=feed` now composes both EV and Arb using that policy and a shared reuse
cache, rather than falling through to EV alone.

Known callers: current router, direct product consumers and calculation/replay
fixtures. Original-input reference and result validation remain distinct domains
owned by `reference.product` and `resolution.core`.

Domain: Retrospective research and browser state

SSOT module/file: `app/reference/multi_page.py`, `page_estimate.py`,
`app/dashboard/opportunity_static/`.

Why this is authoritative: research retains original bindings and separate
ranking; browser rendering consumes server calculations and declared controls.

Known callers: list/detail/research routes and browser actions. No browser math
engine, scheduling policy or account authentication system is introduced.

## Consolidation and retained contracts

- Removed the generic CLI's historical SQL app construction, alternate port,
  lock and PID writes; delegated it to `opportunity_board.main`.
- Removed historical launcher database setup/migration and PID/substr-based
  signal logic. The script remains an explicit exit-2 retirement notice for
  every invocation. The old Stop check could match the newly delegated generic
  command, so it cannot safely identify historical ownership.
- Routed direct product combined-view calls through the existing grouping policy
  and both calculation branches. Preserved percentage ordering, filters,
  explicit zero assumptions, unavailable values and original calculation inputs.
- Removed the router's second parse/validation of the same assumptions in each
  single-view payload invocation. Validation still precedes dataset access.
- Kept `load_sessions`, historical presentation and old saved readers: the
  current router, catalog, research and retained arithmetic tests import them.
- Kept historical SQL `server`/Controller/storage APIs: benchmark/diagnostic and
  storage tests still use their distinct contracts. They are no longer selected
  by the generic product command. Whole-module removal would require first
  separating these callers, not deleting their evidence or shared helpers.
- Kept `e6_live`/recovery: current owners inherit lifecycle helpers; the separate
  recovery entry point serves a read-only retained catalog. Native/reference
  adapters and qualification previews retain distinct supported contracts.

## Validation

Existing CI already includes both edited test modules; no duplicate CI stage added.

- `.venv/bin/python -m unittest tests.test_ssot_policy tests.test_opportunity_feed -q`:
  **14 passed**. Added delegation, disposable retired-script guards and direct
  combined-view equivalence, including zero, unknown fees and filtering.
- `.venv/bin/python -m unittest tests.test_calculation_reuse tests.test_opportunity_board tests.test_dashboard_security -q`:
  **25 passed**, including retained calculation reuse and HTTP boundary checks.
- After retiring the ambiguous Stop path,
  `.venv/bin/python -m unittest tests.test_ssot_policy -q`: **8 passed**;
  default/start/start-existing/stop/status/unknown invocations all fail before
  operation stubs. No server or database is launched.
- `.venv/bin/python -m compileall -q app/dashboard tests/test_ssot_policy.py tests/test_opportunity_feed.py`,
  `sh -n scripts/dashboard` and `git diff --check`: passed.

There are **39 distinct focused tests** above; the repeated eight are not counted
twice. Tests use retained inputs read-only, temporary outputs or mocked startup.
Asyncio emitted one slow-setup diagnostic; it was not a test failure.
No full CI, live collection, credentials, owner migration, process restart,
walkthrough, packaging, signing, commit or release was performed.

## Separate follow-ups

The preceding failure-handling pass reproduced two discovery-test failures with
the original collector: `Lifecycle.test_single_refresh_and_complete_market_queries_before_selection`
and `FullLocalTransport.test_unmocked_discovery_to_grouped_sockets_and_manual_stop`.
They were not rerun here and are not regressions attributed to this pass; see the
[failure-handling record](maintenance-20261001-abend.md).

Any historical process cleanup first needs an exact ownership check; an old PID
and module substring are insufficient after CLI delegation. No historical PID,
process, database or owner data was accessed or altered by this pass. Retirement
of SQL/Controller or inherited historical lifecycle modules requires a separate
caller-separation pass. Current owner acceptance and the frozen beta/runtime
qualification remain separate from these local source checks.
