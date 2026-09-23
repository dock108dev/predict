# Novig access review and fourth-venue decision

**Current access status (September 21):** owner sent both Novig and ProphetX requests; provider responses are pending. No duplicate request is needed. Credentials/production access remain unconfirmed. [Access status](venue-access-status.md) · [Next independent work: B4](reference-integration.md).

September 21, 2026. Owner selected **ProphetX** as venue four. This resolves product selection only; runtime activation, production access and qualification remain unverified. No source code, approval file, credentials or retained evidence changed.

## Official documentation reviewed

- [NBX authentication](https://docs.novig.com/api-reference/authentication): OAuth client credentials must be requested from Novig. Tokens expire after 30 minutes; QA and production differ. This confirms the NBX provisioning dependency, not the owner's account status.
- [REST destinations](https://docs.novig.com/api-reference/rest-api): production `https://api.novig.com/nbx/v2`, QA `https://api-qa.novig.us/nbx/v2`; published per-route limits and millisecond retry/reset headers. Existing bounded proposal limits must not be expanded just because published ceilings are higher.
- [GraphQL overview](https://docs.novig.com/api-reference/graphql/overview): explicitly public without authentication at `https://gql.novig.com/v1/graphql`, but scheduled to be sunsetted. No cutoff date is given on this page. Novig directs migration requests to developers@novig.co for NBX client credentials.
- [GraphQL market queries](https://docs.novig.com/api-reference/graphql/market-queries): documents market type/strike, outcomes, probabilities and current order price/quantity. Availability, freshness, complete depth, side semantics and unit compatibility with NBX are not established by examples; quantity is described as minimum currency units, so do not automatically apply NBX payout-cent conversion.
- [Public daily exchange data](https://docs.novig.com/api-reference/trade-data): unauthenticated daily trade/market CSVs, useful for history and mapping. These are not current executable order books.

## B3 disposition

NBX remains the intended durable integration. Owner/provider assistance: request Novig-issued client ID/secret and QA/production provisioning; enter secrets locally. The prepared request remains unsent. Documentation alone does not establish that credentials have been provisioned.

Public GraphQL is an additional candidate read-only bridge, not proof all Novig data is blocked on credentials and not an automatic substitute for NBX. Engineering should assess the documented contract and sunset risk; if useful, propose a separately bounded public sample with explicit units, freshness and completeness checks. Do not change the existing four-source qualification proposal to GraphQL silently. No API query or market-data download was performed in this review.

Continue native period/rule mapping and segmented native replay independently. Record any future GraphQL observations by their actual transport and evidence scope. B3 remains IN PROGRESS; beta NOT READY. ProphetX selection does not authorize a live run.
