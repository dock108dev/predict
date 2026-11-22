# Prediction data and calculation audit

November 22, 2026. Baseline: `main`, commit `5d66f855ccc8c37530dd9e6ea2eae9549c3b7f12`, version 0.2.0. The checkout was clean before this documentation work. The deployed web, collector and archive images identify the same commit.

The recommendation is to **keep the acquisition, identity, calculation and evidence foundation; retire competing product plans; and make a simple research workspace the primary interface**. A wholesale rewrite would discard useful, tested behavior. Phase 2 should prove data correctness and reproducible calculations. Profitability, public release, onboarding and marketing are separate possible outcomes.

Start with the [archive and reuse decisions](archive.md), then the [proposed implementation sequence](implementation.md). These documents propose work; no archival moves, application fixes, deployment changes or collection changes were made in this audit.

## Decisions to make first

| Decision | Recommendation |
| --- | --- |
| Existing backend | Reuse the independent collector, PostgreSQL current rows, affected-game calculations and read-only app. |
| Existing UI | Keep working controls and inspection. Promote received data, missing cases and calculation traces. Freeze decorative expansion. |
| Old product priorities | Retire them as active instructions while preserving dated findings and source evidence. |
| Historical code | Keep shared owners in place; move standalone consumers only after tracing and detaching dependencies. |
| Data and accounts | Preserve observations, archive shards, journal, settings, Stop choices, credentials, reservations and holds. |
| First engineering work | Repair the demonstrated collector startup failure and establish an honest archive coverage census. |
| Phase 2 completion | Correct, inspectable data and reproducible mathematics, including explicit unavailable cases. Positive returns are not required. |

## What the current system actually does

The ordinary launcher enters `dashboard.opportunity_board`, then `multi_game_server`. The data process admits source observations and calculates affected games. The app reads committed PostgreSQL rows; loading or refreshing the board does not acquire provider data. Current SQL reads are separate from older research publication graphs. See [architecture](../../architecture.md) and [current pregame](../../current-pregame.md).

The current path is materially narrower than the repository's full collection of adapters and research experiments. Ordinary EV covers scheduled full-game moneyline, spread and total, four represented venues, and three provider routes. Lower-level storage accepts five venue labels. Native adapters, wider sports normalization and historical scenario engines do not automatically extend the primary calculation path. See [current calculation admission](../../../app/storage/current_pregame.py), lines 415–455, and [SQL preparation](../../../app/storage/current_rows.py), lines 190–218.

There is already more inspectable data than the positive-opportunity home page suggests. Browse/game/exact comparison reads include fee-qualified prices with missing references, retaining null EV and an unavailable reason. Raw Odds exposes source-local records and native wire independently of a calculation overlay. Admin has bounded database inspection. These are assets to promote, rather than replace. See [pregame reads](../../../app/storage/current_pregame_read.py), lines 90–108, and [raw reads](../../../app/dashboard/raw_price_api.py), lines 54–128.

## Deployed collection is currently failing before dispatch

Read-only server observations on November 22, approximately 3:01–3:04 PM Eastern:

| Observation | Result |
| --- | --- |
| Collector | Restart count advanced from 7,173 to 7,175 between samples; health was starting. Logs repeatedly report `BudgetStop` during startup maintenance. |
| Failure path | `DataRuntime.start` → `storage_maintenance.maintain` → `require_disk_space`. |
| Web and archive | Healthy. Normal Opportunities API returned `total=0` at the sample. This is the positive-view result, not a census of source data. |
| Database | 3,744 MB reported by PostgreSQL; migration `111_known_withdrawal_indexes.sql`. |
| Host filesystem | 38 GB filesystem, 94% used; approximately 2.33 billion bytes free. |
| Archive capture | Enabled in the running collector configuration. Exporter reported no staged backlog or pending batches. |
| SGO archive | 5,938,586 verified records; 2,503,964,339 verified compressed bytes. These are records, not games or independent predictions. |
| Last SGO archive activity | Staged November 20 at 1:32 PM Eastern; verified at 1:47 PM. |
| Reported SGO gaps | 158,097 skipped records; recorded receipt gap bounds November 20, 1:17–2:06 PM Eastern, reason `staging_or_disk_capacity`. |
| Native archive | Kalshi 88 verified records and Polymarket US 120; each reports two skipped records. Last staging was November 20 at 11:32 AM Eastern. |

The immediate failure is more specific than “the disk is below its minimum.” There was more than the fixed 1 GiB floor free. Startup maintenance also requires temporary room for a rewrite:

```python
require_disk_space(ROOT/'.local/postgres', append_bytes=row['bytes']*3)
```

[Maintenance](../../../app/storage/storage_maintenance.py), line 223.

```python
if shutil.disk_usage(directory).free < FREE_DISK_BYTE_FLOOR + append_bytes:
    raise BudgetStop('current_observation_disk_free_floor')
```

[Storage policy](../../../app/collection/current_storage_policy.py), lines 61–74. This exception propagates through [startup](../../../app/collection/data_runtime.py), lines 85–99, before source construction. The particular relation selected at failure was not logged in the sampled messages. A size census found `sgo_quote_revision` at 544,710,656 bytes, but that alone does not establish which rewrite failed.

The existing floor protects retained state. A repair should preserve it and make insufficient rewrite headroom a bounded, observable maintenance disposition where safe. It must also address real capacity pressure and verify that acquisition fits its independent SQL/disk limits. Raising a cap or swallowing every maintenance exception would not establish a sound recovery.

The archive is genuinely populated. Healthy export and zero backlog establish export progress; they do not establish continuous collection or complete historical coverage. The gap counters are not a count of every observation missed during the subsequent outage.

## Source retention supports existing math but loses expansion inputs

The SGO adapter intentionally keeps supported team-points fields and skips other market types:

```python
if odd.get('periodID') != 'game' or odd.get('statID') != 'points' or typ not in MARKETS:
    continue
```

[Adapter](../../../app/collection/sportsgameodds_adapter.py), lines 256–296. The larger player/stat tree is also reduced to bounded team scores. The transport independently requests a fixed market set. Worker preparation sends normalized records, references, event frames and a receipt hash; ordinary ingress explicitly rejects `raw_payload`. See [page preparation](../../../app/collection/sportsgameodds_worker.py), lines 293–311, and [admission validation](../../../app/collection/current_database.py), lines 85–94.

Retained normalized inputs can reproduce supported calculations for covered frames, but they cannot reproduce the original parsing or recover discarded response bytes. Existing archive records cannot later reveal player props that were never requested or fields discarded before retention. Phase 2 needs a measured raw-receipt retention option if reparsing is part of the goal. It should be a separate bounded archive, with normalized admission continuing to use its existing contract.

Other expansion boundaries are explicit league, venue, period and market lists in transport, adapter, domain, projection, admission and reference selection. Adding another book or sport is more than a UI filter. A small shared capability description and explicit adapters should reduce duplication while preserving strict contract identity.

## Provider identity and venue identity need clearer presentation

[SGO projection](../../../app/collection/sportsgameodds_current_rows.py), lines 16–26, maps provider bookmaker `polymarket` to display venue `polymarket_us`, while its own comment says equivalence has not been established. Original provider bookmaker identity is retained.

This is a demonstrated naming ambiguity, not proof that every affected contract is incorrect. Research views should show provider, original bookmaker/venue identifier, displayed venue and any independently established equivalence separately. Familiar labels must not authorize a settlement match.

## The current EV policy is useful screening rather than an event probability model

The active policy is `lowest-no-vig-two-trusted-books-2`, calculation version `predict-current-pregame-6`. It requires at least two complete trusted same-book opposing pairs, then selects the lowest win probability for the particular bet:

```python
selected = min(
    candidates,
    key=lambda item: (F(item["probability"]), BEST_BOOKS.index(item["book"])),
)
```

[Selector](../../../app/comparison/current_pregame.py), lines 150–178. FanDuel, DraftKings, BetMGM and Caesars are the fixed trusted set. This is a deliberate screening policy, not a statistical lower bound or an empirically validated true probability.

A deterministic probe through the actual selector used FanDuel home/away `+150 / -150` and DraftKings `-150 / +150`. It returned home probability `0.4` from FanDuel and away probability `0.4` from DraftKings. Each selection follows the policy correctly; together they sum to `0.8`. They cannot serve as complementary outcomes of one game model. The [journal](../../../app/dashboard/bet_journal_metrics.py), lines 316–333, already refuses paired EV when reference book/input sets differ.

The reusable arithmetic is separate:

```python
probabilities = dict(win=p, loss=1 - p)
ratios = {
    state: F(value["net_receipt_usd"]) / committed - 1
    for state, value in states.items()
}
ev = sum(probabilities[state] * ratios[state] for state in states)
```

[Cashflow values](../../../app/comparison/current_pregame.py), lines 378–387. With probability `0.4`, committed cash `$100`, win receipt `$250` and loss receipt `$0`, this gives `0.4 × 1.5 + 0.6 × -1 = 0`. Fees change the committed cash or net receipts. This calculation can be checked exactly; the reliability of `0.4` requires separate evaluation.

Keep the current screen under its explicit policy name. Add coherent, versioned probability estimates for event/outcome evaluation, with conditioning and missing exceptional outcomes explicit. A new model should not overwrite historical calculations.

## Existing history and journal need a general evaluation layer

Keep the hash-verified archive and its receipt-time cutoff reader. Keep original source, receipt and retained-knowledge clocks. [Replay](../../../app/storage/odds_archive_replay.py), lines 30–53 and 74–105, prevents later receipts entering an earlier reconstruction, but deliberately reports `freshness='not_established'`. Native archive history preserves top levels, not a complete historical depth book.

Working `current_sgo_history` is bounded diagnostic history, pruned after seven days for pregame and one day for legacy live material. It is not the durable backtest dataset. Archive shards have separate retention and coverage semantics. The durable archive currently recognizes Kalshi, Polymarket US and SGO feeds; direct Novig and OddsLink ProphetX routes do not automatically inherit archive support. Route availability and archive availability need separate accounting.

The personal journal correctly freezes original decisions, retains corrections, distinguishes observed/actual/closing cashflows, and guards closing observations with source/receipt/knowledge cutoffs. Keep it as an optional evidence stream. Its automatic discovery selects positive market-to-market arbs; the sampler returns `ev=[]` and later tracks selected identities. It is not a general probability-evaluation cohort. See [sampling](../../../app/dashboard/bet_journal_monitor.py), lines 152–173, and [journal](../../../app/dashboard/bet_journal.py), lines 35–53 and 438–456.

The older [research loop](../../../app/reference/research_loop.py) has useful append-only predictions, outcome annotations and Brier scoring, but hardcodes one DET/BUF event. Reuse those ideas in a general evaluator connected to the current data path. Outcomes, venue settlement, calculation correctness, model quality, execution feasibility and realized returns need separate results.

## Verification performed

This audit inspected source, active routes/imports, configuration contracts, tracked versus ignored planning files, current deployment identities, server status/logs, archive status and bounded SQL statistics. Server SQL used read-only transactions. No provider requests, changes to source collection controls or restarts were initiated by the audit.

| Check | Result and scope |
| --- | --- |
| Acquisition, ledger, activity and scheduling | 79 local tests passed. Covers original clocks, Stop/pause, reservations/holds, scheduling and passive-read behavior. |
| Calculation, matching, journal metrics and saved replay | 99 tests and 24 subtests passed. Covers reference policy, exact math, fees, missing inputs and causal cutoffs. |
| UI assets and shared historical dependencies | 12 tests and 6 subtests passed. Supports the caution against bulk deletion of old-looking modules/assets. |
| PostgreSQL ingress/archive integration | 38 tests passed on disposable PostgreSQL 16.15. Covers atomic ingress, receipt isolation, retry without refetch, export ACK/restart, receipt-cutoff replay and unchanged snapshots. The cluster was stopped. |
| Maintained documentation | Existing checker passed all 56 maintained documents. |
| Historical research-loop test | Collection failed because its opt-in saved page `evidence/public-nfl-reference/vegasinsider.html` is absent. This is a historical reproducibility gap; the module is explicitly deferred by current test policy. |

Total: **228 passing tests and 30 passing subtests**, plus documentation validation. This is focused evidence, not a fresh full-suite or hosted-CI result. Test files and commands are in the [implementation verification section](implementation.md#verification-already-completed).

The local saved development snapshot dates to November 18 Eastern and no local app was listening on ports 8783/8784. The hosted API was read, but a browser research journey, scheduled successful acquisition, full archive content census, probability calibration and actual fills were not verified. The collector startup problem remains open and is the first proposed engineering slice.
