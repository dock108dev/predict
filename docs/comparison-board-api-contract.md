# Current comparison board API v2

The background owner derives compact latest Odds/EV/Arbs boards from
`CurrentRowStore`. A profile-free observation pass publishes original source
facts independently of optional benchmark decoration and existing financial owners.
Ordinary app reads filter stored PostgreSQL results; only selected Details builds
transient financial inputs and calculates the requested amount. Reads make no
provider request or account/quota/due mutation. No raw body or expanded report
history is retained. [Latest boards](latest-board-results.md),
[runtime ownership](data-app-runtime-contract.md).

## Routes and identity

| Route | Current response |
|---|---|
| `/api/boards/games` | `predict-board-catalog-2`: all admitted upcoming NFL, NCAAF, NBA, NCAAB, MLB and NHL occurrences with native full-game winner, spread and total observations, maximum 500. Capacity overflow fails explicitly. |
| `/api/boards/odds`, `/ev`, `/arbs` | `predict-comparison-board-2`: exact `game`, policy, current typed prices, separate two-sided benchmark and compact financial rows. Odds does not calculate financial scenarios. |
| `/api/boards/details` | `predict-board-details-2`: exact `game`, expected `context_id`, policy, and exactly one `quote` or `pair`. Only the selected comparison expands rich financial scenarios. |
| `/api/boards/inputs` | `predict-board-inputs-2`: exact `game`, expected `context_id`, `quote`; allowlisted typed event/selection/source/original-price/clock/native-contract/provenance/benchmark evidence, bounded observed depth and exact quote/observation revisions. This source-only inspection requires no financial discovery. No provider bodies or envelope graphs. |
| `/api/boards/history`, legacy `result_id` or explicit history requests | HTTP 410 `sports_history_unavailable`. Select a current comparison. |
| `/api/stored/*` | Explicit HTTP 410 retirement; no ordinary archive fallback. |

Every board carries `calculation_context = {context_id, epoch, dependency_revision, engine_binding}`; a financial context also includes `policy_revision`. Odds uses its source-only observation context, independently of estimate policy or model deadlines. Each financial row's Details reference repeats `context_id`, policy revision and exact quote/pair ID. Each displayed price's `inputs_identity` repeats game, input version, exact quote ID and context ID. The current v2 protocol does not repurpose legacy result or snapshot IDs.

The context binds the current store reset epoch, canonical game, source/native-book dependencies (including bid-only book changes), original receipt facts, occurrence matching, policy, financial/model/source engine files and applicability boundaries. A receipt-only observation may invalidate a context; it never renews an unchanged source-price timestamp. Unrelated game updates do not invalidate a selected game's context. Shared definitions are built from their versioned owners; no settings-variant report graph is cached or persisted.

Details and typed Original reads capture current rows and compare the required expected context. Changed, removed or temporally expired inputs return HTTP 409 with `current_inputs_changed_or_removed`; an absent selected quote returns `current_selection_removed`. Original-price Details renders its captured price and clocks immediately and keeps that frozen observation visible while supplementary evidence resolves or ends with a bounded unavailable/changed/timeout state. Financial Details adopts only a complete validated response. It never attaches new prices or freshness labels to old financial totals. Captured prices, profiles and financial results belong to one detached coherent frame even if ingress changes afterward.

Selected reads retain the full matching neighborhood: all possible current peer
events and active-membership bits, all relevant contracts/offers (including
benchmarks and other families), native book/receipt revisions, scoring bindings,
source health, epoch, runtime identity/liveness/configuration, policy/engine and
the latest Stop/pause/recovery control identity. Small event identity checks still
see newly admitted peers. Only that neighborhood's contract payloads, typed
records and depth are decoded and prepared. Before/after selected signatures
replace a global all-game marker; unrelated books/publications cannot revoke an
unchanged selection. Changed surrounding inputs, new relevant contracts and
withdrawn authority still refuse. A slate token is never selected-input authority.

## Financial meaning and display

Selected Details policy accepts exact `amount`/compatible `ceiling`, one buffer rate, sizing mode and explicit supported benchmark/method. Ordinary rows identify their background shared default policy; settings do not calculate a new slate. Details carries `selection_context` for the clicked shared row and `calculation_context` for its requested sizing, with equal dependency/engine/epoch identities. Conflicting settings reject. Defaults retain requested $1,000 funding and one 0.005 haircut on deployed capital. Complete EV, decisive conditional EV and opposing pair margins remain separate, with exact quantities/units, modeled fee and settlement assumptions and deployed-capital denominators. Pinnacle remains reference-only; supported alternative benchmarks are explicit, with no substitution for an absent selected two-sided reference.

Observed prices remain visible independently of financial eligibility. Native Polymarket Long/Short and original units/predicates retain their meaning; American offered prices and separately named fair prices use the established display owner. Every ordinary Arbs filter requires two distinct execution venues. Stop, stale source/reference clocks, unknown models and rule/sizing limitations withdraw positive authority while preserving material explanations.

## Bounds and failures

Per-game compact boards are bounded at 512 KiB; Details/typed Original responses at 8 MiB. The read context admits at most 16,384 typed records and 96 MiB of encoded typed inputs, with occurrence matching capped at 16,000 records/2,048 source members. Native depth hydrates only selected games. Catalogs retain compact metadata, never every game's expanded profile graph. The 500-event slate uses explicit bounded pages described in [the slate contract](comparison-slate-api-contract.md).

HTTP retained reads use two fixed lanes: one ordinary worker and one selected
Original/financial Details worker. Admission is capped at three ordinary and two
selected requests (five total); excess returns HTTP 429 `current_read_busy`.
Each queued request has one second to obtain its lane. A running request has a
five-second server response deadline, below the unchanged 30-second browser limit.
Queue/worker deadlines return HTTP 504 with distinct queue/worker timeout codes.
A disconnect or deadline withdraws adoption; it never releases a live worker's
lane or memory reservation. SQL statements have the remaining worker deadline
and at most one-second lock waits; stage and financial checkpoints cooperate with
cancellation. Runtime Stop polling at checkpoints is throttled to at most one SQL status read per 50 ms; local cancellation/deadline checks remain immediate and final selected authority is rechecked exactly. Noncooperative work remains charged until it actually terminates.
Each lane can contain at most one such worker; abandoned work cannot occupy the
ordinary lane through the selected lane. Shutdown rejects new work, signals live
workers and drains for at most one second. Any still-live daemon worker remains
accounted to the shutting-down app process and ends with process termination;
there is no claim that browser abort forcibly killed a thread.

The existing 768 MiB process guard includes conservative reservations for the
other worker, with selected reservations capped at 128 MiB. Selected work reserves decoded snapshot/capture headroom before
fetching payloads and keeps it until termination. Frame cache limits and cleanup
remain unchanged. A bounded local `/api/boards/read-diagnostics` receipt retains
at most 64 stage summaries, with monotonic admission/queue, snapshot/capture,
bundle, identity, serialization, response completion and cancellation-cleanup
durations. It retains no query identities, credentials or input payloads.
No disk spill, persistent selected report cache or provider dispatch is added.
The 2 GiB SQL allowance and 1 GiB free-disk floor remain.

Schemas: [board v2](contracts/predict-comparison-board-2.schema.json), [catalog v2](contracts/predict-board-catalog-2.schema.json), [Details v2](contracts/predict-board-details-2.schema.json), [typed Original v2](contracts/predict-board-inputs-2.schema.json). Legacy v1 schema files preserve their original protocol meaning and are not ordinary current endpoints.

## Calculation availability

Each financial row and selected result carries `availability`
(`predict-calculation-availability-1`), metric-specific states/reason codes and
`numeric_metrics`. States distinguish `numeric_current`, `numeric_last_known`,
`missing_reference`, `unsupported_inputs`, `calculation_failed` and
`not_evaluated`. Complete EV can remain null beside a numeric conditional EV or
decisive pair margin. See the
[financial contract](requested-trade-financial-contract.md#last-known-evaluation-and-availability)
for evaluation and model applicability.

Board summaries count the evaluated scope before filtering. Shared reasons carry
affected result/game counts and venues. Arbs summaries also count refused leg
candidates, so summary totals can exceed the displayed pair count. Odds has
`not_evaluated` availability because it does not run financial calculations.

`evaluation_frame` preserves original price/reference clocks and ages,
capture/evaluation time and whether source times differ. `calculated_at` is
actual calculation completion; price rows also expose `source_state`. A fresh
quote with an older reference is a last-known dependency set, not evidence of a
simultaneous historical trade. Paused transport and price age do not erase
supported inspection math; positive filtering still requires current eligible
inputs.

Board and Details provide the same server-derived percentage companions for
financial metrics, using deployed capital as the denominator. Clients validate
supplied availability fields and show separate empty states for unavailable,
unevaluated and last-known-only results. Read failure envelopes include structured
calculation-failure availability, except the dedicated Stop response.

Schema: [calculation availability v1](contracts/predict-calculation-availability-1.schema.json).

## Source and estimate independence

Prices expose `observed_depth` (at most eight original ask levels, retained count,
truncation, unknown status and native units), original book/provider clocks,
`source_health`, exact observation revision and an optional gross price comparison
with both original inputs. Gross cents are before fees/sizing/exceptional settlement.
Only matched supported selection/scope identities can compare; ambiguous facts
remain visible with a comparison limitation. Original-price Details echoes the
exact observation and quote revisions.

`collection`, `observation_reasons` and source-only per-price `freshness` describe
source availability. `estimate_availability`, `calculation_reasons` and existing
metric-specific `availability` describe derived results separately. Financial
expiry, policy changes and calculation-worker failure do not mislabel healthy
collection or renew its source clock. An observation-only row has null
`calculated_at`. Original source/receipt clocks remain authoritative on every read.

## Read-time observation and comparison display

Each Odds source price additively exposes `observation_display`. Its disjoint
primary `state` is `current`, `pending`, `last_known` or `unknown`. Unknown or
inconsistent original clocks take precedence; otherwise source expiry, captured
or current source unavailability, Stop and runtime failure produce last-known
prices. A price whose source checks pass but whose stored publication is awaiting
reconciliation is pending. Only both source and publication checks passing allow
current. Original prices remain visible in every state. `source_reason_codes`
and `publication_reason_codes` disclose independent, potentially overlapping
limitations; they do not supply additional observations to a count.

`source_age_seconds`, `received_age_seconds` and `read_at` describe the captured
clocks at the read instant. Either age is null when its own clock is unknown.
`current_until` is the earliest existing source-age/pregame boundary, allowing
lightweight display aging without a provider request or financial calculation.
The original freshness policies and exact source/receipt timestamps are retained.
`captured_source_state`/`captured_source_health` preserve publication-time source
facts; `source_state`/`source_health` describe the current read's source health.
An available heartbeat cannot renew the captured original clock or promote an
input captured while unavailable.

`gross_comparison` preserves the same exact selection and arithmetic: the lowest
compatible other-venue normal-payout price minus the selected price, multiplied
by 100 cents. Equal prices still break ties by exact quote identity. Positive
means the selected price is lower; negative means it is higher, before fees,
sizing and exceptional settlement. `comparison_venue` names the chosen peer.
`inputs` retains exactly the selected and peer native positions, original prices,
quote revisions and original clocks, plus captured source state, freshness policy
and read-time observation display metadata for each input.

`display_status` is `current` only when both captured inputs pass those checks;
unknown input metadata/clocks produces `unknown`, either last-known input produces
`last_known`, otherwise either pending input produces `pending`. An absent or
ambiguous compatible peer remains `unavailable` with its existing reason and
the original observation visible. Numeric availability alone never establishes
currentness. `source_time_skew_seconds` is the absolute separation of the two
original source times, or null when either source clock is absent. Newer peer
data never replaces one input in an already captured comparison frame.

Older retained publications can gain this metadata only from their exact stored
price matching quote identity/revision, original price and original clocks.
Unmatched legacy inputs remain explicitly unknown. This compatibility path never
reads newer ingress prices or recalculates the difference. The slate's additive
`read_at` is the actual read instant; `as_of` remains publication time. Neither
clock nor pagination completion implies source freshness or comparison coverage.
The additive display metadata is scoped to Odds and its frozen original-price
Details frame; compact EV/Arbs responses retain their existing financial payload
shape and 512 KiB per-board bound.

## Current compatible peer

Odds also publishes `current_comparison` separately from `gross_comparison`.
The latter remains the lowest compatible observed price, including historical
quotes. The current metric chooses the lowest normal-payout price among compatible
current other-venue observations, with the same exact quote-ID tie break. The
selected price must also pass its original source-age and health checks. Both
metrics use exact cents and carry the captured native event/market/outcome/side,
selection, original prices, source and receipt clocks, and contract identities.

Unavailable comparisons expose a machine `reason_code` distinguishing missing
peers, noncurrent selected/peer observations, unresolved occurrence/mapping,
unsupported native prices and unsupported/conflicting peer matching. Source-age,
health and mapping diagnostics remain in `reason_codes` even when no captured
pair exists. Reading or aging an unavailable result retains those reasons.

Native comparison support is driven by reusable venue/series/market-type rules
and structured source facts across NFL, NCAAF, NBA, NCAAB, MLB and NHL, for full-game
winner/moneyline, spread and total contracts. No ordinary event ID is an admission
list. Both ingress and existing SQL reprojection use the same resolver. An
observation's `same_outcome` contains a supported exact key or a precise reason and
`missing_fields`. Its key includes occurrence/league, family/period, scoring scope,
canonical score predicate, equality treatment and compatible normal-payout units.
Raw source lines, native sides and wording remain separately inspectable. Native
`not_win` remains explicit. Unsupported metadata withholds only the affected
comparison and keeps the source observation visible.

Odds rows include `event` sport/league/title/start and `market` family, period,
period meaning and original line. Each frozen comparison input retains the shared
same-outcome identity and original market context. Local league, market, period,
game and search filters change only displayed rows and counts. Coverage separates
unique market outcomes, underlying cross-source pairs, signed directions and
retained observations; it never substitutes lowest-observed history for current
support. Same-team games remain distinguished by occurrence and scheduled start.

`metric` distinguishes `lowest_current` and `lowest_observed`.
`selection_valid_until` bounds current-peer selection by candidate source/receipt,
source-age and pregame boundaries. Crossing a candidate eligibility boundary
requires background reselection; a read or held Details frame keeps its captured
pair and becomes pending or last-known. No page read chooses a newer comparator.
The Details takeaway derives its higher/lower/equal direction from the exact
signed numerator, labels cents explicitly, and ages the captured comparator.

Native scoring scope is attached from that market's stored facts and applicable
source/type rules. Unknown or contradictory overtime, innings, shootout, predicate,
line or equality facts remain explicit with a specific reason and `missing_fields`.
Exact historical exception reviews remain bounded to their own retained evidence.


## Bounded ordinary Odds payload

`prices` contains each exact observed source frame and its separately captured
current-peer/lowest-observed comparisons once. Odds `rows` is a compact local
index: `price_ref` resolves to that response's `prices[].quote_id`, with the same
quote revision, venue, selection and market/period. It adds no observation or
comparison and cannot select a different frame. Clients reject crossed, duplicate
or omitted references. Financial rows retain every calculation and use an exact `price_ref` when their original source frame equals the same-response price. Differing historical source frames remain explicit.
Older complete Odds rows remain readable for compatibility.

Compact rows omit repeated full occurrence-audit event copies and governing-rule
evidence. Occurrence status/conflicts, immutable revision, original native IDs,
prices, predicates, lines and clocks remain in the board. Both frozen comparison
inputs retain `native_contract_summary` with native wording and explicit predicate/equality/scoring facts, plus the full contract identity. Full
source and scoring evidence remains available through the exact local Original
inputs endpoint. The 512 KiB per-board limit and local-read boundary are unchanged.


Frozen input encoding is `same-board-price-refs-1`. Each available comparison's
`input_refs` identifies two `prices` entries by quote ID and revision; the wire
`inputs` array is empty. Clients resolve these exact same-response entries into
detached input snapshots before rendering. Reads and held Details never bind a
reference to a later response. `native_wordings` pools complete original wording
values, and each price's native summary maps original field labels to pool indexes
in `wording_refs`; every description is retained without truncation, including
unpaired or unsupported observations. Original native predicates, equality/scoring
facts, prices and clocks remain exact. Full occurrence audits remain available in
the local typed source-evidence endpoint. Financial `price_ref` values reuse an original only when its revision, selection, source identity, original price and clocks all agree. Clients restore those exact scalar inputs locally before display. Repeated book audits remain in Odds and the typed Original evidence endpoint.
