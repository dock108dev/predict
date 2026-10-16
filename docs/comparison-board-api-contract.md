# Current comparison board API v2

The ordinary comparison reader uses `CurrentRowStore`: current event/source mappings, exact native selections, current offers and shared native depth. It reconstructs transient financial inputs through the existing shared profile, benchmark, single and pair owners. It neither reads nor writes permanent envelopes, projections, snapshots, calculation reports or publication attempts. A successful read issues no provider requests and changes no account, quota or due state.

## Routes and identity

| Route | Current response |
|---|---|
| `/api/boards/games` | `predict-board-catalog-2`: all admitted upcoming NFL/full-game winner occurrences, maximum 500. Capacity overflow fails explicitly. |
| `/api/boards/odds`, `/ev`, `/arbs` | `predict-comparison-board-2`: exact `game`, policy, current typed prices, separate two-sided benchmark and compact financial rows. Odds does not calculate financial scenarios. |
| `/api/boards/details` | `predict-board-details-2`: exact `game`, expected `context_id`, policy, and exactly one `quote` or `pair`. Only the selected comparison expands rich financial scenarios. |
| `/api/boards/inputs` | `predict-board-inputs-2`: exact `game`, expected `context_id`, policy and `quote`; allowlisted typed event/selection/source/original-price/clock/native-contract/provenance/benchmark evidence. No provider bodies or envelope graphs. |
| `/api/boards/history`, legacy `result_id` or explicit history requests | HTTP 410 `sports_history_unavailable`. Select a current comparison. |
| `/api/stored/*` | Explicit HTTP 410 retirement; no ordinary archive fallback. |

Every board carries `calculation_context = {context_id, epoch, dependency_revision, policy_revision, engine_binding}`. Each financial row's Details reference repeats `context_id`, policy revision and exact quote/pair ID. Each displayed price's `inputs_identity` repeats game, input version, exact quote ID and context ID. The current v2 protocol does not repurpose legacy result or snapshot IDs.

The context binds the current store reset epoch, canonical game, source/native-book dependencies (including bid-only book changes), original receipt facts, occurrence matching, policy, financial/model/source engine files and applicability boundaries. A receipt-only observation may invalidate a context; it never renews an unchanged source-price timestamp. Unrelated game updates do not invalidate a selected game's context. Shared definitions are built from their versioned owners; no settings-variant report graph is cached or persisted.

Details and typed Original reads capture current rows and compare the required expected context. Changed, removed or temporally expired inputs return HTTP 409 with `current_inputs_changed_or_removed`; an absent selected quote returns `current_selection_removed`. The client replaces the entire dialog on failure. It never attaches new prices or freshness labels to old financial totals. Captured prices, profiles and financial results belong to one detached coherent frame even if ingress changes afterward.

## Financial meaning and display

Policy accepts exact `amount`/compatible `ceiling`, one buffer rate, sizing mode and explicit supported benchmark/method. Conflicting settings reject. Defaults retain requested $1,000 funding and one 0.005 haircut on deployed capital. Complete EV, decisive conditional EV and opposing pair margins remain separate, with exact quantities/units, modeled fee and settlement assumptions and deployed-capital denominators. Pinnacle remains reference-only; supported alternative benchmarks are explicit, with no substitution for an absent selected two-sided reference.

Observed prices remain visible independently of financial eligibility. Native Polymarket Long/Short and original units/predicates retain their meaning; American offered prices and separately named fair prices use the established display owner. Every ordinary Arbs filter requires two distinct execution venues. Stop, stale source/reference clocks, unknown models and rule/sizing limitations withdraw positive authority while preserving material explanations.

## Bounds and failures

Per-game compact boards are bounded at 512 KiB; Details/typed Original responses at 8 MiB. The read context admits at most 16,384 typed records and 96 MiB of encoded typed inputs, with occurrence matching capped at 16,000 records/2,048 source members. Native depth hydrates only selected games. Catalogs retain compact metadata, never every game's expanded profile graph. The 500-event slate uses explicit bounded pages described in [the slate contract](comparison-slate-api-contract.md).

One heavy HTTP read runs at a time, with at most four waiting requests; excess requests return HTTP 429 `current_read_busy`. A disconnected request retains its slot until its worker ends. Cooperative financial cancellation stops active work when Stop arrives. SQL capture and selected depth hydration finish before finance, releasing the transaction and ingress lock. Read failures are explicit HTTP 409 or database-unavailable HTTP 503, with no disk spill, persistent report cache or retry archive. Collection is bounded by a 2 GiB SQL allowance, a 1 GiB free-disk floor and a 768 MiB process guard.

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
