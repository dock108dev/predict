# E1 completion report

**Status: complete for the authorized local, offline E1 scope — September 15, 2026.** Shared executable contracts, targeted reuse decisions and examples, one synthetic NFL event walkthrough, focused verification and the concrete E2 boundary are delivered. E2–E10 remain unstarted. Owner live try/acceptance remains separate and unrecorded by this work.

## Exact candidate and preserved state

- Predict root: `/Users/michaelfuscoletti/Desktop/prediction-arb`.
- Origin: `https://github.com/dock108dev/predict.git`; branch `main`; base HEAD **`0ab12b1e7b57f4ea89b6886c3d69b2459afaa258`**. HEAD is unchanged; this candidate is an **uncommitted working tree**, not a new commit or remote release.
- Implementation content digest: **`5427e0d253a837ec87ff29005325764bbe81b8dba63904ebfb54b602eb1b1899`**. Defined as SHA-256 of compact, sorted JSON mapping the six implementation/check/example paths below to their file SHA-256 values.
- [candidate-identity.json](../evidence/e1/candidate-identity.json) records exact final implementation and delivered-file hashes, source identities, branch/origin/status and Desktop tracker hash. It excludes itself from the hash map to avoid self-reference.
- At entry, `README.md` and `docs/product-roadmap-review.md` already had local-source guidance edits. They were preserved **byte-for-byte**, verified against [baseline.json](../evidence/e1/baseline.json). No E1 edits were made to either file. Applicable instruction search found no AGENTS.md in Predict or its parent chain; neither source checkout supplied one.
- SDA: `main`, **`b63ad4d985ab9e8d007767e2b97c78b4783d7c65`**; Scroll Down: `main`, **`087411753d6f4a2665820f84bf6270b08d05ea91`**. Both remained clean at final recheck. Exact inspected paths and hashes: [audit-sources.json](../evidence/e1/audit-sources.json).

## Delivered files

| File | Change / purpose |
|---|---|
| `app/edge_contracts.py` | New immutable reference, terms, fair-price, economics and four signal models; receipt/source/term eligibility checks; isolated versioned exact-value codec. Reuses core units and existing settlement/digest logic. |
| `app/arbitrage.py` | Runtime type checks for executable `Observation.quote` and `book_observations`; depth book conversion shares the guarded path. No fee, detection or depth arithmetic changed. |
| `app/e1_example.py` | One synthetic ATL/PIT pregame walkthrough alongside native Kalshi/Polymarket US books and existing detector replay. |
| `tests/test_edge_contracts.py` | Twenty focused E1 tests covering rejection, cutoffs, identity, terms, unknowns, units and exact replay. |
| `examples/e1/paired_reference.py` | Runnable local SDA paired-outcome traversal adaptation. |
| `examples/e1/status_banner.mjs` | Runnable local Scroll Down dismissal/recovery state adaptation. |
| `docs/e1-contracts.md` | Compact schema/interface specification and ownership/limitations. |
| `docs/e1-reuse-audit.md` | Eleven extract/adapt/skip rows, source revisions/paths, dependencies, licensing findings, effort and rationale. |
| `docs/e2-handoff.md` | One adapter boundary, proposed immutable storage/mapping responsibilities and provider verification matrix. |
| `docs/e1-report.md` | This completion/evidence record. |
| `evidence/e1/` | Baseline, final source and candidate identities, initial/final test output, two extraction outputs, exact walkthrough and verification summary. |
| `/Users/michaelfuscoletti/Desktop/prediction_arb_next_steps.md` | E1 supported completion plus one E2 next action; historical foundation/limitations preserved. Outside Predict Git. |

The six implementation digest paths are the first six rows. All new files and evidence appear in the final candidate manifest; preexisting guidance edits are separately identified rather than attributed to E1.

## Checks and results

Python **3.14.5** from the existing `.venv`; Node **v22.18.0**. No dependencies installed.

| Check | Result / evidence |
|---|---|
| `.venv/bin/python -m unittest tests.test_edge_contracts tests.test_models tests.test_arbitrage tests.test_depth tests.test_fees tests.test_matching tests.test_moneyline tests.test_normalization -v` | **213 tests passed** in 28.932 seconds. [focused-tests.txt](../evidence/e1/focused-tests.txt). Includes 20 E1 tests and foundation regression checks. |
| `.venv/bin/python -m app.e1_example` | Passed immutable model/byte-stable serialization roundtrip and existing detector replay. Output: [walkthrough.json](../evidence/e1/walkthrough.json). |
| `PYTHONPATH=. .venv/bin/python examples/e1/paired_reference.py` | Passed exact prices, ordered pairing, native keys and missing-side behavior. [sda-extraction.txt](../evidence/e1/sda-extraction.txt). |
| `node examples/e1/status_banner.mjs` | Passed persistent delayed row status, dismissal, recovery reset and explicit modes. [scroll-down-extraction.txt](../evidence/e1/scroll-down-extraction.txt). |
| `git diff --check`; final source/guidance identity checks | Passed; [verification.json](../evidence/e1/verification.json). |

Initial E1 run: 19 tests, one error in the **synthetic fixture**, because the Kalshi native book requires both yes/no outcome slots even when one observed ladder is empty. The fixture was corrected to include an explicitly empty yes bid ladder. Initial output remains at [contracts-tests-initial.txt](../evidence/e1/contracts-tests-initial.txt). Final tests include both native conversion paths. No runtime venue behavior was changed to accommodate the fixture.

### What the event proves

- ReferenceQuote is rejected by executable quote/book construction and top-of-book/depth conversion entry points. Existing native books still convert using current adapter rules.
- An earlier source timestamp cannot admit a late receipt. Inclusive cutoff, one-microsecond-late, source clock ahead, stale and wrong-mode cases are tested. Constructor and replay reject tampered inclusion decisions, even if an envelope digest is recomputed.
- Target prices/known copies are excluded; ambiguous family/lineage is ineligible. Duplicate source families use the latest eligible receipt deterministically; repeated receipt IDs fail.
- Wrong periods, swapped outcomes, different schedules and unknown rule profiles cannot enter the estimate.
- The only included reference is `ref-001`. `0.5200` is an explicitly **assigned synthetic probability**, not a fitted or de-vigged estimate. `0.1200` is a probability gap, not net dollars or ROI.
- Existing detector replay preserves unknown PMUS settlement-fee economics. All four signal records keep final net dollars/ROI null. Unknown settlement profiles cannot carry known economic results. Maker/lead-lag records expose missing evidence without implementing those strategies.
- Decimal text including `1.90000000000000000001` and scale `2.1000`, raw text/whitespace, source lineage, receipt decisions and native book types survive exact replay. Payload tampering/version changes fail closed.

## Reuse outcome

**Two adapt-pattern recommendations, nine skips, zero direct extracts.** SDA's paired traversal and Scroll Down's dismissal/recovery state each have a runnable local adaptation. Predict keeps its existing normalization/matching, fee/settlement/depth, immutable capture/replay and dashboard foundation. No framework migration is proposed.

No license file or permissive grant was found in either supplied checkout. That is a recorded constraint, not an inferred license or a failed source-identity lookup. Local audit/extraction examples are complete; direct source copying/distribution remains unverified and is not recommended by E1. No third-party source package/assets were vendored.

## Remaining limitations and stop boundary

- No provider selected or verified. Both-side delivery, source lineage, exact rules, timestamps, cadence, history, permitted reference use and cost remain E2 evidence requirements.
- E1 validates contract structure/declared unknowns and input eligibility. It does not establish provider truth, complete cost assumptions, statistical calibration, production source freshness or source-side pairing. E3/E4 must calculate and qualify those results using retained evidence and existing engines.
- No production pricing, reference provider adapter, later signal strategy, new market-watch UI or persisted-reference database implementation. Codec replay is isolated file replay, not a claim of E2 PostgreSQL integration or owner saved-history acceptance.
- No old app run, service operation, owner-database access, migration, live collection, signup/subscription, trading, commit, push or publishing. No running dashboard files changed. No new claim about runtime state was made.
- Existing venue coverage/access/settlement/sizing limitations, saved-history gaps and uncompleted owner live try remain. The deferred **250 ms performance gate was not restored or rerun**.

**Next E2 action:** build a two-candidate capability/evidence matrix (one direct-book/exchange candidate and one multi-book candidate) to determine whether either supplies one usable NFL paired moneyline with stable source identity and permitted durable reference use. Use the [handoff](e2-handoff.md); selection/access gaps stay explicit. Stop here after E1.

## Fresh verification of the existing E1 candidate

September 15, 2026: this request found the E1 implementation and completion records already present as uncommitted changes. They were preserved and independently rechecked. All entry manifest hashes (including delivered artifacts, tracker and guidance) and all audited source-file hashes matched; both source checkouts remained clean at the supplied revisions. No implementation repair was needed.

The same focused suite passed **213 tests in 28.621 seconds**. Both adaptation probes passed, and the walkthrough output was byte-identical to the saved fixture with model and detector replay successful. `git diff --check` passed. Fresh evidence: [recheck-focused-tests.txt](../evidence/e1/recheck-focused-tests.txt), [recheck-verification.json](../evidence/e1/recheck-verification.json). The entry manifest is preserved as [candidate-identity-before-recheck.json](../evidence/e1/candidate-identity-before-recheck.json); the current manifest refreshes documentation/evidence hashes. The implementation digest and base HEAD are unchanged.

This recheck updates only completion documentation, evidence and the Desktop tracker. E1 remains complete within its stated local/offline limits; the E2 next action and all stop boundaries above remain unchanged.
