# Slice 5 — Novig read-only ingestion

September 12, 2026 UTC. Implementation and offline verification complete within the limits below; **QA and production live ingestion are not qualified**. Slice 4's bounded NFL qualification remains unchanged. Slice 6 has not started.

## Implemented

`app.adapters.novig.NovigAdapter` implements the shared read-only interface. NFL/MLB pregame event discovery uses bounded offset pagination and native identities; markets are bounded by event and count. CASH REST books reconstruct individual order identities and aggregate price levels with Decimal. PLACE replaces the order's remaining quantity; CANCEL removes its ID idempotently. Zero remaining quantity removes a level contribution. Native bids produce sized probability quotes; asks remain unavailable. Raw JSON, receipt time, environment-specific source URLs and evidence kinds are retained. No canonical mappings, fees, matching, settlement decisions or trading methods were added.

REST event/market status and system/event locks are refreshed for snapshots and each connection. Locks are polled every three seconds while streaming and become unknown after five seconds; an OPEN tick cannot override a lock. Status, locks, event liveness, reconstruction, depth, source time and transport health are separate. Closed books clear without waiting for CANCEL; stale order messages cannot revive them. Event-wide live transitions drain selected books once per edge, including repeated live/unlive cycles. END becomes unknown rather than inventing settlement semantics.

The stream uses market-specific subscriptions plus `lifecycle`, never the updates-only global tape as bootstrap. Connections have separate generations, fresh event/market/lock refreshes, fresh initial images, bounded renewal/reconnect and cleanup. Incoming protocol Ping is handled by the websockets library; no JSON ping is sent. Closing/canceling the iterator closes the socket and invalidates reconstruction. Raw accepted transport frames remain available separately from normalized observations.

OAuth tokens renew before their documented 30-minute expiry and on a retriable HTTP 401. REST/auth transient failures have bounded retries. HTTP attempts include authentication in the total budget. Requests are paced at a conservative 250 ms interval; retry/reset headers are interpreted as milliseconds, with a ten-second wait ceiling. Bodies and stream frames have byte budgets. Errors do not become empty successful observations.

## Access and current official contract

Only the dedicated macOS Keychain services `prediction-arb.novig.qa` and `prediction-arb.novig.production` were checked, with accounts `client_id` and `client_secret`. Both pairs are absent. No credential values were printed, no unrelated credentials were searched, and no private endpoint was probed. No provisioned QA or production entitlement is established. The public [authentication guide](https://docs.novig.com/api-reference/authentication) says Novig must issue the client ID/secret; no self-service credential-issuance route is documented there.

| Environment | REST | Token | WebSocket |
| --- | --- | --- | --- |
| Production | `https://api.novig.com/nbx/v2` | `https://api.novig.com/nbx/v1/auth/emm-token` | `wss://api.novig.com/tape` |
| QA | `https://api-qa.novig.us/nbx/v2` | `https://auth-qa.novig.us/oauth/token`, audience `https://api-qa.novig.us` | `wss://api-qa.novig.us/tape` |

These are **documented**, not observed provisioned hosts. QA token details follow the explicit [WebSocket authentication guide](https://docs.novig.com/api-reference/WSS/authentication). Embedded OpenAPI overview prose still shows older production OAuth configuration; the implementation uses the current standalone production guide and does not try alternatives. Confirm the provisioned environment if Novig supplies different instructions.

[REST connection details](https://docs.novig.com/api-reference/rest-api) say data requests have a 256/sec ceiling; endpoint pages variously say 128 or 512/sec. These conflicts remain unresolved account entitlements; no load testing occurred. Retry-After and X-RateLimit-Reset are documented as milliseconds until retry/reset.

[NBX fees documentation](https://docs.novig.com/fees) explicitly states 100 API qty = one $1 payout contract. CASH quantity is therefore preserved as `payout_cents`, not stake or contract count. Prices remain probability fractions. The current NBX [data model](https://docs.novig.com/api-reference/data-model) documents two outcomes and .001–.999 prices. Decimal decoding avoids binary float conversion. Documentation supports units; no live payload has corroborated them in this project.

The [REST book schema](https://docs.novig.com/api-reference/markets/get-order-book) supplies `outcomeLadders` and obfuscated individual bids. [Order ticks](https://docs.novig.com/api-reference/WSS/orderbook-channel) are bare PLACE/CANCEL payloads; `qty` is remaining quantity and `created_at` is order creation time. The adapter never treats it as the source timestamp of later observations. Fills remain raw evidence and are not subtracted again from remaining quantities.

[Lifecycle documentation](https://docs.novig.com/api-reference/WSS/lifecycle-channel) describes CLOSE's implicit cancellations and EVENT_GOLIVE preceding itemized cancellations. [Locks](https://docs.novig.com/api-reference/markets/get-lock-status) describe currently active system and event locks. The NBX market schema has no verified listing-specific rules link or per-listing fee schedule; settlement profiles leave those fields unavailable. `get_fee_metadata` retains the native market reference, observed event status and official schedule URL without computing fees. The general [contracts index](https://support.novig.com/en/articles/16083642-contracts) is available for later listing-rule research; it is not silently assigned to individual listings.

## Important limits

The WebSocket guide promises enveloped initial `book` messages but does **not** specify the complete initial payload shape. The implemented compatibility branch accepts `{"event":"book","data":<REST BookResponseDto>}`. That branch is synthetic-tested and explicitly **unverified on the wire**. Other shapes fail closed with raw evidence retained. Multiple partial initial messages are not merged on an invented completion rule. A live sample may require an ordinary parser repair.

No documented sequence/replay cursor or atomic handoff guarantee was found. Book synchronization and depth stay UNKNOWN even after a valid local reconstruction; missing bootstrap and disconnect become UNSYNCHRONIZED. No source update clock is invented, and receipt freshness is not transport latency. Lifecycle REST/bootstrap races and delayed/duplicate messages within one live subscription cannot be fully ordered without a venue contract; generation fencing protects old connections only. Event liveness snapshots and lock polling are not atomic with books. Reopening does not establish a complete image beyond known local state. Continuous reliability and execution capacity remain unclaimed.

No real updates, naturally occurring halt/closure, QA liquidity, production liquidity, actual token expiry, listing rules, account fee eligibility or data-retention entitlement were verified. These limitations do not block independent later implementation.

## Verification and use

**138 tests pass**, including 28 new Novig tests. All four existing examples plus the new Novig example exit successfully. The original 110 tests remain intact. Novig tests use wholly synthetic HTTP/socket fixtures; one Ping/Pong test uses a local loopback WebSocket server only. They cover units, replacement/aggregation/cancel, malformed inputs, identities, missing bootstrap, lifecycle/locks, event-wide idempotency, old generations, retry units, 401/expiry renewal, limits, fresh recovery, iterator closure and task cancellation. No synthetic result qualifies Novig live ingestion.

```sh
.venv/bin/python -m app.novig_example
.venv/bin/python -m app.novig_verify --help
```

After receiving credentials, enter them locally with hidden prompts (never chat or command arguments):

```sh
.venv/bin/python -m app.novig_verify --environment qa --setup-keychain
.venv/bin/python -m app.novig_verify --environment qa --live --output evidence/slice-5/qa-first-capture
```

Production uses a separate `--environment production` entry. Setup and live verification are separate explicit operations. The verifier requires a new private output directory and caps 30 HTTP attempts including auth, five catalog events, two markets, 60 seconds overall, 100 frames, 8 MB REST bodies and 2 MB stream bodies. Discovery selects one returned pregame event. The stream deliberately reconnects after ten seconds and requests a new token; it stops early after fresh recovered images plus a subsequent real order update. Otherwise it stops at its bounds, retaining quiet or failing evidence. No repeated quiet runs are scheduled. Cleanup and transport counters are recorded independently; qualification is never automatically inferred from a successful exit.

Evidence: [test log](../evidence/slice-5/tests.txt), [access status](../evidence/slice-5/access-status.json), [manifest](../evidence/slice-5/manifest.json), and [preservation comparison](../evidence/slice-5/preservation.json). Official public markdown was fetched September 12 UTC into `research/`; unsuccessful documentation URL attempts are identified in the source manifest. No historical downloads were substituted for live evidence.

## Remaining action

For **Novig live qualification**, obtain Novig-issued QA client credentials and its provisioned access instructions, enter them in the dedicated QA Keychain service, then run the finite verifier above. The exact external dependency is issuance/availability of that OAuth client pair and QA entitlement. An [optional unsent request](novig-access-request.md) is prepared; no message was sent and outreach is not the project's universal next step. Independent Slice 6 normalization can be authorized separately; this work stops before it.
