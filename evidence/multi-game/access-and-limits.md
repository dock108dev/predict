# Multi-game verification pre-dispatch basis

Checked 2026-09-16 01:03 UTC. One new owner-authorized read-only scan, separate from all E6 attempt markers. No sportsbook requests, orders, upgrades or subscription changes. Additional spend $0.

Official pages checked:
- https://docs.kalshi.com/getting_started/rate_limits — Basic read budget 200 tokens/second, default request cost 10; actual account limits and endpoint costs will be rechecked inside this scan, before market subscriptions.
- https://docs.kalshi.com/websockets/orderbook-updates — native `market_tickers` array supports multi-market snapshots/deltas.
- https://docs.polymarket.us/api-reference/rate-limits — 20 public REST requests/second/IP and 20 authenticated requests/second/key.
- https://docs.polymarket.us/api-reference/websocket/markets — up to 100 markets/subscription. No numeric retail connection ceiling stated; this scan uses only one concurrent socket per venue.

Existing read-only project access and no-additional-cost basis: docs/e6-prediction-only-report.md and its official-access.json/account-api-limits.json evidence. No metered data product or paid endpoint is used. Tokens are venue rate-limit units, not paid credits.

Finite run limits: maximum six games, selected only with >300 seconds before kickoff. A 175-second session timer includes discovery and all retries; allow up to five seconds for joined shutdown within the authorized 180 seconds. Both native subscriptions multiplex the selected games, at most two connection attempts/source (four total), one concurrent socket/source (two total). 64 REST requests/source (128 total), sequential <=1/sec/source; 600 messages/source (1,200 total); 1 MiB maximum response/frame and 16 MiB charged bytes/source (32 MiB total), including pending frame reservations. Accepted ingress <=2,048 records/16 MiB, queue 48 records/4 MiB, journal 4,096 records/32 MiB. Any earlier cap ends the session. Metadata revalidated about every 45 seconds, with no silent game replacement. UI polling reads local state only. Startup and refresh do not dispatch market requests. Durable one-attempt marker prevents another scan.
