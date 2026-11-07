# L03 — grouped live ranking and pinned inspection

November 4, 2026. Backend/API and functional controller integrated in the sole
main checkout; no commit or push. L01 remains the acquisition/publication owner;
L02 remains the financial owner. L04 owns the final compact list/drawer styling.
This record does not certify sustained current source coverage or L05 acceptance.

## Current list contract for L04

Use `GET /api/comparison-current`. It now defaults to `group=outcome` and
`metric=conditional_return_percent` (`minimum_return_percent` for the separate
pairs view). Historical `/api/comparison-snapshot` retains its existing default.
League, game, venue, market family and search filters apply to the complete
universe, then grouping, exact ranking and finally bounded pagination occur.

Each outcome retains all matching source rows, including prices with pending,
unavailable or withdrawn finance. Distinct source instruments are never removed
as duplicates. Group identity includes occurrence/game, market, period,
participant, literal predicate, rational signed line and result interpretation.
Missing semantic identity stays source-specific. Native not-win stays not-win;
this display bucket is never settlement-equivalence evidence.

| Response field | Contract |
| --- | --- |
| `id`, `generation`, `cursor` | Root and current authority frame. Root assembly time is not a quote clock. |
| `rows[].id`, `outcome_key`, `quotes` | Stable semantic outcome ID and all its source rows. A group never splits between pages. |
| `rows[].score` | Exact rational maximum of eligible values, or null. No rounding participates in ordering. |
| `rows[].score_source` | Exact row ID, venue, source identity and immutable evidence member that set the score, or null. |
| `rows[].quotes[].ranking` | Per-source eligibility, exact value, metric and typed exclusion reason. Use `metric_status` and `current_reasons` for the detailed financial/authority reasons. |
| `ranking` | Selected metric, explicit reviewed-fee/conservative-estimate basis, common `risk_basis`, current-only flag and score rule. |
| `total`, `outcome_count`, `position_count`, `source_price_count`, `unranked_count` | Filtered-universe totals, not page totals. On ordinary outcomes: outcomes, outcomes, source offers, source offers, unranked outcomes. Pair view position count is combinations; source-price count counts distinct legs. |
| `offset`, `limit` | Outcome offset and bounded page size (1–100). |

Default rank admits only a numeric current `conditional_return_percent`, available
`after_trade_fee_ev` status and L02's supported
`decisive_taker_one_usd_claim_one_fill_total_risk_v1` basis. Source authority must
be current, with no withdrawal reasons. Positive, zero, negative and unknown
outcomes are preserved in that order; deterministic ties use start time,
canonical outcome and stable source identity. A gross value, assumed-net value,
conservative estimate or incompatible sizing basis cannot fill a missing score.

`metric=conservative_return_percent` is a separate, explicitly labeled
**Conservative public-fee estimate** view. It does not combine with or substitute
for the reviewed-fee metric. The same currentness checks and L02 common risk basis
apply. The full `conditional_trade_benchmark`, `conservative_trade_benchmark`,
`reference_calculation`, original/native transforms, revisions and clocks remain
on their source row or exact immutable member. Withdrawal retains the original
Pinnacle pair disclosure with `available=false`; retained math has no current
ranking authority.

## Pagination and updates

Poll `/api/comparison-current/updates?after=CURSOR` at the delivered two-second
cadence. A changed cursor requires a new current read even when generation is
unchanged. Cursor identity includes material dependencies, owner health,
Stop/source controls, settings, policy and expiry. Receipt-only confirmations
cannot invalidate an otherwise unchanged captured proof. New published roots
still change the cursor to expose their own clocks.

For a continuation page send `offset`, `limit`, the same filters/metric and
`expected_cursor=CURSOR_FROM_ACCEPTED_PAGE`. A mismatch, or a nonzero offset
without this expectation, returns HTTP 200 with:

```json
{"state":"page_changed","reason":"comparison_changed_restart_pagination","restart_offset":0,"rows":[]}
```

It also supplies current cursor/generation/result identity. Discard the old page
sequence and read offset zero; never append incompatible pages. This is an
explicit restart, not a historical pagination session or lease on the whole
universe. Frequent actual market changes can restart deep browsing. Currentness
continues to be checked; holding old pagination cannot preserve a stale score.

The installed controller replaces pages, rejects superseded asynchronous responses
(including same-generation authority responses), retains filters/search, preserves
scroll position and restores source-button focus or the content fallback. Hidden
pages stop ordinary polling and reread on visibility return. Saved historical
result navigation remains available. Ordinary reads use repeatable-read read-only
transactions; they do not dispatch acquisition, calculate finance or write
account/quota/schedule state.

## Pinned controller contract for L04

`app/dashboard/opportunity_static/current/snapshot-live.js` exports the lexical
`SnapshotLive` bundle module. Compose it before `snapshot-controller.js` via the
existing frontend builder. `SnapshotLive.create({request, release, onChange,
onError})` returns `open(row,result,metric)`, `check()`, `adopt()`, `close()`,
`renew()` and `state` (including a persistent action/lease `error`).

- `open` clones the row/result actually clicked, including null economics. It
  leases `row.evidence_result_id` (root fallback for historical/pair cases), then
  reads exact `/api/comparison-snapshot/details` with that token. It checks row,
  price and economic identities. Expired/raced-out evidence is an explicit error;
  it never silently opens a newer row. Leasing the member bounds retained data
  to the selected component instead of retaining all members of every old root.
- `state.pinned` contains the immutable displayed `row`, captured `result`,
  selected `metric`, exact `details` and `lease`. **Displayed current values and
  retained historical arithmetic are distinct**: do not overwrite the displayed
  row with `details.row`. Use `details.assumptions` for the member's actual inputs;
  a current response's `assumptions` can describe newly requested settings while
  its older row's finance has been withdrawn.
- `check` uses exact `/selection?id=ROW`. It changes only `notice`, never pinned
  inputs. `notice.old/latest` contain exact original prices, probability, selected
  Pinnacle pair, after-fee/conservative values, fee basis/review facts, revisions,
  availability and typed reasons. Confirmation/receipt clocks and root/member IDs
  alone are not material. Repeated confirmations do not rebuild the notice or
  steal focus from its action.
- `adopt` fetches a fresh exact selection, refuses removed/unavailable rows,
  leases and reads the replacement, then rechecks its current material facts.
  Only after those agree does it swap the whole pinned context and release the
  previous lease. A replacement racing that sequence is refused with the prior
  calculation intact. Ready source prices with pending finance can be adopted;
  their economics remain null. All asynchronous paths have independent tickets.
- `close` releases the token and invalidates outstanding work. Late retention
  responses release their own token. Renewal uses the same token; the installed
  visible panel renews every 30 minutes and on visibility return. Close,
  replacement and page exit release leases. Server limits remain 32 tokens and
  two hours per lease; renewal failure is explicit. No unbounded UI history is
  accumulated.

The installed functional Math & fees panel lives outside the replaceable list.
Its old/latest notice and explicit Use latest prices button are wired; list
updates, filters and sorting continue independently. Close/Escape returns focus
to the selected source if present or a useful fallback. Exact Admin evidence is
linked to the leased member. L04 should replace the provisional panel styling,
not recreate the selection/lease state machine or pause the list.

## Verification and measured limits

- 60 focused portable tests and 6 subtests passed: snapshot/native finance,
  presentation, completion and L03 ranking. An independent rational oracle checks
  701 outcomes/2,804 offers across every page, deterministic ties, negative/zero/
  unknown values, native predicates/instruments and conservative separation.
- All 18 focused PostgreSQL 16.15 tests passed in a disposable cluster. HTTP
  pagination covers the complete fixture without duplicated outcomes or missing
  sources; same-generation dependency/control changes refuse continuation,
  confirmations keep authority, and capture/calculation are forbidden on reads.
  Companion checks cover references, fee expiry, Stop/pause/resync and retention.
- `tests/test_l03_inspection.cjs` passes asynchronous revision/lease races, null
  economics, reference/fee withdrawal, removed/unavailable states and atomic
  replacement. `python -m browser_tests.l03_current` passes the actual bundled
  controller against intercepted authored responses: list advancement while
  pinned, old/latest facts, confirmation suppression, adoption, withdrawal,
  Escape/focus, old/new concurrent searches and page restart. No provider or owner
  database is reachable from that browser fixture.
- Authentic installed browser observation advanced generations 831 → 833 → 834
  → 835 while the same selected member stayed pinned; no browser errors. Source
  authority failed during part of this observation, and the panel correctly kept
  evidence while reporting the selected offer unavailable. This is not evidence
  of uninterrupted native freshness. Evidence: `test-results/l03/live-browser.json`
  and `live-pinned.png`.
- A 20,000-source / 5,000-outcome fixture produced the useful grouped page in
  0.144 seconds. Installed initial useful paint measured 1.628 seconds. After
  reducing repeated identity hashing and identical withdrawal-status allocation,
  six HTTP reads at generations 862/863 (14,303–16,111 sources; 11,445–12,423
  outcomes) measured 1.012–1.227 seconds warm, with a new-root read at 2.282
  seconds. A deliberately cold app/browser useful paint measured 2.295 seconds.
  The post-final-build installed smoke at generation 899 measured 3.714 seconds,
  with working pin/close/focus and no browser errors (`final/installed-smoke.json`
  under the same evidence directory). The larger final tail is retained here,
  not replaced by the earlier faster observation.
  **The two-second target is not consistently met on cold/root replacements.**
  Root decoding and changing runtime/storage load remain measured qualification
  concerns, not missing financial inputs. No sustained percentile claim is made.

Wheel builds, frontend composition/drift, lint and documentation checks are local;
no hosted CI, commit/push or owner acceptance is claimed. App restarts happened
in place; the existing data owner continued normal acquisition. The current worker
loads the checkout, including the small read-projection improvements; no second
publisher or collector was added. Selected token limits and account guards remain.

At 6:33 PM Eastern, accounting remained **31 held credits / 12 unresolved
attempts**, used 1,782 / remaining 98,218, no blocker. Normal scheduled collection
advanced usage; no holds were forgiven or settings/Stop/source pauses reset.
Data was healthy, SQL usage approximately 1.599 GB, Kalshi receiving and
Polymarket US connecting. Its publication remained partial. Cold-read tails,
native delivery/currentness and storage interruptions need L05 sustained
qualification. Missing Kalshi membership/intermediary and ProphetX account/channel
fee facts remain the separate L02 external dependencies. Continue L04 then L05;
known engineering work does not await owner review.
