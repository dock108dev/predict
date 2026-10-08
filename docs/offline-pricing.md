# Offline reference pricing

`app/pricing/baseline.py` computes bounded synthetic offline estimates in
`fair-price-bundle-1`, retaining complete `reference-bundle-1` dependencies.
Older illustrative fair-price records remain readable under their own contract.

The `offline-eligibility-1` policy requires explicit verified pairing, known
lineage, eligible receipt/source clocks, a pregame cutoff and independent
bookmaker families. Target venues and known copies cannot supply their own
reference probability. Missing lineage is ineligible.

For paired decimal odds `a, b`, normalize the reciprocal probabilities by their
sum. The first normalized probability is equivalently `b / (a + b)`. The engine
uses Decimal arithmetic and preserves original inputs and policy in its export.
Shared settlement determines the conditional ordinary-outcome interpretation.

These models and their freshness thresholds are offline test behavior, not
qualified live-feed settings or automatic current-board probabilities. Database
persistence and replay are separate from ordinary dashboard startup. See
[offline opportunities](offline-opportunities.md) and [architecture](architecture.md).
