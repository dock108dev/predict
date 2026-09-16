# E3 completion report — bounded offline our-price baseline

September 15, 2026. **E3 is complete for the authorized synthetic offline engineering scope.** Neither provider is live-qualified; this is not model calibration, owner acceptance or release acceptance. Work stops after E3. [One E4 handoff](e4-handoff.md) is prepared only.

## Exact candidate

- Unchanged HEAD: `0ab12b1e7b57f4ea89b6886c3d69b2459afaa258`.
- Uncommitted E3 implementation digest: `c93dae7a91a2a31b785c62d806c68044dcca9d16be59ad6b7e21c141be79ffc6`.
- Full app/test implementation digest, including retained E1/E2 dependencies: `18e8d627f8fecaad38a1681db23aed503f5def1dd5ed411804364fc58fd91c76`.
- [Exact implementation file manifest](../evidence/e3/candidate-implementation.json), [entry preservation manifest](../evidence/e3/entry-manifest.json), [final verification and document/evidence hashes](../evidence/e3/verification.json). Digests are SHA-256 of canonical sorted file-to-SHA-256 maps; the manifest defines their exact scopes. Report/evidence files are hashed separately to avoid self-reference.

Existing uncommitted work was retained. Necessary extensions to three existing implementation files are listed below; other entry files, including E1/E2 evidence, README, roadmap and E3's original handoff, are byte-preserved. The Desktop tracker is outside Git and is updated separately. Archived SDA and Scroll Down copies remain clean at `b63ad4d985ab9e8d007767e2b97c78b4783d7c65` and `087411753d6f4a2665820f84bf6270b08d05ea91` respectively.

## Changed files and behavior

| Files | Result |
|---|---|
| `app/pricing/__init__.py`, `baseline.py` | Versioned synthetic target/policy, receipt-bound latest-snapshot selection before eligibility, target/copy and unknown exclusions, proportional Decimal de-vig, explicit conditional probabilities and unknown exceptional mass, immutable content-addressed audit, export/restore and exact recomputation. |
| `app/pricing/storage.py` | Explicit-connection persistence through existing Store; all receipt/enrichment/source dependencies and candidate links, complete as-of validation under reference-table locks, immutable retries, durable export/restore and link verification. |
| `app/pricing/fixtures.py` | Reuses the existing E2 invented NFL event; complete then rejected receipt example and explicit synthetic target assumptions. |
| `app/pricing/verify_storage.py` | Restores the actual E2 evidence bundle into a new cluster, saves six estimates, restarts PostgreSQL, restores a fresh store, verifies exact replay, runs compatibility/regression checks and removes its cluster. |
| `app/storage/migrations/005_fair_price.sql` | Additive `fair_price` and `fair_price_input` tables, foreign keys, time index and SQL mutation rejection. |
| `app/storage/store.py` | Extends existing capture reader compatibility from pre-E2/current E2 to exact pre-E2/E2/current E3 migration prefixes with original hashes. No capture table/format reinterpretation. |
| `app/reference/verify_storage.py` | Keeps the existing reference verification runner usable after additive migrations by counting installed migration files instead of hardcoding four. Existing E2 evidence remains unchanged. |
| `integration_tests/test_storage.py` | Current schema count expectation increases from four to five. |
| `tests/test_pricing.py` | Sixteen focused calculation, eligibility, time, settlement and exact-replay tests. |
| `docs/e3-contracts.md`, this report, `docs/e4-handoff.md`, Desktop tracker, `evidence/e3/` | Complete policy/format contract, walkthrough, exact identities, durable evidence, final status and one prepared E4 action. |

The [E3 contract](e3-contracts.md) documents exact parameters, status behavior, units, selection and restore order. The original E1 `FairPrice` remains readable as its original illustrative contract. E3 deliberately uses a new receipt-bound estimate format rather than inheriting E1's latest-eligible structural policy.

## Checks and evidence

| Check | Result |
|---|---|
| Pricing, reference, E1 contracts, models, arbitrage, depth, fees, event matching, moneyline and normalization | **258 passed**, 32.401 seconds. [Full output](../evidence/e3/focused-tests.txt). Includes **16 E3 tests**; [focused pricing output](../evidence/e3/pricing-tests.txt). |
| Existing PostgreSQL foundation suite, connection rebound before setup to the identity-checked disposable cluster | **26 passed**. [Output](../evidence/e3/durable/foundation-storage-tests.txt). |
| Durable E2 → E3 pipeline | Five migrations and idempotent reapply; **10 reference receipts, 13 enrichment revisions, 3 source revisions, 6 fair-price records and 35 candidate links**. [Identity/check ledger](../evidence/e3/durable/storage-verification.json). |
| Real server durability | All six estimates and links survived a PostgreSQL shutdown/restart with `fsync=on`, then were reread and validated. |
| Fresh-store restore | Full reference export, six estimate exports, their exclusions and all six as-of replays are byte-identical. Exact recomputation from restored dependencies matches every original. Original/restored pairs are in [durable evidence](../evidence/e3/durable/). |
| Mutation and omission rejection | SQL update/delete blocked for estimates and links; idempotent retry passes; changed calculation, late dependencies and omitted newest receipt rejected before persistence. |
| Reference compatibility | Original E2 `reference-bundle-1` restored byte-identically, including archived download/alias/source/rule knowledge and rejected observations. Original E2 evidence is read-only. |
| Capture compatibility | The original pre-E2 `capture-bundle-1` restores on five migrations and its saved detector audit replays. An explicitly constructed E2 migration-prefix capture bundle also restores. E1/reference unit checks retain their original formats. |
| Cleanup and preservation | Identity checks, cleanup, `git diff --check`, entry-file and archived-source checks recorded in final verification. No owner database/service access. |

Initial pricing validation caught a test's mistaken assumption that the existing fixture's cancellation payout was a refund. The fixture actually specifies an invented 0.5 fraction. The test expectation was corrected, original fixture preserved, and separate matched/incompatible/unknown/discretionary refund cases added. [Initial failure log](../evidence/e3/pricing-tests-initial.txt) remains preserved. The durable run passed on its first run.

### Required-case coverage

- Independent rational calculation: `b/(a+b) = 21/40`, not expected values copied from the implementation. Exact original high-precision E2 odds and `2.1000` scale survive durable replay.
- Complete/missing/invalid/stale pairs; absent provider-read time; unverified pairing, unknown lineage and rules; target-origin/family/copy exclusions and duplicate delivery sessions.
- A latest malformed snapshot or a latest receipt with no then-known enrichment blocks stale fallback. Every earlier receipt remains in exclusions.
- Late historical downloads cannot enter earlier receipt cutoffs. Later source/rule/alias knowledge cannot modify saved estimates; effective, receipt and knowledge equality boundaries are inclusive. Nanosecond receipt/source distinctions use exact retained time text.
- Pregame buffer and kickoff exclusion; target rule mismatch for tie/overtime/cancellation; matched refund remains symbolic; unknown/discretionary material settlement remains ineligible.
- Explicit degraded/unavailable states, valid probabilities, documented rounding, opposite target predicate and both initial prediction target venues. Full recomputation ignores ambient Decimal context.
- Changed policy/version/hash/output rejected; deterministic ordering; byte-exact exports/replay including all excluded inputs; reference and capture backward compatibility.

## One-event walkthrough

The durable runner begins with the **actual saved E2 synthetic ATL/PIT reference bundle**, preserving its invented September 13, 2026 17:00 UTC start. These are synthetic fixture clocks, not current market data. E3 saves the following Kalshi-target timeline:

| As-of UTC | Result | Reason / calculation |
|---|---|---|
| 16:58:59 | Unavailable | No receipt yet known. |
| 16:59:01 | Unavailable | Latest pair lacks then-known pairing, lineage and rule assessments. |
| 16:59:15 | Unavailable | Latest alias receipt is unresolved at this cutoff; older complete-looking data is not substituted. |
| 16:59:25 | Degraded | Later alias/source/rule assessments are now known; the latest pair is eligible under explicit synthetic assumptions. |
| 16:59:40 | Degraded | The latest historical download is eligible by its actual receipt time. Odds `1.90000000000000000001` / `2.1000` normalize to `0.525000000000000000` / `0.475000000000000000`. |
| 16:59:50 | Unavailable | A newly saved rejected arrival takes the current snapshot slot. Later copy knowledge is retained too; earlier estimates stay unchanged. |

The 16:59:40 estimate ID is `762476841c10983a4e3c6f7902fb7e06d902acc6575a63d42c3c973998cc53f8`. Its export hash is `085505afbe1270832b86ff4524e9a7e29fa8960e0ba59580f751bbf25fb29e3e`: [original](../evidence/e3/durable/estimate-4.json), [fresh-store export](../evidence/e3/durable/estimate-4-restored.json). The complete six-record ID/hash ledger is in durable verification.

Each degraded probability is conditional on a normal team-winner result, with one information family and weight one. It is not an unconditional prediction-contract fair value. Every exceptional probability, unconditional target probability, target USD fair value and net expected profit remains unknown. Settlement compatibility cannot supply missing probability mass. De-vigging does not pay prediction-market trading fees.

## Cleanup and stop

The verifier created only `/private/tmp/e3pg-l2jd41ty`, with its own data directory and socket, port 55481, user `e3_disposable` and empty TCP listen address. Every connection checked database, user, data directory, socket, port, TCP setting and `fsync`. PostgreSQL was stopped and the entire temporary root removed; final verification checks its absence. Owner connection defaults, owner databases and owner services were not used.

No provider requests, credentials, signup/subscription, outreach, sustained collection, UI expansion, E4 economics, trading, commit, push or publishing occurred. The deferred **250 ms gate remains deferred**.

**Remaining limitations:** wholly synthetic pairing/lineage/target-rule assumptions; one provider/book/event; no qualified live cadence, upstream synchronization, complete real copy lineage or bookmaker-change time; no multi-source diversity, calibration, unconditional outcome model or supported net expected return. Offline engineering completion does not resolve source qualification or imply owner acceptance.

**Stop reached: E3 complete offline.** The [E4 handoff](e4-handoff.md) proposes one separately authorized synthetic Arb/Mispricing service, preserving unavailable expected economics until all material outcome probabilities/costs are supported.
