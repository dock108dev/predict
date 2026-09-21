# B3 bounded native qualification proposal — awaiting access references

**Current access status (September 21):** owner sent both Novig and ProphetX requests; provider responses are pending. No duplicate request is needed. Credentials/production access remain unconfirmed. [Access status](b3-access-status.md) · [Next independent work: B4](b4-independent-handoff.md).

Prepared September 21, 2026. **Not approved or executed. B3 remains IN PROGRESS; beta NOT READY FOR SIGNOFF.** [Implementation/evidence](b3-native-integration.md).

The implementation is reviewable. Finalizing this one proposal requires Novig environment/provisioning references and ProphetX production access. ProphetX was selected by the owner on September 21. Production access remains unverified. No approval is inferred from the implementation request. Do not create an approved authorization file until the owner approves the completed scope below; no credentials in chat.

## Proposed single production session

- Sources: Kalshi, Polymarket **US**, Novig and **ProphetX (owner-selected September 21)**. A different fourth venue requires revising this proposal before approval, not substituting a source during execution.
- Environment: production for all four. QA/sandbox is not part of this proposed attempt. Existing sandbox observations remain retained history, never production evidence. If Novig is QA-only, production qualification stays blocked; do not silently switch this run to QA.
- Purpose: native observations and useful overlap in the ordinary Predict dashboard, actual native price/quantity reconciliation, dated updates, source health, explicit limitations, Stop and exact saved-cutoff reopening. No profitable result is required.
- Session: one explicit Start in an owner-approved 15-minute UTC start window, 90-second hard collection deadline including discovery/authentication. Click Stop at approximately 60 seconds if all required observations are available. No autoresume or automatic second run. Fresh UUID/output directory; consume the allowance before Start access. Existing attempt markers are untouched.
- Initial acquisition scope: NFL pregame. Kalshi `KXNFLGAME`; US `tagSlug=nfl`, independently enumerate markets by native game ID without a winner-only query restriction. Novig NFL, one event, at most two markets; ProphetX one event from the provisioned NFL tournament (retained sandbox tournament 31 must not be assumed to identify production). Selection need not be profitable. Retain unsupported returned listings with their native metadata and reasons; this bounded qualification is not an NFL-only beta definition.
- Overlap: shared participant/schedule/native outcome bindings must support the same ordinary comparison path. Novig listing period/rule association remains unresolved and must be resolved from actual listing/provisioning evidence before claiming useful comparison participation. Unknown period is not promoted to full game. ProphetX unsized quotes may participate as unavailable comparisons, with no sized profit claim.

## Access references and requests

| Source | Dedicated local credential reference | Destinations and read-only operations |
|---|---|---|
| Kalshi | `keychain:prediction-arb.kalshi.production/market-data` | `external-api.kalshi.com`: GET account limits/endpoint costs, bounded events/markets; `external-api-ws.kalshi.com/trade-api/ws/v2`: orderbook snapshot/delta subscriptions |
| Polymarket US | `keychain:prediction-arb.polymarket-us/retail-api` | `gateway.polymarket.us`: GET events/markets; `api.polymarket.us/v1/ws/markets`: authenticated market data subscriptions |
| Novig | proposed `keychain:prediction-arb.novig.production/market-data`; owner must confirm issued provisioning | `api.novig.com/nbx/v1/auth/emm-token`: OAuth token; GET `/nbx/v2/emm/events`, events/{id}, events/getMarketsByEvent/{id}, locks, book/{id}. Dated REST snapshots every 30 seconds. No streaming activation in this first scope. Confirm issued token/REST hosts rather than probing alternatives. |
| ProphetX | proposed `keychain:prediction-arb.prophetx.production/trading-api` | `cash.api.prophetx.co/partner`: POST auth/login (refresh only within allowance if required), GET mm/get_sport_events and v4/mm/get_multiple_markets. Dated REST snapshots every 30 seconds. No quiet WebSocket recapture. Production tournament ID/access must be confirmed before freezing the spec. |

Novig Keychain JSON fields are `client_id` and `client_secret`; ProphetX fields are `access_key` and `secret_key`. Entry is owner-local through the existing macOS secret-storage workflow. Secrets/tokens/authentication bodies are never retained. Disabled/unconfigured slots perform no credential lookup. No account creation, provider messages, orders, funding, paid access or reference-provider acquisition.

## Limits, Stop and evidence

- Kalshi and US: at most 100 REST attempts each, at most 100 selected markets each, six concurrent sockets total and twelve connection attempts total under the existing collector; each stream group permits two connections. Existing bounded REST retry handling is charged against the same attempt ceiling. A failed source stays visible and cannot stop healthy sources merely because its feed is unavailable.
- Novig and ProphetX: at most 30 HTTP attempts per adapter including authentication, zero automatic adapter retries; one adapter per source in this proposal, 2,000,000 response bytes each. Failed market requests are not automatically repeated. Other independent sources/markets may finish their existing finite work. No cap extension to obtain a positive or complete result.
- Existing collector limits remain: 16 MiB encoded ingress/2,048 accepted records; 32 MiB/4,096-record journal; 128 MiB output; 256 MiB RSS stop threshold; 1 GiB free-disk floor; queue 48 records/4 MiB. Kalshi/US each have 16 MiB body allowance, 1 MiB maximum frame, 600 messages per group. The first reached limit or deadline ends intake. These are short-run limits, not sustained reliability claims.
- Stop cancels pending work, closes adapters/sockets, rejects late observations, finalizes the existing journal/manifest and replays the same cutoff. Cleanup or persistence failure leaves incomplete history. No collection is owned by browser polling.
- Retain exact spec and implementation hash map, approval digest and consumed marker, fresh run ID, native market-data bodies/provenance, environments, metadata, health, requests/bytes, normalized observations, source limitations, original quantities, replay results, resource report and browser observations. No auth payloads or credentials.
- Reconcile representative native values independently: Kalshi opposite bids; US Long offers and Short bid complements; Novig payout cents divided by 100 and opposite bids; ProphetX American prices with quantity/value still unknown unless a source contract resolves ownership. Unknown fee applicability and settlement remain unavailable; never borrow another venue's economics.
- Required result matrix separates implemented/offline, historical QA, fresh production and actual ordinary-comparison participation. A missing venue, unresolved overlap or absent updates fails B3 exit criteria. Do not automatically retry a failed run.

## Approval mechanism and outstanding owner action

After access references are supplied, engineering freezes the UTC window, exact production tournament/native scope, run spec, app identity and isolated output into one reviewable authorization package. `native_approval.py` checks those hashes and once-only consumption; `app.dashboard.native_preview` opens the ordinary dashboard idle. Start stays disabled without a matching approved package. This document is the bounded proposal, not that approval file.

Owner action now: ProphetX selection is resolved (September 21). Confirm Novig production/QA provisioning and ProphetX production access using local secret-store and issued access-document references only. [Novig documentation review](novig-access-review-20260921.md) identifies public but sunsetting GraphQL; it is not included in this NBX proposal. Any bridge scope must be explicit. **No new authenticated access or collection has occurred.**

## Continuation disposition

ProphetX is selected and remains not_configured with zero access. Native REST segmented replay is verified offline, but this proposal retains its existing flat-session limits and authorization boundary. Novig public GraphQL is a separate discovery/display bridge; its [one-sample proposal](b3-graphql-sample-proposal.md) neither consumes nor changes this authenticated scope. Keys can be obtained when needed, but none were confirmed or accessed. [Access/setup](b3-access-setup.md).

Current ProphetX documentation also describes an affiliate Market Data API with a single raw Authorization key and separate /affiliate routes. The implemented producer uses Trading API credentials and /mm routes. Do not substitute the affiliate key or reinterpret its quantity contract automatically. Confirm issued API type, production tournament identity, applicable quantity/value units, rules and dated REST semantics before freezing this scope. New documentation identifies strike_id as instrument identity for affiliate selections, but that does not qualify the retained Trading quantity units or source clocks.
