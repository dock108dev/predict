# Prediction Arb — Phase 0 venue access and reconnaissance

Verified **2026-09-11** against official sources and the limited public observations below. This is public reconnaissance, not authenticated qualification, a data license, settlement-equivalence approval, or implementation. [PLAN.md](../PLAN.md) remains unchanged; corrections are recorded here. [Status tracker](../../prediction_arb_next_steps.md).

## Result and evidence standard

Kalshi and **Polymarket US** supplied anonymous production NFL discovery, rules/metadata and multi-level books. ProphetX and Novig document authenticated live feeds, but neither was accessed. No venue has yet demonstrated reliable continuous collection, disconnect recovery or measured latency. Actual access conditions remain unverified. The corrected Kalshi own-trading scope is recorded below; no separate permission-letter gate applies to synthetic development.

Labels used throughout: **D** = documented by an official source; **O** = observed in a saved public response; **A** = requires authenticated verification or venue clarification. A missing documented guarantee is marked unknown, not asserted absent. Every source link below was reviewed on 2026-09-11; publication/effective dates are stated separately where available. Mutable documentation must be rechecked before implementation.

| Venue | Public production observation | Documented live/depth path | Sandbox / production dependency | Initial scanner assessment |
|---|---|---|---|---|
| Kalshi | **O:** NFL catalog, event/rules and YES/NO depth; MLB series fees | **D:** anonymous REST; authenticated snapshot/delta WebSocket | Separate demo account/key; production membership/account/API key for streaming; actual conditions unverified | Strong technical candidate; streaming, fee overrides and actual access remain unqualified |
| ProphetX | No anonymous live path established; no live capture | **D:** authenticated V4 market selections/ladder and event WebSockets | Sandbox signup/2FA plus API enablement; distinct production approval and keys | Conditional candidate; depth semantics, rate limits and recovery need verification |
| Polymarket US | **O:** NFL event, moneyline/rules and bid/offer depth | **D:** public gateway REST; authenticated retail market WebSocket | App/account verification and API key; institutional preproduction is separate | Strong technical candidate; streaming semantics/depth ceiling and use rights remain unqualified |
| Novig | No anonymous live path established; no live capture | **D:** NBX REST order ladders plus authenticated order-book WebSocket | Venue-issued OAuth client credentials; QA and production provisioning | Conditional candidate with a real documented depth path; accessibility and performance unproven |

Evidence: [capture guide](../evidence/phase-0/README.md), [provenance manifest](../evidence/phase-0/manifest.json). Eight unauthenticated production GETs returned HTTP 200; five official PDFs were saved separately. No authentication requests, account access, WebSocket connections, account creation or venue contact occurred. Direct documentation fetches that returned 403/429 were not circumvented. No application or infrastructure was created during Phase 0. The later synthetic Slice 1 is recorded in [slice-1.md](slice-1.md).

## 1. Kalshi

### Access, discovery and books

**D:** Anonymous production REST is explicitly supported for market data. Recommended base: `https://external-api.kalshi.com/trade-api/v2`; supported alias `https://api.elections.kalshi.com/trade-api/v2`. Demo REST: `https://external-api.demo.kalshi.co/trade-api/v2`, alias `https://demo-api.kalshi.co/trade-api/v2`. Demo credentials/accounts are separate from production. Only production anonymous data was tested. [Environments](https://docs.kalshi.com/getting_started/api_environments), [public market-data quickstart](https://docs.kalshi.com/getting_started/quick_start_market_data).

Discovery uses `GET /series`, `/series/{series_ticker}`, `/events`, `/events/{event_ticker}`, `/markets` and `/markets/{ticker}`. Series identify contract terms and settlement sources; event children carry market status and rules. Use cursor pagination and explicit series/market identity; this capture was not a complete sports census. [Series list](https://docs.kalshi.com/api-reference/market/get-series-list), [series detail](https://docs.kalshi.com/api-reference/market/get-series), [quickstart](https://docs.kalshi.com/getting_started/quick_start_market_data).

**D:** `GET /markets/{ticker}/orderbook?depth=0` requests all levels; 1–100 requests bounded depth. `orderbook_fp.yes_dollars` and `no_dollars` contain dollar-price strings and fractional contract-quantity strings. Both sides are **bids**. A NO bid at `p` supplies an implied YES offer at `1-p`, with the same contract quantity. Do not interpret these as cent integers, stakes, or two independent ask books. **O:** the captured book is ascending by price, despite the endpoint prose describing best-to-worst; select prices explicitly. [Order-book reference](https://docs.kalshi.com/api-reference/market/get-market-orderbook).

### Streaming, time and suspension

**D:** Production `wss://external-api-ws.kalshi.com/trade-api/ws/v2`; demo `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`. The handshake requires an API key, millisecond timestamp and RSA-PSS signature over timestamp + method + path. Public REST does not imply anonymous WebSockets. Production account eligibility and actual API-key availability were not checked. [Environments](https://docs.kalshi.com/getting_started/api_environments), [WebSocket quickstart](https://docs.kalshi.com/getting_started/quick_start_websockets).

`orderbook_delta` subscriptions accept market tickers, deliver an initial `orderbook_snapshot`, then deltas with `sid`, `seq`, side, `price_dollars`, and signed `delta_fp`. Subscription updates support adding/removing markets and `get_snapshot`. Optional delta `ts_ms` is an exchange millisecond timestamp; `ts` is deprecated. No universal numeric market/subscription ceiling was established. **A:** verify sequence scope, gap recovery and limits with the intended account. A reconnect or gap must invalidate local depth until a new synchronized snapshot is obtained; no replay guarantee was established. [Order-book updates](https://docs.kalshi.com/websockets/orderbook-updates).

The server sends protocol Ping frames every 10 seconds; clients must Pong. Scheduled Thursday 03:00–05:00 ET maintenance can disconnect sessions. Exchange/trading pauses may leave resting orders visible, so a nonempty book is not evidence of tradability. [Keepalive](https://docs.kalshi.com/websockets/connection-keep-alive), [maintenance and pauses](https://docs.kalshi.com/getting_started/maintenance_and_pauses).

REST states include `initialized`, `active`, `inactive`, `closed`, `determined`, `disputed`, `amended`, `finalized`; filter `open` maps to `active`. `inactive` denotes a temporary pause. Reactivation cancels resting orders. Some time-based transitions do not emit lifecycle messages. Track market state, scheduled close and exchange availability together. Expected expiration is expected resolution time, **not kickoff**. **O:** the event's `last_updated_ts` is a year-0001 sentinel; REST book has no exchange timestamp/sequence. Capture time and metadata timestamps cannot establish quote age. [Market lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle).

### Limits and data use

**D:** Current authenticated limits use token buckets, normally 10 tokens/request, not the plan's fixed requests/second assumption. Read/write tokens per second: Basic 200/100; Advanced 300/300; Expert 600/600; Premier 1000/1000; Paragon 2000/2000; Prime 4000/4000; Prestige 10000/8000. `/account/limits` and `/account/endpoint_costs` determine account-specific budgets. Basic/Advanced read burst capacity spans two seconds, higher tiers one. Current 429 responses lack rate-limit/Retry-After headers. **A:** anonymous quota and actual account entitlement remain unknown; authenticated tier figures must not be assigned to anonymous traffic. [Rate limits](https://docs.kalshi.com/getting_started/rate_limits).

**Corrected data-use framing — 2026-09-11:** the owner's scanner and replay support personal potential trading. See the [rechecked assessment](kalshi-data-use.md) for the own-trading allowance, third-party sharing restriction and actual access conditions. No project-specific approval is claimed, and no separate Kalshi support letter is required before synthetic development. The [inquiry](kalshi-data-use-inquiry.md) is optional and unsent. Slice 1 was separately authorized and completed with wholly synthetic fixtures; this does not qualify live access.

### Fees

Use `C` = contracts, `p` = dollar price. **D:** the schedule effective **2026-07-07** gives taker model `M × 0.07 × C × p × (1-p)` and maker model `M × 0.0175 × C × p × (1-p)`, default maker multiplier zero except designated markets. It lists NFL/MLB maker fees, no settlement or membership fee, and warns that FCM charges can differ. Official general example: 100 contracts at $0.50 cost $1.75 in fees. Its cent-rounded table is insufficient for current fractional-fill/account rounding. [Official fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf).

**O:** captured `KXNFLGAME` has `quadratic_with_maker_fees`, multiplier `1`; `KXMLBGAME` has the same type, multiplier `0.5`. MLB historical fee changes show `0.5` scheduled at **2026-08-07T04:59:45.131Z**. The July PDF's MLB multiplier cannot be hardcoded as current. Series metadata alone is also insufficient: **D:** `GET /events/fee_changes` exposes event-level overrides with scheduled timestamps; null overrides revert to the series. Lifecycle `event_fee_update` signals changes. **A:** the candidate event's override history was not captured, so its final effective fee is not certified. [Saved fee history](../evidence/phase-0/kalshi-fee-changes.json), [series fee changes](https://docs.kalshi.com/api-reference/exchange/get-series-fee-changes), [event fee changes](https://docs.kalshi.com/api-reference/events/get-event-fee-changes), [lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle).

**D:** Trade fees round upward to six decimal dollars. Balance precision is $0.0001 for direct members and $0.01 for non-direct members. Floor signed revenue minus trade fee to that grid; the difference is a rounding fee. A per-order accumulator spans maker/taker fills and rebates accumulated rounding, capped so net fees stay nonnegative. Official example: revenue −$0.055, model fee $0.00363825 → trade fee $0.003639, rounding fee $0.001361, balance change −$0.06. This rounding refund is not a universal maker reward. **A:** account precision, additional incentives and event overrides require verification. [Fee rounding](https://docs.kalshi.com/getting_started/fee_rounding).

### Settlement and blockers

**D/O, NFL:** full-game overtime included; two-team tie pays $0.50. Postponed games must begin within 48 hours of original start, otherwise exchange fair value applies. General terms distinguish suspensions before 55 minutes, resumption windows and official final results; a pregame forfeit uses fair value. Candidate-specific rules are saved and take priority over broad summaries. [NFL terms](https://assets.kalshi.com/contract_terms/FOOTBALLGAMEWIN.pdf), [captured event/rules](../evidence/phase-0/kalshi-tb-cin-event.json).

**D, MLB:** extra innings included; without a tie strike, tied teams split settlement. An officially final shortened game can settle to its winner. Start/resumption generally uses a 48-hour window from original start, with abandonment/cancellation otherwise at exchange fair value. Home/away reversals, doubleheaders and forfeits have separate clauses. No full-game listed-pitcher requirement was located; absence of a clause is not verification that all MLB markets are pitcher-independent. [MLB terms, especially pp. 2–4](https://assets.kalshi.com/contract_terms/BASEBALLGAMEWIN.pdf).

**Remaining:** verify membership and applicable API/account conditions; owner-authorized demo/production key setup; stream limits/recovery demonstration; event fee overrides and account precision; exact MLB contract/pitcher interpretation. No continuous-data readiness claim.

## 2. ProphetX

### Access, discovery and depth

**D:** Sandbox base `https://api.sandbox.prophetx.dev/partner`. Onboarding requires a sandbox account, phone/2FA and venue API enablement/test funds; a consumer signup alone does not establish API entitlement. Access/secret keys obtain a bearer session through `/auth/login`; access token lifetime is 20 minutes, refresh token three days. No anonymous live endpoint was established. **A:** none of these steps was performed. [Integration guide](https://docs.prophetx.co/docs/integration).

**D:** Production uses `https://cash.api.prophetx.co/partner`, with separate production approval and credentials. Sandbox success does not confer production access or demonstrate live production liquidity. [Production transition](https://docs.prophetx.co/docs/prophetx-service-api-switch-to-production).

Relative to the `/partner` base, discovery includes `/mm/get_tournaments`, `/mm/get_sport_events?tournament_id=…`; V4 `/v4/mm/get_price_ladder`, `/v4/mm/get_markets?event_id=…`, `/v4/mm/get_multiple_markets?event_ids=…` supply ladder/market selections. Use V4, not deprecated market endpoints. NFL tournament 31 and MLB 109 are documented point-in-time examples, not permanent mappings. **A:** no response was captured to prove current identifiers, full available depth, quantity units, price representation, event start/update timestamps, market status enums, suspension removal or maximum batch size. [Integration](https://docs.prophetx.co/docs/integration), [V4 multiple-markets reference](https://docs.prophetx.co/reference/get_v4-mm-get-multiple-markets).

The separate FIX order-entry documentation describes American/decimal/probability prices and stake units. Those are **not evidence** of the V4 REST/WebSocket encoding. `strike_id`, selection identities and ladder mapping must be checked on authenticated data; do not copy Kalshi contract units or treat advertised odds as executable depth. [FIX reference](https://docs.prophetx.co/docs/prophetx-fix-order-entry).

### Streaming, limits and usage

**D:** Authenticated `/partner/websocket/connection-config` returns connection configuration including `ws_host` when applicable. Register through `/partner/v4/mm/websocket`, then authenticate/sign in and subscribe using socket/channel authorization. Event channels carry `market_selections`; nested JSON must be decoded. `channel_limit` is returned configuration—400 is an example, not a universal entitlement. New event channels replace shared market-selection routing; main-market migration deadline was August 12, 2026. Sandbox uses Talaria; documentation says production dual-publishes with legacy primary, with **September 16, 2026 planned cutover**, not a completed change on this verification date. **A:** no numeric replay/sequence guarantee, atomic snapshot/delta handoff, heartbeat interval or recovery contract was established. Reconnect requires fresh connection/auth/subscriptions and a verified resynchronization procedure before accepting a book. [Current WebSocket guide](https://docs.prophetx.co/docs/integrate-with-websockets).

**A:** Numeric REST market-data limits, actual channel allowance, exchange timestamps, transport-gap detection and halt behavior require venue documentation or authorized samples. Do not invent polling rates or equate channel delivery with exchange freshness. The official [daily market-data reports](https://www.prophetx.co/lobby/t-c/market-data) are not live book access.

Participant agreement §9.2 restricts data to internal trading/compliance use and prohibits redistribution absent agreement. Rulebook §10.1 adds restrictions on commercial derivatives/redistribution. **A:** confirm whether this private cross-venue research and retained replay dataset are covered by the eventual API agreement. [Participant agreement](https://www.prophetx.co/lobby/t-c/market-participant-agreement), [official rulebook](https://framerusercontent.com/assets/53Lhf2UbmDx79ZBvhNu9ZRwNF0.pdf).

### Fees

**D:** Straight markets charge **2% of net gains per market**, assessed at settlement; this is not 2% of gross payout or every contract's purchase price. The current page is updated August 19, 2026. Parlay fees are separately linked; older zero-fee RFQ language must not be generalized to current products. [Trading fees](https://www.prophetx.co/lobby/t-c/trading-fees).

The August 14 filing extends the program originally effective June 29, 2026 through an initial 12-month term. Monthly maker-volume marginal tiers: first $50,000 → 0% rebate; $50,000–$750,000 → 20%; $750,000–$3m → 40%; $3m–$7.5m → 60%; above $7.5m → 80%. Apply the volume-weighted percentage to paid fees, not 80% to all fees merely on crossing the last tier. Official examples: $75,000 volume/$1,000 fees → $66.66 rebate; $7.5m/$100,000 → $49,860. **A:** exact rounding, loss offsets/netting, void treatment and eligibility require clarification. [Fee extension and examples, pp. 2–4](https://framerusercontent.com/assets/oNmtogNF4ucRmj5pymJVs4DLV4.pdf).

A separate August 18 designated-market-maker amendment offers remaining-fee rebates only with qualifying obligations; do not assume owner eligibility. No additional independent settlement levy was located beyond the gains-based charge; absence is not a confirmed zero. [Market-maker amendment](https://framerusercontent.com/assets/85ViMsd6Rf5KgfEaT9KmTEwevo.pdf).

### Settlement and blockers

**D, NFL:** July 14 full-game terms include overtime; **tie voids the contract and returns collateral**, unlike Kalshi/Polymarket US $0.50 settlement. The filing's 55-minute/24-hour clauses appear under total-points rules and cannot be silently applied to moneyline. **A:** precise full-game moneyline postponement/cancellation handling needs the applicable listing and governing rules. [NFL filing, especially p. 4](https://framerusercontent.com/assets/3xBUPoodNIUMWAauxaaccjNRSo.pdf).

**D, MLB:** July 8 amended rules use official MLB results and extra innings. Games must commence on the scheduled local calendar day or void; suspended games not resumed within 36 hours of scheduled start void subject to 4.5/5-inning/determined-outcome exceptions. Called ties are treated as suspensions. Pitcher clauses occur in props; no universal full-game listed-pitcher condition was established. [MLB amendment](https://framerusercontent.com/assets/xOPD9P6Y43gSYnXRNP45EYfPMs.pdf).

**Remaining:** sandbox API enablement; separate production entitlement/keys; permitted data use; actual event/selection/depth/status samples; rate limits, timestamps and reconnect synchronization; moneyline exception rules and exact fee netting/rounding. No ProphetX live sample or common-event coverage established.

## 3. Polymarket US — not international Polymarket

### Access, discovery and depth

This section uses **US-specific** documentation and hosts. International Gamma/CLOB endpoints, wallet/chain mechanics and international fee tables do not establish US capability or fees. **D:** public discovery and books use `https://gateway.polymarket.us`; authenticated retail APIs use `https://api.polymarket.us`. **O:** anonymous US NFL data and depth returned successfully. [US API introduction](https://docs.polymarket.us/api-reference/introduction).

Documented paths include `GET /v1/events`, `/v2/leagues/{slug}/events`, `/v1/markets`, and **singular** `/v1/market/slug/{slug}` for details. Books use **plural** `/v1/markets/{slug}/book`, with sibling `/bbo` and `/settlement` endpoints. Event/market metadata provides game identity, descriptions, sides and status. [NFL-capable league discovery](https://docs.polymarket.us/api-reference/sports/get-events-by-league-slug), [market detail](https://docs.polymarket.us/api-reference/markets/get-market-by-slug), [book](https://docs.polymarket.us/api-reference/markets/get-market-book).

**D/O:** books expose USD `px.value` strings, decimal contract `qty`, bids and offers for the long outcome; identify it from `marketSides.long`. The complementary short-side purchase price is `1 - long bid`, preserving contract quantity. **O:** market `381958` has Tampa Bay as long and Cincinnati as short, fractional depth and minimumTradeQty `0.01`; do not align the separate `outcomes` string array by position to infer sides. Observed REST depth is 27 bids/24 offers. **A:** maximum depth/truncation guarantee has not been established. [Book schema](https://docs.polymarket.us/api-reference/markets/get-market-book), [saved market](../evidence/phase-0/pmus-tb-market.json).

### Authentication, streaming and environments

**D:** Retail API-key setup requires the US app/account verification followed by the developer portal. Signed requests use Ed25519, API-key ID, millisecond timestamp (30-second tolerance) and base64 signature of timestamp + method + path. **A:** owner's eligibility, onboarding/invitation status and key availability were not inspected. [US authentication](https://docs.polymarket.us/api-reference/authentication).

No anonymous retail sandbox was established. Institutional preproduction is a different provisioned pathway: `https://api.preprod.polymarketexchange.com`, versus production `https://api.prod.polymarketexchange.com`, with corresponding gRPC hosts and OAuth/private-key-JWT onboarding. Do not combine its credentials or guarantees with the retail gateway/WebSocket API. [Institutional environments](https://docs.polymarket.us/trader-guide/environments).

**D:** Authenticated retail `wss://api.polymarket.us/v1/ws/markets` supplies full, lite and trade subscriptions; up to 100 markets per subscription, multiple subscriptions allowed. “Full” is described as top levels, so it is not proof of uncapped depth. **A:** retail sequence numbers, replay cursors, snapshot/delta replacement and deletion semantics, connection ceiling and resubscription behavior need authenticated validation. Market guide uses camelCase/string enums while the overview includes snake_case/numeric examples: verify the actual wire schema. [Market stream](https://docs.polymarket.us/api-reference/websocket/markets), [WebSocket overview](https://docs.polymarket.us/api-reference/websocket/overview).

The overview documents heartbeat messages and reconnect backoff, but no definite heartbeat interval or gap-free recovery proof was established. Institutional streaming separately promises initial snapshots and at-least-once delivery; its page has conflicting 20-versus-10 stream limits. Those guarantees do not qualify retail WebSockets. [Overview](https://docs.polymarket.us/api-reference/websocket/overview), [institutional streams](https://docs.polymarket.us/trader-guide/streaming-apis).

### Limits, status and usage

**D:** Public REST is limited to 20 requests/second/IP; authenticated REST to 20 requests/second/API key. On 429, wait at least one second and back off. These are documented ceilings, not measured throughput. [US rate limits](https://docs.polymarket.us/api-reference/rate-limits).

Book `transactTime` is an exchange UTC timestamp; metadata `updatedAt` and scheduled `gameStartTime` are different clocks. States include OPEN, PREOPEN, SUSPENDED, HALTED, EXPIRED, TERMINATED and MATCH_AND_CLOSE_AUCTION. **O:** captured book state is OPEN; no suspension transition was observed. **A:** whether quotes persist/change through a halt and what timestamp accompanies each change require verification. A settlement price statistic in an OPEN book is not final event resolution. [Book schema](https://docs.polymarket.us/api-reference/markets/get-market-book).

The US corporate participant agreement identifies QCX LLC/Polymarket US and separately requires institutional production approval/conformance; §I.24 restricts data redistribution. It is an entity agreement, not automatically the applicable retail API contract. **A:** confirm retail scanner/retention terms and any redistribution permission; no account terms were accessed. [US corporate participant agreement, version 1.3, September 4, 2026](https://polymarketexchange.com/files/legal/latest/participant-agreement-corporate).

### Fees

**D:** US schedule effective **July 1, 2026, 00:00 ET**: taker `0.06 × C × p × (1-p)`; maker rebate `0.0125 × C × p × (1-p)`. Round cents using half-to-even. Aggressive-order cumulative exact-fee rounding can reduce later charges; maker rebates round independently per fill. Official examples for 1,000 contracts: p=.10 → $5.40 fee/$1.12 rebate; p=.50 → $15/$3.12; p=.65 → $13.65/$2.84. Prior-calendar-month notional taker-volume tiers give 10%, 25%, 50% taker rebates at $250k, $1m and $10m, paid weekly; do not assume qualification. No separate sports exception or independent settlement levy was identified in this schedule; the latter remains unconfirmed, not assumed zero. [US fees](https://docs.polymarket.us/fees).

**O:** captured moneyline `feeCoefficient=0.06`, consistent with the US schedule. The supplied plan's 0.05 coefficient is not current. Fill allocation, cumulative rounding, account discounts and actual maker eligibility remain **A**; no fills or private fee records were accessed.

### Settlement and blockers

**D:** US sports guidance includes overtime/extra innings by default, $0.50 for two-team ties without a draw outcome, official shortened MLB results, and fair-value cancellation rather than last-trade settlement. Broad postponement guidance refers to the expiration window, often two weeks. **O:** this NFL market instead specifies rescheduling within **two days of the original date**, then last fair market price. Market-specific terms take precedence; this is not identical wording to Kalshi's “begins within 48 hours.” No general listed-pitcher condition was established. [US sports rules](https://docs.polymarket.us/faqs/sports-faqs), [captured specific rules](../evidence/phase-0/pmus-tb-market.json).

**Remaining:** authorized account/key for retail streaming; wire-schema, depth/synchronization and halt tests; applicable data-use terms; exact candidate settlement equivalence; MLB pitcher and market-specific exception verification. Public REST success does not establish continuous-feed readiness.

## 4. Novig

### Actual live path, authentication and depth

**D:** Novig now publishes a live NBX API. Production REST: `https://api.novig.com/nbx/v2`; QA: `https://api-qa.novig.us/nbx/v2`. OAuth client credentials are issued by Novig; tokens last 30 minutes. The current guide obtains tokens through `https://api.novig.com/nbx/v1/auth/emm-token`. **A:** API account class, approval/KYC requirements for read-only access, QA provisioning and production entitlements require owner/venue action. No credentials were requested or used. [REST environments](https://docs.novig.com/api-reference/rest-api), [authentication](https://docs.novig.com/api-reference/authentication).

Discovery: `/emm/events`, `/emm/markets/open`; `/emm/events/getMarketsByEvent/{eventId}` includes markets and current books. `/emm/book/{marketId}` provides `outcomeLadders` with bids by outcome and obfuscated individual orders in price/time priority. **D:** quantities are minimum currency units (CASH cents) of payout, not stake; 100 units represent one $1 contract. Probability prices are 0–1, up to three decimal places. No explicit all-depth cap was located. **A:** live coverage, populated depth, completeness and update latency are not observed. [Events](https://docs.novig.com/api-reference/events/get-events), [open markets](https://docs.novig.com/api-reference/markets/get-open-markets), [markets by event](https://docs.novig.com/api-reference/markets/get-markets-by-event), [book](https://docs.novig.com/api-reference/markets/get-order-book).

The affiliate odds-screen guide also documents authenticated GraphQL ladders, with a payout-versus-stake worked example (45,000 payout units at .36 corresponds to $450 payout and $162 stake). Historical downloads are separate. There are host discrepancies between overview prose and embedded schemas (GraphQL `api.novig.com/v1/graphql` versus `gql.novig.com/v1/graphql`; older OAuth hosts versus current token guide). **A:** confirm the provisioned current hosts; do not probe alternatives or infer anonymous access. [Official affiliate guide](https://docs.novig.com/affiliates/odds-screens).

### Streaming, limits, timestamps and suspension

**D:** `wss://api.novig.com/tape`, QA `wss://api-qa.novig.us/tape`, bearer-authenticated. A market UUID subscription returns initial book data then order-level ticks; the global `tape` stream is updates-only, not bootstrap. PLACE/CANCEL messages describe individual orders; their remaining quantities must not be added as aggregate level deltas. **A:** sequence/replay cursor, atomic snapshot handoff and full-depth completeness remain unknown. `created_at` can describe order placement, not every exchange update's time. [Order-book channel](https://docs.novig.com/api-reference/WSS/orderbook-channel), [WS authentication](https://docs.novig.com/api-reference/WSS/authentication).

Protocol Ping every 15 seconds requires Pong; JSON ping is rejected. Subscriptions are lost on disconnect; back off, authenticate as needed and resubscribe. **A:** token-expiry handling on an established socket and snapshot consistency across reconnects require a real test. [Heartbeat/reconnect](https://docs.novig.com/api-reference/WSS/heartbeat).

Lifecycle includes OPEN/START/END/CLOSE and EVENT_GOLIVE/EVENT_UNLIVE. CLOSE implicitly cancels book orders without individual cancellation messages; going live triggers cancellations and lifecycle ordering matters. Repeated live/unlive transitions can follow delays. Rebuild event state from REST on startup/reconnect. `/emm/locks` exposes system/event locks: an OPEN status alone is insufficient. **A:** authenticated samples must establish exact timestamp quality and suspension-to-book ordering. [Lifecycle](https://docs.novig.com/api-reference/WSS/lifecycle-channel), [lock status](https://docs.novig.com/api-reference/markets/get-lock-status).

Documentation conflicts: REST overview says other/data endpoints 256 requests/second; book/open-market pages say 128; events/markets-by-event pages say 512. Treat endpoint values as documented claims, not reconciled entitlements. 429 headers include `Retry-After` and `X-RateLimit-Reset` in **milliseconds**, unlike conventional HTTP seconds. No numeric WS subscription ceiling was established. **A:** ask which limits govern the provisioned account and verify headers without load testing. [Limits](https://docs.novig.com/api-reference/rest-api), [book](https://docs.novig.com/api-reference/markets/get-order-book), [events](https://docs.novig.com/api-reference/events/get-events).

### Fees and data use

**D:** Current developer schedule gives zero pregame maker/taker fees and live taker `0.03 × C × p × (1-p)`, rounded half-up to five decimal dollars without a minimum. Convert payout cents to contracts first. [API fee mechanics](https://docs.novig.com/fees).

Current help-center table also lists futures coefficient .06 and parlay .10; parlay fees are embedded in quotes and API takers cannot take those orders. Golf/tennis futures are excluded from the futures fee as of September 10, 2026. Official examples: 100 live contracts at .50 → $.75; 100 futures at .15 → $.765, displayed as $.77. The support page describes VWAP across levels; exact aggregation versus per-fill API wording needs clarification. Absolute effective dates for all coefficients are not provided; verification date is not an effective date. No separate settlement charge was established. [Current fee table/examples](https://support.novig.com/en/articles/16195057-fees-on-novig).

A maker-credit program advertises 50% of collected live taker fees and 70% for eligible NFL/NCAAF futures, with seven-day credits and exclusions for separately contracted makers/affiliates. It is not a universal pregame cash rebate. **A:** qualification, redemption and contract-specific charges remain unverified. [Maker-credit program](https://docs.novig.com/maker-credit-program).

The current member agreement restricts reproduction/retransmission/distribution of market and derived data without consent. **A:** confirm intended private scanner/retention permission and whether API access requires membership or another agreement. [Ludlow Exchange/Novig member agreement, §11](https://support.novig.com/en/articles/16075495-ludlow-exchange-llc-member-agreement).

### Settlement and blockers

Use current exchange contract specifications, not older sportsbook-style rules. The official [market-rules notice](https://support.novig.com/en/articles/9612523-market-rules) redirects to the [current contracts index](https://support.novig.com/en/articles/16083642-contracts). The NFL Winner (`NFL-004`) and MLB Winner (`MLB-002`) PDFs linked there were reviewed; their temporary attachment URLs are not durable source links.

**D, NFL Winner:** overtime included; full-game ties settle .50. Scheduling-week and formal-rescheduling provisions coexist with 48-hour start/resumption clauses; postseason can allow 45 days. Cancellation/forfeiture can void to exchange fair value, not necessarily return the original stake. Fair value uses its own external-market/book methodology. **D, MLB Winner:** extra innings included; pitcher changes explicitly do not affect the contract. Official shortened results can count; 48-hour start/resumption provisions have formal-rescheduling and postseason exceptions. **A:** determine the exact listing's tie/void branch and expiration before approving equivalence. These are product-specification findings, not live market samples. [Contract index and linked winner specifications](https://support.novig.com/en/articles/16083642-contracts).

**Remaining:** venue-issued QA/production OAuth credentials and permitted use; current hosts and effective endpoint limits; authenticated NFL/MLB catalog, rules linkage and depth; snapshot/delta/reconnect sequencing and observed latency; live-transition/locks; fee aggregation/eligibility. **Historical files do not fill any of these live-evidence gaps.**

## Common-event candidate and sample limits

**O:** Tampa Bay at Cincinnati, NFL, September 13, 2026 appears on both accessible venues. This is a candidate match, not approved contract equivalence.

| Field | Kalshi | Polymarket US |
|---|---|---|
| Event | `KXNFLGAME-26SEP13TBCIN` | `74905`, `nfl-tb-cin-2026-09-13` |
| Market | `KXNFLGAME-26SEP13TBCIN-TB` (also separate `…-CIN`) | `381958`, `aec-nfl-tb-cin-2026-09-13` |
| Tampa outcome | YES on `…-TB` | Long, side `763430`; Cincinnati short side `763431` |
| Schedule evidence | Title/date; `expected_expiration_time` and `occurrence_datetime` 20:00Z are not verified kickoff | `gameStartTime` 17:00Z |
| Depth | 31 YES bids, 55 NO bids | 27 long bids, 24 long offers |
| Best Tampa bid / offer | .36 × 56,319.28 / implied .37 × 431,362.78 contracts | .3600 × 77,566.0300 / .3650 × 179,882.1500 contracts |
| Exchange book clock | None in REST response | `2026-09-11T21:53:15.642893046Z` |
| Local retrieval UTC | 21:54:26.743674 | 21:53:43.907944 |

The observations were not simultaneous; no opportunity, executable size or latency conclusion follows. The US book timestamp predates receipt by about 28 seconds, which may represent last update age—not transport latency. Catalog tick metadata and subsequent single-market metadata differ; immutable snapshots are needed to distinguish change from stale catalog data. Rules differ on precise postponement/cancellation semantics and venue-determined fair value. **Settlement compatibility remains UNKNOWN.** ProphetX/Novig coverage of this event is not established; official examples/filings were not substituted for live books. No live MLB book was captured; MLB evidence is limited to Kalshi series/fee metadata and official rule documents.

## Verified corrections to the supplied plan

These supersede assumptions for future work without editing the original plan.

| Topic | Correction / qualification |
|---|---|
| Polymarket US fees | US coefficient .06, not .05; US-specific maker rebate and rounding apply. International fees/APIs do not transfer. |
| Kalshi streaming | Authenticated snapshot/delta WebSocket is documented, with sequence fields and optional exchange timestamps. It has not been exercised here. |
| Kalshi fees | Series type/multiplier, scheduled changes **and event overrides** matter; observed MLB multiplier .5. Account-aware fractional rounding supersedes a universal cent ceiling. |
| ProphetX access | Sandbox requires enablement; production has a separate documented host and approval. Channel migration and planned September 16 transport cutover must be checked at access time. |
| ProphetX fees/rules | Net-market-gain commission plus conditional rebates; NFL tie refund differs from .50 settlement. |
| Novig access | Official authenticated live REST/WS depth exists. Historical-only or “no official API” assumptions are outdated; actual access/depth/latency remain unverified. |
| Novig fees | Pregame zero does not mean all products zero; live/futures/parlay conditions and credit eligibility differ. |
| All venues | Published API availability is not authorization for every use. A matching fixture/title is not settlement equivalence. Plan limits, dates, sample prices and latency targets remain provisional unless explicitly verified here. |

## Completion boundary and one next action

**Complete:** public-source reconnaissance for all four venues; documented corrections and access blockers; limited anonymous Kalshi/US NFL captures with provenance; representative official rules. **Partial:** live sample capture (two of four venues, NFL only). **Not complete:** authenticated access, streams/recovery, latency, all-venue common-event evidence, precise fee eligibility, actual applicable access conditions and settlement-equivalence approval. Synthetic Slice 1 is complete; later implementation slices remain not started.

**Single recommended next action:** prepare a bounded Slice 2 Polymarket US retail access/prerequisite review: identify applicable retail terms and establish owner-authorized account/API-key availability before live streaming. Existing public REST observations do not satisfy authenticated streaming prerequisites. Keep institutional and international APIs separate. No Polymarket US integration, account access or new collection began in Slice 1; see the [tracker](../../prediction_arb_next_steps.md).
