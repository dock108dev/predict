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
Shared boards retain at most 500 game rows and 64 MiB of compact derived facts.
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
bounded by the heartbeat. Existing 2 GiB SQL, 1 GiB disk and 768 MiB process
guards remain. Autovacuum applies to replaceable storage; physical database
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
