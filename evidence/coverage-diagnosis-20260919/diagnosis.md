# Retained usable-coverage diagnosis — September 19, 2026

**The initial-to-Stop decline is fully reconciled as recorded receipt-freshness expiry: 41 Kalshi markets and 3 Polymarket US markets had no qualifying native update within 30 seconds.** This demonstrates absence of qualifying updates in the admitted history, not an upstream outage or missing exchange activity. No application behavior was changed.

| Retained measurement | Kalshi | Polymarket US |
|---|---:|---:|
| Initially usable | 64 | 32 |
| Usable immediately before Stop | 23 | 29 |
| Lost at Stop, all recorded stale | 41 | 3 |
| Distinct markets stale at some point | 63 | 21 |
| Stale observations, including repeated expiry after recovery | 112 | 37 |
| Qualifying native book observations | 555 | 1,330 |
| Unchanged native ladder images received | 0 | 51 |
| Age of last native receipt for lost markets at Stop | 31.061–215.207 s | 30.260–36.976 s |
| Terminal usable | 0 | 0 |

The decline was not monotonic: later native updates restored usability and markets sometimes expired again. The 112/37 stale observations therefore are not counts of permanently lost markets. The three US markets stale at Stop are `657975`, `657992`, and `825205`; all 41 Kalshi IDs and every supporting observation are in [per-market.json](per-market.json).

## Identity and reconstruction boundaries

Session `aa1a5562-5a5f-4b8c-aee2-6f00eaeabe62`, historical candidate `7f41489d2c52c5331cacbd076d406c3ab0786291a5feebb5c55cf2fff02e9961`. Recomputed candidate identity, seven segment hashes, history/replay manifest hashes, every retained body hash, session identity, ingress uniqueness and timestamp order. Exact native replay independently matches 1,885 native books/3,770 packets and 149 derived stale books/298 packets: 2,034 books/4,068 packets total, with no replay sequence gaps. [Identity and replay](identity-and-replay.json).

Historical candidate files differ from current files only in `app/collection/supervised_live.py` and `tests/segmented_collector_fixture.py`, consistent with subsequent finalization work. The collector, native adapters, freshness logic, journal reader and replay dependencies used here match historical hashes. The current finalization candidate also matches its recorded hashes. New finalization telemetry is not evidence about the historical feed or its missing lifetime memory peak.

The full admitted journal—not just the rolling snapshots—survives. Collector state is reconstructible in observation order from **20:56:25.841648 UTC through the pre-Stop boundary at 21:00:25.905415 UTC on September 16**. Initial selected markets are unusable until their first qualifying book. [Timeline](coverage-timeline.json) records 351 count changes including terminal, and [per-market.json](per-market.json) supplies state intervals and all 2,034 book observations with ingress IDs, native receipt times, associated frame IDs/hashes, stale times and nominal deadlines. These are event-driven collector states, not interpolated venue books or proof of continuous upstream delivery. Journal admission precedes synchronous state mutation; the sub-event processing latency is not retained.

All 60 retained periodic snapshots match exactly, covering **20:59:22.746860–21:00:25.864458 UTC**. All five saved status checks also match. Their sample UTC is derived from published UTC plus recorded discovery age; this does not assume the delayed `start_clock` UTC equals the true monotonic origin.

| Saved checkpoint | UTC | Kalshi / US usable |
|---|---|---:|
| Initial | 20:56:51.321825 | 64 / 32 |
| Mid-initial | 20:57:41.568599 | 20 / 31 |
| During refresh | 20:58:34.398782 | 24 / 29 |
| Refreshed | 20:59:07.659529 | 17 / 31 |
| File named `status-pre-stop.json` | 20:59:55.566618 | 19 / 31 |
| Actual `validation.json.before_stop` | Stop boundary | 23 / 29 |

Stop closes intake. Cleanup observations were rejected after closure; the individual group-clear times within **21:00:25.905415–21:00:25.991523** cannot be reconstructed. The terminal journal and final coverage establish disconnected/zero at closure. No synthetic per-market disconnect observations are inserted. Before the first observation, after terminal, and inside this cleanup interval, no continuous market history is claimed.

## Demonstrated causes and native semantics

Every pre-Stop loss has a synchronized native image followed by a stale derivation retaining that image. No intervening qualifying native book restores those 44 markets. First stale emissions occur at 20:57:20.823470 (Kalshi) and 20:57:20.915905 (US), about 30 seconds after initial images.

The historical coverage predicate is synchronized + receipt-recent + eligible/non-invalidated group; it is not a promise of economic executability, positive quantity, exchange freshness or exhaustive depth. Inspection/replay finds no malformed or missing supported native ladder responsible for these losses:

- Kalshi: four acknowledgements, 64 initial snapshots, 491 deltas; contiguous subscription-scoped sequence reconstruction. Native Yes/No bid ladders were populated in all 555 qualifying books. Purchase asks are derived from opposite bids; absent native ask arrays are expected. Any valid snapshot/delta refreshes that market's receipt age, not other markets on the socket.
- US: 1,330 current-request full advertised-window replacement images, each with populated partial Long bids/offers. Replacement removes omitted prior levels; it is not delta merging. Short ladders remain absent/unsupported, and full exchange depth remains unknown. All 51 unchanged ladder images still qualify as new receipts. Repeated source times (17 US and 18 Kalshi observations) also qualify under the original receipt rule. Source-time progression is separate from receipt freshness.
- Health: 667 Kalshi and 1,367 US `connected` rows follow emitted books, including stale books. They do not reset receipt age or restore usability. Initial `awaiting_snapshot` rows explain startup only. There are no admitted pre-Stop disconnection/ineligible/recovery events, subscription departures or extra connection attempts. A connected row alone is not independent proof of transport health. No US heartbeat frames were retained; parser heartbeat messages do not refresh per-market data timers.
- Catalog: both generations retain identical selections; no additions/removals or kickoff exclusions. Re-evaluating every saved partial-refresh safety predicate produces no exclusions. Refresh does not refresh book receipts or re-subscribe unchanged groups. [Catalog/depth checks](catalog-and-depth.json).

## Separate demonstrated timing defect

Kalshi checks expiry only after a **shared socket receive timeout**. Other-market traffic can defer a quiet market's expiry. Retained stale emission ages are **30.006874–32.343594 seconds**; US ages are **30.000927–30.038224 seconds**, with an independent per-market deadline loop. These wall-clock emission delays include scheduling/admission time; they are not pure network latency.

Example: Kalshi prior native book `778d66f2-27af-45cd-9d95-573dfdca4e47`, receipt 20:59:46.688470; nominal deadline 21:00:16.688470; stale book `2968f5f1-563a-4375-978d-c31abd858c2e` emitted 21:00:19.032064. An isolated synthetic characterization using the unchanged actual stream loop proves a quiet book remains recent at ages 31 and 32 seconds while another market supplies frames, then becomes stale at the first timeout at 32.5 seconds. [Check](check_diagnosis.py), [synthetic trace](timer-characterization.json).

This defect temporarily **overstates** freshness; it does not cause the 64→23 decline. No pre-Stop usable book exceeds 30 seconds at the actual Stop checkpoint. Historical counts are preserved rather than replaced with nominal-deadline counts.

## Unknowns and one next action

Quiet books, unchanged upstream state without retransmission, or upstream/per-market delivery loss are hypotheses. The retained journal cannot distinguish them: it records what this collector admitted, not all exchange changes, publisher decisions, ping/pong activity or remote subscription internals. US has no sequence guarantee in these retained images; “no replay gaps” does not establish completeness. No unexplained *collector-state* losses remain; the upstream reason for update absence remains unknown.

**Next action belongs to engineering: repair only Kalshi's expiry scheduling offline**, so each market expires under the existing 30-second rule even while other markets deliver frames. Preserve strict comparison semantics, snapshot/delta reconstruction, subscription sequences, pending receive integrity, reconnect/Stop behavior and all budgets. Verification should cover a busy sibling/quiet market, just-before/at/after threshold boundaries, valid update recovery, unchanged-image handling, no duplicate stale emission, and pending-receive/Stop cancellation; rerun exact retained native/packet replay and applicable stream lifecycle checks. No repair is implemented here, and no live run is needed to verify it offline. This repair should improve timeliness of stale classification, not promise higher usable coverage.

To answer the separate upstream question, the minimum new evidence is a time-aligned independent per-market reference during a stale interval (native snapshot/state or authoritative venue change/delivery records), correlated with raw receive/subscription and connection-health events. An unchanged reference establishes consistency only at that instant; proving missing delivery needs evidence of a specific intervening change. Any new live requests/capture require explicit owner authorization and a separate bounded plan; none is authorized by this diagnosis.

## Verification and reproduction

Four focused checks pass, including actual-loop timer characterization. Offline replay blocks socket connections. Initial diagnostic tooling failures (an overbroad socket replacement disrupting an import, then an optional terminal `source` field) are retained in `run.log`/`run-2.log`; corrected tooling passes without weakened assertions in `run-final.log` and `checks-final.log`. No application test failure or full-suite pass is claimed.

From the repository, using the existing environment:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python evidence/coverage-diagnosis-20260919/diagnose.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python evidence/coverage-diagnosis-20260919/check_diagnosis.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python evidence/coverage-diagnosis-20260919/verify_preservation.py
```

All **2,650 preexisting evidence files / 1,851,488,825 bytes**, all 324 preexisting application/test/document files, and the prior finalization baseline's 2,643 evidence hashes remain unchanged. [Preservation verification](verification.json). Only this separate diagnosis directory and the Desktop tracker were written; the tracker's prior version is retained here. No credential access, live requests, restart, reset, threshold/budget changes, migration, trading, commit, push or publication. US completeness remains unknown, Short unsupported, and thirty-minute/daily capacity, D2 and full D3 incomplete.
