---
updatedAt: 2026-09-11T15:40:57.000Z
---

Fetch the complete documentation index at: https://docs.prophetx.co/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Direct Linking Integration with the ProphetX Trading API

## Overview

This guide walks a Direct Link aggregator through linking a user's ProphetX account on the client, then placing orders directly from the client using that user's own credentials. The aggregator's backend runs a separate integration, under the aggregator's own ProphetX account, purely to ingest market fixture data and real-time order book updates — it never holds or uses an individual user's key/secret.

**High-level steps:**

1. Link the user's ProphetX account from the client (login + 2FA).
2. Generate the user's ProphetX trading API key/secret and store it on the user's device only.
3. Ingest event/market fixture data server-side, using the aggregator's own ProphetX account.
4. Connect the aggregator's backend to Talaria, ProphetX's in-house WebSocket platform, for real-time order book data, using the aggregator's own account.
5. Run a geolocation check before every order.
6. Submit the order directly from the client using the user's own key/secret; the client also listens on its own Talaria WebSocket channel for that order's status.
7. Certify with ProphetX before going live.

***

## Before you start

* The Trading API is not yet open for public self-serve signup. The aggregator needs its own ProphetX API/market-maker account (separate from any end user's account) to run Steps 3–4, plus an aggregator ID to prefix `external_id` values in Step 6. Contact ProphetX's market-making team to get set up in sandbox and, later, production — they'll assign your aggregator ID as part of that same conversation.
* Two different credential types are in play here and should not be confused: **the aggregator's own access key/secret** (server-side, used only for fixture ingestion and market-wide order book data in Steps 3–4) and **each individual user's access key/secret** (client-side only, generated in Step 2, used only by that user's own client in Step 6).
* Sandbox market-maker endpoints in Steps 3–4 are relative to `https://api.sandbox.prophetx.dev/partner`. Keep the `/partner` path as-is.

***

## Step 1: Link the user's ProphetX account

When the user clicks "Link ProphetX" in the aggregator's app, open a modal asking them to log in with their ProphetX email and password.

```http
POST https://sandbox.prophetx.dev/api/v1/auth/login
```
```json
{ "email": "...", "password": "..." }
```

1. If the response indicates two-factor authentication is required, call the verification-code endpoint to text/email the user a code:

```http
POST https://sandbox.prophetx.dev/api/v1/send-verification-code
```

2. Prompt the user for that code, then call `auth/login` again, this time including the code, to complete the login.

3. A successful login returns an `accessToken`. Hold it in the client only — it is what authorizes Step 2's key-generation call.

> These are the same public endpoints ProphetX's own sandbox web app (`sandbox.prophetx.dev`) calls, not endpoints published in ProphetX's partner API docs. Capture the exact request/response fields (and the 2FA-required response shape) via browser dev tools network inspection against `sandbox.prophetx.dev` before building against them. Once going to production, replace `https://sandbox.prophetx.dev` with `https://www.prophetx.co` as the base URL for all APIs.

***

## Step 2: Generate the user's trading API key/secret

Open a second modal confirming the user wants to generate a ProphetX API key for the aggregator to trade with. On confirmation, call:

```http
POST https://sandbox.prophetx.dev/partner/auth/keys
Authorization: Bearer {accessToken from Step 1}
```

**Response**

```json
{ "access_key": "...", "secret_key": "..." }
```

* Store the returned `access_key` / `secret_key` on the user's device only (e.g. secure local storage or platform keychain). Do not send it to, or persist it on, the aggregator's backend.
* This is a deliberate trade-off: keeping the trading secret off the aggregator's servers limits the aggregator's exposure if its backend is ever compromised, at the cost of the aggregator's backend not being able to place orders or query order status for the user directly (see Step 6).
* This key/secret pair is what Step 6 uses to call `submit_order` and to open the user's own private WebSocket channel.

> The exact request/response of `partner/auth/keys` can be captured via browser dev tools network inspection against `sandbox.prophetx.dev`. This is the same endpoint used by ProphetX Web and mobile.

***

## Step 3: Ingest event/market fixture data (aggregator backend)

Using the aggregator's own ProphetX account credentials (from "Before you start", not any user's key), pull tournaments, events, and markets so you have the identifiers you'll need later to place an order.

```http
GET /mm/get_tournaments
GET /mm/get_sport_events?tournament_id={id}
GET /mm/get_multiple_markets?event_ids={id1,id2,...}
GET /mm/get_price_ladder
```

Record the following for each market selection you plan to support:

| Field              | Example                              | Needed for                                                                                                                                                            |
| ------------------ | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tournament_id`    | `109`                                | Fetching events, WebSocket topic naming                                                                                                                               |
| `event_id`         | `10073803`                           | Fetching markets                                                                                                                                                      |
| `market type`      | `moneyline` / `total` / `spread`     | Filtering which markets you expose                                                                                                                                    |
| `sub_type`         | `player_total_hits` (optional field) | Needed to subscribe to prop-specific channels in Step 4 — fetch it via the v2/v4 `get_multiple_markets` endpoint version and read it defensively, since it's optional |
| `strike_id`        | `40a32ae7b39684d430cf494be26cbe6b`   | Required on order submission in Step 6                                                                                                                                |
| valid price ladder | from `get_price_ladder`              | Orders must use a price on this ladder                                                                                                                                |

Reference: `docs.prophetx.co/docs/integration` (Step 3: Seed tournaments, events, markets, and prices).

***

## Step 4: Real-time order book via Talaria WebSocket (aggregator backend)

Real-time order book data is delivered over **Talaria**, ProphetX's in-house WebSocket platform. Talaria has a stable wire protocol — consistent event names, double-JSON-encoded frames, and a consistent channel/auth signing scheme — and no cluster/region concept: one Talaria deployment is your entire connection target, and routing is by hostname.

> The event strings on the wire — `pusher:connection_established`, `pusher:subscribe`, `pusher:signin`, `pusher:signin_success`, `pusher_internal:subscription_succeeded`, `pusher:error` — are simply what Talaria's wire protocol calls them. That's the protocol's own naming, not a reference to any other vendor.

ProphetX has moved off a single shared market-data channel to dedicated channels per event and, for props, per market sub-type. Both migration deadlines have already passed as of this writing (player props: July 29, 2026; main markets, which now also include `sup_moneyline` and `moneyline_3_way`: August 12, 2026) — the old shared channel no longer carries `market_selections` at all, so the aggregator's backend needs to be on the new model now, not as a future migration. This channel model is a property of the subscription API itself — it's the same `event`/`event_subtype` subscription types regardless of transport details.

1. **Get connection config.**

```http
GET /websocket/connection-config
```

This response includes `{app_id, key}` plus a host (and likely port) field — Talaria has no `cluster` to select, so there's nothing region-based to configure. **The exact field name for that host is not finalized in any source available as of this writing.** Treat it like an undocumented endpoint: confirm the real shape with ProphetX, then substitute it for the `TALARIA_WS_HOST` / `TALARIA_WS_PORT` placeholders below.

2. **Open the WebSocket connection** to `{scheme}://{host}[:{port}]/app/{key}?protocol=7&...`, using the host/port from step 1:

```
connect(host=TALARIA_WS_HOST, port=TALARIA_WS_PORT, path=f"/app/{APP_KEY}", query="protocol=7", secure=False)
```

That's the entire connection setup — no region/cluster parameter exists to configure. Once connected, capture `socket_id` off the `pusher:connection_established` event: its `data` field is a JSON string containing JSON — decode it twice.

3. **Discover what to subscribe to** — `event_id` (`GET /mm/get_sport_events?tournament_id={id}`) and, for props, `sub_type` per market (`GET /v4/mm/get_multiple_markets?event_ids={ids}` — use the v4 endpoint version; `sub_type` is optional, so read defensively).

4. **Register your subscription** — `POST /v4/mm/websocket` (this replaces the old `POST /v4/mm/pusher` call; path and body shape unchanged) with a declarative, complete subscription set on every call:

```json
{
  "socket_id": "...",
  "service": "pusher",
  "subscriptions": [
    { "type": "event", "ids": ["18756"] },
    { "type": "event_subtype", "ids": ["18756:player_to_record_a_double_double"] }
  ]
}
```

The `"service": "pusher"` field stays literally `"pusher"` — it names the wire protocol being spoken, not a vendor. Subscribing with type `"event"` always gets every current main market for that event — you don't need to track the main/prop split yourself.

5. **Complete the handshake**: send `pusher:signin` using the `authenticated` block from the register response, wait for `pusher:signin_success`, then send `pusher:subscribe` per channel using that channel's own `auth` + `channel_name` from `authorized_channel` (each channel's auth only works for that channel), and wait for `pusher_internal:subscription_succeeded` on each. The signing scheme is a `{key}:{hex-HMAC}` string, computed over `{socket_id}:{channel_name}` for channel auth and `{socket_id}::user::{user_data}` for signin.

6. **Bind and consume** — bind `market_selections` on each authorized channel. Payload shape is unchanged — only the routing changed (per the channel-model note above). Classify incoming messages by the response's `scope` field (`event_id`, and `sub_type` where present), not by channel name or event name.

Re-fetch connection-config at least every 30 minutes and reconnect if it has changed; treat a dropped socket as a signal to reconnect, get a fresh `socket_id`, and re-register (reconnecting also resets your channel usage). Always read `channel_limit` from the register response rather than hardcoding it — it's account-configured, counts the cumulative union of channels you've registered on that socket, and going over it rejects the entire request with HTTP 400 `exceed_subscription_count`. Subscribe selectively (e.g. not every event's full prop set) rather than assuming headroom.

> **What's confirmed vs. not:** the wire protocol, event names, double-JSON encoding, the subscribe/signin auth scheme, and all channel/event naming are confirmed. What's **not** confirmed is the production hostname/port/TLS scheme you'll actually connect to, and the precise field name `connection-config` returns for it. Get both from ProphetX before touching your connection code.

> This design avoids the earlier concern about needing one live connection per linked user: the aggregator's backend keeps a single connection for shared market data, and each user's own order-status updates are handled by their own client in Step 6 instead. One relevant detail: this same registration flow also auto-authorizes a private per-account channel (`private-service=6-device_type=5-user={account_id}`, carrying an `orders` event) — for the aggregator's backend that only reflects the aggregator's own account's activity, not any individual user's, which is consistent with Step 6's design. The residual question is whether the aggregator's backend needs any visibility into individual users' orders (e.g. for its own history/analytics) — see [Open items](#open-items).

Reference: `docs.prophetx.co/docs/integrate-with-websockets` (confirm the connection host/port with ProphetX before relying on it); `docs.prophetx.co/docs/websocket-events`.

***

## Step 5: Geolocation check (before every order)

Before letting a user submit an order, call ProphetX's IP-based geolocation check and only proceed if it returns success.

**Sandbox:** `https://sandbox.prophetx.dev/ip-geolocation/api/v1/check-ip`

* Call this with the user's current IP address for the order attempt.
* Proceed to Step 6 only if the response's `success` field is `true`.
* If it's not `true`, block the order and give the user a way to retry (e.g. refresh location, try again).

> The exact request/response of `ip-geolocation/api/v1/check-ip` can be captured via browser dev tools network inspection against `sandbox.prophetx.dev`. This is the same endpoint used by ProphetX Web and mobile.

***

## Step 6: Submit the order from the client

Once the geolocation check in Step 5 passes, the client — not the aggregator's backend — submits the order directly to ProphetX, using the user's own key/secret from Step 2.

```http
POST v4/submit_order
```
```json
{
  "external_id": "<aggregator id>_<client-generated uuid>",
  "strike_id": "<from Step 3>",
  "price": -122,
  "quantity": 1.0,
  "fill_or_kill": true
}
```

See `partner-docs.sandbox.prophetx.dev/swagger/mm/index.html` for the full request schema.

`external_id` must be prepended by your aggregator ID and must be unique per order (e.g. `{aggregator_id}_{client_generated_uuid}`) — reusing one on a retry gets it rejected, which is what prevents duplicate submission. Direct Link aggregators will typically only submit limit orders; pair with `fill_or_kill` when the order shouldn't rest on the book if it doesn't fill immediately.

To show the user their own order status in real time, the client runs the same connect-and-register flow as Step 4 (Sections 2–5 of the WebSocket doc), authenticated with that user's own key/secret. It doesn't need to request any event/event\_subtype subscriptions for this — the register response automatically includes a private per-account channel (`private-service=6-device_type=5-user={user's account_id}`) carrying an `orders` event; bind that on the client to get the user's own order/trade updates.

* Because the user's key/secret never reaches the aggregator's backend, the aggregator's backend has no direct visibility into individual order submissions, fills, or cancellations unless the client separately reports them back to the aggregator — flag this as an open item if the aggregator needs server-side order history or analytics.
* Cancellation follows the same client-side pattern: `POST .../cancel_order` with the `external_id` and the `order_id` returned at submission.

***

## Step 7: Certify and go live

Once Steps 1–6 are working end-to-end in sandbox, go through ProphetX's production transition / certification process before pointing your integration at production hosts. ProphetX will confirm certification is complete before you switch over — do not flip any base URL until you have that confirmation.

***

## Open items

| Topic                                      | Status                                                                                                                                                                                                                                                                            |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Trading API general availability           | Not yet public — requires ProphetX to approve the aggregator's own API/market-maker account for Steps 3–4.                                                                                                                                                                        |
| Login / 2FA endpoint schema                | `auth/login` and `send-verification-code` are undocumented public endpoints used by ProphetX's sandbox web app. Capture the exact schema via browser network inspection against `sandbox.prophetx.dev`.                                                                           |
| `partner/auth/keys` schema                 | Capture the exact request/response via browser network inspection against `sandbox.prophetx.dev` — same endpoint used by ProphetX Web and mobile.                                                                                                                                 |
| `check-ip` full schema                     | Capture the exact request/response via browser network inspection against `sandbox.prophetx.dev` — same endpoint used by ProphetX Web and mobile.                                                                                                                                 |
| Talaria `connection-config` response shape | Not finalized in any source available as of this writing — the register/connection-config endpoint is owned by a separate façade service, and the field replacing (or joining) `cluster` isn't settled yet. Confirm the real shape with ProphetX before changing connection code. |
| Talaria production hostname/port/TLS       | Deployment/ingress-specific; not published anywhere available here. Get this directly from ProphetX.                                                                                                                                                                              |
| Client-side key storage risk               | The user's trading secret now lives on-device rather than server-side. Run a security review of local storage/keychain handling on each client platform the aggregator supports.                                                                                                  |
| Backend visibility into user orders        | The aggregator's backend won't see individual submissions/fills unless the client reports them back. Decide if that reporting path is needed for the aggregator's own order history or analytics.                                                                                 |
| Certification timeline                     | To be scheduled with ProphetX once sandbox testing is complete.                                                                                                                                                                                                                   |

***

## References

* Trading API integration guide (fixture ingestion & WebSocket, aggregator's own account): `docs.prophetx.co/docs/integration`
* WebSocket integration: `docs.prophetx.co/docs/integrate-with-websockets`
* Order submission / market-maker API (swagger): `partner-docs.sandbox.prophetx.dev/swagger/mm/index.html`
* Production transition / going live: `docs.prophetx.co/docs/prophetx-service-api-switch-to-production`