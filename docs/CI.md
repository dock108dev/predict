# CI workflows

CI validates source, portable offline behavior, locked dependencies and packaged
assets. It does not access live market providers or establish price freshness.

## Jobs and events

Pull requests, pushes to `main` and manual runs execute `.github/workflows/ci.yml`:

| Job | Required checks |
| --- | --- |
| Offline checks | Compilation, dashboard JavaScript syntax, explicitly selected Python tests, browser client regressions, coverage and usable reports |
| Source, security and package | Critical Ruff rules, CI support formatting, Actions syntax, documentation references, reporting regressions, dependency audit and package smoke checks |

The primary environment is Ubuntu 24.04, Python 3.14 and Node 22. Independent jobs
run in parallel; superseded pull-request runs cancel within their concurrency
group. Main pushes and scheduled/manual work have separate concurrency handling.

`.github/workflows/assurance.yml` runs weekly on Monday at 07:23 UTC and manually.
Its scopes cover macOS 15/Python 3.11 and 3.14 compatibility, optional PostgreSQL
16 integration, dependency refresh and read-only CI health sampling. Scheduled
checks do not qualify a newer pull request. Exact runner/tool settings live in
the workflows and `.github/actions/setup/action.yml`.

Repository check policy does not configure branch protection. Require `Offline
checks`, `Source, security and package` and the applicable CodeQL contexts only
after confirming their names on a pull request. Scheduled jobs should not be
required merge checks. If enabling a merge queue, add the appropriate
`merge_group` triggers first.

## Local checks

For installation and a small set of affected tests, use [development](development.md).
The complete portable workflow uses the existing locked environment:

```sh
.venv/bin/python -m pip check
PATH="$PWD/.venv/bin:$PATH" sh scripts/check-ci
.venv/bin/python -m ruff check app tests scripts/ci
.venv/bin/python -m ruff format --check scripts/ci tests/test_ci_reporting.py
.venv/bin/python scripts/ci/install_tools.py
.local/ci-tools/actionlint -shellcheck=''
.venv/bin/python scripts/ci/docs.py
.venv/bin/python -m pytest -q tests/test_ci_reporting.py
```

`install_tools.py` downloads checksum-pinned validators; dependency installation
and auditing require network access. The quality job also runs hashed `pip_audit`
and `scripts/ci/package_smoke.py`. Package smoke builds a fresh source distribution
and wheel, installs them in a temporary environment, checks declared assets and
runs acquisition-disabled loopback routes. It does not start ordinary providers.
Do not run that broader workflow merely to edit documentation.

## Test selection and isolation

`scripts/ci/suites.json` lists portable Python groups. `python-policy.json` records
explicitly deferred modules/classes/methods and their reasons; `browser-suites.json`
does the same for client tests. `validate_contract.py` rejects missing, duplicate,
unclassified and stale selections. Fresh processes keep memory-sensitive groups
independent. Additional saved-data tests may require separately supplied local
observations; they are not setup checks.

Tests use authored fixtures and temporary synthetic state. The offline runner
inherits Python and Node guards against private `.local`/`.env` reads, historical
`evidence/`/`examples/` reads and non-loopback sockets. These are regression guards,
not an operating-system sandbox. Ordinary source acquisition is not a CI fixture.

`scripts/ci/export.py EMPTY_DESTINATION` copies tracked and nonignored files for
checks without local notes/state. Manifest-sensitive tests need checkout Git
metadata. Supply it only in the disposable export: a local `git clone --no-checkout`,
moving its `.git` directory and `git read-tree HEAD` reproduces the baseline index
without checking out over exported files. Do not commit the working repository
or upload that source copy just to run checks.

## Reports and maintenance

Use a fresh report directory; stale results cannot qualify a run. Offline groups
continue after independent failures and retain explicit interrupted/not-run
outcomes. Missing, malformed, empty or unexpectedly skipped required reports fail.
Coverage and wheel size are advisory; there is no universal threshold or invented
baseline. A passing report export cannot hide an earlier failed group.

Reports include source/ref/event, environment, counts and durations. JUnit,
coverage, audit, package metrics and logs stay in ignored `test-results/` locally
or unique GitHub run/attempt artifacts with 14-day retention. Summaries escape
values and replace progress rather than repeatedly appending. No source archives,
provider credentials or owner captures are uploaded; logs are diagnostic data.

Dependencies are hash-locked in `requirements-ci.txt`. Regenerate after a dependency
change, then review versions and hashes:

```sh
uv pip compile pyproject.toml requirements-ci.in --extra stream --universal --python-version 3.11 --generate-hashes -o requirements-ci.txt
```

Dependabot updates pip and pinned Actions. Pip-audit queries the PyPI advisory
service with dependency names/versions; unavailable or missing findings fail.
Existing GitHub CodeQL and secret scanning are separate repository settings.
Workflows use read-only permissions and do not retain checkout credentials.
There is no release/signing/deployment workflow or external coverage upload.
