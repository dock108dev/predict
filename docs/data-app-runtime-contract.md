# Independent data runtime and latest results

The ordinary installation uses two processes in the same main checkout and the
existing PostgreSQL database. `app.collection.data_runtime` owns `CurrentService`,
current-row maintenance, the shared scanner and shared Odds/EV calculations.
`app.dashboard.opportunity_board` uses `RuntimeClient` and database result readers.
HTTP access never starts the shared workers. No broker or extra database is used.

## Lifecycle and controls

`scripts/opportunity-board start` starts both processes; `status` describes both
and `stop` stops both. Add `--role app` or `--role data` to operate independently.
For example, `stop --role app` followed by `start --role app` leaves collection,
the runtime identity, current-row epoch and calculations intact. Start is
idempotent; racing launcher calls use an exclusive launcher lock. The data owner
also requires an OS ownership lock and a session-level PostgreSQL advisory lock
before constructing or dispatching sources. Process stop checks both command and
birth identity. The launcher never stops PostgreSQL or unrelated processes.

Heartbeat persistence copies loop-owned status before sending its SQL write to
a background thread. Publications take a shared advisory authority lock;
startup and explicit controls take its exclusive counterpart. Heartbeat writes
remain independent, so a long publication cannot suppress liveness. A genuine
control-row conflict has a 100 ms heartbeat wait and the next normal cadence
retries; the eight-second reader death bound is unchanged. Conditional updates
cannot overwrite a changed runtime, Stop, source pause or stopping state.

Native books, source health, catalogs and aggregate admission use one serialized
ingress owner with at most eight outstanding operations. SQL and normalization
run off the event loop; reducer adoption and committed acknowledgments resume on
the loop in order. Cancellation revokes adoption while the actual worker remains
owned. Stop/pause withdraw dispatch immediately, then persist their authority;
the transaction rechecks runtime/control identity and revocation before commit.
Shutdown reports incomplete cleanup rather than releasing a live ingress owner.

Estimates, Scanner and Coverage share one reusable optional-work thread. Each of
the three owners awaits its existing turn before submitting another; queued work
contains callables, not captured graphs. Existing memory admission, FIFO turns
and source runway remain in force. Observations and ingress run independently.
This also reuses the optional thread's allocator heap across large captures.
The single observation owner and serialized ingress owner each have a dedicated
reusable thread; lightweight control and heartbeat writes never queue behind them.

Coverage disables PostgreSQL JIT only inside its bounded capture transaction.
The JSON projection otherwise compiles hundreds of functions before yielding
rows, delaying publication and cancellation on slower hosts. Transaction-local
configuration restores the connection policy on commit or rollback. Shutdown
still cancels active SQL repeatedly and awaits the actual worker within the
existing five-second allowance; it never releases a live worker's reservation.

Admin's global/source Stop is a separate acknowledged command to the data owner.
`data_runtime_command` retains at most 32 pending commands, expires unhandled
commands, and evicts completed acknowledgments. Each command binds the exact
runtime identity. Success means the owning process acknowledged the operation;
timeout, changed owner and cleanup failure remain explicit failures. A timeout
does not authorize an automatic retry. Global and source Stop latches survive a
data restart; existing guarded recovery remains the only resumption path.

An explicit selected-fee command is a separate finite research operation owned
by this same data process. It is never scheduled by discovery, HTTP reads or
restart. Its fixed selected event, three anonymous routes, loaded runtime/source
binding and approved scope must match before admission. A durable consumed
record is written before dispatch; duplicate submission or restart cannot repeat
the operation. Command acceptance is an acknowledgment of scheduling, while the
terminal receipt separately records each attempted response or failure.

The finite operation shares Kalshi's existing source request, connection, byte,
backoff, resource and Stop limits. It adds no allowance or credential fallback.
It uses at most three requests in 45 seconds, ten seconds per request, one-second
spacing, 256 KiB per response and 768 KiB total, with no retry, redirect or cursor
continuation. Source/global Stop cancels and closes transport within the existing
five-second cleanup allowance. Exact original response clocks, bytes and hashes
remain evidence; they do not renew prices/books, create a model facet or prove
trade authority. A partial, stale, conflicted or failed result remains unbound.

`data_runtime` holds one compact validated configuration, sanitized source/status
view, runtime identity, material revision and heartbeat. A heartbeat changes no
source or calculation clock. Readers revoke authority after eight seconds without
a valid owner heartbeat, even when stored prices/results remain readable. App
cleanup only detaches its proxy. It never closes the collector. Data startup
reconciles current SQL without rotating its epoch or replaying old diagnostics.

## Replaceable results and exact authority

Migration 013 adds runtime/status/control storage. Migration 014 adds one bounded
`scanner_latest` publication, with stable opportunity/category and pair keys
inside its compact payload. Migration 015 adds `latest_board` keyed by game and
one `latest_board_status`. Migration 016 permits null calculation time for an
observation whose optional finance failed. Results replace latest state; they do not append
quote payloads, expanded reports or a financial history per update. Current
source facts/depth remain in migration 012 and protected account/quota/audit/
attempt/hold records retain separate owners. No sports reset is performed.

The scanner publication is capped at 32 MiB and retains its existing pair, row,
cache, transition and summary bounds. It contains typed readiness, compact
financial winners/receipts, exact dependencies, original calculation/source
clocks, expiry, policy/engine identities and completeness. Full financial inputs
are omitted; selected tickets capture their exact current members from SQL.
Shared boards have no fixed game-row cutoff; their compact derived-fact
publication retains a 64 MiB byte guard.
[Board result and selected-settings contract](latest-board-results.md).
Expanded Details remain transient, limited to the selected item and amount.

Committed event/contract/offer/native-book/status revisions drive discovery across
processes. Durable markers bind the runtime configuration/status from the same SQL
probe, rather than live Python attributes that another process cannot reproduce.
Readiness and selected inputs use source statuses committed with current rows;
a delayed runtime heartbeat cannot override a newly committed source Stop. Local callbacks are optional wakeups/measurement only. Calculations
run outside SQL transactions. Final publication serializes with current-row
writers and runtime controls, then compares the exact captured facts and runtime
revision. Superseded work cannot publish. Readers independently validate current
facts, owner/revision, engine/policy and temporal bounds; a stored result cannot
grant authority simply because it was read recently.

The app distinguishes unavailable results from an explicit global collection
Stop. A changed/missing publication proof, expired deadline, failed calculation,
SQL read failure or dead heartbeat withdraws scanner/ticket authority and reports
unavailable. A valid later publication can restore results. Only the current
explicit global Stop (or local reader shutdown) reports stopped; a retained
historical Stop summary cannot supply the current collection state.

Changed pairs/games recompute with existing financial owners; unrelated cached
economics keep their original calculation time and economic revision. Worker
restart revalidates persisted compact economics against fresh SQL before reuse.
Expiry, removal, Stop, configuration/model/policy/engine and epoch changes each
withdraw affected authority without requiring a new source packet. A failed
scanner capture removes its latest publication; runtime death is separately
bounded by the heartbeat. The 2 GiB SQL ceiling and 1 GiB free-disk floor
remain; the process guard follows configured RSS (currently 3 GiB). Autovacuum applies to replaceable storage; physical database
growth is still guarded rather than assumed impossible.

## App reads, tickets and observations

Scanner filters/ranking/paging/polls read the durable compact projection. Odds
and EV read shared default-policy boards; their settings apply to selected
Details, not a new whole-slate calculation. Every displayed estimate identifies
its actual policy and original calculation time. Stopped/stale observations remain
last-known. Source-only Odds frames publish independently of optional benchmark,
profile or calculation success. Estimate expiry, policy and calculation-worker
health withdraw financial authority without renewing or withdrawing healthy source
clocks; separate collection and estimate labels expose those meanings. Checked-zero requires
complete current evaluated scope; absent/failed/partial storage is unavailable.

In database mode, native image continuity binds original source event/market
material rather than derived comparison season/stage or counterpart enrichment.
An unchanged image keeps its exact source/receipt/confirmation clocks while new
metadata is normalized independently. Changed source terms, sides, eligibility or
schedule still withdraw the affected image. A transient rediscovery timeout keeps
an existing healthy socket during the same finite retry/backoff policy; exhausted
discovery reports unavailable. This adds no requests, retries or budget allowance.

Tickets bind the published exact row/dependency/economic/engine/policy/epoch
identity and capture only the selected occurrence's inputs. Amount-specific
finance remains allowed for that selection. Selected/latest/replacement frames,
explicit adoption, exact-market destination checks and original expiry remain.
An app restart can require reselection; it does not interrupt data work.

The background scanner alone owns the bounded summary summary file and episode
observations. The app reads a replaceable SQL mirror of compact summary facts;
it never opens a second summary writer. Retention, eviction, censoring and joint
edge/size disclosure retain the summary contract. The bounded transition journal
travels with the latest publication. Missing continuity or a data restart causes
silent resynchronization/censoring; stored rows cannot invent arrivals.

The focused `scripts/ci/postgres.py --da-separation` lane uses a separate disposable
PostgreSQL cluster and authored source/model assumptions. It makes no provider
requests. Fixture evidence supplies engineering verification, not current source
qualification, exact production destinations, hosted CI or live operational validity.


October 20 broad-acquisition integration: the runtime status
bound applies after deduplicating structured metrics. Full discovery, identity
and coverage diagnostics are retained once in `sources[].metrics`; legacy root
`metrics` retains scalar counters and any distinct unmirrored fields.
`status_retention.structured_metrics_location` identifies the detail location.
This avoids a broad-scope heartbeat shutdown caused by serializing the same
large diagnostic structures twice. Account/quota/hold history, source panels,
clocks, controls, Coverage meaning and the final hard capacity guard are preserved.


The status envelope is 1 MiB to carry all 90 configured
source/league/family inventory cells, their last successful boundaries and retained
account evidence. Exact repeated source metrics are still deduplicated. The prior
256 KiB bound was exceeded by honest inventory diagnostics during integration;
a 90-cell regression checks preservation of coverage, source and account fields.
The hard guard remains; no source scope is trimmed to make status fit.

## Acquisition and publication

Bulk acquisition resumes exact native pages across restart, subscribes the complete eligible roster and publishes FIFO book chunks. Ingress waits for available slots and retains Stop/cancellation ownership. Durable raw dispositions are independent of semantic publication. The watchdog and background reservations use the installed RSS setting. Alternate dispatch uses the explicit expanded owner grant and the existing exact request ledger.

See [acquisition](acquisition.md) for ownership, capacity and completeness limits.

Restart recovery retains complete native catalog metadata atomically in
`current_native_catalog_recovery` / `current_native_market_recovery`. Restored
metadata retains original clocks; live books require a new connection image.
Current acquisition images record runtime/connection/census identity, and the
reconciliation report excludes stopped/stale/disconnected authority from current
connection counts. Suspected listing absences remain eligible for recovery;
explicit closure/start and ambiguous subscription identities remain exclusions.
Normalization executes complete bounded chunks in an owned CPU process, with
SQL/Stop authority retained in the parent. The process is joined during cleanup.
Native wire reconstruction also has a per-source CPU owner. Credentials,
socket control, account guards and SQL publication remain in the parent. Bounded
batches retain FIFO delta order and original socket receipt times; a sequence gap
ends the batch and forces a fresh connection image. Child shutdown is joined.
Current owned images share immutable ladders where possible; lifecycle tracking
retains hashes/clocks, not a redundant ladder. Unchanged metadata subtrees may be
shared across complete catalog replacements without sharing writable row shells.

Heartbeat accounting is a read-only display projection prepared outside the
collection loop. Within that one projection, repeated reads may reuse a verified
ledger only while its file identity is unchanged. Spending mutations still lock
and strictly reload the ledger; display preparation grants no dispatch authority.
Catalog binding similarly uses one immutable verified public-contract revision
per operation, rejects a file change at completion, and detaches returned facts.
Streaming market preparation uses the already admitted exact native object and
original receipt hash/path/time, avoiding a full HTTP-page reload per market.

Paid response accounting runs in an owned joined thread after receipt, keeping
strict durable reconciliation off the native socket loop. Cancellation joins the
receipt write. Reservation and the durable dispatch marker also run in joined
workers, followed by a final synchronous revocation check before transport entry.
Cancellation before any request task exists records `not_dispatched` only for
that current runtime attempt, keeps its consumed cycle/day allowance, and cannot
clear an old runtime attempt or a received response. Coverage
counts reconcile an admission batch once per affected sport/family cell.
Native depth has its own exact content revision (migration 027): a newer source
clock still changes the book revision and original clocks, while identical
stored levels need no delete/reinsert. Migrated NULL depth revisions are proven
by the first complete replacement. Equal-clock conflicts and older-image guards
are unchanged. These are implementation contracts, not sustained qualification.

Complete native depth replacement upserts only differing rank values and removes
ranks absent from the complete image; unchanged rows retain their physical tuple.
Downstream observations, estimates, Scanner and Coverage yield during initial
native images, raw queue pressure, or a derived pending tail over 30 seconds.
This is scheduling priority, not a freshness-policy change. Original clocks and
current authority remain unchanged; observations resume after catch-up.

Raw-image persistence skips receipts already superseded by a durable newer image
before encoding depth. After a derived batch has durably saved its input image,
its final disposition updates only an exactly matching receipt; a newer raw image
and its runtime/connection/census identity remain untouched. Generic initial or
failure recovery writes still persist complete images with the same ordering guard.

## Native synchronization and delta acquisition

The revised [coverage contract](broad-coverage.md#freshness-and-verification-window)
separates native synchronization from last-change age. The running native owner
requires a current-generation subscription, valid initial images and durable raw
images. Ordered continuity and pending work are reported independently. An active
stream within two seconds of local processing is `streaming`; an empty pipeline
is `synchronized`. Backlog is `catching_up`; missing images are `initializing`;
invalid images are `partial`; revoked ownership is `disconnected`. Heartbeat expiry
withdraws the persisted synchronization claim without changing source clocks.

Kalshi no longer requests periodic full-roster snapshots. It applies every delta
in order and materializes final market images within bounded contiguous batches.
Reconnects and material catalog changes obtain new initial images. A catalog stop
cancels the stream before joining SQL publication, so no old-generation callback
can continue during that wait. Raw persistence reports inflight work and latency
separately from derived normalization. These synchronization observations do not
relax existing identity, settlement, sizing or financial eligibility checks.
The administrator view and acquisition reconciliation expose the separate result;
ordinary raw-screen delivery remains independently qualified.

Ordinary aggregate accounting uses one owned spawned process for repeated strict
ledger transactions and account binding checks. The process receives a duplicate
of the existing held acquisition lock descriptor; it performs no HTTP requests.
The parent retains the final permission check and transport task creation. Stop
joins mutations (including repeated cancellation), records pre-transport outcomes
when known, and joins process shutdown before acquisition ownership is released.
No account/credit/hold record is dropped or reconstructed to reduce CPU cost.
Finite injected-ledger fixtures retain the joined-thread implementation. Child
RSS must be reported separately alongside parent and combined process use.

## Independent ordinary raw reads

The app now reads received acquisition values directly for Odds/Original Inputs.
Native image persistence and its compact metadata are the acquisition-to-display interface;
app reads do not alter collection, continuity, protected accounting or finance.
App-only restart loads the new routes without restarting the collector. Bounded
read-only SQL snapshots provide coherent raw pages and retain source clocks.
See [raw display ownership](raw-prices.md).
