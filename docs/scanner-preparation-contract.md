# Scanner readiness preparation reuse

The background scanner owns one process-local readiness preparation cache. The
app reads its latest database publication and has a separate bounded selected-item
cache; it never prepares a whole slate for an ordinary scanner page.
[Cross-process ownership](data-app-runtime-contract.md). It stores compact
detached input facts, not financial results, durable history or acquisition
authority. Current SQL remains authoritative. Every capture first takes a fresh
repeatable-read snapshot and resolves the complete current occurrence membership.
A newly admitted conflicting peer can therefore invalidate an unchanged quote.

Preparation runs once per resolved occurrence, through the existing normalized
input, profile and readiness owners. It avoids a second catalog-only adaptation.
One immutable, validated source-rule/selected-applicability snapshot belongs to
each fresh read context. Occurrences receive detached dictionaries; profile
pools and quote-specific applicability checks remain independent.
Unchanged occurrences reuse their prepared facts only when the exact resolved
records, native book headers, epoch, engine, readiness policy, fact registries,
selection, configuration, authority and relevant source state/reason match.
Original quote, book, reference, receipt and calculation clocks keep their own
meanings. A receipt-only change requires fresh readiness facts; it does not by
itself create new economics or renew an original source price.

## Temporal invalidation

Each entry has a half-open validity interval. Equality at its next boundary
requires preparation again; a clock reversal cannot reuse a forward-time result.
Boundaries include original quote/book/reference ages, future original or receipt
clocks, kickoff, occurrence links, nested model applicability and scheduled fees.
All shipped fact-registry contents are freshly hashed. Their activation/expiry
boundaries include inactive selected records absent from currently attached
profiles. The scanner's probe and next revalidation deadline observe those
boundaries even when SQL receives no new packet.

Prepared instrument deadlines withhold old authority at the boundary while fresh
proof is obtained. The existing temporal dependency owner binds active fee and
content schedules into instrument model versions, so crossing such a boundary
also invalidates cached financial results. Reusing preparation never changes the
original calculation instant of unchanged economics.

## Capture ownership and input bytes

`ReadContext` first creates private copies of only the record, quote and metadata
containers it edits before occurrence resolution. Locator removal, aggregate
metadata and source-state edits leave the raw SQL frame unchanged. Other nested
facts, including unknown fields, remain untouched during this short private
phase. The resolver still deep-copies every complete output record, so resolved
records and their nested facts are detached from the original frame in both
directions. This removes an earlier duplicate full traversal; it adds no SQL or
occurrence cache.

Current bundles install the existing exact `ReadContext.guard` directly during
construction, replacing a whole-bundle hash that the context previously computed
and immediately overwrote. Ordinary public `combined_inputs.build` keeps its
self-validating bundle identity and defensive record copies. Ordinary current
bundles keep their full detached records and existing current guard. Only the
private readiness path, bound to an exact occurrence in that read context and
its guard, returns an empty unused `records` field. Its state inputs, profiles,
membership, current identity and clocks remain the same.

After a real readiness capture releases its SQL transaction and connection, the
scanner transfers its already detached frame and financial-input dictionaries
through the private `Projection._ingest_capture` path. The capture caller
relinquishes both outer dictionaries. Preparation retains one recursively frozen
JSON tree per entry. Only the scanner's private `_shared_facts=True` capture path
reuses immutable instruments and financial-input facts across unchanged groups;
their normal dictionary/list mutators are blocked. Public cache reads, ordinary
captures, selected-ticket captures and deep copies return fully mutable detached
ordinary dictionaries and lists, including unknown nested fields. Neither the
cache nor a selected-ticket capture exposes a mutable alias to retained facts.
JSON content, exact validation and every invalidation check remain unchanged.

The ordinary `Projection.ingest` entry point keeps its full encoded-input
64 MiB check and defensive deep copies. It has no ownership or integer-bound
argument. Both paths build target pairs from the projection-owned `self.frame`
and use `self.inputs` for every exact financial dependency check. An ordinary
caller's later mutation of its original frame cannot change target membership,
expiry or predicates through a retained pair alias.

Preparation already counts the encoded bytes of each detached financial-input
value. Capture metadata adds the conservative whole-map bound
`2 + retained_input_bytes + sum(len(encoded(key)) + 2 for key in financial_inputs)`.
This includes UTF-8 and escaped key bytes, colons, commas and outer braces. A
nonempty unique-key map includes one extra comma byte; an empty map counts its
two braces. Unknown nested fields remain included in the encoded value counts.
The capture refuses a bound above 64 MiB. The private ingest path requires an
integer from 2 through 64 MiB, rejecting booleans and invalid bounds before
changing projection state. It consumes only the trusted fresh capture's proof
and avoids a second full-map encoding and copy. This resource proof establishes
no SQL, readiness or financial authority. Exact economic dependencies, current
receipt checks and original calculation clocks retain their existing meanings.

## Bounds and selected tickets

The scanner cache retains at most 500 entries, charged at most 32 MiB by the exact
encoded value/validity envelope plus encoded key bytes. It retains only the
frozen tree, replacing the previous encoded payload rather than retaining both
representations. Encoding during insertion establishes the byte charge; cache
hits require no JSON decode. This is an encoded-size bound, not a strict Python
heap claim. Deterministic least-recently-used eviction, current membership pruning
and process cleanup bound retention. Registry metadata is
separately bounded at 256 files, 16 MiB of input and 65,536 distinct boundaries.
There is no new durable file, table, journal or migration.

Tickets use a separate cache of at most 32 entries and 4 MiB. A server-owned
detached selection supplies exact native members. Fresh repeatable-read SQL and
global occurrence resolution precede preparation of only the selected current
occurrence and its references. The SQL storage guard shares that connection.
Current epoch, engine, policy, dependency, deadlines, Stop, sequence, Amount and
explicit replacement-adoption checks still apply before publication. Failure to
obtain fresh proof withholds action authority. Unrelated commits cannot replace
the selected pair's exact dependency proof.

The 500 executable-occurrence admission limit applies before selected-member
filtering. A selected request cannot bypass the complete current universe's
capacity or occurrence consistency checks.

Pending scanner work continues through bounded worker turns of at most 16 pairs
and the existing nominal 500 ms time cap, without an
unconditional 250 ms delay between turns. The event loop regains control between
turns; Stop, cancellation, expiry and current-input reconciliation remain active.
Idle work still uses one coalescing wake bit and its bounded wait. There is no
additional financial worker pool or unbounded task queue.

A successful post-drain proof may authorize detached calculation inputs for the
next pending turn, bound to the exact marker, projection generation and capture
revision. The token is consumed before work, expires at the next deadline and
does not assert that no ingress occurred. Every turn still obtains fresh SQL,
registry, policy and source proof after calculation and before publishing new
financial values. A changed or failed proof discards continuation and reconciles.
Idle/nonpending operation retains ordinary fresh probing.
When that fresh pre-work SQL, registry, policy and source proof is unchanged and
the next deadline has not arrived, a nonpending tick performs expiry only. There
is no calculation result to publish, so it skips a redundant post-work probe and
materialization. Changed proof or deadline equality still requires fresh capture.
Stop is checked again after the last calculation, each blocking proof and each
capture, before ingestion or publication. A stop arriving on the final pair of
a batch cannot depend on another calculation checkpoint to withdraw authority.

Expiry immediately withdraws expired rows and receipts from the already
published view. It cannot promote completed but unpublished cache entries or
revalidate surviving receipts. This holds inside a financial batch and for an
HTTP reader; fresh post-drain proof controls later financial publication.

The occurrence resolver indexes only necessary league/participant/shared-ID
conditions, then applies its original consistency and metadata predicates.
Missing ID namespaces remain candidates; any matching shared witness still
participates in conflict checks. Candidate audit order remains the original fact
order. Receipt validation shares a single current instrument lookup within a
materialization; exact receipt and original-clock checks are unchanged.

Successful scanner reads schedule the next client poll 500 ms after the read
cycle completes. One active scanner-read generation and one scheduled poll keep
the loop bounded; existing abort, response/page limits, timeouts and failure
backoff remain in force. See the [client contract](scanner-client-contract.md)
for the request and retained-data bounds. Polling cadence is not evidence of
source freshness or demonstrated propagation latency.

The 768 MiB per-process guard remains independent of encoded cache bounds.
Authored SQL/browser workloads test implementation behavior; they do not establish
current provider coverage or financial applicability. See the
[readiness](scanner-readiness-contract.md),
[projection](scanner-projection-contract.md),
[ticket](scanner-ticket-contract.md) and
[summary](scanner-summary-contract.md) contracts.
