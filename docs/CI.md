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

## Check coverage and merge policy

Require **CI readiness** in branch protection or a ruleset to enforce these gates.
The workflows cannot configure that repository setting. The `merge_group` trigger
runs the same gates for merge queues, without path filters. Main pushes validate
the merged state; PRs validate GitHub's merge candidate, with the PR head separately
recorded. These workflows do not publish releases.

| Area / product risk | Exact workflow / job / command | Event / platform | Policy | Reason / evidence |
| --- | --- | --- | --- | --- |
| Python behavior, API boundaries, accounting and recovery | CI / Offline checks / `sh scripts/check-ci` | PR, main, merge group, manual; Ubuntu 24.04 / Python 3.14 | Required | `suites.json`; fresh interpreter per module, JUnit, branch coverage and explicit archival exclusions |
| Browser logic, generated inputs and compilation | CI / Offline checks / `scripts/ci/run_checks.py` | Same; Node 24 | Required | Every client module classified; duplicate entries and unexplained omissions rejected; generated asset drift checked |
| Lint, support formatting and workflow validation | CI / Source, security and package / Ruff, `actionlint -shellcheck=''`, `sh -n scripts/check-ci` | Same | Required | Parser/undefined-name policy for application; formatting for CI/browser support; Actions-aware expressions and inputs |
| Financial persistence, migrations, expiry and cancellation | CI / PostgreSQL storage / SQL migrations and boards / `python scripts/ci/postgres.py` | Same; PostgreSQL 16 | Required | Temporary socket-only cluster; two disjoint shards, each with a 900-second test limit; 25-minute jobs allow install/start/report/cleanup; fresh report directory required |
| Ordinary navigation, keyboard, errors and narrow layout | CI / Ordinary browser journey / `python -m pytest -q browser_tests` | Same; locked Chromium | Required | Authored intercepted board fixtures plus scanner/ticket loopback journeys; fixed fixture clock and displayed-read lease response |
| Fresh distribution, imports, assets and HTTP startup | CI / Source, security and package / `python scripts/ci/package_smoke.py` | Same | Required | Publishable Git-listed source build excluding ignored local catalogs, wheel inventory, separate locked installation, no collector; current stored-dashboard landing page |
| Secrets and dependency advisories | CI / Source, security and package / `secret_scan.py`, `pip_audit` | Same plus weekly dependency refresh | Required | Redacted current-tree Gitleaks with detection controls; CI/browser hash locks and the alternate `uv.lock` audited; scanner outages fail |
| Language security analysis | GitHub-managed CodeQL default setup | Hosted default setup, independent workflow | Advisory until branch rules require it | Managed in repository settings; inspect hosted results separately from local checks |
| macOS and supported Python endpoints | Scheduled assurance / macOS Python 3.11 and 3.14 | Monday 07:23 UTC; macOS 15; manual compatibility | Scheduled | Oldest supported runtime and primary runtime; does not exercise live provider data |
| Package size and dependency/license inventory | Package `metrics.json` | Required builds | Advisory measurement | Wheel bytes, file count, elapsed seconds, installed versions/license expressions; no comparable baseline or size budget |
| Reliability and resource trends | Scheduled assurance / CI health sample / `health.py` | Weekly and every manual scope | Advisory | Up to 30 completed runs / 30 days; event-separated rates, cancelled runs excluded; no inferred flakes or billing |
| Reporting/gate integrity | CI / Source, security and package / `pytest tests/test_ci_*.py`; CI readiness / `gate.py` | Every CI event | Required | Passing, failing, missing, malformed and skipped-report cases; first ten failing JUnit identities in summaries, escaped as data |
| Type checking and broad formatting | No repository-wide typing/format migration | N/A | Explicit omission | Dynamic dict/JSON application has no type-check configuration or established typed boundary; compilation, Ruff and executable schema/contract tests remain required. Broad annotation/style migration would be separate product work |
| ShellCheck, containers and IaC | Shell parser check; no container/IaC distribution | N/A for container/IaC | Explicit omission | Existing shell wrappers use syntax checks; actionlint ShellCheck integration remains disabled, so no claim of shell semantic lint coverage |
| Performance and accessibility scoring | Existing workload, keyboard and overflow assertions | Required functional lanes | Advisory beyond assertions | No stable Lighthouse/burst benchmark or automated WCAG conformance baseline; native/device usability and performance remain separate evidence |
| Signing, deployment and owner-data migrations | None | N/A | Not authorized by CI | Local read-only product; CI does not publish, sign, collect live odds or touch owner state |

Scheduled jobs use the default branch and may be delayed by GitHub; they are not
exact-time jobs. Treat the latest successful weekly assurance as stale after eight
days, and never substitute it for a current PR result. Manual `scope` is a bounded
choice; only excluded checks may be intentionally skipped. Shared storage uses
`workflow_call`, typed Python input and a result output, without secrets. The
setup composite shares only the repeated locked installation steps. All runners
are hosted; no `pull_request_target`, `workflow_run`, privileged PR token, retained
checkout credentials or self-hosted runner is used.

Coverage excludes explicitly deferred modules and measures executed app paths,
including branches. No changed-code delta is claimed without a matching primary
branch report, suite scope, toolchain and platform. History measurements span
changing candidates and are operational observations, not a performance baseline.
Package sizes and local durations likewise have no automatic regression threshold.
The report retains actual failures rather than reducing scope to obtain a pass.

### Tools and report handling

GitHub job summaries and artifacts retain check results; workflow artifacts expire
after 14 days. Required report or upload failures stay visible. Optional health API
outages produce unavailable metrics. Account billing and branch protection are
managed separately in GitHub settings.

Gitleaks scans source for secrets and actionlint validates workflow definitions.
`pip-audit` queries package advisories using dependency names and versions. Advisory
service failures fail the required scan; findings are not silently ignored.
CI and browser dependency locks and the alternate `uv.lock` are audited.
`uv_audit_requirements.py` exports pinned PyPI packages and hashes without installing
or resolving them, and the audit writes a separate `uv-audit.json`. Unreviewed
package sources and missing hashes fail the exporter.

CodeQL default setup is managed by GitHub independently of these workflows. Local
checks cannot establish its current status; consult the repository's code-scanning
results. No additional external coverage or reporting service is configured here.

The storage workflow partitions registered SQL targets across two independent
PostgreSQL jobs. Both must pass; a failed shard does not cancel the other. Local
`postgres.py` runs the entire suite by default; use `--shard-index 1 --shard-count 2`
(or index 2) to reproduce a CI partition. Each artifact includes its target list.
Verbose test names and a thread dump after 120 seconds in one test help diagnose
stalls. A process timeout records an explicit failure reason without inventing
JUnit results for unfinished tests.

## Readiness reports and package inputs

The readiness job retains `test-results/readiness/metrics.json` and `summary.md`
for each run and attempt, including malformed job-result input. Missing, skipped,
cancelled and failed required jobs fail the gate. Reports distinguish the tested
merge SHA, PR head and merge-group SHA; inspect the component artifacts for details.

Package checks include authored Markdown, text, HTML and compressed evidence as
well as code and structured assets. The clean installed smoke evaluates dated
fee bindings and reviewed source rules, so missing model inputs fail even when
imports succeed. Public-page fixtures have token-bearing fragments removed;
`app/fixtures/public-capture-redactions-20261028.json` records their provenance.

Each portable check owns a temporary directory to keep pytest cleanup from
pruning unrelated projects' test state. Generated reports stay in `test-results/`
and are not dependencies of the source distribution.

## Current limitations

Local publication/census, multisport, storage/delivery, capacity and two client
contract checks have unresolved failures. Passing browser, package or support
checks does not qualify the complete application. Keep the gates strict and use
the failing test output to select focused repairs before rerunning the full suite.
Hosted results must correspond to the source being reviewed.

The workflows do not enforce branch protection themselves. Administrators must
require `CI readiness` in repository rules. CodeQL default setup is independently
configured; it is not part of this aggregation. No additional reporting service
is required. Native summaries and artifacts remain in GitHub Actions; local
Gitleaks CLI analysis does not upload source to a scanning service. pip-audit sends
dependency identities to its advisory services. See the
[GitHub Actions billing documentation](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
for current runner and storage eligibility; do not infer account allowances from
local test results.

## October 28 local engineering checkpoint

The review at base `689135d52fad412765179b0164ad28d272910f09` implemented
same-run readiness reports, financial-evidence packaging and test registration,
per-check temporary state, and bounded spawn/financial/clock regression repairs.
Preserved local evidence lives under `test-results/ci-review-*`.

- Broad portable run: 2,798 passed / 26 failed Python cases and two failed client
  scripts (`ci-review-offline/summary.md`). Its suite-registration failure was
  subsequently repaired.
- Disposable SQL: 329 passed / 28 failed, without runner timeout
  (`ci-review-postgres/junit.xml`).
- Focused product recheck: the closeout reports 37 passed / 12 failed; its JUnit
  declares 85 tests and 12 failures in its suite summary, but contains 45
  testcase elements, nine with failure elements (`ci-review-recheck/junit.xml`).
  These totals do not directly reconcile with the closeout. Preserve the original
  report and reconcile counting/reporting during the next run; none establishes a pass.
- CI support, four browser journeys, package smoke, workflow/source validation,
  secret scan and locked dependency audits passed in their respective local runs.

The broad runs precede final targeted fixes and do not qualify the closing tree.
Remaining failing contracts concern SQL publication/census/multisport, seven-module
storage/delivery/capacity behavior, and client hold wording/quote binding. Repair
these without weakening identity, financial, clock, Stop or accounting gates.
The Desktop execution plan assigns the repair and final qualification separately.

No commit, push, hosted qualification or process restart was performed by that
CI review. At this documentation cleanup, repository HEAD is `3338bea`, which
contains subsequent changes; neither its loaded runtime identity nor its hosted
status was established by this documentation pass. The historical dirty-tree
statement describes the review, not the current checkout. Branch protection was
reported ineffective at review time; requiring `CI readiness` remains an optional
owner/admin decision, not an applied setting or a prerequisite silently added here.
