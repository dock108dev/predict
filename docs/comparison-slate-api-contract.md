# Current comparison slate API v2

`GET /api/boards/slate?view=odds|ev|arbs&filter=positive|all|hedges` returns `predict-comparison-slate-2`. Each returned board uses the background shared default policy. `requested_policy` records settings reserved for selected Details; `sizing_scope=shared_default_selected_details` makes that distinction explicit. No provider requests, whole-slate finance or account mutations occur in the read. [Latest-result contract](latest-board-results.md).

The reader returns the complete sorted upcoming occurrence catalog, with at most 500 games, and one bounded page of boards/errors. `offset` defaults to 0 and must be 0–499; `limit` defaults to 25 and must be 1–50. Each complete encoded page, including catalog, summaries, errors and storage metadata, is bounded at 8 MiB. `limit` is an upper bound: the server selects a contiguous prefix that fits this byte bound. A nonempty page advances by at least one game; an individually unrepresentable game/envelope is explicitly refused, never omitted. The catalog is ordered by scheduled start then canonical game key. Every occurrence in that page has exactly one board or explicit error; there is no silent omission.

The response carries:

- `games`: the entire bounded catalog, with original participants/source members and current input revisions.
- `boards`, `errors`: only the requested page's occurrences.
- `coverage`: `{total_games, offset, limit, returned_games, next_offset, complete}`. `next_offset` is null only at the end; `returned_games` includes explicit per-game errors.
- `read_revision`, `epoch`: captured coherent source/receipt/native-depth/engine and availability identity, plus the reset generation.
- `read_token`, `read_expires_at`: opaque process-local captured-read capability and its initial inactivity expiry. It authorizes only continuation of this bounded local read.
- `read_at`: original database capture instant, identical across pages; `as_of` remains the stored publication time. Neither the token nor a page renews an original source clock. The browser continues aging observations from their original clocks.
- `bounds`: `{maximum_games: 500, maximum_page_games: 50, maximum_bytes: 8388608}`.
- Exact selected policy, source/read instant, Stop state, storage availability and `provider_requests: 0`.

First-page callers omit the token and start at offset zero. Subsequent pages submit both `read_token` and `expected_revision`, with the same policy, view, filter and requested page limit. Continue at the returned `next_offset`, not `offset + limit`. Pages come from the same detached PostgreSQL frame; ordinary new books and background publications do not invalidate it. A fresh offset-zero read captures later published games and prices. An offset without a token, crossed context, changed revision, expired/evicted token or lost authority returns an explicit HTTP 409 refusal. A token can open exact captured Details; it never authorizes replacement inputs.

Settings or view changes cancel the previous client collection. The browser validates token, expiry, read instant, revision, epoch, catalog membership, policy, quote/context identity and complete board/error coverage before adopting its bounded aggregate. No partial collection replaces a previously complete view. The complete read retains its 80 MiB wire budget; at most 500 progressing pages can cover the 500-game catalog. Empty catalogs use one complete empty page. Recoverable frame failures receive one fresh local attempt. If that recovery also fails, polling stops until the user chooses Reload results, preserving local filters and the matching row position where possible. Prior complete values retain the unverified-freshness warning if recovery fails. Reads and recovery do not dispatch providers or calculations.

The app retains at most four pagination, displayed or selected captures and 64 MiB in aggregate, including conservative container/accounting allowances. Each token has a 120-second inactivity lease. Successful forward pagination renews that lease; replaying the same or earlier offset does not. The initial `read_expires_at` and captured read/source clocks stay fixed across pages. New captures retire completed/displayed frames within the same count/byte bounds; if active pagination or selected Details still leave insufficient room, the new capture is refused rather than destroying an active read. Continuation of an expired or evicted token is explicitly refused. Completion strips page boards and validation proofs, retaining bounded immutable selection evidence. Visible completed lists and opened selections renew their cache leases, never source eligibility. Closing Details releases its selected token with `DELETE /api/boards/read-lease?read_token=…`; this removes only transient read evidence. Cleanup runs on access and every five seconds, and app shutdown clears all captures. The existing 768 MiB process guard can refuse capture/page allocation without increasing its allowance. Only one immutable serialized selected view is retained per capture; page envelopes are transient and no database transaction stays open between HTTP requests.

A lightweight committed authority check runs before continuation and after rendering. Epoch, runtime identity/liveness, explicit Stop/recovery controls, configuration, source availability, worker authority and policy/engine/matching bindings can revoke the frame. Routine books, receipts, diagnostic wording and publications cannot. A fresh read after withdrawal carries the existing last-known/unavailable semantics; a prior token cannot restore eligibility.

A complete 500-game request uses ten pages at limit 50, with the unchanged 80 MiB total-read ceiling. This is a working-data capacity bound, not a count of available live NFL games. Resource checks retain the ordinary process/storage guards. The background owner finishes SQL capture and selected depth hydration before finance, then publishes bounded compact results. No expanded full-slate report graph or settings cache persists. Odds/EV/Arbs pages read those stored results and do no financial evaluation.

Schema: [slate v2](contracts/predict-comparison-slate-2.schema.json). Individual board and selected Details semantics follow [the board contract](comparison-board-api-contract.md).

## Availability summaries

Page-scoped `availability` reports stable state counts, total/numeric/current/
positive results, an outcome and shared causes with affected result/game counts
and venues. Counts cover inspected results and refused candidates before
Positive/All filtering. Errors carry structured `calculation_failed`
availability. `evaluated_no_positive` differs from `not_evaluated`, `unavailable`,
`partial` and `last_known_only`; an unevaluated slate cannot claim that no positive
EV was found.

The browser validates supplied availability fields and combines all
page/board/error summaries for the final coherent slate, including an all-failed
scope. It publishes only after revision and complete-coverage checks pass.
Individual row and evaluation-frame meanings follow the
[board availability contract](comparison-board-api-contract.md#calculation-availability).

Odds observation counts use shown locally filtered boards and their typed prices,
separately from full admitted catalog game totals and returned catalog observation
totals. Each observation has one primary `observation_display` state; overlapping
reason counts are disclosed separately. Per-venue denominators distinguish
observations from matching games with observations. Missing boards retain their
explicit errors and unknown observation counts. Reference originals and financial
comparison counts are separate units. `coverage.complete` means requested pages
were retrieved, and never asserts current sources or available comparisons.

Odds also shows displayed-scope comparison coverage from the same captured price
rows and current-pair aging rules: games with a current comparison, distinct team
win outcomes with a current cross-source pair, and retained price observations.
An unordered underlying quote pair is counted once; its two signed directions do
not double outcome coverage. Local search/game filters and aging update this
summary without a new provider request or peer selection. Disclosure separates
stale inputs, missing peers, unsupported/conflicting matching and pending
publication, retaining specific reasons. These are observed current counts,
separate from the registry's conditional supported-outcome capacity.

## Raw pagination supersedes the Odds slate consumer

The ordinary Odds browser now uses `/api/raw/prices`, with SQL-snapshot pages of
50 books, independently of this derived slate's 500-game and whole-game response
bounds. Financial consumers retain the v2 slate contract. See the
[raw read and full-dataset verification contract](raw-prices.md).
