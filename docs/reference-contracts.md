# Reference records and eligibility

`app/edge_contracts.py` implements `edge-contracts-1`: validated reference quotes,
fair-price records and signal input eligibility. Native prediction quotes and
reference bookmaker prices are separate types. References never become executable
order books through an implicit conversion.

References retain canonical event/market IDs, original provider identity, receipt
and source timestamps, decimal spelling, provenance and explicit lineage.
Matching evidence is versioned; ambiguous or unknown mapping stays unavailable.
Fee, settlement and depth calculations reuse the shared domain engines.

Reference records alone do not select a provider or establish a production
probability model. The [offline pricing baseline](offline-pricing.md) uses a
separate receipt-bound estimate format. The ordinary current board requires its
own supported probability basis before displaying dependent EV.
