# Predict next steps — 99% fee coverage

Updated November 10, 2026.

## SportsGameOdds pivot implementation in progress

The owner confirmed that paid venue and exact-market coverage, a defensible
replacement reference and a useful object-budget schedule are available. On that
basis the owner directed the SportsGameOdds pivot, retaining both direct
native feeds. See the [assessment and integration work](docs/sportsgameodds-pivot-decision-20261110.md).
Production cutover is authorized when the replacement is integrated and verified;
buying a paid subscription requires a separate owner instruction.
The fee-validation work below remains paused and unchanged.

The [free-tier sample](docs/sportsgameodds-free-evaluation-20261110.md) and
[evaluation plan](docs/sportsgameodds-evaluation-plan-20261110.md) retain the
underlying evidence and original direction. Always retain direct Kalshi and
Polymarket US; the pivot replaces The Odds API and transitions its benchmark.

The new parser, guarded worker, object ledger, source controls and transactional
current-reference storage have fixture and disposable-database coverage. They are
not yet a verified production cutover: the active configuration still uses The
Odds API, and the configured SportsGameOdds key reports Amateur limits without a
reset timestamp. Verify the actual authorized paid account, reset and scope; then
complete real collection, matching, reference/EV and desktop/mobile journeys.
The cached free observations did not establish a typed shared event ID, paid
venue coverage, or Polymarket US identity. See
[operations](docs/sportsgameodds-operations-20261110.md).

On November 10 the app and data processes were restarted with the existing
source selection; the new SGO tables are present. Focused checks passed with
fixtures and disposable PostgreSQL 14, and a read-only installed EV page
loaded at desktop and mobile widths. This does not establish SGO paid coverage,
live EV, a real SGO-to-native match, or a complete cutover. The older D03 smoke
script refused the current `/view/current/` assets and did not complete; its
failure is not an installed-page rendering result. The current SGO reference
path tries a qualified named Pinnacle pair, then a narrowly scoped reviewed
NBA moneyline bookmaker median. Its jurisdiction bindings are currently empty,
so that median cannot yet qualify live inputs. See [reference rules](docs/sgo-reference-rules-20261110.md).
Complete paid-account, matching, broader reference,
provider-status and pinned journey verification before declaring the pivot done.

Show a numeric trading fee for **at least 99% of distinct current offers**
in the configured live desk, using verified public terms or a defensible
conservative estimate for manual retail trades. Measure before fee, reference,
EV or positive-only filters. Report any shortfall by cohort and its cause.
[Coverage policy and source schedules](docs/fee-coverage-policy.md)

## Current status

Local implementation and fixture verification are complete for the fee coverage
scope. The latest verified F09 pregame sample covered 910 of 910 current offers
across all four venues. It included 192 exact Pinnacle references and 192
after-fee EV results. Native publication was partial. Desktop and mobile checks
passed. The fresh in-game run was paused before the evening window.
[Coverage evidence](docs/f09-coverage-20261110.md) ·
[Engineering and validation evidence](docs/fee-coverage-validation-20261110.md)

The **Principal Product/Systems Engineer for Market Data and Trading
Economics** owns the milestone. Resume validation when requested. F09 is the
first executable slice with the existing sources during an active slate.
F03 and F08A can be qualified independently as their production inputs
become available.

## Remaining slices

### F09 · Validate representative 99% fee coverage

- **Owner** — Market data and trading economics engineer, with QA for the
  installed desktop and mobile journeys.
- **Outcome** — Evidence of fee coverage across distinct normal pregame
  and active in-game collection cycles. The earlier in-game Polymarket US
  spreads outside the documented fee price range remain an explicit cohort gap.
- **Work and dependencies** — Resume the read-only capture during an active
  slate. Record coverage and fee gaps separately from exact Pinnacle, after-fee
  EV, unpublished working prices and retained unavailable offers. Reconcile
  representative fee and arb arithmetic and inspect desktop and mobile UI.
  Preserve source controls and unresolved holds.
- **Completion and deliverables** — Append the dated census export, counts
  by venue, league, family, period and phase, screenshots and disposition of
  any shortfall to the [F09 report](docs/f09-coverage-20261110.md).
  Quantify any dependency that prevents reaching the target.

### F03 · Verify Novig signed in-game publication

- **Owner** — Market data and trading economics engineer.
- **Outcome** — A current in-game Novig offer shows the exact one-fill fee
  from a signed, fresh post-reset book. After-fee EV requires an exact
  same-phase Pinnacle pair and qualifying settlement evidence.
- **Work and dependencies** — Provision a production read-only Novig key
  through the existing local credential reference. Observe a subscribed
  market through go-live and a qualifying slate.
- **Completion and deliverables** — Capture the ordinary offer and pinned
  drawer, reconcile the acquired side, depth and fee, and confirm frozen
  replay preserves those terms after withdrawal. Record actual fee and
  reference availability separately. [Novig checks](docs/fee-coverage-validation-20261110.md#f03--novig-signed-in-game-feed)

### F08A · Verify Kalshi automatic fee renewal

- **Owner** — Integration engineer for the renderer route, with the market
  data and trading economics engineer for evidence qualification.
- **Outcome** — A scheduled Kalshi fee review renews prospectively and the
  same terms appear in Admin and on a current offer.
- **Work and dependencies** — Provision a trusted HTTPS route that can
  fetch and completely render the official PDF. Compare its output to the
  approved representation before configuring it. The manual review at
  handoff expires November 10 at 11:24:42 p.m. Eastern.
- **Completion and deliverables** — Retain the request-bound origin receipt
  and exact-market evidence. Match the scheduled renewal and deadline in
  Admin and a pinned current offer. If the route remains unavailable,
  record the measured effect of expiry in F09.
  [Renderer contract](docs/f08a-kalshi-rendered-renewal.md)

[Full validation checklist](docs/fee-coverage-validation-20261110.md) ·
[Local workflow](AGENTS.md)
