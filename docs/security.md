# Local security maintenance

September 16, 2026. This source pass starts at HEAD
`5fd1d5e8234a84a96d5465f74335c16f9a8b5bc7` **plus the preexisting uncommitted
SSOT/math changes** documented in [ssot.md](ssot.md). It follows the current
README, [Desktop tracker](../../prediction_arb_next_steps.md), and
[roadmap](product-roadmap-review.md). The owner's security implementation request
authorizes these bounded fixes despite the roadmap's general deferral of
production hardening. This is not a new qualified build or owner acceptance.
Existing processes and retained evidence were not intentionally modified.

## Application and boundaries

The current product is Python/aiohttp with static HTML/JavaScript. Its authoritative
factory is `app/dashboard/multi_game_server.py`; the compatibility factory and
CLI in `opportunity_board.py` delegate to it. The launcher binds IPv4 loopback,
starts idle, and uses a minimal environment with no inherited provider secrets.
No reverse proxy, remote hosting, accounts, roles, tenant boundaries, password
reset, payment routes, uploads, webhook receiver, or admin interface is implemented
in this product. There is no login session or cookie to harden.

| Boundary | Current policy and source |
| --- | --- |
| Browser → dashboard | `/`, `/game`, fixed CSS/shared JS and `/view/` assets; GET `/api/status`, `/api/sessions`, `/api/dashboard`, `/api/calculate`; POST `/api/start`, `/api/stop`. All use the same middleware. Inputs are untrusted. No CORS permission is granted. |
| Browser → collection authority | Exact local Host and matching Origin for mutations; JSON only, 4 KiB body limit; Start settings remain integers bounded by `MultiOwner.start` to 1–6 games / 1–180 seconds. Stop requires `{}`. Browser metadata rejects cross-site requests. |
| Owner process → provider | Explicit Start loads dedicated macOS Keychain credentials through `collection/venue_access.py`. Fixed Kalshi/Polymarket US destinations, signing and credential-echo checks are existing controls. No browser-supplied credential or destination. HTTP/WebSocket data is untrusted input to adapters, bounded journals and projections. |
| Background work → files | `MultiOwner` owns collection/finalization tasks, rejects overlapping starts, and writes bounded scan artifacts. No automatic scheduled collection. Saved journals/manifests are checked before projection; hashes establish consistency, not authenticity against someone who can rewrite all files. |
| Browser → retained files | Session/game selectors index discovered datasets; they are not joined directly into arbitrary file paths. Static serving stays within the asset directory. Saved source folders and manifests are trusted local inputs; OS-account isolation remains relevant. |
| Process → database | Current beta is file-backed; its CLI denies psycopg connections. Older `dashboard/server.py` serves separate historical/PostgreSQL workflows. `storage/store.py` uses a local Unix socket, bound query values and quoted identifiers. Migrations are trusted repository SQL. |
| Internal worker → worker | Historical `dashboard/refresh.py` uses pickle for internally generated thread handoffs. No user/file/wire deserialization path was identified there; maintain its explicit internal-only contract. |
| Data → browser | Current templates escape dynamic text; assumptions in localStorage are user-entered probabilities/bases, not provider secrets. Research source URLs come from bound local evidence. No public analytics integration was identified in this surface. |

Provider verifiers and historical E5/E6 previews remain separate commands.
ProphetX/Novig adapters and optional reference-service environment settings are
retained; this pass neither activates them nor changes their entitlement status.
Launcher subprocess arguments are lists, with process command and start-time
checks before stopping an instance. Owner data, credentials, services, and frozen
review candidates were not accessed or replaced by validation.

## Findings and changes

Each finding below has high confidence from current source unless stated otherwise.
Severity reflects this single-user, direct-loopback deployment.

### Confirmed defects with security relevance

- **Malformed assumption shapes and unknown game selection** — category: input
  validation / error handling; severity: **low**; status: **fixed**. In
  `multi_game_server.py:dashboard`, JSON was used through `.get` and `.strip`
  without checking object/entry/basis types. For example, an EV request with
  `assumptions=[]` produced an unhandled exception. Unknown game selection also
  used an unguarded `next`. Crafted requests could generate server failures and
  noisy exception logs, but no persistent denial of service or code execution
  was established. Shapes, permitted fields, entry count and basis length are now
  checked before saved-data loading; unknown games return 422. Unexpected failures
  return a generic 503 and log only the exception class, not its potentially
  sensitive message or traceback.

### Hardening opportunities implemented

- **Request authority validation** — category: browser/API boundary; severity:
  **low**; status: **fixed**. The previous Host check derived its accepted port
  from that same untrusted Host. `local_security.check_browser` instead uses the
  actual socket port, rejects duplicate Host/Origin values, rejects nonmatching
  supplied Origin and cross-site Fetch Metadata, and requires same-origin JSON
  mutations. Previous POST Origin checking already blocked ordinary cross-site
  form attacks; no authentication bypass is claimed. Local aliases remain
  supported, with each mutation matching the alias used to load the page.
- **Oversized/malformed control payloads** — category: input/resource controls;
  severity: **low**; status: **fixed**. The beta inherited aiohttp's default body
  allowance, accepted non-JSON content types at `req.json`, and ignored Stop
  bodies. It now uses 4096 bytes and explicit JSON/empty Stop validation. Invalid
  requests are rejected before owner dispatch. Calculation inputs reuse the
  existing `fees.engine.number` precision policy earlier in request processing.
  The suspected decimal-exponent expansion issue was **not a vulnerability**:
  the existing shared parser already enforces 24 digits / exponent magnitude 12.
  No financial values are rounded, clamped or otherwise changed by this pass.
- **Incomplete response protections** — category: browser/privacy headers;
  severity: **low**; status: **fixed**. Early exceptions and 422 responses skipped
  the existing CSP/no-store update. Responses handled by application middleware
  now consistently include CSP with form/frame restrictions, no-store, nosniff,
  DENY framing, no-referrer, restricted camera/microphone/location permissions,
  and noindex/nofollow. HTTP parser failures before middleware are outside this
  guarantee. Noindex is indexing guidance, not access control. HSTS is deliberately
  absent on plain HTTP loopback.
- **Inactive dependency-update configuration** — category: dependency hygiene;
  severity: **low**; status: **fixed in source**. `.github/dependabot.yml` contained
  an empty `package-ecosystem`. It now selects `pip` for the existing root project
  manifest, retaining the weekly schedule. Hosted activation is unverified; the
  change was not pushed. No package vulnerability or clean vulnerability scan
  is claimed.

### Intentional acceptable patterns

- **No account login/local session token** — category: authentication; severity:
  **informational**; confidence: high; status: **accepted for current local scope**.
  Loopback, exact Host, browser Origin and Fetch Metadata protect browser access
  boundaries; they do not authenticate another process or OS user on this machine.
  A local program can forge these headers. This is not suitable for remote or
  shared-host deployment. Introducing account authentication is not justified by
  the present personal-prototype architecture.
- **Trusted internal pickle and parameterized SQL** — category: deserialization /
  injection; severity: **informational**; confidence: high; status: **accepted**.
  Inspected historical worker handoffs originate within the process; database
  values use parameters and dynamic identifiers use psycopg quoting. Neither
  pattern establishes a remotely exploitable injection finding. Never add an
  uploaded/replayed pickle input to that worker contract.

## Prioritized remaining roadmap

1. **Decide whether other local users/processes are adversaries.** Category:
   authorization; severity: **medium if shared/untrusted machine, informational
   under current assumption**; confidence: high; status: **needs decision**.
   If they are, define a private per-launch capability/bootstrap flow and OS file
   permissions before any multi-user/remote use. Origin is not local-process
   authentication. Do not enable network binding or proxy this app as-is.
2. **Bound aggregate saved-data work and retention.** Category: availability;
   severity: **low**; confidence: high; status: **deferred**. `datasets()` replays
   discovered saved captures for requests; collection is bounded per run but
   retained history can grow. A local caller can repeatedly request expensive
   projections. Choose a history/retention UX, then cache immutable verified
   projections with identity invalidation and a small request-concurrency budget.
   Do not delete retained evidence to implement this implicitly.
3. **Choose a maintenance/retirement policy for historical servers.** Category:
   attack surface; severity: **low**; confidence: high; status: **needs decision**.
   E6 live/real guards retain the older Host-port policy, and the PostgreSQL
   dashboard has a separate token policy. If these remain actively supported,
   port shared browser protections with their own compatibility tests. This pass
   changes only the active beta and its delegating entry point, not preserved
   candidate implementations or independently running previews.
4. **Define storage ownership and reproducible dependencies.** Category: local
   filesystem/supply chain; severity: **low**; confidence: medium; status:
   **deferred**. Current artifacts inherit local directory/umask ownership; no
   hostile-symlink or same-account attacker protection is claimed. For a shared
   machine, adopt private new runtime directories and symlink-safe creation after
   deciding whether captures are shared. Choose a supported Python version and
   lockfile process before pinning the broad dependency ranges. Do not chmod,
   migrate, or rewrite owner evidence in a maintenance sweep.

Manual verification outside this repo: Keychain ACLs/entitlements, existing
artifact permissions, active process identity, provider scopes, GitHub Dependabot
execution and advisory scanning remain **unverified** (informational, confidence:
medium, status: deferred). A limited source-pattern check found no private-key
block/AWS access-key pattern in app/tests/scripts; this is not a comprehensive
secret-history audit. No production security guarantee is inferred.

## Validation and operational limits

The missing `.venv` was restored with the existing `.[stream]` project extras.
The pre-edit baseline passed 37 focused tests. After changes, the same set plus
four security tests passed: **41 tests**, including saved arithmetic reconciliation
and two disposable mock Start/Stop cycles. A final focused rerun of the four
boundary tests covers the final validator/header edits, static page/JS responses,
forged Host, missing/foreign Origin, Fetch Metadata, wrong content type, oversized
bodies, invalid assumption types, rejected decimal exponents, rejected mutations
before dispatch, valid mock controls, and sanitized 503 logging.

```sh
.venv/bin/python -m unittest tests.test_dashboard_security tests.test_opportunity_board tests.test_multi_game tests.test_personal_beta tests.test_multi_page tests.test_page_estimate tests.test_math_reconciliation -q
.venv/bin/python -m unittest tests.test_dashboard_security -q
.venv/bin/python -m compileall -q app/dashboard/local_security.py app/dashboard/multi_game_server.py tests/test_dashboard_security.py
.venv/bin/python -m pip check
git diff --check
```

Syntax, dependency consistency and whitespace checks pass. Existing aiohttp
AppKey and asyncio timing warnings remain. `pip check` is not an advisory scanner;
no dependency CVE audit, full CI matrix, browser walkthrough, live feed test,
credential read, owner database access, signing, packaging, commit or publishing
was performed. Tests read retained market fixtures and write disposable synthetic
state only. Existing unrelated edits remain. **Running processes have not been
restarted and do not receive these source protections until restarted.** Restart
only the intended idle beta through its existing launcher when operationally
appropriate; no new collection is implied.
