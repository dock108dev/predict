> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Trading Fees

> How Novig prices trading fees, and when they apply

Novig charges a single trading fee, on one side of a trade. On straight contracts it applies only while the underlying event is live; [RFQ trades](#rfq-trades) are priced on their own schedule.

## The Formula

```
Total Fee  =  P  ×  (1 − P)  ×  Coefficient  ×  Contracts
```

| Term          | Meaning                                                                               |
| ------------- | ------------------------------------------------------------------------------------- |
| `P`           | The **execution price** of the fill, between \$0.00 and \$1.00 — not your limit price |
| `Coefficient` | Currently **0.03** for live taker fills                                               |
| `Contracts`   | The number of contracts in the fill, where one contract pays \$1.00 at settlement     |

<Warning>
  **Watch the units.** `Contracts` counts \$1.00-payout contracts, but the API's `qty` field is denominated in minimal units: **100 `qty` = 1 contract** (`qty` of 1 is \$0.01 of payout). Divide `qty` by 100 before putting it in the formula, or you will overstate the fee by 100×.
</Warning>

Each fill is priced independently, so a partially filled order accrues a fee per fill rather than one fee on the parent order.

**Fees are charged exactly, including sub-cent amounts** — there is no rounding up to the cent and no minimum fee. The only quantization is the ledger's own precision, 5 decimal places (\$0.00001), applied with standard half-up rounding. A fill small enough to owe a fraction of a cent is charged that fraction.

The formula is symmetric around \$0.50: `P` and `1 − P` produce the same fee, so a fill at \$0.30 costs exactly what a fill at \$0.70 costs. The fee peaks at `P = 0.50`, where `0.03 × 0.25` works out to \$0.0075 per contract — 0.75% of payout, or 1.5% of notional at even money — and falls toward zero at both tails.

### Worked Examples

At the current 0.03 coefficient:

| Fill                   | `qty` on the wire | Calculation                 | Fee charged |
| ---------------------- | ----------------- | --------------------------- | ----------- |
| 100 contracts @ \$0.50 | 10,000            | `0.50 × 0.50 × 0.03 × 100`  | \$0.75      |
| 100 contracts @ \$0.30 | 10,000            | `0.30 × 0.70 × 0.03 × 100`  | \$0.63      |
| 100 contracts @ \$0.70 | 10,000            | `0.70 × 0.30 × 0.03 × 100`  | \$0.63      |
| 100 contracts @ \$0.10 | 10,000            | `0.10 × 0.90 × 0.03 × 100`  | \$0.27      |
| 500 contracts @ \$0.45 | 50,000            | `0.45 × 0.55 × 0.03 × 500`  | \$3.7125    |
| 1 contract @ \$0.50    | 100               | `0.50 × 0.50 × 0.03 × 1`    | \$0.0075    |
| 0.01 contract @ \$0.50 | 1                 | `0.50 × 0.50 × 0.03 × 0.01` | \$0.00008   |

The last three rows are the sub-cent rule: \$3.7125 is charged as \$3.7125, not rounded to \$3.72, and a one-`qty` fill owes \$0.000075, charged as \$0.00008 after the ledger's 5-decimal quantization. A cent floor on that fill would be a \~125× overcharge, which is why there isn't one.

## Who Pays

| Side      | Fee                                                                                    |
| --------- | -------------------------------------------------------------------------------------- |
| **Taker** | Pays the fee above. Debited from your balance at match time                            |
| **Maker** | Pays **no fee**, and may earn a [Maker Credit](/maker-credit-program) on the same fill |

There is no maker fee, and no opt-in or contract is required to collect Maker Credits. The Maker Credit is currently 50% of the taker fee actually collected on the trade, which works out to:

```
Maker Credit  =  P  ×  (1 − P)  ×  0.015  ×  Contracts
```

See the [Live Trading Maker Credit Program](/maker-credit-program) for the full terms, eligibility, and crediting schedule.

<Warning>
  **Maker Credits are straights only. RFQ makes do not earn a Maker Credit.** Quoting an RFQ makes you the maker on a combination contract, and combination contracts are excluded from the Program — see [Eligible Markets and Scope](/maker-credit-program#2-eligible-markets-and-scope). No amount of RFQ volume accrues Maker Credits; only straight-contract makes matched in-game do.
</Warning>

## RFQ Trades

RFQ executions are priced on their own coefficient and their own form of the same quadratic.

|                         | Straight contracts                         | RFQ (combination contracts) |
| ----------------------- | ------------------------------------------ | --------------------------- |
| Taker coefficient       | 0.03                                       | **0.10**                    |
| Maker fee               | none                                       | none                        |
| Maker Credit            | 50% of the taker fee, when matched in-game | **not eligible**            |
| Charged only while live | yes                                        | no — assessed on execution  |

A combination contract has no single contract price, so the taker fee is expressed in stake form. With `wager` the taker's stake and `collateral` the pricer's, the implied probability is `wager / (wager + collateral)`, and `Coefficient × P × (1 − P) × Pot` reduces to:

```
RFQ Taker Fee  =  0.10  ×  wager  ×  collateral  ÷  (wager + collateral)
```

Two differences from the straight schedule worth calling out. The RFQ taker fee **is not gated on event liveness** — RFQs execute before the event begins, so the charge applies on execution rather than only during live play, and it is not a Live Trading fee for Maker Credit purposes. And the maker side, the EMM pricing the RFQ, pays **no fee** but likewise earns **no credit**.

## When Fees Apply

<Warning>
  **Straight-contract fees are charged only on fills matched while the underlying event is live** — that is, while the event's status is `OPEN_INGAME`. A fill matched at any other time is not charged, on either side, and generates no Maker Credit. ([RFQ trades](#rfq-trades) are the exception: they are charged on execution, live or not.)

  Liveness is evaluated **at match time**, not when the order was placed. A resting order placed hours before kickoff that fills in the second quarter is a live fill and is charged; a live-priced order that fills during a suspension is not.
</Warning>

Because the charge follows the event's status at the moment of the match, knowing whether an event is live is a fee question, not a cosmetic one. There are two ways to know, and they are covered in detail on the [Market Lifecycle Channel](/api-reference/WSS/lifecycle-channel) page:

<CardGroup cols={2}>
  <Card title="WebSocket: the transitions" icon="bolt" href="/api-reference/WSS/lifecycle-channel">
    The `lifecycle` channel publishes `EVENT_GOLIVE` when an event enters live play and `EVENT_UNLIVE` when it leaves. Fees begin on `EVENT_GOLIVE` and stop on `EVENT_UNLIVE`.
  </Card>

  <Card title="REST: the snapshot" icon="database" href="/api-reference/WSS/lifecycle-channel#reading-event-status-over-rest">
    `GET /nbx/v2/emm/events/{eventId}` returns the event's `status`. `OPEN_INGAME` is exactly the fee-charged condition. Use it to bootstrap on connect and after any reconnect.
  </Card>
</CardGroup>

<Note>
  **The live window can open more than once.** A game that is delayed or suspended mid-play goes `OPEN_INGAME → DELAYED → OPEN_INGAME`, so fees switch on, off, and on again. Each `EVENT_GOLIVE` also cancels every order resting across that event's markets. Track the edges rather than assuming one live window per event — see the [repeatability warning](/api-reference/WSS/lifecycle-channel#event-liveness-event_golive-and-event_unlive).
</Note>

## Reading Fees from the API

Every fill on `GET /nbx/v2/emm/fills/all` reports what it cost you. A charged fill carries `fee`, the total debited from your
wallet for that fill in minimum currency units. It is omitted on fills that were not charged, so a maker fill or a non-live
fill simply has no `fee` field.

Each fill also lists its `transactions`, the ledger rows that debited your wallet: a `FILL_*` row for your collateral
(`price × qty` for the outcome you bought) and, on a charged fill, a `FEE_*` row for the fee. The `kind` names your role
(`TAKER` or `MAKER`), whether the event was live at match time (`LIVE` or `NONLIVE`), and whether the charge came from cash
(`FUNDS`) or promotional credit (`TRADE_CREDIT`). Only your own wallet's rows appear, so a maker never sees the taker's fee.

```json theme={null}
{
    "id": "01990f91-2d8a-7b6c-8a1e-4f5a6b7c8d90",
    "qty": 200,
    "price": 0.61,
    "isTaker": true,
    "fee": "1.4274",
    "transactions": [
        { "kind": "FILL_STRAIGHT_TAKER_FUNDS", "amount": "122", "...": "..." },
        { "kind": "FEE_STRAIGHT_TAKER_LIVE_FUNDS", "amount": "1.4274", "...": "..." }
    ]
}
```

The fee row is the formula at the top of this page: `0.03 × 0.61 × 0.39 × 200 = 1.4274` minimum units, or \$0.014274. Real-time
`fill` events on the [private channel](/api-reference/WSS/private-channel) do not carry these fields; fetch the fill history.

## Scope and Notes

* **Two schedules.** The formula at the top of this page prices straight contracts. Combination contracts (multi-leg or "parlay" contracts, including everything traded via RFQ) are priced by the [RFQ schedule](#rfq-trades) and are not eligible for Maker Credits.
* **Trading fees only.** "Fees" here means Novig's trading fees. Clearing, banking, and payment processing fees are not included.
* **The coefficient can change.** The coefficient above is the current live trading fee schedule, posted pursuant to Rule 3.6 of the Ludlow Rulebook. Read it from this page rather than hardcoding a rate you can't update.
* **No cent floor.** Charges carry to 5 decimal places (\$0.00001), so sub-cent fees are charged as sub-cent amounts.

<Tip>
  Liquidity providers (LPs) with USD 200,000 or more deposited can request a dedicated Slack channel with the Novig team.
</Tip>

Questions on fees or the Maker Credit Program: [caleb.henry@novig.co](mailto:caleb.henry@novig.co).
