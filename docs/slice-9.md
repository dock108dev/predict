# Slice 9 — versioned, outcome-aware fee engine

Completed September 12, 2026 UTC. Engine `fees-1`; registry schema 1.
Next project action: **Slice 10 — top-of-book arbitrage detection**. Stop before Slice 10.

The offline engine calculates hypothetical acquisition/fill cashflows independently
of market matching. It retains supplied settlement status; it neither revisits nor
qualifies Slice 8's ten UNKNOWN production pairs. Actual fill reconciliation is
**unverified for every venue**. No account activity was used as fee evidence.

## Coverage and qualification

| Venue | Formula support | Schedule applicability | Rounding verification | Remaining conditions |
|---|---|---|---|---|
| Kalshi | Metadata-driven quadratic, maker variants, series/event changes and independent null clearing | Scoped series history required; event completeness explicit; flat unsupported | Six-decimal ceiling, balance grid, per-order refund across roles | Supplied account precision; event history; FCM extras; rounding guide effective instant unknown |
| Polymarket US | Entry taker fee, per-fill maker rebate, separate volume rebate estimate | US July 1 version; retail whole contracts only | Half-even cents; each taker fill capped by cumulative exact-fee allowance, never increased | Native applicability evidence; rebate eligibility; separate settlement levy unestablished |
| ProphetX | Positive market net gain at settlement; marginal monthly rebate estimate | Straight only, explicit dollar cashflows; native quantity conversion rejected | Raw commission verified arithmetically; positive rounded charge unknown unless scenario rule supplied | Complete market netting, rounding, eligibility, exact effective instant |
| Novig | Pregame/live/futures, golf/tennis exception, explicit pre-fee app parlay, API parlay maker | Documentation scenarios; API parlay taker rejected | Five-decimal half-up; per-fill versus match-VWAP conflict remains conditional | Unknown effective instants, aggregation interpretation, maker eligibility/retained fees; live ingestion unverified |

Official sources, retrieval timestamps, byte hashes, failed fetches and examples
are retained in [research sources](../evidence/slice-9/research/sources.json).
The [research assessment](../evidence/slice-9/research/findings.md) explains conflicts
and the difference between retrieval and effective dates. The registry includes
source references and hashes; the current Kalshi PDF was browser-readable while
the direct download returned HTTP 429. That failed body is retained as failure
evidence, not treated as a PDF. No coefficient was copied from PLAN.md.

## API and scenario contract

```python
from app.fees import calculate, replay
from app.fee_example import scenario

context = scenario()  # labeled synthetic Polymarket US acquisition
result = calculate(context)
assert result['settlement_status'] == 'UNKNOWN'
assert result['fill_reconciliation'] == 'unverified'
assert replay(result) == result
```

`calculate()` accepts a JSON-shaped dictionary. Monetary/quantity inputs must be
strings or integers, never floats. See `app/fee_example.py` for complete examples.
Required context includes venue, environment, native market ID, product,
timezone-aware trade/calculation times, and explicit fills or ProphetX cashflows.
All calculations use USD. Acquisition price is dollars per $1 payout contract;
`outcomes` supplies payout fractions between zero and one, including exceptional
fractions when the caller has evidence. ProphetX instead supplies aggregate
`stake_usd` and dollar `gross_payouts` scoped to one market.

Each fill has a unique ID, order ID, maker/taker role, execution price, quantity
and unit. Novig integer `payout_cents` converts explicitly by dividing by 100.
No adapter field is automatically interpreted as stake. Caller-declared product,
liveness, identity, outcome and account facts are scenario inputs, not inferred
facts. `applicability_evidence` is retained caller evidence, not authenticated venue
approval. Omission adds a conditional reason. Non-production environments receive
a conditional production-schedule simulation label.

`complete_order_history=True` asserts all earlier fills are supplied in order;
accumulators begin at zero and never borrow state from another order or market.
Optional fill trade times must be chronological within an order and no later than
the scenario time. Kalshi metadata changes can occur between fills. Orders spanning
multiple base schedule versions are explicitly unsupported; ordinary historical
selection and replay within one base version work. Closing sales/inventory and
collateral netting are outside this acquisition implementation and rejected.

The returned entry fee is the gross charge. Credits appear separately. Entry cash
requirement does not rely on maker rewards; entry balance debit and terminal net
cashflow include immediate documented maker rebates and rounding refunds. Deferred
or unknown rewards never fund entry or net payout. Unknown settlement charges and
their dependent net amounts remain null. Values cover venue trading fees only;
conditional account extras are not claimed to be zero. A caller can explicitly
assume no PMUS settlement levy or choose hypothetical ProphetX cent rounding;
these choices remain conditional in the audit.

## Registry, arithmetic and replay

`app/fixtures/fee-schedules-v1.json` is the small local schedule registry. Selection
matches venue/product and a half-open effective interval. Unknown effective
instants require an explicit version and remain conditional; an observation date
never becomes a fabricated effective date. New versions must retain old records,
close old known intervals, and avoid overlapping intervals. Ambiguity and duplicate
versions raise errors. The MLB example selects before/at the actual retained
August fee-change timestamp; its base rounding-version timing remains conditional.

Each result embeds the exact context, complete registry snapshot, selected row,
engine version, hashes and arithmetic trace. `replay()` uses that embedded registry
and rejects altered inputs, hashes or results. Preserve the engine version and
referenced source artifacts with the audit. Hashes detect corruption; they do not
sign or authenticate evidence. No database or general rules language was added.

A fresh 100-digit Decimal context isolates calculations from caller precision,
rounding and traps. Inputs are bounded to 24 significant digits and 12 decimal
places, with at most 10,000 fills. Intermediate values remain Decimal; only JSON
output converts them to strings. Rounding uses explicit venue stages. Novig VWAP
retains its computed intermediate; conditional aggregation is never silently
selected for multiple taker fills. Per-order accumulators retain their remainders.

## Verification and preservation

**247 offline tests pass (213 existing, 34 fee tests); all eight existing examples
and the new fee example pass.** The new example contains 27 checked scenarios.

Run from the repository root:

```sh
.venv/bin/python -m app.fee_example
.venv/bin/python evidence/slice-9/verify.py
```

The [fee example](../evidence/slice-9/fee-example.json) contains official worked
examples and labeled synthetic boundary, grouping, maker/taker, outcome, unknown,
account and historical cases. Expected amounts are literal official examples or
independently checked arithmetic, never calls to the engine to generate an oracle.
Tests also cover tampering, Decimal-context isolation, scope, fractional units,
effective boundaries, future changes, null clearing and separate orders.

[Full verification](../evidence/slice-9/verification.json),
[preservation comparison](../evidence/slice-9/preservation.json),
[artifact manifest](../evidence/slice-9/manifest.json).
PLAN.md, adapters, shared models, previous tests and historical evidence are
preserved. Credentials were neither read nor changed. No dependencies were added.
No trades, balances/history, funds, purchases, contacts, commits, pushes or
publishing occurred. README and the Desktop tracker reflect this handoff.

Slice 10 must consume fee applicability and independent settlement qualification,
retain UNKNOWNs and prevent unsupported charges from becoming zero. ProphetX
native sizing and Novig live ingestion remain separate constraints. No arbitrage
detection, sizing, execution, dashboard or database is included here.
