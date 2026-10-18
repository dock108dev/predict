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

## Check map and event policy

| Area / product risk | Exact workflow / job / command | Event / platform | Policy | Reason / evidence |
| --- | --- | --- | --- | --- |
| Portable behavior, API contracts, financial calculations and cleanup | CI / `offline` / `sh scripts/check-ci` | PR, main push, merge group, manual / Ubuntu 24.04, Python 3.14, Node 24 | Required | Registered Python and client suites; isolation forbids private inputs and non-loopback network |
| Omitted tests, missing reports and generated drift | `validate_contract.py`, `run_checks.py`; frontend builders invoked by `check-ci` | Same | Required | Every discovered test must have an explicit classification; required zero/all-skipped suites fail |
| Lint, compilation and formatting | CI / `quality` / Ruff commands above; compile and JS syntax in offline | Same | Required | Whole maintained Python lint scope; formatting covers CI support and browser harnesses. Legacy application-wide reformatting is outside this change |
| Broad static type checking | No declared type-checker configuration | N/A | Not claimed | Dynamic legacy application has no established typing gate; compilation, schemas, lint and behavioral contracts remain required. A broad annotation migration is outside this CI change |
| Workflow and shell correctness | CI / `quality` / `actionlint -shellcheck=''`, `sh -n scripts/check-ci` | Same | Required | Actions-aware expression/input validation plus shell syntax; ShellCheck analysis is not enabled |
| Documentation references and executable examples | CI / `quality` / `python scripts/ci/docs.py`; example modules selected in `suites.json` | Same | Required | Maintained shipped guides and authored executable examples only; live provider examples are excluded |
| Reporting and gate failures | CI / `quality` / `pytest tests/test_ci_reporting.py`; readiness / `gate.py` | Same | Required | Passing, failed, cancelled, missing, malformed, all-skipped and intentional assurance N/A samples |
| Distribution completeness and installed HTTP startup | CI / `quality` / `package_smoke.py` | Same | Required | Fresh sdist/wheel, exact package file inventory including reviewed scoring PDFs, hash-locked new environment, imports/routes outside source tree; no SQL owner or acquisition |
| Persistent boundaries and migrations | CI / `postgres`, reusable storage / `postgres.py` | Same / PostgreSQL 16 | Required | Disposable cluster, selected migration/transaction/read tests and teardown; never ordinary state |
| Browser journey, focus, enlargement and finite Stop | CI / `browser` / `pytest -q browser_tests` | Same / locked Chromium | Required | Intercepted boards and authored loopback SC04/SC05; automated evidence does not establish owner or installed-device acceptance |
| Representative UI performance and resource budgets | Browser SC04/SC05 harnesses and retained JSON | Same | Required existing SC04/SC05 budgets; measurements environment-specific | Formal SC06 500-event/30-ticket/burst stress qualification is deferred under the October 16 owner priority decision. Its executable campaign was removed at the owner’s request on October 17; historical failures remain failures |
| Secrets | CI / `quality` / `secret_scan.py` | Same | Required | Redacted current publishable-tree scan; exact public identifiers/digests have dated, path-scoped exceptions and credential negative controls. History is outside scan scope |
| Dependency vulnerabilities and inventory | CI / `quality` / locked `pip_audit`; package metrics | Same; advisory data refreshed per run | Required audit; informational license inventory | Findings and scanner outage fail. Unknown licenses stay null; no invented legal approval |
| Broader runtime compatibility | Scheduled assurance / `compatibility` | Monday 07:23 UTC or typed manual / macOS 15, Python 3.11 and 3.14 | Scheduled/requested required | Portable suite and fresh package; each matrix result remains visible |
| Service/security refresh | Scheduled assurance / `postgres`, `security` | Weekly or selected manual scope / Ubuntu | Scheduled/requested required | Reuses storage policy and refreshes locked dependency advisories |
| Reliability, queue, elapsed and resource telemetry | Scheduled assurance / `health` / `health.py` | Weekly/manual; Actions read API | Advisory | At most 30 completed CI runs from 30 days; optional API failures retain other samples |
| Scoped assurance outcomes | Scheduled assurance / `summary` / `assurance_report.py` | Weekly/manual | Requested checks required; other scopes N/A | Only intentionally unrequested jobs may skip. Health availability cannot overwrite correctness outcomes |
| Language static security analysis | Existing GitHub CodeQL default setup | GitHub-managed | Independent; not asserted by readiness | Read-only API inspection confirmed Actions, JavaScript/TypeScript and Python configured; no activation performed |
| Windows, native device, other browsers and expanded architecture matrices | No workflow | N/A | Not claimed | No Windows product support or native-device executor is established by this repository. Local Apple silicon evidence and hosted matrix evidence remain separate |
| Container/IaC scanning; signing/deploy/publish | No workflow | N/A | Outside ordinary PR CI | No maintained container/IaC deployment target was found; release/environment authorization is separate |

PR and main runs have distinct value: the PR candidate can be a generated merge
commit; the main push checks integrated state. `merge_group` handles a future queued
candidate, but no active merge queue was observed. There are no path filters that
can strand readiness. No privileged `pull_request_target`, `workflow_run`, secret
inheritance, persistent self-hosted runner or PR comment publisher is introduced.
Fork checks receive no application credentials. External Actions use full SHAs;
checkout credential persistence is disabled. Cache correctness follows hash-locked
installs and does not rely on warm contents.

The weekly schedule is Monday at 07:23 UTC on the default branch. GitHub can delay
or omit scheduled execution; inspect the run date and SHA before relying on it.
Manual scopes are validated choice inputs, default to `all`, and require normal
repository workflow-dispatch permission. A selected scope's cancelled/failed/missing
job fails its summary; deliberately unselected scopes show N/A. An old scheduled
pass never qualifies a newer PR. No tag, environment or release publishing is added.

The ordinary browser job has a 15-minute outer timeout for tooling setup and
SC04/SC05 journeys. The required PostgreSQL job retains the small SC06 financial
roundtrip, ready-ticket, original-clock expiry and missing-depth checks. The
removed stress campaign has no manual workflow, schedule or launcher flag.
Historical stress reports are evidence of their failed runs, not current CI gates.
A cancelled runner may prevent final uploads; cancellation still fails readiness.

## Metrics and integration policy

Each applicable report retains tested SHA, event/run identity and environment.
Local dirty-tree evidence is not hosted evidence for that SHA. JUnit durations
must be finite and nonnegative. Required missing or malformed reports fail rather
than becoming zero findings. Package metrics retain wheel bytes, elapsed
seconds and installed dependency/license inventory. Fresh local report directories
preserve prior diagnostics; use `package_smoke.py --report-dir EMPTY_DIRECTORY`.

Coverage line/branch measurements describe the executed scope, with archival
exclusions in `python-policy.json`. Changed-line coverage and comparable deltas
remain unavailable without an identified matching baseline. No arbitrary universal
coverage threshold is introduced. Performance deltas require the same workload,
runtime, browser, machine class and measurement boundary; otherwise report only
the new measurement. The health report's baseline is null; its rolling sample may
contain different historical suite scopes and is reliability telemetry, not a
product-performance comparison.

Health first-attempt rates exclude cancellations and explicitly retrieve attempt 1
for rerun runs. Missing first attempts remain unavailable. Recovery never implies
flakiness. Elapsed samples use run start to final completed job; nearest-rank p95
requires at least 20 samples. Queue time is creation to first job start. Summed job
seconds are observed runner minutes, not elapsed time or billing. Incomplete job
samples and individual API outages remain explicit. Failed-step categories can
include downstream report/gate failures and must not be treated as independent root
causes. Critical-path dependency reconstruction, account quota and suspected flakes
remain unavailable. Artifact metadata is a bounded sample, not total billed storage.

Native summaries and artifacts are the reporting surface; no new reporting service,
account, token, paid tier or notification integration is activated. Official
eligibility was checked on 2026-10-17:

| Option / status | Eligibility and limits | Data, permission, retention and failure behavior |
| --- | --- | --- |
| GitHub summaries/artifacts/read API: existing, configured | Repository observed public. Standard hosted runners are free for public repositories; larger runners are charged. Private GitHub Free includes 2,000 minutes/month, 500 MB artifact storage; cache allowance is 10 GB/repository. Actual owner billing plan/quota was not read | Existing GitHub account and ephemeral workflow token; contents read, Actions read only for telemetry. Source executes on GitHub; synthetic/redacted reports upload to GitHub for 14 days. No separate LOC/user/upload service limit applies to these CLI reports; GitHub platform/storage limits apply. Required upload/report failures remain visible; telemetry outage is advisory. Usage without payment can block at quota; paid budgets are owner-controlled |
| actionlint CLI: existing, locally executed | Open-source local executable, public/private eligible; no account, token, LOC, seat or upload quota | Workflow source stays in the job; no external analysis upload. Version/checksum-pinned installer. Missing tool or failed validation fails quality |
| Gitleaks CLI: existing, locally executed | Open-source CLI; no account, seat, LOC or scan-upload quota. This does not adopt the separately licensed wrapper Action | Current publishable-tree files stay in the job; redacted JSON retained for 14 days. Negative controls protect the narrow exceptions. Findings or tool failure fail quality |
| pip-audit/coverage: existing, locally executed | No new SaaS subscription, upload or user quota | Dependency names/versions go to the vulnerability advisory service; source/coverage has no external dashboard upload. Advisory-service outage fails the required audit; coverage/report outage fails its applicable gate |
| CodeQL: existing default setup observed | Repository is public; API confirmed configured languages and weekly schedule | Existing GitHub integration, no new setup or permissions applied; results remain separate from this readiness gate. Its latest result does not qualify dirty local source |

Sources: [GitHub billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions),
[job summaries](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#adding-a-job-summary),
[actionlint](https://github.com/rhysd/actionlint),
[Gitleaks CLI and Action distinction](https://github.com/gitleaks/gitleaks).
Codecov, SonarQube Cloud, OSV-Scanner and Lighthouse CI are not recommended for
activation in this pass: native coverage, existing CodeQL, pip-audit and workload
browser measurements already cover the immediate needs. Their account eligibility
and commercial limits were not evaluated, and no claim of free private access is
made. Dedicated changed-code coverage is a future need only after a trustworthy
baseline exists. The package license inventory is informational; the missing
project license decision and null dependency licenses remain owner review items.

Read-only repository inspection found `main` unprotected and no rulesets. The
workflow implements readiness but cannot enforce merging by itself. Recommended
owner setting: require `CI readiness` on `main` after resolving current failures;
choose freshness/up-to-date rules with the owner's merge policy. This is a
recommendation, not an applied repository setting.

### Browser harness freshness and scheduling

The SC06 authored workload uses its own original source clocks. Cloning a retained
quote into a different authored market must drop the old market's confirmation;
it must not reseal or reuse that provider proof. Production confirmation validation
is unchanged, and a regression verifies that a transplanted proof is rejected.

The former 500-event, 30-sample timing and burst campaign was removed from active
source at the owner's request. Its dedicated browser harness, diagnostic SQL/HTTP
server, profiler and harness-only tests are removed together. Product summary,
financial, stale-input, missing-depth and ordinary browser checks remain required.
This implements the existing October 16 deferral; it does not claim the stress
campaign passed or establish a new performance baseline. Prior failure reports
remain retained under `test-results/browser-repair-20261017/`.

### Offline fixture and current-contract repairs

Native metadata enrichment preserves a separately reviewed occurrence ID rather
than replacing it with a different native game identifier; the occurrence owner
still revalidates its seal. Synthetic financial workloads supply explicit original
scoring terms. They do not inherit source qualification or bypass missing-scope
refusals. Public retail quantity evidence cannot qualify a payout whose exact
scoring scope remains unknown.

Financial/observation tests resolve the board's existing local price references
before inspecting complete rows, and endpoint tests exercise the current bounded
read lane. Unsupported-market tests use actually unsupported markets/leagues;
explicit linked schedule evidence is distinguished from an absent schedule.
A valid content-bound book confirmation remains independent currentness evidence.
The 80-observation board retains its 512 KiB cap; the current-peer frame omits an
unused repeated explanation while the displayed gross-comparison tooltip retains it.

The offline runner gives JavaScript fixture subprocesses the same Python
interpreter that owns the locked CI environment. Client tests must not depend on a
developer's `.venv` being present in a clean hosted checkout. Required suite
registration and failure handling remain unchanged.
