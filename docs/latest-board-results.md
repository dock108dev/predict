# Background observations and estimate results

The independent data runtime owns `LatestBoardOwner`, with separate bounded
observation and optional-estimate workers. Each polls committed current-row
identities every two seconds; slow financial work cannot block subsequent source
publications. Pages read PostgreSQL; filters, paging, polling and
original-price Details dispatch no providers and perform no financial evaluation.
Selected financial Details may still calculate one requested amount through the
existing owners. The shared policy never causes request-side slate calculation.

## Independent source publication

Each admitted upcoming NFL full-game winner occurrence first uses the profile-free
catalog and existing source-price validation. Selected depth hydration is bounded.
Optional benchmark parsing, financial discovery/profile attachment, context
identity and calculation run separately. Missing/malformed benchmarks and failed
finance leave valid native prices, exact source IDs, revisions, clocks and retained
asks visible. A financial error publishes explicit estimate-unavailable reasons;
invalid source facts remain an explicit observation error, rather than checked zero.

Migration 015 provides one replaceable status row and at most 500 game rows.
Migration 016 permits a null calculation clock when no calculation succeeded.
Each game retains three compact responses, capped at 2 MiB per row and 64 MiB
in total. Each price retains at most eight ask levels, total retained level count,
native units, book/provider clocks and truncation/unknown-depth status. Expanded
financial states, raw bodies and history are not retained. Absent games are removed
from latest publication; protected business tables have separate owners.

Source-only observation contexts bind epoch, exact dependencies, engine and source
applicability. Financial contexts additionally bind policy and financial/model
applicability. Original-price Details checks the observation context and echoes
quote and observation revisions; it does not require financial profiles. Any
late dependency/runtime change refuses the complete Details frame.

A rejected catalog occurrence cannot stop publication for other occurrences.
The background-only tolerant catalog records at most 500 bounded
`catalog_errors` with source members and `observation_invalid`. A prior failed
occurrence remains an obsolete stored frame when no valid current occurrence
already covers its members; its binding/dependencies still withdraw eligibility.
New valid occurrences keep publishing. `scope_complete` remains false while any
catalog failure exists. Raw schedules/contracts are never edited or guessed to
make publication succeed. Selected reads keep strict validation and refuse the
conflicting occurrence. Background shutdown cooperates at catalog, occurrence,
financial and publication boundaries within the existing five-second drain.

## Selected Original read ownership

Exact Original and selected financial Details share one bounded worker; ordinary
stored slate/catalog reads have an independent bounded worker. Admission remains
five total, split two selected/three ordinary, with one-second queue and
five-second worker response deadlines. Cancelled or expired work retains its
lane and conservative memory reservation until its thread actually terminates.
A 128 MiB selected reservation cap and the shared 768 MiB process guard bound
parallel memory; no unbounded executor or hidden retry is introduced.

Selected snapshots decode only the complete relevant matching neighborhood.
Global small event identities detect new possible peers; contracts, benchmark
inputs, native books/receipts, source health and operational controls bind the
selected signature before/after detached work. Unrelated updates do not cause
refusal. SQL Stop polling at checkpoints is bounded to 50 ms intervals, with
immediate local cancellation and an unconditional final Stop/authority boundary.
See [read bounds and diagnostics](comparison-board-api-contract.md).

## Clock and status meanings

Source freshness is evaluated on each read from original source/receipt clocks,
source state and declared source-age limit (900 seconds when none is supplied).
Native declared 30-second limits retain that meaning. Future/unknown clocks,
source failures, Stop and pregame end remain explicit last-known limitations.
Book confirmation and heartbeat never renew the original source clock.

`observation_display` gives each observation one primary state: current, pending
publication, last-known or unknown/unavailable. Original-clock/source limitations
and publication reasons are separate arrays; reasons can overlap and are never
added to primary-state totals. Pending reconciliation alone does not mean the
source clock expired. Source health may be available while a captured price is
older or awaiting a valid publication.

`observation_valid_until` contains source boundaries; `valid_until` contains
financial authority boundaries. Passing a financial/model/reference boundary,
changing calculation policy or losing the calculation worker withdraws affected
metrics without changing source freshness or claiming collection stopped.
`collection` and per-price source health remain separate from
`estimate_availability` and metric-specific financial `availability`.

Price differences use the existing exact normal-payout conversion only for matched
supported identical selections/scope across venues. They are gross cents before
fees, sizing and exceptional settlement, with both original inputs disclosed.
The established comparator remains the lowest compatible other-venue price,
including historical quotes, with the existing quote-ID tie break. A separate
`current_comparison` chooses the lowest compatible current other-venue price and
also requires the selected observation to be current. Both exact differences and
frozen inputs survive read-time aging. Candidate source/receipt, freshness and
mapping boundaries require background reselection; reads never substitute a peer.
Comparison status uses both captured inputs and their existing source policies,
current source health and publication authority. It cannot become current merely
because a numeric difference exists. Source-time skew is the absolute separation
of the two original source clocks, or unknown when either clock is absent.
YES/NO and Long/Short remain separate native positions. Ambiguous identity leaves
the comparison unavailable while retaining each source price. Complete EV,
conditional EV and covered-outcome economics retain their existing stricter owners;
unknown costs/probabilities/settlement inputs are never defaulted to zero.

Read-time `observation_display` separates source reasons from publication reasons
and gives each observation one primary current, pending, last-known or unknown
state. Source expiry/Stop/unavailability and unknown clocks take precedence over
pending reconciliation; a still-valid original clock awaiting publication is
pending without a false `source_expired` reason. Captured source state/health and
read-time source health are separate. Relative ages and the existing policy's
next currentness boundary are additive display metadata, never replacement clocks.

Both original gross-comparison inputs are independently aged on every read.
The exact difference and deterministic comparator remain unchanged when either
input becomes last-known, pending or unknown. Actual source-time separation is
disclosed, including unknown skew for a missing source clock. Compatibility
metadata for an older publication uses only its exact captured price, never a
newer peer. Source-only Odds status is independent of estimate/model expiry.
See the [API display contract](comparison-board-api-contract.md#read-time-observation-and-comparison-display).

## Publication and reuse

Internal `predict-latest-board-3` publications carry bounded committed dependency
manifests. Own source/receipt/book facts govern each observation. Matching
neighborhoods and compatible other-venue candidate rosters govern each comparison,
including candidate additions/removals and metadata changes. Unrelated games,
opposing outcomes and routine source-status clocks do not revoke unchanged
observations. Source health remains material. No freshness threshold is relaxed.

Publication holds current ingress/runtime locks and checks each game's captured
dependencies before committing it. Relevant late work loses authority; unrelated
games can still publish. A slower estimate pass cannot overwrite a newer source
frame. A source-only publication commits before optional discovery and estimation,
and time-only boundaries also trigger source reselection. Independent workers
allow that process to continue while estimates are slow.

Epoch, configuration, runtime identity/liveness, explicit Stop and observation
worker health invalidate source authority immediately. A separate observation
binding includes matching/normalization algorithms. Each native observation and
potential same-predicate peer additionally binds only its own registry target and
applicable retained governing rule. Registry-only changes wake background
reconciliation and change read identity without withdrawing unrelated games.
Changed matching cannot leave an old pair labeled current. Optional worker,
policy and full-engine changes withdraw financial authority separately. Original
receipt clocks remain relevant to their own captured observation; routine status
receipt/heartbeat clocks cannot renew a source price or invalidate the whole slate.

Per-game economic revisions include the selected dependencies and applicability.
Unchanged games retain their original result revision and calculation time,
including when a conservative deadline is advanced without changed economics.
A failed calculation can be retried by the background owner; page operations do
not wake it. Missing database results stay unavailable. A stale/dead runtime keeps
retained observations inspectable without claiming current collection or an
acknowledged explicit Stop. Multi-page reads pin one bounded detached capture; later books and publications are visible in a fresh read. Lost runtime authority still refuses continuation. See the [slate contract](comparison-slate-api-contract.md).

## Ordinary Odds and selected Details

Odds keeps all observations available by default. Its summary separates matching
games from the full admitted stored catalog, shown observations from gross
comparisons, and per-venue observation totals from games with observations.
The short current-comparison summary counts games, distinct team-win outcomes and
retained observations within the displayed scope. Its disclosure counts underlying
current cross-source pairs once across signed directions and separates stale,
missing-peer, unsupported/conflicting, pending and unknown causes. The same frozen
inputs and aging helpers govern rows and counts. Detailed observation/source
coverage remains in a separate disclosure.
Reference originals are counted separately. Every shown observation belongs to
one primary state; expandable reason counts may overlap. A missing board remains
an explicit error with unknown observation counts. The summary includes its read
time. Page retrieval completion only confirms that
the requested boards/errors were retrieved.

Compact differences name the other venue and comparison status; the current-peer
metric is labeled separately from the lowest observed price metric. Original-price
Details shows selected and comparator native prices/sides, their exact original
clocks, human ages, source state, skew and subtraction direction. Positive means
the comparator costs more; negative means it costs less, before financial costs.
Exact rational cents and raw JSON remain inspectable. Optional estimate messages
use one short explanation with expandable exact reason codes.

A short takeaway above the supporting details describes whether the selected
price is higher/lower/equal, names the comparator, labels cents and discloses its
captured age/status. It uses the exact signed difference and the same frozen pair.

While Details is open, its captured pair remains fixed. Lightweight text updates
advance relative ages and conservatively age status past the supplied original
policy boundary; they perform no fetch or financial calculation. Close and reopen
the price to select newer observations. Source health displayed on that retained
frame describes its last read, not an unseen live health refresh.
