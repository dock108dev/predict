# Local security

The supported application is a single-user service bound to `127.0.0.1`, with
local saved journals and explicit Start/Stop. It has no accounts, tenant isolation,
public webhooks or order execution. Remote, reverse-proxy and shared-user deployment
are unsupported. Browser protections do not authenticate other local processes.

## HTTP and browser boundary

`local_security.py` validates Host, Origin and Fetch Metadata and supplies response
security headers, including CSP. Mutating routes require JSON. Strict streamed
parsing rejects duplicate keys and non-finite numbers, with 4 KiB control and
1 MiB import limits. `query_policy.py` validates selectors and manual assumptions.
Reference/result imports append only to an active projected session; completed
saved packages cannot be edited through those routes.

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
credentials. Real collection requires an explicitly configured run specification
and its applicable approval/consumed-attempt checks before dedicated Keychain
access. Browser input cannot supply provider destinations or credentials.
See [configuration](configuration.md) for source-specific access and separate tools.

Saved selectors resolve through discovered packages. Journal hashes and manifests
establish consistency, not authenticity against someone who can replace a whole
package. Saved data and provider content remain untrusted display input.
The current dashboard accepts neither pickle nor SQL from the browser. Historical
SQL and internal worker serialization have separate trusted-local entry points.

Failures use sanitized operation names, exception classes and traceback locations;
raw provider content and credentials must not enter logs. See
[failure handling](error-handling.md) for cleanup and incomplete packages.

## Support limits

Remote or shared-user deployment needs authentication, filesystem isolation and a
TLS/proxy design. Importing untrusted capture directories needs a defined staging
boundary and symlink-safe file handling. Neither is supported by the current local
workflow. Global request quotas, body-read deadlines and replay concurrency limits
are not implemented merely by bounding notification subscriptions.

Hash-locked dependencies, dependency consistency checks and hosted static analysis
are complementary checks, not proof that no vulnerable dependency exists. Keychain
ACLs, provider permissions and platform behavior require separate verification.
See [development](development.md#pull-request-ci) for the actual CI checks.
Dated findings and their original validation remain in the
[security engineering record](history/maintenance-20260928/security.md).
