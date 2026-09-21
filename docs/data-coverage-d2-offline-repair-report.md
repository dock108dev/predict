# D2 offline discovery/reporting repair — live validation outstanding

September 16, 2026. Both evidenced defects are repaired and checked offline. **D2 remains incomplete.** No credentials, fresh venue data, pilot, beta restart, attempt reset or D3 work occurred. Existing uncommitted work and all original evidence remain intact.

## Root causes and behavior

**US reconciliation.** The prior projection treated any accepted separate `gameId` query as authoritative replacement for embedded listings—even an empty HTTP 200. The projection now retains the union of native observations and their receipt/body provenance. Embedded IDs missing from a separate query explicitly produce `contradictory_listings` and unestablished completeness. Conflicting duplicate identities/metadata remain excluded; no favorable version is silently chosen. A distinct separate listing does not erase an embedded listing.

Inventory membership, completeness and subscription eligibility are separate. US subscription evidence requires a native market ID and unique slug, a resolved event, two distinct native side IDs with explicit Boolean Long/Short roles, side market IDs matching the parent market, native team names matching the resolved event participants, and nonempty native description/rules. Existing active/full-game, conflict, schedule and five-minute kickoff checks also apply. Missing or conflicting evidence blocks selection without deleting inventory. Broader unknown completeness alone does not block a sufficiently evidenced listing. This is conservative subscription identity/support evidence, not settlement equivalence or economic qualification. US Short purchase depth stays unavailable.

**Refresh publication.** Previously a `finally` block published partial traversal inventory while producer selection still described the previous traversal. HTTP receipts were also added to inventory before journal admission. A generation now publishes inventory, parsed market objects and its eligible/selected plan together, only after successful traversal and durable admission of the generation record. Failed, canceled or rejected publication retains the prior generation. Partial durable traversal, failure reason and current refresh state are separate diagnostics. Status and final reports expose generation ID, completion time and continuously computed age; no successful catalog yet means unknown counts. Producer-applied generation/selection and actual requested/acknowledged/receiving/usable counts are distinct from the published plan.

HTTP accounting separates budgeted attempts, received HTTP responses and durably retained responses. Receipt pages enter discovery only after the journal acknowledges them. A response rejected before admission is counted as received, not durable inventory; a response journaled before a queue failure remains retained. Negative safety observations from admitted partial refreshes immediately clear affected usable books and prevent reuse. Native closure flags, schedule changes, the clock-based kickoff margin and disconnection remain safety exclusions even when the last completed catalog is retained. Control-loop reconciliation retires affected subscriptions. An unchanged published catalog is not permission to reuse invalid books.

## Saved-response reproduction and checks

Only original replacement session `97dbc1e0-36c7-49c8-a19b-f4856278e21c` is used for the live-response regressions. Its journal chain remains `db0dca7dcf13b5839f9fc3323e090648f749aa9f664de04fbc1255482341609d`.

| Offline projection | Kalshi | Polymarket US |
|---|---:|---:|
| Completed generation 1 and 2 events | 32 | 32 |
| Retained markets / eligible / selected plan | 64 / 64 / 64 | 32 / 32 / 32 |
| Market completeness | exhausted for retained events | unestablished; 32 embedded listings contradict 32 empty separate queries per traversal |
| Durable third-traversal progress | 32 events / 6 markets | 20 events / 20 embedded markets |
| Coverage after interrupted third traversal | generation 2 retained: 32 / 64 | generation 2 retained: 32 / 32 |

These are repaired **offline projections**, not new subscriptions. The original live US selected/requested/acknowledged/receiving/usable counts remain **zero**. The rejected third-traversal body is not available in the journal; the regression injects a saved admitted page at the real ingress ceiling to test rejection, without presenting that page as the missing original response.

**75 tests passed** across discovery, collector, native adapters/replay, failure handling, saved calculations and math reconciliation; JavaScript syntax passed. After the final safety latch change, all 20 affected discovery/collector checks passed again; invalidated streams cannot revive on catalog publication and must resynchronize in a replacement group. Eight new focused regressions cover the actual contradictory responses, insufficient native evidence/closure, interrupted third traversal and coherent plan counts/age, actual serialized-cap rejection, publication rejection/cancellation, durable-before-queue-failure accounting, old-catalog safety invalidation/cutoff, and original native replay. The local-only HTTP/WebSocket test still exercises discovery, 24 Kalshi/eight US subscriptions, unchanged refresh and manual Stop. Its synthetic US fixtures now explicitly provide required native terms and identity. All **491** original recent Kalshi books and exact quote packets replay; saved-math regressions pass without changing original inputs. No live transition or disconnect was fabricated.

## Public documentation and unresolved contract

Reviewed the official [Get Markets contract](https://docs.polymarket.us/api-reference/markets/get-markets) and [Markets overview](https://docs.polymarket.us/api-reference/market/overview) on September 16. They document `gameId` as a string, `sportsMarketTypes` as an enum array including `SPORTS_MARKET_TYPE_MONEYLINE`, Boolean active/closed filters, and limit/offset pagination. The existing request's field names and moneyline value align with that contract. This does **not** establish why the saved responses are empty or prove backend filter behavior. No documented filter correction was identified and no query was changed. Alternative filtering/serialization/backend explanations remain unverified hypotheses; no alternate live query was attempted. Short-page exhaustion remains scoped to the retained filter traversal, not proof of all venue listings.

## Candidate and preservation

Candidate identity (SHA-256 of the canonical sorted source-hash map):
`d42c27b914996c4f05376aaf3a1982998677e34211545550d95c345ec7bf0481`.

[Exact verification](../evidence/d2-coverage/offline-repair-20260916/verification.json) records HEAD, all 181 source hashes and differences from the replacement candidate. Changes are confined to `coverage.py`, `continuous.py`, `coverage_owner.py`, `coverage.js`, the existing collector test and the new repair test; documentation/derived outputs accompany them. **1,827 preexisting evidence files match their pre-repair hashes.** No original evidence file was edited or deleted.

[Derived evidence](../evidence/d2-coverage/offline-repair-20260916/verification.json) includes generation projections, interrupted traversal diagnostics, exact replay and final test log. Reproduce from the repository root with `PYTHONPATH=. .venv/bin/python evidence/d2-coverage/offline-repair-20260916/derive.py`. Outputs stay in that new directory. The beta was not restarted and has not loaded or live-validated this candidate.

All D2 ceilings are unchanged, including the stricter **16 MiB / 2,048-record serialized ingress** bound. No collector rewrite, segmentation, settlement ingestion, database change, scheduling, spending, trading, commit, push or publishing was performed.

Next task: a separately authorized finite validation using the [prepared handoff](data-coverage-d2-validation-handoff.md). Carry forward demonstrated Kalshi coverage and browser independence; establish repaired US subscriptions, coherent refresh reporting and direct manual Stop. Broader US completeness and live resource behavior remain unresolved. No new pilot is authorized by this report.
