> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Market Lifecycle Channel

> Subscribe to market lifecycle events

### Channel Name

**Channel:** `lifecycle` (Global channel for all markets)

### Subscription

```javascript theme={null}
ws.send(
    JSON.stringify({
        event: "subscribe",
        data: "lifecycle",
    }),
)
```

### Event Types

| Type           | Description                                                                                                 |
| -------------- | ----------------------------------------------------------------------------------------------------------- |
| `OPEN`         | Market has opened and is accepting orders                                                                   |
| `START`        | The underlying event/game has started                                                                       |
| `END`          | The underlying event/game has ended                                                                         |
| `CLOSE`        | Market has closed and is no longer accepting orders                                                         |
| `EVENT_GOLIVE` | The underlying event went live (`OPEN_INGAME`). Every order resting across the event's markets is cancelled |
| `EVENT_UNLIVE` | The underlying event is no longer live. Nothing is cancelled                                                |

<Warning>
  **Critical:** When a market closes (indicated by a `CLOSE` event), all outstanding orders on that market are **implicitly cancelled**. No individual cancellation messages will be sent for these orders.

  You must use lifecycle events to manage order state for any open orders in the given market.
</Warning>

### Event Liveness: `EVENT_GOLIVE` and `EVENT_UNLIVE`

`EVENT_GOLIVE` and `EVENT_UNLIVE` are the two edges of a single boolean: whether the event's status is `OPEN_INGAME`. They are **event-level**, so you receive **one tick per open market in the event** — the `market` payload tells you which markets are affected, and every tick in the burst carries the same `eventId`.

**Why this matters: fees follow liveness.** Taker fees are charged only on fills matched while the event is live (`OPEN_INGAME`). Non-live fills are not charged, and makers are never charged a fee — they may instead earn a [Maker Credit](/maker-credit-program). Liveness is resolved at match time from the same event status these ticks announce, so the lifecycle channel is your fee-relevant signal for whether a fill you are about to take will be charged. See [Trading Fees](/fees) for the fee formula itself.

|                                | `EVENT_GOLIVE`                               | `EVENT_UNLIVE`                          |
| ------------------------------ | -------------------------------------------- | --------------------------------------- |
| Event status                   | `OPEN_INGAME`                                | anything else (`DELAYED`, `FINAL`, ...) |
| Resting orders                 | **all cancelled** across the event's markets | untouched                               |
| Market status                  | stays `OPEN` — markets keep accepting orders | stays as-is                             |
| Taker fees on subsequent fills | charged                                      | not charged                             |

On `EVENT_GOLIVE`, the drain is announced before it is itemized: the `EVENT_GOLIVE` tick(s) arrive **first**, followed by an individual `CANCEL` tick per drained order on the `tape` and market channels, and on your `private` channel for your own orders. Markets are **not** closed by going live — you can immediately re-quote at live prices.

<Warning>
  **These edges repeat. `EVENT_GOLIVE` is not a one-time flag.** A game that is delayed or suspended mid-play transitions `OPEN_INGAME → DELAYED → OPEN_INGAME`, which emits `EVENT_GOLIVE`, then `EVENT_UNLIVE`, then `EVENT_GOLIVE` again — and **each** `EVENT_GOLIVE` drains every order resting on that event's markets, including orders you placed during the delay.

  Treat these ticks as edge-triggered and idempotent: keep a per-event live flag, set it on `EVENT_GOLIVE`, clear it on `EVENT_UNLIVE`, and never assume the first `EVENT_GOLIVE` is terminal. Halftime does not un-live a game; a weather or injury suspension does.
</Warning>

<Note>
  Derive liveness from the tick's `type`, not from `market.event.status`. The `event` join is a snapshot taken when the market entered the book — it may be absent from tick payloads entirely, and when present its `status` is not guaranteed to reflect the transition the tick is announcing. For an authoritative status snapshot, use the REST endpoints below.

  If an event has no open markets left (for example every market has already settled), the terminal `EVENT_UNLIVE` has no market to name and no tick is sent.
</Note>

Example burst for an event with two open markets going live:

```json theme={null}
{ "type": "EVENT_GOLIVE", "market": { "id": "market-a", "eventId": "event-1", "status": "OPEN", "...": "..." } }
{ "type": "EVENT_GOLIVE", "market": { "id": "market-b", "eventId": "event-1", "status": "OPEN", "...": "..." } }
{ "type": "CANCEL", "order": { "id": "order-1", "marketId": "market-a", "...": "..." }, "...": "..." }
```

And the mirror edge when that event is suspended:

```json theme={null}
{ "type": "EVENT_UNLIVE", "market": { "id": "market-a", "eventId": "event-1", "status": "OPEN", "...": "..." } }
{ "type": "EVENT_UNLIVE", "market": { "id": "market-b", "eventId": "event-1", "status": "OPEN", "...": "..." } }
```

### Reading Event Status over REST

The WebSocket gives you the transitions; REST gives you the snapshot. Use REST to bootstrap liveness on connect and after any reconnect (you cannot see edges that fired while you were disconnected), then let the lifecycle channel carry you forward.

**One event by id** — read `status` directly:

```bash theme={null}
curl -X GET "https://api.novig.com/nbx/v2/emm/events/550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer $TOKEN"
```

```json theme={null}
{
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "type": "Game",
    "status": "OPEN_INGAME",
    "description": "Kansas City Chiefs @ Buffalo Bills",
    "league": "NFL",
    "scheduledStart": "2026-01-26T18:30:00.000Z",
    "marketIds": ["market-a", "market-b"]
}
```

`status == "OPEN_INGAME"` is exactly the condition under which taker fees are charged. Any other value — `OPEN_PREGAME`, `CLOSED_PREGAME`, `DELAYED`, `FINAL`, `CANCELED` — is non-live and uncharged.

**Every live event** — filter server-side, and use it as your startup snapshot:

```bash theme={null}
curl -X GET "https://api.novig.com/nbx/v2/emm/events?status=OPEN_INGAME&league=NFL&limit=100" \
  -H "Authorization: Bearer $TOKEN"
```

A minimal reconciliation pattern:

```javascript theme={null}
const live = new Set()

// 1. Bootstrap from REST on connect / reconnect.
const events = await fetch("https://api.novig.com/nbx/v2/emm/events?status=OPEN_INGAME&limit=100", {
    headers: { Authorization: `Bearer ${token}` },
}).then((r) => r.json())
events.forEach((e) => live.add(e.id))

// 2. Let the lifecycle channel carry the edges from there.
ws.on("message", (raw) => {
    const tick = JSON.parse(raw)
    if (tick.type === "EVENT_GOLIVE") live.add(tick.market.eventId) // resting orders on this event are now gone
    if (tick.type === "EVENT_UNLIVE") live.delete(tick.market.eventId)
})

const willPayTakerFee = (market) => live.has(market.eventId)
```

Both endpoints are rate limited to 512 requests per second. Poll them only to reconcile — the WebSocket is the low-latency path.

### Message Format

Lifecycle ticks arrive as **bare payloads** — there is no `{ "event": ..., "data": ... }` envelope on this channel (the envelope is only used for subscription acks, errors, and private events):

```json theme={null}
{
    "type": "OPEN",
    "market": {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "description": "KC v BUF Total",
        "status": "OPEN",
        "strike": 26.5,
        "type": "TOTAL",
        "volume": 1000000,
        "eventId": "123e4567-e89b-12d3-a456-426614174001",
        "outcomeIds": ["outcome-1", "outcome-2"],
        "settledAt": null,
        "event": {
            "id": "123e4567-e89b-12d3-a456-426614174001",
            "description": "KC Chiefs vs BUF Bills - Week 14",
            "type": "REGULAR_SEASON",
            "status": "OPEN_PREGAME",
            "game": {
                "id": "game-001",
                "league": "NFL",
                "status": "SCHEDULED",
                "scheduledStart": "2023-12-10T20:00:00Z",
                "homeTeam": {
                    "id": "team-buf",
                    "name": "Buffalo Bills",
                    "shortName": "Bills",
                    "symbol": "BUF",
                    "mascot": "Bills"
                },
                "awayTeam": {
                    "id": "team-kc",
                    "name": "Kansas City Chiefs",
                    "shortName": "Chiefs",
                    "symbol": "KC",
                    "mascot": "Chiefs"
                }
            }
        }
    }
}
```

### Market Object

The `market` object in lifecycle events contains:

| Field         | Type           | Description                                                                                                                                                                                                  |
| ------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `id`          | string         | UUID of the market                                                                                                                                                                                           |
| `description` | string         | Human-readable market description                                                                                                                                                                            |
| `status`      | string         | Market status (OPEN, CLOSED, SETTLED)                                                                                                                                                                        |
| `strike`      | number         | Market threshold value. **Omitted** for markets with no strike                                                                                                                                               |
| `type`        | string         | Market type (TOTAL, SPREAD, MONEY, etc.)                                                                                                                                                                     |
| `league`      | string         | League the market belongs to                                                                                                                                                                                 |
| `isConsensus` | boolean        | Whether the market is a consensus market                                                                                                                                                                     |
| `volume`      | number         | Total trading volume                                                                                                                                                                                         |
| `eventId`     | string         | Associated event UUID                                                                                                                                                                                        |
| `playerId`    | string         | Associated player UUID. **Omitted** when not applicable                                                                                                                                                      |
| `player`      | object \| null | Player details (if applicable)                                                                                                                                                                               |
| `competitor`  | object \| null | Competitor details (if applicable)                                                                                                                                                                           |
| `outcomeIds`  | string\[]      | Array of outcome UUIDs                                                                                                                                                                                       |
| `outcomes`    | object\[]      | Full outcome objects for the market                                                                                                                                                                          |
| `settledAt`   | string \| null | Settlement timestamp (if settled)                                                                                                                                                                            |
| `event`       | object         | Event details including game and teams. **Omitted** when unavailable; when present, a snapshot from when the market entered the book — do not read liveness from `event.status`, use the tick `type` or REST |
