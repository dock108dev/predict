# Personal data workspace implementation handoff

## Assignment

Coordinate and complete the simplification of Predict into a personal data workbench. The owner needs to navigate data, inspect calculations, compare captured observations and evaluate experiments with less cognitive noise. Implement the agreed structure: **Data**, **Experiments**, and a small **Settings** utility. Finish implementation, integration, deployment and engineer-led verification in one assignment before asking for owner review.

This is authorization to implement that direction. Use existing components and styles, simple tables and practical defaults. Make routine layout decisions without another visual-design or feature-selection round.

## Baseline and working rules

Repository: /Users/michaelfuscoletti/Desktop/prediction-arb
Known application baseline: main at b449e792ad0ac9d951a93a10af9c6f0df5a1e5ec.
Site: https://predict.dock108.dev

Read AGENTS.md, the current completion/assignment record at docs/engineering/phase2-20261122/queue.md, docs/CI.md, docs/ev-checkpoint-experiment.md and docs/monitor-live.md. Verify actual HEAD and dirty state first; preserve later work and these handoff documents. Work in this single checkout on main. Do not create a worktree or successor app.

Phase 2 engineering is completed history. The NCAAB models/game-log/accuracy plan in docs/engineering/ncaab-model-research-backlog.md remains deferred. This assignment is the usable interface to existing capabilities, not new model ingestion or a new backtest engine.

## Required experience

### Data is home

Make the main entry a game-oriented data browser with search, sport and date selection. Preserve access to every currently supported sport; NCAAB should be easy to select without changing acquisition scope.

Group source observations only through established canonical identity. Provider/event counts are not unique-game counts. Keep unmatched/source-local observations clearly identifiable and reachable; never merge by similar names alone.

Open a game to inspect books, supported markets, main and alternate lines, captured observations and available results. Distinguish latest stored prices from frozen first-observation/T−10 checkpoints. Show actual observation times; refreshing the UI reads stored data.

Positive EV and arbitrage are filters/calculation views within Data, not separate destinations. Preserve nonpositive prices and explicit unavailable reasons. A missing fee/reference must not hide a valid received price or become numeric zero.

An exact-bet drilldown exposes selected line, both checkpoint observations when present, book/source identity, reference probability, fees/cashflows, EV, timestamps, underlying source evidence and export. Main status can change; −4.5 and −5.5 remain different bets. Keep conservative screening and coherent evaluation estimates explicitly distinguished.

Use bounded server reads, grouping/filtering before pagination, stable snapshot/revision identity and matching exports. Do not download the whole catalog into the browser to group games. Preserve filters, selected capture, game and exact bet through links and Back.

### Experiments is evaluation

Move the existing first-observation/T−10 study here: declared games/population, capture coverage, early/late changes, missing/refused/missed cases, outcomes when available and reproducible exports. Reuse existing cohort/evaluation capabilities where applicable.

Do not leave a second complete received-data browser stacked beneath the experiment. Reuse the same game/bet inspection tools from both main destinations. Preserve append-only corrections, causal checkpoint validity and unchanged source clocks.

Only expose experiments that actually work. Future model comparisons, accuracy and game-log backtests belong here when their backlog is implemented; do not add empty dashboards or nonfunctional Run buttons. Keep sporting outcomes, model quality, quoted EV and actual trading returns distinct.

### Settings is small and operational

Replace the broad owner-facing Admin interface with collection state, next discovery/capture, credits and unresolved holds, meaningful storage warnings, Stop/Resume, source pauses and essential existing configuration. Move odds/theme preferences here if retained.

Keep healthy status compact. Surface actionable problems without dumping policy versions, hashes, raw reason codes, ranking jargon or repeated explanations into default tables. Detailed evidence remains inspectable where relevant.

## Retire competing entry points

Consolidate Research/Browse Odds/Odds/Raw Inputs into Data; Opportunities/EV/Arbitrage into Data views; saved replay into capture/evidence inspection; relevant Coverage/Admin facts into Settings or contextual details. Put fee explanation beside the calculation. Turn off standalone Scanner, My Bets, About and Trading Fees interfaces for this scope while preserving their records and required backend behavior.

Inventory all HTML entry points, not just menus: ordinary routes, /admin?section=... variants, /current/coverage, /admin/retained and the broad /view/ static HTML aliases. Old bookmarks and internal links must not resurrect the old navigation. Use fixed local destinations and explicit compatibility mappings that preserve valid selection context; clearly retire unsupported destinations without redirect loops.

Keep necessary APIs, JS/CSS/fonts, export readers, source evidence, journal/exposure records and background owners. In particular, bet_journal_api.mount also owns APIs and a sampler: do not remove that whole mount merely to hide /my-bets. Archive old interface/test material recoverably before deleting anything useful. Use one shared navigation definition across surviving screens; no More menu full of retired products.

## Code starting points

All paths in this section are relative to the repository above.

- app/dashboard/multi_game_server.py: page routes, legacy aliases and broad static mount.
- app/dashboard/research_api.py and app/storage/research_catalog.py: passive catalog, repeatable-read tokens, detail revisions and exports.
- app/research/experiment.py and app/research/experiment_evidence.py: frozen experiment records/comparison/export.
- app/dashboard/current_pregame_api.py: current prices and arbitrage reads.
- app/dashboard/opportunity_static/current/research.html, research.js, experiment.js, research-tools.js: currently combined research/catalog interface.
- app/dashboard/opportunity_static/current/pregame*, raw-odds*, admin*, mode-settings.js and snapshot-*: reuse useful owners/renderers while retiring competing shells.
- app/dashboard/bet_journal_api.py, admin_database.py and raw_price_api.py: separate HTML retirement from data/API ownership.

Trace actual mount ownership before editing; a route list alone is not a dependency map.

## Preserve operating behavior

Keep :20/:50 discovery, one initial full research snapshot, scheduled T−10, no separate saved-game refresh/Live polling, and bounded postgame result checks. Retain all supported books/alternates, account/credit/window guards, Stop/pauses, reservations, original data and financial exposure. Do not reset state or change collection scope to simplify the UI.

Preserve the one-owner proxy and remembered browser login, including /etc/caddy/predict-auth and /etc/caddy/predict-owner-session.Caddyfile. No authentication rewrite, new subscription, source/model feed, bankroll logic or public-user onboarding.

Keep existing storage limits and report capacity honestly. Browsing, filtering, navigating, inspecting and exporting must cause zero provider requests and no hidden recalculation/acquisition jobs.

## Coordination and verification

Delegate independent UI, route/API and verification work where useful; assign file ownership and integrate it yourself. Keep this one outcome rather than handing back intermediate fixes.

Verify the actual owner journey on installed Predict at the retained 150% zoom: Data → find an NCAAB game → inspect books/main/alternates → exact calculation/source evidence → early/T−10 comparison → matching export → Back with context preserved. Use genuine retained data, including a nonpositive/unavailable case and incomplete capture. Do not require a new positive edge, fresh game outcome or invented observation window.

Check normal navigation, direct links, reload and remembered login. Exercise legacy bookmarks as functional compatibility journeys, not source-absence/removal-only tests. Verify necessary static assets still load, Settings shows real state and required controls remain available. Use disposable fixtures for mutating control tests; preserve live owner choices and active scheduled captures.

Run only meaningful affected API/SQL/controller/browser checks and the required private-beta CI. Update obsolete tests to the agreed behavior and retain old versions recoverably; do not restore broad legacy journeys merely because they once existed. Keep the owner's two-minute normal CI/CD requirement, parallel validation/image preparation and all mandatory pre-deploy checks. If it fails, diagnose the changed bottleneck and complete the repair without bypassing the gate.

Deploy through the normal workflow. Verify the installed candidate, all configured role health, retained data/controls and zero acquisition from the new read paths. Coordinate any collector restart around actual scheduled captures; avoid restarting unaffected data roles.

## Completion and handoff

The earliest sufficient stopping condition is the complete installed journey above, functional legacy-link resolution, preserved data/controls, passing affected checks and successful normal CI/deployment. No extra soak, arbitrary sample count, profitability/calibration proof or owner-review dependency is added.

Update the active assignment and operating guides with final routes and behavior; keep phase 2 history and the deferred model backlog distinct. Finish with the new navigation, what was combined/disabled, real verification evidence, commit and CI/deploy links, and any material limitation. Explain the outcome plainly. Ask the owner only if a genuine unresolved decision or external blocker prevents completion.


## Owner scope clarification during implementation

Trading is specifically prediction-market trading: market-to-book EV and
comparisons, and market-to-market comparisons. Sportsbook observations remain
reference-price evidence; sportsbook-to-sportsbook and book-to-market trading
result views are excluded. Existing historical records are preserved.

Implementation routes and operating behavior are documented in
[the personal workspace guide](../personal-data-workspace.md). Deployment and
installed verification are recorded in the active assignment closeout, separately
from local fixture and retained-snapshot checks.

The owner's subsequent scope limit selects ten sportsbook reference sources
(FanDuel, DraftKings, BetMGM, Caesars, BetRivers, Hard Rock Bet, Bookmaker.eu,
BetOnline, Bovada, William Hill), with SportsGameOdds as the sole active provider.
Trading markets remain on the trade side and outside this ten-book count. Existing
captured policies, historical inputs and numeric probability policies remain
preserved; only future requested scope and default active browsing are narrowed.

## Completed implementation and later reset direction

The workspace is installed at application commit `b4ef1f6`; required CI/deployment
on `e9bbf92` succeeded in run
[45104792325](https://github.com/dock108dev/predict/actions/runs/45104792325).
The installed retained-data journey and exact offline export reproduction passed
before Michael's subsequently authorized fresh-data reset. Observed data was then
cleared with verified backups while financial/journal records, controls,
configuration, credentials, remembered login and scheduled-slot history were
preserved. Fresh Data/Experiments and all role health were checked afterward.
The [active assignment completion record](phase2-20261122/queue.md#workspace-completion-and-fresh-start)
separates those two observations and records the preserved limits and pending
fresh T−10 evidence. No new live pair, profitability proof or owner review is a
completion dependency after the authorized fresh start.

## Owner follow-up: navigation and zero fees

The owner reported Open game returning Too Many Requests and an unhelpful default
table. The follow-up removes duplicate list reads on game navigation, serializes
navigation reads, retries only an expired snapshot, and keeps the server read
capacity unchanged with bounded admission waiting. Status filters now select
games without removing their reference and nonpositive price context.

The owner additionally requested exercise calculations assume zero fees,
behind a feature flag with the existing fee implementation preserved. Include
fees defaults off and is available in Settings. Current calculations and new
checkpoints record the chosen assumption; frozen historical evidence retains its
original mathematics. The operating guide documents the durable flag and its
recalculation behavior.
