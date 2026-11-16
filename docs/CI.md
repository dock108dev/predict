# Continuous integration

CI checks the source, packaged assets, and authored fixtures. The checks use
disposable state with acquisition disabled. Start with the
[development setup](development.md#install-tools) and run commands from the
repository root.

## Required checks

The [CI workflow](../.github/workflows/ci.yml) runs on pull requests, pushes to
`main`, merge groups, and manual dispatch. Its Ubuntu 24.04 runners use Python
3.14 and Node 24.

| Job | What it checks |
| --- | --- |
| Offline | Portable Python and client behavior, compilation, JavaScript syntax, generated frontend drift, and coverage |
| Source, security and package | Ruff, CI formatting, actionlint, shell syntax, maintained links, report validation, dependency locks, secret and advisory scans, and a fresh wheel install with HTTP startup |
| PostgreSQL storage | Four shards on disposable PostgreSQL 16 covering migrations, transactions, admission, publication, expiry, and recovery |
| Ordinary browser journey | Locked browser tooling with intercepted or loopback fixtures for first use, stable ranked refresh, desktop and mobile fee details, and Scanner journeys |

`CI readiness` requires all four jobs to pass in the same run. Missing, failed,
cancelled, or unexpectedly skipped required jobs fail the gate. To enforce the
check for merges, require `CI readiness` in a GitHub branch protection rule or
ruleset. PR runs validate GitHub's merge commit and report the PR head separately.
CI concurrency cancels superseded runs within the same pull request.

[Scheduled assurance](../.github/workflows/assurance.yml) runs Mondays at 07:23
UTC on the default branch. It checks macOS with Python 3.11 and 3.14, reuses the
PostgreSQL workflow, refreshes dependency advisories, and samples CI health.
Manual scopes are `all`, `compatibility`, `postgres`, and `security`. Every
scope includes the advisory health sample. CodeQL and Dependabot run separately
from readiness. Check jobs set `contents: read` and leave checkout credentials out
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

## Reports and dependencies

GitHub job summaries collect check, coverage, and case outcomes. Artifacts are
retained for 14 days. The compact readiness report is retained for 90 days,
subject to GitHub's retention policy. Local reports default to ignored `test-results/`. Use a
fresh output directory for each invocation that preserves existing reports.
JUnit summaries count serialized cases separately from pytest's totals, which
can include subtests. Inconsistent reports fail required checks. Coverage
describes the executed scope. Fixture results do not establish live provider
coverage or installed load times.

The readiness summary collects advisory measurements from the same workflow.
It reports named correctness cases for quote authority, financial eligibility,
exact pairing, accounting, and outage recovery. The outcome requires the
listed case evidence and shows failures, skips, and missing cases explicitly.
Artifacts from earlier attempts are eligible when they belong to the same run
and tested commit. Required job conclusions still determine the gate.

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
fixture and sample count. They describe the test environment and are useful for
spotting large changes on comparable runners. The compact `signals.json` keeps
commit and artifact identities, coverage gaps, named cases and timing samples.

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
