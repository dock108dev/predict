# Live outcome comparison — November 4, 2026

## November 12 · Pregame opportunities first

**Opportunities** opens on pregame full-game winners, spreads and totals,
including available alternate lines. **Expected value** and **Arbitrage**
rank this cohort. Keep in-game markets behind a separate **Live** tab.
Live finance and coverage are deferred. Apply pregame scope before grouping,
ranking, pagination and counts. At kickoff or earlier authoritative state
change, withdraw the market from pregame results. Pinned inspections keep
their original evidence and clearly indicate that it has aged out.

The default EV basis is the sportsbook estimate before fees. Use the best
eligible payout from FanDuel, DraftKings, BetMGM and Caesars and de-vig that
same book's two original quotes. The pregame window is 15 minutes. Target
five-minute refresh for priority pregame games within existing limits.
Publish numeric negative and zero results. Keep the ranked and exact-line
design below. Current calculations follow the [EV contract](benchmark-ev.md).

Use venue names throughout the bettor desk and audit drawer. Keep
data-provider identity, vendor fair values, raw provenance, billing and
direct-versus-aggregate comparisons in Admin. Display sportsbook prices
for the same line even when a calculation cannot qualify.

## November 12 · Compare every venue on the line

The owner approved the ranked dashboard and its game, EV, Arbitrage and
unavailable states on November 12, 2026. The approved local reference is
`Desktop/Predict dashboard mockups/Predict.html` with the accompanying PNGs.
The acceptance milestone is the installed journey on `main` with source
and calculation evidence appropriate to each result.

The owner walkthrough opened Detroit–Washington Over 205.5 from EV and
encountered three unavailable results above the useful price and fee. The
dashboard must lead with the strongest calculated opportunities and show
every price for the exact bet inside its card. This section
governs the current interface. `NEXT_STEPS.md` owns the execution sequence.

| View | Primary content | User action |
| --- | --- | --- |
| Dashboard | Ranked EV and Arbitrage cards in separate tabs. An EV card shows the exact outcome, ranking result, all venue prices and the selected comparison book with both original prices. An arb card shows the ranked minimum net return, chosen legs and other venue prices for both opposing sides. | Open a game, inspect a venue or open the pinned calculation directly from the card. |
| Game | Both sides of each full-game winner, spread and total, with main and alternate lines and the same venue columns. | Switch market family, include alternates and inspect any quote without losing the line. |
| EV | Offered price, fair probability or fair odds, and the selected result. If the result is unavailable, put one specific reason beside the price. | Expand the selected sportsbook pair, exact inputs, method, fee assumptions, original clocks and pinned source evidence. |
| Arbitrage | Two opposing legs, their prices, modeled funding and the minimum net payoff across evidenced settlement states. | Inspect both legs, quantities, fee rounding, settlement state cashflows and depth status. |

Group the complete exact outcome before pagination. Rank EV cards by the best
eligible result for the selected basis and name that venue. Rank Arbitrage by
the minimum modeled net payoff divided by total modeled funding, including both
fees. Sort exact unrounded values descending with deterministic ties. Show
positive, zero and negative numeric results in that order, with a Positive only
filter. Each venue keeps its distinct offers on that line and their applicable
EV. The bettor sees venue names. Kalshi and Polymarket US display direct quotes.
The selected EV comparison book is visible on the card, with its quoted pair
and separate estimated fair odds. Show same-line sportsbook quotes even when
they lack the evidence required for EV. Admin → Quote quality compares the
direct and aggregate observations with their original timestamps and event
association evidence. In the
game table keep opposite sides adjacent. Preserve signed lines, periods and
settlement distinctions. Grouping offers does not establish settlement equivalence.
Retain the user's saved basis and odds format. The preview illustrates the
After fee selection. Apply the selected basis consistently to card rank, venue
values and the opened calculation.

The opening dashboard is usable when finance is blocked. Display one
plain-language availability notice and a direct **Find my game** action. EV and
Arbitrage report the selected scope's priced, calculated and missing counts.
Keep positive, zero and negative evaluated results available. Use distinct
states for a stale quote, a provider that does not offer the line, an unknown
provider population, a missing reference and a calculation waiting to publish.
Last-known prices are available through an explicit toggle. Put quote age,
modeled fee size and the active EV blocker by the offered price. A current quote
shows what $10 would pay on a win before fees. The arbitrage card shows each
leg's stake, total funding with fees, and the lowest modeled payout. Keep full
settlement terms, source IDs and technical diagnostics in details or Admin.

On narrow screens let the venue prices wrap within each ranked card. In the
game table keep the outcome visible and make the remaining venue columns
horizontally reachable with clear headings. Game and quote
navigation preserve filters, sort, scroll and the selected exact line. An open
inspection keeps one capture. Use latest prices offers a coherent replacement
when one is current. Read-only navigation remains independent of collection.

Acceptance starts from the ordinary dashboard at desktop and 390px. Recreate
Detroit–Washington Over 205.5 with several venue prices and a blocked EV result.
The price, venue and reason must be legible before opening the row. Then use a
current numeric EV and a modeled two-leg payoff on the ordinary pages, with
independent recalculation from the displayed inputs. A negative result counts.
Run the empty, partial, expired and resumed states through the same entry point.
See the [calculation contract](benchmark-ev.md) and [coverage measures](broad-coverage.md).

## Current scope — November 11, 2026

The working execution queue is `NEXT_STEPS.md`. Use the current
[coverage measures](broad-coverage.md#next-version-target--bulk-live-data-and-99-coverage)
and [fee policy](fee-coverage-policy.md). The November 4 design below records
earlier grouping and inspection decisions. Use the current interface direction
above for presentation and the current calculation contract for financial basis.

The pregame EV desk starts with the sportsbook estimate before fees. It selects
the highest eligible exact-line payout among FanDuel, DraftKings, BetMGM and
Caesars and de-vigs that book's own pair. Keep qualified and after-fee
bases distinct, with explicit gaps when direct native contracts lack a verified
binding. Build opposing comparisons from the exact native contract and
settlement evidence without requiring a sportsbook probability. Show a
negative modeled payoff when a compatible pair qualifies and its price is
unfavorable. Preserve independent Kalshi and Polymarket US inputs. New P2P
venues are backlog work. A clean macOS profile starts with acquisition off
and can use synthetic replay before configuring supported read-only sources.
See the [setup guide](configuration.md).

## Authority and status

The local November 7 engineering record under `docs/engineering/live-data-20261107/`
contains the follow-up and delivery evidence. The product contracts below remain
applicable. The [development guide](development.md) describes the integrated desk
and replay.

### November 6 checkpoint — dated evidence

This is the current product plan from the November 4 owner design conversation.
It supersedes conflicting November 3 per-source cards, manual-refresh discovery,
inline Why panels and treatment of automatic ordinary-list publication as optional.
November 3 verification remains dated evidence, not acceptance of this new scope.
Local L01–L05 implementation, integration and engineer-led verification are
recorded delivered on November 6 at 11:21 AM Eastern. Read the
[L05 final delivery record](engineering/live-comparison-20261104/L05-delivery.md)
for scheduled NBA receipt-to-list proof, independently checked reviewed EV and
authentic reference-backed numeric adoption while the list advanced.

Known limits remain explicit: native quotes can expire during turnover; an observed
startup desktop Markets load took 2.454s against the two-second target; account-
specific net fees still need applicable account facts. The observed scheduled
collection resumed through the separately owner-authorized one-time balance
recovery, consumed once, without releasing the 34 held credits / 13 historical
attempts. It is not a standing authorization for new 429 recovery exceptions.
Prior blocked/open entries are historical and must not override the final evidence.
No universal currentness, hosted CI, commit/push or owner acceptance is claimed.
The next step at that checkpoint was ordinary use and focused follow-up. Actual
November 7 findings now have an explicit engineering queue; do not automatically
redispatch historical optimization assignments or leave the new work behind
owner acceptance.

Read `AGENTS.md`. Work only in this repository on main. Preserve the
existing uncommitted prototype and protected data. No worktree, commit/push,
trading, provider correspondence, hosting or installer work is included.
Normal local integration, restarts and acquisition remain authorized within
300 aggregate credits per 15-minute cycle and 16,800 per operating day, subject to
actual account-window, quota, reservation, hold, Stop and source-pause guards.
The latest observed ledger must be inspected; historical held-credit totals are
not current account authority.

## Earlier owner decisions · November 4 design record

For the current phase, default basis, reference books and provider presentation,
follow the November 12 pregame direction above.

- Opportunities opens with ranked outcomes, not a game picker or a card per book.
- One outcome such as Ravens to win contains every relevant source together.
  Use compact book rows; retain winner/spread/total and distinct alternate lines.
- Show source, offered odds, EV before trade fees and EV after trade fees together.
  Default ranking is after-fee EV. Keep positive, zero, negative and unknown values.
- Pinnacle stays up front as the pricing reference. Exact matched Kalshi and
  Polymarket US outcomes must use it just as the aggregate venues do.
- Math, fee assumptions, fair-odds derivation and detailed clocks move into a
  slide-out Math & fees panel, with exact Admin evidence still reachable.
- Display actual winning conditions, not Long/Short as primary selection labels.
  Native wording remains inspectable. Do not turn not-to-win into opponent-to-win
  without evidence for the relevant settlement states.
- Startup synchronizes sources and obtains API prices as needed; ongoing streams
  and the existing 15-minute API schedule keep the ordinary list current.
  Routine browsing must not require Refresh prices or retain yesterday's head.
- The list updates and reranks automatically. An open math panel retains the
  exact selected inputs. A material update offers New prices available and an
  explicit Use latest prices action; no silent replacement mid-calculation.
- The owner requested crisper typography, color contrast and spacing. The visual
  refinement below is a proposal, not a newly approved palette/typeface.

## Design references

- [Current live list/drawer mockup](design/live-comparison-20261104/live-ranked-mockup.html)
- [Earlier compact outcome study](design/live-comparison-20261104/outcome-study.html)
- [Visual refinement notes](design/live-comparison-20261104/README.md)

These are editable HTML fragments for the inline preview, not app implementations
or production inputs. Their simulated feed status, reference matches and native
fee amounts are illustrative. In particular the 2¢ Kalshi and 1¢ Polymarket fees
must never be copied into production as verified schedules. The ProphetX unknown
fee demonstrates partial availability; engineers must investigate the real inputs
rather than treating every mockup blank as a permanent accepted product gap.

## Ranking and grouping contract

1. Admit exact game occurrence, period, predicate, participant and signed line.
   A shared display bucket is not proof of settlement equivalence. Preserve
   distinct native instruments, source IDs, alternative offers and raw evidence.
   If multiple routes from one book remain, show each meaningful offer compactly;
   deduplicate only proven duplicate observations, not distinct contracts.
2. Group the complete filtered universe before pagination. All source rows for an
   outcome travel together. Include source prices even when that source lacks EV.
   Report outcome, source-price and unranked counts in their actual units.
3. Each source gets its own exact matched Pinnacle pair, probability, fee basis,
   original clocks and result identity. Never copy another source's EV or silently
   reuse a probability across unsupported lines, scoring or settlement predicates.
4. The outcome score is the maximum eligible numeric EV after trade fees among
   its source rows. Highlight and name the source setting that rank. Missing fees
   are not zero, and a gross value cannot compete in the after-fee ranking.
5. Use exact values for sorting, then deterministic start time, canonical outcome
   and stable source/result identity for ties. Formatting and rounded displayed
   ties must not alter order. Alternative before-fee sorting remains secondary.
6. Rank within one declared financial basis: decisive win/loss after trade fees,
   normalized to total modeled risk including the modeled trade fee. This is not
   full-state net EV. Keep assumed-net/buffered metrics and pair minimums distinct.
   Where source fee models use different order sizes/rounding/fill assumptions,
   disclose them and compare only the supported common basis; do not silently rank
   incompatible sizing scenarios as equivalent. Preserve actual account settings.
7. Expired prices, references or fee models cannot set a current score. Current
   means quote-specific source evidence under a declared policy, not a recent
   heartbeat, HTTP read, recalculation or metadata change. Engineering must inspect
   and document those policies; no arbitrary new universal expiry is approved here.
8. Zero/negative numeric outcomes remain accessible in descending order. Missing
   finance is an unranked state with the dependent reason, not checked-zero.
   A collection failure withdraws affected ranking authority promptly, shows the
   affected scope and recovery state, and preserves evidence for inspection.

## Acquisition, publication and stable inspection

Startup must resolve retained Stop/pause/account guards first. Synchronize native
book images/deltas and get an initial API batch when retained inputs lack usable
current evidence, through the existing scheduler/reservation owner. Opening a tab,
changing filters or restarting the app cannot independently spend credits or create
another collector. Reuse a healthy owner; preserve its finite backoff and holds.
The native transport is the existing streaming mechanism, not an assumed webhook.

Keep partial readiness explicit while each source initializes. Ready prices from
healthy sources can render; the list cannot claim complete readiness while another
source is pending, held or failed. Reconcile all configured six-league/three-family
scope; do not drop slow sources to make startup appear healthy.

Committed price, reference, model, policy and expiry changes trigger affected
calculations and atomic replacement of the ordinary current projection. Browser
reads consume a coherent publication; they do not compute or acquire a whole slate.
Coalesce superseded updates and retain bounded work. A fresh source-only price must
remain visible if optional finance is pending or fails. Do not mix a new price
with an old probability, fee model or EV. Report measured receipt-to-publication
and publication-to-display delay rather than calling a read timestamp live.

Opening Math & fees binds the displayed source, outcome, original odds, reference,
probability, fee scenario, result/policy and clocks. Background list updates do not
change them. Show a concise old → latest odds and after-fee EV notice only when
relevant economics/input authority changes; an identical confirmation must not
create incessant prompts. Use latest prices adopts one coherent latest context
and replaces all dependent fields together. If removed, expired or unavailable,
show that state instead of adopting an unrelated row. Close/Escape returns focus
to the opening source/outcome or a useful fallback after reordering/removal.
A retained inspected revision is evidence, not current eligibility.

Keep search, filters, scroll and focus usable during reranking. Avoid stealing
focus or jumping the viewport when a row moves. Respect reduced motion. Handle
reconnect/resync and out-of-order requests explicitly; an old response cannot
roll the board or drawer back. Retention must be bounded and leases released;
automatic updates cannot append an unbounded snapshot history or provider bodies.

## Historical Pinnacle design and native finance work

The November 12 comparison uses the four configured books. Pinnacle
acquisition is backlog work.

The product requirement includes reference-backed native calculations; blank native
EV is not a completed implementation just because prices render. Engineers must
trace the exact missing-context, scoring/equality and occurrence bindings on real
examples, retrieve applicable official facts where needed and repair valid paths.
Verify that normalized native Short/NO price transformations retain the correct
winning condition, bid/ask direction, quantities and exceptional outcomes.

Display raw Pinnacle prices beside the relevant named outcomes. Put fair odds,
margin removal, conditional probability and provenance in the drawer. Pinnacle
is reference-only. Verify applicable fee schedule, account/product/channel,
rounding, quantity, model interval and denominator per source. Do not renew a model
date or insert a mock fee to get a number. Separate a missing account-specific fact
from an engineering gap; identify the smallest genuine external dependency and
continue independent work. Before-fee EV can remain available when only fees fail.

## Visual refinement proposal

Use neutral cool surfaces with strong navy text. Reserve blue for actions/links,
teal/green for positive values, restrained red for negative values and amber for
an actual changed-price notice. Do not use tinted teal everywhere or very pale
text for important numbers. Keep native and aggregate rows equally legible.

Use a crisp system body font and tabular figures, with the existing Manrope option
for headings. Prefer 13–14px body, 12px secondary copy and 15–16px price/EV values
at desktop; do not shrink labels to fit mobile. Use fewer weights, lighter chrome,
consistent row spacing and subtle rules. Match tokens to actual backgrounds in
light/dark appearances; measure normal-text contrast at least 4.5:1 and large-text
contrast at least 3:1. Keep visible focus and non-color indicators. This is a
proposed refinement of the agreed layout and requires visual assessment; it does
not reopen the owner's outcome-table and drawer decisions.

## Delivery slices and completion

See the [engineering queue](engineering/live-comparison-20261104/README.md).
L02 calculation engineering is now locally integrated; see its
[financial contract](engineering/live-comparison-20261104/L02-financial-contract.md).
The owner's subsequent request for conservative public-schedule estimates is
recorded there. Those estimates remain explicitly separate from verified-fee
ranking; missing account facts and partial freshness remain visible.

L01 current acquisition/publication and L02 native reference/fee work precede
L03 grouped ranking/current reads; L04 integrates the interface and visual polish;
L05 qualifies the complete installed experience. These are ownership boundaries,
not isolated workspaces or automatic permission for concurrent agents.

Required engineering proof covers startup, native change, scheduled API change,
reference-only change, fee applicability changes, list reranking, stable open drawer, explicit
adoption, relevant-source outage/Stop, reconnect and complete grouped pagination.
Use disposable fixtures for failure cases and proportionate real-runtime evidence
for source-to-screen claims. Full provider-denominator 99% and multi-hour coverage
assurance remain separate; ordinary automatic source-to-screen publication is now
required. No fixed diagnostic-attempt limit or fabricated receipt bundle is added.
Owner product acceptance follows engineering and integration verification. Report
real external blockers explicitly and continue known independent fixes.
