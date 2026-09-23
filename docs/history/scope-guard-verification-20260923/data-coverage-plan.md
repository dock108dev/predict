# Predict — expanded beta delivery plan

**September 23 actual-run update:** corrected discovery matched a shared game, but US subscription scope expanded improperly; bounded qualification FAIL. Cleanup/replay pass. The guard is repaired and tested offline, not live-qualified. [Final report](../evidence/b6-two-source-corrected-72967ba6-7b2f-419c-9ecd-16283c9868bf/final-report.md) supersedes the generic initial PASS. Both attempts consumed; automation paused; full actual-source qualification and beta signoff OPEN.

**Owner decision — September 21:** MoneyPuck dropped from the active plan. NHL analytics/model data is **MISSING — deferred**, with no replacement search, license inquiry or further MoneyPuck request queued. Preserve completed NHL engineering and historical evidence. Independent B5 and finite B6 offline integration are complete; missing NHL analytics remains an actual-data gap. KenPom remains deferred; Novig/ProphetX replies remain pending.

Updated September 22, 2026. This plan implements the owner's [current beta scope](product-roadmap-review.md). **Beta not ready.** No B1–B7 package is complete merely because an earlier D/E/slice component passed.

## B1 — working coverage map and integration scope — COMPLETE

Delivered September 20, 2026: [source × sport × market/period matrix](b1-coverage-matrix.md) and [concrete B2 implementation handoff](b2-product-integration-handoff.md). The assessment covers all six sports, four prediction-source slots and both reference types, with production/sandbox/fixture/documentation evidence separated, explicit unknowns, source recommendations and an owning-slice dependency ledger.

ProphetX is selected as the fourth venue; production access remains a B3 dependency. The Odds API NFL Pinnacle h2h sample is complete; broader entitlement and actual delay remain unqualified. Sport-specific model candidates and their output/independence gaps are recorded. B5 implements required pregame first-half markets; second-half offered at halftime is stretch. MLB cumulative 3/5/6/regulation 9, NHL individual periods 1/2/3 and current-season conference/league championships are selected; NCAAB is men’s Division I. Remaining actual data questions do not make B1 incomplete or block B2.

B1 included code-path inspection, retained-evidence review, targeted official public research and document reconciliation. No B2 implementation, beta launch, credential/account access or new authenticated collection occurred.

## Missing-data work belongs to the slice that uses it

| Slice | Unresolved data/information to address during that slice | If unavailable |
|---|---|---|
| B3: prediction venues | Novig provisioning and wire samples; selected ProphetX production access; ProphetX size/update semantics; US Short depth and source-specific discovery/fees/terms | Mark the affected source/side incomplete, request precise owner/provider help, continue other integration work |
| B4: references | Free delayed Pinnacle route and actual delay/coverage; current power-index provider(s), sport coverage and usable probability/line outputs | Keep missing inputs explicit; continue reference plumbing and independently supported calculations; do not silently substitute paid data or another reference type |
| B5: sport/market breadth | Actual native IDs/listings, selected period/championship contracts, college venue aliases, result/settlement sources and seasonal samples | Independent engineering and owner definitions complete; qualify exact native fields when available; no silent beta exclusions |
| B6: integrated use | Actual joint coverage/cadence, session length, provider limits and resource measurements | Scope the run from available evidence; leave unmet beta criteria open rather than pretending all data problems were solved |

The [B1 dependency ledger](b1-coverage-matrix.md#owning-slice-dependency-ledger-and-owner-help) records current evidence, exact owner assistance and completion checks. Maintain each dependency's current evidence, next action, engineering/owner/provider responsibility and completion check. Unknowns are work items, not assumptions of success and not a blanket project stop. The four-plus-two/six-sport beta floor stays unchanged while slices progress.

## B2 — connect collection to the product — COMPLETE

Delivered the [shared session projection, ordinary dashboard integration and verified history readers](b2-product-integration-handoff.md). Explicit fixture sessions now update comparisons, expose source/market gaps and dated references, freeze during saving, and reopen immutable cutoffs. Three source identities and two events include a non-Kalshi pair; unknown third-source economics remain unsupported. Existing 18-Arb/96-EV math reconciliation and focused collector/history/browser checks passed. [Exact identity and evidence](../evidence/b2-product-integration-20260920/final-report.md).

This is fixture-backed integration, not production-source qualification. Real product Start remains unavailable without a new allowance. Existing D2/supervised consumed-attempt protections remain intact. B3 is in progress; real qualification is pending provider access and approval.

## B3 — four prediction venues — IN PROGRESS; real qualification blocked

[B3 engineering](b3-native-integration.md) connects Novig and a provisional ProphetX (owner-selected September 21; activation pending) REST branch through the existing collector, native observation journal, ordinary projection, source health and Stop. Source-specific purchase conversion, failure isolation, retained replay and shared-history ordering are offline verified. Kalshi series/US tag scopes are configurable; unsupported discovered native metadata remains visible. Native REST supports shared flat and segmented replay; B2 behavior is preserved.

ProphetX selection is resolved. The owner sent Novig and ProphetX access requests; both are pending provider responses. Production provisioning remains unverified; see [Novig access review](novig-access-review-20260921.md) for the documented public GraphQL alternative and its sunset limitation. No B3 QA/production collection or four-venue production comparison is qualified. Finalize the [single bounded proposal](b3-native-qualification-proposal.md) with the selected venue/access references before requesting approval and any new authenticated access. Unknown Novig listing period/rules and ProphetX sizes remain explicit prerequisites/limitations.
Exit: each of four venues has observed production input, integrated health/history and useful comparison participation; source-specific gaps are visible. Offline adapters do not count. No inference of full exchange delivery from short samples.

## B4 — independent engineering COMPLETE; actual Pinnacle sample integrated, model outstanding

[B4 implementation and offline verification](b4-independent-handoff.md) now supplies separate model/Pinnacle Details, reference EV, original-input replay and explicit local imports through the existing collector/history. [Source contracts](b4-source-contracts.md) and [bounded acquisition proposal](b4-acquisition-proposal.md) separate documentation from actual access. KenPom is deferred by owner; no login or entitlement work. The single authorized NFL Pinnacle sample succeeded (one credit, 499 remaining), with 16 actual side references in ordinary saved Details. Compatible prediction observations and settlement binding remain required for actual EV. [Evidence](../evidence/b4-pinnacle-sample-20260921/final-report.md). Full B4 remains IN PROGRESS until both actual-source roles are integrated and reproducible. No Novig or ProphetX key is required.

Implement repeatable acquisition for the selected power-index/model provider(s) and the verified free Pinnacle path. Retain model version/as-of time, source time where available, receipt time, actual delay evidence, native prices, source family and market identity. Derive supported estimates transparently and show unresolved mappings. Preserve delayed estimates as delayed; no live-quality timing prerequisite merely to display correct labeled arithmetic.

Exit: both requested reference types appear in game/market details and supported EV calculations with reproducible original inputs. No forced win-probability conversion from raw team ranks; no invented spread/total/futures forecasts. Unsupported model-market cells stay explicit beta gaps for decision.

## B5 — independent engineering COMPLETE; actual coverage IN PROGRESS

[Consolidated handoff](b5-independent-engineering-handoff.md) · [final acceptance](../evidence/b5-independent-20260922/final-report.md) · [remaining dependencies](b5-remaining-backlog.md).

| Product capability | Independent engineering state | Remaining qualification |
|---|---|---|
| Full-game winner, spread/run-line/puck-line and total | COMPLETE across NFL, NBA, MLB, NHL, NCAAF and men’s D1 NCAAB within reviewed seasons and explicit contract scope | Native listings, participant bindings, rule applicability, purchase size and fees by venue |
| Pregame partial periods | COMPLETE: football/basketball first half; MLB cumulative first 3, first 5, first 6 and regulation 9; NHL individual periods 1, 2 and 3. Winner/spread/total remain separate | Actual period IDs, completion/tie/exception terms and period-specific reference distributions |
| Sporting results and venue settlement | COMPLETE shared full-game/H1 framework plus MLB/NHL/selected periods; corrections, pending/conflicting states, independent venue decisions, as-of and immutable pregame links | Actual result/payout records; unsupported completion, pitcher, fair-value and refund terms |
| College identity coverage | COMPLETE current official directory: 266 DI football programs (2026) and 365 men’s DI basketball programs (2026–2027), additive to historical decisions | Native venue aliases/IDs, FCS-only contracts, campus/site bindings and later seasons |
| Shared payout structures | COMPLETE explicit fractional/equality/three-way truth tables, purchase-stake pushes and categorical championship states | Real cross-strike/ternary native books and third-leg economics; exceptional probabilities, void/fair-value amounts and fee returns |
| Conference/league championship futures | COMPLETE current-season identity, horizon, full field, exclusive/overlapping states, explicit probability mass, pending/eliminated/result handling | Native fields, source-specific award/no-award rules, actual forecasts and executable economics |
| Ordinary product and history | COMPLETE filters, Details, source isolation, references, Stop, flat/segmented compatibility and exact saved reopening; oversized legacy flat input rejected before materialization | Actual jointly scoped six-source use and owner beta review; finite B6 offline integration complete |

Owner definitions are resolved: men’s D1 basketball; cumulative baseball 3/5/6/regulation 9; individual hockey periods 1/2/3; current-season conference/league championships. H2-at-halftime and live/in-play remain stretch. Historical tiny college rosters and sport-by-sport next instructions are superseded; [exact planning snapshots](history/b5-independent-20260922/README.md) and original handoffs remain preserved.

Exit for **full B5** still requires actual source/market coverage reconciled against the matrix, exact native rule/economics qualification, supported reference/result inputs and practical integrated use. Offline fixture success does not satisfy those data requirements or owner acceptance. No hidden beta exclusions; explicit unknowns remain visible.

## B6 — offline integrated readiness COMPLETE; full B6 actual criteria OPEN

[Integrated report](../evidence/b6-offline-20260923/final-report.md) and [handoff](b6-offline-integrated-handoff.md) bind the exact implementation/workload. The owner's offline request authorized the thirty-minute target, implemented as ten unchanged 180-second segments with paced updates and measured source gaps, resources, Stop/finalization and exact fresh-process replay. Browser verification, second-session isolation, reference changes, corrections/as-of and controlled storage failures pass. Novig's unchanged native request ceiling is visible; no continuous four-feed or production delivery claim follows.

Next: [one bounded real-data proposal](b6-next-real-milestone.md) using recorded Kalshi/US access, with exact event/native rules and one separately approved package before access. Full B6 exit still requires actual-source beta criteria with no hidden sport/market exclusions. No positive-profit requirement, invented SLA or owner acceptance follows from offline PASS.

## B7 — owner beta review

Only after engineering readiness, guide one short action at a time through the product, offer technical drilldown, record modifications verbatim and finish with a short-answer survey on utility, clarity, trust, changes and explicit verdict. Keep engineering PASS, owner acceptance and future live expansion/release separate.

## Scope and execution boundaries

The B2 request authorized implementation, focused tests, read-only retained observations and an isolated fixture browser verification. These are complete. No new real collection, credential/account access, spending, outreach, trading or release was authorized or performed. B3 implementation/public documentation/offline replay/isolated fixtures are authorized. Source selection/access and approval of the concrete bounded proposal remain required before new real access. Existing evidence and consumed attempts are preserved; fixture success does not transfer to live readiness.

## Retained foundation

D1 inventory, D3a segmented replay, bounded two-venue live results, one-market diagnostic PASS, saved multi-game calculations, normalization/matching/fees/depth and reference scaffolding remain reusable. Their old next actions are superseded. See [gap assessment](beta-gap-assessment-20260920.md) and [planning snapshots](history/beta-reset-20260920/README.md).

September 21 continuation: supported native listing association, selected/unconfigured ProphetX, native REST segmented replay and the temporary Novig GraphQL display bridge are offline verified. [Evidence](../evidence/b3-continuation-20260921/final-report.md) · [access/setup](b3-access-setup.md). GraphQL does not supply qualified purchase comparisons. B3 remains IN PROGRESS.

September 21 B4 acquisition update: Keychain reference `keychain:prediction-arb.the-odds-api.free/nfl-pinnacle-readonly` configured; one approved request consumed. No further collection authorized. [Completed NHL mapping and consumed MoneyPuck homepage contract](b4-model-mapping-next.md).

September 21 MoneyPuck acquisition update: one approved homepage GET returned HTTP 302 to `https://moneypuck.com/data_license.htm`; 143 original bytes retained, zero probabilities, no redirect/retry/extra request or credit use. [Historical consumed attempt; subsequent owner decision dropped MoneyPuck](../evidence/b4-moneypuck-sample-20260921/final-report.md). Actual model output and independence remain unresolved; full B4 IN PROGRESS. MoneyPuck is dropped; no license review or follow-up is queued.
