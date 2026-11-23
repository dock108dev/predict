# Private beta CI and deployment

Predict has one owner and one active working copy on `main`. Normal CI protects
data, calculations and the personal server. It does not qualify a public launch,
multiple users, onboarding, marketing or an enterprise release process.

## Required checks

[CI](../.github/workflows/ci.yml) runs on pushes to `main` and manual dispatch.
One runner performs focused checks, cached image verification and deployment.
The normal runner budget is two minutes; GitHub queue time is recorded separately.
A budget timeout is a failure, never evidence of a completed deployment.

The focused contracts cover exact reference/EV/cashflow arithmetic, collection
budget and Stop guards, checkpoint timing and persistence, lossless export, and
the deployment paths affected by the change. Storage/migration changes add a
small disposable PostgreSQL check. Private proxy smoke verifies owner access and
credential stripping; image/Compose smoke uses disposable state with acquisition
disabled. Current-main identity is checked before build and before SSH handoff.

The [selector](../scripts/ci/fast_checks.py) records changed paths, selected checks,
actual durations and limits in `test-results/fast` and the run summary. Source
lint, workflow syntax and secret checks remain inexpensive baseline checks.
Missing or failed selected checks stop the release. Unavailable data and
unsupported calculations remain explicit rather than being treated as zero.

The fast path does not run public-user journeys, broad browser matrices,
legacy-removal assertions, the historical test-catalog gate or every SQL shard.
It does not assert complete regression coverage, calibrated probabilities, live
fills or profitable trading. Do not add a test solely to prove an old feature or
workflow was removed.

## Personal release

Only current `main` deploys to [the personal workspace](https://predict.dock108.dev/).
The same job reuses content-identified role images and BuildKit layers, exercises
the selected images, publishes pinned digests and invokes the restricted server
release. Provider credentials never enter CI. GitHub's temporary token supplies
registry access; the existing `hetzner` environment supplies restricted SSH access.

The host validates managed configuration and protected storage bindings, rolls
affected roles, checks all configured service health, and installs the matching
proxy/Compose/release files. Current and previous images remain available for
rollback. Obsolete-image cleanup runs only after a healthy release and preserves
both image sets and all container images. [Server operations](hetzner.md)

A superseded revision is skipped instead of replacing newer code. Manual rescue
runs use the same focused checks and release behavior. No second manual deployment
workflow or separate full-suite success is required for ordinary private use.

## Optional extended checks

[Full validation](../.github/workflows/full-validation.yml) preserves broader
regression, browser, package/security and four-shard PostgreSQL checks for an
explicit investigation. It is manual-only and outside the two-minute normal
release path. The older focused [assurance workflow](../.github/workflows/assurance.yml)
is also manual-only. Neither adds a hidden nightly or weekly full-test gate.
Dependabot and GitHub dependency alerts remain separate.

The pre-simplification tests and workflow sources were preserved at commit
`02cd1286e5d1c527b4fd854f778f7bbe0f7399e5` and in a verified private source archive
on the owner's Mac. Those archived files are not normal CI inputs. Existing
mathematical and data-integrity fixtures remain reusable without reviving old
product acceptance requirements.

## Local reproduction

Use the existing [development environment](development.md#install-tools).

```sh
.venv/bin/python scripts/ci/fast_checks.py --plan
.venv/bin/python scripts/ci/fast_checks.py
.venv/bin/python scripts/ci/fast_checks.py --paths app/research/experiment.py
```

The plan prints the precise selected commands. Local execution uses disposable
fixtures; it does not acquire provider data or place trades. Set `PG_CONFIG` to
PostgreSQL 16's `pg_config` for selected SQL checks.

For a specific changed owner, running its narrow regression directly remains
appropriate. Full local subsystem routing and explicit extended assurance remain
available when a named investigation needs them; they are not the routine release
checkpoint. Keep unchanged historical tests out of a new repair's completion gate.

## Evidence and timing

The run summary distinguishes focused validation, image cache/build, proxy/Compose
smoke, publication and installed deployment. A green focused result describes its
selected contracts. A full-validation result describes the separately executed
suite. Keep both distinct from actual source acquisition, research coverage,
probability quality and trading results.

Measure the complete job, including setup and release, against the two-minute
budget. Cold downloads, runner queue and exceptional migration work must remain
visible. Preserve backups and data guards while optimizing measured bottlenecks.
