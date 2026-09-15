> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Data Model

> Understanding how Novig structures events, markets, and outcomes

## Overview

Before fetching data from the Novig API, it's important to understand how our markets are structured. Novig uses a hierarchical data model with three levels: Events, Markets, and Outcomes.

## Understanding the Data Model

<Steps>
  <Step title="Event">
    The top-level object representing a game or match, like "KC Chiefs vs BUF Bills - Week 14". Events contain metadata about the competition including teams, scheduled start time, and league.
  </Step>

  <Step title="Market">
    Each event contains a set of related markets. A market is a specific proposition with a `type` (e.g., SPREAD, TOTAL, MONEY) and optional `strike` value. For example, "KC v BUF Total 47.5" is a market.
  </Step>

  <Step title="Outcomes">
    * Each market contains exactly two mutually exclusive, completely exhaustive outcomes identified by `outcomeIds`. These represent the two sides of the trade (e.g., Over/Under, Home/Away). Orders are placed on outcomes, not markets.

    ```json theme={null}
    {
      "id": "abc123-market-uuid",
      "description": "KC v BUF Total",
      "type": "TOTAL",
      "strike": 47.5,
      "outcomeIds": [
        "outcome-uuid-over",
        "outcome-uuid-under"
      ]
    }
    // Outcome 0: Over 47.5 → priced at 0.524
    // Outcome 1: Under 47.5 → priced at 0.524
    ```
  </Step>
</Steps>

## Key Concepts

<CardGroup cols={2}>
  <Card title="Events" icon="calendar">
    Events typically correspond to real-world games or matches. Each event has a unique `eventId` and contains information about the teams, league, and scheduled start time.
  </Card>

  <Card title="Markets" icon="chart-line">
    Markets define what you're trading on. Common types include `MONEY` (moneyline), `SPREAD`, `TOTAL`, and player props like `PASSING_YARDS`.
  </Card>

  <Card title="Outcomes" icon="code-branch">
    Outcomes are the tradeable units. When placing an order, you specify an `outcomeId`, not a market ID. Each market always has exactly two outcomes.
  </Card>

  <Card title="Prices" icon="percent">
    Prices are decimal probabilities (0.001 to 0.999) — the stake per \$1.00 payout. A price of 0.524 means \$0.524 staked to win \$1.00.
  </Card>
</CardGroup>

<Tip>Events, markets, and outcomes may also reference specific players or competitors via optional `playerId` and `competitorId` fields.</Tip>

## Market Types

Novig supports a variety of market types across different sports:

| Type            | Description                    | Example                |
| --------------- | ------------------------------ | ---------------------- |
| `MONEY`         | Moneyline / winner             | Chiefs vs Bills winner |
| `SPREAD`        | Point spread                   | Chiefs -2.5            |
| `TOTAL`         | Over/under on combined score   | Over 47.5              |
| `TEAM_TOTAL`    | Over/under on one team's score | Chiefs Over 24.5       |
| `PASSING_YARDS` | Player passing yards           | Mahomes Over 275.5     |
| `RUSHING_YARDS` | Player rushing yards           | Pacheco Over 65.5      |
| `RECEPTIONS`    | Player receptions              | Kelce Over 5.5         |

<Note>
  For a complete list of market types, see the [API Reference](/api-reference/markets).
</Note>

## Example: Full Event Structure

Here's how a typical NFL game is structured in the API:

```json theme={null}
{
  "event": {
    "id": "event-uuid-123",
    "description": "KC Chiefs vs BUF Bills - Week 14",
    "type": "REGULAR_SEASON",
    "status": "SCHEDULED",
    "game": {
      "id": "game-uuid-456",
      "league": "NFL",
      "scheduledStart": "2024-12-15T20:00:00Z",
      "homeTeam": {
        "name": "Buffalo Bills",
        "symbol": "BUF"
      },
      "awayTeam": {
        "name": "Kansas City Chiefs",
        "symbol": "KC"
      }
    }
  },
  "markets": [
    {
      "id": "market-uuid-spread",
      "description": "KC v BUF Spread",
      "type": "SPREAD",
      "strike": -2.5,
      "outcomeIds": ["outcome-kc-spread", "outcome-buf-spread"]
    },
    {
      "id": "market-uuid-total",
      "description": "KC v BUF Total",
      "type": "TOTAL",
      "strike": 47.5,
      "outcomeIds": ["outcome-over", "outcome-under"]
    }
  ]
}
```
