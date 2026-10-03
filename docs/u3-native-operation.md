# U3 native current operation

October 3, 2026. The ordinary launcher automatically attaches `CurrentService` to `CurrentStore` and starts one native owner, independently of tabs. [Qualification evidence](../evidence/u3-native-current-20261002/README.md) binds the exact revision and scope. Novig and ProphetX remain unavailable pending U4; no Odds API request is made.

## Open, configure, pause and reopen

Run `.venv/bin/python -m app.dashboard --port 8785` from the repository. The default scope is NFL full-game winner, spread and total; the six-sport roadmap remains configurable, without implying all offerings are admitted. The existing processes at 8783/8784 were preserved during engineering. Closing and reopening a process loads the new application files; a previously running process retains its original code.

Optional small configuration: copy the reviewed `evidence/u3-native-current-20261002/live-config.json` to `.local/predict-current-config.json`, or pass its absolute path using `--current-config`. That qualification configuration runs for 600 seconds. Without a saved configuration the attended maximum is 3,600 seconds. The exact key set, schema and standing-grant identifier are validated before ownership or credential loading. A malformed configuration fails closed. Reducing a bound is allowed; increasing a ceiling is rejected. Supported sports are NFL, NCAAF, NBA, NCAAB, MLB and NHL. Broader configuration is not sustained live qualification.

The separate `/admin` page shows source states, bounded metrics, identity exclusions and sanitized issues. **Pause Kalshi** or **Pause Polymarket US** revokes that source before cancellation and closes its socket/client. **Stop native service** revokes all admission/dispatch, expires held reviews and releases ownership only after bounded safe cleanup. No browser control creates workers. Reopening requires a new runtime/attempt record; Stop/Pause does not reuse or resume an old consumed attempt.

Dedicated credentials are read through the existing guarded macOS Keychain loader. Missing or refused credentials stop only the affected source. Secrets, private messages, account information and orders are not retained. All destinations are the existing fixed native read-only allowlist.

## Concrete operational envelope

| Resource | Bound |
| --- | --- |
| Source HTTP operations, including retries | 240 per source/runtime; strict 10-second transport timeout |
| Native connections | 12 per source/runtime; one active socket each |
| Selected markets | 20 per source, family rotation; Kalshi parser ceiling remains 20 |
| Selected events / transient discovery pages | 24 events / 36 pages per source generation |
| Native payload transport | `native-http-v2`: 4 MiB response wire, 2 MiB entity/decoded, 16 MiB parse expansion, depth 32, 100,000 structural tokens |
| Discovery transport budget | 6 MiB wire and 6 MiB decoded per source/runtime, including rejected deliveries |
| All source HTTP + stream bytes | 16 MiB per source/runtime |
| Socket buffering | 256 KiB message, one queued frame, compression disabled; original incremental Kalshi continuity enforced |
| Current ingress / records / reducer | 8 MiB per observation, 2,048 retained records, 16 MiB serialized reducer; combined catalog remains under the existing 512-market reducer ceiling |
| Source catalog | 200 events, 512 markets, 2 MiB serialized source inventory; US parsing narrowed by exact listing-selected IDs without rewriting receipt bytes/hashes |
| Process RSS | 256 MiB; peak RSS watchdog, no cap relaxation |
| Store / subscriptions / reviews | Existing 64 MiB serialized catalog ceiling, eight subscribers with one latest notice each, eight immutable reviews, 2 MiB total review capacity and 300-second TTL |
| Retry | 2/5/15/30/60-second backoff; five consecutive connection failures or three malformed images stop the source; HTTP/WebSocket 429 waits at least 60 seconds and respects Retry-After up to 300 seconds |
| Cleanup | Five seconds for task cancellation and five seconds for client closure; unresolved safety keeps ownership and a sanitized issue |
| Durable operational state | Exclusive immutable attempt records: maximum 64 records / 256 KiB before refusing reopening; rolling issues: 200 / 1 MiB; no ongoing quote journal |

These limits apply simultaneously. A smaller transport, identity or lifetime allowance can end a source before the attended timer. Oversized US queries can be excluded individually under the existing query-cap policy; later independent queries continue within the same consumed byte budget. No partial response is admitted. Repeated malformed data, authentication/entitlement errors and total budget exhaustion stop that source.

POSIX advisory ownership is shared with retained real `TransportSession`/`ContinuousSession` collectors. A second process or legacy `/api/start` cannot begin overlapping acquisition. Existing finite seals, deadlines, journal fsync acknowledgments, durable cursors/chains and replay remain unchanged. The lock file's last PID is an operational record, not proof of current ownership; the held OS lock governs.

## Exact current admission and clocks

Current admission deep-copies the shared reducer, validates bounded exact books/catalogs, prepares normalized records and atomically commits through the strict current serializer. Only after successful store admission does it swap the reducer, its own service sequence and quote revision index. Current mode never advances a journal cursor. Durable operation explicitly acknowledges `JournalSink` after fsync.

Catalog retirement and changed identity remove affected current books. The owning worker then obtains a fresh subscription image, including when enrichment by the other source changes membership. Incomplete/malformed/rejected observations preserve previous valid inputs, degrade that source and require resynchronization. Complete empty sides produce outcomes without prices. Held Details inputs remain immutable across changes, failures and retirement, and expire on TTL/shutdown.

Kalshi asks are the exact complement of opposite native bids with the original contract quantity. US Long offers and complemented Long bids for Short retain the existing adapter semantics. Win and not-win predicates stay separate; separate native predicate domains never silently turn a Kalshi NO into the opponent's YES. Reviewed literal half-point spreads are oriented in the existing home-margin domain, and totals in combined score. Integer/equality or unsupported predicate forms remain exclusions. An unresolved exact shared occurrence may remain source-local and unverified; it never creates a verified match or comparison cue. Exceptional settlement, costs, sizing and model support remain independently unqualified.

Versioned policies are `kalshi-book-age-engineering-1` and `polymarket_us-book-age-engineering-1`, each with a 30-second engineering eligibility threshold. This is not a measured provider cadence guarantee. Kalshi snapshot send time is not promoted to quote time; supported delta timestamps describe source book updates. US `transactTime` describes the complete market-data image's book transaction time. Missing/regressed time stays unknown/rejected. Identical images, heartbeats, depth-only changes and source-state transitions preserve the original price clocks. A real price/input change has a coherent quote revision. Monotonic store aging advances eligibility independently of acquisition and does not reprice a held review.

Official contracts checked: [Kalshi orderbook updates](https://docs.kalshi.com/websockets/orderbook-updates), [Kalshi event listing](https://docs.kalshi.com/api-reference/events/get-events), [US event listing](https://docs.polymarket.us/api-reference/events/get-events), [US market stream](https://docs.polymarket.us/api-reference/websocket/markets) and [US rate limits](https://docs.polymarket.us/api-reference/rate-limits). Source-to-receipt and receipt-to-projection measurements describe only observations whose clocks support them. Browser snapshot HTTP delivery and visible coherence were checked; precise paint latency is not instrumented or claimed.

## U6 supported native-only startup

Set the strict boolean `aggregate_enabled` to `false` in the current configuration before launch. It defaults to `true`; existing configurations with the former exact key set preserve their prior behavior. The full-service `enabled` flag retains its meaning. Disabled aggregate operation constructs no shared scheduler, loads no aggregate credential, performs no bootstrap/paid request and touches no quota ledger. Novig/ProphetX show `stopped / aggregate_disabled`; admin shows no configured shared scheduler and no newly verified balance. Guarded native recovery preserves the setting and binds it into each consumed attempt. Changing the saved configuration blocks recovery until ordinary reopening with the new configuration.
