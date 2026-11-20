# Continuous integration

CI checks the source, packaged assets, and authored fixtures. The checks use
disposable state with acquisition disabled. Start with the
[development setup](development.md#install-tools) and run commands from the
repository root.

## Required checks

The [CI workflow](../.github/workflows/ci.yml) runs on pull requests, pushes to
`main`, merge groups, and manual dispatch. Its Ubuntu 24.04 runners use Python
3.14 and Node 24.

| Behavior / risk | Exact workflow, job and entry point | Event / platform / checkpoint | Status | Authority / evidence |
| --- | --- | --- | --- | --- |
| Incorrect prices, fees, matching or delivery | `CI` / `Offline checks` / `sh scripts/check-ci` checks portable Python and Node behavior, compilation, JavaScript syntax, generated assets and the test manifest. It retains JUnit and Python line and branch coverage. | PR, `main` push, merge group, manual / Ubuntu 24.04 | Required by `CI readiness` | Repository `ci.yml` and `gate.py`; full suite registrations remain unchanged. |
| Unshippable package or unsafe source | `CI` / `Source, security and package` runs Ruff, actionlint, shell syntax, docs and `pytest tests/test_ci_*.py`, plus the redacted Gitleaks scan, pip-audit for both lock sources, and a wheel build, locked install and HTTP startup. | Same CI events / Ubuntu 24.04 | Required by `CI readiness`. Duplication and complexity measurements are advisory. | Repository quality job and expanded reporter; runs before behavior fanout. |
| Transaction, migration or recovery failure | `CI` / `PostgreSQL storage` calls `Shared disposable storage assurance`. Four shards run `scripts/ci/postgres.py` against temporary PostgreSQL 16 databases. | Same CI events and manual assurance / Ubuntu 24.04 | Required by the calling workflow | Repository reusable `storage.yml`; all four SQL shards retained. |
| Desk and Scanner journeys break | `CI` / `Ordinary browser journey` / `pytest browser_tests` uses locked Chromium and intercepted or loopback fixtures for first use, ranked refresh, keyboard, fee details and Scanner journeys. | Same CI events / Ubuntu 24.04 | Required by `CI readiness` | Repository browser job; required cases validated from JUnit. |
| New advisories for locked dependencies | `Scheduled assurance` / `Dependency refresh` audits both hash-locked requirements files and the `uv.lock` export. `CI health sample` reads bounded Actions history. | Weekly default branch or manual assurance / Ubuntu 24.04 | Dependency audit required in the security scope. History is advisory. | Repository `assurance.yml`; optional health telemetry cannot override security results. |
| Deployment uses an unverified image | `Deploy Predict dev server` / `Build and verify Hetzner images` runs the proxy and Compose smoke scripts before GHCR publication. `Deploy Predict to Hetzner` consumes the verified digests, and `Release result` retains the stage outcomes. | Manual branch dispatch / Ubuntu 24.04 | Release workflow. The repo variable, dispatch input and `hetzner` environment govern deployment. | Repository `hetzner.yml`; independent manually authorized image/deployment checkpoint. |

`CI readiness` requires all four jobs to pass in the same run. Missing, failed,
cancelled, or unexpectedly skipped required jobs fail the gate. It also requires
matching downloaded reports and executed JUnit evidence for quality, offline,
browser and **all four** SQL shards. The artifact download precedes the gate;
download failure cannot become an evidence-free pass. Offline report entries
must cover the current registered suites, client checks and syntax checks.
The quality inventory and SQL shard identity are checked independently of the
local affected-test router. Malformed, zero-case, failed or missing required
evidence fails readiness even when Actions reports successful jobs. PR runs validate
GitHub's merge commit and report the PR head separately.
CI cancels superseded runs within the same pull request.

`CI readiness` is a workflow result. Requiring it for merges is a separate
GitHub branch-protection or ruleset setting; inspect repository settings before
assuming merges enforce it. Manual deployment has its own image and environment
checks. [GitHub required-check semantics](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks).

### Quality before expensive behavior work

`Source, security and package` runs first. `Offline checks`, the four-shard
PostgreSQL lane and `Ordinary browser journey` depend on its success, then run in
parallel. The stable `CI readiness` job runs with `always()` and requires success
from **all four** required jobs. A quality failure intentionally skips behavior
work and fails readiness; skipped work is never a behavior pass or N/A.

For deliberate failure diagnosis, manually dispatch `CI` with the typed boolean
`full_diagnostics: true`. Behavior lanes may then run despite quality failure;
the override cannot bypass readiness and does not run after workflow
cancellation. Normal PR/push/merge-group checks still run every registered test
when quality succeeds. No hosted affected-test selection, prediction or cached
result reuse is used.
Readiness JSON and its actual Actions summary record the mode and explain why
behavior ran or was prevented.

The trade-off is later independent behavior feedback on quality-invalid
candidates and a quality-job delay before passing candidates' fanout. The manual
override is the diagnostic escape hatch. The dependency avoids expensive work on a revision that a required quality
check has already rejected. Release authorization remains separate.

[Scheduled assurance](../.github/workflows/assurance.yml) runs Mondays at 07:23
UTC on the default branch, subject to runner scheduling. The weekly run checks
for new dependency advisories between code changes, including the combined CI
locks excluded from Dependabot version updates. Manual scopes are `all`,
`postgres`, and `security`. The regular CI workflow runs the same PostgreSQL
suite on code changes. Every assurance scope includes the advisory health sample.
Verify macOS-specific setup locally using the [quickstart](../README.md#requirements-and-quickstart).
CodeQL and Dependabot run separately from readiness. Check jobs set
`contents: read` and leave checkout credentials out
of later steps. The scheduled history reader adds `actions: read`. The manual
Hetzner workflow builds and smoke-tests images before
publishing them by digest. Deployment also requires its environment controls.
[Release instructions](hetzner.md#releases)

## Local reproduction

Use the [focused check map](development.md#focused-checks) for routine changes.
The portable manifest uses explicit Python and client test lists, without a
predictive result cache. To run the complete portable lane in fresh processes:

```sh
PATH="$PWD/.venv/bin:$PATH" sh scripts/check-ci --output "$(mktemp -d)"
```

The portable checks use Poppler's `pdftotext` for the PDF renderer fixture.
The runner rejects zero-case and entirely skipped suites and records explained
fixture exclusions in the manifests under `scripts/ci/`.

For other affected checks, use the matching command below:

```sh
.venv/bin/python scripts/ci/docs.py
.venv/bin/python -m ruff check app tests scripts/ci browser_tests
.venv/bin/python -m ruff format --check scripts/ci browser_tests tests/test_ci_*.py tests/ci_support.py
.venv/bin/python -m pytest -q tests/test_ci_*.py
.venv/bin/python scripts/ci/install_tools.py
.local/ci-tools/actionlint -shellcheck=''
sh -n scripts/check-ci
.venv/bin/python scripts/ci/package_smoke.py --report-dir "$(mktemp -d)"
```

The tool installer verifies release checksums. The package check builds from
publishable source, inspects wheel contents, and starts the fresh installation
with acquisition disabled.

Run SQL tests as an ordinary user with PostgreSQL 16's `pg_config` on your path.
The runner creates and stops its own socket-only cluster. Set `PG_CONFIG` or
pass `--pg-config` to select the matching tools. With no test selector, the
runner runs the complete registered suite.

```sh
.venv/bin/python scripts/ci/postgres.py --report-dir "$(mktemp -d)" --tests tests/test_ordinary_publication_sql.py
```

To reproduce a hosted partition, pass `--shard-index` with a value from 1 to 4
and `--shard-count 4`. SQL reports record the database engine, Python version,
and selected targets. An interrupted process records its failure without
inventing results for unfinished tests.

Install both locks together for browser checks so conflicting pins fail before
the tests run. Add Playwright's `--with-deps` flag for the hosted Linux setup.

```sh
.venv/bin/python -m pip install --require-hashes -r requirements-ci.txt -r requirements-browser.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q browser_tests
```

The documentation check rejects links to private or ignored local files. The
optional `scripts/ci/export.py` command validates
`config/ci-retained-resources.json` when exporting a standalone retained fixture
set. Ordinary setup and portable tests use the shipped source and authored
fixtures.

The test contract checks that the portable dispositions and the quality job's
`tests/test_ci_*.py` collection agree. A file marked quality-only with a name
outside that glob fails validation. SQL `--tests` reports identify a focused run
and retain its exact targets separately from the full registered shard lane.

The portable pregame reference cases assert priority fallback, complete
same-line partitions, and exact push/draw probabilities. The valuation cases
assert actual outlay, fee rounding, per-state returns, and ranking using
authored terms. The storage shard summaries also name the selected-unit
publication, pagination, and real PostgreSQL lock-recovery cases. The ordinary
browser cases cover current boards, saved captures, journal workflows and
keyboard/touch interactions at desktop and phone widths. These checks use fixtures and disposable storage. Live reference,
fee, fill, and collection coverage require separate evidence.

The current-board regression groups protect these boundaries:

| Behavior | Tests | Expected protection |
| --- | --- | --- |
| Conservative exact-pair reference | `test_current_pregame_reference_policy.py` | Hand-checked probabilities and score; incomplete or conflicting pairs rejected; line eligibility unchanged |
| Two-sided fee math | `test_pregame_arbs.py` | Exact cents, both outcomes positive, fees can erase a gross edge, no probability dependency |
| Observed sportsbook quotes | `test_pregame_sportsbook_prices.py` | Exact event/line, clocks and availability; exchanges cannot become fee-free books |
| PostgreSQL admission and recovery | `test_current_pregame_sql.py`, `test_pregame_board_views_sql.py` | Atomic values, pagination, withdrawals, fee-only expiry/cache invalidation and recovery without EV |
| Current browser flows | `browser_tests/test_pregame_current.py`, `browser_tests/test_pregame_games_arbs.py` | Native actions and focus, pinned inspection, late-response protection, retained filters and visible polling failures |
| Snapshot helper | `test_dev_snapshot.py` | Failed transfer stays partial/private and never restores; non-snapshot socket rejected using mocked I/O |

These cases are retained as distinct calculation, persistence and UI boundaries;
the runtime/provider boundary remains unverified by their fixtures. The
portable modules are registered in the existing required manifest; the SQL cases
are registered in the disposable PostgreSQL lane.

### Selecting local cases

The local entry point is a conservative **subsystem router**, not predictive
selection or a result cache:

```sh
.venv/bin/python scripts/ci/affected.py --plan
.venv/bin/python scripts/ci/affected.py
.venv/bin/python scripts/ci/affected.py --base origin/main --plan
.venv/bin/python scripts/ci/affected.py --full --plan
```

Omit `--plan` to execute. Choose your PostgreSQL 16 `PG_CONFIG` when it is not on
PATH. `--full` runs all registered portable, PostgreSQL, Chromium and quality
behavior lanes, plus docs; it does not replace the security/package/toolchain
jobs in required CI. Hosted workflows and their full checks are unchanged.

The default comparison is **HEAD versus index + worktree**, plus nonignored
untracked files. `--base` adds committed branch work since `merge-base(BASE,
HEAD)`. Rename detection is disabled so old and new paths both participate.
Known journal, SGO and pregame source/assets route to their module suites and
storage/browser consumers. Changed test modules are included; literal Python
imports of changed test helpers add inspected consumers or broaden. New
unclassified tests are included and broaden; update their required manifest
classification before merging. A changed shared fixture, migration, lockfile,
configuration or `AGENTS.md`, unknown source, deleted input or unknown helper
consumer falls back visibly to the registered behavior lanes. Broadening can be expensive:
inspect `--plan` first. Documentation alone selects the docs check. An empty
working diff executes no tests and makes no pass claim.

This bounded routing table is intentionally conservative. It does not infer
arbitrary dynamic imports, runtime file dependencies or external-service
changes; use `--full` or explicit additional targets for those. Do not interpret
its selection as exhaustive dependency analysis. Extend the mappings when
adding consumers to the maintained subsystems. The router uses the existing
pytest and disposable PostgreSQL entry points; it does not install a coverage
history service. [Pytest selection and discovery](https://docs.pytest.org/en/stable/how-to/usage.html).

First-run behavior is identical to subsequent runs: there is no selection or
result database to warm. The ignored `.local/test-affected/last-plan.json` is
rewritten diagnostic output and is never read as an input. Missing, stale or
corrupt diagnostics cannot suppress tests; no prior success is reused. Runs
stop at the first failing command and preserve its status, including pytest's
exit 5 for accidental zero collection. Each execution allocates fresh retained JUnit/SQL outputs under the ignored
`.local/test-affected/run-*/` directory. PostgreSQL continues to use its existing
fresh socket-only disposable runner; a direct `postgres.py` invocation still
requires an empty report directory. Use `--collect-only -q` or explicit pytest node IDs
for narrower iteration; SQL node IDs go to `postgres.py --tests`. Pytest `--lf`
is failure history, not affected selection.

The selector tests in `tests/test_ci_affected.py` cover working-tree and
merge-base changes, helper consumers, new/deleted/renamed inputs, configuration,
missing diagnostics and failure propagation. Keep those cases aligned when
changing the routing rules.

## Reports and dependencies

GitHub job summaries collect check, coverage, and case outcomes. Artifacts are
retained for 14 days. The compact readiness report is retained for 90 days,
subject to GitHub's retention policy. Local reports go to the ignored
`test-results/` directory by default. Use a fresh output directory per run.
JUnit summaries count serialized cases separately from pytest's totals, which
can include subtests. Inconsistent reports fail required checks. Coverage
describes the executed scope. Fixture results do not establish live provider
coverage or installed load times.

The readiness summary collects advisory measurements from the same workflow.
It reports named correctness cases for quote authority, financial eligibility,
exact pairing, accounting, and outage recovery. The outcome requires the
listed case evidence and shows failures, skips, and missing cases explicitly.
Case artifacts must match the run, commit and execution attempt. An earlier
artifact is eligible only when the Actions Jobs API identifies that job as a
successful job carried over into the rerun. If the API or the new artifact is
unavailable, the missing case evidence stays visible. The advisory summary
lists carried-over artifacts separately. The required gate separately validates
reports through `scripts/ci/required_evidence.py`, using a complete latest-jobs
inventory only when older reports are needed on a rerun. Unavailable or truncated
history grants no reuse. Complete current-attempt evidence needs no API call.
Job conclusions **and** required reports determine readiness; advisory telemetry
cannot override either. [GitHub rerun behavior](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)

Python coverage reports lines and branches separately, with component totals
and coverage of executable lines and branch origins added or modified in the
tested tree. The report links missed lines or branches to the tested commit.
For pull requests the comparison base is the tested merge commit's first
parent. Pushes and merge groups use their event's previous or base SHA.
Coverage deltas require a successful exact-base artifact with matching offline
manifest, platform family, Python and coverage tools. The summary lists
unmeasured changed files and withholds comparisons when evidence is unavailable.

The advisory summary also includes exact duplicate Python function bodies and
Ruff complexity findings, secret and dependency audit counts, the slowest
completed job and the sampled first-attempt pass rate. Dependency count changes
can reflect updates to advisory databases. Timing measurements come from the
existing browser, PostgreSQL selection and desk recovery fixtures, including the
fixture and sample count. Timing deltas require the same fixture, sample count,
response budget where applicable, runner class, Python and PostgreSQL or
Playwright versions. Older reports missing that metadata still show their
measurements. The compact `signals.json` keeps commit and artifact identities,
coverage gaps, named cases and timing samples.

Manual release attempts retain `release-result-<run>-<attempt>` for 14 days.
The report lists proxy, Compose smoke, digest publication and deployment step
outcomes. It records the reason for a publish-only, disabled or unreached
deployment. An unexpectedly skipped requested deployment is visible as a
failure. The report job can read contents and receives no deployment secrets.

Gitleaks scans the publishable worktree. Published findings include validated
relative paths, rule IDs, and line numbers. Dependency audits check the two
hash-locked manifests and a requirements export of `uv.lock`. The advisory
service receives dependency names and versions. Missing required scan results
fail the check. Scheduled health uses short, read-only GitHub Actions history
and reports unavailable measurements separately.

Regenerate locks with `uv` after changing dependencies, then review the versions
and hashes and run the affected checks:

```sh
uv pip compile pyproject.toml requirements-ci.in --extra stream --universal --python-version 3.11 --generate-hashes -o requirements-ci.txt
uv pip compile requirements-browser.in --universal --python-version 3.11 --generate-hashes -o requirements-browser.txt
.venv/bin/python scripts/ci/validate_lock.py
```

The setup action installs the lock before the editable package and uses
`--no-deps --no-build-isolation` for the editable install. Dependabot checks
Python and Actions dependencies. External Actions use full commit SHAs.
