# Development

Work from the repository root with the Python 3.11+ environment described in the
[README](../README.md). The `stream` extra is needed for the current dashboard's
adapter imports, even when exercising saved data. The development workflow is an
editable source checkout; a standalone wheel is not a self-contained dashboard
because saved evidence and assets are loaded from repository paths.
Use Python 3.14 for current local checks, matching the single CI runtime.

## Source layout

| Location | Responsibility |
| --- | --- |
| `app/dashboard/multi_game_server.py` | Current HTTP routes |
| `app/dashboard/coverage_owner.py` | Current owner and finalization |
| `app/dashboard/session_projection.py`, `product_view.py` | Durable projection and product calculations |
| `app/dashboard/query_policy.py`, `local_security.py` | Selection/assumption policy and browser/body boundaries |
| `app/dashboard/multi_game.py` | Retained projection, calculation/ranking and inherited owner helpers |
| `app/dashboard/opportunity_board.py` | Compatibility factory and CLI entry point |
| `app/dashboard/opportunity_static/` | Current list and game-detail browser assets |
| `app/collection/` | Bounded discovery, transport, file journals and recovery |
| `app/adapters/`, `app/models/`, `app/normalization/` | Venue conversion and shared identity |
| `app/opportunities/`, `app/fees/`, `app/reference/` | Conditional math, fees and research |
| `app/storage/` | Separate historical PostgreSQL persistence/replay |
| `tests/` | Unit, saved-fixture and local mock checks |
| `integration_tests/` | Separately invoked PostgreSQL checks |
| `evidence/` | Retained observations and verification artifacts; preserve original inputs |
| `.local/` | Ignored local process state and logs |

See [architecture](architecture.md) for data flow and persisted contracts, and
[configuration](configuration.md) for runtime settings and service requirements.
Use [SSOT](ssot.md) for module ownership and retained compatibility decisions.

Entry-point and combined-feed guards run offline:

```sh
.venv/bin/python -m unittest tests.test_ssot_policy tests.test_opportunity_feed tests.test_calculation_reuse tests.test_opportunity_board -q
sh -n scripts/dashboard
```

The retired-launcher checks execute a copied script with disposable stubs; the
entry-point guard mocks server startup. They do not launch a server or database.
The current factory selects CoverageOwner; older MultiOwner helpers remain shared.
Use `query_policy` for selection/assumption changes and `local_security` for body
limits. Do not copy these policies into new routes or direct product helpers.

## Focused checks

For changes to the current owner, routes or saved projection:

```sh
.venv/bin/python -m unittest tests.test_coverage_failure_handling -q
.venv/bin/python -m unittest tests.test_abend_handling tests.test_novig -q
.venv/bin/python -m unittest tests.test_security_hardening tests.test_dashboard_security -q
.venv/bin/python -m unittest \
  tests.test_multi_game tests.test_opportunity_board tests.test_personal_beta \
  tests.test_failure_handling \
  tests.test_ssot_policy tests.test_dashboard_security -q
.venv/bin/python -m compileall -q app/dashboard app/collection
```

These tests read saved fixtures and use disposable output or local mocks. They do
not authorize provider collection. For calculation changes, also use the relevant
math reconciliation, fee or research tests; do not rewrite their retained baselines
to make a test pass.

For saved-reader or resolution changes, also run:

```sh
.venv/bin/python -m unittest tests.test_session_projection tests.test_product_integration tests.test_nfl_resolution -q
```

For current browser edits, with Node.js available:

```sh
node --check app/dashboard/opportunity_static/dashboard.js
node tests/test_dashboard_failures.cjs
node tests/test_board_security.cjs
node tests/test_concise_dashboard.cjs
node tests/test_source_details.cjs
node tests/test_multi_page_ui.cjs
```

The source-details check covers disclosure identity and keyboard focus across
replacement markup, changed links, removed/hidden controls and deliberate focus
changes. For polling/render changes, also inspect a real browser at desktop and
narrow widths: keep a row summary or link focused during refresh, reorder/remove
rows, switch saved scans, and move focus while a request is pending. Follow the
[local UI requirements](ui-design-requirements.md); historical review screenshots
are not evidence for current source.

Use `git diff --check` after edits. There is no configured formatter/linter.
Prefer small readable edits consistent with nearby code; avoid repository-wide
formatting churn. Inspect a test or verifier's side
effects before running it. Full test discovery, database integration, evidence
writers, live verifiers and browser walkthroughs are not routine cleanup checks.

## Pull-request CI

[CI](../.github/workflows/ci.yml) runs the stable **Offline checks** job on every
pull request and push to `main`, and supports manual dispatch. It uses Ubuntu
24.04, Python 3.14 and Node 22, with a 20-minute job limit.
This is a focused baseline,
not certification of every Python/platform combination. Node runs the existing
dependency-free browser regression scripts; no npm install is needed.

To reproduce it in a disposable environment from the repository root:

```sh
python3.14 -m venv /tmp/predict-ci-venv
/tmp/predict-ci-venv/bin/python -m pip install --require-hashes -r requirements-ci.txt
/tmp/predict-ci-venv/bin/python -m pip install --no-deps --no-build-isolation -e '.[stream]'
/tmp/predict-ci-venv/bin/python -m pip check
PATH="/tmp/predict-ci-venv/bin:$PATH" sh scripts/check-ci
```

[The check script](../scripts/check-ci) compiles Python, checks current browser
JavaScript syntax and runs selected dashboard, failure-handling and independent
saved-input math/research regressions. Local HTTP mocks and temporary output are
used; retained evidence is read-only. No credentials, provider requests,
PostgreSQL service, live verifier, packaging or release is part of this job.
Failures remain in the Actions step logs; no owner captures are uploaded.
The retained-regression group prints individual test names so a timeout identifies
the test in progress.
For socket shutdown changes, use `tests.test_failure_handling`,
`tests.test_kalshi`, `tests.test_polymarket_us_stream` and
`tests.test_two_source_qualification`; these cover cancellation during close and
rejected-frame finalization. Keep both success and genuine cleanup-failure cases.

Tracked retained fixtures are immutable inputs read by offline tests and saved-review code. Ignore rules do not untrack existing files. Keep required retained fixtures tracked so a clean checkout can run those checks. Preserve their original bytes and historical failure/consumption states. Approvals and unrelated acquisitions remain ignored. The consumed-attempt regression resolves its retained marker within this checkout without following an owner’s absolute output path. To check fixture portability, export tracked and nonignored files to a temporary checkout and run the affected retained-review tests there; a pass in the full local archive is insufficient.

`evidence/source-bindings-20260929/proposal.json` is a required acquisition-policy
fixture with a pinned SHA256. Its exact ignore exception makes it a checkout
input; sibling approvals, outputs and acquisition records remain local. Including
the specification does not authorize any provider request.

The ignored `app/reviews/native` catalog is an optional local archive. Its absence
contributes no historical paths or accepted native judgments, and does not prevent
ordinary saved-scan reads. Invalid existing catalogs, missing indexed records and
unsafe history paths still fail rather than granting review qualification. The
failure-handling and catalog-portability tests exercise this clean-checkout case.
Frozen native-review oracle tests select `native_interpretation="original"`
explicitly. The current route rejects a legacy game absent from its selected
interpretation with HTTP 422; it does not promote those frozen calculations into
current qualified economics.

[requirements-ci.txt](../requirements-ci.txt) locks runtime, stream and build
dependencies with hashes and platform markers. CI caches only pip downloads and
installs dependencies on every run; the editable project install cannot resolve
additional packages. After changing dependency requirements, regenerate the lock
with [uv](https://docs.astral.sh/uv/pip/compile/) and review its diff:

```sh
uv pip compile pyproject.toml requirements-ci.in --extra stream --universal --python-version 3.11 --generate-hashes -o requirements-ci.txt
```

The universal lock retains markers for the declared minimum Python version;
ordinary CI and current local validation use Python 3.14 only.

Use `--upgrade` for an intentional full dependency refresh. Weekly Dependabot
updates cover pip and SHA-pinned GitHub Actions. Existing GitHub-managed CodeQL
checks (`Analyze (python)`, `Analyze (javascript-typescript)` and
`Analyze (actions)`) remain separate; do not add a duplicate CodeQL workflow.

## Maintenance boundaries

Preserve retained evidence, frozen candidates and consumed-attempt markers.
Follow [module ownership](ssot.md#conflicts-removed-and-retained-paths) before
retiring historical entry points; some helpers still have current callers.
See [failure handling](error-handling.md#limits-and-separate-follow-up) for
cleanup and recovery behavior. Record validation results with the change rather
than appending run histories to this guide.

## Tracked inputs and local output

Ignore rules exclude new evidence, process state, caches, browser reports and build
output; already tracked retained fixtures remain checkout inputs. An ignored file
can still be tracked. Inspect `git ls-files -ci --exclude-standard` before deciding
whether any artifact can leave the index. Do not remove that entire list: saved
packages, replay fixtures, frozen sources and authored acquisition tools may still
have supported callers.

Generated test/browser transcripts are local-only where removed from tracking.
The `.txt` test transcripts in `evidence/b3-continuation-20260921` and
`evidence/b3-native-integration-20260920` are now local-only. Their historical
reports retain original references; those transcripts are not fresh-checkout
requirements. Saved journals, structured replay inputs, reports and authored
package tools remain tracked. Root `build/` and `dist/` are ignored package output.
Historical reports may refer to that retained local evidence; a fresh checkout
includes only the tracked fixtures needed by supported offline tests. Preserve
required saved inputs, frozen sources and authored tools when cleaning artifacts.

For artifact removal, verify local hashes before and after index changes, check
that paths are ignored and no longer tracked, and test affected code in a temporary
export of tracked plus nonignored working files. This includes unfinished source
changes while excluding local-only evidence. Keep that export distinct from a
released or qualified candidate. Index removal changes the proposed current tree;
it neither deletes local files nor purges Git history.

## Naming

Name files, tests and documents for their feature or behavior, such as
`test_nba_first_half.py` or `reference-integration.md`. Use descriptive headings
and link labels. Keep historical identifiers only where needed to locate original
evidence or read an existing saved format. Keep slice/task chronology in the
[implementation history](implementation-history.md), dated handoffs and planning records,
not in module comments or current setup instructions. Retained authorization labels,
reviewer provenance and hash-bearing fixture text are compatibility/evidence inputs;
rewriting them requires a separate migration or regenerated-evidence decision.

The optional retained-coverage generator `scripts/write_v1_beta_coverage_status.py`
reads a specific historical archive, named in its `build_status` function. Those
local-only inputs are not installation requirements or assumed present in a fresh
clone. Use a disposable `--output` when verifying it; it does not enable collection
or change workflow acceptance. Generated guidance points to repository-local
configuration.

The optional `scripts/us_metadata_package/build.py` prepares inert, sealed
diagnostic packages and also requires its retained baseline inputs. Its
`--authority-file` argument identifies an explicit provenance file; non-offline
preparation fails before writing when it is absent. Offline rehearsals use
synthetic provenance. Preparation does not activate a package or grant permission
to execute it; existing seals, approval and consumed-attempt checks still apply.

## Opportunity-card preview and focused checks

The isolated ordinary-app simulation uses synthetic local endpoints. Run `.venv/bin/python -m unittest tests.test_opportunity_feed -v` for percentage grouping, no-model comparisons, original-input math, frozen reopening and HTTP Stop. Run lifecycle modules in separate processes to keep process-wide peak RSS from earlier tests out of later bounded fixtures. The simulation launcher is `.venv/bin/python -m tests.opportunity_card_preview .local/opportunity-card-preview`; its optional local `pause-books` file pauses fixture updates for freshness checks, and must be removed after the check. No provider endpoints or credentials are used.
