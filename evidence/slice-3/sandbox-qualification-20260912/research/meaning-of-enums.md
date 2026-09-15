---
updatedAt: 2026-09-10T15:58:27.000Z
---

Fetch the complete documentation index at: https://docs.prophetx.co/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Meaning of Enums

Understand the current enum values returned for Trading API orders, markets, and events.

## Summary

Use this page to understand the meaning of enum values returned for orders, markets, and events.

### Order Object

This object is returned by `POST /v4/mm/submit_order`, `POST /v4/mm/submit_multiple_orders`, `GET /v4/mm/get_order_history`, and WebSocket events. It includes four enum fields: `status`, `matching_status`, `winning_status`, and `update_type`.

#### Status

* **inactive**: The order request has been received but is still being validated. It is not yet visible to clients and cannot be filled.
* **open**: The order has passed validation, is visible to clients, and is available to be filled by other users.
* **invalid**: The order failed validation and never became available to users. The most common reason is insufficient cash balance during activation.
* **canceled**: The order was canceled by the client, and no amount was filled. If the order was partially filled, the resting portion is canceled. The `status` remains `open`, and `matching_status` becomes `fully_matched` once only the filled portion remains.
* **void**: The order was explicitly voided by the internal operations team due to regulatory requirements or other reasons.
* **wiped**: The order was automatically wiped when certain events occurred, such as all pre-match orders being wiped once an event transitions from pre-match to live.
* **manually\_settled**: The order was not auto-settled due to data source issues or existing limitations, so it required manual settlement.
* **settled**: An auto-settled profitable order has this status. Once the cash balance is updated, the status transitions to `closed`.
* **closed**: The final status for auto-settled orders. Auto-settled losing orders move directly to `closed`.

#### Order flow examples

1. For a profitable auto-settled order: `inactive` => `open` => `settled` => `closed`
2. For a losing auto-settled order: `inactive` => `open` => `closed`
3. For a manually settled order: `inactive` => `open` => `manually_settled`

#### Fill status

The API field is matching\_status.

* open (unmatched): No part of the order has been filled yet, and the order is still resting.
* partially\_filled (partially\_matched): Part of the order has been filled, and the remaining amount is still resting.
* filled (fully\_matched): The full order amount has been filled.

#### Settlement outcome

The API field is `winning_status`; use **profit** and **loss** when describing the outcome in your product.

* **loss** (`lost`): The order closed at a loss, and no payout is made to the participant’s account.
* **profit** (`won`): The order closed at a profit, and the quantity and profit are credited to the participant’s cash balance.
* **no\_result**: There was no official result for the event, so the original quantity is returned to the participant’s cash balance.
* **tbd**: The final result is still pending.
* **manual loss** (`manually_lost`): The automatic process did not receive the final result, and manual intervention set the order to a loss.
* **manual profit** (`manually_won`): The automatic process did not receive the final result, and manual intervention set the order to a profit.
* **draw**: The order was a draw, and the original quantity is returned to the participant’s cash balance.
* **push**: No side profited, and the original quantity is returned to the participant’s cash balance.

#### Update type

* **status**: The order information has changed.
* **matching**: A new fill or matching update was received for this order.

### Market Object

This object is returned by the Trading API markets endpoint.

#### Type

* **moneyline**
* **spread**
* **total**

### Event Object

* **sub\_type**: If null, it is a normal event. If “outrights”, it is a custom-created future/outright event. The current API model name is `SportEvent`.

## Examples

Use the following examples to interpret common order status combinations.

### Check whether an order is currently on the exchange order book

```python
if status == 'open' and matching_status != 'fully_matched':
	print('I have', quantity, 'resting on the exchange order book')
else:
	print('Order is not on the exchange order book')
```

### Case 1: Fully canceled order

* T0: Order, status='open', quantity=10
* T0 + 1: Send `POST /v4/mm/cancel_order`
* T0 + 2: Receive a WebSocket update with order, status='canceled'

If the WebSocket update is missed instead:

* T0: Order, status='open', quantity=10
* T0 + 1: Send `POST /mm/cancel_order`
* T0 + 2: WebSocket update is missed because the connection is interrupted
* T0 + 3: Reconcile state after reconnecting

One approach is:

1. Call `POST /v4/mm/cancel_all_orders` to cancel all open orders.
2. Call `GET /v4/mm/get_order_history` for the last 10 minutes, or query from the last disconnect time to `now()` if you know exactly when the WebSocket disconnected.
3. After you reconcile all orders, reconnect to the WebSocket and resubmit any required orders.

### Case 2: Partially canceled order

* T0: Order, status='open', quantity=10
* T0 + 1: quantity=3 is filled
* T0 + 1.1: Send `POST /v4/mm/cancel_order`
* T0 + 2: Receive a WebSocket update with order, status='open', matching\_status='fully\_matched', quantity=3

### Case 2.2: Partial fill before cancel completes

* T0: Order, status='open', quantity=10
* T0 + 1: quantity=3 is filled
* T0 + 1.1: Send `POST /v4/mm/cancel_order`
* T0 + 2: Receive a WebSocket update with order, status='open', matching\_status='partially\_matched', quantity=10, filled\_quantity=3. This reflects the fill that occurred before ProphetX received the cancellation request.
* T0 + 3: Receive a WebSocket update with order, status='open', matching\_status='fully\_matched', quantity=3

### Case 3: Fully filled order

* T0: Order, status='open', quantity=10
* T0 + 1: quantity=10 is filled
* T0 + 1.1: Send `POST /v4/mm/cancel_order`
* T0 + 2: Receive a WebSocket update with order, status='open', matching\_status='fully\_matched', quantity=10