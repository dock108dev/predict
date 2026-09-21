# Novig temporary GraphQL bridge decision

September 21, 2026. Owner requested GraphQL for now, with NBX if it is not useful. **Useful narrowly: discovery and dated display prices. Not sufficient for B3 purchase comparisons.** No endpoint query or credential access occurred.

## Checked contracts and decision

The [overview](https://docs.novig.com/api-reference/graphql/overview) documents unauthenticated `https://gql.novig.com/v1/graphql` and an impending sunset without a date. The [playground](https://docs.novig.com/api-reference/graphql/playground) supplies event filtering, event IDs, schedule, market/outcome descriptions and `last`/`available`. That supports a small replaceable display bridge. Documented pagination/cursors, source-price timestamps, market IDs within this event query and period/rules are absent; receipt time cannot establish price age. Do not invent pagination or infer full game.

The separate [market query](https://docs.novig.com/api-reference/graphql/market-queries) exposes ID/type/strike, probability and order price/qty. It does not connect the demonstrated event shape to that market-ID query or provide an executable-side guarantee; qty is described generically as minimum currency units. The bridge deliberately requests no orders or quantities and emits no purchase book.

The [affiliate odds-screen guide](https://docs.novig.com/affiliates/odds-screens) gives useful additional bid/quantity interpretation and distinguishes available from last trade. However, it names `api.novig.com/v1/graphql`, unlike the public overview. Its example quantity math is not assumed to validate the `gql` schema. No host fallback, price complement, NBX unit reuse or complete-depth claim is implemented. Last trade remains labeled last trade.

The isolated producer uses the common discovery, health, Stop, catalog projection and flat/segmented history interfaces. Original successful bodies and query are retained; replay reconstructs the display catalog, including matching exclusions. Positional display IDs explicitly are not native market identities. Native metadata/rules remain unknown. GraphQL failure/oversize/partial errors are unavailable without automatic retries. Other venues continue.

Current fixed query: NFL pregame display catalog. This sample scope does not restrict the beta definition. Runtime maximum: two requests, 1,000,000 cumulative response bytes, 10-second per-request deadline, no redirects, no credentials. Catalog parsing caps 20 events and 100 markets. No schema introspection, open-ended pagination or mutation. The first public sample has a smaller one-request proposal.

**Do not invest in deeper deprecated GraphQL normalization without new supporting evidence.** NBX remains the durable route, and exact native period/rule association is still required for real useful overlap. GraphQL is not a substitute for four-source production qualification.
