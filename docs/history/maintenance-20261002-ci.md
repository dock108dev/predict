# CI readiness — October 2, 2026

CI now uses one Python version, 3.14, matching the installed local 3.14.5
environment. The stable `Offline checks` job keeps its existing regression groups,
Ubuntu 24.04, Node 22, hashed dependency install, read-only permissions, immutable
action pins, timeout and cancellation behavior.

The hosted run at commit `57a09b00d357827e436b5568793775716732a1cc` failed
in `test_saved_package_error_is_safe_and_logged_for_both_readers`: the ignored
local native-review catalog was required before the intended saved-read failure
could be handled. All three GitHub-managed CodeQL checks passed on that commit;
those results do not qualify this edited source.

Catalog absence now supplies no historical paths or accepted review judgments.
Existing corrupt catalogs and missing indexed records still fail. Both saved
history and review readers use the shared loader. Four portability tests join
the existing failure tests in CI. Frozen review oracle tests explicitly select
the original interpretation, preserving their calculations and fixture bytes.
A current-route regression verifies that absent legacy games return HTTP 422
without candidates; the calculation lookup now raises an explicit selection
error instead of escaping an async handler as `RuntimeError`.

Focused validation: 12 failure/catalog tests and 26 saved-review tests passed
under Python 3.14.5 in an export of tracked and nonignored files without the
local native catalog. After strengthening the route assertion, its single test
passed again. Python compile checks, shell syntax, Ruby YAML parsing, final diff
whitespace checks and `pip check` passed. Action pins were checked against their
official release tags. No Actions-specific local validator was installed.

The full CI script, a fresh hashed dependency installation, Linux execution and
hosted checks for these uncommitted edits remain unrun. The local runtime has
cryptography 50.0.2 while CI locks 50.0.1; local build tools do not match the full
CI install set. No active required-status branch protection or rules were found
for `main`; repository settings remain unchanged.

The frozen beta remains unchanged. Current source app hash is
`3ec2cf3ecef4b6d11742e8d0827bee1b165933ad690faf9a6b974bc253ba814e`,
using its existing app-manifest recipe. This pass neither commits nor pushes,
restarts the ordinary app, activates providers, changes owner state, nor grants
owner acceptance or release qualification.
