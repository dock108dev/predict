# Selected-unit pregame board responses

Request an ordinary board with
`GET /api/comparison-current?layout=desk&phase=pregame&ranked=1&summary=1&unit_usd=25`.
The `predict-pregame-board-1` response distinguishes `unit_needed`,
`valuation_pending`, `ready`, and `read_failed`. A ready board has a `populated`
or `empty` `board_state`. A complete board may report `replacement_pending`
while calculations run for the same amount.

Pass the returned `board_cursor` with the same amount and filters for later
pages. A `page_changed` response starts pagination again. For exact inspection
pass `id`, `quote_key`, `expected_member`, `unit_usd`, and `board_id` to
`/api/comparison-current/selection?layout=desk&phase=pregame`. A superseded
member reports `unit_publication_changed`.

- `saint-marys-25-board.json` and `saint-marys-12-board.json` come from a
  synthetic admitted fixture with authored reference and placement terms.
- `saint-marys-25-selection.json` shows the exact clicked offer and its
  same-bet comparison, including a qualified negative fixture offer.
- `retained-novig-25-board.json` came from a disposable replay of four retained
  events. The board has zero qualified rows. `retained-novig-offers.json`
  records the 18 ordinary Browse and inspection results with verified $0.00
  fees, original clocks and the specific blockers.

The board and its exact selection include opaque publication and member
identifiers from the runs that produced each example.
