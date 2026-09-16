# Personal opportunity-board POC

Completed September 15, 2026 EDT (September 16 UTC). Open **[the board](http://127.0.0.1:8782/)**. The isolated instance is running, and its browser tab is left open.

## What works

Choose either real Detroit–Buffalo capture, navigate its exact cutoff, inspect complementary purchase candidates, change whole-contract quantity, then use **EV explorer** to enter a normal-settlement probability. Selection and assumptions remain in the URL across refreshes. The board has 52 cutoffs in the initial capture and 47 in the live-watch capture. It defaults to the last cutoff with both books connected, synchronized and receipt-fresh.

The main cards show purchasable legs, top price/size, retained depth, depth-adjusted cost, modeled fees, dollars and return. Expand details for cashflows, specific settlement conflicts, fee calculations and original observation IDs. Stale/disconnected/unsynchronized books and cross-venue receipt skew remain visible; displayed historical scenarios are never currently executable. Near misses remain visible, and shared-liquidity alternatives are not summed.

## Real results

At both default cutoffs, with **100 contracts per leg**, the explicit cent-balance fee scenario produces:

| Candidate | Purchases | Purchase cost | Modeled fees | Normal-settlement profit | Return on entry cash |
|---|---|---:|---:|---:|---:|
| Cross-venue | Buffalo Kalshi YES at $0.68 + Detroit US Long at $0.33 | $101.00 | $2.86 | −$3.86 | −3.72% |
| Same-market comparison | Buffalo Kalshi YES at $0.68 + Buffalo NO at $0.33 | $101.00 | $3.08 | −$4.08 | −3.92% |
| Reverse cross-venue | Buffalo NO + Buffalo US Short | Unavailable | Unavailable | Unavailable | Unavailable |

The reverse pair has **no supported US short purchase ask**. No bid/short quote is converted into a fabricated purchase. Kalshi asks use its established opposite-bid transformation and quantities. Kalshi NO retains its native “Buffalo does not win” meaning; it is Detroit exposure only under the displayed normal-winner condition.

Every evaluable cross-venue cutoff in both captures has a $1.01 combined top price and −$3.86 normal-settlement result at this size/scenario. There are no positive normal-settlement candidates or qualified all-outcome results. [Saved result summary](../evidence/opportunity-board/results.json).

For Detroit US Long at $0.33 and 100 contracts, an **illustrative 40% probability** gives $40 expected payout, $34.33 entry cash, **$5.67 expected profit / 16.52% return**, with **34.33% break-even**. At 20%, expected profit is −$14.33. These are what-if probabilities, not estimates from market prices or E3. Initial 50% is labeled illustrative. Tie, void/refund and discretionary outcomes are explicitly excluded from this conditional probability model. Selecting unresolved fees leaves net EV and break-even unavailable while retaining supported purchase/fee/payout diagnostics.

## Bounded assessment and limitations

The retrospective assessment is dated **2026-09-16 00:27:31 UTC**, separately from September 15 observation cutoffs. Listing metadata is selected only from records retained by each cutoff; no later prices or listing revisions enter that cutoff. Original observations and prior assessments are untouched. New analyses are stored in `evidence/opportunity-board/`.

- Both exact listings specify half-dollar tie payouts. Kalshi uses commencement within 48 hours; US uses rescheduling to a date within two days. Their exceptional fair-value payouts are not established as equal. The existing settlement comparator flags the postponement conflict; full worst-case profit remains unknown.
- Retained US metadata establishes coefficient **0.06**. The [official fee page](https://docs.polymarket.us/fees), checked during this work, announces **0.0695 effective 11:59 PM ET September 16**, after both captures. That later change is not applied retrospectively.
- Kalshi effective event overrides and account precision are absent. Scenarios explicitly assume multiplier 1, no event override and either cent or $0.0001 balance precision, using existing [rounding rules](https://docs.kalshi.com/getting_started/fee_rounding). US independent settlement charges remain unestablished, so the numeric net scenario explicitly assumes none. Additional account charges and rebates are excluded by assumption, never silently zeroed in unknown mode.
- Quantity is whole contracts, with one modeled taker fill per consumed level and partial final levels. Existing US fee support rejects fractional fill quantities: crossing a fractional retained level can leave fees/net unavailable. Actual fill fragmentation, simultaneous fills and account-specific costs are unverified. Exact amounts remain in details; primary display rounds dollars to cents.

Reuse: existing validated E6 loaders, market mapping and as-of projections; E5 selection component and dashboard styling; the existing depth consumer, fee/outcome engine, settlement relationships/comparator and Arb arithmetic/policy. The E4 service is explicitly synthetic-bound, so this narrow real-book entry point reuses its underlying engines without relabeling synthetic estimates or changing that service's contract. No replacement collector, database or general framework was introduced.

## Verification and operation

**9 focused tests passed**: native orientation, unsupported purchase sides, as-of/prefix selection, missing/stale/disconnected/skewed inputs, independent positive/negative/unknown arithmetic, depth overflow, account precision, fractional-fill limits, probability separation and read-only HTTP selection. Synthetic prices appear only in calculation tests. JavaScript syntax passed. [Test output](../evidence/opportunity-board/focused-tests.txt).

Actual browser: inspected the real pair, changed size from 100 to 250, preserved candidate selection, entered 40% EV, expanded cashflows, selected unknown fees and inspected the specific missing settlement-charge explanation, switched saved sessions, and reopened bookmarked inputs. At **390×844**, document width was **390**, with usable candidate and EV cards. No console warnings/errors observed; temporary viewport reset. Only this new instance was stopped/restarted; accepted previews and owner services remained untouched.

From any directory:

```sh
/Users/michaelfuscoletti/Desktop/prediction-arb/scripts/opportunity-board start --port 8782
/Users/michaelfuscoletti/Desktop/prediction-arb/scripts/opportunity-board status
/Users/michaelfuscoletti/Desktop/prediction-arb/scripts/opportunity-board stop
```

Start chooses another free loopback port if needed and prints its URL. Stop verifies the process identity and stops only this board. It reads validated saved files on startup; it has no collection/start-order route, credential access or database connection. All prior uncommitted work remains in place. No new market capture, migration, live-run guard reset, orders, commit, push or publishing occurred.

**Next personal-beta step:** under a new explicit scope, connect this board to the existing owner-started bounded Start/Stop capture loop so each completed scan opens directly as saved opportunity results. Stop after this POC; no new scan is authorized or performed here.
