# Slice 1 — shared models and read-only adapter foundation

Completed **2026-09-11**, under explicit owner authorization for local implementation
using wholly synthetic fixtures. **Synthetic qualification only.** No live adapter,
account access, new venue data, stream connection or database was used.

## Implemented files

| File | Responsibility |
|---|---|
| [core.py](../app/models/core.py) | Venue/native references, event/market/outcome, probability, quantity, money, raw envelope, quotes, outcome books, settlement profiles and pairwise compatibility |
| [base.py](../app/adapters/base.py) | Async discovery, snapshots, update iteration, settlement rules and resource cleanup; no trading/account methods |
| [synthetic.py](../app/adapters/synthetic.py) | Finite invented adapter, unknown-ID errors and cancellation propagation |
| [moneyline.json](../app/fixtures/moneyline.json) | Entirely invented teams, prices, rules and updates; no Phase 0 data reused |
| [example.py](../app/example.py) | Runnable discovery → snapshot → rules → updates demonstration through the abstract interface |
| [test_models.py](../tests/test_models.py), [test_adapter.py](../tests/test_adapter.py) | Focused failure cases and adapter contract checks |
| [pyproject.toml](../pyproject.toml), [README.md](../README.md) | Python requirement and local run instructions; no third-party dependencies |

Package initializers complete the local `app`/`tests` layout from the plan. File
identities are recorded in the [validation manifest](../evidence/slice-1/manifest.json).

## Model and adapter contract

- Numeric model constructors require finite `Decimal` values. The explicit parsing
  helper accepts decimal text, integers or Decimal and rejects floats and booleans.
  It does not quantize or perform arithmetic. Probability is a dimensionless payout
  fraction in [0,1]; endpoints are valid observations, not eligibility to trade.
  Monetary amounts carry a three-letter currency code. No currency registry or FX
  conversion is implemented. Signed money and zero quantities can be represented;
  snapshot book levels must have positive size.
- Quantity units are declared strings: contracts, stake currency, payout units or a
  venue-specific unit can be retained without conversion. Use `unknown` when units
  are unverified. A book requires consistent units across its levels; no cross-venue
  comparability or contract payout equivalence is inferred.
- Venue-native event and market IDs live in the raw envelope's immutable `NativeRef`.
  Outcome IDs remain distinct. Canonical event, market and outcome mappings are
  optional; ingestion does not depend on matching. Empty discovered outcomes or
  participants mean none identified by this observation, not a complete taxonomy.
- Receipt time is mandatory and timezone-aware. Exchange time is separately optional
  and never substituted with receipt time. Aware offsets are retained. No latency or
  clock-order claim is made. Python datetime has microsecond precision; original JSON
  retains any finer source timestamp for a later adapter to handle explicitly.
- `RawPayload` keeps source location/channel, native identity, evidence kind, receipt
  time and original JSON text. Decoding returns a fresh object with Decimal fractions;
  altering it cannot mutate the retained source. Non-JSON formats and compression
  are not handled by this slice. No persistence or replay engine is implemented.
- Books contain separate outcome ladders. `None` means a side was unavailable;
  an empty ladder is an observed empty side. Each supplied side has independent
  unknown/partial/full depth. Bids descend, asks ascend, duplicate price levels are
  rejected; later adapters must explicitly normalize/aggregate native messages.
  No complementary ask, missing outcome, additional depth or synchronization is
  synthesized. A crossed observation is not automatically rewritten or discarded.
- Market state and book synchronization default to UNKNOWN. Sequence is optional
  opaque source text and does not prove continuity. Unknown rules remain `None`.
  Settlement compatibility belongs to a pair of market references and defaults to
  UNKNOWN; recording another value requires a rationale, but does not itself verify
  the conclusion. No matching or settlement decision algorithm exists.
- `stream_markets` returns an async iterator of whole observations: Market, Quote,
  OrderBook or SettlementProfile. It does not expose order entry, cancellation,
  balances or positions. Native deltas, reconnect recovery and transport belong to
  subsequent adapters; consumers must still honor unknown/stale/suspended states.
  Errors and cancellation propagate. The async context manager closes resources.

## Verification actually performed

Runtime: **Python 3.14.5**. Project metadata requires Python 3.11+; other Python
versions were not exercised. No dependencies were installed.

| Check | Actual result |
|---|---|
| `python3 -m unittest discover -s tests -v` | **16 tests passed**, 0 failures/errors |
| `python3 -m app.example` | Exit 0; finite demonstration completed |
| Network isolation | Full synthetic adapter contract passed with socket creation patched to raise |
| Preservation | PLAN.md and all existing Phase 0 files compared against baseline hashes; original 13 source hashes checked against their manifest |
| Documentation | Local links checked; mandatory support-inquiry instructions replaced |

Tests cover exact long-decimal preservation under a low-precision context, rejection
of floats/bools/nonfinite/malformed numbers, invalid prices/sizes/currencies, naive
timestamps and unknown exchange times, unmapped ingestion, native IDs, immutable raw
text and nested decoded data, empty versus unavailable sides, partial depth, invalid
ordering/duplicate levels/unit mismatch, unknown states/rules, the complete synthetic
async flow, invalid subscriptions, cleanup on failure, cancellation and the read-only
public interface.

Example output included:

```text
SYNTHETIC ONLY: Comets at Lanterns; venue=synthetic
native event=invented-event-001; market=invented-moneyline-001; canonical=None
state=unknown; sync=unknown; exchange_at=None
comets-win: bid levels=2; depth=partial; asks=None; unit=synthetic_lots
lanterns-win: bid levels=1; depth=partial; asks=None; unit=synthetic_lots
first price=0.410000000000000000000000001
overtime=None; cancellation=None
quote: bid=0.42; size=None; ask=None; exchange_at=2026-09-11T11:59:59.500000+00:00
market update: state=suspended; exchange_at=None
Complete: finite synthetic demonstration; no live qualification.
```

## Remaining boundary and next action

Slice 1 is complete. No fees, matching, arbitrage, durable storage, execution, live
transport or later slice has been implemented. Synthetic success establishes model
and interface behavior only; it does not establish venue permission, membership,
streaming reliability, fee applicability, settlement equivalence or profitability.

**Next action for Slice 2:** prepare a bounded Polymarket US **retail** access and
prerequisite review, identifying applicable retail terms and owner-authorized
account/API-key availability for the authenticated market stream. The existing
public REST samples do not supply those prerequisites. Keep institutional and
international paths distinct. Slice 2 integration and any account access require
separate authorization; none began here. A Kalshi support inquiry is optional.

## Revalidation of existing completion — September 11, 2026

The attached request was checked against an already implemented Slice 1. All 19
existing artifact hashes matched the completion manifest before this recheck; no
application or test changes were necessary. The 16 tests passed again, including
the adapter contract with socket creation blocked, and the example exited 0 on
Python 3.14.5. All 13 captured-source hashes and the original PLAN.md hash matched.

The official Kalshi Developer Agreement v1.1, its landing page, API introduction,
market-data quickstart, WebSocket guide and API-key guide were rechecked. The
corrected permission assessment and optional, unsent inquiry remain current for
this scope. No account conditions, live reliability, fees or settlement equivalence
were qualified. Slice 2 remains unstarted; its next action remains the bounded
Polymarket US retail access/prerequisite review described above.
