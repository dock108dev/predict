# Acquisition and background processing

The data process owns provider connections, accounting, current input storage and
background calculations. The app reads stored publications. Restarting the app
leaves acquisition running; restarting data preserves explicit Stop choices,
source pauses, unresolved attempts and held credits. See the
[runtime contract](data-app-runtime-contract.md) for lifecycle controls and
[configuration](configuration.md) for settings and credentials.

## Sources and current state

Kalshi and Polymarket US use native discovery and streaming adapters. Aggregate
featured and alternate lines use The Odds API when separately enabled and
permitted by the local authority and account guards. Pinnacle is a reference
source, not a purchase leg. League and family scope comes from configuration;
the example configuration enables NFL native acquisition and disables aggregate
requests. It is not the owner's installed configuration.

Discovery stores exact traversal receipts before publishing catalog metadata.
Native metadata parsing runs in an owned process per source. Books replace the
current image by exact source, event and market identity; this is not an archive
of every price update. Listing absence is retained as a suspicion, separately
from explicit closed or settled metadata. A missing listing does not establish
withdrawal or reduce a completeness denominator.

Raw persistence and derived publication are separate stages. Subscription
generation and snapshot/delta continuity determine whether a native image is
synchronized. A listing alone is not a received book. Malformed or unusable
values remain inspectable with reasons and cannot gain calculation authority.
Featured and alternate responses retain separate removal scopes. Admission
retries reuse the same paid receipt and recheck Stop without fetching again.

## Memory and backpressure

Native image material, raw pending work and derived work share immutable values
where possible. Discovery parsing, raw persistence and financial work have
separate scheduling boundaries, but lifecycle owners join active work during
cancellation before releasing resources. Capacity refusal remains explicit;
valid peers must not be silently dropped to make a smaller workload appear complete.

`markets_per_source` controls publication chunk size. Source-byte budgets, RSS,
response sizes, per-record validation and SQL/disk guards remain separate limits.
Use the configured values, not numbers from a previous run, when diagnosing a
refusal. Raising a storage ceiling does not grant additional provider spending.

## Accounting and observation

Aggregate requests must satisfy the configured cadence, operating window,
authority expiry, account window, reserve, quota and hold checks. Stop or an
unresolved charge must not be cleared to force progress. Local authority files
are operator state and are not distributed with the repository.

`python -m app.collection.acquisition_report` reads a coherent SQL census without
provider dispatch. It requires the ordinary database; it is an operational read,
not an offline test. Interpret discovered, received, synchronized, matched and
financially supported populations separately. Unknown offered counts remain
unknown. Neither raw availability nor a healthy process establishes complete
provider coverage or sustained latency and memory performance.

For isolated changes, use the [disposable SQL runner](CI.md#local-reproduction)
and select the affected tests with `--tests`. Keep provider credentials and owner
storage out of test fixtures.

## SportsGameOdds integration work

The SGO page adapter, object accounting, reference capture and worker are under
integration; their presence alone does not establish that the installed runtime
has cut over. The adapter retains original bookmaker clocks and availability,
including per-book alternate lines, and refuses incomplete or ambiguous input
rather than authorizing an absence-based withdrawal. Cursor completion alone is
not an authoritative census. Unknown settlement and unjoined native contracts
remain unqualified for reference and EV. The direct Kalshi and Polymarket US
owners remain separate.

The reference table's bounds, retention and disposable cached/synthetic replay
measurements are documented in [current-row storage](current-row-storage.md#sportsgameodds-reference-observations-integration-work).
Those results use free cached pages and invented scale fixtures, not paid-plan
coverage, live freshness, account allowance or actual cost. Exact plan terms,
venue access and operating cadence require the authorized account's own evidence.

The ten cached free NBA/NHL event objects contained SGO event IDs, teams,
status and bookmaker links, but no typed external shared game ID. SGO event IDs
and aliases remain provider-local; bookmaker URLs or matching names must not be
promoted to a foreign event-ID namespace. This observation does not establish
what every paid response may contain.
