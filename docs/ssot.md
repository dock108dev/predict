# Current sources of truth

Product scope was reset September 20, 2026: the [beta definition](product-roadmap-review.md),
[B1–B7 delivery plan](data-coverage-plan.md) and [Desktop tracker](../../prediction_arb_next_steps.md)
are authoritative. Four prediction venues, model plus free delayed Pinnacle references,
six sports and the requested market families are required. Beta signoff is not ready.
Earlier D/E/slice reports retain component evidence, not active next-action authority.

Local HEAD inspected in this documentation pass: `edad00dd980cc8535d69a815d1199b82dd0e83cb`,
with existing uncommitted work. No current runtime/hosted qualification is inferred.
The domain map below describes existing implementation, not completion of the expanded beta.

The domain and retention decisions below originate from the earlier SSOT pass at
`5fd1d5e8234a84a96d5465f74335c16f9a8b5bc7` and remain applicable. See
[development](development.md) for current setup/checks and
[failure handling](error-handling.md) for current finalization and diagnostics.
The earlier verification record at the end is historical.

## Authoritative domains

Domain: Product routing and client API

SSOT module/file: `app/dashboard/multi_game_server.py`

Why this is authoritative: the current opportunity-board launcher serves its
multi-game list, game details, saved sessions and explicit Start/Stop routes.
Views are `arb`, `ev`, `research`; sorts are `roi`, `dollars`. Unknown selections,
duplicate query selections and unknown cutoffs fail with HTTP 422.

Known callers: `app/dashboard/opportunity_board.py` (both factory and CLI),
`app/dashboard/opportunity_static/dashboard.js` and `board.js`.

Domain: Configuration and scan lifecycle

SSOT module/file: `app/dashboard/coverage_owner.py` (`CoverageOwner`, D2 production mode), extending `app/dashboard/multi_game.py:MultiOwner`

Why this is authoritative: production selects the bounded D2 inventory collector,
with one Start/Stop owner, finalizer, process lock and persistent consumed-attempt
guard. Startup is idle, with no scheduled collection or autoresume. Historical
MultiOwner configuration/sample tests and saved calculations remain supported.

Known callers: multi-game server; local-only beta test producer.

Domain: Ingestion and event identity

SSOT module/file: `app/collection/continuous.py` with `app/collection/coverage.py`,
using `app/normalization/registry.py` and existing venue adapters

Why this is authoritative: `ContinuousSession` builds each venue catalog before
matching and subscriptions, retaining unmatched/excluded markets, refreshing every
60 seconds and enforcing the kickoff margin. It extends `TransportSession` and
reuses native producers/stream parsers. `MultiSession` retains historical sample
compatibility; its six-game selection no longer controls production collection.

Known callers: `MultiOwner`; `PredictionProducer`; native replay checks.

Domain: Credentials and destination policy

SSOT module/file: `app/collection/venue_access.py`

Why this is authoritative: defines the current prediction-only destinations,
project credential references and credential loading for explicit Start.

Known callers: prediction discovery, producer and transport session. The route
middleware separately owns loopback/Origin checks; these are not account login.

Domain: Current capture persistence and replay

SSOT module/file: `app/collection/transport_session.py` (`ObservationJournal`,
`reopen`), `app/collection/native_replay.py`

Why this is authoritative: the beta retains file journals and native replay;
`multi_game.saved_rows` verifies manifests before projection. The CLI forbids
database connections. PostgreSQL storage remains a separate historical API.

Known callers: `MultiSession`, `MultiOwner.finish`, saved dashboard and research.

Domain: Conditional board calculations

SSOT module/file: `app/opportunities/board.py`

Why this is authoritative: computes original-input board legs and conditional
normal-winner Arb/EV using `app/depth.py:consume`, `app/fees/engine.py:calculate`
and `app/settlement.py` payout/relationship rules. Missing probability is `None`;
no default fair probability exists. This is distinct from all-outcome qualification.

Known callers: `multi_game.game_calculation`; `reference.page_estimate.estimate`.
The shared fee, depth and settlement implementations also serve the older
arbitrage and opportunity audit engines.

Domain: Saved-page research

SSOT module/file: `app/reference/multi_page.py` (`saved_comparisons`, `research_row`)
and `app/reference/page_estimate.py:estimate`

Why this is authoritative: one six-game manifest binds saved source and target
identity; both list and details use these comparisons and the same estimator.
`public_page.py` parses paired odds; `research_loop.page_arithmetic` supplies
page arithmetic. Requested research size is never silently capped.

Known callers: multi-game server and `page_estimate.for_saved_game`.

Domain: Projection, ranking and presentation

SSOT module/file: `app/dashboard/multi_game.py` and
`app/dashboard/opportunity_static/`

Why this is authoritative: per-game projection isolates observations, selects a
retained cutoff and sizes board candidates against depth. Ranking preserves
Decimal precision. Research uses its separate retrospective ranking class in
`multi_page.rank_research`. Browser presentation does not calculate financial values.

Known callers: current server; dashboard and game-detail pages.

## Conflicts removed and retained paths

- Removed the alternate single-game route implementation and its duplicate
  `opportunity_board.catalog` cutoff policy. The public `create_app` entry point
  delegates to the current server, and tests use `multi_game.default_point`.
  CLI and factory now share routes; the CLI default port matches the launcher.
- Removed the implicit 0.50 probability in `opportunities.board.evaluate`.
  Explicit numerical test scenarios still pass their probability. Omitted inputs
  produce “Assumption needed” and null EV.
- Removed silent unknown-view-to-EV, unknown-sort-to-dollar and unknown-freshness
  selection behavior at the product API boundary. Known UI selections are unchanged.
- Removed routine evidence writes from the math and multi-page regression tests;
  they assert equality against the retained baselines instead.
- Keep the two original single-game captures and default identity constants:
  `load_sessions` actively includes them in the current saved catalog, and offline
  arithmetic tests use their exact identity. Their compatibility is data projection,
  not an alternate server policy.
- Keep `page_estimate.retained`: the one-game binding/hash validator remains a
  focused regression input. Runtime list/detail calculations use the six-game
  manifest; historical one-game artifacts remain unchanged.
- Keep `MultiOwner.personal_beta=False` and older E6 one-attempt guards: they protect
  consumed verification attempts and are exercised by guard/recovery checks. They
  are never selected by the current production factory. Removing them safely
  requires a separate retirement decision for the verification entry points.
- Keep historical Slice/E5/E6 previews, adapters and PostgreSQL replay/storage:
  the roadmap explicitly retains completed work, the current beta imports E6
  projection/journal helpers, and the historical tools retain independent callers.
  ProphetX/Novig limits are documented, not silently promoted to current live support.
  No unsupported environment aliases were removed in this pass.

Follow-up for risky removals: decide which historical launchers/verification APIs
can be retired, then extract shared E6 helpers before removing their modules.
Do not delete consumed-attempt markers or original evidence. Unify conditional
board and versioned all-outcome audit contracts only after defining how their
intentionally different qualification/provenance semantics should map.

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

## D1 independent coverage projection — September 16, 2026

`app/collection/coverage.py` owns offline catalog completeness/accounting and report
projection, before intersection or scan selection. It shares native adapter
`parse_event`/`parse_market` conversion and `prediction_discovery.participant_mapping`
with the existing normalization registry. It never replaces the collection owner,
matching/settlement qualification or calculation engines. Retained market absence
is unknown coverage, not a zero venue denominator. See [D1](data-coverage-d1-report.md).

D3's chosen persistence direction is to extend `ObservationJournal`/native replay
with bounded segments and manifests; the historical SQL API remains separate.
This decision performs no migration or new collection.


## D2 evidence boundary — September 16, 2026

The sole authorized pilot failed in local discovery after 2.434 seconds. Its
immutable journal/manifest and frozen pilot source are under `evidence/d2-coverage/`.
The repaired candidate has 67 focused offline checks; no replacement live run
occurred. Current denominators, wider subscriptions and live browser/Stop evidence
are unestablished. [D2 report](data-coverage-d2-report.md) owns those observations;
the Desktop tracker/coverage plan retain incomplete status. This does not authorize
D3, another pilot, indefinite collection or migration.

D2 offline journal-efficiency candidate uses versioned, lossless per-row compression inside the existing hash-chain journal; `reopen` restores identical rows for native replay. Logical record, expanded queue, memory and terminal-reserve accounting remain explicit. Legacy journals are untouched. This candidate is not live-validated; the unchanged record ceiling still limits the measured workload. See [efficiency report](data-coverage-d2-journal-efficiency-report.md).


## D3a offline segmented history — September 16, 2026

`collection/segmented.py` extends `ObservationJournal` with the separately versioned
`d3a-offline-segments-1` file mode, cumulative policy, seals, atomic manifests and
read-only interrupted-prefix indexes. `NativeVerifier` shares the legacy native
parsers/converter; `GroupedNativeVerifier` keeps sequential stream state across
segments without a whole-run list. Metadata, command and native image dependencies
must precede a usable book. No checkpoints or external payload store are used.

`dashboard/coverage_owner.py:OfflineHistoryOwner` handles retained-input admission,
expanded queue accounting and offline Stop/finalization; `replay_segmented` verifies
completed histories. The production factory still selects legacy `CoverageOwner`.
D2 transport, 2,048 lifetime ingress allowance and original recovery identity checks
are unchanged. Mock collector integration is delivered through an explicitly isolated path; there is no
live segmented route or daily collection authorization. See [D3a results, storage
format and recovery limits](data-coverage-d3a-report.md). D2 and full D3 are incomplete.


## Mock-only segmented collector integration — September 16, 2026

`CoverageOwner(mock_segmented=True)` requires an isolated output root and explicit
numeric-loopback fixture endpoints. It runs the existing `ContinuousSession`,
discovery and native producers, using `SegmentedTransportJournal` and sequential
finalization. Production construction does not select this option. No credential
resolution, reference feed or external redirect is permitted in the mock path.
Published catalog generations, producer-applied generations and usable books are
separate; shared lifecycle cleanup creates the terminal only after producer joins
and queue accounting. Failure cannot manufacture completion. D3a policy and D2
limits/attempt protection remain unchanged. Busy local Stop passes; resource
pressure still exhausts four segments at 4,092 ingress. See [integration report](data-coverage-d3-mock-integration-report.md).
Next is an offline sustained-capacity policy/experiment, not a live pilot.
