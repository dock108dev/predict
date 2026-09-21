# Offline coverage inventory

Input: `evidence/d1-coverage/synthetic-pages.json` (synthetic).
SHA-256: `9029bc323214fef5d64286879883a8bb18d57b551fd4c0263c9976b1f161fe61`.
As of: 2026-09-16T16:00:00+00:00; last retrieval: 2026-09-16T14:00:00+00:00; age: 7200.0 seconds.

**Current full coverage: unavailable.**

- Historical/synthetic inventory only; no new data collected.
- Exhausted applies only to a captured query traversal, not the whole live venue.
- Polymarket embedded markets are not independently proven exhaustive.
- Matching is event identity plus retained market presence, not outcome/contract/settlement equivalence.
- Purchase support is adapter capability, not available liquidity or live qualification.

## kalshi

```json
{
  "events": {
    "discovered": 2,
    "in_scope": 2,
    "excluded": 0,
    "raw_occurrences": 3,
    "duplicates": 1,
    "matching": {
      "matched": 1,
      "unmatched": 1
    },
    "exclusions": {}
  },
  "markets": {
    "discovered": 2,
    "in_scope": 2,
    "excluded": 0,
    "raw_occurrences": 2,
    "duplicates": 0,
    "matching": {
      "matched": 1,
      "unmatched": 1
    },
    "exclusions": {}
  },
  "sides": {
    "supported": 4,
    "unsupported": 0,
    "unknown": 0,
    "total": 4
  },
  "in_scope_sides": {
    "supported": 4
  },
  "events_without_retained_markets": 0,
  "market_discovery": {
    "exhausted": 2
  }
}
```

Active subscriptions: unknown (offline).
Event discovery: exhausted; market completeness: exhausted_for_retained_events.

Discovery:

- `/events` {'series_ticker': 'KXNFLGAME', 'status': 'unopened'}: **exhausted**, terminal empty cursor; 1/1 retained pages used.
- `/events` {'series_ticker': 'KXNFLGAME'}: **exhausted**, terminal empty cursor; 1/1 retained pages used.
- `/markets` {'event_ticker': 'k'}: **exhausted**, terminal empty cursor; 1/1 retained pages used.
- `/markets` {'event_ticker': 'unmatched'}: **exhausted**, terminal empty cursor; 1/1 retained pages used.

| Event ID | Title | Schedule | Identity | Match | Exclusion | Market discovery |
|---|---|---|---|---|---|---|
| k | Detroit vs Buffalo | 2026-09-20T17:00:00+00:00 | resolved | matched | — | exhausted |
| unmatched | Chicago vs Minnesota | 2026-09-20T17:00:00+00:00 | resolved | unmatched | — | exhausted |

| Market ID | Event ID | Type / period / state | Purchase sides | Event match | Exclusion |
|---|---|---|---|---|---|
| km | k | moneyline / full_game / active | yes Detroit (supported); no Not Detroit (supported) | matched | — |
| other | unmatched | moneyline / full_game / active | yes Detroit (supported); no Not Detroit (supported) | unmatched | — |

## polymarket_us

```json
{
  "events": {
    "discovered": 3,
    "in_scope": 3,
    "excluded": 0,
    "raw_occurrences": 3,
    "duplicates": 0,
    "matching": {
      "matched": 1,
      "unmatched": 1,
      "unresolved": 1
    },
    "exclusions": {}
  },
  "markets": {
    "discovered": 3,
    "in_scope": 3,
    "excluded": 0,
    "raw_occurrences": 3,
    "duplicates": 0,
    "matching": {
      "matched": 1,
      "unmatched": 1,
      "unresolved": 1
    },
    "exclusions": {}
  },
  "sides": {
    "supported": 3,
    "unsupported": 3,
    "unknown": 0,
    "total": 6
  },
  "in_scope_sides": {
    "supported": 3,
    "unsupported": 3
  },
  "events_without_retained_markets": 0,
  "market_discovery": {
    "embedded_only": 3
  }
}
```

Active subscriptions: unknown (offline).
Event discovery: exhausted; market completeness: unestablished.

Discovery:

- `/events` {'tagSlug': 'nfl'}: **exhausted**, short offset page (adapter stopping rule); 1/1 retained pages used.

| Event ID | Title | Schedule | Identity | Match | Exclusion | Market discovery |
|---|---|---|---|---|---|---|
| p | fixture | 2026-09-20T17:00:00+00:00 | resolved | matched | — | embedded_only |
| solo | fixture | 2026-09-20T17:00:00+00:00 | resolved | unmatched | — | embedded_only |
| unknown | fixture | 2026-09-20T17:00:00+00:00 | unresolved | unresolved | — | embedded_only |

| Market ID | Event ID | Type / period / state | Purchase sides | Event match | Exclusion |
|---|---|---|---|---|---|
| pm | p | moneyline / full_game / active | pmL Detroit (supported); pmS Buffalo (unsupported) | matched | — |
| solom | solo | moneyline / full_game / active | solomL Detroit (supported); solomS Buffalo (unsupported) | unmatched | — |
| unknownm | unknown | moneyline / full_game / active | unknownmL Detroit (supported); unknownmS Buffalo (unsupported) | unresolved | — |

Full native provenance, participants, terms and counterpart IDs are in the companion JSON report.
