# Local security

The supported application is a single-user service bound to `127.0.0.1`, with
automatic configured read-only acquisition, Stop controls and separate saved-session readers. It has no accounts, tenant isolation,
public webhooks or order execution. Remote, reverse-proxy and shared-user deployment
are unsupported. Browser protections do not authenticate other local processes.

## HTTP and browser boundary

`local_security.py` validates Host, Origin and Fetch Metadata and supplies response
security headers, including CSP. Mutating routes require JSON. Strict streamed
parsing rejects duplicate keys and non-finite numbers, with 4 KiB control and
1 MiB import limits. Body consumption has a ten-second total deadline, including
chunked uploads; partial progress does not reset it. Timeout returns a fixed HTTP
408, closes the connection and dispatches no mutation. Cancellation still
propagates. This deadline starts at body consumption, not initial connection or
header receipt. `query_policy.py` validates selectors and manual assumptions.
Reference/result imports append only to an active projected session; completed
saved packages cannot be edited through those routes.

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

Failures use sanitized operation names, exception classes and traceback locations;
raw provider content and credentials must not enter logs. See
[failure handling](error-handling.md) for cleanup and incomplete packages.
Native discovery failures now expose exception classes in source-stop, refresh
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
