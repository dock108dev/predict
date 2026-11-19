# Usability sprint: read performance and missing EV

November 18, 2026 Eastern. The local app uses the private server snapshot restored
at `20261119T022859Z`, with no local collector. The snapshot, API samples, SQL
plans, profiles and failing/passing checks remain outside Git under
`.local/usability-sprint-20261118/`.

## What changed

- Read stored withdrawal state directly from `current_offer_storage`, retaining an
  explicit `sgo_line_presence.expired` exclusion. The former `current_offer` view
  reconstructed original-price JSON and joined native books/ladders just to test
  whether a quote was withdrawn. Source prices still come from committed payloads;
  this does not remove withdrawal, active-contract, kickoff, route or reference guards.
- Apply Arbitrage search/league/family filters in SQL before decoding full source
  records. Reject nonprofitable pre-fee pairs using once-parsed exact fractions.
- Reuse exact cent-allocation repricing within one quote/group. Return independent
  nested samples, and release these temporary memos after each group.
- Retain up to 4,096 immutable pair results across unrelated publication revisions.
  Their identity includes sealed input revision, quote/fee inputs, source clocks and
  scoring scope. Concurrent visitors share the same pair calculation. The ordinary
  SQL eligibility pass still excludes expired fees, withdrawal and kickoff before
  reuse; quote timestamps are never renewed. The existing whole-query cache remains
  query/cursor/deadline scoped.
- Bound SQL statements at eight seconds and API work at ten seconds. A cancelled
  request sets a cooperative stop signal, checked during Python pairing. A timeout
  returns an explicit 503 `current_read_timeout`, never an empty result. These
  limits prevent continuing the observed abandoned work; they are not the speed fix.
- Browse/game/exact comparisons now include fee-qualified stored prices when EV
  lacks a reference. `reference`, EV, fair odds and ranking value remain null;
  `ev_unavailable_reason` retains the actual calculation refusal. Opportunities
  still requires complete positive EV. Exact sportsbook comparison maps reversed
  event roles even when no reference pair exists.

## Evidence that changed the diagnosis

The deployed baseline reproduced the report: Opportunities took 5.524/2.766 seconds
and Browse took 6.792/8.847 seconds on two successive reads. Their server `read_ms`
were 4,647/2,217 and 5,397/6,652 respectively. Arbitrage returned no bytes before
both 45-second observers timed out. Exact comparison took 1.102/0.742 seconds
(server reads 319/416 ms); all-game lines 0.588/1.107 seconds (248/230 ms).
These are observations, not a controlled
benchmark or a 45-second completion requirement.

JIT was a plausible initial explanation but the actual deployed query plan had
cost 6,573 and **no JIT section**. Turning JIT off did not explain the problem.
The plan instead showed repeated source-body reconstruction: 1,743 offer accesses,
3,486 reference/line-presence checks and native-book scans repeated once per
selected offer. The query took approximately 3.4–4.4 seconds in those plan captures.

At a separate host sample, collector/web/database CPU were approximately 94%/67%/20%.
Two web connections remained idle in transaction after the sportsbook reference
SELECT while Python calculated Arbitrage, despite observer timeouts. That establishes
that client timeout did not stop server work. Shared host pressure materially limits
comparison with the Mac; it does not prove that every slow request had one cause.

## Comparable local calculation/read measurements

A fixed-clock run imported the pre-sprint code from Git and the updated code into
one process against the **same** restored data: 13,809 calculation records, 4,835
fee-qualified prices, 28,285 stored offers and 107,360 current reference quotes.
The table reports first/repeated calls in milliseconds, not a flushed-disk benchmark.
Ordinary SQL buffers were already warm; Arbitrage's initial whole-query/pair caches
were cold. Two reads per path are a small repeatable sample, not a percentile claim.

| Path | Before first/repeat | After first/repeat | Returned evidence |
| --- | ---: | ---: | --- |
| Opportunities | 153 / 143 | 136 / 130 | Same 70 opportunities; 208,627 bytes |
| Browse odds | 211 / 180 | 267 / 269 | 101 → 241 games; first-page payload 1,363,588 → 1,230,083 bytes |
| Boston search | 22 / 20 | 20 / 19 | Same 2 rows; 14,234 bytes |
| NBA filter | 11 / 10 | 9 / 9 | Same 4 rows; 28,049 bytes |
| Spread filter | 45 / 47 | 43 / 42 | Same 19 rows; 133,453 bytes |
| Exact comparison | 9 / 7 | 28 / 27 | Same 3 venue rows; 23,787 bytes |
| All game lines | 5 / 5 | 5 / 4 | 4 → 5 authentic lines; 27,939 → 31,427 bytes |
| Arbitrage, initial / repeat | 2,517 / 2 | 2,235 / 2 | Same 239 pairs, 54,513 candidate pairs; first 30 rows 167,721 bytes |
| Arbitrage, switch to NBA | 797 | 261 | Same 47 pairs; unchanged pairs can reuse their exact calculation |

Browse's added 140 games are previously hidden prices without EV. Its higher read
cost is **not** a same-work slowdown claim, nor a claimed speedup. Exact comparison
adds a price-table eligibility branch, accounting for its small local regression.
The browser additionally supplies the selected `game_key` to constrain that branch.
All-game-lines gains one previously hidden authentic price in this example.

The benchmark process peaked at 553.5 MB RSS while retaining both implementations,
query caches, payloads and profiles. This is not an isolated deployed-worker peak
or a steady-state memory qualification. The new temporary repricing memos are
released per group rather than accumulating across the slate.

After restarting the ordinary local app on the new snapshot, HTTP observations
showed Opportunities at 655 ms for the first request and 172/168 ms repeated;
Browse at 765/312 ms for its expanded population. Exact comparison with game identity
was 24/25 ms; all game lines 19/20 ms. Arbitrage was already warm from browser use
and returned in 8 ms; its measured cold cost is the fixed-clock table above.
Separate HTTP samples include client scheduling, serialization and transfer; fixed
storage timings isolate the read/calculation work. Browser first-usable rendering,
selected-quote shells, feedback and return interactions are verified separately by
the sprint browser checks. No long operating window was required for these changes.

The owner's 100 ms feedback, 200 ms comparison shell and two-second ordinary-result
budgets remain proposed engineering targets, not repository release gates. Cold
Arbitrage remains 2.235 seconds locally in this cohort. The next sufficient evidence
is the deployed workflow plus normal browser/API reads on its installed SHA; this
local report alone does not establish deployed latency under live host contention.

## First deployed check exposed the remaining SQL bottleneck

The first GitHub deployment (`adead2955…`, workflow `44446682769`) installed and
served the intended code, but **did not complete the performance outcome**.
Arbitrage returned `503 current_read_timeout` after 8.94/8.56 seconds. Opportunities
still took 2.739/5.049 seconds; Browse 7.698/7.168 seconds. These failing results
remain in the sprint's deployed timing evidence; successful deployment was not
mistaken for successful behavior.

A request-equivalent read-only trace localized the Arbitrage failure: its initial
eligibility SELECT hit the eight-second SQL timeout after 8.034 seconds. Python
pair modeling and sportsbook decoding had not started. The actual plan nested
1,000+ price rows against 297 pending sportsbook jobs, repeatedly decompressing
large quote payloads to test each job's event-ID membership.

The revised predicate expands each price's small event-ID array once and joins
those IDs to the pending-work primary key:

```sql
NOT EXISTS (
  SELECT 1
  FROM jsonb_array_elements_text(p.payload->'sportsbook_event_ids') ref(event_id)
  JOIN current_pregame_work w
    ON w.provider='sportsgameodds' AND w.native_event_id=ref.event_id
)
```

This retains the same exclusion: any pending job for an attached sportsbook event
suppresses that price until recovery. It does not omit pending work or truncate
candidate coverage. An equivalent read-only plan on the live database returned
1,672 eligible prices in **474 ms**, versus the original statement's eight-second
timeout. A complete diagnostic using this candidate SQL and the installed Python
model returned 184 pairs from 41,642 candidates in 9.654 seconds (SQL 1.448 seconds,
reference fetch 0.682 seconds in that separate sample). This diagnostic is not an
installed-endpoint claim. Source files on the server were not edited.

Two other query changes address demonstrated board costs:

- Opportunities admits complete **bet groups** having at least one stored positive
  venue before expensive eligibility work. All aliases/venues within such bets
  remain candidates, so a newer negative alias cannot be bypassed by an older
  positive one. Bets with no positive stored price cannot produce a positive result.
- Browse first chooses the page's game identities, then builds full game JSON only
  for those games. Counts, kickoff order and all lines within the selected games
  remain intact; it no longer constructs large documents for off-page games.

Actual before/candidate `EXPLAIN ANALYZE` calls in one deployed repeatable-read
transaction measured **Opportunities 1,406→324 ms**, and **Browse 3,794→2,099 ms**.
Those are SQL times under the same database snapshot, not browser transfer times.
Remaining Browse work included approximately 744 ms qualifying price-only rows
and 579 ms qualifying complete rows. Repeated reference availability lookups
contributed roughly 150 ms, so this evidence did not justify a larger reference
schema redesign. The solver also now copies mutable cashflow/presentation maps
without repeatedly deep-copying immutable source and fee evidence.

A new disposable integration case attaches a distinct sportsbook event to market
prices, admits a job for that event, and verifies that cached pairs disappear
before recalculation and return after recovery. The focused SQL run now passes
**30 tests plus 2 subtests** in 6.02 seconds. Unit checks remain **23 passed**.
The next sufficient stopping condition is normal completed API/browser behavior
on the next GitHub-deployed SHA, including a cold Arbitrage read. No additional
observation window or two-second release gate was introduced.

## Verification and limits

- `tests/test_pregame_arbs.py`, `tests/test_pregame_sportsbook_prices.py` and
  `tests/test_current_pregame_reference_policy.py`: **23 passed**. Includes independent
  memoized cashflows, amount/clock identity, reversed reference-free roles and a
  short injected server deadline proving that background Python work stops.
- PostgreSQL 16 disposable run of `tests/test_current_pregame_sql.py` and
  `tests/test_pregame_board_views_sql.py`: **29 tests plus 2 subtests passed** in
  5.90 seconds. This covers eligibility, withdrawal, source routing, original
  clocks, full-game grouping, fees, cache expiry and missing-reference inspection.
- The initial SQL run retained **3 failures/26 passes**. Two assertions encoded the
  former behavior that hid authentic prices when EV lacked two books. They now
  require null EV plus the actual missing-reference reason, while the positive
  board remains empty. The new expiry fixture initially changed an empty table;
  it now links exact source revisions and supplies real expired-presence records.
- Ruff checks and formatting pass for the changed backend/calculation/test files.

No provider request, account mutation, source configuration, Stop choice or financial
ledger changed in these reads and disposable tests. Hosted checks, deployment and
installed behavior are recorded in the main sprint handoff after they occur.

Learning update: The first deployed timeout occurred inside SQL before any pair modeling | replaced the queued-reference membership join and deferred off-page JSON construction | candidate live plans improve Arbitrage eligibility from an eight-second timeout to 474 ms, Opportunities 1406→324 ms and Browse 3794→2099 ms; 32 SQL checks pass | next deployed cold-read and browser verification remain required.

Review decision: Browse must hide prices without complete EV | prior test expectation superseded by owner sprint scope; blocks desired browsing | updated assertions to require null EV and actual reason while retaining the positive-opportunity rule.
