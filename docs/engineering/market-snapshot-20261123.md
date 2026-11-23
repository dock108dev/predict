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

Verification below distinguishes disposable fixtures, retained-data integration,
installed site observations and hosted CI/deployment.

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

Deployment and installed public-site evidence follow below.

### Installed integration follow-up

Migration116 applied through `deploy/release.sh` full maintenance protocol using
all three validated/published role images from CI45225548056. Retained database
backup: `/srv/predict/backups/before-migration.iefDmdI5.dump` (71,669,951 bytes).
All configured roles were healthy after the guarded rollout.

CI45225548056 and45226141268 passed their selected tests, proxy validation and
image verification/publication, then correctly refused handoff because less than
55 seconds remained within the existing110-second execution budget. Their release
metrics report59.638 and63.493 seconds before refusal. Warm cached images alone
did not resolve the issue: second-run SQL took42.039s versus portable23.319s.
The limits were not relaxed. Disposable SQL fixtures now migrate one empty schema
per exact migration manifest, seal it against connections, clone an isolated DB
for each class, verify all migration hashes and assign distinct storage epochs.
The same47 SQL tests and6 subtests passed before/after; local runner time changed
17.819→14.999 seconds. A separate regression proves sibling data/DDL isolation.
The subsequent normal run passed in105.665 seconds, including deployment.

Public-site review found two owning-boundary issues, fixed before owner handoff:
- Empty-cache collector restart forgot the last valid receipt. Runtime reads now
  derive that fact from accepted durable receipts independently of heartbeat
  availability; SQL proves healthy/unhealthy states preserve the receipt without
  writing heartbeat or status.
- Market projection overwrote human selection labels with internal team IDs.
  Display uses the exact participant mapping/source role name, including existing
  compact projections, while preserving offer/revision identity. Totals omit the
  spread-style plus prefix. Focused formatter and identity checks pass.

Integrated follow-up checks pass:278 portable tests +26 subtests;49 SQL tests
+6 subtests, including all originally selected SQL targets and new restart/isolation
cases. The path-based selector intentionally selects different portable owners
for this narrower follow-up; the earlier full implementation check remains374.

### Normal release and retained-data recovery

Normal CI/deploy45227966609 succeeded on `e6862a0` in105.665 measured seconds,
without changing the two-minute job limit or55-second handoff allowance.
The preceding run45227614767 failed during GHCR publication (`unknown blob`),
not validation or handoff; the same revision succeeded on the next normal run.
Reports for all runs are retained in `.local/market-snapshot-20261123/ci-*`.

Installed recovery linked15 historical captures before yielding to the ordinary
12:20 PM Eastern T−10 writer's lock. That scheduled checkpoint completed normally.
The resumed finite recovery linked28 more, skipped16 already-linked/modern
operations and refused11 links at the unchanged research retention cap. These
11 original checkpoints remain inspectable as legacy evidence; no source data,
old arithmetic or account record was rewritten and no provider request was made.

The public-site exact offer journey opened Maryland Eastern Shore moneyline at
Novig +900, stored screening EV +6.62%, supporting DraftKings pair +800/−1350,
reference probability10.66% and Fees OFF. A browser-generated export retained the
selected pull/offer/revision and reproduced all8 numeric moneyline offers offline.
An expired SQL paging lease renewed without changing that exact selection.

Final reference-tab review found normalized reference storage also includes the
trading venues. The focused tab now projects sportsbook inputs only; the complete
immutable snapshot/export still retains every original input. A real snapshot
SQL regression covers this distinction. Affected checks:102 portable +26 subtests,
12 PostgreSQL +3 subtests, lint/workflow/secret checks pass. Final publication and
remaining installed journeys follow below.


### Final installed acceptance findings

Normal CI45228995230 installed `cac6e10` in78.106s. Its public reference tab
contains the sportsbook inputs only while the positive filter stays active.
The actual 12:20 PM Indiana State T−10 shows independent moneyline/spread/total
rows; moneyline -0.51% and spread -0.80% remain current, alongside total +1.00%.

Two additional installed findings were resolved before final handoff:
- Future T−10 was Scheduled in the case list but deep exact-line/source context
  still said Unknown or checkpoint missing. The renderer now derives those
  source cells, continuity, drilldowns, coverage and graph markers from the same
  checkpoint task state. Captured-but-missing exact lines remain distinct.
  Regression uses the actual future New Mexico State/Ohio shape and retained team
  identities, without guessing names from the title.
- Indiana State Previous capture correctly refused the wrong newer canonical
  market ID for its older source-local capture. History now projects each
  capture's own immutable market ID; navigation/reload/Back retain it with its
  pull. No identity or revision substitution was allowed.

Protected configuration and fee-schedule digests, actual Stop/source pauses and
remembered-login file hash match before/after. The public Settings view separates
service health/source availability from the durable accepted receipt after
restart. Browsing/exact export starts no provider acquisition.

**Material operating limitation:** the existing128 MiB research cap refused11
additional historical links. Those original checkpoints remain in legacy
evidence. At inspection90.9 MiB retained plus36.1 MiB protected late reservations
left0.1 MiB unreserved; future captures can also refuse under that existing guard.
No cap expansion, automatic eviction, reimport or financial assumption was used
to make acceptance pass.

The installed unfiltered arbitrage read initially reached its existing deadline.
An authentic read-only profile identified repeated normalization of every book
quote for every alternate line, repeated hashing of large witnesses, and redundant
compact JSON transferred for each family. The reader now projects scope metadata,
indexes references once per frozen pull by market/line, and keys immutable cached
inputs by verified pull and original position. The authoritative side/settlement
checks still reject wrong-polarity spreads after that broad bucket. An unprofiled
read of the same installed retained population completed in13.422s,64 stored
pairs,0 provider requests, inside the unchanged30-second arb deadline. Focused
SQL confirms identical baseline output and skipped unrelated normalization.
