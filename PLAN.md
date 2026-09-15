Below is the plan I’d use as the working technical spec. It deliberately keeps **data collection, market matching, arb detection, and execution** separate so we can get useful results before touching automated trading.

# Prediction Market Arbitrage Engine

## 1. Objective

Build a real-time system that ingests prediction-market pricing from multiple U.S. venues, identifies economically equivalent contracts, calculates executable arbitrage opportunities using each venue’s actual fee structure and available liquidity, and records enough historical data to determine which opportunities are realistically tradeable.

Initial venues:

1. Kalshi
2. ProphetX
3. Polymarket US
4. Novig

Secondary venues:

5. Crypto.com Predictions
6. Fanatics Markets
7. Additional prediction-only exchanges as APIs/data access become available

The first target is **sports prediction markets**, particularly markets where normalization is deterministic:

- moneyline
- spread
- total

Later expansion:

- player props
- futures
- multi-outcome markets
- politics
- economics
- entertainment
- other binary prediction markets

The first objective is not automated execution. The first objective is to answer:

> How often do real, fee-adjusted, executable cross-market arbs occur, how large are they, how long do they survive, and how much capital could actually be deployed?

---

# 2. Core Design Principles

## 2.1 Stream instead of poll wherever possible

The system should be event-driven.

If a venue offers WebSocket market data, maintain a local copy of its order books and recalculate affected arbitrage pairs whenever an update arrives.

Do not globally poll every venue once per second.

Current situation:

| Venue | Preferred ingestion |
|---|---|
| Kalshi | API market/order-book data; investigate current streaming support as part of adapter implementation |
| ProphetX | WebSocket / Talaria |
| Polymarket US | WebSocket |
| Novig | Direct API if access is available; otherwise external data source |
| Crypto.com | REST polling |
| Fanatics | Likely external data source unless direct market-data access becomes available |

ProphetX specifically supports real-time market/order-book ingestion through its trading API infrastructure and Talaria/WebSocket feeds. 

Polymarket US exposes a WebSocket with order-book, price and trade streams, and recommends streaming rather than continuously polling REST. 

Crypto.com's official prediction API is currently REST based and allows 100 requests/minute and 50,000/day at the public tier. 

---

# 3. High-Level Architecture

```text
                         ┌─────────────────┐
Kalshi ─────────────────>│                 │
ProphetX ────────────────>│ Venue Adapters │
Polymarket US ───────────>│                 │
Novig ───────────────────>│                 │
Crypto.com ──────────────>│                 │
Fanatics ────────────────>│                 │
                         └────────┬────────┘
                                  │
                                  ▼
                         Normalized Market
                              Events
                                  │
                   ┌──────────────┴──────────────┐
                   ▼                             ▼
             Current Books                Raw Storage
                   │
                   ▼
           Canonical Matcher
                   │
                   ▼
            Matched Markets
                   │
                   ▼
              Fee Engine
                   │
                   ▼
             Arb Calculator
                   │
                   ▼
          Execution Simulator
                   │
                   ▼
       Opportunities / History
                   │
          ┌────────┴────────┐
          ▼                 ▼
         API               UI
```

The important boundary is:

**Venue adapters do not determine arbitrage.**

Their only job is turning venue-specific data into a common representation.

---

# 4. Repository Structure

Initial monorepo:

```text
prediction-arb/
    app/
        adapters/
            base.py
            kalshi.py
            prophetx.py
            polymarket_us.py
            novig.py
            crypto.py
            fanatics.py

        models/
            venue.py
            event.py
            market.py
            quote.py
            orderbook.py
            fees.py
            arb.py

        normalization/
            teams.py
            players.py
            leagues.py
            market_types.py
            names.py

        matching/
            event_matcher.py
            market_matcher.py
            rule_matcher.py
            confidence.py

        fees/
            kalshi.py
            prophetx.py
            polymarket.py
            novig.py

        arbitrage/
            binary.py
            multiway.py
            depth.py
            optimizer.py

        execution/
            simulator.py
            sizing.py
            risk.py

        storage/
            postgres.py
            redis.py

        api/
            fastapi.py

        monitoring/
            metrics.py
            logging.py

    tests/
    scripts/
    migrations/
    config/
```

Python is sufficient for the initial version.

The problem is primarily:

- asynchronous I/O
- transformation
- matching
- small numerical calculations

It is not computationally heavy enough to justify another language initially.

---

# 5. Venue Adapter Interface

Every venue implements the same interface.

```python
class VenueAdapter:

    async def discover_events(self):
        ...

    async def discover_markets(self):
        ...

    async def get_snapshot(self, market_id):
        ...

    async def stream_markets(self):
        ...

    async def get_market_rules(self, market_id):
        ...
```

Where supported later:

```python
    async def place_order(self):
        ...

    async def cancel_order(self):
        ...

    async def get_positions(self):
        ...
```

Trading functionality stays entirely separate from data ingestion during the research phase.

---

# 6. Raw Data Preservation

Store the original venue object before normalization.

This is important because we will inevitably discover fields later that matter for matching.

Example:

```text
raw_market
    venue
    external_event_id
    external_market_id
    received_at
    payload_json
```

Do not normalize and discard the source payload.

Raw storage gives us:

- debugging
- replay
- parser improvements
- historical backtesting
- evidence when a matcher produces a bad pair

---

# 7. Canonical Event Model

Every venue event eventually maps to one canonical event.

```text
CanonicalEvent

id

category
sport
league

participant_a
participant_b

scheduled_start

venue_event_ids

status
    scheduled
    live
    completed
    postponed
    canceled
```

Sports example:

```text
event_id:
NFL:2026-09-13:DAL:NYG
```

For MLB:

```text
MLB:2026-09-10:BOS:NYY
```

Canonical IDs should be deterministic where possible.

---

# 8. Entity Normalization

Maintain canonical mappings.

```text
Dallas Cowboys
DAL
Cowboys
Dallas
```

all become:

```text
NFL:DAL
```

Similarly:

```text
New York Yankees
NY Yankees
NYY
Yankees
```

becomes:

```text
MLB:NYY
```

Sources:

- internal static mappings initially
- official league/team identifiers where useful
- venue-specific aliases learned over time

Tables:

```text
entity
entity_alias
venue_entity_mapping
```

Do not rely on repeated fuzzy matching once an alias is known.

---

# 9. Canonical Market Model

A market should represent its economic exposure, not the venue's wording.

```text
CanonicalMarket

event_id

market_type
    MONEYLINE
    SPREAD
    TOTAL
    PLAYER_PROP
    FUTURE
    BINARY

period
    FULL_GAME
    FIRST_HALF
    SECOND_HALF
    FIRST_QUARTER
    FIRST_5_INNINGS
    etc.

subject

line

outcome

settlement_rule_class
```

Example:

```text
event:
MLB:2026-09-10:BOS:NYY

market:
MONEYLINE

period:
FULL_GAME

outcome:
NYY
```

Another:

```text
event:
NFL:2026-09-13:DAL:NYG

market:
SPREAD

subject:
DAL

line:
-3.5

outcome:
DAL
```

---

# 10. Quote Model

Every adapter emits the same object.

```text
Quote

venue
venue_event_id
venue_market_id

canonical_event_id
canonical_market_id

outcome

bid_price
bid_size

ask_price
ask_size

timestamp_exchange
timestamp_received

market_state
```

For full depth:

```text
OrderBook

bids:
    [(price, quantity)]

asks:
    [(price, quantity)]
```

Use `Decimal`, not floating-point arithmetic, for monetary calculations.

---

# 11. Price Representation

Internally everything should use:

```text
0 < price < 1
```

Example:

```text
0.52
```

regardless of whether a venue presents:

- American odds
- decimal odds
- probability
- cents

ProphetX explicitly supports several pricing representations including cents, American odds, decimal odds and probability. 

Normalize immediately.

---

# 12. YES / NO Normalization

Internally attempt to represent every two-outcome market as:

```text
Outcome A
Outcome NOT A
```

or equivalently:

```text
YES
NO
```

This allows:

```text
DAL YES
```

to be recognized as equivalent to:

```text
NYG NO
```

where the settlement rules truly make those complementary.

However, complementarity must not be assumed blindly.

Potential problems:

- tie rules
- overtime rules
- draw/no-action rules
- canceled games
- three-way soccer markets
- pushes

---

# 13. Market Matching

This is likely the most important subsystem.

There are two matching layers.

## Layer 1: Event Matching

For sports:

```text
league
participants
scheduled time
```

should normally identify the event.

Example confidence:

```text
same league             required
same participants       required
start difference < 15m  strong
same calendar date      required
```

Once confirmed, store the mapping permanently.

---

# 14. Market Matching

Within a matched event:

```text
market type
period
subject
side
line
settlement rules
```

must agree.

Example:

```text
DAL -3.5
```

does not match:

```text
DAL -3
```

Likewise:

```text
Full game ML
```

does not match:

```text
First-half ML
```

The canonical market key might be:

```text
NFL:2026-09-13:DAL:NYG
|FULL_GAME
|SPREAD
|DAL
|-3.5
```

---

# 15. Matching Confidence

Use explicit confidence levels.

### Tier A — deterministic

All structured fields agree.

Safe for automatic arb calculation.

### Tier B — high confidence

Minor naming discrepancies exist but identity is extremely likely.

Can display an opportunity but flag the mapping.

### Tier C — candidate

Semantic/fuzzy similarity suggests equivalence.

Requires manual approval.

### Rejected

Important structured terms conflict.

Never calculate an arb.

---

# 16. Role for LLM Matching

An LLM can help identify candidate market mappings when descriptions differ materially.

It should not determine whether money is automatically traded.

Workflow:

```text
new market
    ↓
deterministic matcher
    ↓
unmatched?
    ↓
fuzzy matcher
    ↓
possible candidate?
    ↓
LLM classification
    ↓
human validation
    ↓
permanent deterministic mapping
```

That keeps AI out of the execution-critical path.

---

# 17. Settlement Rule Compatibility

This deserves first-class treatment.

Two markets can look identical while resolving differently.

Potential differences:

- regulation vs overtime
- listed pitchers
- postponed-game treatment
- abandoned-game handling
- official stat source
- stat correction window
- push handling
- tie handling
- event deadline
- qualifying vs winning
- venue-specific cancellation language

Model:

```text
SettlementProfile

includes_overtime
push_behavior
postponement_behavior
cancellation_behavior
official_source
expiration_time
notes
```

Initially classify settlement compatibility as:

```text
EXACT
COMPATIBLE
UNKNOWN
INCOMPATIBLE
```

Only `EXACT` and approved `COMPATIBLE` markets qualify for strong arb alerts.

---

# 18. Current Venue Fee Models

Fees should be executable code, not configuration constants.

## Novig

Current straight pregame trades are fee-free for both maker and taker.

Live taker trades use:

```text
fee =
0.03 × price × (1-price) × contracts
```

Maker fills remain fee-free. 

This makes Novig particularly interesting as an anchor venue for pregame arbitrage.

---

## ProphetX

Current straight trades charge:

```text
2% of net gains per market
```

The current schedule was updated August 19, 2026. 

This is materially different from an entry fee and must be modeled by outcome.

---

## Polymarket US

Current fee:

```text
Taker:
0.05 × contracts × price × (1-price)

Maker rebate:
0.0125 × contracts × price × (1-price)
```

The exchange applies explicit rounding rules. 

---

## Kalshi

Kalshi's general taker formula is:

```text
0.07 × contracts × price × (1-price)
```

and markets that carry maker fees generally use:

```text
0.0175 × contracts × price × (1-price)
```

Some products can have different schedules, so fee selection must be market-aware rather than assuming one universal Kalshi coefficient. 

---

# 19. Fee Engine Interface

```python
class FeeModel:

    def entry_fee(
        self,
        price,
        quantity,
        liquidity_role,
        market
    ) -> Decimal:
        ...

    def settlement_fee(
        self,
        price,
        quantity,
        won,
        market
    ) -> Decimal:
        ...
```

Examples:

```text
NovigPregameFee
NovigLiveFee

ProphetXStraightFee

PolymarketUSTakerFee
PolymarketUSMakerFee

KalshiFee
```

Every returned opportunity must specify exactly which fee models were applied.

---

# 20. Fee Versioning

Fee schedules change.

Therefore:

```text
fee_schedule

venue
effective_from
effective_to
market_type
formula
version
source
```

Arb history must retain the fee version used at calculation time.

Otherwise historical simulations become wrong when an exchange changes pricing.

---

# 21. Basic Binary Arbitrage Calculation

For two complementary contracts:

```text
Outcome A at Venue X
Outcome B at Venue Y
```

calculate:

```text
total_entry_cost
net_settlement_if_A
net_settlement_if_B
```

Then:

```text
profit_if_A =
net_settlement_if_A - total_cost

profit_if_B =
net_settlement_if_B - total_cost
```

Guaranteed profit:

```text
min(profit_if_A, profit_if_B)
```

Guaranteed ROI:

```text
guaranteed_profit / total_cash_required
```

This is the primary metric.

---

# 22. Do Not Use a Generic "Arb Percentage"

The system should distinguish:

```text
raw pricing discrepancy

gross theoretical ROI

fee-adjusted ROI

depth-adjusted ROI

safety-adjusted ROI
```

The number we ultimately care about is:

> Guaranteed executable ROI after known fees at currently available liquidity.

---

# 23. Unequal Stakes

Buying identical contract counts is not necessarily optimal once fees differ.

The engine should solve for stake amounts that maximize the minimum terminal payout.

For outcomes A and B choose:

```text
qA
qB
```

such that:

```text
profit_if_A ≈ profit_if_B
```

subject to:

```text
qA <= available_liquidity_A
qB <= available_liquidity_B
```

This becomes a small optimization problem.

Later it can include:

- fee nonlinearities
- rounding
- minimum contract sizes
- different collateral requirements

---

# 24. Full Order-Book Arb Calculation

Top-of-book is only the first screening step.

Example:

```text
Venue A

0.48 × 100
0.49 × 300
0.50 × 700


Venue B

0.47 × 50
0.48 × 200
0.49 × 500
```

The engine should walk both books simultaneously and calculate marginal arb profitability.

Result:

```text
0-50 contracts       3.4%
51-100               2.8%
101-250              1.7%
251+                  negative
```

Then report:

```text
maximum executable quantity above threshold
maximum expected guaranteed profit
weighted average ROI
```

This is far more meaningful than just comparing BBO.

---

# 25. Opportunity Object

```text
ArbitrageOpportunity

id

canonical_event
canonical_market

legs[]

gross_cost
fees

payout_by_outcome

guaranteed_profit
guaranteed_roi

maximum_size

quote_age

first_seen
last_seen
duration

matching_confidence
settlement_confidence

execution_type
    IMMEDIATE
    MAKER_DEPENDENT

status
```

---

# 26. Immediate vs Maker-Dependent Opportunities

These must never be mixed.

## Immediate

Both sides can be taken against existing liquidity now.

```text
TAKER / TAKER
```

This is the closest thing to genuine executable arbitrage.

## Maker-dependent

At least one leg requires posting an order and waiting.

Examples:

```text
MAKER / TAKER
MAKER / MAKER
```

Potentially attractive, but not guaranteed because the market can move before the resting order fills.

Display separately.

---

# 27. Opportunity Thresholds

Do not hard-code a universal 3.2% threshold.

Instead calculate true net ROI and configure alert thresholds separately.

Initial research thresholds could be:

```text
>= 0.5%    record
>= 1.0%    highlight
>= 2.0%    strong
>= 3.0%    exceptional
```

These thresholds apply **after modeled exchange fees**.

Initially add an execution safety reserve when classifying opportunities.

Example:

```text
true net ROI       2.8%
execution reserve  0.4%
safe ROI           2.4%
```

The reserve is for execution uncertainty, not an invented fee.

---

# 28. Quote Freshness

Every opportunity should track quote age.

```text
venue timestamp
local received timestamp
calculation timestamp
```

Example:

```text
ProphetX     23 ms
Kalshi       118 ms
```

Potential stale-book rule:

```text
>250 ms warning
>1 second unsafe
```

Actual thresholds should be derived from observed behavior rather than guessed.

---

# 29. Clock Synchronization

Server clock needs to be reliable.

Use NTP/system clock sync.

Otherwise latency measurements across adapters become meaningless.

Record both:

```text
exchange timestamp
received timestamp
```

where available.

---

# 30. Data Ingestion Strategy

Each adapter maintains:

```text
market catalog
latest BBO
full book where available
status
last update
```

Flow:

```text
REST snapshot
    ↓
establish websocket
    ↓
subscribe
    ↓
process deltas
    ↓
maintain local book
```

On reconnect:

```text
discard uncertain local state
fetch fresh snapshot
resume deltas
```

Never assume an order book remained synchronized through a disconnected stream.

---

# 31. Polymarket US Adapter

Polymarket US is one of the easiest direct integrations.

Public APIs expose:

- events
- markets
- order books
- BBO
- settlement information

and authenticated WebSockets provide continuous market updates. 

Tasks:

```text
[ ] API credentials
[ ] enumerate sports/events
[ ] retrieve market metadata
[ ] implement websocket authentication
[ ] subscribe to market-data stream
[ ] parse full book
[ ] reconnect/resync
[ ] map sides
[ ] implement fee calculation
```

One subscription supports up to 100 market slugs, so subscription sharding will be needed at scale. 

---

# 32. ProphetX Adapter

ProphetX offers:

- market/event APIs
- trading APIs
- real-time order-book infrastructure
- Talaria/WebSocket streaming
- eventual order submission

Its Trading API is explicitly designed for algorithmic traders and liquidity providers. 

However, production API access is not currently entirely self-service and may require direct onboarding. 

Tasks:

```text
[ ] request/confirm API access
[ ] create sandbox account
[ ] authenticate
[ ] retrieve tournaments
[ ] retrieve events
[ ] retrieve markets
[ ] ingest price ladder
[ ] connect Talaria/WebSocket
[ ] subscribe by event
[ ] build local books
[ ] reconnect/resync
[ ] implement 2%-of-net-gains fee model
```

This should be one of the first integrations because the sports taxonomy should help bootstrap canonical matching.

---

# 33. Kalshi Adapter

Tasks:

```text
[ ] establish authenticated API client
[ ] enumerate events/markets
[ ] retrieve order books
[ ] determine best available streaming mechanism
[ ] normalize YES/NO exposure
[ ] identify market-specific fee schedule
[ ] implement current fee schedule
[ ] cache market metadata
[ ] reconcile market settlement rules
```

Kalshi provides market and order-book data through its API. 

The fee subsystem must explicitly support product-specific fee variations. 

---

# 34. Novig Adapter

Novig is currently the largest data-access question.

Publicly documented exchange files provide historical trades and market information but are not sufficient for a live arb scanner. 

Tasks:

```text
[ ] determine official API availability for account
[ ] request direct API access if necessary
[ ] evaluate realtime third-party source
[ ] enumerate events
[ ] enumerate markets
[ ] validate latency
[ ] validate order-book depth
[ ] implement historical-data importer
[ ] implement Novig fee models
```

The historical files are still valuable for:

- market taxonomy
- event-name normalization
- liquidity analysis
- validating pricing behavior

---

# 35. Crypto.com Predictions Adapter

Useful additional venue because the official data API requires no authentication for personal noncommercial usage.

Available APIs include:

- event enumeration
- search
- contract enumeration
- contract pricing 


Problem:

```text
100 requests/minute
50,000 requests/day
```

means we cannot naively poll every contract every second. 

Strategy:

```text
poll event catalog slowly
identify contracts matching our tracked events
poll only relevant active contracts
prioritize contracts where another venue has active pricing
```

This can function as a secondary opportunity source rather than a primary streaming venue.

---

# 36. Fanatics Markets

Treat Fanatics as a secondary adapter initially.

Tasks:

```text
[ ] determine whether direct market-data access exists
[ ] investigate underlying contract identifiers
[ ] evaluate third-party feeds
[ ] compare overlap against Crypto.com
[ ] determine whether exposure is actually independent
```

A key question is whether Fanatics and Crypto.com represent sufficiently independent executable liquidity to count as separate arb legs rather than different front ends around related infrastructure.

Do not assume they are independent until verified.

---

# 37. Database Design

## PostgreSQL

Use for durable relationships/history.

Tables:

```text
venues

raw_events
raw_markets

canonical_entities
entity_aliases

canonical_events
event_mappings

canonical_markets
market_mappings

settlement_profiles

fee_schedules

quotes_history

arbitrage_opportunities

arb_legs
```

---

# 38. Redis

Use Redis for transient current state:

```text
current market metadata
current BBO
current order books
matched-market indexes
active opportunities
```

Do not make Redis the historical source of truth.

---

# 39. Historical Quote Storage

Potentially enormous.

Do not blindly write every order-book message into PostgreSQL forever.

Start with:

```text
every BBO change
every detected arb
full book around arb events
periodic snapshots
```

Potential later options:

- TimescaleDB
- ClickHouse
- Parquet object storage

We can decide after measuring data volume.

---

# 40. Arb-Triggered Capture

Whenever an arb crosses a threshold:

capture:

```text
full books from both venues
raw payloads
fee calculations
matching metadata
timestamps
```

Then continue recording until the opportunity disappears.

This creates a perfect research dataset without storing every book update forever.

---

# 41. Replay Engine

Build ingestion events so they can be replayed.

```text
historical messages
        ↓
same normalizer
        ↓
same matcher
        ↓
same arb engine
```

This makes it possible to:

- test algorithm changes
- compare thresholds
- validate fee fixes
- reproduce false positives
- simulate execution

without waiting for another Sunday.

---

# 42. Execution Simulation

Before real automated execution, simulate fills.

For every opportunity:

```text
signal time
assumed decision latency
assumed order send latency
book at theoretical arrival
```

Calculate:

```text
would both legs still fill?
what quantity?
what final ROI?
```

Eventually we can derive a realistic latency penalty from actual data instead of choosing an arbitrary safety percentage.

---

# 43. Partial-Fill Risk

This is probably the biggest practical risk.

Example:

```text
buy leg A
filled

buy leg B
price disappears
```

You no longer have an arb.

You have a directional position.

Therefore automated trading requires explicit policy.

Possible strategies:

### Strategy A
Use fill-or-kill on both venues where supported.

### Strategy B
Submit least-liquid leg first.

### Strategy C
Submit faster/more reliable venue second.

### Strategy D
Allow hedge slippage up to predefined loss.

### Strategy E
Do not automate until venue execution characteristics are well measured.

For the MVP:

**simulation only.**

---

# 44. Capital Allocation

Eventually maintain:

```text
venue available balance
venue reserved balance
outstanding orders
open positions
settlement timing
```

An opportunity is only executable if enough capital already exists on both venues.

Cross-venue capital movement cannot be part of a time-sensitive trade.

Therefore capital allocation becomes an optimization problem:

```text
How much cash should sit at each exchange based on observed opportunity frequency and size?
```

That can be solved later from historical arb data.

---

# 45. Settlement Delay / Capital Efficiency

Two opportunities with identical ROI are not necessarily equivalent.

Example:

```text
2% return settling tonight
```

is materially different from:

```text
2% return settling three months from now
```

Eventually calculate:

```text
ROI
time to expected settlement
capital-hours locked
```

Useful ranking metric:

```text
profit / capital / expected lock duration
```

For sports, this is naturally favorable because settlement is usually fast.

---

# 46. Market Status Controls

Never trigger on:

```text
closed
halted
suspended
expired
settled
```

Also detect:

```text
venue A active
venue B suspended
```

which can create spectacular-looking fake arbs.

Polymarket US explicitly exposes states including open, suspended, halted, expired and terminated. 

---

# 47. Event Start Controls

Initially focus on:

```text
PRE-GAME
```

Benefits:

- simpler settlement matching
- lower update velocity
- easier execution
- Novig pregame fee advantage
- fewer suspension races

Add live markets as a distinct Phase 2/3 capability.

Do not silently combine live and pregame calculations.

---

# 48. Market Universe Discovery

Run a slower background catalog process.

Example:

```text
every 1-5 minutes:
    refresh active events
    refresh market listings
    identify new markets
    canonicalize
    create subscriptions
```

Price streaming remains continuous.

Market discovery does not need millisecond speed.

---

# 49. Subscription Prioritization

If venue limits become problematic, prioritize markets where cross-venue overlap exists.

Example:

```text
Kalshi says Yankees/Boston exists
ProphetX has same event

=> high-priority subscriptions
```

A unique obscure contract existing on only one venue has no current arbitrage value.

---

# 50. Opportunity UI

First dashboard:

```text
EVENT
MARKET

VENUE A
OUTCOME
PRICE
SIZE

VENUE B
OUTCOME
PRICE
SIZE

RAW GAP
FEES
NET ROI

MAX SIZE
MAX PROFIT

AGE
DURATION

MATCH CONFIDENCE
SETTLEMENT CONFIDENCE
```

Sort by:

```text
guaranteed profit
net ROI
duration
maximum size
```

---

# 51. Example

```text
Yankees @ Red Sox
Full Game Moneyline

BUY NYY
Novig
0.47
$420 available

BUY BOS
ProphetX
0.50
$610 available


Entry cost:
$0.97 / paired exposure

Novig fees:
$0.00

ProphetX modeled settlement fee:
calculated per current schedule

Worst-case payout:
$X

Net guaranteed ROI:
2.XX%

Max profitable size:
$420 equivalent

First seen:
19:31:24.221

Current duration:
2.4 sec

Match:
Tier A

Settlement:
Compatible
```

---

# 52. Alerting

Initially don't alert on every tiny arb.

Possible conditions:

```text
net ROI >= 1%
AND
max profit >= $10
AND
match confidence = Tier A
AND
settlement compatible
AND
quotes fresh
```

Log everything lower for research.

Later tune using actual opportunity frequency.

---

# 53. Metrics

Capture operational metrics:

```text
messages/sec by venue

stream disconnects
reconnects

quote latency

markets tracked
markets matched
match percentage

arbs detected
arbs by venue pair

average arb duration
median arb duration

arb ROI distribution

arb depth distribution

potential profit/day

false-positive count
```

The research metrics matter at least as much as system uptime initially.

---

# 54. Venue Pair Analysis

Track results separately.

Example:

```text
Novig ↔ ProphetX
Novig ↔ Kalshi
Novig ↔ Polymarket

ProphetX ↔ Kalshi
ProphetX ↔ Polymarket

Kalshi ↔ Polymarket
```

We want to discover where pricing actually diverges.

It is entirely possible that 80% of practical opportunities occur between only two venue pairs.

If so, development effort should follow the money rather than adding twenty exchanges.

---

# 55. Opportunity Duration

For each arb:

```text
first_detected
last_detected
maximum_roi
minimum_roi
maximum_size
```

Produce distributions:

```text
<100 ms
100-250 ms
250-500 ms
0.5-1 sec
1-3 sec
3-10 sec
10+ sec
```

This determines whether manual trading, semi-automation or full automation is realistic.

---

# 56. False-Arb Classification

Every apparent arb that proves invalid should get a reason.

Examples:

```text
STALE_QUOTE
BAD_MARKET_MATCH
SETTLEMENT_MISMATCH
INSUFFICIENT_DEPTH
SUSPENDED_MARKET
FEE_ERROR
ROUNDING_ERROR
PARTIAL_BOOK
EVENT_TIME_MISMATCH
```

That becomes our matcher/risk backlog.

---

# 57. Testing

## Unit tests

Fee functions:

```text
known price
known quantity
expected fee
```

Matching:

```text
same team aliases
different lines
different periods
reversed participants
```

Arb math:

```text
equal stakes
unequal fees
unequal liquidity
depth walking
```

---

# 58. Golden Dataset

Create manually verified examples for:

```text
same market
different market
compatible rules
incompatible rules
```

Every matcher change runs against this dataset.

This is critical because false positives are more dangerous than missed matches.

---

# 59. Integration Tests

Per venue:

```text
connect
discover event
discover market
get book
receive update
reconnect
resnapshot
normalize correctly
```

Where sandboxes exist, use them.

ProphetX explicitly offers sandbox integration for API development. 

---

# 60. Secrets

Credentials only through environment/secret management.

```text
KALSHI_KEY
PROPHETX_KEY
POLYMARKET_KEY
...
```

Never place trading credentials in:

- source code
- browser UI
- logs
- raw message storage

Read-only and trading credentials should be separate where the venue supports it.

---

# 61. Compliance / Venue Rules

Before moving from personal analysis into automated trading, verify for each venue:

```text
API trading allowed
automation allowed
rate limits
data usage restrictions
geolocation requirements
account restrictions
market-data licensing
```

For example, ProphetX's documented direct integration requires geolocation checks before order entry. 

Crypto.com's public market-data access is expressly for personal, non-commercial usage unless separately licensed. 

This should be considered an engineering constraint, not paperwork to discover after implementation.

---

# 62. MVP Scope

The MVP should deliberately be narrow.

### Venues

```text
Kalshi
ProphetX
Polymarket US
Novig
```

Crypto.com comes immediately after if integration is trivial.

Fanatics follows once its data path is validated.

### Sports

```text
NFL
NCAAF
MLB
NBA
NHL
```

### Markets

Start with:

```text
moneyline
```

Then:

```text
spread
total
```

No player props in the first pass.

---

# 63. Phase 0 — Access and Reconnaissance

Tasks:

```text
[ ] establish accounts/access

[ ] verify Kalshi API access
[ ] verify ProphetX sandbox/API access
[ ] verify Polymarket US API access
[ ] determine Novig realtime path

[ ] document rate limits
[ ] document auth
[ ] document streaming support
[ ] document market discovery endpoints
[ ] document order-book format

[ ] confirm current fees directly from official sources
[ ] record current fee schedule/version

[ ] pull representative NFL/MLB markets from each venue
```

Deliverable:

A JSON dump showing the same sporting event from every available venue.

---

# 64. Phase 1 — Read-Only Venue Adapters

Implement:

```text
ProphetX
Polymarket US
Kalshi
Novig
```

Each must output:

```text
events
markets
BBO
depth
timestamps
status
```

No cross-market matching yet.

Deliverable:

A unified screen showing raw current markets from every venue.

---

# 65. Phase 2 — Canonical Sports Model

Implement:

```text
leagues
teams
events
moneyline mapping
```

Goal:

```text
Yankees @ Red Sox
```

appears once with all venue listings attached.

Deliverable:

```text
Canonical Event
    Kalshi markets
    ProphetX markets
    Polymarket markets
    Novig markets
```

---

# 66. Phase 3 — Fee Engine

Implement every venue's actual fee calculation.

Build automated test cases from official examples.

Deliverable:

For any potential order:

```text
price
quantity
liquidity role
entry fee
settlement fee
net return
```

---

# 67. Phase 4 — Moneyline Arb Engine

Implement complementary outcome comparison.

Every book update:

```text
normalize
update cache
identify matched markets
calculate fee-adjusted opportunity
calculate available depth
persist result
```

Deliverable:

Live table of genuine fee-adjusted moneyline arbs.

This is the first point where we'll learn whether the idea has practical value.

---

# 68. Phase 5 — Historical Analysis

Run continuously for enough sporting cycles to quantify:

```text
arbs/day
venue pairs
median duration
median ROI
median available capital
theoretical profit/day
```

The primary decision becomes:

> Are there enough durable opportunities to justify execution engineering?

---

# 69. Phase 6 — Spread and Total Support

Add canonical:

```text
line
period
push behavior
```

Matcher complexity increases substantially here.

Test heavily around:

```text
-3 vs -3.5
8 vs 8.5
pushes
alternate lines
```

---

# 70. Phase 7 — Execution Simulator

Without placing trades:

```text
detect arb
simulate decision latency
simulate orders
inspect subsequent books
estimate fills
```

Run multiple hypothetical latency assumptions:

```text
50 ms
100 ms
250 ms
500 ms
1 sec
manual ~5 sec
```

This tells us whether actual automation is necessary.

---

# 71. Phase 8 — Optional Assisted Execution

Potential intermediate step:

```text
ARB FOUND

[Open Novig]
[Open ProphetX]
```

with exact:

```text
market
side
quantity
price
```

No autonomous orders.

Useful if opportunities commonly survive several seconds.

---

# 72. Phase 9 — Automated Execution

Only pursue after proving:

```text
opportunity frequency
latency requirements
fill behavior
fee accuracy
capital requirements
venue API rules
```

Components then needed:

```text
balance service
position service
order router
fill monitor
hedge recovery
kill switch
daily exposure limits
venue limits
audit log
```

---

# 73. Kill Switches

If automated trading is eventually enabled:

Global:

```text
TRADING_ENABLED=false
```

Per venue:

```text
KALSHI_ENABLED=false
```

Per strategy:

```text
LIVE_MARKETS_ENABLED=false
```

Automatic disable conditions:

```text
stream disconnected
book stale
fee schedule unknown
position mismatch
balance mismatch
excessive API errors
abnormal fill behavior
```

---

# 74. Major Unknowns

These should remain explicit rather than being hand-waved away.

## Novig live market data

Need reliable real-time access.

This is probably the largest immediate integration question.

## ProphetX production access

API infrastructure clearly exists, but production access requires onboarding rather than simple anonymous signup. 

## Kalshi streaming architecture

Need to confirm current best production method and actual usable update latency.

## Fanatics independence

Need to determine whether its market liquidity provides genuinely separate arb opportunities relative to Crypto.com infrastructure.

## Settlement differences

Could eliminate a meaningful percentage of apparent matches.

## Real execution latency

Impossible to know from documentation.

Must be measured.

## Partial fills

Could dominate actual profitability.

## Capital fragmentation

Money sitting across six exchanges has an opportunity cost.

---

# 75. Decisions We Should Make Now

### Language

Python.

### Architecture

Async/event-driven.

### Primary store

PostgreSQL.

### Live state

Redis.

### Internal price format

Decimal probability `0–1`.

### First market

Sports moneyline.

### First trading mode

Read-only.

### Fees

Actual venue-specific fee models.

### Matching

Deterministic whenever possible.

### LLM usage

Candidate discovery only.

### Opportunity calculation

Depth-aware and outcome-aware.

### Automation

Deferred until measured data justifies it.

---

# 76. Decisions We Should NOT Make Yet

Do not prematurely decide:

```text
exact automated-trading threshold

capital allocation per exchange

ideal cloud hosting

microservice boundaries

whether Rust/Go is needed

player-prop taxonomy

non-sports taxonomy

maker strategy

optimal execution order

smart-order routing

machine-learning matching

commercialization
```

We need actual market behavior first.

---

# 77. First Practical Build Sequence

I would implement in this exact order:

### Slice 1
Shared models and adapter interface.

### Slice 2
Polymarket US ingestion.

### Slice 3
ProphetX ingestion.

### Slice 4
Kalshi ingestion.

### Slice 5
Novig data-access solution.

### Slice 6
Team/league normalization.

### Slice 7
Canonical event matcher.

### Slice 8
Moneyline market matcher.

### Slice 9
Fee engine.

### Slice 10
Top-of-book arb detection.

### Slice 11
Full-depth arb calculation.

### Slice 12
PostgreSQL historical capture.

### Slice 13
Simple live dashboard.

### Slice 14
Crypto.com adapter.

### Slice 15
Fanatics investigation/adapter.

### Slice 16
Execution replay/simulator.

Only after those results:

### Slice 17+
Actual trading.

---

# 78. Definition of MVP Success

The MVP is successful if we can open a dashboard during a sports day and reliably see:

```text
all equivalent moneyline markets

actual executable prices

available quantity

actual venue fees

net guaranteed ROI

maximum executable profit

quote freshness

opportunity duration
```

and then answer quantitatively:

```text
How many opportunities occurred?

Which venue pairs produced them?

How large were they?

How much capital could be deployed?

How long did they survive?

Would a human have had time?

Would a 250-ms bot have filled them?

What would theoretical daily/weekly profit have been?
```

At that point we make the only important next decision:

> Is there enough real edge to justify connecting the order APIs?

Everything before that is relatively cheap engineering and produces useful data even if the answer ends up being no.

The part I would be most strict about is **not building execution early**. The first genuinely valuable milestone is the moneyline scanner with real fee calculations and historical duration/depth. Once that runs through a couple of busy NFL/NCAAF weekends, we'll know whether we're looking at a software project that can make money or a very elaborate dashboard documenting efficient markets.