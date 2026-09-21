# Offline coverage inventory

Input: `evidence/multi-game/sessions/5accf9ee-94b9-4b09-8130-6849f842155e/saved-observations.json` (historical retained capture).
SHA-256: `3c1140c9b82912df9148afd22699dc3fcf047eeb75e6159d5342c4b73e4178d7`.
As of: 2026-09-16T16:00:00+00:00; last retrieval: 2026-09-16T14:57:21.076456+00:00; age: 3758.923544 seconds.

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
    "discovered": 32,
    "in_scope": 32,
    "excluded": 0,
    "raw_occurrences": 32,
    "duplicates": 0,
    "matching": {
      "matched": 32
    },
    "exclusions": {}
  },
  "markets": {
    "discovered": 12,
    "in_scope": 12,
    "excluded": 0,
    "raw_occurrences": 12,
    "duplicates": 0,
    "matching": {
      "matched": 12
    },
    "exclusions": {}
  },
  "sides": {
    "supported": 24,
    "unsupported": 0,
    "unknown": 0,
    "total": 24
  },
  "in_scope_sides": {
    "supported": 24
  },
  "events_without_retained_markets": 26,
  "market_discovery": {
    "exhausted": 6,
    "unknown": 26
  }
}
```

Active subscriptions: unknown (offline).
Event discovery: exhausted; market completeness: unestablished.

Discovery:

- `/trade-api/v2/events` {'series_ticker': 'KXNFLGAME', 'status': 'open', 'with_milestones': 'true'}: **exhausted**, terminal empty cursor; 1/1 retained pages used.
- `/trade-api/v2/markets` {'event_ticker': 'KXNFLGAME-26SEP17DETBUF'}: **exhausted**, terminal empty cursor; 1/1 retained pages used.
- `/trade-api/v2/markets` {'event_ticker': 'KXNFLGAME-26SEP20CARATL'}: **exhausted**, terminal empty cursor; 1/1 retained pages used.
- `/trade-api/v2/markets` {'event_ticker': 'KXNFLGAME-26SEP20CINHOU'}: **exhausted**, terminal empty cursor; 1/1 retained pages used.
- `/trade-api/v2/markets` {'event_ticker': 'KXNFLGAME-26SEP20CLETB'}: **exhausted**, terminal empty cursor; 1/1 retained pages used.
- `/trade-api/v2/markets` {'event_ticker': 'KXNFLGAME-26SEP20MINCHI'}: **exhausted**, terminal empty cursor; 1/1 retained pages used.
- `/trade-api/v2/markets` {'event_ticker': 'KXNFLGAME-26SEP20NOBAL'}: **exhausted**, terminal empty cursor; 1/1 retained pages used.

Historical collection: 1 subscription request(s); 6 markets with retained books; stream closed=True at 2026-09-16T14:57:30.403117+00:00.

| Event ID | Title | Schedule | Identity | Match | Exclusion | Market discovery |
|---|---|---|---|---|---|---|
| KXNFLGAME-26SEP17DETBUF | DET Lions vs BUF Bills | 2026-09-18T00:15:00+00:00 | resolved | matched | — | exhausted |
| KXNFLGAME-26SEP20CARATL | CAR Panthers vs ATL Falcons | 2026-09-20T17:00:00+00:00 | resolved | matched | — | exhausted |
| KXNFLGAME-26SEP20CINHOU | CIN Bengals vs HOU Texans | 2026-09-20T17:00:00+00:00 | resolved | matched | — | exhausted |
| KXNFLGAME-26SEP20CLETB | CLE Browns vs TB Buccaneers | 2026-09-20T17:00:00+00:00 | resolved | matched | — | exhausted |
| KXNFLGAME-26SEP20GBNYJ | GB Packers vs NY Jets | 2026-09-20T17:00:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP20INDKC | IND Colts vs KC Chiefs | 2026-09-21T00:20:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP20JACDEN | JAC Jaguars vs DEN Broncos | 2026-09-20T20:05:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP20LVLAC | LV Raiders vs LA Chargers | 2026-09-20T20:05:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP20MIASF | MIA Dolphins vs SF 49ers | 2026-09-20T20:25:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP20MINCHI | MIN Vikings vs CHI Bears | 2026-09-20T17:00:00+00:00 | resolved | matched | — | exhausted |
| KXNFLGAME-26SEP20NOBAL | NO Saints vs BAL Ravens | 2026-09-20T17:00:00+00:00 | resolved | matched | — | exhausted |
| KXNFLGAME-26SEP20PHITEN | PHI Eagles vs TEN Titans | 2026-09-20T17:00:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP20PITNE | PIT Steelers vs NE Patriots | 2026-09-20T17:00:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP20SEAARI | SEA Seahawks vs ARI Cardinals | 2026-09-20T20:25:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP20WASDAL | WAS Commanders vs DAL Cowboys | 2026-09-20T20:25:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP21NYGLAR | NY Giants vs LA Rams | 2026-09-22T00:15:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP24ATLGB | Atlanta vs Green Bay | 2026-09-25T00:15:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP27ARISF | Arizona vs San Francisco | 2026-09-27T20:05:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP27BALDAL | Baltimore vs Dallas | 2026-09-27T20:25:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP27CARCLE | Carolina vs Cleveland | 2026-09-27T17:00:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP27CINPIT | Cincinnati vs Pittsburgh | 2026-09-27T17:00:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP27HOUIND | Houston vs Indianapolis | 2026-09-27T17:00:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP27KCMIA | Kansas City vs Miami | 2026-09-27T17:00:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP27LACBUF | Los Angeles C vs Buffalo | 2026-09-27T17:00:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP27LARDEN | Los Angeles R vs Denver | 2026-09-28T00:20:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP27LVNO | Las Vegas vs New Orleans | 2026-09-27T20:25:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP27MINTB | Minnesota vs Tampa Bay | 2026-09-27T20:05:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP27NEJAC | New England vs Jacksonville | 2026-09-27T17:00:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP27NYJDET | New York J vs Detroit | 2026-09-27T17:00:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP27SEAWAS | Seattle vs Washington | 2026-09-27T17:00:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP27TENNYG | Tennessee vs New York G | 2026-09-27T17:00:00+00:00 | resolved | matched | — | unknown |
| KXNFLGAME-26SEP28PHICHI | Philadelphia vs Chicago | 2026-09-29T00:15:00+00:00 | resolved | matched | — | unknown |

| Market ID | Event ID | Type / period / state | Purchase sides | Event match | Exclusion |
|---|---|---|---|---|---|
| KXNFLGAME-26SEP17DETBUF-BUF | KXNFLGAME-26SEP17DETBUF | moneyline / full_game / active | yes Buffalo (supported); no Buffalo (supported) | matched | — |
| KXNFLGAME-26SEP17DETBUF-DET | KXNFLGAME-26SEP17DETBUF | moneyline / full_game / active | yes Detroit (supported); no Detroit (supported) | matched | — |
| KXNFLGAME-26SEP20CARATL-ATL | KXNFLGAME-26SEP20CARATL | moneyline / full_game / active | yes Atlanta (supported); no Atlanta (supported) | matched | — |
| KXNFLGAME-26SEP20CARATL-CAR | KXNFLGAME-26SEP20CARATL | moneyline / full_game / active | yes Carolina (supported); no Carolina (supported) | matched | — |
| KXNFLGAME-26SEP20CINHOU-CIN | KXNFLGAME-26SEP20CINHOU | moneyline / full_game / active | yes Cincinnati (supported); no Cincinnati (supported) | matched | — |
| KXNFLGAME-26SEP20CINHOU-HOU | KXNFLGAME-26SEP20CINHOU | moneyline / full_game / active | yes Houston (supported); no Houston (supported) | matched | — |
| KXNFLGAME-26SEP20CLETB-CLE | KXNFLGAME-26SEP20CLETB | moneyline / full_game / active | yes Cleveland (supported); no Cleveland (supported) | matched | — |
| KXNFLGAME-26SEP20CLETB-TB | KXNFLGAME-26SEP20CLETB | moneyline / full_game / active | yes Tampa Bay (supported); no Tampa Bay (supported) | matched | — |
| KXNFLGAME-26SEP20MINCHI-CHI | KXNFLGAME-26SEP20MINCHI | moneyline / full_game / active | yes Chicago (supported); no Chicago (supported) | matched | — |
| KXNFLGAME-26SEP20MINCHI-MIN | KXNFLGAME-26SEP20MINCHI | moneyline / full_game / active | yes Minnesota (supported); no Minnesota (supported) | matched | — |
| KXNFLGAME-26SEP20NOBAL-BAL | KXNFLGAME-26SEP20NOBAL | moneyline / full_game / active | yes Baltimore (supported); no Baltimore (supported) | matched | — |
| KXNFLGAME-26SEP20NOBAL-NO | KXNFLGAME-26SEP20NOBAL | moneyline / full_game / active | yes New Orleans (supported); no New Orleans (supported) | matched | — |

## polymarket_us

```json
{
  "events": {
    "discovered": 32,
    "in_scope": 32,
    "excluded": 0,
    "raw_occurrences": 32,
    "duplicates": 0,
    "matching": {
      "matched": 32
    },
    "exclusions": {}
  },
  "markets": {
    "discovered": 32,
    "in_scope": 32,
    "excluded": 0,
    "raw_occurrences": 32,
    "duplicates": 0,
    "matching": {
      "matched": 6,
      "unmatched_missing_market": 26
    },
    "exclusions": {}
  },
  "sides": {
    "supported": 32,
    "unsupported": 32,
    "unknown": 0,
    "total": 64
  },
  "in_scope_sides": {
    "supported": 32,
    "unsupported": 32
  },
  "events_without_retained_markets": 0,
  "market_discovery": {
    "embedded_only": 32
  }
}
```

Active subscriptions: unknown (offline).
Event discovery: exhausted; market completeness: unestablished.

Discovery:

- `/v1/events` {'active': 'true', 'closed': 'false', 'orderBy': 'startTime', 'orderDirection': 'asc', 'sportsMarketTypes': 'football_team_full_game_winner', 'tagSlug': 'nfl'}: **exhausted**, short offset page (adapter stopping rule); 7/7 retained pages used.

Historical collection: 1 subscription request(s); 6 markets with retained books; stream closed=True at 2026-09-16T14:57:30.403381+00:00.

| Event ID | Title | Schedule | Identity | Match | Exclusion | Market discovery |
|---|---|---|---|---|---|---|
| 101466 | DET Lions vs BUF Bills | 2026-09-18T00:15:00+00:00 | resolved | matched | — | embedded_only |
| 101467 | PHI Eagles vs TEN Titans | 2026-09-20T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 101468 | PIT Steelers vs NE Patriots | 2026-09-20T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 101469 | MIN Vikings vs CHI Bears | 2026-09-20T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 101470 | CAR Panthers vs ATL Falcons | 2026-09-20T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 101471 | GB Packers vs NY Jets | 2026-09-20T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 101472 | NO Saints vs BAL Ravens | 2026-09-20T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 101473 | CIN Bengals vs HOU Texans | 2026-09-20T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 101474 | CLE Browns vs TB Buccaneers | 2026-09-20T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 101475 | JAC Jaguars vs DEN Broncos | 2026-09-20T20:05:00+00:00 | resolved | matched | — | embedded_only |
| 101476 | LV Raiders vs LA Chargers | 2026-09-20T20:05:00+00:00 | resolved | matched | — | embedded_only |
| 101477 | SEA Seahawks vs ARI Cardinals | 2026-09-20T20:25:00+00:00 | resolved | matched | — | embedded_only |
| 101478 | MIA Dolphins vs SF 49ers | 2026-09-20T20:25:00+00:00 | resolved | matched | — | embedded_only |
| 101479 | WAS Commanders vs DAL Cowboys | 2026-09-20T20:25:00+00:00 | resolved | matched | — | embedded_only |
| 101480 | IND Colts vs KC Chiefs | 2026-09-21T00:20:00+00:00 | resolved | matched | — | embedded_only |
| 101481 | NY Giants vs LA Rams | 2026-09-22T00:15:00+00:00 | resolved | matched | — | embedded_only |
| 108683 | ATL Falcons vs GB Packers | 2026-09-25T00:15:00+00:00 | resolved | matched | — | embedded_only |
| 111297 | KC Chiefs vs MIA Dolphins | 2026-09-27T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 111298 | CAR Panthers vs CLE Browns | 2026-09-27T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 111299 | TEN Titans vs NY Giants | 2026-09-27T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 111300 | NE Patriots vs JAC Jaguars | 2026-09-27T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 111301 | LA Chargers vs BUF Bills | 2026-09-27T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 111302 | NY Jets vs DET Lions | 2026-09-27T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 111303 | HOU Texans vs IND Colts | 2026-09-27T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 111305 | SEA Seahawks vs WAS Commanders | 2026-09-27T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 111306 | CIN Bengals vs PIT Steelers | 2026-09-27T17:00:00+00:00 | resolved | matched | — | embedded_only |
| 111307 | ARI Cardinals vs SF 49ers | 2026-09-27T20:05:00+00:00 | resolved | matched | — | embedded_only |
| 111309 | MIN Vikings vs TB Buccaneers | 2026-09-27T20:05:00+00:00 | resolved | matched | — | embedded_only |
| 111310 | LV Raiders vs NO Saints | 2026-09-27T20:25:00+00:00 | resolved | matched | — | embedded_only |
| 111311 | BAL Ravens vs DAL Cowboys | 2026-09-27T20:25:00+00:00 | resolved | matched | — | embedded_only |
| 111312 | LA Rams vs DEN Broncos | 2026-09-28T00:20:00+00:00 | resolved | matched | — | embedded_only |
| 112325 | PHI Eagles vs. CHI Bears | 2026-09-29T00:15:00+00:00 | resolved | matched | — | embedded_only |

| Market ID | Event ID | Type / period / state | Purchase sides | Event match | Exclusion |
|---|---|---|---|---|---|
| 657964 | 101466 | moneyline / full_game / active | 1315440 Lions (supported); 1315441 Bills (unsupported) | matched | — |
| 657966 | 101467 | moneyline / full_game / active | 1315444 Eagles (supported); 1315445 Titans (unsupported) | unmatched_missing_market | — |
| 657969 | 101468 | moneyline / full_game / active | 1315450 Steelers (supported); 1315451 Patriots (unsupported) | unmatched_missing_market | — |
| 657972 | 101469 | moneyline / full_game / active | 1315456 Vikings (supported); 1315457 Bears (unsupported) | matched | — |
| 657975 | 101470 | moneyline / full_game / active | 1315462 Panthers (supported); 1315463 Falcons (unsupported) | matched | — |
| 657978 | 101471 | moneyline / full_game / active | 1315468 Packers (supported); 1315469 Jets (unsupported) | unmatched_missing_market | — |
| 657980 | 101472 | moneyline / full_game / active | 1315472 Saints (supported); 1315473 Ravens (unsupported) | matched | — |
| 657983 | 101473 | moneyline / full_game / active | 1315478 Bengals (supported); 1315479 Texans (unsupported) | matched | — |
| 657986 | 101474 | moneyline / full_game / active | 1315484 Browns (supported); 1315485 Buccaneers (unsupported) | matched | — |
| 657989 | 101475 | moneyline / full_game / active | 1315490 Jaguars (supported); 1315491 Broncos (unsupported) | unmatched_missing_market | — |
| 657992 | 101476 | moneyline / full_game / active | 1315496 Raiders (supported); 1315497 Chargers (unsupported) | unmatched_missing_market | — |
| 657994 | 101477 | moneyline / full_game / active | 1315500 Seahawks (supported); 1315501 Cardinals (unsupported) | unmatched_missing_market | — |
| 657996 | 101478 | moneyline / full_game / active | 1315504 Dolphins (supported); 1315505 49ers (unsupported) | unmatched_missing_market | — |
| 657999 | 101479 | moneyline / full_game / active | 1315510 Commanders (supported); 1315511 Cowboys (unsupported) | unmatched_missing_market | — |
| 658002 | 101480 | moneyline / full_game / active | 1315516 Colts (supported); 1315517 Chiefs (unsupported) | unmatched_missing_market | — |
| 658005 | 101481 | moneyline / full_game / active | 1315522 Giants (supported); 1315523 Rams (unsupported) | unmatched_missing_market | — |
| 779756 | 108683 | moneyline / full_game / active | 1559000 Falcons (supported); 1559001 Packers (unsupported) | unmatched_missing_market | — |
| 825195 | 111297 | moneyline / full_game / active | 1649878 Chiefs (supported); 1649879 Dolphins (unsupported) | unmatched_missing_market | — |
| 825196 | 111298 | moneyline / full_game / active | 1649880 Panthers (supported); 1649881 Browns (unsupported) | unmatched_missing_market | — |
| 825198 | 111299 | moneyline / full_game / active | 1649884 Titans (supported); 1649885 Giants (unsupported) | unmatched_missing_market | — |
| 825199 | 111300 | moneyline / full_game / active | 1649886 Patriots (supported); 1649887 Jaguars (unsupported) | unmatched_missing_market | — |
| 825200 | 111301 | moneyline / full_game / active | 1649888 Chargers (supported); 1649889 Bills (unsupported) | unmatched_missing_market | — |
| 825201 | 111302 | moneyline / full_game / active | 1649890 Jets (supported); 1649891 Lions (unsupported) | unmatched_missing_market | — |
| 825202 | 111303 | moneyline / full_game / active | 1649892 Texans (supported); 1649893 Colts (unsupported) | unmatched_missing_market | — |
| 825204 | 111305 | moneyline / full_game / active | 1649896 Seahawks (supported); 1649897 Commanders (unsupported) | unmatched_missing_market | — |
| 825205 | 111306 | moneyline / full_game / active | 1649898 Bengals (supported); 1649899 Steelers (unsupported) | unmatched_missing_market | — |
| 825206 | 111307 | moneyline / full_game / active | 1649900 Cardinals (supported); 1649901 49ers (unsupported) | unmatched_missing_market | — |
| 825208 | 111309 | moneyline / full_game / active | 1649904 Vikings (supported); 1649905 Buccaneers (unsupported) | unmatched_missing_market | — |
| 825209 | 111310 | moneyline / full_game / active | 1649906 Raiders (supported); 1649907 Saints (unsupported) | unmatched_missing_market | — |
| 825210 | 111311 | moneyline / full_game / active | 1649908 Ravens (supported); 1649909 Cowboys (unsupported) | unmatched_missing_market | — |
| 825211 | 111312 | moneyline / full_game / active | 1649910 Rams (supported); 1649911 Broncos (unsupported) | unmatched_missing_market | — |
| 848861 | 112325 | moneyline / full_game / active | 1697210 Eagles (supported); 1697211 Bears (unsupported) | unmatched_missing_market | — |

Full native provenance, participants, terms and counterpart IDs are in the companion JSON report.
