# Development

Use a source checkout and Python 3.11+; Python 3.14 and Node 22 match the primary
CI workflow. Run commands from the repository root. Current operation requires
macOS Keychain access, while portable offline tests also run on Linux.

## Install tools

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-ci.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation -e '.[stream]'
.venv/bin/python -m pip check
```

The hashed lock includes runtime, stream, test and build tools. An ordinary app
installation can instead use the smaller editable install in the README.

## Focused checks

Select the tests affected by a change rather than discovering every historical
acquisition harness:

```sh
.venv/bin/python -m compileall -q app/dashboard app/collection
.venv/bin/python -m pytest -q tests/test_current_ssot.py tests/test_current_contract.py tests/test_current_service.py
.venv/bin/python -m ruff check app tests scripts/ci
node tests/test_current_client.cjs
```

For browser changes, syntax-check the edited module and run its matching client
regressions. For retained saved-reader changes, use `test_session_projection.py`
and `test_product_integration.py`; for calculation changes, use the matching math,
fee or settlement tests. Tests should use disposable state and no provider secrets.

`sh scripts/check-ci` runs the portable suite manifest in fresh processes and
writes ignored reports under `test-results/ci`. See [CI](CI.md) for workflow scope
and separate PostgreSQL assurance. Additional historical tests can require
local acquisition files or expired specifications; they are not installation
checks. Do not relax production scope/window checks to make those fixtures pass.

## Synthetic preview

```sh
.venv/bin/python -m tests.current_integration_server --synthetic-test --port 8797
```

Open `http://127.0.0.1:8797/`, `/arbs` or `/admin`. All displayed prices are
synthetic. The test provider uses production interfaces without credentials or
provider access. Its `/__test/commit` controls are exclusive to this test server.
Stop it with Ctrl-C. The ordinary app never falls back to this provider.

For EV, modeled/net Details and Coverage, use the dedicated comparison harness:

```sh
.venv/bin/python -m tests.comparison_preview
```

Follow its printed loopback address. These servers use explicit test providers
through current interfaces. Fictional sample generation lives in
`tests/current_sample.py`.

## Source layout

| Location | Responsibility |
| --- | --- |
| `app/collection/current_*` | Current configuration, source workers, schedule, quota and lifecycle |
| `app/dashboard/current_*` | Latest state, leases, serialization and calculations |
| `app/dashboard/multi_game_server.py` | Shared route registration |
| `app/dashboard/opportunity_static/` | Packaged browser assets |
| `app/collection/continuous.py`, `continuous_streams.py` | Explicit finite-session discovery/ownership and stream groups |
| `app/dashboard/session_*`, `coverage_owner.py` | Retained journals, saved projection and finite-session control |
| `app/adapters/`, `models/`, `normalization/` | Venue conversion and exact identity |
| `app/opportunities/`, `fees/`, `settlement.py`, `reference/` | Shared math, fees, settlement and reference research |
| `app/storage/`, `integration_tests/` | Separate PostgreSQL workflow and disposable integration checks |
| `tests/`, `app/fixtures/` | Authored offline tests; archived replay tests are explicitly opt-in |

See [architecture](architecture.md#module-ownership) before adding parallel policy
or calculation implementations. Keep versioned saved formats readable. Reference
models do not automatically become current-board probability sources.

## Maintenance

Preserve public imports, packaged asset paths and supported fixture readers.
Ruff checks critical defects; formatting checks apply to CI support code. Prefer
localized edits consistent with nearby source. Review Python modules above 500
physical lines and extract or justify above 1,000; JavaScript uses 300/600,
styles 300/600, markup 250/500 and shell launchers 100/200. Classify extensionless
scripts by shebang: `scripts/opportunity-board` is Python, `scripts/check-ci` is
shell. Generated fixtures, lockfiles and required frozen source inputs are not
mechanically split.

Native HTTP protocol helpers live in `collection/native_http_transport.py`.
`prediction_producer.py` keeps the request budget, payload admission and observation
producer, with aliases for existing helper imports. Neither transport helpers nor
framing code imports its owner. Use `tests/test_native_http_reader.py` for plaintext,
TLS, surplus, cap and cancellation controls after changing this boundary.
The E6 failed-start fixture supplies its own temporary ownership lock/output and
checks lock release; never point fixture tests at the ordinary runtime lock.

Retain the continuous discovery/session owner and current native/quota owners as
cohesive state machines: ordering, ownership, consumed budgets, failure and cleanup
share one mutation boundary. Stream mechanics already live in `continuous_streams`;
HTTP framing now has a separate module. Cost/source-input value objects and current
contract validation implement versioned wire contracts, so their validators stay
next to the types they admit. Test classes group controls by feature and share
setup; their size alone does not require fixture duplication. These review decisions
apply below the 1,000-line Python limit; renew them after material growth or new
responsibilities. Do not split immutable schemas, applied SQL migrations or frozen
source archives to meet line counts.

Keep local notes, collected observations and generated reports out of Git. Authored
schemas and examples live under `docs/contracts`; independent test inputs live in
`tests/fixtures` and `app/fixtures`. `tests/comparison_oracles.py` resolves original
research provenance names to required fixture files without reading local notes.
The `tests/fixtures/retained-retail` inputs preserve public market observations,
original receipts and evaluation clocks; they do not establish present availability.
Keep these required inputs visible to Git. Sealed executors require the exact source and
control files in `scripts/v1_coverage_package` and `scripts/v1_counterpart_package`;
do not regenerate those inputs as part of documentation cleanup.

Local credentials, state, generated reports and working notes are ignored.
The [CI contract](CI.md) declares required suites and archival omissions. Merge
checks cannot read historical evidence or owner state; author independent fixtures
for maintained behavior instead of adding captures to the gate. Run `git diff --check` after edits.
