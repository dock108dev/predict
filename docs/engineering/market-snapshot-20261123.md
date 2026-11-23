# Main market snapshots — active implementation

Owner assignment: [implementation plan](predict-market-snapshot-implementation-plan.md).
Baseline inspected: `main` at `3be036a`; only the owner-supplied plan was untracked.
All implementation stays in this checkout. Existing controls, accounting, data,
frozen evidence, credentials and remembered login remain protected.

## Milestone and verification contract

The owner needs independent game/market rows, one exact eligible headline offer,
one-click calculation inspection, and authentic acquisition identity throughout.
Review is prevented today by the game-wide maximum and the lack of a durable
current comparison membership contract. Those are assigned engineering work.

The 600-second inclusive whole-input receipt span is an explicit owner rule,
combined with identical logical pull identity. It is not a new source-age rule.
The normal two-minute CI/CD lane is an owner requirement implemented in
`.github/workflows/ci.yml` and documented in `docs/CI.md`; mandatory validation,
proxy checks, image identity and health remain required. A schema migration uses
the existing guarded backup/migration maintenance path before fast release.

Earliest sufficient stopping condition: integrated acquisition, SQL/API and UI
checks cover the plan's state transitions; normal CI/deployment passes; the
installed public site completes the exact-offer journey with history, export,
Back/reload, checkpoint states, arbitrage, Settings and legacy links. An unavailable
live edge, outcome or future T−10 is an observation limit, not a reason to wait or
start new polling. No additional soak, profitability target or sample gate applies.

## Findings and choices

- Installed baseline verified on `https://predict.dock108.dev`: one game row
  combines families and shows a game-wide best EV. Different source timestamps
  alone do not establish cross-pull mixing.
- Settings `received_at` and `last_book_receipt_at` come from diagnostic quotes
  and source-state summaries in `app/collection/current_admin.py`. SGO's SQL
  storage mode need not retain prices there. Add an accepted-page receipt clock
  separately from service availability; failed HTTP/account reads are not valid
  price receipts.
- Backend/frontend work shares `market_pull` and `market_pull_scope`, with frozen
  single-pull inputs and a stable start ordering. Unproven legacy evidence stays
  inspectable under its original provenance, outside the eligible current board.

- Official [event endpoint](https://sportsgameodds.com/docs/endpoints/getEvents)
  defines the page limit and cursor over events; the
  [batch guide](https://sportsgameodds.com/docs/guides/data-batches) documents
  redundant cursors and moving event ordering. An authentic retained single-event
  checkpoint carried `next_cursor_present=true`. Therefore returned exact
  single-event scope closes the event's requested odds surface without another
  paid empty-page fetch. Broad discovery retains its page chain and uncertain
  omission authority. Requiring no cursor for this single-event case was an
  engineering inference, not an owner gate, and has been removed.
- Measured retained source evidence: six canonical checkpoints ranged from
  195,532 to 17,795,847 bytes. One 7,889,531-byte checkpoint with 245 offers and
  771 reference observations compresses to 424,357 bytes at zlib level 6. Store
  full evidence once per pull, separate from compact per-family ranking facts.
  Existing retained allocation was 72,727,358 of 134,217,728 bytes at inspection;
  the 128 MiB cap and explicit refusals remain unchanged.

## Integration and checks

In progress. Final evidence will distinguish disposable fixtures, retained-data
integration, installed site observations and hosted CI/deployment.

### Integrated local result

- Normal affected check selection passes: 374 portable tests + 41 subtests;
  47 disposable PostgreSQL tests + 6 subtests. Lint, workflow syntax and secret
  scanning passed. Reports are retained under
  `test-results/fast/1795453998584408000-local/` (ignored local evidence).
- The first integrated SQL run exposed an obsolete working-table-only arb seed;
  the fixture now publishes an authentic frozen acquisition. It also exposed a
  real benchmark bug: raw quotes lack normalized receipt provenance. Paired book
  benchmarks now use the tagged normalized reference inputs; selected-book and
  explicit historical reference-comparison assertions pass.
- A subsequent export check caught PostgreSQL `SUM(bigint)` returning Decimal
  for allocation accounting. The owning status boundary now emits integer bytes;
  exact experiment export/offline reproduction passes. Both failing runs remain
  in `.local/market-snapshot-20261123/fast-checks-first.log` and `fast-checks-second.log`.
- 58 maintained documents pass the documentation-link checker after registering
  the existing personal workspace guide in its maintained catalog.
- Genuine retained-data linking matched one unique resolved ledger reservation,
  preserved all 132 numeric EVs in 245 offers and reproduced those results offline.
  Full recovery remains an installed maintenance operation, not browser behavior.

Deployment and installed public-site acceptance are pending below. No owner
review is requested at this intermediate checkpoint.
