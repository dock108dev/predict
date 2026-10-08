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
styles 300/600, markup 250/500 and shell launchers 100/200. Generated fixtures,
lockfiles and required frozen source inputs are not mechanically split.

Local credentials, state, generated reports and working notes are ignored.
The [CI contract](CI.md) declares required suites and archival omissions. Merge
checks cannot read historical evidence or owner state; author independent fixtures
for maintained behavior instead of adding captures to the gate. Public docs should explain behavior and commands, not task history,
private workspaces or review status. Run `git diff --check` after edits.
