---
updatedAt: 2026-07-21T17:01:18.000Z
---

Fetch the complete documentation index at: https://docs.prophetx.co/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Various Websocket Use Cases

Use Trading API WebSocket patterns to confirm order status, build market order books, monitor fills, and manage risk in real time.

Use these WebSocket patterns to confirm order status, monitor market updates, and manage risk in real time.

## Order activation confirmation

Orders on ProphetX rely on FIFO queues for activation. After you submit an order through the REST API, record its `order_id`. You will receive a private-channel update indicating whether the order was activated successfully or failed. The most common failure reason is insufficient cash balance.

## Safety protection

If you do not receive an order activation message within 10 seconds of submission, the cause may be a WebSocket disconnection or a lost message. Reconnect the WebSocket and call `GET /mm/get_order/{id}` to retrieve the current order status.

## Order cancellation confirmation

After you cancel an order through `POST /mm/cancel_order`, or cancel multiple orders through `POST /mm/cancel_multiple_orders`, a successful response returns `200`. The canceled orders can no longer be filled. A private-channel update identifies the orders that were canceled. Attempting to cancel an order that is already canceled returns `400`.

## Build the order book in real time

To build the order book for a market and track fill activity, subscribe to `market_selections` on the broadcast channel. Call `GET /mm/get_markets` or `GET /mm/get_multiple_markets` every 15 minutes and compare the response with your WebSocket-built order book. This helps prevent inaccuracies caused by missed WebSocket messages.

Subscribe to `matched_order` on the same broadcast channel to receive real-time fill details. When market liquidity changes because an order is filled, a `matched_order` message includes the fill price and filled quantity.

## Risk control in real time

Fill updates for your orders are pushed to you through a private channel. These messages include details such as `order_id`, `filled_quantity`, and `fill_price`. Use this information to rebalance your book and minimize exposure in real time.

## Ensure WebSocket connectivity

A disconnect event is typically sent when the WebSocket connection is lost. To reduce false positives, you can also listen to the public `health_check` message, which is broadcast every 5 seconds. If you rely on this message, disconnect and reconnect the WebSocket if no `health_check` message is received for more than 30 seconds.