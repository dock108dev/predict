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
| `app/dashboard/coverage_owner.py` | Current owner and finalization |
| `app/dashboard/session_projection.py`, `product_view.py` | Durable projection and product calculations |
| `app/dashboard/query_policy.py`, `local_security.py` | Selection/assumption policy and browser/body boundaries |
| `app/dashboard/multi_game.py` | Retained projection, calculation/ranking and inherited owner helpers |
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
The current factory selects CoverageOwner; older MultiOwner helpers remain shared.
Use `query_policy` for selection/assumption changes and `local_security` for body
limits. Do not copy these policies into new routes or direct product helpers.

## Focused checks

For changes to the current owner, routes or saved projection:

```sh
.venv/bin/python -m unittest \
  tests.test_multi_game tests.test_opportunity_board tests.test_personal_beta \
  tests.test_failure_handling tests.test_coverage_failure_handling \
  tests.test_ssot_policy tests.test_dashboard_security -q
.venv/bin/python -m compileall -q app/dashboard app/collection
```

These tests read saved fixtures and use disposable output or local mocks. They do
not authorize provider collection. For calculation changes, also use the relevant
math reconciliation, fee or research tests; do not rewrite their retained baselines
to make a test pass.

For saved-reader or resolution changes, also run:

```sh
.venv/bin/python -m unittest tests.test_session_projection tests.test_b2_product tests.test_b5_nfl_resolution -q
```

For current browser edits, with Node.js available:

```sh
node --check app/dashboard/opportunity_static/dashboard.js
node tests/test_dashboard_failures.cjs
node tests/test_board_security.cjs
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
24.04, the minimum supported Python 3.11 and Node 22, with a 20-minute job limit.
This is a focused baseline,
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
The retained-regression group prints individual test names so a timeout identifies
the test in progress. Its prior ten-minute hosted limit was exceeded on September
23; increasing the bound does not establish a passing run.

The exact evidence exceptions in [.gitignore](../.gitignore) are immutable inputs
read by the existing offline tests and saved-review code. Include these files in
the same pull request as the source changes: they were previously present only
in the local ignored archive. Their bytes and historical failure/consumption
states are unchanged. Approvals and unrelated acquisitions remain ignored. The
consumed-attempt regression resolves its retained marker within this checkout,
without following an owner's absolute output path. To check fixture portability,
export tracked and nonignored files to a temporary checkout and run the affected
retained-review tests there; a pass in the full local archive is insufficient.

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
checks (`Analyze (python)`, `Analyze (javascript-typescript)` and
`Analyze (actions)`) remain separate; do not add a duplicate CodeQL workflow.
The September 23 read-only GitHub inspection found no required status checks or
active branch rules on `main`. CodeQL passed on `1f7c1ce`, but its Offline checks
job timed out. These results do not qualify the current uncommitted source.
Repository-settings changes require their own scope.

CI maintenance validation: 106 affected offline tests passed in a temporary
checkout containing only tracked and nonignored files (macOS, Python 3.14).
All 67 newly included fixture files matched the original archive byte for byte.
Workflow YAML/contract inspection, shell syntax, Python compilation and 3.11
syntax parsing, dependency consistency, and two browser regression scripts passed.
A separate diagnostic of the 479-test retained group completed 288 tests before
its deliberate 180-second local cap; this is not a full-group pass. Full Ubuntu
Python 3.11 execution and CodeQL on the changed source remain unverified.

## Maintenance boundaries

Preserve evidence, frozen candidates, current uncommitted work and consumed-attempt
markers. Follow [SSOT retention decisions](ssot.md#conflicts-removed-and-retained-paths)
before retiring historical entry points; shared E6 helpers still have current
callers. Cleanup does not activate those tools. Use the
[recovery guide](error-handling.md#limits-and-separate-follow-up) for lifecycle limits.

September 23 cleanup builds on `1f7c1ce` plus the current error-handling, security
and SSOT edits. The saved-history reader remains one cohesive module: its format
checks, cutoff projection and resolution-history functions are easier to read
without a new abstraction or changed API. Formatting preserved its complete
syntax tree. One unused `Decimal` import was removed from the collector.
CI commands were reflowed with module order and arguments verified unchanged.

Historical maintenance counts and the earlier launcher checkpoint are preserved
in [September 16 cleanup records](history/cleanup-20260916.md). They do not describe
the current focused commands above.

Cleanup validation: the saved-reader/resolution command above passed 32 tests.
Changed-module Python compilation, CLI `--help`, CI shell syntax, 45 local
documentation targets and `git diff --check` passed. Existing aiohttp AppKey and
asyncio timing warnings remained visible. The full CI matrix and live/browser
checks were not run; no service, credential, evidence, database or release
operation was performed.
