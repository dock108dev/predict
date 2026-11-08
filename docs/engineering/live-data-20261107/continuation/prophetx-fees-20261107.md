---
updatedAt: 2026-11-03T15:41:34.000Z
agentTools:
  projectIndex: https://docs.prophetx.co/llms.txt
---

# Trading Fees

How ProphetX charges trading fees — the commission and maker/taker models, and where the fee you were charged shows up in the API.

ProphetX charges a fee on filled orders using one of two models. Which model and rate apply to your account is configured on ProphetX's side — there's no field on `submit_order` to choose it, and no endpoint to query your current rate. If you're not sure which model your account is on, ask your ProphetX integration contact.

This page covers fees on regular fills. Closing a position through [Positions](https://docs.prophetx.co/docs/positions) is charged differently — a flat percentage of profit only, never your account's maker/taker or commission rate, and never charged on a loss or breakeven close.

***

## The two models

| Model         | How it charges                                                                                                                                                                                                                                                                                                                    |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `commission`  | A flat rate applied to every fill, regardless of which side of the trade you were on.                                                                                                                                                                                                                                             |
| `maker_taker` | The rate depends on whether your fill was passive (**maker** — you were resting on the book and got taken) or aggressive (**taker** — you crossed and took existing liquidity). Taker pays the higher rate; maker pays the lower rate, and may also earn a rebate — see [Maker Rebates Program](https://docs.prophetx.co/docs/volume-fee-rebate-program). |

***

## Telling maker from taker

The API doesn't return a role field on a fill, but you can derive it from what you already control:

* An `ALO` (Add-Liquidity-Only) order is **always maker** — it's rejected rather than allowed to take, so any fill it gets was passive. See [order\_strategy](https://docs.prophetx.co/docs/integration#step-5-submit-and-cancel-orders). Over FIX, the equivalent is `ExecInst(18)=6` (make-only) — see [§5.1](https://docs.prophetx.co/docs/prophetx-fix-order-entry#51-make-only-orders-and-order-size).
* A market order is **always taker** — by definition it crosses into existing liquidity.
* A plain limit order is maker if it rested on the book and was later taken by someone else, and taker if it crossed and matched immediately on entry.

***

## Where the fee shows up

The examples below all follow the same order, so the numbers tie together across surfaces: a $30 maker order on MLB event `10079773`, market `219`, at price `120`, that fills in three $10 pieces charging `0.04`, `0.04`, and `0.05` — a `0.13` total.

**REST.** The dollar amount you were actually charged — already resolved under whichever model applies to you — is in the `fee` field.

`GET /v4/mm/get_trades` and `GET /v4/mm/get_order_matched_detail` — the fee for one specific fill:

```json
{
  "data": {
    "trades": [
      {
        "id": 918273645,
        "order_id": "partner_8900af46-2b89-40fa-a27a-ff65fcb437d2",
        "price": 120,
        "quantity": 10,
        "profit": 12,
        "fee": 0.04,
        "strike": null,
        "strike_id": "cffa7ddc4fd50acbe51684e7addabe00",
        "status": "settled",
        "winning_status": "tbd",
        "matched_at": "2026-10-06T07:12:03Z"
      }
    ],
    "next_cursor": null
  }
}
```

`GET /v4/mm/get_order_history` and `GET /v4/mm/get_order/{id}` — the order's total fee across all three fills (the same object; `get_order_history` wraps it in a `data.orders[]` list, `get_order/{id}` returns it directly under `data`):

```json
{
  "data": {
    "order_id": "partner_8900af46-2b89-40fa-a27a-ff65fcb437d2",
    "sport_event_id": 10079773,
    "market_id": 219,
    "outcome_id": 4,
    "price": 120,
    "quantity": 30,
    "filled_quantity": 30,
    "open_quantity": 0,
    "profit": 36,
    "fee": 0.13,
    "status": "settled",
    "matching_status": "fully_matched",
    "winning_status": "tbd",
    "strike_id": "cffa7ddc4fd50acbe51684e7addabe00"
  },
  "last_synced_at": "2026-10-06T07:12:05Z"
}
```

**WebSocket.** The private `orders` event carries the same running total as `fee`, updated on every fill — see [Private user channel](https://docs.prophetx.co/docs/websocket-events#private-user-channel). It's only present if you registered for v2 (CFTC-vocabulary) messages; the legacy v1 `wagers` feed never carries it. This frame is the fill confirming the first $10 piece, so `fee` is `0.04` — not yet the order's `0.13` total:

```json
{
  "aggressive": false,
  "fee": 0.04,
  "fill_price": 120,
  "filled_quantity": 10,
  "matching_status": "partially_matched",
  "open_quantity": 20,
  "price": 120,
  "quantity": 30,
  "total_filled_quantity": 10,
  "update_type": "matching",
  "sport_event_id": 10079773,
  "status": "open",
  "user_id": "<redacted>"
}
```

The public `trade_execution`/`matched_bet` broadcast — the anonymized tape every participant receives — deliberately does **not** include fee: it's not account-specific data, and exposing it there would leak your commercial terms to everyone else on the feed.

**FIX.** The same fee rides on the Execution Report: `Commission(12)` is this fill's fee (sent only when it's nonzero), and the custom `CumulativeFee(6002)` tag is the running total across all fills on the order. FIX is tag=value, not JSON — the Trade report for that same first fill carries:

```
ExecType(150)=F  OrdStatus(39)=1  LastQty(32)=10  LastPx(31)=120
Commission(12)=0.04  CommType(13)=3  CumulativeFee(6002)=0.04
```

See [Execution Report](https://docs.prophetx.co/docs/prophetx-fix-order-entry#8-execution-report-8) in the FIX Order Entry spec.

**Wallet.** A `maker_taker` fee posts as a `FEE` transaction (`transaction_sub_type: MAKER_TAKER`); a `commission` fee posts as `COMMISSION` — see [transaction types](https://docs.prophetx.co/docs/wallets). The ledger row for that same first fill:

```json
{
  "data": {
    "transactions": [
      {
        "status": "Completed",
        "user_id": "550e8400-e29b-41d4-a716-446655440000",
        "transaction_type": "FEE",
        "transaction_sub_type": "MAKER_TAKER",
        "amount": 0.04,
        "change": -0.04,
        "balance": 999.96,
        "balance_before": 1000.00,
        "details": "4b6e2f1a-7c3d-4e8a-9f2b-1d5c6a8b9e0f",
        "market_id": "219",
        "event_id": "10079773",
        "trade_id": "918273645",
        "description": "Maker/taker fee",
        "created_at": "2026-10-06T07:12:03Z"
      }
    ],
    "next_cursor": null
  }
}
```