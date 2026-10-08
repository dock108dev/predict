# CI workflows

CI checks source, portable offline behavior, dependencies and package assets. It does not access live providers or establish market freshness.

## Events and required checks

| Area / product risk | Exact workflow / job / command | Event / platform | Policy | Reason / evidence |
|---|---|---|---|---|
| Current source syntax and undefined names | CI / Source, security and package / `python -m ruff check app tests scripts/ci` | PR, main push, manual / Ubuntu 24.04, Python 3.14 | Required policy | Parser, invalid statements and undefined names; historical code is not reformatted |
| CI support formatting | Same / `python -m ruff format --check scripts/ci tests/test_ci_reporting.py` | Same | Required policy | New automation code has a bounded formatting contract |
| Actions syntax, expressions, inputs, dependencies | Same / `.local/ci-tools/actionlint -shellcheck=''` | Same | Required policy | Pinned actionlint 1.7.12; shell syntax separately checked. ShellCheck lint is not claimed |
| Python compilation, all dashboard JS syntax | CI / Offline checks / `sh scripts/check-ci` | Same; Node 22 | Required policy | Recurses into current, preview and retained shipped browser assets |
| Quote identity, conditional math, clocks, quotas, failure/Stop/recovery, persistence, routes | Same / `scripts/ci/suites.json` exact pytest groups | Same | Required policy | Existing portable suites plus adapter/model/math/transport/current-revision boundaries. Fresh process per group preserves peak-RSS gates |
| Browser behavior, escaping, saved state and keyboard focus | Same / `node tests/test_*.cjs` excluding explicit entries in `scripts/ci/browser-suites.json` | Same | Required policy | Dependency-free simulated DOM checks; real browser/device accessibility and usability testing remain separate |
| JUnit/report failure and missing-data semantics | Quality job / `python -m pytest -q tests/test_ci_reporting.py` | Same | Required policy | Missing/malformed/zero/all-skipped reports, scan outages, command exits and escaping |
| Known dependency vulnerabilities | Quality job / `python -m pip_audit -r requirements-ci.txt --require-hashes --disable-pip --progress-spinner off --timeout 20 -f json` | Same | Required policy | Includes runtime/stream/build/test tools; no vulnerability suppression. Outage, missing report or skipped dependency cannot become zero findings |
| Production package/assets/import/entry point | Quality job / `python scripts/ci/package_smoke.py` | Same | Required policy | Build sdist/wheel, install hashes in fresh env, install wheel without resolving, import outside checkout, assets and `--help`. Does not launch ordinary providers |
| Coverage and wheel size | Offline JSON/XML; package `metrics.json` | Same | Advisory metrics | Line/branch evidence and bytes; no arbitrary coverage/size budget or unequal baseline comparison |
| Maintained owner platform and minimum runtime | Scheduled assurance / macOS Python 3.11 and 3.14 / full offline contract + package | Monday 07:23 UTC, manual / macOS 15 | Scheduled | Declared minimum 3.11, current 3.14. Full intermediate-minor and Windows/Linux-arm matrix omitted: no support evidence justifies the runner cost; Linux 3.14 remains PR platform |
| Historical SQL transactions, migrations, replay | Scheduled assurance / Historical PostgreSQL storage / `python scripts/ci/postgres.py` | Weekly/manual / Ubuntu, runner PostgreSQL 16 | Scheduled | Current ordinary app needs no DB. Existing 43 integration cases create/drop disposable DBs in a separate temporary cluster, local-only sockets and bounded cleanup. Local PostgreSQL 14 evidence is a separate environment |
| CI reliability and speed | Scheduled assurance / CI health sample / `python scripts/ci/health.py` | Weekly/manual / Ubuntu | Advisory | Read-only Actions API: latest 30 repository runs, 30-day cutoff, no pagination, event-separated rates, reruns, elapsed durations and observed job minutes |
| Language static analysis | Existing GitHub-managed CodeQL Python/JS/Actions | Existing configured events | Existing separate checks | Managed outside these workflow files; check repository settings for its configured events |
| Generated registry/schema drift | Existing normalization, matching, contract, frozen-oracle suites | PR | Required behavior coverage | No separate code generator build step declared; immutable inputs must not be regenerated to pass |
| Broad type checking / universal style formatting | Not configured | — | Omitted | No existing typing/style contract for mixed historical Python; compilation, critical Ruff rules and behavioral checks apply. Adopting whole-codebase typing is separate scoped work |
| Historical acquisitions, sealed packages and archive oracles | Existing opt-in `tests/test_*` outside suite manifest; four explicit browser exclusions | Explicit/local | Deferred | Not silently discovered: these can require ignored captures, approvals or prepared packages. Preserve exact archival expectations. CI does not invoke evidence writers or acquisition rehearsals |
| Browser lab performance / end-to-end accessibility | N/A for deterministic merge gate | — | Omitted | No npm web build or existing browser-test harness; current provider loop cannot be used as CI input. Simulated DOM checks do not prove browser paint, WCAG or production performance. Controlled synthetic browser harness is a bounded follow-up |
| Container/IaC/release/signing/deployment | N/A | — | Omitted | No product container/IaC or authorized release workflow in this repository; PRs never publish |

“Required policy” is repository code policy, **not active branch protection**.
Workflow files do not configure GitHub branch protection. When enabling required checks, use the workflow job names: require `Offline checks` and `Source, security
and package`, plus the established CodeQL checks after checking their current exact
names. Do not require scheduled jobs. These workflows do not configure a `merge_group` trigger. If one is enabled, add both merge jobs on
`merge_group` before requiring the queue. No path filters can strand checks.

## Installation and local reproduction

Python dependencies and tools are universally locked with hashes for Python 3.11+.
Tool versions are pinned in the lock.
Setuptools/wheel are explicitly installed before the no-isolation editable build.
No tool depends on a warm cache. Python/Node minor lines and runner OS images
receive supported patch updates; they are not exact runner-image snapshots.
Binary validators have version-specific SHA256 pins for Linux x86_64/macOS arm64.
Other architectures require a reviewed checksum before installation.

```sh
python3.14 -m venv /tmp/predict-ci-env
/tmp/predict-ci-env/bin/python -m pip install --require-hashes -r requirements-ci.txt
/tmp/predict-ci-env/bin/python -m pip install --no-deps --no-build-isolation -e '.[stream]'
/tmp/predict-ci-env/bin/python -m pip check
PATH="/tmp/predict-ci-env/bin:$PATH" sh scripts/check-ci
/tmp/predict-ci-env/bin/python scripts/ci/install_tools.py
/tmp/predict-ci-env/bin/python -m ruff check app tests scripts/ci
/tmp/predict-ci-env/bin/python -m ruff format --check scripts/ci tests/test_ci_reporting.py
.local/ci-tools/actionlint -shellcheck=''
/tmp/predict-ci-env/bin/python scripts/ci/package_smoke.py
```

The test output directory must be empty before a run. Use `--output` to select a
fresh directory; stale results never qualify a run. The Python manifest lists exact
suite scope. New tests belong in that reviewed manifest; broad discovery could
execute archive/acquisition workflows. Browser discovery runs all `test_*.cjs`
except explicitly documented archive oracles. Tests only write synthetic temporary
state; saved fixtures remain inputs. Use `scripts/ci/export.py EMPTY_DESTINATION`
for a clean candidate copy: tracked and nonignored files, no ignored local catalog,
credentials or saved acquisitions. Repository-internal evidence symlinks are
relocated inside the export; escaping links fail. Never upload that source copy.

Regenerate the lock after a requirements change and review versions/hashes:

```sh
uv pip compile pyproject.toml requirements-ci.in --extra stream --universal --python-version 3.11 --generate-hashes -o requirements-ci.txt
```

Weekly Dependabot covers pip and SHA-pinned Actions, including the composite action.
The setup composite repeats only locked Python/Node installation. Independent quality
and offline jobs run in parallel; no unnecessary reusable workflow or cross-workflow
privilege chain. Superseded PR runs cancel within their event/PR concurrency group;
main pushes and manually requested/scheduled work are not cancelled by PR activity.

## Reports, measurement and trust

Native summaries contain candidate/ref/event, environment, per-check outcomes,
counts and durations; `metrics.json` retains nulls for unavailable baselines.
JUnit and coverage JSON/XML, dependency audit JSON, package bytes and relevant logs
are in unique run/attempt artifacts with **14-day retention**. No source archives,
private credentials or owner captures are uploaded. Tools never execute report
contents. Summary values are escaped; test logs remain diagnostics. No PR comments
or notifications are posted.

Offline groups continue after independent failures, with 15-minute process limits
and a 35-minute job cap. Reports are updated after each completed group and include
NOT RUN entries for interrupted work. Final upload runs after failure; absent
reports are errors. Quality reports inspect step outcomes and expected report shape,
so successful commands with missing data still fail. A cancelled job cannot be
claimed PASS. GitHub job/artifact names remain stable except unique artifact suffixes.

Coverage is a first measurement of this exact suite/runtime/lock, not a universal
threshold. Changed-line coverage and coverage deltas are unavailable without a
comparable primary-branch baseline. Wheel bytes have no blocking budget. Synthetic
suite times include instrumentation and cannot be compared to older unittest jobs.
Metrics report dependency finding counts; severity is unavailable where the tool's
API does not supply it, rather than inferred from advisories. No automatic retries,
rerun-based flake claims or softened thresholds.

CI-health reports select at most 30 recent repository runs and retain only relevant
CI run identities. First-attempt rate excludes cancellation and reruns whose first
outcome is unavailable. Elapsed is workflow start through last completed job;
median uses observed samples, nearest-rank p95 requires at least 20. Queue time,
critical-path decomposition, cache quota and account billing remain unavailable.
Observed job minutes are not billed minutes. Optional health failures cannot block
independent correctness jobs. No baseline crawler or external metrics upload exists.

Weekly assurance runs on the default branch at Monday 07:23 UTC (03:23 EDT / 02:23
EST), subject to GitHub scheduling delay and default-branch/inactivity rules. Seven
days is the expected evidence interval; older evidence is stale, and scheduled
results never qualify a newer PR. Manual `scope` is a typed choice: `all`,
`compatibility` or `postgres`; health reporting also runs. It grants no provider,
account, release or production authority.

## Reports and external services

Jobs use read-only repository permissions, do not persist checkout credentials,
and do not expose provider secrets to PRs. Reports remain in GitHub Actions or
ignored local output. Hosted retention and billing depend on repository settings.

Secret scanning is handled by the repository’s existing GitHub secret scanning.
CI does not install or run a separate secret scanner. Actionlint runs as a pinned
local binary. Pip-audit queries the PyPI
advisory service for dependency names/versions; it does not upload source. Outages
and missing reports remain failures, not zero findings. No external coverage
upload service or hosted application deployment is configured.
