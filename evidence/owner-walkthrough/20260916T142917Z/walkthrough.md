# Owner walkthrough — in progress

Build: edad00dd980cc8535d69a815d1199b82dd0e83cb; initially clean working tree. Existing beta started with feeds idle. Saved six-game research opened at 100 contracts, cent scenario, dollar sorting.

Owner feedback: pending. No owner walkthrough steps or acceptance claimed. Independent arithmetic and live scan remain pending.

## Saved research list — owner response

Owner, verbatim: “i literally understnd all of it.”

Context: response to the initial request to describe understanding of the six-game research list. No explanation requested. This records reported understanding, not completion of navigation, independent arithmetic, live scanning, or overall acceptance.

Next guided step: owner changes sorting to ROI and reports the resulting first game.

## ROI sorting — owner response

Owner, verbatim: “browns buccs”. Context: first game after requested ROI sort. Supplied browser URL shows sort=roi, research view, quantity=100, scenario=cent, original six-game capture retained. Reported first game agrees with the historical checkpoint; independent arithmetic review remains pending.

Next guided step: owner opens Browns–Buccaneers game details and returns to the list, reporting any changed selections.

## Game drilldown and return — owner response

Owner, verbatim: “all stayed including sort. filters was collapsed instead of expanded like when I left but thats probably expected”.

Owner reports game drilldown and return preserved all selections including sort. Filters disclosure returned collapsed; owner qualified this as probably expected. Supplied return URL retains research view, 100 contracts, cent scenario, ROI sort and original six-game capture. No usefulness or overall acceptance verdict inferred.

## Unresolved fees — owner response

Owner, verbatim: “All ROI is unavailable”. Supplied browser URL confirms scenario=unknown, research view, quantity=100, ROI sorting and original six-game capture. Owner observed unavailable ROI across the list; no independent observation of net-dollar display is inferred from that response.

Technical navigation finding: dashboard.html renders Filters & sorting as a details element without an open attribute; dashboard.js persists calculation/filter query values and selected row, but not disclosure expansion. Owner-reported collapse agrees with implementation. No implementation change made.

Next guided step: restore the cent-balance scenario before independent six-row arithmetic review.

## Cent scenario restored and independent arithmetic

Owner, verbatim: “back to normal”. Supplied URL retains research/100/cent/ROI/original capture.

All six running API rows match independent Fraction arithmetic from original paired odds and retained native Kalshi opposite-side bids at each original cutoff. Verified proportional margin removal, 18-decimal stored probability, full requested 100 contracts, fills, purchase cost, pinned conditional fees, expected payout, net and ROI on cost plus fee. All six consume only their first ask level at 100. Full detail: independent-research-check.json. Historical checkpoints match. No calculation discrepancy found in this review.

12 focused existing research tests pass, including identity/orientation/schedule binding, cross-game isolation, depth boundaries, cent/direct fee scenarios, unknown fees, exact sorting, manual/live separation and preserved timestamps. Evidence: research-checks.txt. Tests are technical evidence only. Implementation hashes unchanged.

Limitations: saved bookmaker page receipt follows all target observations; bookmaker update time and delay unknown. Margin-removal model and account/event fee applicability remain conditional. Ordinary winners include overtime; tie/refund/cancellation/postponement/discretionary differences and unconditional EV remain unresolved. Insufficient retained depth suppresses research net without capping requested size.

## Quantity entry — unresolved owner observation

Owner, verbatim: “maxed to 185”. Supplied browser URL shows quantity=185 after the instruction to enter 200. Do not treat owner 200-contract navigation as completed.

Source inspection: Size per leg input has min=1 and step=1, without a maximum attribute; its change handler requests recalculation. Read-only API checks accept both 185 and 200 and return those exact requested quantities with full Cleveland fills. Saved quantity-185-api.json and quantity-200-api.json. This does not explain or disprove the reported UI behavior; interaction method and browser state remain unresolved. No UI values or implementation changed.

## Quantity change — owner observation

Owner, verbatim: “ROIs are changing by about .02% which is probably fine cause of volume and rounding maybe??” Supplied browser URL shows quantity=185 (not 200), cent fees, ROI sorting, original research capture.

Independent retained-odds/native-depth arithmetic agrees with running dashboard for all six rows at 100, 185 and 200 contracts. All use one unchanged price level, fill the complete requested quantity, and have no depth price impact at these sizes. Small ROI differences arise from conditional cent fee rounding and displayed percent rounding. Evidence: quantity-100-185-200.json. No implementation changes. Owner has not reported exact net-dollar values or completed a depth-boundary walkthrough.

## Insufficient saved depth — owner observation

Owner, verbatim: “most became unavailable except lions bills”. Supplied URL confirms quantity=4000000, cent scenario, ROI sort and original research capture.

Independent native-depth check and running dashboard agree: five research rows are unavailable because requested 4,000,000 exceeds their retained capacity; Cleveland capacity is 3,667,992.66. Buffalo retains 27,741,763.45 total capacity and fills the full 4,000,000 at its original first level. All six retain requested quantity 4,000,000; unavailable rows have no modeled fills/net/ROI rather than a capped calculation. Buffalo fee/net/ROI agree with independent arithmetic. Evidence: quantity-4000000.json. These are saved ladders, not executable liquidity.

Next guided step: restore 100 contracts and open Cleveland game for explicit manual what-if input.

## Cleveland detail restored to 100 — owner-provided content

Owner supplied the rendered detail text. It shows Cleveland Page-derived research at 23.4098%, +$0.20 conditional net and 0.86% ROI, requested/available 100 / 3667992.66; explicit retrospective time mismatch, both source/target timestamps, unknown bookmaker timing, conditional fee applicability and exceptional settlement limitations. Separate cross-venue pair shows Cleveland Kalshi NO + Cleveland US Long, -$2.87, 100 per leg, books >5 seconds apart; alternative YES/US Short unavailable with unsupported purchase ask. Supplied URL has quantity=100, scenario=cent and blank manual probability/basis. This is evidence of displayed separation, not an owner clarity verdict.

Next guided step: owner enters an explicit personally chosen what-if probability for Cleveland Kalshi YES.

## Explicit manual what-if — owner input and result

Owner supplied rendered Cleveland YES what-if: p=0.32, net $8.79, quantity 100. Supplied URL records probability=.32 and basis=“bounce back”, cent scenario and original event/cutoff.

Independent arithmetic: 100 × 0.32 = $32 expected payout; original entry cash $22 + $1.21 = $23.21; conditional net $8.79. Read-only running API comparison with and without probability confirms Page-derived probability/net and Arb candidate economics remain unchanged. Evidence: manual-cleveland-032.json. No probability was chosen or edited by the assistant. Browser persistence still awaits owner navigation.

Next guided step: return to dashboard and reopen Cleveland to inspect retained manual inputs.

## Manual assumption persistence — owner response

Owner, verbatim: “it was”. Context: asked whether 0.32 and “bounce back” remained after returning to the dashboard and reopening Cleveland What-if EV. Supplied URL confirms probability=.32, basis=bounce back, Cleveland Kalshi YES, quantity=100, cent scenario and original capture/cutoff. Owner-reported persistence confirmed; no overall acceptance inferred.

Next guided step: switch to another saved scan and back to the six-game scan, then inspect retained research settings. Live scan has not begun.

## Saved-scan switching — owner response

Owner, verbatim: “all stayed”. Context: asked to switch to another saved scan and back to the six-game scan and inspect research view, quantity, fee assumptions and sorting. Recorded as owner-reported preservation; supplied ambient URL remains game detail and does not independently demonstrate the intermediate selection actions.

Read-only status before live readiness: {"state": "idle", "active": false, "operating_mode": "personal-beta", "start_available": true, "error": null, "cleanup_errors": [], "saved": ["5c9b7dca-a813-4d77-80f5-0691d06068eb"], "session": null, "cleanup_complete": true, "coverage": null}. No live scan initiated by assistant. Next step: owner readiness and chosen scan bounds.

## Owner-started bounded live scan

Owner pasted running dashboard with max games 6, seconds 30, current scan selected, new capture 5accf9ee-94b9-4b09-8130-6849f842155e, capture time 2026-09-16 14:57 UTC. Six games selected; 26 beyond configured limit. New research view explicitly reports no bound saved page for this capture and leaves all six research values unavailable. Retained pasted text: owner-live-paste.txt.

By assistant inspection scan was stopped/inactive, cleanup complete, no error or cleanup errors, Start available, distinct new saved session present beside original. The assistant did not press Start or Stop. Read-only new-scan research endpoint is historical and all six values unavailable; prior page research is not reused for new observations. Evidence: live-scan-status.json, live-run-record.json, new-scan-research.json. Discovery-stage historical labeling and owner Stop action have not been witnessed or confirmed. Reopening new saved result remains pending.

## New saved scan reopened in Arb — owner-provided content

Owner supplied 12 cross-venue pairs for new saved session 5accf9ee-94b9-4b09-8130-6849f842155e at 100/cent/ROI. Numeric conditional values: Detroit–Buffalo -$3.86, Carolina–Atlanta -$4.20, Cleveland–Tampa Bay -$2.17, New Orleans–Baltimore -$2.68, Minnesota–Chicago -$2.84, Cincinnati–Houston -$4.16. Six alternative US Short purchases remain unavailable. Two pairs usable at cutoff; four numeric pairs excluded by receipt skew (Minnesota also has missing source-time progress).

Independent Fraction arithmetic using this new session native inputs reconciles all 12 cross-venue rows: six negative conditional values and six unavailable. Current saved endpoint labels data historical; status remains stopped/inactive with cleanup complete. Evidence: reopened-scan-arb.json. All recorded implementation hashes remain unchanged. Preexisting evidence preservation check: 0 changed files; see preservation-check.json.

Manual Stop and discovery-stage prior-result labeling remain untested in this owner scan, which ended by duration/cutoff. This single scan proves neither continuous reliability nor profitability. Next step: owner overall usefulness and clarity assessment; tracker closeout pending that response.

## Owner overall assessment — verbatim

> its fine. I think the scanning should just be continuous background all data not just some random thing I pick but I get why we did that for this. I see like no polymarket data either it looks like only kalshi so far

Recorded separately from technical results. Owner prefers continuous background coverage over manually bounded scanning and found Polymarket coverage unclear. No unattended operation, broadened feeds or implementation is authorized by this review. Technical clarification: each supported new-scan cross-venue pair contains a Polymarket US Long leg; US Short purchase asks are unsupported. Page-derived research specifically targets Kalshi YES and does not imply absence of Polymarket observations.

## Closeout

Walkthrough closed with actual completed steps and omissions documented. No arithmetic discrepancy identified in the reviewed six research rows, quantity scenarios, manual 0.32 example or 12 new-scan cross-venue rows. Owner Stop and initial discovery-stage historical labeling were not exercised/observed; multi-level depth boundaries were checked offline, not demonstrated by an owner-entered intermediate size. Filters disclosure expansion is not persisted. Overall response “its fine” is retained as stated, not upgraded to unconditional acceptance or release readiness.

Next action: prepare a scoped proposal for continuous background coverage across supported feeds, defining coverage and making Kalshi/Polymarket US participation and unavailable sides visible; keep collection idle until separately authorized. No repair begun.
