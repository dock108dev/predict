# Continuous integration

CI checks source, packaged assets and authored fixtures without paid collection
or ordinary application data. It does not deploy or release the product. The
workflow files and suite manifests define the current check scope.

## Required checks

`.github/workflows/ci.yml` runs on pull requests, pushes to `main`, merge groups
and manual dispatch. Four jobs feed the stable `CI readiness` gate:

| Job | Checks |
| --- | --- |
| `offline` | Portable Python modules in fresh processes, client regressions, compilation, JavaScript syntax, coverage reporting and generated frontend drift |
| `quality` | Ruff, CI support formatting, pinned actionlint, shell syntax, documentation references, dependency consistency, reporting tests, redacted Gitleaks scan, hash-locked pip-audit and a fresh package/install smoke test |
| `postgres` | Disposable socket-only PostgreSQL 16, migrations, current-row financial and occurrence roundtrips, transaction tests and teardown |
| `browser` | Locked Playwright/Chromium journeys with intercepted responses: wide/narrow layouts, settings, Details, keyboard focus, Retry, empty states, Stop and enlarged text |

Primary runners use Ubuntu 24.04, Python 3.14 and Node 24 (`.nvmrc`). Readiness requires all
four jobs to succeed in the same run; skipped, cancelled, missing or malformed
results fail. Enable the `CI readiness` required check in GitHub branch rules
separately. Pull-request concurrency cancels superseded runs; other event types
use separate concurrency groups.

`assurance.yml` runs weekly and manually. It adds macOS 15 with Python 3.11 and
3.14, reuses SQL checks, refreshes dependency advisories and samples CI health.
Manual scopes are `all`, `compatibility`, `postgres` and `security`; the health
sample runs for every dispatch. Scheduled results do not replace a pull request's
checks. CodeQL and Dependabot checks are independent of this readiness gate.

## Local reproduction

Install the [development environment](development.md#install-tools), Node 24 and
PostgreSQL 16 tools, including `pg_config`. Run commands from the repository root.
Use temporary test state; never point checks at ordinary data or credentials.

```sh
PATH="$PWD/.venv/bin:$PATH" sh scripts/check-ci
.venv/bin/python -m ruff check app tests scripts/ci browser_tests
.venv/bin/python -m ruff format --check scripts/ci browser_tests tests/test_ci_*.py tests/ci_support.py
sh -n scripts/check-ci
.venv/bin/python scripts/ci/docs.py
.venv/bin/python -m pytest -q tests/test_ci_*.py
```

Other job entry points are:

```sh
.venv/bin/python scripts/ci/install_tools.py
.local/ci-tools/actionlint -shellcheck=''
.venv/bin/python scripts/ci/secret_scan.py
.venv/bin/python -m pip_audit -r requirements-ci.txt -r requirements-browser.txt --require-hashes --disable-pip --progress-spinner off --timeout 20
.venv/bin/python scripts/ci/package_smoke.py
.venv/bin/python scripts/ci/postgres.py
.venv/bin/python -m pip install --require-hashes -r requirements-browser.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q browser_tests
```

The tool installer downloads pinned validators and verifies their platform
checksums; unsupported architectures fail. Dependency auditing reads current
advisory data. Hosted Ubuntu installs Chromium's system libraries with
`--with-deps`. `PREDICT_CI_CHROMIUM` can select a local browser for diagnostics,
but then the browser revision differs from the locked CI revision.

SQL checks create and stop their own temporary cluster and require an ordinary
user account. Set `PG_CONFIG` to select PostgreSQL 16 explicitly and `--report-dir`
to keep local environments separate; the SQL runner records its Python and
PostgreSQL identity and rejects other majors unless `--allow-other-postgres` is
explicitly passed for compatibility diagnostics. Browser requests are intercepted. Package smoke builds and installs
a fresh distribution with acquisition disabled. The Python and Node isolation
guards reject private state, credential files, historical acquisition inputs and
non-loopback connections; they are regression guards rather than an OS sandbox.

## Suite inputs and output

`scripts/ci/suites.json`, `python-policy.json` and `browser-suites.json` classify
the Python and client tests. Older acquisition modules and captured client oracles
with unavailable portable inputs are deferred with reasons. Required suites reject
zero cases, all-skipped results and client scripts without a completion marker.
Do not remove production checks to accommodate an expired fixture.

The SQL suite verifies current rows, transient calculations, input-bound Details,
expiry and restart behavior. Separate compatibility tests exercise retained
storage codecs and HTTP 410 responses for retired ordinary-history routes.
Intercepted browser responses use current version 2 calculation contexts.

For retained-fixture diagnostics,
`.venv/bin/python scripts/ci/export.py EMPTY_DESTINATION` copies tracked and
nonignored source and validates the resources declared in
`config/ci-retained-resources.json`. Those historical inputs must exist locally;
this export is not required for ordinary setup or portable tests. It rejects
publishable private state and escaping symlinks. The export has no Git metadata,
so index-dependent tests require their own disposable repository fixture.
The documentation checker validates maintained links and rejects personal paths,
private-state links and local planning references.

Reports under ignored `test-results/` include JUnit, coverage, redacted findings,
dependency advisories and package measurements. Hosted artifacts are retained for
14 days. Browser screenshots contain synthetic failure states only. Missing
measurements remain null; there is no universal coverage threshold or fixed
performance baseline.

The advisory health sample reads at most 30 completed CI runs from the last 30
days. It separates pull-request and main results, excludes cancellation from
first-attempt success and keeps unavailable timing/cache/artifact data explicit.
Health findings do not override a pull request's correctness checks.

## Dependency maintenance

Keep the combined runtime, stream, build and test lock complete. CI installs it
before the editable package with `--no-deps --no-build-isolation`.
`validate_lock.py` checks required roots and the build backend. Regenerate locks
explicitly with `uv` installed:

```sh
uv pip compile pyproject.toml requirements-ci.in --extra stream --universal --python-version 3.11 --generate-hashes -o requirements-ci.txt
uv pip compile requirements-browser.in --universal --python-version 3.11 --generate-hashes -o requirements-browser.txt
```

Review changed versions and hashes, then run affected checks. Actions use reviewed
full commit SHAs. Gitleaks exceptions are narrow public-ID/digest rules with expiry
and a negative control; the scan covers the current tree rather than Git history.
Dependabot covers runtime and Actions updates. The project currently has no chosen
license in package metadata; dependency licenses do not supply a project license.

## Reports and failure handling

Required missing, malformed, cancelled and all-skipped checks fail readiness.
JUnit durations must be finite and nonnegative. Dependency findings and audit
outages fail the audit; unavailable measurements remain null. Coverage describes
the executed scope, not a universal threshold or an unmeasured performance delta.

The secret scan covers tracked and nonignored publishable files. It does not
hydrate ignored historical review resources. Setup, export, scanner or report
failures produce a failing `secret-metrics.json` with a safe stage reason and
null findings; an absent scan never becomes zero findings. The standalone
retained-resource export still validates its declared fixture hashes.

The Python and client fixtures use the CI interpreter and disposable state.
Cloning a quote into another authored market must remove the original market's
content-bound book confirmation; fixtures cannot reuse that provider proof.
Source prices retain original clocks, and HTTP reads cannot invent a background
financial publication. Runtime replacement revokes selected authority while a
data restart preserves unchanged durable source rows and epoch.

## Scope and limitations

The required browser journeys exercise scanner interaction and manual tickets;
SQL tests cover small financial, ready-ticket, expiry and missing-depth cases.
Full-scale stress and source-to-screen performance are not established by these
checks. Authored fixtures do not establish current provider coverage or valid
production execution destinations.

Workflow tokens use read-only permissions. Fork checks receive no application
credentials, checkout does not persist credentials, and Actions are pinned by
commit. No deployment, publishing or external reporting service is configured
by these checks. Configure `CI readiness` as a required branch check separately;
workflow success alone cannot enforce merge policy.
