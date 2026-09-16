# E4 completion report — bounded offline Arb/Mispricing service

September 15, 2026. **E4 is complete for the authorized synthetic offline engineering and durable replay scope.** No live qualification, calibration, attainable profitability or owner acceptance is established. Work stops after E4. [One E5 market-watch handoff](e5-handoff.md) is prepared only.

## Exact candidate and preservation

- Unchanged HEAD: `0ab12b1e7b57f4ea89b6886c3d69b2459afaa258`.
- Uncommitted E4 implementation digest: `06acc81d91c69e31560792775ff1acce3ccd88656f54967101c9311b92d67426`.
- Full retained implementation digest: `b43681c2defd477aba66c8d2a83705ace71447a8f060e2b9b1c302c9178bc29d`.
- [Exact file manifest](../evidence/e4/candidate-implementation.json). Digests hash canonical sorted file-to-SHA-256 maps; the manifest defines each scope. [Final verification](../evidence/e4/verification.json) separately records documentation/evidence hashes to avoid self-reference.

At entry, every file in E3's full implementation manifest matched and all six saved estimates independently restored/recomputed with their original IDs and export hashes. The [E3 recheck ledger](../evidence/e4/e3-recheck.json) preserves this evidence. E3 implementation digest at entry was `c93dae7a91a2a31b785c62d806c68044dcca9d16be59ad6b7e21c141be79ffc6`.

Existing uncommitted work was preserved. Only three preexisting implementation files required additive compatibility changes, listed below. All other entry files—including README, roadmap, E1/E2/E3 evidence, historical captures and the prepared E4 handoff—remain byte-identical. [Before](../evidence/e4/preservation-before.json) and [after](../evidence/e4/preservation-after.json) preservation records identify the exact changes. The Desktop tracker is outside Git; its [prior text](../evidence/e4/tracker-before.md) is retained.

Archived SDA remains clean at `b63ad4d985ab9e8d007767e2b97c78b4783d7c65`; Scroll Down remains clean at `087411753d6f4a2665820f84bf6270b08d05ea91`. No commits, push or publishing occurred.

## Changed files and behavior

| Files | Result |
|---|---|
| `app/opportunities/__init__.py`, `service.py` | Shared dependency-bound evaluation; replay-verified E3; exact prediction target/book/rule binding; cutoff/freshness validation; separate Arb/Mispricing state cashflows and statuses; fixed-basis within-class ranking; immutable versioned export and recomputation. |
| `app/opportunities/fixtures.py` | New explicitly invented receipts of existing NFL fixture books, separate complete/missing unconditional scenario models, positive/negative economics. Existing fixture and E3 files are unchanged. |
| `app/opportunities/storage.py` | Explicit-connection durable service entry point; complete immutable input objects, E3 foreign key and per-audit links; read validation and fresh-store restore. |
| `app/opportunities/verify_storage.py` | Fresh identity-checked socket-only PostgreSQL verifier, actual restart, fresh-store exact replay, corruption rejection, compatibility checks, foundation suite and cleanup. |
| `app/storage/migrations/006_opportunities.sql` | Three additive immutable E4 tables, foreign keys, cutoff index and SQL mutation rejection. |
| Existing `app/storage/store.py` | Capture compatibility accepts the exact E3 five-migration prefix alongside pre-E2/E2/current E4 prefixes; original migration hashes and capture semantics remain unchanged. |
| Existing `app/pricing/verify_storage.py` | E3 verifier's migration count follows installed migration files so the additive sixth migration does not break its setup. Existing E3 evidence is unchanged. |
| Existing `integration_tests/test_storage.py` | Current migration-count expectation becomes six. |
| `tests/test_opportunities.py` | Sixteen focused service/economics/replay tests, including independently derived results and precision boundaries. |
| E4 contract/report, E5 handoff, `evidence/e4/`, Desktop tracker | Final scope, exact identity, walkthrough, verification, cleanup and next action. |

[Service contract](e4-contracts.md) documents exact policy, monetary units, status/ranking semantics, restore order and limitations. Existing settlement, fee, detector and depth calculation implementations were reused unchanged.

## Verification

| Check | Result and evidence |
|---|---|
| Service, pricing, reference, E1 contracts, models, detector, depth, fees, event/market matching and normalization | **274 passed**, 66.879 seconds. Includes **16 E4 service tests**. [Full output](../evidence/e4/focused-tests.txt). |
| PostgreSQL foundation suite | **26 passed**, exclusively rebound to the verified disposable cluster before setup. [Output](../evidence/e4/durable/foundation-storage-tests.txt). |
| Durable chain | Original reference bundle → six original persisted E3 estimates → seven service evaluations → immutable audits and dependencies. **6 fair-price records, 35 E3 links, 7 E4 audits, 13 shared input objects, 56 E4 links**. [Identity/check ledger](../evidence/e4/durable/storage-verification.json). |
| Real durability | All seven audits and links reread successfully after actual PostgreSQL shutdown/restart with `fsync=on`. |
| Fresh-store replay | Full reference export, six E3 estimates, seven E4 exports, exact recomputation and rankings match. Original/restored file pairs and exact IDs/hashes are in the durable ledger. |
| Mutation/dependency rejection | SQL UPDATE/DELETE blocked on all three E4 tables; dangling dependency foreign key rejected; changed result and late knowledge rejected before persistence. Controlled corruption probes rejected missing links and changed payloads, then rolled back and reverified the intact record. Restore into an empty store rejects absent E3/reference dependencies. |
| Format compatibility | Original E1/reference/pricing tests pass; actual retained pre-E2 capture restores and replays its detector; actual E2/E3 and new E4 capture exports restore into separate fresh stores with exact migration prefixes. |
| Preservation/cleanup | All unrelated entry files and archived source copies preserved; both disposable clusters stopped and removed; final candidate hashes and whitespace check recorded in verification. |

### Required cases covered

- All six E3 estimates retain unavailable expected economics. The saved roughly 0.525/0.475 values remain conditional on a normal team-winner result; exceptional mass and unconditional value are not invented.
- Complete invented unconditional probability model with independently calculated positive and negative net results. Every material state is enumerated; target/payout hashes and any claimed target value are checked against the probabilities.
- Missing/null mass stays unavailable; negative/out-of-range/nonfinite probabilities, excess mass, extra outcomes, wrong target/payout bindings and unsupported policy/model versions are rejected.
- Unknown fee contexts/account precision, unresolved PMUS settlement charges, unknown quantities, invalid increments/minimums, insufficient depth and unverified units propagate explicitly.
- Exceptional 0.5 payouts, unknown cancellation outcomes, changed exceptional payouts and acquisition-cost refunds retain their exact state cashflows. Unknown material outcomes do not become a worst-case guarantee; known-state diagnostics remain separate.
- Kalshi order grouping/rounding refunds and PMUS cumulative order rounding are tested; depth cost is charged once through consumed prices. No maker exemption/rebate or international PMUS economics is assumed.
- Stale book and excessive receipt skew suppress ranked net results while retaining conditional diagnostics. Late receipt, later-known rules/fee assessments, future source clock and nanosecond cutoff violations are rejected. Equality boundaries and ambient Decimal context independence are tested.
- Rankings stay within signal class, event, cutoff, quantity and model identity; unknown rows are explicit. Related scenarios retain shared-liquidity families and have no aggregate attainable profit.

### Failures found and resolved

Initial service checks found a test oracle that omitted Kalshi's documented order rounding refund, and a target-rule lookup that could select an older retained market revision by iteration order. The oracle now includes the refund; the service binds target rules to the detector's exact market hashes. Initial failures remain in [the initial log](../evidence/e4/service-tests-initial.txt).

The first durable run passed persistence, restart and fresh-store E4 replay, then stopped when the capture reader correctly rejected a second import into a nonempty compatibility-test database. Its cluster was removed. The verifier now allocates a separate fresh database per format check. [Initial failure/cleanup](../evidence/e4/durable-initial/storage-verification.json) is preserved. The final run used a newly created cluster and passed all checks. An intermediate 273-test success is also preserved; final verification includes the added exact-time boundary test.

## One-event walkthrough

Synthetic event: ATL/PIT, invented kickoff September 13, 2026 17:00 UTC. Evaluation cutoff: 16:59:40 UTC. These are fixture clocks, not current market observations.

1. Restore the original full E3 reference history and saved estimate `762476841c10983a4e3c6f7902fb7e06d902acc6575a63d42c3c973998cc53f8`, whose original export SHA-256 remains `085505afbe1270832b86ff4524e9a7e29fa8960e0ba59580f751bbf25fb29e3e`.
2. Introduce separately identified synthetic book receipts using the existing Slice 11 price/depth fixture structure. Acquire three Kalshi ATL contracts and three PMUS PIT contracts at 0.20 each under the retained invented settlement/account assumptions.
3. Existing engines produce total entry cash **1.27 USD** and modeled worst-case net **1.73 USD**, conditional on both specified fills and compatible settlement. All normal and exceptional state cashflows remain in the audit.
4. E3 Mispricing remains **unavailable**, precisely because its probability basis omits unconditional exceptional mass. Audit: `434a49f6f7532c616e607fb61561441ec50cce656ffb3c279c5e3329c83a4dbc`.
5. Select a separate explicitly invented complete model: ATL 0.60, PIT 0.33, each of seven exceptional states 0.01. Under the fixture's 0.5 exceptional payouts, target value is `0.60 + 7 × 0.01 × 0.5 = 0.635` USD/contract. Expected gross payout for three is 1.905 USD. At price 0.20, cost 0.60 plus fee 0.04 yields **+1.265 USD**. At price 0.80, cost 2.40 plus fee 0.04 yields **−0.535 USD**. Neither calculation changes E3.
6. Persist, restart PostgreSQL, export, restore a fresh store, recompute and compare byte-exact outputs and rankings.

| Saved case | Arb modeled worst-case net USD | Mispricing modeled expected net USD |
|---|---:|---:|
| Original E3 basis | 1.7300 | Unavailable |
| Complete invented model, 0.20 target ask | 1.7300 | 1.265000 |
| Same invented model, 0.80 target ask | −0.0700 | −0.535000 |
| Missing exceptional probability mass | 1.7300 | Unavailable |
| Unknown quantity | Unavailable | Unavailable |
| Unknown target account fee precision | Unavailable | Unavailable |
| Stale book | Unavailable | Unavailable |

For a separate four-contract depth test, Kalshi costs `3 × .20 + 1 × .80 = 1.40`; rounded charges total .06 with a .01 order rounding refund. Entry cash is **1.45**, expected payout **2.54**, expected net **1.09 USD**. PMUS rounds its same-order cumulative raw fee .0384 to .04. These independent oracles verify grouping and avoid double-counting impact.

Runnable checks:

```sh
.venv/bin/python -m unittest tests.test_opportunities -v
.venv/bin/python -m app.opportunities.verify_storage
```

The durable command creates and removes its own isolated cluster, uses no owner connection defaults, and writes E4 evidence. Preserve existing evidence before rerunning if a separate candidate record is needed.

## Cleanup, limitations and stop

Final cluster: `/private/tmp/e4pg-3p_7djh3`, socket-only port 55482, user `e4_disposable`, empty TCP listen address, local socket permissions 0700 and `fsync=on`. Each connection checked database/user/data directory/socket/port/TCP/fsync identity. It was stopped and the temporary root removed; final filesystem verification confirms absence. The initial failed verifier's cluster was also stopped and removed.

No owner database, owner service, provider request, credentials, signup/subscription, outreach, UI implementation, sustained collection, lead/lag, maker modeling, trading, commit, push or publishing occurred. The **250 ms gate remains deferred**.

Limits: one synthetic event; existing one-family uncalibrated E3 baseline; invented pairing, rule and fee applicability; invented unconditional models; one explicit equal quantity for Arb and one target leg per audit; both ladders required for the shared service; modeled taker fill partition with unknown actual fragmentation; no portfolio liquidity allocation. Synthetic arithmetic and durable engineering success do not establish live source qualification, calibration, attainable profitability, owner acceptance or release acceptance.

**Stop reached: E4 complete offline.** The [E5 handoff](e5-handoff.md) proposes one separately authorized saved synthetic market-watch walkthrough; no E5 implementation was started.
