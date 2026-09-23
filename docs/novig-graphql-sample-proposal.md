# One public Novig GraphQL sample — NOT APPROVED

September 21, 2026. Separate from the authenticated four-source proposal. The owner chose GraphQL as a temporary direction; this is not collection approval.

Purpose: determine whether the documented public event query returns useful discovery and display fields at the documented host. No credentials, other providers, orders, introspection or account access.

Exactly one POST to `https://gql.novig.com/v1/graphql`, JSON body with `query` equal to:

```graphql
query PredictPregame {
  event(where: {status: {_eq: "OPEN_PREGAME"}, game: {league: {_eq: "NFL"}}}) {
    id description game { scheduled_start }
    markets { description outcomes { description last available } }
  }
}
```

No variables. NFL OPEN_PREGAME only. No documented pagination is assumed. No retry, redirect, host fallback or second query; null/empty/error is a valid result. Hard elapsed limit 15 seconds, request deadline 10 seconds, 1,000,000 response-byte cap, parsed catalog maximum 20 events/100 markets, 16 MiB output, 256 MiB RSS guard and 1 GiB free-disk floor. Abort on first cap, HTTP/GraphQL/schema error, unexpected authentication requirement or Stop. No budgets expand to obtain a useful result.

Retain in a fresh UUID directory under `evidence/b3-public-graphql/`: exact query/endpoint, implementation identity, approval/consumed marker, status and receipt timestamp, successful original response bytes and SHA-256, parsed display catalog, source health, stop/failure report and replay result. Retain a sanitized reason on rejected/oversize responses rather than claiming a complete response. Do not rewrite earlier evidence or retry the consumed attempt.

Interpretation checks: match event IDs/descriptions/schedules and literal available/last values to original response; keep missing metadata explicit; prices have receipt timestamps only; no quantities or purchase asks, no net-profit or full-depth claim. Validate catalog reconstruction and saved cutoff in the ordinary product. Keep this public observation separate from NBX or production-qualified comparisons.

Before execution freeze the app hash map, exact output UUID and once-only approval package. No credential setup is needed. Approval question: **Approve this one unauthenticated GraphQL sample with the exact query and limits above?** This approval is required by the owner's explicit continuation gate before any new collection.
