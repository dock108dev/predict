# Offline opportunity calculations

`app/opportunities/service.py` evaluates receipt-bound exported estimates and
explicit synthetic prediction-book inputs using shared matching, settlement, fees and depth.
The storage interface persists complete immutable audits atomically; the pure
service supports offline recomputation without asserting durable persistence.

Inputs retain reference history, exact native market revisions, original book
receipts and quantities, fee context, sizing, probability model or null, policy
and evaluation cutoff. Later knowledge cannot rewrite a saved result. Unknown,
changed, late or mismatched dependencies are rejected or withheld according to
the contract. Reference prices are not executable books.

Arbitrage and model-based EV are separate results. This service requires synthetic
provenance for books, mappings and assumptions; its output is not a current
production opportunity. Ordinary board calculations use current SQL inputs and
their own [financial contract](requested-trade-financial-contract.md), with named
benchmarks and explicit modeled assumptions. The offline model does not supply
live probabilities to that path. See [offline pricing](offline-pricing.md).
