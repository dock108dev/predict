# Current sources of truth

September 23, 2026. Inspected HEAD:
`1f7c1ce1950194a2b230e40cf93417f851f2cc30`, with the uncommitted error-handling,
security, SSOT, cleanup, CI and documentation passes preserved. These changes affect working source, not running
processes or retained qualification candidates. The [beta definition](product-roadmap-review.md),
[delivery plan](data-coverage-plan.md) and [Desktop tracker](../../prediction_arb_next_steps.md)
own product scope and acquisition authority. Full beta signoff remains open.

## Authoritative domains

Domain: Product routing and entry points

SSOT module/file: `app/dashboard/multi_game_server.py`

Why this is authoritative: the default CLI, native preview and bounded two-source
qualification panel all construct this router with their respective owner.
The public `opportunity_board.create_app` delegates here; it does not own an
alternate route implementation.

Known callers: `scripts/opportunity-board`, `app/dashboard/opportunity_board.py`,
`native_preview.py`, `two_source_preview.py`, browser list/details/import controls.

Domain: Dashboard choices and manual assumptions

SSOT module/file: `app/dashboard/query_policy.py`

Why this is authoritative: one choice catalog governs view, sort, scenario,
freshness, period, family and positive filters. HTTP queries also enforce unique
selectors and exact scalar numeric bounds. Explicit manual probabilities, including
zero, require a nonblank basis. Invalid direct ranking/product choices raise
ValueError instead of selecting an alternate behavior.

Known callers: router middleware for dashboard, calculation, session catalog and
resolution; `product_view.calculate/dashboard`; `multi_game.rank_filter`;
`reference.multi_page.rank_research`. Internal score-distribution probabilities
remain a separate supported calculation contract; HTTP scalar validation is not
applied to those dictionaries.

Domain: Local browser boundary and mutation bodies

SSOT module/file: `app/dashboard/local_security.py`

Why this is authoritative: Host/Origin policy, response headers, strict streamed
JSON parsing and path-specific body limits are defined here. Controls use 4 KiB;
reference/resolution imports use 1 MiB. Early Content-Length checks and streamed
reads use the same `body_limit`; handlers no longer supply duplicate limits.

Known callers: `multi_game_server` middleware, Start/Stop and both import handlers.
The application maximum uses `IMPORT_BODY_LIMIT`. See [security](security.md).

Domain: Configuration, lifecycle and authorization

SSOT module/file: `app/dashboard/coverage_owner.py`, with
`app/collection/native_approval.py` for native approval checks

Why this is authoritative: the default factory selects `CoverageOwner(product_mode=True)`.
Source configuration comes from `multi_game.configuration` unless an explicit
preview supplies a run spec. Start/Stop, cleanup, finalization and resource ownership
remain shared. Real source Start requires the configured approval path; legacy
bounded collection and supervised modes retain their separate consumed-attempt policies.

Known callers: current router, native preview, qualification owner/session and
isolated fixture harnesses. No scheduling, auto-Start or new live allowance is added.

Domain: Ingestion, identity and durable projection

SSOT module/file: `app/collection/continuous.py`, `coverage.py`,
`app/dashboard/session_projection.py`

Why this is authoritative: collection reuses native adapters, registry and shared
sport/market handlers. `SessionProjection` reduces acknowledged rows into current
and saved snapshots. The unused `legacy` selection copy is removed; historical
selection records still participate in cursor/hash accounting.

Known callers: `CoverageOwner`, native producers, `session_history` and
`product_view`. `native_product.py` and `novig_graphql.py` extend the same collector;
GraphQL displayed values remain distinct from sized book opportunities.

Domain: Persistence and saved reopening

SSOT module/file: `app/collection/transport_session.py`, `segmented.py`,
`native_replay.py`, `app/dashboard/session_history.py`

Why this is authoritative: flat/segmented journals and native replay preserve
original observations. The format-aware reader validates before projection.
`multi_game.saved_rows` remains the reader for older multi-game packages that
current catalog/research paths still consume.

Known callers: collector finalization, ordinary saved catalog, cutoff/details,
resolution history and retained research. PostgreSQL is a separate historical
persistence API, not a second backend selected by the current launcher.

Domain: Conditional calculations and reference selection

SSOT module/file: `app/dashboard/product_view.py`, `multi_game.game_calculation`,
`app/opportunities/board.py` and `score_lines.py`

Why this is authoritative: list/detail paths reuse the same calculation engines,
depth, fees, settlement and ranking. Product references are enumerated or explicitly
selected by ID at a retained cutoff. The unused `reference_for` convenience
selector is removed; no automatic single-reference selection path remains there.

Known callers: ordinary dashboard/detail routes and retained replay tests.
`reference.product` owns original-input reference validation;
`resolution.core` owns bound sporting/venue-result calculations. Unknown values
and negative/zero results remain valid; no source qualification is inferred.

Domain: Retrospective page research and browser rendering

SSOT module/file: `app/reference/multi_page.py`, `page_estimate.py`,
`app/dashboard/opportunity_static/`

Why this is authoritative: research uses its original saved event bindings and
separate retrospective ranking semantics. Browser code formats server results and
uses explicit reference IDs; it does not recalculate financial values.

Known callers: list/details, saved research routes and browser controls.
Research ranking shares only selection validation with ordinary ranking.

## Conflicts removed and retained paths

| Candidate | Usage evidence / action |
| --- | --- |
| Route-local choice dictionary and resolution duplicate/numeric checks | Replaced with `query_policy.validate_http_query` at all four selection routes. |
| Direct invalid view/sort/freshness fallback | Rejected using the same choice catalog in direct product and ranking callers. |
| Separate product/retained manual-basis checks | Replaced with shared assumptions validation; whitespace-only basis fails consistently. |
| Repeated control/import byte limits | Routed through `local_security.body_limit`; strict security behavior retained. |
| `product_view.reference_for` | Only three test call sites, no application/script caller. Deleted; tests now exercise explicit reference IDs or absent selection. |
| `SessionProjection.legacy` | Assigned on selection rows, never read anywhere. Deleted state and assignment; row accounting is unchanged. |
| Retained single-game and multi-game readers | Kept: default catalog, saved calculations and page research use them. No migration of evidence. |
| `MultiOwner`, old one-attempt/supervised modes | Kept: current owner inherits lifecycle/status helpers; qualification and offline entry points use distinct policies. |
| Historical SQL, research and collection previews, all-outcome audit engines | Kept: independent entry points and shared imported helpers remain. These contracts are not interchangeable with conditional product calculations. |
| Native Novig/ProphetX and separate reference acquisition | Kept: current collector has native-source branches; pending real qualification is not proof of dead code. |
| Launcher instance names and reference environment setting | Kept: `poc/beta` select different process records; historical optional reference transport reads `ODDS_API_KEY`. Neither grants collection authority. |

Risky follow-up: extract shared collection preview lifecycle/book formatting helpers and identify
which historical executable workflows can be retired before deleting their modules.
Keep consumed-attempt guards, original records and exact replay versions.
`CoverageOwner.start(max_games=...)` remains a legacy request-shape compatibility
parameter with no coverage-limit effect; the current UI hides it. A later control
contract cleanup should stop sending it from current clients and reject it on that
owner while retaining it for the explicitly supported historical MultiOwner path.
Do not unify sporting/qualification policy or conditional/all-outcome math merely
because some branches look alike.

## September 23 validation

61 tests passed:

```sh
.venv/bin/python -m unittest tests.test_ssot_policy tests.test_dashboard_security tests.test_session_projection tests.test_reference_integration tests.test_multi_game tests.test_multi_page tests.test_math_reconciliation tests.test_score_lines -q
```

Four new guard tests cover direct fallback rejection, duplicate selectors,
nonblank assumption basis, shared route rejection before loading data, and removal
of the unused helper/state. Existing reference tests now exercise explicit
selection; they were not deleted. Checks also cover saved reopening, exact original
math and supported partition-distribution inputs. The CI script includes
`tests.test_ssot_policy`.

Changed-module Python compilation, shell syntax, local documentation links and
`git diff --check` passed. Existing aiohttp AppKey and asyncio timing warnings
remained visible. No full CI matrix, live collection, credential lookup, service
restart, database migration, browser walkthrough, commit or publication.

## Historical records

The following sections retain earlier candidate-specific observations. They are
not the current product contract or authorization to execute a run.

## Historical SSOT verification

Passed 37 focused tests:

```sh
.venv/bin/python -m unittest tests.test_opportunity_board tests.test_multi_game tests.test_personal_beta tests.test_page_estimate tests.test_multi_page tests.test_math_reconciliation -q
```

Coverage includes both factory paths, absent probability, explicit EV arithmetic,
unsupported/duplicate selections, unknown cutoffs, two local-producer Start/Stop
cycles with disposable output, per-game isolation, six-game research/list detail
consistency, independent arithmetic and equality with the retained 18-candidate /
96-scenario baseline. Existing aiohttp AppKey and asyncio timing warnings appeared;
there were no failures.

`python3 -m compileall -q` over the three changed application modules and four
changed test modules, and `git diff --check`, also pass. After the successful
37-test run, `.venv` disappeared from the workspace; the attempted virtualenv
compile command therefore failed before running. System Python supplied the
syntax check. At that checkpoint, restoring the development environment was needed before
rerunning the command. The current cleanup pass has verified that `.venv` is
available again; use the development guide for current commands. An existing owner-try `app-start.log` gained two
lines during this pass; it was not edited or reverted by this work. No provider requests,
credential lookup, database work, application restart, packaging, full CI matrix,
commit or publishing was performed. Browser/live checks were not run; this pass
claims focused source validation only.

## Inventory projection independent coverage projection — September 16, 2026

`app/collection/coverage.py` owns offline catalog completeness/accounting and report
projection, before intersection or scan selection. It shares native adapter
`parse_event`/`parse_market` conversion and `prediction_discovery.participant_mapping`
with the existing normalization registry. It never replaces the collection owner,
matching/settlement qualification or calculation engines. Retained market absence
is unknown coverage, not a zero venue denominator. See [inventory projection](data-coverage-d1-report.md).

sustained collection's chosen persistence direction is to extend `ObservationJournal`/native replay
with bounded segments and manifests; the historical SQL API remains separate.
This decision performs no migration or new collection.


## Bounded collection evidence boundary — September 16, 2026

The sole authorized pilot failed in local discovery after 2.434 seconds. Its
immutable journal/manifest and frozen pilot source are under `evidence/d2-coverage/`.
The repaired candidate has 67 focused offline checks; no replacement live run
occurred. Current denominators, wider subscriptions and live browser/Stop evidence
are unestablished. [bounded collection report](data-coverage-d2-report.md) owns those observations;
the Desktop tracker/coverage plan retain incomplete status. This does not authorize
sustained collection, another pilot, indefinite collection or migration.

bounded collection offline journal-efficiency candidate uses versioned, lossless per-row compression inside the existing hash-chain journal; `reopen` restores identical rows for native replay. Logical record, expanded queue, memory and terminal-reserve accounting remain explicit. Legacy journals are untouched. This candidate is not live-validated; the unchanged record ceiling still limits the measured workload. See [efficiency report](data-coverage-d2-journal-efficiency-report.md).


## Segmented history offline segmented history — September 16, 2026

`collection/segmented.py` extends `ObservationJournal` with the separately versioned
`d3a-offline-segments-1` file mode, cumulative policy, seals, atomic manifests and
read-only interrupted-prefix indexes. `NativeVerifier` shares the legacy native
parsers/converter; `GroupedNativeVerifier` keeps sequential stream state across
segments without a whole-run list. Metadata, command and native image dependencies
must precede a usable book. No checkpoints or external payload store are used.

`dashboard/coverage_owner.py:OfflineHistoryOwner` handles retained-input admission,
expanded queue accounting and offline Stop/finalization; `replay_segmented` verifies
completed histories. The production factory still selects legacy `CoverageOwner`.
bounded collection transport, 2,048 lifetime ingress allowance and original recovery identity checks
are unchanged. Mock collector integration is delivered through an explicitly isolated path; there is no
live segmented route or daily collection authorization. See [segmented history results, storage
format and recovery limits](data-coverage-d3a-report.md). bounded collection and full sustained collection are incomplete.


## Mock-only segmented collector integration — September 16, 2026

`CoverageOwner(mock_segmented=True)` requires an isolated output root and explicit
numeric-loopback fixture endpoints. It runs the existing `ContinuousSession`,
discovery and native producers, using `SegmentedTransportJournal` and sequential
finalization. Production construction does not select this option. No credential
resolution, reference feed or external redirect is permitted in the mock path.
Published catalog generations, producer-applied generations and usable books are
separate; shared lifecycle cleanup creates the terminal only after producer joins
and queue accounting. Failure cannot manufacture completion. segmented history policy and bounded collection
limits/attempt protection remain unchanged. Busy local Stop passes; resource
pressure still exhausts four segments at 4,092 ingress. See [integration report](data-coverage-d3-mock-integration-report.md).
Next is an offline sustained-capacity policy/experiment, not a live pilot.
