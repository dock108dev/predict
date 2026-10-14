# All-game comparison slate

`GET /api/boards/slate` supplies Odds, EV and Arbs through one bounded SQL read. The ordinary screens default to **All games**. Team search, an optional game filter and result sorting operate on the returned slate; they do not request each game separately.

## Request

Supported query fields are `view=odds|ev|arbs`, `filter=positive|all|hedges`, `amount`, `ceiling`, `buffer`, `sizing_mode`, `benchmark_venue` and `benchmark_method`. Defaults are `view=odds`, `filter=positive` and the existing server policy. The ordinary client sends requested-trade sizing, its applied amount/buffer and the explicitly selected benchmark. Amount and buffer remain exact policy inputs; `buffer` is a rate, so a displayed 0.5% sends `0.005`.

`game`, `result_id`, `quote`, `pair`, `history`, unknown fields, duplicate fields and invalid settings are refused before SQL. Details, originals and history continue to use the existing per-game endpoints documented in [the board API contract](comparison-board-api-contract.md).

## Response

The version is `predict-comparison-slate-1`:

```json
{
  "version": "predict-comparison-slate-1",
  "view": "arbs",
  "filter": "all",
  "policy": {},
  "games": [],
  "boards": [],
  "errors": [],
  "stopped": false,
  "as_of": "2026-10-14T12:00:00+00:00",
  "bounds": {"maximum_games": 200, "maximum_bytes": 8388608},
  "provider_requests": 0,
  "storage": {}
}
```

Here `{}` denotes the existing complete policy or pipeline-status object, not an omitted identity. `games` contains the existing canonical catalog entries: exact game key, title, participants, kickoff, membership and match evidence. Known kickoffs must be later than the read instant; unknown kickoffs remain unknown. Games are ordered by kickoff and exact key.

Each game has exactly one nested `predict-comparison-board-1` response in `boards`, or one entry in `errors` of the form `{"game_key":"KEY","reason":"game_inputs_unavailable"}`. A game-specific input failure preserves healthy independent boards and keeps the failed occurrence visible. Nested boards retain their own policy, input version, original prices, selected benchmark, result/snapshot identities, financial metrics and freshness. The client validates each nested board against its own game and the applied policy. It binds Details to the clicked row's game, participants and immutable result identity.

`as_of` is the slate's read instant. It does not renew a source quote, benchmark, model or saved result. Original clocks and dependency-local freshness remain on each nested board and row. The coverage summary counts games with retained prices per venue across the full slate; it does not claim that every venue offers every game. A genuinely absent ProphetX, Kalshi, Polymarket US or Pinnacle input stays unavailable. A missing selected two-sided benchmark is never replaced implicitly or displayed as zero EV.

## Saved results and local work

A result calculated by a predecessor engine stays inspectable under **All comparisons**, with changed-engine/dependency reasons and its original result-as-of. Engine identity is checked against the same shared read context used for catalog, member bundles and saved results. Changed or stale results cannot qualify as current positive opportunities. Pending calculations retain original prices and any prior saved result with an explicit label. Complete EV, conditional EV and scenario margins retain their separate meanings.

`storage` is the existing database pipeline status, including its state, error, backlog and pending-work counts when available. Ordinary UI labels storage refusal as paused saving, including a storage-limit message when applicable; it does not leave a refused save labeled as an active calculation. Admin retains the detailed status.

Reads may enqueue missing or superseded results in the existing bounded **local calculation queue**. Duplicate descriptors coalesce, existing queued work counts toward capacity, a closed queue refuses work, and the scheduler stops at the first capacity refusal. A cursor gives later visible games a turn; a still-owned request whose changing inputs refuse publication moves to the end of the existing queue with its generation unchanged. This does not acquire provider data, force collection, mutate quota/holds or change due times. HTTP 202 indicates pending saved calculations; HTTP 200 indicates no pending calculations in this read.

The slate permits at most 200 games and 8 MiB for the final serialized response, including appended storage metadata. Each existing compact board retains its 512 KiB bound. Capacity refusal returns a clear 409 error without silent row truncation; database unavailability returns 503. No provider fallback occurs.

The browser schedules one next saved read after the prior read completes: two seconds while calculations are pending, ten seconds when stable, stopped or saving is unavailable. Failed reads return to the slower interval and stop after the existing finite failure limit. Original-input dialogs pause polling until closed. A canceled or delayed timer cannot start an overlapping read; explicit settings changes still cancel obsolete requests. These intervals do not change source freshness or provider schedules.

The response schema is [predict-comparison-slate-1](contracts/predict-comparison-slate-1.schema.json). Cross-game and settings associations additionally require the executable server/client guards; JSON schema alone cannot establish those relationships.

Portable qualification: `tests/test_comparison_slate.py`, `tests/test_comparison_slate_fairness.py`, `tests/test_slate_ui.cjs`, `tests/test_slate_polling.cjs` and the fully intercepted `browser_tests/test_slate_browser.cjs`. These tests use authored/mocked data and establish no installed or owner acceptance claim.
