# L04 — compact comparison and stable math drawer

November 4, 2026. Implemented in the sole main checkout, built and restarted
locally. No commit/push, worktree, provider correspondence or trading. L05 remains
open for installed end-to-end qualification, cold-read performance and sustained
source currentness. This is engineering delivery, not owner acceptance.

## Running interface

- [Opportunities](http://127.0.0.1:8783/) — one outcome table, four primary columns:
  Source, Odds, EV before fees, EV after trade fees. Every returned source offer
  remains present, including Kalshi/Polymarket, negative, zero, pending and withdrawn
  economics. Source names open Math & fees. The contributor has a small edge marker
  and the text “Sets rank”; `score`, `score_source` and `ranking` come from L03.
- [Markets](http://127.0.0.1:8783/odds) and game links preserve filtering, exact
  lines, occurrences, both sides and American/Decimal preference.
  [Both sides](http://127.0.0.1:8783/arbs) retains its distinct scenario-minimum basis.
- [Admin](http://127.0.0.1:8783/admin) retains source controls, usage and settings.
  The drawer's exact inspection link names its leased immutable member and row.

Pinnacle raw prices appear above the source rows with both outcome names and the
sources using that pair. Identical exact pairs can share a strip; different pairs,
selected sides or predicates cannot. Retained reference authority names affected
sources. Fair-price derivation lives in the drawer. NO/not-win remains not-win;
spread labels say “to cover”; native Long/Short and transformations remain in
source details. Grouping is not a new settlement-equivalence claim.

Reviewed-fee ranking remains the default. Conservative public-fee estimates keep
their own labeled ranking and extra column. They never replace a reviewed value.
Assumed-net/price-difference inspection and pair minimums retain their own basis.

## Drawer and interaction

`snapshot-drawer.js` is presentation only; `SnapshotLive` still owns
open/check/adopt/close/renew, exact revision checks, raced-out refusal, bounded
leases and atomic adoption. The list remains independent. Source selection uses
an exact row, not the first row from another venue or outcome. There is no browser
eligibility or financial-ranking calculation.

Displayed values come from `pinned.row`, including null/withdrawn values. The
separately labeled retained arithmetic uses `details.row` and that member's
`details.assumptions`. It cannot restore current economics. The drawer includes
selected odds, both EVs, before/after formulas, risk/fee amounts, quantity/fill
assumptions, review dates, fair-price/margin derivation, original/native price,
source/reference clocks and literal evidence. Member fee rounding is inspectable.

Material notices show changed odds, before/after EV, reference prices/probability,
fee amounts/basis and availability, including unchanged offered odds. Exact old/
latest records remain expandable. Repeated identical confirmations preserve the
notice DOM, focus, scroll and disclosure state. Adoption still verifies and leases
the complete replacement before releasing the old one. Removed/unavailable states
refuse adoption; pending finance stays pending. Lease and retention errors are
explicit. Opening/closing never substitutes the historical row into the display.

Desktop has an independent side drawer; narrower panels use a native modal dialog
with keyboard focus containment. Close/Escape releases the selection and returns
focus to its source or Results if absent. Visible focus, signed financial values,
textual status and non-color rank markers are retained. List rerenders preserve
source focus/scroll, filters and drafts; the selected button's expanded state is
restored. `page_changed` and same-generation authority checks remain L03's. Returning
from a historical result to Latest now also starts ordinary polling. The source
status disclosure retains its open state across updates.

## Visual verification

Neutral surfaces, navy text, restrained blue actions, signed green/red values and
amber material notices replace the provisional teal treatment. System body type
was assessed against bundled Manrope in the installed app; system text was retained
for compact labels/numbers, with Manrope for the main heading/brand. These are
implemented design proposals, not a claim that the owner approved exact tokens.

Actual bundle checks cover 1280px, the 600 × 602 panel, 390px, 200% root text,
light/dark appearances, reduced motion, keyboard opening and Close/Escape focus,
modal focus containment, odds preference and populated/pending/empty/error/update
states. At enlarged sizes, a wide comparison scrolls inside its own container;
it does not overflow the page or shrink normal labels. Normal secondary labels
are 12px at default sizing. Visible text contrast is measured against effective
solid backgrounds, including rank tint, notice and controls, at least 4.5:1 in
both appearances. The initially failing dark skip-link contrast was repaired.

Evidence under ignored `test-results/l04/`:

- `final/desktop.png`, `final/list-600.png`, `final/list-390.png`,
  `final/drawer-desktop.png`, `final/drawer-600.png`, `final/drawer-390.png`,
  `final/dark-390.png`, `final/manrope-body-assessment.png`: installed app.
- `fixture/`: four-source positive/zero/negative/pending fixture, named references,
  update notices, both appearances, enlarged text, empty/pending/error screenshots;
  `fixture/result.json` contains actual contrast results.
- `browser-checks.txt`: all ten historical/current browser journeys pass. Earlier
  historical tests still expected pre-L03 cards/inline Why and lacked new read/
  lease routes; they now verify the delivered table/drawer without owner SQL.
- 43 focused Python tests pass; two client suites pass, including asynchronous
  inspection races, withdrawal, adoption and lease cleanup. All 18 PostgreSQL 16.15
  checks pass in disposable storage. Two affected SQL nodes were repeated after
  final cache-path changes. Final live bundle/browser checks also pass.
- Wheel build, authored asset composition/drift, lint, docs and whitespace checks
  pass locally. Hosted CI was not run.

## Measured loading cost and read fixes

Useful paint is recorded only for a usable ready result, not an initializing shell.
The initial installed HTTP read took 2.724 seconds. The first styled installed
page took 3.178 seconds: API 3.050 seconds, DOM construction 25 ms; assets took
roughly 9–24 ms. A profile of the then-larger root measured authority/dependencies
0.463s, blob read 0.114s, decode 1.294s, authority projection 1.191s, grouping/page
0.460s and response serialization 0.004s. Profiling adds overhead; those stage
figures are attribution, not a latency percentile. See `profile.txt` / `read.prof`.

The root represented about 134 MB of row JSON plus references/pairs at that sample.
Opening a much smaller immutable member previously evicted the sole decoded root.
The cache now retains the list root through evidence reads, bounded to one cached
list revision; historical list pagination can still use that cache. Each current
read continues to check dependencies, time, settings and owner/source authority.
A SQL regression proves inspection does not trigger root decoding on the next
unchanged list read. A separate reference lookup now uses the exact member's
assumptions instead of a containing root's assumptions.

A post-fix installed page took 2.486s (29 ms rendering). After the final wheel and
app restart, the cold useful page took **2.762s** (API 2.682s, rendering 13 ms).
Three same-root warm pages took **1.078s, 1.039s and 1.012s**, rendering 4 ms each.
`final/browser.json` records the observations and generation. The final pin stayed
on one member with no browser errors, but its 15-second observation saw no new
root; live advancement is not claimed for that interval. Earlier L03 live advance
and L04's intercepted changing-root checks remain separate evidence.

**The two-second cold target is still missed.** Keep L03's 2.30–3.71s observations
and L04's 3.178s observation visible alongside the later measurements. Warm cache
and smaller changing runtime slates do not certify cold-root latency. L05 needs
bounded compact-root/read work and sustained replacement measurements; do not
remove source scope, skip current authority or use fixture timings to hide this.

## Runtime, accounting and L05 boundaries

The app was restarted after building; the data process was also restarted normally
in place, preserving Stop/source pauses, settings, accounts and holds. Its shutdown
outlasted the launcher's initial wait, then completed without force-killing.

At 6:50 PM Eastern the inspected ledger had 31 held credits / 12 unresolved
attempts. The 7:00 PM scheduled aggregate request returned **HTTP 429 without quota
headers**, adding a three-credit uncertain attempt. At 7:03 PM, protected exposure
was **34 credits / 13 attempts** with `quota_missing_duplicate_or_malformed` blocking
aggregate acquisition. The last authenticated provider balance was still the
6:45 PM observation: used 1,797 / remaining 98,203. It is not proof that the new
uncertain request was free or charged. The existing conservative recovery allows
specified server-error cases, not this 429; no guard was broadened, hold released,
replay forced or account assumption invented. Inspect current state for the next
allowed action and preserve all exact uncertain records.

At that same check both native sources were receiving, but source receipt is not
proof of complete current publication. SQL used 2,084,553,507 bytes against the
2,147,483,648-byte guard; storage was available with no cleanup errors. This near-cap
observation and prior maintenance interruptions remain operational qualification
issues, separate from the external aggregate throttle and missing account fee facts.
Kalshi membership/intermediary terms and ProphetX account/channel fee facts remain
L02's genuine external inputs; conservative estimates remain separately labeled.

L05 should continue installed source-to-screen checks, recovery/maintenance and
sustained publication qualification, cold/root-replacement latency repairs and
full-scope readiness reconciliation. These are engineering responsibilities, not
owner-review prerequisites or completed source coverage. Recheck current runtime
and protected accounting state before operational actions.

### Final integration findings

The real server's security middleware uncovered a lease-release defect that the
intercepted routes had not caught: DELETE lacked `Content-Type: application/json`
and was refused. The controller now sends the required header and reports release
failure instead of silently swallowing it. Both browser fixtures assert this
boundary. An installed browser check verifies HTTP 200 and the exact unchanged
set of earlier leases after opening/closing. Nine leases created by L04's own
verification runs were identified by member and creation/expiry times and released
through the supported endpoint; the two earlier selections were preserved.
See `release-check.json` and `released-own-verification-leases.json`.

The post-restart publication issue is more specific than physical SQL headroom:
the automatic retained input/result budget is almost full. At the last read-only
check, packed results occupied 57,392,112 bytes and inputs 76,633,645 bytes, totaling
134,025,757 against the unchanged 134,217,728-byte cap. The worker repeatedly refused
`seal` at the `ordinary_retention_capacity` guard. Root 1019 did not advance;
7:06 PM current reads reported held publication, zero current / 16,863 retained
prices while native reconnection progressed. This is a **local publication/storage
blocker**, not the external HTTP 429 and not evidence that the drawer froze the list.
Physical SQL had recovered to about 1.672 GB after normal maintenance/restart.
Neither protected selections nor the retention limit were cleared to force a pass.
L05 must repair bounded successor-publication headroom and verify fresh advancing
roots before claiming the full installed live experience qualified.

Final 7:10 PM Eastern check: app and data processes are running, data healthy,
Kalshi receiving, Polymarket US connecting, and SQL at 1,657,447,203 bytes.
The aggregate hold remains 34 credits / 13 attempts. Last same-root browser smoke
was 1.322s (21 ms rendering), with no page errors; it does not replace the 2.762s
cold result. Navigation/pagehide release also preserves the exact earlier lease
set, verified in SQL (`final/post-restart.json`); keepalive response events are not
observable after that page navigation. `final/post-restart-600.png` shows the actual
held/retained list. The minimum measured fixture text contrast was **5.84:1**.
