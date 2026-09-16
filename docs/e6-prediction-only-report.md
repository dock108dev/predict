# E6 prediction-only integration and bounded capture

September 15, 2026. Scope: Kalshi and Polymarket US observation capture in isolated file journals; no owner database/services, E5 preview, orders, account mutation, paid inputs, commit, push or publishing.

## Access

Current official source copies and retrieval hashes: `evidence/e6/prediction-only/research/official-access.json`.

- [Kalshi rate limits](https://docs.kalshi.com/getting_started/rate_limits): token budgets, normally 10 tokens per read. Existing dedicated production key successfully read `/account/limits` and `/account/endpoint_costs`. Actual Basic account returned 200 read tokens/second and 600 read bucket capacity; use that observed capacity rather than the documentation's generic two-second description. Selected GETs use the observed default cost of 10. E6 throttles to at most one sequential REST request/second/source; no upgrade endpoint is invoked.
- [Kalshi API keys](https://docs.kalshi.com/getting_started/api_keys), [WebSocket authentication](https://docs.kalshi.com/getting_started/quick_start_websockets): RSA-PSS signing using the existing dedicated project Keychain entry. REST signatures cover their actual path without query; WS signatures cover the native WS path.
- [Polymarket US retail access](https://docs.polymarket.us/api-reference/introduction), [authentication](https://docs.polymarket.us/api-reference/authentication), [rate limits](https://docs.polymarket.us/api-reference/rate-limits): public gateway market catalog, dedicated existing retail Ed25519 key for the market socket, 20 REST requests/second/IP publicly and 20/key authenticated. One selected market is below the documented [100 markets per subscription](https://docs.polymarket.us/api-reference/websocket/markets). The numeric retail connection ceiling is not documented here; this run uses one concurrent connection/source and at most two attempts/source.
- No additional-cost entitlement basis: existing project retail/production credentials, documented ordinary account API access, successful current authenticated Kalshi access and the bounded market socket results below. No subscription, metered paid-data product, signup, upgrade or trade is invoked. These venues' request tokens are rate-limit units, not sportsbook credits. This verifies the existing access path, not a new commercial data license or future billing guarantee.
- The Odds API stays disabled. Its key is not looked up merely because it may be present. No quota probe or reference request occurs. An explicit optional reference setting supports the same event, `pinnacle` and `h2h`, with known quota/cost evidence and at most five free credits including retries. Missing or exhausted references stop only that ancillary task. No optional reference entitlement, pairing or fair-price qualification is claimed in this run.

## Engineering

The run specification, preflight and observation owner default to prediction-only. No reference tasks or reference health entry exist when disabled; probabilities, estimates and Mispricing remain unavailable. Startup/preflight perform no network or credential lookup; discovery and capture require explicit invocation. Production destinations and project credential references are fixed. Raw secret echoes are suppressed and cannot be labeled exact. Exceptions are reported by safe category.

Existing native Kalshi sequence/snapshot recovery and Polymarket US subscription-generation/replacement-image logic remain in use. REST, WS, frame, queue, total bytes and duration remain bounded. All discovery attempts count against the same per-source 64-request and 16 MiB allowance subsequently carried into the session. The WS frame/HTTP-response cap stays 1 MiB, with one queued frame, at most 1,000 messages and two connection attempts/source. Queue: 48 records/4 MiB; ingress: 2,048 records/16 MiB; journal: 4,096 rows/32 MiB. Pending frame bytes remain reserved.

Local discovery failures were retained. The first constructor failure dispatched zero requests. The league catalog exceeded the response cap even at five events because a single game's embedded props exceeded 1 MiB. Generic catalog queries without a native winner filter also reached the cap; the V2 enum produced an empty event response. The documented generic events API's string filter accepts the observed native `football_team_full_game_winner` value, returning one full-game winner market per event. This stays below the original cap and avoids collecting ancillary props. Both final catalogs exhausted pagination with 32 identified NFL games. Mapping of new `DET Lions`/`BUF Bills` labels requires the abbreviation and mascot to independently resolve to the same existing NFL registry team; disagreeing names fail.

Real event validation rejects kickoff, changed event/market schedule, live/ended state and explicit rescheduling. The final session revalidates metadata every 45 seconds. Changes between refreshes remain a coverage limitation; this is not a continuous lifecycle guarantee.

## Measured result

**Complete for this bounded prediction-only integration and one real capture. Full E6 remains incomplete.**

- Git HEAD: `0ab12b1e7b57f4ea89b6886c3d69b2459afaa258`, unchanged. Exact uncommitted app/test candidate SHA-256: `a33bf60ea4cebbf74d47249eae31a03c52922b43806ac51a07f2408ebe7a421a`. [Per-file identity](../evidence/e6/prediction-only/final-capture-candidate.json). Independent post-run verification found no candidate file changes. Existing uncommitted work is retained.
- Event: **Detroit Lions at Buffalo Bills**, kickoff **2026-09-18 00:15 UTC / September 17, 8:15 p.m. EDT**. Both exhaustive current catalogs identify the same schedule and participants. Kalshi event `KXNFLGAME-26SEP17DETBUF`, selected market `KXNFLGAME-26SEP17DETBUF-BUF` (YES = Buffalo). Polymarket US event `101466`, market `657964`, slug `aec-nfl-det-buf-2026-09-17`; long side `1315440` = Detroit, short side `1315441` = Buffalo. Native sides are retained; no array-position pairing or settlement equivalence is inferred. [Selected configuration](../evidence/e6/prediction-only/real-20260915-discovery6/run-spec.json), [catalog and mapping evidence](../evidence/e6/prediction-only/real-20260915-discovery6/catalog.json).
- Session `75ec21c1-5962-48e1-96e2-5f6b5ef07150`: started **20:29:08.643372 UTC**, observation cutoff **20:31:08.646185 UTC**, joined shutdown completed within **120.142 seconds** of Start. The summary was finalized at 20:31:08.905916 after replay/export. The 120-second session includes its startup discovery. Prior bounded discovery attempts used **47.159 active seconds in total**; combined active discovery plus session time was **167.301 seconds**. Implementation pauses between discovery attempts are not capture time; no connections were left collecting in those pauses.

| Observation | Kalshi | Polymarket US |
|---|---:|---:|
| Raw incoming WS frames | 17 | 28 |
| Reconstructed native books | 16 | 28 |
| Quote packets replayed | 32 | 56 |
| Stream connection attempts | 1 | 1 |
| REST attempts, including all preliminary discovery | 30 | 36 |
| Conservative body bytes charged, all attempts | 2,746,874 | 7,225,508 |
| Raw WS payload bytes | 6,286 | 145,459 |

**139/139 ingress records delivered/persisted**, plus the separate terminal completion row. No sequence rejection or observed stream disconnect occurred before shutdown; this does not establish gap-free upstream history. Both initial images arrived about 7.86 seconds after Start, following discovery. Both sources remained connected through the observed window, then explicitly became disconnected at Stop. Largest observed frame-receipt intervals were 17.834 s Kalshi / 17.172 s US; these describe this quiet event, not feed latency or a universal cadence. The 30-second stale threshold is an operational setting only.

The deadline interrupted the third periodic US catalog sweep between requests. All dispatched HTTP bodies in the capture are complete, but that final sweep did not produce a third validated US metadata revision. The terminal source states, native shutdown diagnostics and retained pages make the cutoff explicit. Earlier oversized discovery attempts remain incomplete in their own journals; they are not mixed into the successful frame/book counts. No economic audit or invented estimate is present.

**Replay:** all 44 synchronized native books and all 88 quote packets reproduced exactly using the native parsers and saved receipt clocks. Full reopened journal/export equality and its hash chain were independently verified in a fresh process after capture exited. Journal chain SHA-256: `4a954b03a0e1146104a4ae6c319b3201e721a45eff356ec35fe506dbfb36c29a`. [Independent replay](../evidence/e6/prediction-only/independent-replay.json), [raw journal](../evidence/e6/prediction-only/real-20260915-discovery6/session/75ec21c1-5962-48e1-96e2-5f6b5ef07150.jsonl), [saved observation export](../evidence/e6/prediction-only/real-20260915-discovery6/saved-observations.json), [capture summary](../evidence/e6/prediction-only/real-20260915-discovery6/capture-summary.json), [coverage details](../evidence/e6/prediction-only/coverage-audit.json).

## Verification and cleanup

**80 focused test executions passed** before capture: prediction-only idle/preflight/no-reference ownership, optional-reference failure isolation, native reconnect/snapshot/replacement replay, cancellation, queue/byte/request limits, secret redaction, current catalog filter and conflicting participant/phase checks. [Final test output](../evidence/e6/prediction-only/pre-capture-tests-fixed.txt). Initial failures are retained: the real REST constructor lacked common initialization; a stale mock market schedule then correctly failed the added schedule-conflict check. Both were fixed and tested before the successful capture. The constructor-only failure dispatched no requests.

Both native streams and REST adapters report closed; the owning process exited successfully. No new server, database or owner service was started or changed. A fresh in-memory scan of 53 slice evidence files found no dedicated credential values, JSON-escaped values or base64 equivalents; the comparison values were never exported. [Redaction verification](../evidence/e6/prediction-only/redaction-verification.json). Existing evidence/E5 files are verified against entry hashes; intended E6 changes are listed separately in [preservation evidence](../evidence/e6/prediction-only/preservation-final.json). Archived sources, the owner database/services and accepted E5 preview were untouched. No commit, push or publishing.

## Economics and next boundary

**Capture and books are delivered.** Effective event fees/account rounding, complete outcome/settlement compatibility and cross-venue economic matching are not qualified by this slice. Arb therefore retains precise unavailable diagnostics; no profit, executable quantity beyond observed native depth, fair price or probability is manufactured. Mispricing stays unavailable because reference collection/model inputs are absent. Additional spend **$0**; reference requests **0**. The optional-reference code is locally bounded, but no live optional entitlement or provider response was qualified.

**One concrete next action:** add an isolated, file-only E6 real-book/replay view for this saved Detroit–Buffalo session, exposing native side identity, source health, the cutoff and unavailable economics. Reuse these observations; no new live collection or owner-database change is needed for that slice. This work stops here. Continuous reliability, naturally observed recovery, live lifecycle completeness, economic qualification, real-view owner feedback and full E6 completion remain separate and open.
