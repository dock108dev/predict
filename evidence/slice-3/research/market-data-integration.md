---
updatedAt: 2026-09-10T19:33:46.000Z
---

Fetch the complete documentation index at: https://docs.prophetx.co/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Market Data Integration

Retrieve tournaments, sport events, markets, prices, and available quantities for a market-data or price-display application.

Retrieve tournaments, sport events, and live markets from ProphetX for your market-data or price-display application.

The Market Data API is read-only and uses JSON over HTTPS. Use it to retrieve the tournaments, events, markets, prices, and available quantities you need for your application.

***

## Table of contents

1. [What you'll be working with](#1-what-youll-be-working-with)
2. [Environments](#2-environments)
3. [Authentication](#3-authentication)
4. [Endpoints](#4-endpoints)
   * [Tournaments](#41-list-tournaments)
   * [Sport events](#42-list-sport-events)
   * [Markets for one event](#43-get-markets-for-an-event)
   * [Markets for many events](#44-get-markets-for-multiple-events)
5. [Response data reference](#5-response-data-reference)
6. [Errors](#6-errors)
7. [A full walkthrough](#7-a-full-walkthrough)
8. [Quick reference card](#8-quick-reference-card)

***

## 1. What you'll be working with

Four endpoints, all returning JSON wrapped in a `{"data": …}` envelope:

| What you want               | Endpoint                                    | Method |
| --------------------------- | ------------------------------------------- | ------ |
| Browse tournaments          | `/affiliate/get_tournaments`                | `GET`  |
| Browse sport events         | `/affiliate/get_sport_events`               | `GET`  |
| Get markets for one event   | `/{version}/affiliate/get_markets`          | `GET`  |
| Get markets for many events | `/{version}/affiliate/get_multiple_markets` | `GET`  |

The typical flow is **tournaments → events → markets**: pick a tournament, list its events, then pull live markets and prices for the events you care about.

***

## 2. Environments

We run two environments. Start in sandbox while you're integrating, then flip to production when you're ready to go live.

| Environment    | Base URL                                   | Use it for                                                |
| -------------- | ------------------------------------------ | --------------------------------------------------------- |
| **Sandbox**    | `https://api.sandbox.prophetx.dev/partner` | Development and testing. Same API surface, isolated data. |
| **Production** | `https://cash.api.prophetx.co/partner`     | Live odds and real data.                                  |

Every endpoint path below is relative to the base URL.

***

## 3. Authentication

Contact our Market Data team at <jordan.grzeczka@prophetexchange.com> to be issued an affiliate API key.

You'll get a single API key. Send it as the `Authorization` header on every request. **No** `Bearer ` **prefix** — just the raw key.

```http
GET /affiliate/get_tournaments HTTP/1.1
Host: api.sandbox.prophetx.dev
Authorization: your-affiliate-api-key
Accept: application/json
```

***

## 4. Endpoints

### 4.1 List tournaments

`GET /affiliate/get_tournaments`

Returns all tournaments available on the platform.

**Query parameters**

| Param               | Type | Required | What it does                                                                                                          |
| ------------------- | ---- | -------- | --------------------------------------------------------------------------------------------------------------------- |
| `has_active_events` | bool | no       | When `true`, only return tournaments that currently have active sport events. Skip it (or `false`) to see everything. |

**Example**

```bash
curl -H "Authorization: $API_KEY" \
     "https://api.sandbox.prophetx.dev/partner/affiliate/get_tournaments?has_active_events=true"
```

**Response**

```json
{
  "data": {
    "tournaments": [
      {
        "id": 123,
        "name": "NFL — Regular Season",
        "sport": { "id": 1, "name": "Football" },
        "category": { "id": 10, "name": "USA", "countryCode": "US" },
        "updated_at": 1735689600000000000
      }
    ]
  }
}
```

***

### 4.2 List sport events

`GET /affiliate/get_sport_events`

Returns sport events. Filter by tournament or by a specific list of event IDs — or pass no filter to get everything.

**Query parameters**

| Param           | Type   | Required | What it does                                                                                    |
| --------------- | ------ | -------- | ----------------------------------------------------------------------------------------------- |
| `tournament_id` | int    | no       | Only events belonging to this tournament.                                                       |
| `event_ids`     | int\[] | no       | Only the specific events you ask for. Repeat the parameter, e.g. `event_ids=101&event_ids=102`. |

**Example**

```bash
curl -H "Authorization: $API_KEY" \
     "https://api.sandbox.prophetx.dev/partner/affiliate/get_sport_events?tournament_id=123"
```

**Response**

```json
{
  "data": {
    "sport_events": [
      {
        "event_id": 101,
        "tournament_id": 123,
        "tournament_name": "NFL — Regular Season",
        "name": "Patriots vs. Jets",
        "sport_name": "Football",
        "scheduled": "2026-06-01T17:00:00Z",
        "status": "scheduled",
        "competitors": [
          { "id": 11, "name": "Patriots", "side": "home" },
          { "id": 20, "name": "Jets", "side": "away" }
        ]
      }
    ]
  }
}
```

`scheduled` is ISO 8601 in UTC.

***

### 4.3 Get markets for an event

`GET /{version}/affiliate/get_markets`

Returns all markets for a single event, including moneylines, spreads, totals, and available selections with current prices and quantities.

**API versions**

The path is version-prefixed. Use **v4** unless you have a reason not to — it returns CFTC-compliant field names (`price`, `strike`, `strike_id`, `quantity`).

| Version | Path                        | Status                       |
| ------- | --------------------------- | ---------------------------- |
| `v1`    | `/affiliate/get_markets`    | Deprecated — please migrate. |
| `v2`    | `/v2/affiliate/get_markets` | Stable.                      |
| `v3`    | `/v3/affiliate/get_markets` | Stable.                      |
| `v4`    | `/v4/affiliate/get_markets` | **Latest — recommended.**    |

**Query parameters**

| Param           | Type   | Required | What it does                                                                                            |
| --------------- | ------ | -------- | ------------------------------------------------------------------------------------------------------- |
| `event_id`      | int    | **yes**  | The event to fetch markets for.                                                                         |
| `market_types`  | string | no       | Comma-separated allowlist, e.g. `moneyline,spread,total`. Only markets of these types are returned.     |
| `min_liquidity` | float  | no       | Only return markets at or above this liquidity threshold. Useful for filtering out thinly-priced lines. |

**Example**

```bash
curl -H "Authorization: $API_KEY" \
     "https://api.sandbox.prophetx.dev/partner/v4/affiliate/get_markets?event_id=101&market_types=moneyline,spread&min_liquidity=100"
```

**Response (v4)**

```json
{
  "data": [
    {
      "id": 555,
      "name": "Moneyline",
      "display_name": "Moneyline",
      "type": "moneyline",
      "category_name": "Game Lines",
      "sub_type": "moneyline",
      "selections": [
        [
          { "outcome_id": 1, "name": "Patriots", "price": 1.95, "strike": null, "strike_id": "line_1", "quantity": 2100.0 }
        ],
        [
          { "outcome_id": 2, "name": "Jets", "price": 1.95, "strike": null, "strike_id": "line_2", "quantity": 2150.0 }
        ]
      ]
    }
  ]
}
```

> **Note on** `selections`**:** In **v3** and **v4**, each entry inside `selections` is itself a list (selections grouped by side/team). In **v1** and **v2**, `selections` is a flat array of objects. This shape difference is independent of the field-naming difference below.

`price` uses the API's decimal price format. `strike` is the point spread or total (`null` on moneyline markets). Preserve the literal `strike_id` field when you use it in API requests or responses.

***

### 4.4 Get markets for multiple events

`GET /{version}/affiliate/get_multiple_markets`

Same data as `get_markets`, but batched across many events in a single call. Great for refreshing prices on a list of upcoming games.

**API versions** — same scheme as `get_markets`:

| Version | Path                                 |
| ------- | ------------------------------------ |
| `v1`    | `/affiliate/get_multiple_markets`    |
| `v2`    | `/v2/affiliate/get_multiple_markets` |
| `v3`    | `/v3/affiliate/get_multiple_markets` |
| `v4`    | `/v4/affiliate/get_multiple_markets` |

**Query parameters**

| Param       | Type   | Required | What it does                                                   |
| ----------- | ------ | -------- | -------------------------------------------------------------- |
| `event_ids` | int\[] | **yes**  | Events to fetch markets for. Repeat the parameter for each ID. |

**Example**

```bash
curl -H "Authorization: $API_KEY" \
     "https://api.sandbox.prophetx.dev/partner/v4/affiliate/get_multiple_markets?event_ids=101&event_ids=102&event_ids=103"
```

**Response — typical shape**

```json
{
  "data": {
    "101": [ { /* market */ }, { /* market */ } ],
    "102": [ { /* market */ } ],
    "103": []
  }
}
```

Each market object has the same fields as in [§4.3](#43-get-markets-for-an-event).

> **Heads up:** A small number of responses may come back as a flat list of markets rather than a keyed object. If you're parsing defensively, check the type and, in the flat-list case, group by each market's `event_id` field.

***

## 5. Response data reference

A complete field-by-field reference for everything you'll receive.

### Tournament

| Field        | Type              | Description                                          |
| ------------ | ----------------- | ---------------------------------------------------- |
| `id`         | int               | Tournament ID. Use this to filter events.            |
| `name`       | string            | Display name, e.g. `"NFL — Regular Season"`.         |
| `sport`      | object \| null    | The sport, as `{ id, name }`.                        |
| `category`   | object \| null    | The category/region, as `{ id, name, countryCode }`. |
| `updated_at` | int (nanoseconds) | Last-updated timestamp.                              |

### Sport event

| Field             | Type           | Description                                                                                                        |
| ----------------- | -------------- | ------------------------------------------------------------------------------------------------------------------ |
| `event_id`        | int            | Event ID. Use this with the markets endpoints.                                                                     |
| `tournament_id`   | int \| null    | Parent tournament.                                                                                                 |
| `tournament_name` | string \| null | Parent tournament's display name.                                                                                  |
| `name`            | string \| null | Display name.                                                                                                      |
| `sport_name`      | string \| null | The sport's display name.                                                                                          |
| `scheduled`       | string \| null | ISO 8601 UTC scheduled start time.                                                                                 |
| `status`          | string \| null | Lifecycle status, e.g. `"scheduled"`, `"live"`, `"finished"`.                                                      |
| `competitors`     | array          | Each entry has `id`, `name`, `side` (`"home"`/`"away"`), and optionally `display_name`, `abbreviation`, `country`. |

### Market

| Field           | Type           | Description                                                      |
| --------------- | -------------- | ---------------------------------------------------------------- |
| `id`            | int            | Market ID.                                                       |
| `name`          | string         | Market name.                                                     |
| `display_name`  | string \| null | Display name, if different from `name`.                          |
| `type`          | string \| null | e.g. `"moneyline"`, `"spread"`, `"total"`, `"sup_moneyline"`.    |
| `category_name` | string \| null | The market's category, e.g. `"Game Lines"`.                      |
| `sub_type`      | string \| null | The market's sub-type.                                           |
| `strike`        | float \| null  | Market-level point spread or total, if applicable.               |
| `selections`    | array          | Available outcomes. See note in §4.3 about v1/v2 vs v3/v4 shape. |

### Selection

| Field           | Type           | Description                                       |
| --------------- | -------------- | ------------------------------------------------- |
| `outcome_id`    | int \| null    | Selection outcome ID.                             |
| `name`          | string \| null | Display label, e.g. `"Patriots"`, `"Over"`.       |
| `competitor_id` | int \| null    | The competitor this selection belongs to, if any. |
| `strike`        | float \| null  | Point spread or total. `null` for moneyline.      |
| `strike_id`     | string \| null | API identifier for the line.                      |
| `price`         | float \| null  | **Decimal price.**                                |
| `quantity`      | float \| null  | Available quantity for this specific selection.   |

***

## 6. Errors

The API uses standard HTTP status codes. Error bodies are JSON when available.

| Status | What it means                                           | What to do                                                              |
| ------ | ------------------------------------------------------- | ----------------------------------------------------------------------- |
| `200`  | Success.                                                | —                                                                       |
| `400`  | Bad request — usually a malformed or missing parameter. | Check your query string.                                                |
| `401`  | Unauthorized — bad key or missing header.               | Verify your `Authorization` header.                                     |
| `404`  | The resource (e.g. an `event_id`) doesn't exist.        | Double-check the ID.                                                    |
| `429`  | Rate-limited.                                           | Back off and retry with exponential delay.                              |
| `5xx`  | Server-side issue.                                      | Retry with backoff. If it persists, reach out to your ProphetX contact. |

***

## 7. A full walkthrough

The typical "fetch live prices for a slate of games" flow, in three calls:

```
  ┌───────────────────────┐    1. List active tournaments
  │   get_tournaments     │       → pick the ones you care about
  └──────────┬────────────┘
             │
             ▼
  ┌───────────────────────┐    2. List events in those tournaments
  │   get_sport_events    │       → collect event_ids
  └──────────┬────────────┘
             │
             ▼
  ┌───────────────────────┐    3. Batch-fetch live markets & prices
  │ get_multiple_markets  │       → render prices in your product
  └───────────────────────┘
```

**Step 1 — active tournaments:**

```bash
curl -H "Authorization: $API_KEY" \
     "https://api.sandbox.prophetx.dev/partner/affiliate/get_tournaments?has_active_events=true"
```

**Step 2 — events for the tournament(s) you picked:**

```bash
curl -H "Authorization: $API_KEY" \
     "https://api.sandbox.prophetx.dev/partner/affiliate/get_sport_events?tournament_id=123"
```

**Step 3 — markets for a batch of events:**

```bash
curl -H "Authorization: $API_KEY" \
     "https://api.sandbox.prophetx.dev/partner/v4/affiliate/get_multiple_markets?event_ids=101&event_ids=102&event_ids=103"
```

For high-frequency price refreshes, re-run step 3 on whatever cadence your product needs — and keep an eye on rate limits.

***

## 8. Quick reference card

```
Base URL (sandbox)     : https://api.sandbox.prophetx.dev/partner
Base URL (production)  : https://cash.api.prophetx.co/partner
Auth header            : Authorization: <api-key>     (no "Bearer " prefix)

GET  /affiliate/get_tournaments                   [?has_active_events]
GET  /affiliate/get_sport_events                  [?tournament_id] [?event_ids]
GET  /{v1|v2|v3|v4}/affiliate/get_markets            ?event_id [&market_types] [&min_liquidity]
GET  /{v1|v2|v3|v4}/affiliate/get_multiple_markets   ?event_ids
```

***

Need access, a higher rate limit, or a feature that isn't covered here? Get in touch with your ProphetX contact — we're happy to help you ship.