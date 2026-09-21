# Prepared Novig provisioning draft — retained reference

Owner status, September 21: a brief Novig access request has been sent and is pending. This longer prepared draft is not asserted to be the exact sent message; do not resend it.

To: developers@novig.co
Subject: NBX QA and production access for a private read-only market-data tool

Hello Novig developers,

I am building Predict, a private sports market-data comparison tool. Please provide the onboarding requirements for separate QA and production NBX OAuth client credentials. We need read-only event/market discovery, listing metadata, status/locks, order-book snapshots and potentially market-data updates. We will not place orders, fund accounts or use account/position data through this integration. Please deliver credentials through a secure channel.

Please confirm:

- Issued QA/production token, REST and WebSocket hosts; read-only permissions, rate limits, any access cost and private raw-response retention terms.
- How an exact event/market ID identifies full-game versus half/period scope, overtime treatment and listing-specific settlement/void rules. Missing period fields will remain unknown in our tool.
- CASH book quantities, ownership of each bid, whether complementary purchases are supported for every returned market, and any exceptions to payout-cent interpretation.
- A market-specific initial book example, snapshot-to-update ordering, sequence/source-clock semantics, depth/completeness guarantees, and implicit cancellation behavior on lifecycle changes.
- The GraphQL sunset timetable and migration guidance. The overview documents gql.novig.com while the affiliate odds-screen guide names api.novig.com; please confirm current endpoint/schema compatibility and available/last semantics.

Thank you.

Prepared only. Not sent. Contact source: [official migration notice](https://docs.novig.com/api-reference/graphql/overview).
