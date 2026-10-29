# Local security

The supported application is a single-user service bound to `127.0.0.1`, with
automatic configured read-only acquisition, Stop controls and separate saved-session readers. It has no accounts, tenant isolation,
public webhooks or order execution. Remote, reverse-proxy and shared-user deployment
are unsupported. Browser protections do not authenticate other local processes.

## HTTP and browser boundary

`local_security.py` validates Host, Origin and Fetch Metadata and supplies response
security headers, including CSP. Mutating routes require JSON. The HTTP parser rejects duplicate Content-Type
headers with HTTP 400 before application control dispatch; regression tests cover
conflicting orders and identical duplicates. This is an existing parser protection. Strict streamed
parsing rejects duplicate keys and non-finite numbers, with 4 KiB control and
1 MiB import limits. Body consumption has a ten-second total deadline, including
chunked uploads; partial progress does not reset it. Timeout returns a fixed HTTP
408, closes the connection and dispatches no mutation. Cancellation still
propagates. This deadline starts at body consumption, not initial connection or
header receipt. `query_policy.py` validates selectors and manual assumptions.
Reference/result imports append only to an active projected session; completed
saved packages cannot be edited through those routes.

Every request to the shared ordinary/retained router rejects duplicate query
fields before reaching a handler. A single value per field is required, including
comparison ceilings, current revision cursors and coverage filters. Admin controls
require a JSON object before action selection; arrays, scalars and null return 422
without invoking Stop, refresh, pause or recovery.

Only explicit `PublicRequestError` validation messages are returned verbatim by
the shared router. These must be authored messages, never provider text, parser
errors, user values or messages copied from another exception. Other `ValueError`
subclasses, including JSON and text decoding errors, receive a fixed 422 response.
Current comparison reads return only an explicit set of authored recovery/refusal
codes; arbitrary ValueError text and decoding errors use the fixed
`current_inputs_unavailable` reason. Scanner reads likewise preserve their explicit
filter/revision codes and use `scanner_query_invalid` for other caught failures.
Selected fee control failures use a fixed refusal message before their result can
enter a persisted acknowledgment. Diagnostic operations are
`comparison_read_refused`, `scanner_query` and `selected_fee_control_refused`.
No prefix or message-shape test grants public-message authority.

Safe diagnostics record the operation, exception class and traceback locations;
they omit messages, chains, source lines and locals. Structured calculation
refusals and `SelectionError` responses retain their separate existing contracts.

The separate `app.collection.server` synthetic tool uses this same socket-derived
Host, Origin, Fetch Metadata and response-header policy. Start and Stop require
same-origin uncompressed JSON; Stop accepts an empty object. Its existing 2 KiB
body limit also applies to chunked requests, with the shared ten-second body
deadline. Local test clients must supply their actual Origin. Its database/session
limits remain separate; normal dashboard startup does not launch this tool.

Fetch Metadata, when present, must be one unambiguous `same-origin` or `none`
value. A request from another localhost port can be `same-site` while still being
cross-origin; those browser requests are rejected, including GET subresource
loads. Missing Fetch Metadata remains supported for trusted local tools, while
Host and Origin checks still apply. These headers are browser safeguards, not
credentials against another local process.

`GET /api/updates` admits at most eight subscriptions per application instance.
Excess requests receive 429 with `Retry-After: 1`; disconnect, cancellation and
preparation failure release capacity. HEAD returns headers without event bytes or
a subscription. Status and Stop do not consume subscription slots.

Renderers escape dynamic text. `BoardView.externalLink` accepts absolute HTTP(S)
URLs without credentials, raw whitespace/control characters or backslashes;
invalid URLs become plain escaped labels. External links use `noopener noreferrer`.
Manual assumptions in localStorage are calculation inputs, not provider secrets.

## Providers, files and processes

The launcher uses a minimal environment and does not load `.env` or forward shell
credentials. Ordinary startup validates its bounded configuration and acquires exclusive ownership before dedicated Keychain access. Retained real collectors separately require a run specification and applicable consumed-attempt checks. Browser input cannot supply provider destinations or credentials.
See [configuration](configuration.md) for source-specific access and separate tools.

Saved selectors resolve through discovered packages. Journal hashes and manifests
establish consistency, not authenticity against someone who can replace a whole
package. Saved data and provider content remain untrusted display input.
The current dashboard accepts neither pickle nor SQL from the browser. Historical
SQL and internal worker serialization have separate trusted-local entry points.

New watchlist saves stage an exclusive unpredictable file in the destination
directory with mode 0600, flush/fsync it, then atomically replace the watch file.
A predictable `.tmp` symlink cannot redirect the write; a destination-file
symlink is replaced without following it. A newly created immediate storage
directory uses mode 0700. Existing directories/files are not migrated or chmodded.
Write failure preserves the previous watchlist. Staging cleanup logs safe errors
without masking the primary write failure. Parent directories remain trusted;
this is not a symlink-safe importer for arbitrary capture directories, nor a
cross-process watchlist locking/directory-fsync durability guarantee.

New launcher role directories request mode 0700 and new `data.log`/`server.log`
files request mode 0600. Log appends use O_NOFOLLOW and reject non-regular files
or files owned by another user. Nonblocking open prevents a substituted FIFO
from hanging startup. Existing regular logs retain their contents and permissions;
this change does not inspect or chmod historical owner files. Process records and
parent directories remain trusted local state, not an authenticated sidecar channel.

Failures use sanitized operation names, exception classes and traceback locations;
raw provider content and credentials must not enter logs. See
[failure handling](error-handling.md) for cleanup and incomplete packages.
Native discovery failures expose exception classes in source-stop, refresh
and catalog error fields, rather than arbitrary exception text. Safe diagnostics
retain traceback locations; explicitly generated policy/status codes remain in
their normal dedicated fields. Healthy source isolation is unchanged.

## Support limits

Remote or shared-user deployment needs authentication, filesystem isolation and a
TLS/proxy design. Importing untrusted capture directories needs a defined staging
boundary and symlink-safe file handling. Neither is supported by the current local
workflow. Global request quotas and a connection/header deadline are not
implemented. The JSON body deadline and notification quota do not cap every
expensive saved-reader path or authenticate local clients.

Hash-locked dependencies, dependency consistency checks and hosted static analysis
are complementary checks, not proof that no vulnerable dependency exists. Keychain
ACLs, provider permissions and platform behavior require separate verification.
See [development](development.md#focused-checks) for the actual CI checks.

## Error privacy and launcher files

Browser and control results use fixed public messages or exact allowlisted reason
codes. Arbitrary provider, decoder and storage exceptions must not become JSON
messages. Safe diagnostics record operation, exception class and frame locations
without source text, exception messages or local variables.

Launcher logs request private permissions and reject symlink, non-regular and
wrong-owner append targets. Trusted parent directories and existing file modes
remain part of the local deployment boundary; new-file protection does not
change historical permissions or authenticate hostile code running as the same
OS user. Request/header concurrency limits and remote authentication require a
separate design; loopback browser checks do not provide those guarantees.

## Raw-reader hardening findings

The October 28 source pass found the following issues in
`app/dashboard/raw_price_api.py`. These are local resource and diagnostic
boundaries, not evidence of remote authentication bypass.

| Finding / category | Severity / confidence | Evidence and realistic impact | Resolution / status |
| --- | --- | --- | --- |
| Raw-read admission bypass / resource exhaustion | Medium / high | Failure reads bypassed the four-operation gate; exports waited on it without refusing excess requests. A local client or repeated browser requests could queue work and compete for database/thread resources. | Fixed: failure reads and releases share the gate; exports refuse excess work with HTTP 429, as page and Details reads already did. |
| Cancelled raw-read exception disclosure / diagnostic privacy | Medium / high | The shielded task raised database exceptions directly. Python 3.14 could log their raw messages after cancellation, and a late failure could replace cancellation. | Fixed: thread results carry failures as data; `raw_read_after_cancellation` logs only class/frame locations, cancellation propagates, and the slot remains charged until work finishes. |
| Export connection ownership / resource exhaustion | Medium / high | Cancellation during `to_thread(connect)` could lose a subsequently opened connection; cancellation during SQL could begin close while work was still running. | Fixed: connection creation records ownership before returning, each operation is joined, and the connection closes in `finally`. |
| Export SQL duration / hardening opportunity | Low / high | Export transactions lacked the page reader's SQL timeouts. Slow queries or idle streaming could retain database resources longer than ordinary pages. | Fixed: ten-second statement and 125-second idle-transaction timeouts. These are not a total export or network-write deadline. |

The local threat model intentionally accepts unauthenticated same-user tools,
trusted storage parents and internal process serialization. Host/Origin/Fetch
Metadata checks, parameterized SQL, text-safe rendering and fixed provider
endpoints remain the browser/provider boundaries. No new account system, HSTS on
plain loopback HTTP, global logging suppression or provider retry was introduced.

Prioritized follow-up remains:

1. **Deferred hardening:** define total export/network-write and global connection
   limits if slow local readers interfere with ordinary use. Four simultaneous raw
   operations are bounded, but this is not a global server resource quota. An
   interrupted export has no `export_complete` trailer and must be treated as
   incomplete.
2. **Needs deployment decision:** authentication, TLS and filesystem isolation are
   prerequisites for any remote or shared-user deployment; current browser checks
   do not authorize that deployment.
3. **Outside-repository verification:** verify Keychain ACLs, provider permissions
   and historical file permissions in a separately scoped operational review.
   This pass makes no fresh dependency-vulnerability or platform-security claim.

Focused regressions in `tests/test_security_hardening.py` use synthetic threads,
connections and requests to verify admission refusal, cancellation ownership,
message redaction and export deadlines without provider requests or owner data.
