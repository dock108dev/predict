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

Primary runners use Ubuntu 24.04, Python 3.14 and Node 22. Readiness requires all
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

Install the [development environment](development.md#install-tools), Node 22 and
PostgreSQL tools, including `pg_config`. Run commands from the repository root.
Use temporary test state; never point checks at ordinary data or credentials.

```sh
PATH="$PWD/.venv/bin:$PATH" sh scripts/check-ci
.venv/bin/python -m ruff check app tests scripts/ci browser_tests
.venv/bin/python -m ruff format --check scripts/ci browser_tests tests/test_ci_reporting.py
sh -n scripts/check-ci
.venv/bin/python scripts/ci/docs.py
.venv/bin/python -m pytest -q tests/test_ci_reporting.py
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
user account. Browser requests are intercepted. Package smoke builds and installs
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

`.venv/bin/python scripts/ci/export.py EMPTY_DESTINATION` copies tracked and
nonignored source into an empty directory. It rejects publishable private state
and escaping symlinks. Required fixtures and executor inputs must remain available.
The export has no Git metadata; tests that inspect the index need a disposable Git
checkout. The documentation checker validates maintained links and rejects personal
paths, private-state links and local planning references.

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
