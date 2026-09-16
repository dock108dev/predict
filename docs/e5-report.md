# E5 — bounded synthetic NFL market-watch walkthrough

September 15, 2026. **E5 is complete for the authorized file-only synthetic preview and engineering/browser verification scope.** Owner feedback and acceptance are not recorded. No E6 implementation was performed; the 250 ms gate remains deferred.

## Exact candidate

- Unchanged Git HEAD: `0ab12b1e7b57f4ea89b6886c3d69b2459afaa258`.
- E5 implementation digest: `6ad13beea76e45d8a429985347fd422075d3759f447ec072836b4df20a368a33`.
- Full retained implementation digest: `6e6e33e22cf6e2fdf66371ec34c7d1c48143db3792280fdb04bf271f6494429a`.
- [Exact file manifest](../evidence/e5/candidate-implementation.json). Each digest hashes a sorted file-to-SHA-256 map using compact canonical JSON. Documentation and screenshots are hashed separately in [final verification](../evidence/e5/verification.json).

The [entry recheck](../evidence/e5/entry-recheck.json) matches all 131 files in E4's full implementation manifest. E3 has only the three known E4 changes documented in the E4 report: storage compatibility, disposable verifier migration count and its integration test. Archived SDA and Scroll Down remain clean at `b63ad4d985ab9e8d007767e2b97c78b4783d7c65` and `087411753d6f4a2665820f84bf6270b08d05ea91`. All preexisting repository files, uncommitted work, evidence and source copies are preserved. The Desktop tracker is the only preexisting file edited; its prior text is retained in this evidence folder.

## Operable preview and exact controls

Open **[the isolated preview](http://127.0.0.1:8775)**. It is left running and open on the E3 baseline for owner review.

From any directory:

```sh
/Users/michaelfuscoletti/Desktop/prediction-arb/scripts/e5-preview start --port 8775
/Users/michaelfuscoletti/Desktop/prediction-arb/scripts/e5-preview status
/Users/michaelfuscoletti/Desktop/prediction-arb/scripts/e5-preview stop
```

Start is idempotent while its matching process is running. If the requested port is occupied, it chooses the next free loopback port and prints the actual URL. Status identifies that URL and process. Stop checks PID, actual command and process start time before signaling only this preview, then waits for exit. Runtime state/log: `.local/e5-preview/process.json` and `server.log`. Browser bookmarks are scoped to the exact origin, so use the printed URL; changing ports does not carry a browser bookmark across origins.

No owner-dashboard command, default owner connection helper, migration or provider transport is used. The server runs with a minimal environment containing no inherited credential variables. Its process guard rejects outbound connections, child processes, database connection entry points and credential-file reads. The only application routes are the page, its local assets and the file replay package. CSP limits page connections to the same origin. Live and Historical controls are visibly unavailable; every presented case is Synthetic.

## What changed

| Files | Behavior |
|---|---|
| `app/dashboard/e5_preview.py` | Existing aiohttp framework, isolated entry point, saved E3/reference resolution, E4 restore/recompute, original E4 ledger identity checks, Decimal presentation, original E4 ranking and file-only process guards. |
| `app/dashboard/e5_static/index.html`, `watch.css`, `watch.js` | Event screen, conditional estimate, scenario selection, books, separate signals/ranking, fee/depth/outcome details, reference cutoff navigation, loading/empty/error states and browser bookmark reopening. |
| `app/dashboard/e5_static/state.js` | Stable selection identities, exact saved bookmark verification and degradation dismissal/recovery. |
| `scripts/e5-preview` | Credential-free launch environment, free loopback port selection and verified process Start/Stop. |
| `tests/test_e5_preview.py`, `test_e5_state.cjs` | Focused loading, dependency, money, ranking, route/isolation and interface-state checks. |
| `tests/e5_browser_states.py` | Separate test-only loopback server for observable loading, empty and validation-error screens. Not part of the review server; stopped after verification. |
| `tests/e5_verify_files.py` | Repeatable two-pass file replay and isolation proof; refuses to overwrite an existing evidence output. |
| This report, `evidence/e5/`, Desktop tracker | Candidate, screenshots, repeatability, limits and one review action. |

The existing dashboard's stylesheet is served directly and its header, panel, tab, status, table and expandable-detail components are extended with native DOM/CSS. Existing controller, collector, dashboard JavaScript, engines and storage files are unchanged. E1's Scroll Down degradation pattern is adapted: dismissing the summary does not hide unavailable row states, and degradation reappears after recovery. No React migration, source-package copying or edits to archived applications.

## Saved evidence and economic presentation

Every request validates the complete saved reference history, restores all six saved E3 estimates, compares their exact as-of dependencies, and restores/recomputes all seven E4 audits. Each E4 audit ID, export SHA-256, estimate ID and book IDs must match E4's saved verification ledger. No result is displayed if validation fails. All economics come from those engine replays; the browser performs no monetary arithmetic.

Baseline: saved estimate `762476841c10983a4e3c6f7902fb7e06d902acc6575a63d42c3c973998cc53f8`. Its **52.5% is conditional on a normal team-winner result**, from one synthetic information family. Exceptional probability mass, unconditional target value and expected profit remain unavailable. The top baseline remains pinned when exploring separate reference cutoffs or invented scenarios.

| Saved case | Arb worst-case net USD | Mispricing expected net USD |
|---|---:|---:|
| `e3-unavailable-ev` | +1.73 | Unavailable |
| `invented-positive` | +1.73 | +1.265 |
| `invented-negative` | −0.07 | −0.535 |
| `invented-missing-mass` | +1.73 | Unavailable |
| `unknown-quantity` | Unavailable | Unavailable |
| `unknown-fees` | Unavailable | Unavailable |
| `stale-book` | Unavailable | Unavailable |

These are alternative synthetic scenarios, never an aggregate profit. Complete invented cases retain the independently assumed 0.635 USD target value. Mispricing positive capital is 0.64 USD and negative capital is 2.44 USD; Arb uses both legs' entry cash plus consumed reserve (1.27 USD in the baseline). Size is three contracts per Arb leg or three on the Mispricing target. Per-contract displays are rounded to six decimal places; percentage returns to four decimal places with Decimal half-even formatting. Exact fractions and cashflows remain in details. Arb per-contract means one equal-quantity two-leg unit, not the sum of leg quantities.

Reference navigation exposes retained receipts, provider reads, their ages at the chosen cutoff, exclusions and discrete delivered-odds comparisons. Equal receipt timestamps explicitly have no temporal ordering. Bookmaker change times remain unknown; there is no interpolation or claim that every upstream change was captured. Different same-cutoff scenarios do not alter the reference timeline. A selected receipt absent at an earlier cutoff remains selected by identity with an unavailable explanation. Book selection and open details persist across scenario changes, including unknown/stale cases.

Saved audit reopening stores the case key, complete audit ID, exact export hash, selected book, signal, reference cutoff/receipt and open panels. Reopening and page reload fetch and validate the files again, then require the exact identities. A changed or missing bookmark target fails closed; the user may explicitly clear the browser bookmark and open the baseline. This does not remove any source audit.

## Verification — engineering and browser evidence

| Check | Result |
|---|---|
| Focused Python tests | **10 passed**: seven expected cases; reference ages/binding; exact display denominators; unknowns/ranking; tampered audit; missing/mismatched dependencies; absent collector routes; fail-closed API; shared stylesheet/CSP. [Log](../evidence/e5/focused-tests.txt). |
| Interface state | Passed stable identity, missing selection, degradation → dismiss → recover → degrade, exact bookmark roundtrip and mismatch rejection. [Log](../evidence/e5/ui-state-tests.txt). |
| File repeatability | Two independently loaded packages are byte-identical, including seven original E4 audit identities and six E3 estimates. Four process guards reject attempted network, DB, subprocess and credential-file operations before they occur. No collector, keyring or dotenv module is loaded. [Final ledger](../evidence/e5/repeatability-final.json). |
| Launcher | Idempotent Start, verified Stop, restart on 8775 and full package retrieval pass. Served package hash matches the final file replay. [Ledger](../evidence/e5/launcher-verification.json). |
| Actual browser, desktop | 1440×1000: E3 unknown EV, invented positive/negative, missing mass, unknown quantity/fees, stale input, both ranking views, fee/refund/depth/outcomes, stable fee panel, reference tombstone and saved reopening/reload verified. [Case observations](../evidence/e5/desktop-cases.json), [reopening](../evidence/e5/reopened.json). |
| Actual browser, narrow | 390×844: all seven scenarios, conditional/invented labels, book/details, unknown/stale net, absent reference selection and exact saved reload verified. Document width remains 390 pixels for all cases; detailed tables scroll within their panel. [Cases](../evidence/e5/narrow-cases.json), [reload](../evidence/e5/narrow-reload.json). |
| Loading/empty/validation-error UI | Observed in the actual browser at both sizes using the separate, explicit test-state server. Empty/error states reveal no fallback economics. The changed-identity error is test-only, not a change to saved evidence. [Narrow state snapshots](../evidence/e5/narrow-states.json). |
| JavaScript and console | Both new JavaScript files pass `node --check`; review-tab warning/error console is empty. [Console](../evidence/e5/browser-console.json). Expected HTTP 422 belongs only to the deliberate validation-error test. |
| Preservation | Original E4 implementation/evidence and all preexisting repository files retain their entry hashes; archived sources retain exact revisions and clean status. [Final ledger](../evidence/e5/verification.json). |

### Visual evidence — separate from owner feedback

- [Desktop baseline](../evidence/e5/desktop-baseline.png)
- [Final desktop invented positive result](../evidence/e5/desktop-positive-final.png)
- [Narrow conditional baseline, 390 pixels](../evidence/e5/narrow-baseline-390.png)
- [Narrow positive result](../evidence/e5/narrow-positive-final.png)
- [Narrow stale state](../evidence/e5/narrow-stale.png)
- [Loading](../evidence/e5/loading.png), [empty](../evidence/e5/empty.png), [validation error](../evidence/e5/validation-error.png)
- Narrow [loading](../evidence/e5/narrow-loading.png), [empty](../evidence/e5/narrow-empty.png), [validation error](../evidence/e5/narrow-invalid.png)

Visual checks show readable labels, intact panels and no page-wide horizontal overflow at the tested narrow width. Dense receipt/fee tables intentionally retain internal scrolling and expandable exact data. Screenshots and browser checks are engineering verification only. **Owner feedback: none collected. Owner acceptance: not claimed.**

### Issues found and resolved

The first launcher's command check did not account for macOS reporting Python's resolved executable path. It refused to stop the process, as designed, but caused a second isolated preview to be launched. Both exact E5 processes were identified and stopped; the initial evidence is retained. The launcher now records the actual command plus start time, waits for shutdown and allows reusing a recently closed port. Final Start/Stop/restart checks pass. No owner service was touched.

The first narrow viewport override applied to the most recently created test tab, leaving the desktop review tab at 1440 pixels. That initial screenshot is retained as `narrow-baseline.png` but **is not narrow-screen evidence**. The actual 390-pixel tab was measured and used for all final narrow checks. Browser loading exceeded one short locator deadline during a replay; the loading state remained visible and the completed replay was checked subsequently. No latency gate is inferred.

## Repeat and review

```sh
cd /Users/michaelfuscoletti/Desktop/prediction-arb
.venv/bin/python -m unittest tests.test_e5_preview -v
node tests/test_e5_state.cjs
node --check app/dashboard/e5_static/watch.js
node --check app/dashboard/e5_static/state.js
.venv/bin/python -m tests.e5_verify_files --output /tmp/e5-new-replay-check.json
```

Choose a new filename for each replay evidence run. No database is needed or initialized.

**One concrete next action:** owner reviews the open synthetic preview: inspect E3's unavailable EV → choose invented positive/negative → inspect fees/depth/outcomes → choose stale/unknown → save an audit, switch cases, reopen it and reload. Record the owner's actual feedback against this candidate before proposing further implementation.

## Limits and stop

One invented ATL/PIT event, one reference family and partial prediction ladders. No calibration, empirical exceptional probabilities, verified fill feasibility or real profitability. Conditional fee/rule assumptions remain visible. Reference history has six saved evaluation cutoffs; scenario alternatives share one E4 cutoff. File replay is intentionally synchronous and takes several seconds; this package has no sustained ingestion or performance qualification. Full original engine evidence is reused because no economic engine changed; no database regression suite or original verifier was rerun.

No provider request, credentials, signup/subscription, outreach, owner-database access, migration, owner-service restart, sustained collection, trading, commit, push or publishing. **Stop reached: E5 only; E6 remains unstarted and separately scoped.**
