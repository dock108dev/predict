# Current sources of truth

Current source baseline: September 16, 2026, commit `00bc5ee` plus the uncommitted
failure-handling and repository-cleanup changes. The [Desktop tracker](../../prediction_arb_next_steps.md)
and [roadmap](product-roadmap-review.md) still own product scope. Existing services
were not restarted, and source validation is not owner acceptance.

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

SSOT module/file: `app/dashboard/multi_game.py` (`configuration`, `MultiOwner`)

Why this is authoritative: constructs bounded multi-game configuration and owns
Start, overlap rejection, Stop/finalization and saved-scan status. Production
factory explicitly selects personal-beta operation. No scheduled collection.

Known callers: multi-game server; local-only beta test producer.

Domain: Ingestion and event identity

SSOT module/file: `app/collection/multi_game.py`, using `app/normalization/registry.py`
and existing venue adapters

Why this is authoritative: `MultiSession` discovers common pregame events and
binds actual native purchase sides before subscriptions; normalization remains
in the shared registry. It extends `TransportSession` rather than creating a
second transport lifecycle.

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
