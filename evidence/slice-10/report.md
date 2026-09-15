# Slice 10 — offline detector report

**287 tests and all ten examples pass. No current production opportunity qualifies.**

Ten production structural pairs remain settlement-UNKNOWN. Twenty candidate leg combinations retain their diagnostics; related liquidity families are not independent capacity.

## Captured production diagnostics

| Native legs | Asks | Reference gap | Limitations |
|---|---|---|---|
| kalshi: KXNFLGAME-26SEP13CLEJAC-JAC / no + polymarket_us: 381957 / 763429 | unavailable + unavailable | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13CLEJAC-JAC / yes + polymarket_us: 381957 / 763428 | unavailable + unavailable | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13CHICAR-CHI / no + polymarket_us: 381953 / 763420 | unavailable + 0.6050 | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13CHICAR-CHI / yes + polymarket_us: 381953 / 763421 | unavailable + unavailable | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13BUFHOU-HOU / no + polymarket_us: 381962 / 763439 | unavailable + unavailable | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13BUFHOU-HOU / yes + polymarket_us: 381962 / 763438 | unavailable + unavailable | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13ATLPIT-ATL / no + polymarket_us: 381956 / 763426 | unavailable + 0.3000 | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13ATLPIT-ATL / yes + polymarket_us: 381956 / 763427 | unavailable + unavailable | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13BALIND-IND / no + polymarket_us: 381955 / 763425 | unavailable + unavailable | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13BALIND-IND / yes + polymarket_us: 381955 / 763424 | unavailable + 0.6100 | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13BALIND-BAL / no + polymarket_us: 381955 / 763424 | unavailable + 0.6100 | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13BALIND-BAL / yes + polymarket_us: 381955 / 763425 | unavailable + unavailable | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13ATLPIT-PIT / no + polymarket_us: 381956 / 763427 | 0.3000 + unavailable | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13ATLPIT-PIT / yes + polymarket_us: 381956 / 763426 | 0.7100 + 0.3000 | -0.0100 | settlement UNKNOWN; no raw pricing edge; receipt skew 6194.036398 seconds; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13CLEJAC-CLE / no + polymarket_us: 381957 / 763428 | unavailable + unavailable | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13CLEJAC-CLE / yes + polymarket_us: 381957 / 763429 | unavailable + unavailable | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13CHICAR-CAR / no + polymarket_us: 381953 / 763421 | unavailable + unavailable | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13CHICAR-CAR / yes + polymarket_us: 381953 / 763420 | unavailable + 0.6050 | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13BUFHOU-BUF / no + polymarket_us: 381962 / 763438 | unavailable + unavailable | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |
| kalshi: KXNFLGAME-26SEP13BUFHOU-BUF / yes + polymarket_us: 381962 / 763439 | unavailable + unavailable | unknown | settlement UNKNOWN; one or both asks unavailable; verified sizing/fee contexts unavailable; historical observations |

The sole two-ask sum is 1.0100 ($1 reference gap −0.0100). It lacks a raw edge and also lacks qualification evidence. Available images retain their original timestamps. Source-time, status/lock and reconstruction reasons are listed per leg in the full JSON. Missing markets were not assigned synthetic historical books.

## Synthetic demonstrations

| Scenario | Quantity | Worst profit (USD) | Classification / limit |
|---|---:|---:|---|
| positive | 100 | 16.8800 | positive-conditional; no current production qualification |
| negative | 100 | -13.220000 | no-net-edge; no current production qualification |
| fees-eliminate-gap | 100 | -1.250000 | no-net-edge; no current production qualification |
| exceptional-loss | 100 | -83.1200 | no-net-edge; no current production qualification |
| zero | 100 | 0.000000 | no-net-edge; no current production qualification |
| unknown-fees | 100 | unknown | insufficient-evidence; no current production qualification |
| unavailable-size | unsized / deferred | unknown | diagnostic only; no current production qualification |
| maker-dependent | unsized / deferred | unknown | diagnostic only; no current production qualification |
| inactive | 100 | 16.880000 | positive-conditional; no current production qualification |
| stale | 100 | 16.880000 | positive-conditional; no current production qualification |
| skew | 100 | 16.880000 | positive-conditional; no current production qualification |
| duplicate-liquidity | 100 | 16.880000 | positive-conditional; no current production qualification |

Positive baseline arithmetic: 100 × (.40 + .40) = $80 acquisition cost; Kalshi modeled cash fee $1.68 plus PMUS $1.44 yields $83.12 required cash and $16.88 worst-case conditional profit. The zero example separately reserves/consumes $16.88. At .49 + .49, $98 acquisition plus $3.25 fees produces a $1.25 loss. An exceptional zero payout produces an $83.12 loss.

All real-fee-model positive scenarios remain conditional: Kalshi schedule/account assumptions and PMUS settlement-fee assumptions are not waived. Test-only synthetic zero-fee results exercise the qualification branch but are not venue fee evidence.

Defaults: 30-second receipt age, 5-second cross-leg receipt skew and 30-second source snapshot age, inclusive and configurable. Last-change age is not disconnection or latency. Fee/account unknowns remain unknown; maker-dependent orders are deferred. All calculations assume both taker legs fill once at the stated asks.

[Full results](detector-example.json) · [Verification](verification.json) · [API and limitations](../../docs/slice-10.md)

**Next: Slice 11 — full-depth arbitrage calculation and sizing. Not implemented.**
