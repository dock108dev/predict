# Slice 3 — ProphetX read-only ingestion

Current result: September 11, 2026 America/New_York / September 12 UTC. **Sandbox API access, REST ingestion, American-price normalization and authenticated transport recovery work. Live selection-message delivery/reconstruction and quantity sizing remain incomplete.** Production is unverified. Slice 2 remains qualified for its existing scope; PLAN.md and all earlier evidence are preserved. Slice 4 has not begun.

## Latest bounded follow-up — September 12, 2026 01:15 UTC

The existing signed-in session and API key-management area were rechecked; no login or new key was required. The designated sandbox Keychain credential authenticated successfully. [Fresh evidence and artifact identities](../evidence/slice-3/sandbox-followup-20260912/manifest.json) supersede the previous artifact identity for the small diagnostic/test changes below; all prior captures remain preserved.

One further bounded capture on returned NFL event **19458** used **10 HTTP attempts, all 200**, two connections, and the same existing time/message/storage limits. Registration explicitly authorized event `19458` with a `market_selections` binding on each generation; the requested and authorized scope match. Deliberate disconnect, HTTP-200 refresh, resubscription and cancellation succeeded, and transport closed. It received **eight frames: six handshake acknowledgments and two classified as other**. There were **zero `market_selections` frames and zero market-ID-filtered messages**. The other frame names/bodies were not retained, so their purpose is unknown. This establishes that the selected-market filter did not discard a received `market_selections` image; it does not prove that the venue feed is broken or requires additional entitlement. No naturally occurring change was demonstrated within this interval.

The [current event guide](https://docs.prophetx.co/docs/websocket-events) describes change-triggered selection delivery, rather than guaranteeing an initial image. The [current integration guide](https://docs.prophetx.co/docs/integrate-with-websockets) still supports the event-scoped registration/handshake used here. Both sources were saved afresh. Quantity/value ownership, source clock units and further status definitions remain unresolved; no new unit inference was promoted. Resting REST quotes remain available as unsized probability quotes.

Added safe protocol-frame counters, authorized/requested event-scope evidence, and filtered-market counts to transport/verifier diagnostics. Unknown event names collapse to `other`; tokens, signatures and account information are excluded. A synthetic regression exercises other events and out-of-selection market images, and an offline regression replays the new sanitized REST response with request-query provenance. **80 tests and all three examples pass.** See [validation](../evidence/slice-3/sandbox-followup-20260912/validation.json), [result](../evidence/slice-3/sandbox-followup-20260912/live/sandbox-20260912T011548Z/result.json) and [preservation](../evidence/slice-3/sandbox-followup-20260912/preservation.json).

Cumulative execution across the preceding ledger and this follow-up is **42 HTTP attempts, all 200; six WebSocket connections; twenty frames (eighteen handshake, two other)**. Further quiet repeats are not a useful qualification step. The precise next action remains obtaining the venue clarification in the unsent request below. No venue contact occurred; production and Slice 4 remain untouched.

## Current qualification

| Area | Result |
| --- | --- |
| Account/API entitlement | Existing Chrome sandbox session was signed in. API Integration displayed an existing key and key-management controls. The supplied sandbox credential authenticated and retrieved Trading V4 data successfully; API enablement is confirmed, not merely inferred from website login. |
| Credential configuration | Existing dedicated sandbox credentials migrated from the previously authorized `.env` into `prediction-arb.prophetx.sandbox` / `trading-api` in macOS Keychain. Keychain readback matched; plaintext sandbox values removed from `.env`. No new key was needed, no key was revoked, and no secret was printed or placed in source/evidence. Environment and production credentials remain separate. |
| Native REST ingestion | Tournament/event/valid-price-ladder/market endpoints returned HTTP 200. One NFL event yielded 139 parent market objects and 447 distinct leaf strikes. Native selection identities, Decimal values, raw provenance and placeholders replay correctly. |
| Economic ingestion | Trading V4 American odds corroborated against the exact sandbox event UI. Shared unsized ask `Quote` objects now expose probabilities. Native `quantity` and `value` ownership/units remain unresolved; normalized sizes and sized ladders are unavailable. |
| Transport/recovery | Current WSS config, event authorization, signin/subscription acknowledgments, deliberate disconnect, token refresh, fresh reconnect/resubscription and cancellation succeeded on three bounded runs. |
| Streaming market-data qualification | **Incomplete:** no `market_selections` messages arrived in three bounded runs. The latest diagnostic breakdown is above. No initial-image or reconnect-image guarantee is assumed. Synthetic reconstruction is tested but is not a live feed verdict. |
| Production | No production request or setup was performed. The previous designated-entry check found no production credential; current entitlement and production liquidity remain unverified. Sandbox results do not transfer. |

No orders, funding, purchases, venue messages, commits, pushes or publication occurred. Website login no longer blocks this slice.

## New evidence and exact artifacts

Fresh directory: [sandbox qualification](../evidence/slice-3/sandbox-qualification-20260912/). See [artifact manifest](../evidence/slice-3/sandbox-qualification-20260912/manifest.json), [summary](../evidence/slice-3/sandbox-qualification-20260912/summary.json), [tests](../evidence/slice-3/sandbox-qualification-20260912/tests.txt), [UI corroboration](../evidence/slice-3/sandbox-qualification-20260912/ui-corroboration.json), and [preservation check](../evidence/slice-3/sandbox-qualification-20260912/preservation.json).

All saved market responses are **actual sandbox observations**, not production liquidity. Replays use these sanitized market-only responses. Earlier invented fixtures remain labeled synthetic; saved official schemas/guides are documentation. Authentication bodies, tokens, socket IDs, signatures and private-account subscriptions are not retained.

The execution ledger is finite:

| Capture | Result | HTTP attempts |
| --- | --- | ---: |
| `catalog/sandbox-20260912T005709Z` | Login and tournament catalog succeeded. Returned NFL `31` and MLB `109`. | 2 |
| `attempt-1/sandbox-20260912T005720Z` | All REST endpoints succeeded; parsing stopped on reused market IDs before streaming. Original responses preserved. | 5 |
| `attempt-2/sandbox-20260912T005913Z` | Repaired native parsing; 35-second transport exercise; two acknowledged event subscriptions, forced refresh and cancellation; no market frames. | 10 |
| `verification/sandbox-20260912T010125Z` | REST succeeded; a newly added period mapping rejected an empty sub_type; stopped before streaming. Fixed and replayed locally. | 5 |
| `verification-fixed/sandbox-20260912T010141Z` | Final approximately 50-second exercise, 25 seconds before deliberate disconnect and up to 25 after; two acknowledged subscriptions, refresh and cancellation; no market frames. | 10 |

**32 total HTTP attempts, all HTTP 200; four WebSocket connections and twelve handshake frames across both transport runs.** There was no expanding event scan. Each invocation stayed under its declared limits: twenty HTTP attempts, ninety seconds overall, sixty stream seconds, two connections, two MB incoming stream data and five MB retained market bodies. The catalog had no selected event; each market run used only event **19458**, Chicago Bears at Carolina Panthers, September 13 at 17:00 UTC. The streaming selection was full-game moneyline, native market **219**, strike **0**. The final capture's effective selected market count was one, below the maximum three.

## Repairs and supported normalization

### Native identity and discovery

ProphetX uses a market ID as a template across different lines and events. The old adapter wrongly rejected distinct `market_strikes` sharing an `id`. It now uses an explicit composite of native **event ID : market ID : strike**, retaining all original fields in raw JSON. Example: `19458:66:1.5`, `19458:66:2`, `19458:66:2.5`. This composite is an adapter lookup key, not a claimed new venue-assigned ID. Empty parent containers are not emitted as tradable leaf markets. `strike_id` remains the native selection identity, with its native outcome ID retained separately. Decimal-equivalent strikes yield the same key, and different events cannot overwrite each other.

A full replay retains 447 leaf strikes without collisions. Full-game `sub_type=moneyline` is distinguished from first-half moneyline; the verifier no longer selects the first three generic `type=moneyline` rows. An empty optional sub_type is retained raw and does not become an invalid period. Full-game and first-half period labels are mapped only from their explicit subtypes.

**The existing pregame filter did not exclude this usable event:** actual `scheduled` is `2026-09-13T17:00:00Z`, actual state is `not_started`, and the UI shows September 13 at 1 PM Eastern for the same event ID. Tests preserve these requirements; no timezone or status relaxation was needed.

### Price convention — corroborated, now implemented

The [current Trading V4 schema](https://docs.prophetx.co/reference/get_v4-mm-get-multiple-markets) provides native price plus `display_price`. On the exact event page, five REST prices and signed display strings agree with UI probability percentages:

| REST price | UI probability | Conversion |
| ---: | ---: | --- |
| +146 | 40.65% | `100 / (146 + 100)` |
| −164 | 62.12% | `164 / (164 + 100)` |
| −265 | 72.6% | `265 / (265 + 100)` |
| −2200 | 95.65% | `2200 / (2200 + 100)` |
| −4500 | 97.83% | `4500 / (4500 + 100)` |

This is corroboration using native display strings and the matching official sandbox UI, **not just plausible numeric ranges**, and does not borrow FIX or affiliate API units. The UI selection ticket labels “Cost” and “To Gain” and offers the matching moneyline side; it was viewed and closed without entering an order or depositing.

`american_probability` uses a local Decimal context with at least fifty digits. Each native window exposes its best available price as a shared `Quote` with `ask.price`, no invented bid, and `ask.quantity=None`. These appear in `ProphetXBook.normalized_quotes`; `get_quotes` returns them after a fresh REST snapshot. Native prices/windows remain intact. Placeholder/null-price/zero-quantity selections do not create quotes. Sized `OrderBook` ladders remain unavailable, and their shared sync remains UNKNOWN. The native reconstruction property remains separate.

### Quantity — a concrete unresolved distinction

The actual API fields do not support treating `quantity` as the taker's dollar cost or contracts. For Carolina +146 the response has `quantity=91.71`, `value=17.12`, while the UI displays $17. For Chicago −164 it has `quantity=56.26`, `value=81`, and UI $81. At −4500, `quantity=10` and `value=450`, matching UI $450. Thus the UI correlates to `value`, **not quantity**. The current Trading schema does not explain the ownership or transformation between these fields, and sandbox values alone do not establish it. Neither field is silently used for sizing. Native Decimal quantity remains unit UNKNOWN; value remains available in raw provenance.

### States, timestamps and window behavior

Actual REST markets use `status=active`, including both priced and placeholder-only markets. The corresponding moneyline listing is displayed and its quote opens the selection ticket. `active` now maps to shared ACTIVE; other market strings remain UNKNOWN because the [enum guide](https://docs.prophetx.co/docs/meaning-of-enums) primarily defines **order** states. Missing stream status is never backfilled from an old REST state. Synthetic unknown/suspended/closed/status-only reopening cases cannot restore prices or book qualification.

The observed native `updated_at` values are nineteen-digit integers, while documented [event lifecycle examples](https://docs.prophetx.co/docs/sport-events-life-cycle) use the same style. Epoch nanoseconds is a plausible interpretation, but neither the reviewed Trading field definitions nor this capture establish clock units and exact meaning sufficiently. Market metadata `updated_at` can remain old while selections change; it is not treated as the current liquidity-image clock. Raw selection times, metadata times, envelope timestamp and sequence remain distinct. Absolute exchange time stays unavailable; no source age or latency is fabricated. Native integer progression remains exact and survives reconnect.

[WebSocket Events](https://docs.prophetx.co/docs/websocket-events) describes complete best-selection arrays on a strike, a ten-best cap and placeholders. The implementation replaces supplied native windows, rejects unexpected shape, retains partial depth, and invalidates on delete/malformed/disconnected state. Actual REST placeholder rows were `price=null`, `quantity=0`, `updated_at=0`. They remain native observations without a quote. Natural REST changes removed the +146 and −164 levels between the early and final captures; replay confirms they are not merged back. This is **REST replacement evidence**, not a live WebSocket reconstruction claim. No live stream replacement, empty transition, halt or source-time progression was observed.

## Current transport and access protocol

The [current guide](https://docs.prophetx.co/docs/integrate-with-websockets) was rechecked and saved in the new research directory. At execution, September 16 remained a future production transport cutover date. Actual sandbox config returned `ws_host=ws.sandbox.prophetx.dev`, cluster `mt1`, plus app/key/service fields. The client used WSS to the returned host, not a hardcoded legacy vendor endpoint. Registration through `/partner/v4/mm/websocket` returned one event channel with an account limit of 400. That is an observed sandbox allowance, not a universal entitlement.

On both generations the Pusher-compatible connection-established, signin-success and subscription-success stages completed. The first connection was deliberately closed; the second used fresh socket authorization and the same complete event subscription set. `/auth/refresh` returned 200. Only event-scoped market channels were subscribed; private account channels were excluded. Cancellation propagated and sockets/client closed. No selection messages were delivered, and no REST image was promoted into a stream image. Quiet receipt handling does not declare a socket disconnected. A repeated image would not become a new source time merely because of reconnect.

The login/refresh references still conflict on ten versus twenty minute access lifetime; conservative five-minute refresh and one-day maximum refresh-token reuse remain. This run exercised explicit refresh but did not wait for natural token expiry. The published Trading OpenAPI limit is fifty requests/second and up to fifty events per market query; this work used the much smaller local limits above.

## Validation

**78 tests and all three offline examples pass.** All 50 pre-ProphetX tests remain. Seven new tests replay actual sandbox discovery, identity collisions, prices, placeholders, event eligibility and natural REST removal, plus focused precision/status cases; the earlier 21 ProphetX tests were adjusted for the corrected composite IDs. Tests stay offline.

Files changed: `app/adapters/prophetx.py`, `app/adapters/prophetx_stream.py`, `app/prophetx_verify.py`, `app/prophetx_example.py`, `tests/test_prophetx.py`, new `tests/test_prophetx_live_replay.py`, README, this handoff and the Desktop tracker. Shared model files and prior venue adapters are unchanged. Fresh manifests identify the exact tested artifacts. Earlier Slice 3 evidence remains historical, including its initial unknown-price result; current normalized-price evidence supersedes that limitation only.

Run from the project:

```sh
.venv/bin/python -m unittest discover -v
.venv/bin/python -m app.example
.venv/bin/python -m app.polymarket_us_example
.venv/bin/python -m app.prophetx_example
```

The explicitly opted-in live command remains available, but no further capture is needed simply to repeat these quiet sessions:

```sh
.venv/bin/python -m app.prophetx_verify --live --environment sandbox --tournament 31 --event 19458
```

Those IDs were selected from this capture, not permanent discovery constants. The event will eventually stop meeting the pregame filter. Production requires an explicit separate environment and credential.

## Remaining work and one next action

Bounded REST/native ingestion, unsized probability quotes and transport recovery are working. **Sized economic ingestion and live market-message/reconstruction qualification remain incomplete.** Remaining contract questions are quantity versus value (including whose stake/payout each represents), timestamp units/meaning, additional market-state mappings, and whether this sandbox event channel is expected to deliver selection updates. Exact settlement rules/compatibility and production liquidity also remain unqualified; none is inferred from these tests. Unlimited depth, continuous history and a naturally occurring halt are not required gates for bounded ingestion.

**Next action:** have ProphetX clarify the concrete sandbox feed and field-contract questions in the unsent request below. No login action or new generic prerequisite review is needed. The agent has not sent this request and will not contact the venue without authorization.

### Unsent request

Our existing sandbox Trading API key authenticates and reads V4 market data successfully. For NFL event 19458 (Chicago Bears at Carolina Panthers), we registered an event subscription through `/partner/v4/mm/websocket` and connected to the returned `ws.sandbox.prophetx.dev`. Signin and subscription acknowledgments succeeded on both sides of deliberate reconnect; refresh also returned HTTP 200. Three bounded runs received no `market_selections` messages. The latest run explicitly confirmed the requested event scope and binding; it received six handshake frames plus two unclassified other frames, and filtered zero market messages. REST selections changed between captures. Does this sandbox channel publish natural updates, and is any additional event-data entitlement or configuration required?

Please clarify the Trading V4 selection fields `quantity` and `value`, including whose stake, cost, contracts or payout each represents. For example, Carolina +146 had quantity 91.71 and value 17.12, while the UI displayed $17; Chicago −164 had quantity 56.26 and value 81, matching UI $81. Please also confirm units/meaning for selection and market `updated_at`, envelope `timestamp`, and the supported market-status enum. This is private read-only verification for our own trading decisions; no orders or funding are requested.
