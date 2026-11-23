# Predict main market snapshot implementation plan

Final handoff for the lead engineer, November 23, 2026.

Implement a Data workspace centered on market comparisons. The owner must be able to scan a game’s moneyline, spread and total separately, identify the exact offer behind the best stored EV, and open its supporting calculation directly. Every current comparison must use one identifiable acquisition pull. Detailed evidence and historical comparisons remain accessible underneath that experience.

This is the next implementation assignment. This planning request does not execute the changes. The lead owns integration, proportionate verification, normal CI/CD, deployment and the installed owner journey before handing the work back.

## Scope and constraints

- Keep Data, Experiments and Settings as the three destinations. Use existing styles and simple tables.
- SportsGameOdds is the sole active identity/data provider. Keep the selected ten sportsbook references and existing supported prediction markets, as owned by `app/comparison/reference_scope.py`. Other retained exchanges remain historical context without new integrations. Sportsbooks are reference inputs; trading remains on the prediction-market side.
- Preserve the current probability methodology, trusted-book requirements, exact-contract rules, fee implementations and budgets. Fees remain OFF. Record the actual fee mode with each calculation and checkpoint.
- Keep the actual discovery, initial-capture, T−10 and outcome workflow. Do not add recurring full-slate scans or saved-game polling to satisfy the UI.
- Preserve financial/account guards, unresolved holds, journal records, Stop choices, source pauses, settings, remembered login and retained evidence. Do not wipe or reimport the fresh dataset for this implementation.
- Work in `/Users/michaelfuscoletti/Desktop/prediction-arb` on `main`, following `AGENTS.md`. Inspect actual HEAD and dirty state first and preserve subsequent/uncommitted work. Do not create another checkout or successor application.
- NCAAB model, game-log and accuracy implementation remains deferred. No new feed, trading execution or backtest engine is included.

The November 23 owner review supplies displayed examples, not established backend causes. In particular, differing source timestamps do not prove cross-pull mixing. The Jazz +630 moneyline at +6.59% and Jazz +13.5 spread at +109/+2.24% illustrate the required independent rows; those exact prices need not recur for acceptance.

## Priority and product decisions

| Priority | Change | Requirement or review example |
| --- | --- | --- |
| P0 | Establish acquisition identity, membership and scoped replacement; enforce eligibility for current EV and arbitrage. | Self-contained pulls; newer missing inputs must not inherit EV; timestamp examples E and G. |
| P1 | Return and render game-plus-market rows with one exact best offer and direct EV inspection. | Jazz moneyline/spread example A; positive-filter focus B; evidence-first inspector C. |
| P1 | Separate the current comparison set from history and classify missing values. | Withdrawn total-6 observations and misleading empty fields in D. |
| P2 | Present scheduled, captured, missed and failed checkpoints accurately. | Future T−10 shown as failure; empty scoring tables in F. |
| P2 | Complete arbitrage summaries, shared formatting and operating-status mapping. | Missing selections/odds/allocations G; layout, naming, clocks and receipt status H. |

Apply these defaults consistently:

1. **Row identity:** established game identity + supported market family + period. The selected acquisition snapshot is part of the row’s calculation context. Keep source-local games separate when canonical identity is unavailable; never merge by similar names. The ordinary board covers the existing supported full-game moneyline, spread and total scope.
2. **Best offer:** highest eligible stored screening EV among supported trading venues’ source-designated main offers, across both selections, within that snapshot. Preserve existing screening arithmetic and reference policy. Use a deterministic existing identity/order tie-break for equal EV; do not introduce a new ranking model.
3. **Main lines:** each venue can have its own main line. Preserve the exact side and signed line for every offer and reference. Use the trading venue’s own source-designated main status; keep reference-book main status separate. Do not nominate a venue’s main line from another book’s line or from the largest EV. An alternate or uncertain-main offer cannot silently become the default headline.
4. **Alternates:** excluded from the default headline, positive filter and ranking population. An explicit Include alternates control may widen that population; visibly mark an alternate winner. Different lines never become one bet.
5. **Sorting and filtering:** default to EV descending, with numeric results before missing calculations and stable ordering for ties. Keep all EV signs available; positive EV is an obvious quick filter. Sorting, filtering, the headline and its EV link must use the same eligible candidate set.
6. **Latest incomplete attempt:** the affected row shows the newest attempt’s in-progress, partial or failed state and no current numeric headline. The previous complete comparison is accessible as Previous capture, with its own time. This does not declare its offers withdrawn. An unrelated or out-of-scope attempt does not suppress the row.
7. **Historical maximum:** do not use an all-time best as the current headline. If exposed, place it in history with its exact offer and snapshot time.
8. **Sportsbook boundary:** market-to-book EV uses sportsbook reference evidence. Two-leg arbitrage/allocation summaries are market-to-market. Preserve any existing market/book price benchmark under an explicit reference-comparison label; never present the sportsbook as an executable second leg or claim locked profit from it.

## Row expansion and exact offer interaction

The default row shows game/start, market, selected team or outcome, exact line when applicable, trading venue, odds, EV, capture time and a concise reference basis. State fees OFF in the current comparison context without repeating zero-fee text on every ordinary cell. Historical views show their captured fee treatment.

When no main offer has eligible numeric EV, show the market and specific calculation consequence with access to its received prices. Do not select an arbitrary offer and call it best.

Keep search, sport, date, positive EV and EV sorting easy to reach. Put less-used source and age controls in a compact expansion. At the owner’s normal viewport and retained 150% zoom, useful market content must appear without scrolling past a full screen of filters and explanations.

Clicking EV opens the exact headline offer immediately. The inspector leads with:

1. Game, actual selection, market/line, venue and odds.
2. Stored EV, reference probability/basis, fee assumption and capture time.
3. Supporting same-pull reference prices and the calculation’s meaningful limitations.
4. Expandable source identities, revisions, hashes, exact rational arithmetic and reproduction/export evidence.

Expanding the market row shows other matching trading offers and both sides with exact lines. With positive EV active, show matching positive offers first. Offer explicit access to Other offers, Reference inputs, Alternates and History; do not replace the focused view with the entire observation catalog. Supporting references remain accessible while the positive filter stays active.

Links, Back and reload preserve filters, row, snapshot and exact offer/revision. An expired SQL paging lease may open a new read, but must not silently substitute another offer. Preserve the existing bounded-read, captured-export and revision checks. Acquire no provider data from browsing or exporting, and retain protection against overlapping navigation/read amplification.

## Acquisition identity and timing

Use a durable logical `pull_id` assigned to an actual acquisition operation before dispatch. Retain child request/attempt IDs, requested scope, accepted receipt/page membership, receipt clocks and completion state. Reuse existing acquisition/ledger identities where sufficient; add only the minimal missing manifest or links.

A content hash can deduplicate bytes but cannot identify a unique acquisition: two attempts can return identical bodies. A SQL repeatable-read token is also distinct from the acquisition snapshot identity. Pagination belongs to one declared logical pull; retries retain their own attempt IDs and only accepted responses enter its membership. Contradictory or unclosed response membership cannot be promoted as complete.

Unchanged economic inputs may reuse arithmetic after the new pull’s membership and eligibility are proven. Bind the result to that pull’s actual provenance; cached arithmetic cannot fill a missing input or retain an old capture identity as the new one.

For each current EV calculation, validate the trading offer and every reference observation required to produce the result, including both sides and the reference candidates required by the existing selection policy. For arbitrage, validate both trading legs and their required inputs.

The owner’s timing rule is:

`all required inputs share pull_id AND max(received_at) − min(received_at) <= 600 seconds`

Different pulls fail even one second apart. A shared pull ID cannot override the receipt-span limit. Exactly 600 seconds satisfies this timing rule; any greater span fails. Apply the span to the complete input set, not adjacent pairs. A slow unrelated game/page must not invalidate a self-contained comparison in another game.

Source timestamps remain separate, visible provenance. Differing source clocks do not alone violate this rule. Do not add a new source-age threshold. Preserve other documented price, reference, contract, settlement and eligibility checks; satisfying pull membership does not bypass them.

## Snapshot lifecycle and replacement

Track completeness and replacement at the declared source/game/market/period scope, including requested book and line coverage. A global scan may be partial while a particular game/market scope has affirmatively completed. Do not promote a scope whose completion cannot be established.

Only an attempt whose declared scope covers the board row’s required acquisition scope can replace or suppress that row. A narrower book/line attempt remains inspectable in its own scope; it cannot replace or suppress the unrestricted row or assert omissions outside its request. A full-scope attempt with partial/failed results still suppresses its current numeric headline. UI filters do not rewrite acquisition membership. Never extend a restricted request with older observations to manufacture a full-scope snapshot.

Complete means the relevant requested acquisition has closed successfully with known accepted response membership. It does not mean every selected bookmaker must quote every market, and it does not mean numeric EV is available. Confirm this interpretation against SGO’s actual request/pagination semantics during the first slice. When omission authority is uncertain, record Not returned or Coverage uncertain instead of asserting source withdrawal.

| New acquisition state | Ordinary comparison | Treatment of previous data |
| --- | --- | --- |
| In progress for this scope | Show capture in progress; no new headline EV. | Previous capture remains explicitly accessible. |
| Complete, eligible inputs present | Publish this snapshot and select its best eligible main offer. | Previous snapshot becomes history. |
| Complete, required reference or price input missing | Publish this snapshot with the specific calculation consequence and null EV. | Older positive EV cannot remain the current headline. |
| Complete, an old offer is absent | Exclude that offer from this snapshot’s comparison set. | Retain its prior observation; label omission separately from explicit withdrawal. |
| Source explicitly withdraws an offer | Exclude it from current eligible offers. | Keep the withdrawal and prior evidence in history. |
| Partial, failed or cancelled attempt for this scope | Show the actual attempt state; no inherited current numeric EV. | Do not infer withdrawal or merge old observations into the attempt. |
| Attempt does not cover this scope | Leave this row’s selection unchanged. | No absence or withdrawal inference. |

Use durable acquisition ordering established when an attempt starts. A delayed older completion must not overwrite a newer attempt or accepted snapshot. Do not choose replacement solely by completion time.

Publish a scope’s snapshot state, membership and calculation associations consistently. A reader must not see new offers paired with old reference/calculation projections during promotion. Keep history and existing exact exports immutable, within current retention/accounting limits. Capacity refusal must remain explicit; do not expand caps or introduce automatic eviction to make this phase pass.

Historical records without provable acquisition membership remain inspectable under their original provenance and calculation version. Backfill links only when authentic retained evidence establishes them. Do not invent batch IDs from rounded timestamps, rewrite old calculations or admit unverified legacy membership to the new current board.

## Experiments and presentation semantics

Compute each early and T−10 checkpoint from its own pull. Compare those independently captured results across checkpoints. Preserve existing intentionally cross-checkpoint analyses, such as early-offer/late-reference diagnostics, as clearly labeled analytical views outside current opportunity eligibility, EV ranking and arbitrage. They must not appear to be a same-pull trading result.

Drive checkpoint labels from actual task state and target/deadline:

- Before due: Scheduled, with the actual due time.
- Claimed/in progress: Capturing.
- Captured: Captured, with actual receipt/capture times.
- After an uncaptured window closes: Missed, with the relevant reason.
- Actual failure/refusal/cancellation: display that state and its concrete consequence.

Before T−10 is due, do not describe a case as failed or incomplete merely because its late observation is absent. If a completed checkpoint lacks the selected exact line, explain that separately from an absent checkpoint. With no scored completed games, show a concise empty state instead of empty scoring grids.

Apply one missing-value policy across Data, Experiments, arbitrage and Settings:

| Meaning | Presentation |
| --- | --- |
| Not applicable | Omit, such as line for moneyline. |
| Irrelevant empty/default metadata or zero count | Omit from the ordinary view. |
| Actual zero EV or meaningful zero value | Keep and format correctly. |
| Expected future evidence | Show due time and scheduled state. |
| Missing required input | Explain the consequence, such as No matching reference pair in this pull. Preserve null numerically. |
| Unresolved selection identity | Give a specific label/limitation; never guess a team or emit an unexplained Unknown. |
| Withdrawn/superseded evidence | Keep under the relevant history. |

Use shared venue and team/selection formatting. Display rounded percentages and ordinary odds; keep exact fractions in evidence/exports. Apply the configured display timezone consistently, using Eastern when no preference is selected, and retain an explicit label for the date filter’s Eastern-day semantics. Do not mix raw UTC strings into ordinary rows.

Market-to-market arbitrage shows both actual selections/lines, venues, odds, illustrative per-leg allocation, total committed cash, captured fee treatment, snapshot time, modeled return and minimum modeled profit. Preserve existing settlement and sizing limitations. These are stored-price calculations, not fill promises.

Investigate Settings’ Available/Last receipt not reported mismatch by tracing the owning status fields. Show service availability and last valid receipt as separate facts; do not infer acquisition failure from the displayed mapping alone.

## Engineering slices and dependencies

### Slice 1 Acquisition contract and eligibility

**Priority P0.** Trace discovery, event requests, retries, pagination, first capture and T−10 into stored offers/references and current calculations. Establish the smallest durable pull/membership contract, scoped completion states, ordering and replacement behavior. Enforce same-pull and receipt-span eligibility in current EV and arbitrage readers/writers; avoid a reader-only check that still exports mixed inputs.

Start with `app/collection/experiment_acquisition.py`, `sportsgameodds_worker.py`, `sportsgameodds_transport.py`, `app/storage/sportsgameodds_reference.py`, `sgo_line_presence.py`, `current_pregame.py`, `current_pregame_read.py`, and `app/research/ev_movement.py`. Reuse the existing single-page checkpoint builder where applicable. Keep raw source facts and comparison membership separate so the existing omission/grace mechanism does not keep an old offer in a new snapshot’s comparison.

**Acceptance:** the acquisition/replacement cases in the verification matrix pass in disposable fixtures and SQL; calculated/exported input membership agrees; actual cadence and request scope are unchanged. Deliver the API contract and a representative populated fixture for the frontend slice.

### Slice 2 Main market rows and exact offer journey

**Priority P1; depends on Slice 1’s contract.** Add a bounded server projection for game/market rows. Select eligible main candidates, filter, rank, group and count before pagination. Return the headline offer identity/revision and snapshot context directly; do not download the catalog to rank or group in the browser.

Implement the compact table, direct EV link, focused expansion, exact-offer summary and URL/Back/reload behavior. Start with `app/storage/research_catalog.py`, `app/dashboard/research_api.py`, and the current `data.html`, `data.js`, `data-evidence.js` and shared styles.

**Acceptance:** moneyline/spread/total have independent rows; the displayed EV, offer, filter, sort and export agree; different venue main lines remain exact; the owner can reach the headline calculation in one click. Busy/expired reads do not trigger retry amplification or silently replace selections.

### Slice 3 History and checkpoint meaning

**Priority P1/P2; depends on Slices 1 and 2.** Integrate active/history separation, snapshot selection, missing-value rules and actual checkpoint states. Preserve frozen evidence and offline reproduction. Start with `app/research/experiment.py`, `ev_movement.py`, experiment evidence/exports and the current `experiment.js` renderer.

**Acceptance:** a new complete but uncalculable pull removes the old current EV; failed/partial attempts preserve history without implying withdrawal; scheduled T−10 and later missed/failed states are distinct; historical inspection and exact exports retain the selected snapshot and fee assumption.

### Slice 4 Arbitrage details and installed delivery

**Priority P2; depends on Slice 1’s eligibility and Slice 2’s shared presentation.** Complete the arbitrage summary, consistent labels/times, compact layout and Settings receipt mapping. Preserve functional legacy-link resolution and the three-screen navigation. Start with `app/comparison/pregame_arbs.py`, its stored-input readers, shared formatters and Settings’ actual status owner.

**Acceptance:** both market legs and allocations are understandable together; sportsbook evidence cannot appear as an executable leg; the installed journey and normal release checks below pass.

The lead may parallelize acquisition/storage, comparison/API and frontend work after agreeing the shared snapshot/offer response contract. Assign file ownership and integrate each slice in the existing checkout. The lead remains responsible for the full result rather than separate specialist handoffs.

## Verification matrix

| Case | Required result |
| --- | --- |
| Valid offer and required reference pairs in one pull | Existing calculation succeeds when its other guards pass. |
| Different pulls one second apart | Reject current EV/arbitrage mixing. |
| Identical response bytes in separate attempts | Preserve different acquisition identities; deduplication cannot permit mixing. |
| Required receipt span exactly 600 seconds and then just over | Timing eligibility passes at the boundary and fails above it. |
| Receipts at 0, 590 and 1,180 seconds | Reject; adjacent gaps cannot defeat the whole-input span rule. |
| Different source clocks but same pull and acceptable receipts | No rejection solely because of the source-clock difference; retain context and other existing guards. |
| New complete pull lacks references, is negative, or omits the old positive offer | Publish its actual result/null/current membership. Old positive EV is history only. |
| Partial/failed/cancelled or out-of-scope acquisition | Correct scoped state; no fabricated withdrawal, inheritance or damage to unrelated markets. |
| Older attempt completes after a newer one | No backward replacement. |
| Main +13.5, +14 and +14.5; alternate with a larger EV | Preserve distinct exact bets; default headline excludes alternates and uncertain main status. |
| Trading venue main +13.5, reference book main +14, exact +13.5 references marked alternate | Keep the trading offer classified main. Apply unchanged exact-reference eligibility; reference main status cannot relabel the trading offer. |
| Positive filter, EV sort, direct click and export | All bind to the same eligible offer, line, snapshot and calculation revision. |
| Early and late checkpoints | Each uses only its own pull; offline exports reproduce without live settings/source reads. Analytical cross-checkpoint diagnostics stay separately labeled. |
| Scheduled, capturing, captured, missed, failed/refused and cancelled checkpoint fixtures | Accurate state/due time; no false failure before due. |
| Fees OFF and existing fee-enabled historical fixtures | New results retain zero-fee mode; existing fee code and historical reproduction remain intact. |
| Market-to-market pair and market/book reference comparison | Correct labels and details; no executable sportsbook leg or unsupported locked-profit claim. |
| Browsing, filters, expansion, inspection, history and export | Zero provider requests and no hidden acquisition jobs; bounded server reads. |
| Clock/name/null formatting and Settings receipt mapping | Consistent ordinary labels and timezone; no invented values or source-failure diagnosis. |

Use focused unit, SQL, controller and browser checks appropriate to these behaviors. Update obsolete frontend expectations to the new interaction model while preserving useful old fixtures recoverably. Do not restore the observation-heavy default merely to satisfy an old test.

All browser product review and acceptance must use **https://predict.dock108.dev**. Do not use localhost or a private backend tunnel as the substitute acceptance surface. Keep the owner’s normal viewport, retained 150% zoom and remembered login. Verify Data → find a supported NCAAB game/market → identify the exact headline offer → click EV → inspect references/source → export → Back/reload. Also exercise history, a nonpositive or missing-input case, scheduled/incomplete checkpoint states, arbitrage, Settings and functional legacy bookmarks.

Use authentic retained data where available and disposable fixtures for state transitions and mutations. Do not require a new positive edge, live arbitrage, fresh game outcome or a new T−10 waiting window to complete engineering verification. If a particular live state is unavailable, report that precise observation limit and retain the fixture/integration evidence for the behavior.

## Inspection questions to close during Slice 1

These are engineering tasks, not additional owner approval gates:

- Which existing logical operation and per-request ledger IDs can establish pull membership? Trace one discovery/initial capture and one T−10 capture end to end, including retries/pages.
- What can SGO’s actual scoped response prove about completion and omission? Establish the smallest valid game/market completion boundary. If provider semantics do not establish closure, keep coverage uncertain and withhold promotion; do not manufacture a complete state.
- Where can current working-table assembly or read-time selection retain inputs across acquisitions? Inspect joins and exported witnesses before asserting that any reviewed example mixed pulls.
- Which retained snapshots have authentic reconstructable membership? Preserve legacy evidence separately where the new rule cannot be proven.
- Which field owns Settings’ last receipt, and how does it differ from service availability? Repair the mapping at its owning boundary.

Record the findings and resulting implementation choices in the active engineering record. Prefer extending existing owners and evidence links to introducing another storage platform or comparison engine.

## Completion and lead handoff

Complete the agreed engineering and integration before requesting owner review. Run the affected checks and the required normal two-minute CI/CD workflow, preserve all mandatory pre-deploy gates, deploy through the normal path, and verify the installed public-site journey and configured role health. Diagnose and fix any changed bottleneck without weakening the release requirement.

Update operating guides and the active assignment record. Hand back the working result with commit and CI/deployment links, the verified exact-offer journey, the acquisition/eligibility decisions, preserved operating controls and any material limitation. No new soak duration, arbitrary sample count, profitability/calibration target or owner-review dependency is added.
