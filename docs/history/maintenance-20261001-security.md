# October 1 local security hardening

Base Git revision: `57a09b00d357827e436b5568793775716732a1cc`. This pass builds on
the uncommitted [failure-handling maintenance](maintenance-20261001-abend.md),
preserving that work, original evidence, approved/consumed-attempt state and
running processes. README, Desktop tracker, current candidate, architecture,
SSOT, development and earlier maintenance decisions were read before edits.

Frozen beta application manifest SHA256:
`2b3b9330e5749572681ad28c073396aa2411bb685fee157546b8ab51f69ae193`.
Current application manifest SHA256:
`151e8e32d20178ba15aa062da7a18abc5915a59bec026d87116c652b9e51a6a4`.
The latter hashes current bytes at the frozen manifest's application paths, using
the same sorted compact JSON digest. It includes both maintenance passes, not a
new commit, owner acceptance or runtime qualification. The original candidate
manifest/evidence was not rewritten.

## Security understanding

Predict is a Python/aiohttp, file-backed personal service bound to `127.0.0.1`.
Static JavaScript renders saved/current comparisons, watches and manual scenarios.
It has no login sessions, roles, tenants, remote admin, public webhook/callback,
payment/reset/invite flow or order submission. Remote/proxy/shared-user operation
is unsupported; adding a hosted authentication stack was not warranted.

| Boundary | Current controls and reviewed implications |
| --- | --- |
| Browser to HTTP | Socket-derived Host, exact Origin, Fetch Metadata, JSON parsing/byte limits, selection policy and security headers. Same-user programs can forge headers; this is not local-process authentication. |
| HTTP to persisted state | Imports target an active projected session. Saved selections resolve through the server-owned catalog; downloads have fixed filenames. Watches grant no collection authority. |
| Owner to provider | Exact run specification, candidate/output approval and consumed attempts precede dedicated Keychain access. Provider destinations/roles are server-owned; browser controls cannot inject arbitrary URLs. Current transport paths reject redirects and have finite request/byte/credit bounds. |
| Provider/saved content to UI | Content is untrusted. Dynamic renderers escape text and restrict external links to HTTP(S), with `noopener noreferrer`; CSP, no-store, no-referrer and noindex remain. Hashes verify consistency, not authenticity against a package writer. |
| Background work to files/processes | Journals, caches and workers retain existing bounds. New JSON body deadlines and exclusive watch staging supplement them. Launcher arguments are lists, with process identity checks and a minimal environment. No shell interpolation was introduced. |
| Historical SQL/serialization | PostgreSQL is a separate trusted-local mode, not the default dashboard. Queries use bound parameters/composed identifiers. Internal pickle is worker serialization, not browser-supplied input. Migration SQL is repository-owned. |

Reviewed routes, mutation/import schemas, saved-file/path selection, browser
HTML/links/storage, provider access, approval/credential paths, subprocesses,
logging, SQL/serialization entry points and CI/dependency setup. Searches used
source paths rather than reading private owner settings or Keychain contents.

## Confirmed issue fixed

**Arbitrary discovery exception text reached status and diagnostic rows.**
Category: sensitive error disclosure; area: `continuous.py` discovery/source
failure handling; severity **medium**, confidence **high**, status **fixed**.
The previous collector copied `str(result)`/`str(exc)` into source-stop,
catalog-exclusion and refresh fields. A transport/parser exception containing a
private URL, path or credential could therefore become browser-visible or durable
diagnostic content. This establishes a disclosure path, not an observed real-key
incident. Exceptions now contribute class names; safe logs retain locations and
source identity. Existing dedicated policy codes remain. Failure injection verifies
no sentinel private text reaches those fields/logs, and a healthy source still
publishes independently.

## Hardening opportunities fixed

| Title | Category / affected area | Severity / confidence / status | Realistic scenario, code evidence and fix |
| --- | --- | --- | --- |
| JSON body reads had no time bound | Availability; `local_security.read_json` and route middleware | Low / high / fixed | A stalled local caller could retain a request indefinitely below the byte cap. The read loop awaited each chunk without a timeout. A ten-second total consumption deadline now returns fixed 408, forces connection closure and invokes no mutation; progress cannot reset it. This is not a header/connection or global concurrency limit. |
| Another localhost origin was accepted as same-site | Browser trust boundary; `check_browser` | Low / high / fixed | A page on another localhost port could issue GET subresource requests with `Sec-Fetch-Site: same-site`, potentially driving replay or consuming already-bounded subscriptions. Previously only `cross-site` was rejected. Present metadata must now be one `same-origin` or `none` value; duplicate/unknown/same-site values are denied. Missing metadata remains supported for trusted local clients; mutation Origin checks are retained. No read-access or mutation bypass via browser SOP is claimed. |
| Predictable watchlist staging followed links | Filesystem integrity; `WatchStore.save` | Low / high / fixed | A stale or tool-created `watch.tmp` symlink could make `write_text` truncate an unrelated owner file before replacement. Exclusive unpredictable same-directory staging eliminates that path; replacement does not follow a destination-file symlink. Failed write/fsync/replace retains the previous watchlist. Parent directories remain trusted. |
| Newly saved watches used ambient file permissions | Local privacy; `WatchStore.save` | Low / high / fixed | Ambient umask could make saved watch names/criteria readable to other OS accounts. New staging/replacement files use 0600; a newly created immediate directory uses 0700. Existing owner directories/data were not chmodded or migrated. |

## Intentional acceptable patterns

- **Local-process trust:** authentication; informational/high confidence,
  **accepted** for the documented single trusted account. No account or tenant
  API exists. Loopback/Host/Origin guards do not authenticate another process.
- **Browser/display controls:** client security; informational/high confidence,
  **accepted**. Existing escaping, URL restrictions, CSP, no-store and frame
  denial remain. HTTP loopback has no HSTS; noindex is not authorization. Browser
  preferences/assumptions contain inert calculation inputs, not provider secrets.
- **Exact provider authority:** authorization/quota; informational/high confidence,
  **accepted**. Client settings cannot grant live allowance, refund failed
  reservations or reuse consumed attempts. Credential-safe logging suppression in
  dedicated acquisition executables and safe failure telemetry remain intentional.
- **Trusted-local historical modes:** deserialization/storage;
  informational/medium confidence, **accepted** within their existing scope.
  No pickle, arbitrary SQL, subprocess command or filesystem path was exposed as
  a new browser operation.

## Validation

Temporary synthetic output, loopback mocks and read-only retained fixtures only.
No provider request, account/credential lookup or owner-data modification occurred.

- New `tests.test_security_hardening`: **9 passed**, including total body
  deadline, normal cancellation, same-site/ambiguous metadata rejection,
  independent healthy-source preservation, staging/destination symlinks,
  permissions, atomic failure and secondary-cleanup error preservation.
- `tests.test_security_hardening`, `tests.test_dashboard_security`,
  `tests.test_ssot_policy`: **26 passed** on the final source, including the nine
  new cases above.
- `tests.test_commercial_engineering`: **12 passed** (watches/history).
- `tests.test_native_selectors`, `tests.test_source_session`: **26 passed**.
- `tests.test_abend_handling`, `tests.test_coverage_failure_handling`:
  **16 passed**, preserving the prior maintenance behavior.
- `test_board_security.cjs` and `test_dashboard_failures.cjs` passed.
- Python compile, shell syntax, edited documentation links and
  `git diff --check` passed. `pip check`: no broken requirements.
- A narrow private-key/AWS-key pattern search in `app`, `scripts` and `.github`
  returned no matches. This is not a complete secret scan. No dependency-advisory
  scanner, hosted/static-analysis run or CVE-clean claim is included.

The two older continuous-discovery baseline failures recorded in the previous
maintenance report were not rerun or reclassified. They remain a separate fixture/
admission follow-up; these passing affected checks do not claim the full CI matrix
is green. New security regressions are included in `scripts/check-ci`.

## Prioritized remaining roadmap

1. **Before remote/proxy/shared-user operation — needs decision.** Authentication
   and filesystem isolation; medium severity outside the supported local model,
   high confidence. Choose session/capability authentication, least-privilege
   directory ownership and TLS/proxy policy, then implement role/tenant controls
   only if those product concepts exist. Do not expose this service remotely now.
2. **Before accepting untrusted capture directories — deferred.** File handling;
   low severity in the current trusted-parent model, high confidence. Define
   private staging, reject traversal/symlink chains with descriptor-based opening,
   and bound inventory/replay. Current watch staging does not solve parent-path
   races or authenticate whole capture packages.
3. **If local contention warrants it — deferred.** Availability; low severity,
   high confidence. Measure affected expensive saved routes and add admission/
   execution budgets plus a header/connection policy that preserves Stop/status.
   JSON body and subscription limits alone do not bound all CPU or connections.
4. **Operational assurance — manual verification outside this pass.** Dependency/
   platform security; informational severity, medium confidence. Separately check
   current advisories and hosted scans, Keychain ACLs/provider scopes, permissions
   on existing state/logs, and loaded-process identity. Existing bytes were not
   migrated, and active processes have not loaded these changes.

Current operating guidance is [security](../security.md); README/development and
the Desktop tracker link this record. No live collection, approvals, restart,
browser walkthrough, database integration, packaging, signing, commit, push or
release was performed. Owner acceptance and frozen-candidate qualification remain
separate.
