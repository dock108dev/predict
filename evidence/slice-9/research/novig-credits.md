> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Live Trading Maker Credit Program

> Earn cash credits when your make order supplies liquidity: in-game on straight contracts, on every fill in NFL and NCAAF futures

Earn cash credits back on qualifying trades where your make order gets matched in-game.

**NFL and NCAAF futures use a separate, higher schedule.** The credit is 70%, and you earn it on every fill. See [NFL and NCAAF Futures](#nfl-and-ncaaf-futures).

## How It Works

<Steps>
  <Step title="Eligible markets carry a Live Trading fee">
    The Program applies to markets that carry a Live Trading fee. It also applies to any market Novig designates by Notice, currently [NFL and NCAAF futures](#nfl-and-ncaaf-futures). A market that carries no fee is not eligible.
  </Step>

  <Step title="Place make orders whenever you like">
    You may place make orders on eligible markets at any time, including before the event begins. The timing of when you place an order does not determine eligibility for a Maker Credit; placing an order, by itself, never earns a Maker Credit.
  </Step>

  <Step title="Get matched while the event is in-game">
    A Maker Credit is earned only if your make order is matched (filled) while the event is in-game. When that match occurs, you earn a Maker Credit equal to 50% of the trading fee charged on your counterparty's take order (the "Taker fee"):

    ```
    Maker Credit = 50% × Taker Fee
    ```
  </Step>

  <Step title="Credited as cash within 7 days">
    Maker Credits are credited to your account as cash within seven (7) calendar days of the qualifying trade.
  </Step>

  <Step title="Cancelled or waived trades earn nothing">
    If a trade is cancelled or adjusted, or the associated fee is waived, refunded, or otherwise not collected, no Maker Credit accrues.
  </Step>
</Steps>

<Note>
  **Knowing when an event is in-game.** An event is in-game when its status is `OPEN_INGAME`. The `lifecycle` WebSocket channel publishes an `EVENT_GOLIVE` tick when an event enters live play and an `EVENT_UNLIVE` tick when it leaves, and `GET /nbx/v2/emm/events/{eventId}` returns the status directly. Both are documented on the [Market Lifecycle Channel](/api-reference/WSS/lifecycle-channel) page. Note that a delayed or suspended game can enter and leave live play more than once.
</Note>

## NFL and NCAAF Futures

NFL and NCAAF futures markets use their own fee schedule. Novig set it higher than the straight-contract schedule to promote liquidity. Two terms differ from the Program above.

|                                  | Straight contracts   | NFL / NCAAF futures      |
| -------------------------------- | -------------------- | ------------------------ |
| Taker coefficient                | 0.03                 | **0.06**                 |
| Maker fee                        | none                 | none                     |
| Maker Credit                     | 50% of the taker fee | **70% of the taker fee** |
| Credit requires an in-game match | yes                  | **no — earned on fill**  |

**A 0.06 taker coefficient, charged on execution.** A futures market has no single event in progress. Novig therefore charges the taker fee on every fill, not only during live play. The [RFQ schedule](/fees#rfq-trades) works the same way. The formula does not change:

```
Taker Fee  =  0.06  ×  P  ×  (1 − P)  ×  Contracts
```

**A 70% Maker Credit, earned on fill.** The credit follows the fee. Each time your resting order fills, you earn 70% of the taker fee Novig collects from the other side:

```
Maker Credit  =  70%  ×  Taker Fee  =  0.042  ×  P  ×  (1 − P)  ×  Contracts
```

The fee peaks at `P = $0.50`. There the taker pays \$0.015 per contract, and the maker earns \$0.0105 per contract.

Every other Program term applies to these markets without change. This covers eligibility, the exclusion of Combination Contracts, the seven-day crediting window, the reversal of credits on cancelled or waived trades, and the anti-abuse rules.

<Note>
  **Read the rate from the fill, not from this page.** Every charged fill on `GET /nbx/v2/emm/fills/all` carries `feeCoefficient`. This field reports the coefficient Novig charged. Two schedules now run at once, so read the field. Do not hardcode a rate. See [Reading Fees from the API](/fees#reading-fees-from-the-api).
</Note>

## Terms and Conditions

* Open to all Members except Affiliates of the Exchange and Members with an executed Market Maker Agreement
* Applies to markets that carry a Live Trading fee, and to any market designated by Notice; markets that carry no fee are not eligible
* Maker Credit is currently 50% of the Live Trading Taker fee collected on the trade
* NFL and NCAAF futures markets are designated Eligible Markets by Notice on their own terms: a 0.06 Taker fee coefficient and a 70% Maker Credit, earned on fill rather than requiring an in-game match
* Novig may modify, suspend, or terminate this Program, or your participation in it, at any time

***

### 1. Description of Program

Welcome to Novig's Maker Credit Program (the "Program"), through which eligible Members may earn a cash credit (a "Maker Credit") for supplying liquidity on qualifying trades in markets that carry a Live Trading fee. The Program is offered by Ludlow Exchange, LLC, d/b/a Novig ("Novig" or the "Exchange"), a Commodity Futures Trading Commission-designated contract market, located at 169 Madison Avenue #2199, New York, NY 10016. The terms "you" or "your" mean the Member participating in the Program. Participation in the Program is expressly conditioned upon acceptance of and compliance with these Terms and Conditions (these "Terms"), the Ludlow Rulebook (the "Rulebook"), and the Ludlow Member Agreement (the "Member Agreement"). Capitalized terms used but not defined in these Terms have the meanings given to them in the Rulebook and the Member Agreement. ANY DISPUTE RELATING TO THIS PROGRAM WILL BE RESOLVED IN ACCORDANCE WITH SECTION 9 BELOW, AND PARTICIPANTS WAIVE THE ABILITY TO BRING CLAIMS IN A CLASS ACTION FORMAT.

### 2. Eligible Markets and Scope

The Program applies to each market for which Novig assesses a Live Trading fee (each, an "Eligible Market"). In these Terms, "market" refers to a Contract, as defined in the Rulebook, that is available for trading on the Exchange. A market is an Eligible Market for as long as it carries a Live Trading fee under Novig's live trading fee schedule (as posted on the Novig website pursuant to Rule 3.6 of the Rulebook); a market that does not carry a Live Trading fee is not an Eligible Market and does not generate Live Trading Maker Credits.

For purposes of the Program, "Live Trading" means trading in an Eligible Market while the underlying event is in progress ("in-game"), as reflected in Novig's live trading fee schedule. Trading fees assessed at any other time — including before the event begins — are not Live Trading fees and do not generate Maker Credits.

A "qualifying trade" is a trade in an Eligible Market in which your Maker order, quote, or other Maker-side interest is matched (filled) while the underlying event is in progress (in-game), such that a Live Trading Taker Fee is assessed and collected on the counterparty's Taker order. The time at which you placed your order does not affect whether a trade is a qualifying trade; an order placed before the event begins may result in a qualifying trade if it is matched while the event is in-game.

For each Eligible Market, Novig will specify by notice on the Novig website (a "Notice") the applicable Maker Credit percentage, the effective period, the crediting frequency, and whether trades resulting from Novig's request-for-quote ("RFQ") process under Rule 5.2 of the Rulebook are eligible for Maker Credits. These terms may vary between Eligible Markets and between different periods for the same Eligible Market, provided they are posted by Notice and applied consistently to similarly situated Members.

**NFL and NCAAF futures.** Notwithstanding the three preceding paragraphs, effective September 2026 Novig designates NFL and NCAAF futures markets as Eligible Markets by this Notice, on the following terms: a Taker fee assessed on execution at a 0.06 coefficient, and a Maker Credit equal to 70% of the Taker fee actually collected on the trade. Because a futures market is not tied to a single event in progress, the Taker fee in these markets is not assessed as a Live Trading fee and the corresponding Maker Credit is not conditioned on the trade being matched while an event is in-game; it is earned whenever your Maker-side interest is filled. All other provisions of these Terms apply to these markets unchanged, including the exclusion of Combination Contracts set forth in this Section, the eligibility conditions in Section 3, and the calculation, crediting, and adjustment provisions of Sections 4 and 5.

The Program does not apply to Combination Contracts (including any multi-leg or "parlay" Contracts). No Maker Credit accrues on any trade in a Combination Contract, regardless of whether that Contract otherwise carries a Live Trading fee or is matched while the underlying event is in-game.

### 3. Eligible Members

All Members are eligible to participate in the Program, except: (i) Affiliates of the Exchange; and (ii) any Member that has executed a Market Maker Agreement with the Exchange under Chapter 4 of the Rulebook. Eligibility is determined at the time of the applicable trade.

### 4. How Maker Credits Are Calculated

For each qualifying trade in an Eligible Market, if your order, quote, or other Maker-side interest supplies liquidity, you receive a Maker Credit calculated as 50% of the Live Trading fee actually collected by Novig from the other side of the trade (the "Taker fee"):

```
Maker Credit = 50% × Taker Fee
```

Novig posts the applicable Maker Credit percentage for each Eligible Market by Notice and may adjust it from time to time by Notice, consistent with the Program's filed terms; in no case will a Maker Credit exceed the Taker fee actually collected by Novig on that trade.

A Maker Credit is calculated only on Taker fees actually collected and retained by Novig — not on fees merely assessed. If a Taker fee is reduced, waived, refunded, or rebated under any other program or arrangement, your Maker Credit reflects only the amount Novig actually collects and retains after that reduction, waiver, refund, or rebate. For purposes of the Program, "fees" means Novig's trading fees, and does not include clearing, banking, or payment processing fees.

Because an Eligible Market is, by definition, a market that carries a Live Trading fee, only Taker fees generated through live trading on the Exchange are eligible for Live Trading Maker Credits; fees generated through any other Novig product, mode, or offering are not.

Under Novig's live trading fee schedule, the Taker fee for a trade is calculated as:

```
Taker Fee = 0.03 × P × (1 − P) × Contracts
```

where "P" is the price of the Contract, expressed as a value between \$0.00 and \$1.00, and "Contracts" is the number of Contracts in the trade. Applying the current 50% Maker Credit percentage, this means:

```
Maker Credit = 0.015 × P × (1 − P) × Contracts
```

In NFL and NCAAF futures markets, as designated by Notice in Section 2, the Taker fee coefficient is 0.06 and the applicable Maker Credit percentage is 70%:

```
Taker Fee    = 0.06  × P × (1 − P) × Contracts
Maker Credit = 0.042 × P × (1 − P) × Contracts
```

These formulas, and the fee schedule generally, may be updated from time to time and are available at [Trading Fees](/fees).

### 5. Crediting and Adjustments

Novig will credit Maker Credits to your account, as cash, within seven (7) calendar days of the qualifying trade, unless Novig posts a different crediting frequency for a specific Eligible Market by Notice. Such cash, once credited, is subject to the withdrawal terms set forth in the Rulebook and the Member Agreement. If a trade is cancelled or adjusted (including under Rule 5.8 of the Rulebook), or if the associated Taker fee is waived, reversed, refunded, returned, or otherwise not collected for any reason, no Maker Credit accrues with respect to that trade, and Novig will reverse or reclaim any Maker Credit already credited for that trade.

### 6. Anti-Abuse and Compliance

You may not enter into wash trades, prearranged trades, self-matching orders, or any other trade or course of conduct designed to generate Maker Credits without bona fide market risk. The Rulebook's prohibitions on abusive trading, including Rule 5.11, apply in full to activity under this Program, and violations are subject to discipline under Chapter 9 of the Rulebook. If Novig's Chief Regulatory Officer determines that your participation is abusive or inconsistent with the purpose of the Program, Novig may withhold, reverse, or reclaim any Maker Credit and may suspend or terminate your participation in the Program.

### 7. Program Term

The effective period of the Program will be announced by Notice on the Novig website. The Program will begin at 12:00 AM Eastern Time ("ET") on August 4, 2026 (the "Implementation Date") and will expire one year from the Implementation Date, unless extended by Novig by Notice.

### 8. Monitoring, Modification, and Termination

Novig will monitor participation and trading activity under the Program and maintain records of its operation. Novig may modify, suspend, or terminate the Program, or any Member's participation in the Program, at any time by Notice.

### 9. Dispute Resolution

Any dispute relating to this Program is a "Dispute" governed by the informal dispute resolution, mandatory arbitration, and class action waiver provisions of the Member Agreement (Sections 22–25) and Chapters 10–11 of the Rulebook, including the opt-out rights and carve-outs set forth therein.

### 10. Additional Terms

**Administration:** Novig expressly reserves the right to amend, suspend, or terminate this Program at any time without prior notice or consent, and administration of this Program is at Novig's sole discretion. Questions relating to eligibility, these Terms, or any other aspect of this Program will be resolved at Novig's sole discretion, and its decisions will be final and binding.

**Release:** By participating in this Program, you agree to release, defend, indemnify, and hold harmless the Exchange and its directors, officers, and employees, consistent with Rule 12.3 of the Rulebook.
