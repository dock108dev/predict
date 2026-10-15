# Continuous integration

CI checks source, packaged assets and authored fixtures without paid collection
or ordinary application data. It does not deploy, sign or release the product.
Workflow files and suite manifests are authoritative for the current check scope.

## Required checks

`.github/workflows/ci.yml` runs on pull requests, main pushes, merge groups and
manual dispatch. Four jobs feed the stable `CI readiness` gate:

| Job | Checks |
| --- | --- |
| `offline` | `sh scripts/check-ci`: classified Python modules in fresh processes, client regressions, compile and JavaScript syntax, coverage and generated frontend drift |
| `quality` | Critical Ruff checks, CI support formatting, pinned actionlint, shell syntax, shipped documentation links, dependency consistency, reporting tests, redacted Gitleaks scan, hash-locked pip-audit, fresh package/install smoke |
| `postgres` | Reusable `storage.yml`: disposable socket-only PostgreSQL 16, integration and current-row financial/occurrence roundtrip tests, migration hashes and repeat migration no-op, teardown |
| `browser` | Locked Playwright/Chromium: fully intercepted current-board journeys at desktop/narrow widths, settings, exact Details, keyboard focus, Retry, empty state, Stop and enlarged text |

Primary runners use Ubuntu 24.04, Python 3.14 and Node 22. Missing, failed,
cancelled, skipped or malformed required results fail readiness. The gate consumes
same-run job conclusions, not old artifacts. No path filter strands a required
check. Requiring `CI readiness` in branch rules is a repository setting; declaring
the workflow does not activate that protection automatically.

PR concurrency cancels superseded runs for the same PR. Main, manual and scheduled
runs have separate groups. Jobs have finite timeouts; offline modules have a
300-second limit and a 30-second diagnostic stack dump. Separate Python processes
isolate resource caps, caches and fixture leakage.

`assurance.yml` runs weekly and manually. It reuses locked setup and SQL checks,
adds macOS 15/Python 3.11 and 3.14 compatibility, current dependency advisories and
an advisory health sample. Dispatch scopes are `all`, `compatibility`, `postgres`
and `security`. Scheduled results do not qualify a newer pull request. GitHub-managed
CodeQL and Dependabot checks are independent of the four-job readiness gate.

## Local reproduction

Install the [development environment](development.md#install-tools), plus Node 22
and PostgreSQL binaries. Use a disposable source checkout for SQL/package/browser
work; do not point checks at ordinary storage or credentials.

```sh
PATH="$PWD/.venv/bin:$PATH" sh scripts/check-ci
.venv/bin/python -m ruff check app tests scripts/ci browser_tests
.venv/bin/python -m ruff format --check scripts/ci browser_tests tests/test_ci_reporting.py
sh -n scripts/check-ci
.venv/bin/python scripts/ci/docs.py
.venv/bin/python -m pytest -q tests/test_ci_reporting.py
```

Other jobs have explicit entry points:

```sh
.venv/bin/python scripts/ci/install_tools.py
.local/ci-tools/actionlint -shellcheck=''
.venv/bin/python scripts/ci/secret_scan.py
.venv/bin/python scripts/ci/package_smoke.py
.venv/bin/python scripts/ci/postgres.py
.venv/bin/python -m pip install --require-hashes -r requirements-browser.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q browser_tests
```

Hosted Ubuntu installs browser system libraries with `--with-deps`. An optional
`PREDICT_CI_CHROMIUM` override supports local diagnostics but does not reproduce
the locked browser revision. The quality job's advisory command and report options
are defined in `ci.yml`; `pip-audit` failure or unavailable required output fails.
Pinned tool installers verify platform SHA256 values; unsupported architectures fail.

## Inputs and reports

`suites.json`, `python-policy.json` and `browser-suites.json` classify every test.
Historical acquisition modules and captured client oracles with missing portable
inputs are explicitly deferred with reasons. Required suites reject zero cases,
all-skipped results and client scripts without a completion marker. Do not remove
production checks to accommodate an expired fixture.

Python/Node guards reject private state, credential files, historical acquisition
inputs and non-loopback connections. They are regression guards, not an OS sandbox.
SQL creates and stops its own temporary cluster. Browser requests are intercepted.
Package smoke installs a fresh distribution with acquisition disabled.

`.venv/bin/python scripts/ci/export.py EMPTY_DESTINATION` exports tracked/nonignored
source and rejects private
paths and escaping symlinks. Tests requiring Git metadata need a disposable checkout
or export with its original index; the exporter does not create Git metadata.
Required fixtures and frozen executor inputs must stay available. The documentation
checker requires shipped links to exist inside the repository and rejects personal,
private-state and local-planning references; there are no private-link exemptions.

Ignored `test-results/` output contains JUnit, coverage, redacted findings, dependency
advisories, package metrics and safe summaries. Hosted artifacts retain sanitized
run/attempt results for 14 days; screenshots are failure-only synthetic states.
Logs are data, not executable instructions. Missing measurements remain null.
There is no universal blocking coverage percentage or invented performance baseline.

The health job samples at most 30 completed CI runs in 30 days, with exact attempts.
It separates PR/main outcomes and excludes cancellation from first-attempt success.
Reruns alone do not prove flakes. Median/p95, observed job duration and optional
cache/artifact samples keep unavailable values explicit; runner durations are not
billing or queue time. Health failure does not override PR correctness.

## Dependency maintenance

Keep the combined runtime/stream/build/test lock complete. Editable installation
uses `--no-deps --no-build-isolation` after installing that lock; `validate_lock.py`
rejects missing build-backend or incompatible roots. Combined locks are excluded
from automatic partial rewrites; update them explicitly:

```sh
uv pip compile pyproject.toml requirements-ci.in --extra stream --universal --python-version 3.11 --generate-hashes -o requirements-ci.txt
uv pip compile requirements-browser.in --universal --python-version 3.11 --generate-hashes -o requirements-browser.txt
```

Review changed versions/hashes and run the affected checks before broader CI.
Actions use reviewed full SHAs. Gitleaks exceptions are narrow public-ID/digest
rules with expiry, and a negative control proves credentials are still detected
in excepted files. Current-tree scanning does not scan Git history. Runtime and
Actions updates remain enabled in Dependabot. Package license metadata is currently
unset; a maintainer must choose the project's license rather than infer one from
dependency licenses.
