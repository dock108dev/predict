# Continuous integration

CI checks the source, packaged assets, and authored fixtures. The checks use
disposable state with acquisition disabled. Start with the
[development setup](development.md#install-tools) and run commands from the
repository root.

## Required checks

The [CI workflow](../.github/workflows/ci.yml) runs on pull requests, pushes to
`main`, merge groups, and manual dispatch. Its Ubuntu 24.04 runners use Python
3.14 and Node 24.

| Product risk | Exact workflow, job and entry point | Event and platform | Policy |
| --- | --- | --- | --- |
| Incorrect prices, fees, matching or delivery | `CI` / `Offline checks` / `sh scripts/check-ci` checks portable Python and Node behavior, compilation, JavaScript syntax, generated assets and the test manifest. It retains JUnit and Python line and branch coverage. | PR, `main` push, merge group, manual / Ubuntu 24.04 | Required by `CI readiness` |
| Unshippable package or unsafe source | `CI` / `Source, security and package` runs Ruff, actionlint, shell syntax, docs and `pytest tests/test_ci_*.py`, plus the redacted Gitleaks scan, pip-audit for both lock sources, and a wheel build, locked install and HTTP startup. | Same CI events / Ubuntu 24.04 | Required by `CI readiness`. Duplication and complexity measurements are advisory. |
| Transaction, migration or recovery failure | `CI` / `PostgreSQL storage` calls `Shared disposable storage assurance`. Four shards run `scripts/ci/postgres.py` against temporary PostgreSQL 16 databases. | Same CI events and manual assurance / Ubuntu 24.04 | Required by the calling workflow |
| Desk and Scanner journeys break | `CI` / `Ordinary browser journey` / `pytest browser_tests` uses locked Chromium and intercepted or loopback fixtures for first use, ranked refresh, keyboard, fee details and Scanner journeys. | Same CI events / Ubuntu 24.04 | Required by `CI readiness` |
| New advisories for locked dependencies | `Scheduled assurance` / `Dependency refresh` audits both hash-locked requirements files and the `uv.lock` export. `CI health sample` reads bounded Actions history. | Weekly default branch or manual assurance / Ubuntu 24.04 | Dependency audit required in the security scope. History is advisory. |
| Deployment uses an unverified image | `Deploy Predict dev server` / `Build and verify Hetzner images` runs the proxy and Compose smoke scripts before GHCR publication. `Deploy Predict to Hetzner` consumes the verified digests, and `Release result` retains the stage outcomes. | Manual branch dispatch / Ubuntu 24.04 | Release workflow. The repo variable, dispatch input and `hetzner` environment govern deployment. |

`CI readiness` requires all four jobs to pass in the same run. Missing, failed,
cancelled, or unexpectedly skipped required jobs fail the gate. To enforce the
check for merges, require `CI readiness` in a GitHub branch protection rule or
ruleset. PR runs validate GitHub's merge commit and report the PR head separately.
CI cancels superseded runs within the same pull request.

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
browser first-use cases include the fictional practice journeys at desktop and
phone widths. These checks use fixtures and disposable storage. Live reference,
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
the runtime/provider boundary remains unverified by their fixtures. The new
portable modules are registered in the existing required manifest; the SQL cases
are registered in the disposable PostgreSQL lane.

### Selecting local cases

Use pytest node IDs or affected modules for routine changes. Check discovery
with `--collect-only -q` when a selector is uncertain. Pass SQL node IDs to
`postgres.py --tests`. An unexpected zero-case pytest result exits with code
5. When a shared fixture or configuration change has unclear reach, run the
affected suite. Pytest's `--lf` uses failure history.

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
lists carried-over artifacts separately. Required job conclusions determine the
gate. [GitHub rerun behavior](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)

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
