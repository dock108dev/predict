# Development

Work from the repository root with the Python 3.11+ environment described in the
[README](../README.md). The `stream` extra is needed for the current dashboard's
adapter imports, even when exercising saved data. The development workflow is an
editable source checkout; a standalone wheel is not a self-contained dashboard
because saved evidence and assets are loaded from repository paths.

## Source layout

| Location | Responsibility |
| --- | --- |
| `app/dashboard/multi_game_server.py` | Current HTTP routes |
| `app/dashboard/multi_game.py` | Scan owner, saved projection and ranking |
| `app/dashboard/opportunity_board.py` | Compatibility factory and CLI entry point |
| `app/dashboard/opportunity_static/` | Current list and game-detail browser assets |
| `app/collection/` | Bounded discovery, transport, file journals and recovery |
| `app/adapters/`, `app/models/`, `app/normalization/` | Venue conversion and shared identity |
| `app/opportunities/`, `app/fees/`, `app/reference/` | Conditional math, fees and research |
| `app/storage/` | Separate historical PostgreSQL persistence/replay |
| `tests/` | Unit, saved-fixture and local mock checks |
| `integration_tests/` | Separately invoked PostgreSQL checks |
| `evidence/` | Retained observations and verification artifacts; preserve original inputs |
| `.local/` | Ignored local process state and logs |

See [architecture](architecture.md) for data flow and persisted contracts, and
[configuration](configuration.md) for runtime settings and service requirements.
Use [SSOT](ssot.md) for module ownership and retained compatibility decisions.
The lifecycle methods are expanded for readability but remain in `multi_game.py`;
no new owner abstraction, route policy or persisted schema is introduced.

## Focused checks

For changes to the current owner, routes or saved projection:

```sh
.venv/bin/python -m unittest tests.test_multi_game tests.test_opportunity_board tests.test_personal_beta tests.test_failure_handling -q
.venv/bin/python -m compileall -q app/dashboard/multi_game.py app/collection/multi_game.py
```

These tests read saved fixtures and use disposable output or local mocks. They do
not authorize provider collection. For calculation changes, also use the relevant
math reconciliation, fee or research tests; do not rewrite their retained baselines
to make a test pass.

For current browser edits, with Node.js available:

```sh
node --check app/dashboard/opportunity_static/dashboard.js
node tests/test_dashboard_failures.cjs
node tests/test_concise_dashboard.cjs
```

Use `git diff --check` after edits. There is no configured formatter/linter.
Prefer small readable edits consistent with nearby code; avoid repository-wide
formatting churn. Inspect a test or verifier's side
effects before running it. Full test discovery, database integration, evidence
writers, live verifiers and browser walkthroughs are not routine cleanup checks.

## Pull-request CI

[CI](../.github/workflows/ci.yml) runs the stable **Offline checks** job on every
pull request and push to `main`, and supports manual dispatch. It uses Ubuntu
24.04, the minimum supported Python 3.11 and Node 22. This is a focused baseline,
not certification of every Python/platform combination. Node runs the existing
dependency-free browser regression scripts; no npm install is needed.

To reproduce it in a disposable environment from the repository root:

```sh
python3.11 -m venv /tmp/predict-ci-venv
/tmp/predict-ci-venv/bin/python -m pip install --require-hashes -r requirements-ci.txt
/tmp/predict-ci-venv/bin/python -m pip install --no-deps --no-build-isolation -e '.[stream]'
/tmp/predict-ci-venv/bin/python -m pip check
PATH="/tmp/predict-ci-venv/bin:$PATH" sh scripts/check-ci
```

[The check script](../scripts/check-ci) compiles Python, checks current browser
JavaScript syntax and runs selected dashboard, failure-handling and independent
saved-input math/research regressions. Local HTTP mocks and temporary output are
used; retained evidence is read-only. No credentials, provider requests,
PostgreSQL service, live verifier, packaging or release is part of this job.
Failures remain in the Actions step logs; no owner captures are uploaded.

[requirements-ci.txt](../requirements-ci.txt) locks runtime, stream and build
dependencies with hashes and platform markers. CI caches only pip downloads and
installs dependencies on every run; the editable project install cannot resolve
additional packages. After changing dependency requirements, regenerate the lock
with [uv](https://docs.astral.sh/uv/pip/compile/) and review its diff:

```sh
uv pip compile pyproject.toml requirements-ci.in --extra stream --universal --python-version 3.11 --generate-hashes -o requirements-ci.txt
```

Use `--upgrade` for an intentional full dependency refresh. Weekly Dependabot
updates cover pip and SHA-pinned GitHub Actions. Existing GitHub-managed CodeQL
checks (`Analyze (python)` and `Analyze (javascript-typescript)`) remain separate;
do not add a duplicate CodeQL workflow. As inspected on September 16, `main` has
no branch protection or repository rulesets. Making **Offline checks** mandatory
requires a separate authorized repository-settings change.

## Maintenance boundaries

The September 16 cleanup builds on commit `00bc5ee` plus the existing uncommitted
[failure-handling changes](error-handling.md). The root README now points to this
guide and the relocated [historical summaries](implementation-history.md).
Unused imports in the two multi-game modules were removed; normal `asyncio` import
replaces the scan owner's dynamic import. Public names and factory delegation are
unchanged. The lifecycle formatting was checked for syntax-tree equivalence before
that import substitution.

Keep `PLAN.md`, evidence, old launchers and the earlier one-attempt mode under the
existing [retention decisions](ssot.md#conflicts-removed-and-retained-paths).
Retiring a historical server requires identifying its shared helpers and callers
first; cleanup does not silently authorize that retirement or activate old tools.
See the [recovery guide](error-handling.md#limits-and-separate-follow-up) for the
remaining shutdown and durability limits.

Cleanup validation: the focused command above passed 29 tests. Both listed Node
regression scripts, JavaScript syntax, Python compilation, CLI `--help`, 48 local
Markdown link targets and `git diff --check` passed. Existing aiohttp AppKey and
asyncio timing warnings remained visible. No owner service was started/restarted,
and no live collection, database check, commit or publishing was performed.


## Documentation accuracy checkpoint — September 16

This incremental pass uses `00bc5ee02d87936d12ddb5fe0bda485f89dbed6d` plus the
preexisting uncommitted failure handling, cleanup and CI work. During this pass,
HEAD advanced externally to `6ce2964`, incorporating that maintenance; this pass
did not create a commit. The documentation and launcher edits remain uncommitted.
It adds architecture
and configuration guides, reconciles the Desktop tracker with its completed
sections, and corrects the launcher's startup-failure log path for the selected
instance. Earlier validation counts remain historical. The running owner process
and prepared review evidence were not refreshed by this documentation pass.

The launcher change was syntax-checked and its early child-exit branch exercised
with mocked processes, sockets and temporary runtime directories for both instance
names. No actual child process or listener was started. All 44 local Markdown file targets in the edited repository guides, launcher /
dashboard / storage CLI `--help`, and `git diff --check` passed. The first mocked
assertion was corrected to resolve macOS temporary-directory aliases; both instance
checks then passed. No application suite, database, live collection,
browser review or hosted CI run was needed or performed for this change.
