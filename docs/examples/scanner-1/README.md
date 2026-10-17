# Authored SC02 consumer examples

Every JSON file here is an authored protocol fixture, not live/source/model evidence. [Schema](../../contracts/predict-opportunity-scanner-1.schema.json), [consumer rules](../../scanner-projection-contract.md).

1. `cold.json`: not yet evaluated; no checked-zero claim.
2. `snapshot.json`: one flat globally ranked coherent page.
3. `unchanged.json`: retain the existing page; adopt supplied current coverage.
4. `changed.json`: atomically replace the page and ranking. Previously held IDs absent from `ranked_ids` leave this view.
5. `resync.json`: discard the prior page and adopt this bounded snapshot after a gap/epoch/query mismatch.
6. `stopped.json`: empty authoritative replacement; Stop withdrew the previous rows.
7. `receipt.json`: **trusted internal** v2 proof only. Never submit it over HTTP.

Store `server_id`, `epoch`, `publication_revision`, `query_id` and the exact filters/page. Repeat `/api/scanner` with `since`, `epoch`, `query_id` and those same filters. A changed filter/page begins a fresh snapshot. A multi-page reader supplies `expected_revision`; on 409 discard the partial collection. Apply replacement responses atomically. At row `expires_at`, withdraw current authority locally even without another response. Do no client money/percentage/allocation arithmetic and do not treat source receipt, SQL observation or publication time as an original-price renewal.

SC03 will provide stable selected manual tickets and exact verified venue destinations. SC04 uses these scanner responses for selection identity, not legacy game grouping or Details close/reopen behavior. SC06 adds actual delivery/render timing and episode semantics.
