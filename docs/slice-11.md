# Slice 11 — full-depth arbitrage calculation and sizing

Implemented September 12, 2026. Calculator `depth-1`.
**Next action: Slice 12 — PostgreSQL historical capture. Stop before Slice 12.**

The finite, offline calculator evaluates supplied acquisition depth with exact
Decimal cashflows. Full-depth means all supplied levels, not unlimited exchange
liquidity. Every candidate is independent: related listings share liquidity and
capacities must not be summed as simultaneous portfolio capacity. Both modeled
orders must fill; this is neither an execution system nor a fill guarantee.

## API and integration

```python
from app.depth import Search, size_depth, evaluate_allocation, replay
from app.depth_example import fixture, NOW

data, ladders = fixture()  # explicitly invented books and settlement rules
parents, matcher, _, fee_contexts, _ = data
report = size_depth(parents, matcher, ladders, fee_contexts,
    evaluation_time=NOW,
    search=Search(min_roi='0.10', total_cash_limit='10'))
candidate = next(c for c in report['candidates'] if all(c['input']['ladders']))
allocation = evaluate_allocation(candidate, ('3', '3'))
assert replay(candidate) == candidate
```

`size_depth` refreshes the existing event/moneyline matcher and retains the full
Slice 10 top-of-book report, including pricing diagnostics and conditional
calculations. Candidate IDs, current pair revisions, rule/market hashes, parent
snapshot hashes, scopes and native liquidity identities are reused. Eligibility
checks and settlement UNKNOWNs are retained. The original detector API and default
historical example output are preserved. Its historical loader now accepts optional
observation/report factories so the depth example can use the same retained books.

`book_ladders(book, partial_final=..., **observation_context)` consumes adapter
images. Each `AcquisitionLadder` wraps the existing Observation and immutable
(price, native quantity, provenance) rows. Units, minimums and increments inherit
the explicit Observation contract; `partial_final` must explicitly be true or
false, with the sizing evidence describing that scenario rule. None remains an
unsized diagnostic. Scope, reconstruction, clock semantics/problems, state, locks,
raw source body and body hash all remain in replay inputs.

Kalshi derives every acquisition price as one minus the opposite native bid and
preserves the opposite bid's contract quantity, exactly as its documented quote
adapter does. Other venues consume native asks only. No PMUS short asks or Novig
complementary asks are invented. ProphetX's unknown native economic conversion
remains unsupported independently of settlement and other venue qualification.

Existing adapter ladders have already aggregated price levels according to their
native contract. This layer rejects repeated or unordered prices, contradictory
top/depth observations, missing provenance, and conflicting full observations.
Identical complete observations deduplicate. It does not combine snapshots or pick
favorable variants. Input ladders must be ascending; the walk consumes the cheapest
levels, permits an exact partial final level only when declared, and cannot reuse
or exceed visible quantity. A maximum of 10,000 supplied levels per leg is explicit;
exceeding it produces an unsized diagnostic, not a truncated book.

## Supported sizing and separate objectives

Verified payout contracts and verified Novig payout cents convert to $1 payout
contract units. Fractions, zero-origin venue increment grids, and minimum order
quantities are preserved. Positive quantities must meet both the minimum and
increment. Fractional PMUS fills still receive the real fee engine's unsupported
retail-fractional result; this slice does not reinterpret native economics.

The search includes zero on each leg, including the zero/zero no-trade alternative.
The latter needs no entry cash or execution reserve and wins all nonpositive ties.
Single-leg allocations are evaluated against every material outcome as well.

| Objective | Definition |
|---|---|
| `equal_max_profit` | Greatest worst-case modeled profit among equal quantities and zero |
| `max_profit` | Greatest worst-case modeled profit over the two independent grids |
| `max_roi` | Greatest worst-case profit / total required cash, among positive profits |
| `max_deployment` | Largest total required cash with positive worst-case profit meeting inclusive Search minimum profit and ROI |
| `minimum_known_diagnostic` | Largest minimum over known outcomes only; never a guaranteed optimum or recommendation |

Deployment includes the separately disclosed execution reserve. Venue cash limits
apply to the respective left/right legs; total cash limits include the reserve.
These are hypothetical scenario inputs, never inferred balances. Policy reporting
thresholds remain separate from Search deployment thresholds. Immediate and deferred
fee credits stay separate; deferred or unknown rewards cannot fund entry.

Every supplied material outcome is calculated. Fractional payouts multiply the
actual quantity of that leg. Acquisition refunds use the exact consumed entry cost,
including unequal-price fills. An unknown payout or fee leaves dependent cashflows,
worst-case profit and ROI null, while minimum-known diagnostics remain available.
Incomplete outcome cashflows explicitly mark objective optimality unresolved; zero
is not advertised as the proven optimum of unknown economics.

## Search method, precision and bounds

Small domains use exhaustive evaluation of both zero-origin quantity grids. There
is no smoothness, ROI monotonicity, binary search or two-payout balancing assumption.
An allocation that would need a forbidden partial fill is counted as examined and
excluded. Quantity-grid sizes are computed with exact integers; the equal-quantity
common grid uses rational LCM. Independent tests use closed-form venue fee arithmetic
and tiny exhaustive loops, not expected values obtained from the optimizer.

The default limit is 4,096 allocations per candidate, including zero and infeasible
partial-fill proposals. Callers may set 1–100,000. In a larger domain, the method
first proposes common-grid depth boundaries, then grid extremes, then a deterministic
lexicographic prefix. It is intentionally a bounded candidate search, not a global
optimization algorithm. It uses lazy grids and caches per-leg fee evaluations.
The output records the entire domain size, first/last positive indices, increments,
minimums, common grid, evaluation count, limit and whether it was reached.

A completed grid gets `proven-optimal-within-supplied-grid-and-fill-model`; a limited
search gets `best-found-search-limit`. Unsized inputs and unresolved objective
cashflows have separate statuses. Even a grid proof is conditional on fee, payout,
qualification and fill assumptions; it is not a guaranteed executable optimum.
Tie-breaking is deterministic first encounter; zero wins ties at zero profit.
No optimizer library or binary floating-point arithmetic is used. Financial work
runs in an isolated 100-digit Decimal context; input bounds follow the fee engine
(24 significant digits / 12 decimal places). Computed VWAP is a reporting ratio,
never a replacement fee input. Quantity and cashflows are recomputed exactly for
explicit allocations. No approximation is used to fit a refund into a payout ratio.

## Fees and fill partition

Every positive leg invokes the actual versioned fee engine once with the consumed
price levels as ordered fills in one new taker order. Modeled fills share one
explicit match ID if a caller chooses Novig's conditional match-VWAP interpretation.
One fill per consumed level is an assumption, including when only one price is
consumed. Actual exchange fragmentation can change rounding even at a single price.

For nonzero or unknown schedule coefficients the allocation retains the explicit
`fill-fragmentation-unbounded` condition: different subfills can change charges and
no conservative fee bound is asserted. Thus an exhaustive grid result under the
modeled partition does not become a fragmentation-independent profit guarantee.
Zero-coefficient schedules do not need this additional rounding limitation; all
other fee-engine assumptions and qualification conditions still apply.

Kalshi per-order rounding credits, PMUS cumulative fee allowance, Novig aggregation
conditions and unknown settlement fees remain in full audits. The engine receives
original consumed prices and quantities, not one invented VWAP fill or one order
per price level. Missing fees are null. No account conditions are waived.

The small fee extension `refund_outcomes` accepts distinct acquisition refund names
and uses the exact aggregate entry cost as gross payout before outcome charges.
Its audit version is **`fees-1-refunds-1`**; ordinary contexts remain **`fees-1`** with
unchanged results. Replay checks both versions against their actual context and
output. ProphetX refunds through this native acquisition extension are rejected;
its existing explicit market-cashflow API is unchanged. Historical fee evidence
and the schedule registry were not changed.

## Results and replay

Each selected allocation includes quantities, original consumed level provenance,
VWAP, costs, fees, credits, cash per venue and total, all terminal outcomes, worst
and minimum-known profit, ROI, constraint/exclusion reasons, native liquidity
identities and exact matching/rule/observation provenance. Objective and optimality
are supplied alongside each selected allocation. `evaluate_allocation` validates a
specific allocation against the saved input domain and produces the same full
cashflow detail; it does not optimize or refresh current matching.

A compact equal-quantity curve retains up to 64 evaluated points by default,
configurable from 2–256, and reports truncation explicitly. Complete small-domain
curves include every equal grid point; larger searches prioritize depth boundaries.
Points are in search order, with no interpolation or monotonicity claim. All
outcome details for any valid explicit quantity can be reconstructed from the audit.

Every candidate embeds the exact input report, ladders, raw JSON, fee templates,
registry snapshot, search constraints, evaluation time and hashes. `replay` validates
input and result identity and recomputes the saved calculation. Replay is historical
arithmetic verification, not a fresh matching decision or authenticated evidence.
Use `size_depth` again to refresh current eligibility.

## Demonstration, verification and coverage

Run the finite verification from the repository root:

```sh
.venv/bin/python -m app.depth_example
.venv/bin/python evidence/slice-11/verify.py
```

[Readable report](../evidence/slice-11/report.md),
[full demonstration](../evidence/slice-11/depth-example.json),
[verification results](../evidence/slice-11/verification.json),
[preservation checks](../evidence/slice-11/preservation.json),
[artifact hashes](../evidence/slice-11/manifest.json).

The invented-depth demonstrations use real Kalshi and PMUS fee models. They show
shrinking/disappearing profit, top screening, unequal-grid improvement, different
profit/ROI/deployment objectives, fractional final fills, grouped rounding,
nonmonotonic ROI, partial depth, binding venue/total cash, exceptional losses,
refunds, unknown settlement/fees, no profitable allocation and exhausted budgets.
A zero-fee stub exists only in an explicitly labeled qualification-branch unit test;
it is not used in the demonstration or as an arithmetic oracle.

The production portion uses only existing retained Kalshi and PMUS images. Ten
structural pairs remain settlement-UNKNOWN; 20 related candidate combinations yield
zero qualified current opportunities. The one observed two-ask sum remains 1.0100.
Missing books, reconstruction/sizing evidence and fee contexts are not fabricated.
No production positive-depth opportunity or actual-fill reconciliation is claimed.

**321 offline tests (287 existing plus 34 new) and all eleven examples pass.**
Actual command outcomes are recorded in verification.json and tests.txt. All 44
saved candidate audits also pass JSON serialization/replay checks in
[serialized-replay.json](../evidence/slice-11/serialized-replay.json). PLAN.md and all historical evidence are preserved. The only preexisting
implementation changes are the optional historical-loader hooks and versioned refund
extension. No dependencies, live collection, credentials, balances/history, funds,
purchases, outreach, commits, pushes, publishing, database, dashboard or execution
work was performed. README and the Desktop tracker carry the Slice 12 handoff.
