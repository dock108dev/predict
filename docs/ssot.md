> **October 2 product reset:** the owner rejected the UI and stopped the saved-data walkthrough. [Audit](usability-audit-20261002.md), [major usability sprint plan](usability-sprint-plan.md) and [current acceptance](beta-coverage-acceptance.md) govern new work. Historical scan/history/card-layout requirements and owner-review next actions below are superseded; existing technical behavior and candidate evidence retain their own boundaries. Necessary new live attempts are authorized within the plan and shared 500/month Odds API allowance.

# Current sources of truth

This guide maps current behavior to its authoritative modules. See [configuration](configuration.md) for source setup and collection limits.

## Authoritative domains

Domain: Product routing and entry points

SSOT module/file: `app/dashboard/multi_game_server.py`

Why this is authoritative: the default CLI, native preview and bounded two-source
qualification panel all construct this router with their respective owner.
The public `opportunity_board.create_app` delegates here; it does not own an
alternate route implementation.

Known callers: `scripts/opportunity-board`, `app/dashboard/opportunity_board.py`,
`app/dashboard/__main__.py`, `native_preview.py`, `two_source_preview.py`, browser
list/details/import controls. The generic module command delegates to
`opportunity_board.main`; it no longer constructs the historical SQL server or
writes its PID/lock files. Historical `scripts/dashboard` controls fail explicitly
before database setup, migrations or signals. Its old PID plus module-substring
check cannot distinguish the newly delegated generic command from an old process;
cleanup of any historical process needs separately verified ownership.

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
`product_view.dashboard(view='feed')` explicitly composes Arb and EV through
`opportunity_feed.combine`, the same grouping/ranking policy used by the router;
it no longer falls through to EV alone. The combined feed ranks by percentage
within declared groups, including when the ordinary-view sort is dollars.
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

## Start control contract

Domain: Start controls and browser requests

SSOT module/file: `multi_game.MultiOwner.start_controls` and
`coverage_owner.CoverageOwner.start_controls`

Why this is authoritative: status publishes the selected owner's accepted fields.
The router rejects unsupported fields before calling Start; the browser uses the
same declaration for visibility and request construction. Signature tests guard
against drift. CoverageOwner normally accepts duration only; an explicitly
configured product instance with an isolated aggregate endpoint also declares
`source_settings`. QualificationOwner accepts duration only; MultiOwner also
applies a game limit. Owners enforce numeric and frozen-run limits.

Known callers: Start/status/dashboard routes, `dashboard.js`, qualification and
native previews, and synthetic fixtures.

## Conflicts removed and retained paths

The compatibility factory delegates to the current router. Query validation and
manual assumptions use `query_policy`; body limits use `local_security`.
Unsupported choices fail explicitly instead of selecting a fallback.
Current snapshot routes share `multi_game_server.selected_game`; an absent game
raises an explicit selection error before calculation, sizing or review.

Older saved readers remain dependencies of catalog and research views. MultiOwner
provides inherited lifecycle helpers and a supported bounded multi-game path.
Historical SQL, all-outcome audit engines and reference acquisition have separate
contracts and entry points. Native adapters remain implemented even where real
source qualification is incomplete. Instance names select process records, not
collection permissions. Do not replace these distinct contracts with conditional
product calculations or remove shared helpers without checking their callers.

Candidate-specific changes and test results are retained in the
[September engineering record](history/maintenance-20260928/ssot.md) and the
[October entry-point/feed maintenance record](history/maintenance-20261001-ssot.md).
