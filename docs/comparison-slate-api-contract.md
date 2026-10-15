# Current comparison slate API v2

`GET /api/boards/slate?view=odds|ev|arbs&filter=positive|all|hedges` returns `predict-comparison-slate-2`. Existing exact calculation settings apply to every returned board. No provider requests, financial/account mutations or saved sports calculations occur.

The reader returns the complete sorted upcoming occurrence catalog, with at most 500 games, and one bounded page of boards/errors. `offset` defaults to 0 and must be 0–499; `limit` defaults to 25 and must be 1–50. Each page is bounded at 8 MiB. The catalog is ordered by scheduled start then canonical game key. Every occurrence in that page has exactly one board or explicit error; there is no silent omission.

The response carries:

- `games`: the entire bounded catalog, with original participants/source members and current input revisions.
- `boards`, `errors`: only the requested page's occurrences.
- `coverage`: `{total_games, offset, limit, returned_games, next_offset, complete}`. `next_offset` is null only at the end; `returned_games` includes explicit per-game errors.
- `read_revision`, `epoch`: current coherent source/receipt/native-depth/engine and availability identity, plus the reset generation.
- `bounds`: `{maximum_games: 500, maximum_page_games: 50, maximum_bytes: 8388608}`.
- Exact selected policy, source/read instant, Stop state, storage availability and `provider_requests: 0`.

First-page callers capture `read_revision`; subsequent pages submit `expected_revision`. A changed revision returns HTTP 409 `current_slate_changed`, so clients discard the partial collection and retry from a fresh boundary. Settings or view changes cancel the previous client collection. No partially assembled slate replaces a previously coherent view. The browser validates every page, catalog membership, policy, quote/context identity and complete board/error coverage before publishing its bounded aggregate.

A complete 500-game request uses ten pages at limit 50. This validates a working-data bound rather than claiming 500 live NFL games. Resource checks retain the ordinary process/storage guards. SQL capture and selected native-depth hydration finish before financial calculations; no expanded full-slate report graph or settings cache persists. Odds pages omit financial calculation work, while EV/Arbs pages call the existing financial owners.

Schema: [slate v2](contracts/predict-comparison-slate-2.schema.json). Individual board and selected Details semantics follow [the board contract](comparison-board-api-contract.md).
