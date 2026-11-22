# Archive and reuse decisions

The first archival action should remove obsolete plans from active authority. Physical code movement follows dependency checks. Existing useful data and mathematical evidence stay available.

This is a proposed manifest. No listed file or state was moved, deleted, disabled or relabeled during the audit. See the [audit](README.md) for findings and [implementation sequence](implementation.md) for the work that makes code archival safe.

## Keep and use in phase 2

| Area and paths | Why keep it | Change in emphasis |
| --- | --- | --- |
| `app/collection/data_runtime.py`, `current_service.py`, `current_database.py`, `current_ingress.py` | Existing data owner, atomic admission and recovery. | Make acquisition state and failure reasons inspectable independently of the UI. Repair demonstrated startup failure. |
| `app/storage/current_rows.py`, `current_pregame.py`, `current_pregame_read.py` | Proven identities, source clocks, affected-game work and indexed reads. | Keep projections; add a broader observation catalog rather than weakening calculation admission. |
| `app/adapters/`, `app/collection/sportsgameodds_*`, native transports | Existing connectors and provenance/synchronization patterns. | Document actual capabilities and active routes. Retained adapters are not automatically primary-path support. |
| `app/normalization/`, `app/comparison/same_outcome.py`, occurrence/scoring owners, `app/resolution/` | Correct event, outcome, period and settlement distinctions. | Preserve ambiguity and unsupported cases visibly. Extend through versioned identities. |
| `app/comparison/current_pregame.py`, `pregame_valuation.py`, `pregame_valuation_fees.py`, `cashflows.py`, `app/fees/` | Exact money/quantity/fee arithmetic and existing shared users. | Separate screening policy, coherent probability models and scenario assumptions. |
| `app/storage/sportsgameodds_reference.py`, `odds_archive.py`, `odds_archive_export.py`, `odds_archive_replay.py`, `odds_replay.py` | Paired source evidence, immutable exports, causal replay and saved calculations. | Establish measured coverage; add bounded original receipts and a general evaluator. |
| `app/dashboard/raw_price_api.py`, `app/storage/raw_prices.py`, `app/dashboard/admin_database.py` | Already exposes original data and bounded inspection without paid requests. | Promote into the operator workflow. Show original provider/bookmaker identity. |
| `app/dashboard/bet_journal*.py`, journal storage/monitoring | Original decisions, fills, corrections, closing comparisons and reported cash results. | Optional personal evidence. Add an independent research cohort so betting/manual selection does not govern evaluation. |
| Current Browse, Game, exact Details, amount research, exports and Admin | Working operator functionality. | Reuse compact tables and details. Positive opportunities become a filter/view within research. |
| Quota/account ledgers, guards, source pauses and Stop | Protect cost, state and unresolved financial exposure. | Preserve existing authority. Weekly dollar budgeting remains distinct from request/object units. |
| Applied SQL migrations, schemas, current regression fixtures | Required by migration-prefix/hash checks and retained reader contracts. | Add migrations when needed; never move or edit applied history to make the tree smaller. |

## Archive the authority of old local plans first

These files exist locally but are already ignored by Git. They are not shipped contributor documents. Moving them will clarify the next task; it will not by itself shrink the deployed application.

| Local path | What is superseded | What to retain |
| --- | --- | --- |
| `NEXT_STEPS.md` | My Bets/month-of-actual-use priority and broad deployment work as the primary POC path. | Known bugs, actual-venue closing limitation and protected-state instructions that still apply. Replace with one short current pointer when phase 2 starts. |
| `docs/product-roadmap-review.md` | Interleaved snapshot, live, public UI and Scanner priority chronology. | Dated discoveries and concrete evidence. |
| `docs/usability-sprint-plan.md`, `docs/engineering/live-data-20261107/` | Old queue as the controlling implementation sequence. | Reproducible data/UI defects, separately triaged for current relevance. |
| `docs/practical-use-requirements.md` | Broader-audience usability and past completion/coverage requirements as prerequisites for personal data/math proof. | Identity, clock, fee and source correctness requirements. |
| `docs/ui-design-requirements.md`, `docs/ui-redesign-20261103.md`, `docs/ui-redesign-implementation.md`, `docs/ui01-delivery-20261103.md` | Prior visual design decision and delivery queue as new work. | Historical design rationale and actual usability observations. |
| `docs/product-completion-20261020-plan.md`, old D/Q/SC/E delivery plans and manifests | Previous scope, fixed qualification windows, obsolete installation/acceptance sequences. | Source semantics, calculation examples, failure records and known unresolved issues. |
| `docs/ev-research-loop-plan.md` | One NFL page experiment as a general current roadmap. | Prediction/outcome separation and knowledge-time principles. |

Proposed treatment: add a short superseded notice and historical index, preserve original relative paths initially, and remove active pointers from the current task queue. Consolidate files later only when inbound links are repaired. Do not rewrite old results as passed or silently discard unresolved findings.

## Freeze product expansion that does not serve this research phase

| Area | Treatment |
| --- | --- |
| More palettes, theme controls and visual design rounds | Keep installed behavior; freeze expansion. Avoid a cosmetic simplification sprint. |
| New onboarding, recommendation explanations for unfamiliar users, marketing, public launch and attribution presentation | Historical/future-product backlog. Internal provenance remains part of research correctness. |
| Multiple ranking scores as the principal experience | Keep calculations as optional views; foreground exact price, model, fees and availability. |
| Automated trading, account integration, full execution/depth qualification | Separate optional scope. They do not gate a correct data/calculation POC. |
| Scanner and retained finite-session UI | Preserve as advanced/research tools while useful; stop treating their full publication/readiness graph as the primary operator path. |
| Legacy aggregate provider/The Odds API | Dormant capability unless a concrete source need justifies activation. Preserve all financial/account records. |
| Rich NFL-specific tie/void/funded models | Explicit research scenarios with their own applicability. They are not a universal probability model. |

## Code archival candidates requiring dependency work

| Candidate | Current dependency or limitation | Safe archival condition |
| --- | --- | --- |
| `scripts/e5-preview`, `e6-preview`, `e6-real-view`, `e6-live-watch`, `e6-recovery-preview`; corresponding dashboard modules/static trees | `opportunity_board.py` imports `e6_real` and `e6_live`; router serves E5 shared state and U0 assets; retained readers/package smoke use these paths. | Move shared readers/state/validation to maintained owners, update imports/assets/package tests, then archive genuinely standalone launchers and consumers. |
| `app/dashboard/opportunity_static/u0/` | Current asset allowlist still serves `u0/board.js` and CSS; useful display helpers remain. | Confirm replacement consumers and route/asset parity before moving anything. |
| `app/dashboard/opportunity_static/current/prism.js` | Includes functional filter/refresh relocation and navigation as well as themes. | Extract functional layout binding before any cosmetic removal. Keeping it frozen is cheaper for the first slice. |
| `app/reference/research_loop.py`, `multi_page.py`, `page_estimate.py` | Fixed events/evidence paths, shared arithmetic imports, historical test corpus missing. | Retain useful functions or extract them, provide portable replacement evaluation fixtures, then mark fixed experiments historical. |
| Old synthetic pricing/opportunities flows | Explicit synthetic contracts, examples and retained readers remain. Current code imports older math modules too. | Archive standalone consumers, retain shared math and truthful synthetic fixtures. Do not relabel them as live data. |
| Old branches in `sportsgameodds_schedule.py` / worker | Current `ActivityCollector` uses some shared budget primitives from older scheduling owners. | Extract the live shared primitives, then remove unused branches based on actual callers. |
| Sealed historical delivery packages under `scripts/v1_*_package/` | Frozen manifests, spent-attempt guards and opt-in research contracts. | Preserve historical accountability; detach from current instructions. Packaging changes require demonstrated absence of current supported consumers. |
| Historical test nodes | Test policy already separates required, deferred and archival coverage. Names such as U0/E5/SC do not establish irrelevance. | Retire a test only with the behavior it exclusively covers; preserve shared correctness regressions and current CI contracts. |

The current entry point, router and packaging references are [here](../../../app/dashboard/opportunity_board.py), [here](../../../app/dashboard/multi_game_server.py) and [here](../../../pyproject.toml). Migration preservation is enforced in [Store.migrate](../../../app/storage/store.py), lines 95–117.

## Preserve without cleanup

Do not treat `.local/`, ignored evidence, archive files, PostgreSQL state, private journal/preferences, credentials, configuration, account windows, quotas, reservations, holds, consumed-attempt markers or source Stop/pauses as archival clutter. Disk recovery needs an ownership-aware census, verified retention and an explicit distinction between reproducible temporary output and unique evidence. This audit did not authorize a blanket purge.

Historical directories under `.local/dev-consolidation-20261016/` remain recoverable history. Phase 2 stays in this repository on `main`; it does not create a successor checkout or worktree.
