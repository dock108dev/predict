# Phase 0 evidence

Retrieved on **2026-09-11**. These are bounded public research captures, not a continuous feed or execution evidence. [Findings](../../docs/venue-access.md), [machine-readable provenance and SHA-256 hashes](manifest.json).

No credentials, cookies, account sessions, authentication responses or request headers were saved. Raw response bodies are unchanged. The manifest records source URL, local UTC start/retrieval times, HTTP status, identifiers and evidence class. Catalog files contain more than the selected event; selection does not prove exhaustive coverage.

## Live unauthenticated production observations

| File | Venue identifiers / scope | Retrieved UTC |
|---|---|---|
| [kalshi-series.json](kalshi-series.json) | {"selected_series_tickers": ["KXNFLGAME", "KXMLBGAME"], "scope": "Sports series catalog; includes other series"} | 2026-09-11T21:53:05.280316+00:00 |
| [pmus-nfl-events.json](pmus-nfl-events.json) | {"league_slug": "nfl", "selected_event_id": "74905", "selected_event_slug": "nfl-tb-cin-2026-09-13", "selected_market_id": "381958", "scope": "Returned NFL events, including other events/markets"} | 2026-09-11T21:53:06.513501+00:00 |
| [kalshi-nfl-markets.json](kalshi-nfl-markets.json) | {"series_ticker": "KXNFLGAME", "selected_event_ticker": "KXNFLGAME-26SEP13TBCIN", "scope": "First requested open-markets page, limit 100; not exhaustive"} | 2026-09-11T21:53:43.837278+00:00 |
| [pmus-tb-cin-book.json](pmus-tb-cin-book.json) | {"market_id": "381958", "market_slug": "aec-nfl-tb-cin-2026-09-13", "long_side_id": "763430", "short_side_id": "763431", "id_provenance": "Market/side IDs from pmus-tb-market.json; book embeds marketSlug"} | 2026-09-11T21:53:43.907944+00:00 |
| [kalshi-fee-changes.json](kalshi-fee-changes.json) | {"series_ticker": "KXMLBGAME"} | 2026-09-11T21:53:44.034206+00:00 |
| [kalshi-tb-cin-event.json](kalshi-tb-cin-event.json) | ["KXNFLGAME-26SEP13TBCIN"] | 2026-09-11T21:54:26.631142+00:00 |
| [kalshi-tb-book.json](kalshi-tb-book.json) | ["KXNFLGAME-26SEP13TBCIN-TB"] | 2026-09-11T21:54:26.743674+00:00 |
| [pmus-tb-market.json](pmus-tb-market.json) | ["aec-nfl-tb-cin-2026-09-13"] | 2026-09-11T21:54:26.830502+00:00 |

Source endpoints are recorded verbatim in the manifest. All eight requests returned 200. Each body is a live observation, **not an official documentation example**. No ProphetX or Novig live response was captured because no authorized credentials were available and no anonymous documented live path was established. No live MLB book was captured.

## Official documents — not live observations

| File | Official source | Retrieved UTC |
|---|---|---|
| [kalshi-nfl-rules.pdf](kalshi-nfl-rules.pdf) | [Original official PDF](https://assets.kalshi.com/contract_terms/FOOTBALLGAMEWIN.pdf) | 2026-09-11T21:55:39.665439+00:00 |
| [kalshi-mlb-rules.pdf](kalshi-mlb-rules.pdf) | [Original official PDF](https://assets.kalshi.com/contract_terms/BASEBALLGAMEWIN.pdf) | 2026-09-11T21:55:39.952877+00:00 |
| [prophetx-nfl-rules.pdf](prophetx-nfl-rules.pdf) | [Original official PDF](https://framerusercontent.com/assets/3xBUPoodNIUMWAauxaaccjNRSo.pdf) | 2026-09-11T21:55:40.361383+00:00 |
| [prophetx-mlb-rules-amendment.pdf](prophetx-mlb-rules-amendment.pdf) | [Original official PDF](https://framerusercontent.com/assets/xOPD9P6Y43gSYnXRNP45EYfPMs.pdf) | 2026-09-11T21:55:40.876056+00:00 |
| [prophetx-fee-extension.pdf](prophetx-fee-extension.pdf) | [Original official PDF](https://framerusercontent.com/assets/oNmtogNF4ucRmj5pymJVs4DLV4.pdf) | 2026-09-11T21:55:41.600201+00:00 |

The ProphetX fee document includes official worked examples; these are illustrative policy calculations, not fills or account records. The NFL/MLB PDFs are general product terms, not proof that a specific live listing exists. Kalshi rule URLs came from its captured series metadata. ProphetX PDFs were reached through official exchange materials. Novig winner specifications were reviewed through its official contracts index but were not saved; their attachment links are temporary.

## Candidate and limits

Tampa Bay–Cincinnati on September 13, 2026 is a common **candidate** between the captured Kalshi event and Polymarket US event 74905. The latter contains moneyline market 381958; the single-market response binds its long outcome to Tampa Bay. The research report records the exact sides, depth and timing. No four-venue common event is established.

The books were captured about 43 seconds apart. They cannot demonstrate a contemporaneous arbitrage or actual fills. Kalshi REST supplies no exchange book timestamp; Polymarket US transactTime is not a transport-latency measurement. Settlement compatibility is UNKNOWN because postponement/fair-value treatment has not been reconciled.

These files remain local. Data-use scope for automated collection, scanner development, retention and redistribution is unresolved; public access is not a blanket license. Do not expand collection or publish these samples based solely on this evidence.

## Verification record — 2026-09-11

- All 13 saved source files match the SHA-256 hashes in the manifest; eight JSON bodies parse successfully.
- Selected event/market IDs and reported book-level counts were checked against the raw responses.
- Local links in the report, evidence guide and tracker resolve. Kalshi, Polymarket US and Novig documentation links match their official indexes; other official sources were opened during research.
- Structured JSON key inspection and credential-pattern checks across JSON and extracted PDF text found no credentials, private account fields, bearer tokens, private keys or signed-access URLs. No authenticated source was used.
- Supplied PLAN.md SHA-256 is unchanged: `d7cc3c1a0d991ae3afe175b9c1d64820aab7ce853a78911b34ac8c08cdd9e91c`.
- Workspace contains only the supplied plan and research/evidence files. No application, dependency installation, infrastructure or Git repository was created.
