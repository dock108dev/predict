---
updatedAt: 2026-08-26T15:53:33.000Z
---

Fetch the complete documentation index at: https://docs.prophetx.co/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# WebSocket Events

Understand Trading API WebSocket payloads, event and sub-markets channel routing, and `scope`-based classification.

Use this page to interpret Trading API WebSocket payloads under the new event and sub-markets channel model. For the complete connection, subscription-registration, capacity-planning, and Pusher-handshake flow, see [Integration with Websockets](/docs/integrate-with-websockets).

## Migration to event and sub-markets channels

Register subscriptions with `POST /partner/v4/mm/websocket`. This replaces `POST /partner/v4/mm/pusher` for access to the new channel types.

| Market coverage | Required action                                                | Deadline            |
| --------------- | -------------------------------------------------------------- | ------------------- |
| Player Props    | Subscribe to the new Sub-markets channels.                     | **July 29, 2026**   |
| Main markets    | Migrate from the shared main public channel to Event channels. | **August 12, 2026** |

## Channel routing and scope

| Channel              | Pattern                                                                         | Payloads                                                                         |
| -------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Main public channel  | `private-broadcast-service=6-device_type=5`                                     | Existing shared messages. Its `market_selections` payloads are being phased out. |
| Event channel        | `private-broadcast-service=6-device_type=5-event={event_id}`                    | Main-market `market_selections` for one event.                                   |
| Sub-markets channel  | `private-broadcast-service=6-device_type=5-event={event_id}-subtype={sub_type}` | Prop `market_selections` for one event and sub-type.                             |
| Private user channel | `private-service=6-device_type=5-user=<your_account_id>`                        | Participant-specific order and account updates.                                  |

Event and Sub-markets channels both publish `market_selections`. Use the `scope` returned in each `authorized_channel` entry to classify incoming messages, not the channel name. Event-channel scope contains `event_id`; Sub-markets-channel scope contains `event_id` and `sub_type`.

## WebSocket event message structure

```json
{
  "timestamp": int64,
  "change_type": string,
  "payload": base64 encoded string,
  "op": string
}
```

The `payload` value varies by `change_type`, as detailed below.

The available `op` values are:

* `c` stands for create
* `u` stands for update
* `d` stands for delete

## Broadcast payloads

The following payload types are published on broadcast channels. During the migration, `market_selections` moves from the shared main public channel to Event and Sub-markets channels; its payload schema does not change.

The broadcast payload reference includes six event types:

* **tournament**<br />Sent when a new tournament becomes available, an existing tournament is disabled, or tournament data is updated.<br />Payload structure:
  ```json
  {
    "id": string, // unique tournament identifier
    "info": {
      "banner": string,
      "category": {
        "countryCode": string,
        "id": integer,
        "name": string
      },
      "id": integer, // tournament id
      "image": string,
      "name": string,
      "sport": {
        "id": integer,
        "name": string
      },
      "sequence_number": int
    }
  }
  ```

* **market**<br />Sent when a new market becomes available for an event, a market is removed from an event, or market data is updated.<br />Payload structure:
  ```json
  {
    "id": string, // unique event identifier
    "info": {
      "id": int, // market id
      "sport_event_id": int, // event id, same as outer id
      "name": string,
      "status": string,
      "description": string,
      "sequence_number": int
    }
  }
  ```

* **sport\_event**<br />Sent when a new event becomes available in a tournament, an existing event is removed, or event data is updated.<br />Payload structure:
  ```json
  {
    "id": string, // unique event identifier
    "tournament_id": string,
    "info": {
      "competitors": [
        {
          "abbreviation": string,
          "country": string,
          "display_name": string,
          "id": integer, // competitor id
          "name": string,
          "side": string
        }
      ],
      "display_name": string,
      "event_id": integer,
      "name": string,
      "scheduled": string,
      "sport_name": string,
      "status": string,
      "tournament_name": string,
      "type": string,
      "sequence_number": int
    }
  }
  ```

* **market\_strike**<br />Sent when a market has a new strike, an existing strike is removed, or strike data is updated.<br />Payload structure:
  ```json
  {
    "id": int, // market_strike id
    "info": {
      "id": int,
      "sport_event_id": int,
      "market_id": int,
      "outcome_id": int,
      "strike": float,
      "strike_id": string,
      "type": string,
      "name": string,
      "status": string,
      "favourite": bool,
      "sequence_number": int
    }
  }
  ```

* **market\_selections**<br />Sent for all selections on a strike when selection liquidity changes, such as new resting orders, filled orders, voided orders, or canceled orders. Liquidity is calculated from resting quantity on a strike. Event and Sub-markets channels both publish this event name; classify the message using the channel's `scope`.<br />Payload structure:
  ```json
  {
    "sport_event_id": int,
    "market_id": int,
    "info": {
      "id": int,
      "name": string, // market name
      "selections": [
        // Contains two arrays of best selections
        // The current system limits each array to the 10 best selections for this event
        // If no best selection exists, the system returns one placeholder selection
        [
          {
            "outcome_id": int,
            "name": string,
            "competitor_id": int,
            "strike": float,
            "strike_id": string,
            "price": float,
            "display_price": string,
            "display_strike": string,
            "display_name": string,
            "value": float,
            "quantity": float,
            "updated_at": int
          }
        ],
        [
          {
            "outcome_id": int,
            "name": string,
            "competitor_id": int,
            "strike": float,
            "strike_id": string,
            "price": float,
            "display_price": string,
            "display_strike": string,
            "display_name": string,
            "value": float,
            "quantity": float,
            "updated_at": int
          }
        ]
      ],
      "type": string,
      "strike": float,
      "sequence_number": int
    }
  }
  ```

* **matched\_order**<br />Sent when a successful fill occurs. This event broadcasts the filled price details to all listeners.<br />Payload example:
  ```json
  {
    "info": {
      "strike": 0,
      "strike_id": "cffa7ddc4fd50acbe51684e7addabe00",
      "market_id": 219,
      "fill_price": 124,
      "filled_quantity": 45.3,
      "price": 124,
      "origin_market_strike": 0,
      "outcome_id": 4,
      "sequence_number": 1709130007835319000,
      "sport_event_id": 44285780
    }
  }
  ```

## Private user channel

Messages sent through this channel are available only to your participant session.

The private channel publishes two event types:

* **order**<br />Sent when your order status changes. You receive updates when an order is activated, canceled, or filled, including updated order metadata.<br />Payload structure:
  ```json
  {
    "info": {
      "order_id": string,
      "user_id": string,
      "market_id": int,
      "sport_event_id": int,
      "outcome_id": int,
      "price": float,
      "strike": float,
      "quantity": float,
      "profit": float,
      "filled_quantity": float,
      "fill_price": float,
      "total_filled_quantity": float,
      "open_quantity": float,
      "matching_status": string,
      "winning_status": string,
      "status": string,
      "external_id": string,
      "strike_id": string,
      "update_type": string,
      "sequence_number": int
    }
  }
  ```

* **health\_check**<br />Sent to all WebSocket sessions every 5 seconds to help you monitor connection health.<br />Payload example:
  ```json
  {
    "event": "health_check",
    "data": {
      "change_type": "private_system_signal",
      "op": "u",
      "payload": "e30=",
      "timestamp": 1717689526365275600
    }
  }
  ```