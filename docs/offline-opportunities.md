# Offline opportunity calculations

`app/opportunities/service.py` evaluates receipt-bound exported estimates and
explicit prediction-book inputs using shared matching, settlement, fees and depth.
The storage interface persists complete immutable audits atomically; the pure
service supports offline recomputation without asserting durable persistence.

Inputs retain reference history, exact native market revisions, original book
receipts and quantities, fee context, sizing, probability model or null, policy
and evaluation cutoff. Later knowledge cannot rewrite a saved result. Unknown,
changed, late or mismatched dependencies are rejected or withheld according to
the contract. Reference prices are not executable books.

Arbitrage and model-based EV are separate results. The current board's signed
gross percentages use their own original-input contract and do not imply that the
offline storage model is a live probability source. See [offline pricing](offline-pricing.md).
