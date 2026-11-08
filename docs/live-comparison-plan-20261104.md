# Live outcome comparison — November 4, 2026

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

## Decisions made by the owner

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

## Pinnacle and native finance work

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
reference-only change, fee expiry, list reranking, stable open drawer, explicit
adoption, relevant-source outage/Stop, reconnect and complete grouped pagination.
Use disposable fixtures for failure cases and proportionate real-runtime evidence
for source-to-screen claims. Full provider-denominator 99% and multi-hour coverage
assurance remain separate; ordinary automatic source-to-screen publication is now
required. No fixed diagnostic-attempt limit or fabricated receipt bundle is added.
Owner product acceptance follows engineering and integration verification. Report
real external blockers explicitly and continue known independent fixes.
