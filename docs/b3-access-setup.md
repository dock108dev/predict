# Getting Novig and ProphetX access into Predict

**Current access status (September 21):** owner sent both Novig and ProphetX requests; provider responses are pending. No duplicate request is needed. Credentials/production access remain unconfirmed. [Access status](b3-access-status.md) · [Next independent work: B4](b4-independent-handoff.md).

September 21, 2026. Setup stores secrets locally; it does not start collection. B3 IN PROGRESS; beta NOT READY. The owner has sent both access requests; the steps below are retained setup guidance, not instructions to send duplicates.

## Novig

1. **Request already sent; await the response.** The documented contact is developers@novig.co. Ask for NBX QA and production client credentials for private read-only discovery, listing metadata and prices. Novig publishes that contact in its [GraphQL migration notice](https://docs.novig.com/api-reference/graphql/overview).
2. Obtain the environment-specific client ID and client secret securely. Ask Novig to confirm issued token/REST hosts, listing-period/rule fields and initial-book guarantees. [Authentication](https://docs.novig.com/api-reference/authentication) requires client credentials; GraphQL needs none. Do not assume QA access grants production.
3. From a local Terminal in this repository, with the project's Python environment active, run:

```sh
python -m app.collection.native_credentials novig --environment production
```

Enter the client ID and secret at the hidden prompts. For QA, use `--environment qa`. This saves JSON under `prediction-arb.novig.production` / `market-data` (or the QA equivalent). The older diagnostic setup command stored separate fields and is not the B3 setup command.

GraphQL is useful for a small discovery/display bridge only. It does not currently supply qualified purchase comparisons. No key is needed for the [separately proposed public sample](b3-graphql-sample-proposal.md); it has not been approved or run. NBX remains the intended durable route.

## ProphetX

1. **Request already sent; await the response.** Reference: [Requesting API Access](https://docs.prophetx.co/docs/requesting-api-access), including its **New Access Request** form for Trading API access. Explain that Predict only reads market data, request production access plus a separate sandbox if useful, and confirm any conditions or cost before accepting them.
2. The currently implemented adapter uses the **Trading API access key and secret key** with login, then read-only `/mm` market endpoints. Request those production credentials and the production NFL tournament ID or a documented tournament-discovery route. Historical sandbox tournament 31 is not a production default.
3. ProphetX also offers a [read-only Market Data API](https://docs.prophetx.co/docs/market-data-integration). It uses a **single affiliate key** and `/affiliate` endpoints; that is a different credential and adapter contract. If ProphetX provisions that instead, tell me the API type before setup so I can adapt it. Do not enter an affiliate key into the Trading key/secret fields.
4. Once Trading API credentials are issued, run locally:

```sh
python -m app.collection.native_credentials prophetx --environment production
```

Enter the access key and secret key at hidden prompts. For sandbox, use `--environment sandbox`. Storage: `prediction-arb.prophetx.production` / `trading-api`, or its sandbox equivalent. Existing compatible environment-tagged JSON from the older setup is accepted if the environment matches.

## After setup

Tell me only which environment is ready and which local reference was saved. If supplied, include the issued access-document path and production tournament ID. Never paste keys, secrets or tokens into chat. I will freeze the candidate and exact scope for the [four-source qualification proposal](b3-native-qualification-proposal.md), obtain its approval once, then use an explicit Start. Credential entry does not authorize collection.
