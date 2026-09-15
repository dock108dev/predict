> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Order Book Channel

> Subscribe to real-time order book updates

## Order Book Channel

Subscribe to public order book updates including order placements and cancellations.

### Channel Names

* **Global tape:** `tape` - Receive updates for all markets
* **Market-specific:** `{marketId}` - Receive updates only for a specific market (UUID)

<Note>
  When subscribing to a **specific market**, you will receive initial `book` messages containing the current order book state.
  When subscribing to the **global tape** (`tape`), you will **not** receive these initial order book state messages—only
  subsequent updates.
</Note>

### Subscription

<CodeGroup>
  ```javascript Global Tape theme={null}
  // Subscribe to all markets
  ws.send(
      JSON.stringify({
          event: "subscribe",
          data: "tape",
      }),
  )
  ```

  ```javascript Specific Market theme={null}
  // Subscribe to a specific market
  ws.send(
      JSON.stringify({
          event: "subscribe",
          data: "123e4567-e89b-12d3-a456-426614174000", // Market ID
      }),
  )
  ```
</CodeGroup>

### Event Types

The order book channel broadcasts two types of events:

* **PLACE** - A new order has been placed or an existing order has been partially filled
* **CANCEL** - An order has been explicitly cancelled

<Note>
  Implicit cancellations (e.g., when a market closes) are **not** broadcast on this channel. Use the [Market Lifecycle
  Channel](/api-reference/WSS/lifecycle-channel) to handle those events.
</Note>

### Message Format

Order book ticks arrive as **bare payloads** — there is no `{ "event": ..., "data": ... }` envelope on tick frames. (The envelope is used only for subscription acks, the initial `book` snapshot, errors, and private events.)

```json theme={null}
{
    "type": "PLACE",
    "order": {
        "id": "order-456",
        "price": 0.667,
        "qty": 110,
        "originalQty": 110,
        "currency": "CASH",
        "marketId": "market-789",
        "outcomeId": "123e4567-e89b-12d3-a456-426614174000",
        "status": "OPEN"
    },
    "fills": [
        {
            "id": "fill-123",
            "orderId": "order-456",
            "price": 0.667,
            "qty": 50,
            "isWash": false,
            "isTaker": true,
            "marketId": "market-789",
            "outcomeId": "123e4567-e89b-12d3-a456-426614174000"
        }
    ],
    "market": {
        "id": "market-789",
        "description": "KC v BUF Total",
        "status": "OPEN",
        "type": "TOTAL",
        "strike": 26.5,
        "volume": 1000000
    }
}
```

### Order Fields

| Field         | Type   | Description                                                                       |
| ------------- | ------ | --------------------------------------------------------------------------------- |
| `id`          | string | UUID of the order                                                                 |
| `price`       | number | The price of the order in decimal probability (0-1, up to 3 decimal places)       |
| `qty`         | number | The remaining quantity in Minimum Currency Units                                  |
| `originalQty` | number | The original quantity when the order was placed                                   |
| `currency`    | string | CASH or COIN                                                                      |
| `marketId`    | string | UUID of the market                                                                |
| `outcomeId`   | string | UUID of the outcome for this order                                                |
| `status`      | string | Current order status                                                              |
| `created_at`  | string | Placement timestamp. **Omitted** when absent — note this one field is snake\_case |

### Fill Fields

| Field       | Type    | Description                                |
| ----------- | ------- | ------------------------------------------ |
| `id`        | string  | UUID of the fill                           |
| `orderId`   | string  | UUID of the order that was filled          |
| `price`     | number  | The execution price in decimal probability |
| `qty`       | number  | The quantity filled                        |
| `isWash`    | boolean | Whether this is a wash trade               |
| `isTaker`   | boolean | Whether this fill was the taker side       |
| `marketId`  | string  | UUID of the market                         |
| `outcomeId` | string  | UUID of the outcome                        |

### Example Implementation

<CodeGroup>
  ```javascript JavaScript/TypeScript theme={null}
  import WebSocket from "ws"

  const ws = new WebSocket("wss://api.novig.com/tape", {
      headers: {
          Authorization: `Bearer ${ACCESS_TOKEN}`,
      },
  })

  ws.on("open", () => {
      // Subscribe to global tape
      ws.send(
          JSON.stringify({
              event: "subscribe",
              data: "tape",
          }),
      )
  })

  ws.on("message", (data) => {
      const message = JSON.parse(data.toString())

      if (message.event) {
          // Enveloped frame: subscription ack, initial book snapshot, error, or private event
          return
      }

      // Bare tick: { type, order, fills, market }
      const { type, order, fills, market } = message

      console.log(`${type} event for market: ${market.description}`)
      console.log(`Order: ${order.qty} @ ${order.price}`)

      if (fills.length > 0) {
          console.log(`Fills: ${fills.length}`)
          fills.forEach((fill) => {
              console.log(`  - ${fill.qty} @ ${fill.price}`)
          })
      }
  })
  ```
</CodeGroup>

### Unsubscribing

To stop receiving updates from a channel:

```javascript theme={null}
ws.send(
    JSON.stringify({
        event: "unsubscribe",
        data: "tape",
    }),
)
```

You'll receive a confirmation:

```json theme={null}
{
    "event": "unsubscribed",
    "data": {
        "channel": "tape"
    }
}
```
