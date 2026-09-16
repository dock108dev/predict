# E6 bounded transport integration

## Completion boundary

**Transport engineering complete for the bounded local-mock package. Real-feed qualification remains unstarted; full E6 is not complete.** Real Start is disabled in code. No provider endpoint, credential store, owner database or owner service was accessed. No subscription, purchase, outreach, trading, Git commit/push or publishing occurred. The accepted E5 preview and all prior app/evidence files are preserved.

This package adds an observation-only E6 owner. It deliberately does not pass real observations through E2's synthetic-only knowledge records or E3/E4's invented fixture economics. Native prediction and reference observations can be retained with null pairing, lineage, fee and settlement assessments. Supplying assessment references does not enable calculations.

## Implemented paths

- `app/collection/odds_http.py`: actual asynchronous HTTP event-odds request/streaming path; explicit NFL event, `h2h`, `pinnacle`, decimal odds, ISO dates and source-ID request. One concurrent request, no redirects or automatic decompression, explicit timeout, capped response/session body bytes, cancellable request/close, bounded caller-owned retry/backoff. Only numeric loopback HTTP endpoints and a fixed dummy key are accepted in this package.
- Request/credit/dollar reservation precedes every dispatch. Response used/remaining/last headers must each appear once as bounded nonnegative integers and reconcile with the known baseline. Missing, duplicate, reset, inconsistent or exhausted quota stops further requests. Timeout/uncertain dispatch retains its reservation. Lower reported cost never refunds the reserved credits; over-reservation can intentionally stop early. Excess reported charges are recorded and stop collection; actual provider billing is not qualified.
- Each dispatched reference request emits exact bounded body bytes, hash, status, sanitized quota/retry headers, request start/receipt times and budget state. Partial, oversized, truncated, cancelled, compressed or redirected captures cannot pass validation. An exactly capped body without confirmed EOF is conservatively incomplete. A response echoing the dummy secret is suppressed with explicit incomplete evidence, not presented as an exact capture. Exceptions and saved requests never contain the credential-bearing URL.
- `app/collection/prediction_producer.py`: reuses existing Kalshi and Polymarket US REST adapters, event normalization, native stream engines, `book_observations` and storage `packet` conversion. Kalshi retains sequence-gap detection and full-snapshot recovery. PMUS retains subscription generations and atomic replacement-image semantics. Discovery clears old selections, requires explicit event/market identity, participants, schedule and active moneyline state, and never silently selects another event.
- Prediction REST and WebSocket activity share per-source body and dollar allowances. REST attempts and reconnects reserve cost before dispatch. Pending receives reserve their allowed frame bytes so concurrent discovery cannot spend the same allowance. Known unused bytes are released; uncertain failed receives remain conservatively charged. Frame/message/connection/discovery limits and the session deadline bound retained native parser histories. No change to the old controller's 60-second cap or native protocol code.
- `app/collection/run_spec.py`: local, side-effect-free configuration preflight; explicit identities, mappings, assessment revisions, authorization references, schedule/window, duration/cadence, quota/cost and cleanup. No credential resolver is present. A valid real specification still reports activation disabled and real Start rejects it before opening files or transports.
- `app/collection/transport_session.py`: explicit Start/Stop, a maximum 300-second deadline including discovery, independent health/staleness, reference identity checks, repeated bounded discovery, cancellation/join of producers, and a bounded fsynced observation journal using the existing `CaptureQueue`. Native frames are separate from derived book/health updates; a stale/invalidated book does not masquerade as a new wire receipt.

## Storage and replay

The new versioned file journal stores the supplied specification, every accepted HTTP/frame/book/health record and completion accounting. It uses hash chaining and unique ingress IDs; exact replay detects edits and torn tails. Missing terminal completion is reported as interrupted, with no inferred crash time. It uses the existing native storage packet representation but **does not migrate or write PostgreSQL**. E2's synthetic database tables and prior E6 saved format are unchanged.

Bounds: 48 queue items/4 MiB queue, 2,048 ingress records/16 MiB canonical ingress, 4,096 physical journal rows/32 MiB journal. Accepted rows are fsynced before queueing; queue/capacity failure stops collection. Disk write failure cannot claim durable completion. The file store is the primary durable store, so “persisted” here is not a PostgreSQL count. OS-level hung filesystem behavior remains outside the responsiveness guarantee.

Body accounting bounds application payloads; socket/kernel buffers, protocol framing and headers are separate. Native WebSocket libraries enforce a finite maximum frame size and one queued frame. There is no subsecond source-timing claim.

## Verification

The focused suite uses local HTTP/WebSocket servers, fabricated frames and an explicitly adapted retained PMUS market object. The retained object's source is `evidence/phase-0/pmus-tb-market.json`; its old settlement text/fees do not enter calculations or become current event knowledge. Local HTTP access logging is disabled. No live credentials are used.

- **21 focused tests passed:** actual request parameters/exact bytes/redaction; oversized streaming and total limits; cancellation in connection/stream/backoff/discovery; timeout/truncation; 429 accounting; quota exhaustion/unknown/duplicate/contradictory/reset evidence; dollar reservation; native reconnects and synchronization; wrong reference event, changed schedule, missing mapping, kickoff/window conflicts; idle preflight and disabled real Start; mixed-source persistence, null economics, exact replay and tamper/torn-tail/interrupted handling.
- **113 regressions passed:** existing Kalshi parser/replay, PMUS stream, reference, pricing, opportunities and E5 preview. E5 interface-state check also passed. No changes were made to those existing implementation paths.
- Short mixed local-server run retained native snapshot/delta/replacement receipts and independent health exclusions, with two connections per prediction source and exact replay. See [summary](../evidence/e6/transport-integration/mixed-summary.json) and [journal](../evidence/e6/transport-integration/mixed-session.jsonl).
- Final local mock run: **65.109 seconds**, **90/90 records delivered/persisted**, **7 reference requests**, **19 total local HTTP requests** and **two connections per prediction source**. Every loaded implementation/test file matches the final candidate. See [measured result](../evidence/e6/transport-integration/final-65s/summary.json), [loaded identity](../evidence/e6/transport-integration/final-65s/runtime-identity.json), [saved journal](../evidence/e6/transport-integration/final-65s/session.jsonl) and [cleanup](../evidence/e6/transport-integration/final-65s/cleanup.json). This crosses the unchanged old 60-second limit through E6 ownership. It is neither a 300-second nor a real-feed qualification.
- The original completed 900-second E6 synthetic evidence is reused **only for the unchanged synthetic path**. No new 15-minute claim is made for this observation owner. The 250 ms gate remains deferred.

Initial failures remain under the evidence directory. They exposed discovery-sibling cancellation/cleanup and a mock's missing Kalshi pagination cursor. A later review added shared prediction byte reservations. The diagnostic 65-second run predates that reservation change; its `http_stopped:false` was an incorrect object-null check after cleanup, not an observed listening service. Final cleanup checks the server's actual serving state.

## Candidate and preservation

Git HEAD remains `0ab12b1e7b57f4ea89b6886c3d69b2459afaa258`; additions are uncommitted. Transport implementation/test digest: `91fa570778961e48f5f3fe3dcef9afdf8e6a3db7c1e7ff3daebcab2a780560db`. Full app/test digest: `e4b923d8625d6a4b222b20c1595bc6663aec9c9638229c9978d4b4d76fbfb1e5`. [Candidate file hashes](../evidence/e6/transport-integration/candidate.json) identify the transport implementation and tests; [preservation result](../evidence/e6/transport-integration/preservation.json) compares all entry-hashed preexisting app/test/docs/evidence/script/example files against entry hashes. The Desktop tracker is updated separately and its entry contents are retained. Existing E5/E6 implementation, historical evidence and archived source copies were not edited.

## Reproduce and next boundary

```sh
.venv/bin/python -m unittest tests.test_e6_transport -v
.venv/bin/python -m app.collection.run_spec docs/e6-first-real-run.json
```

The preflight skeleton intentionally reports missing owner choices. `tests.e6_transport_verify` is a local-mock verifier, not a provider launcher; it refuses to overwrite its evidence directory. The existing synthetic preview remains unchanged and starts idle.

The next owner action is to fill/review [the first-real-run specification](e6-first-real-run.md). Remaining live-only work includes current entitlement/cost evidence, actual identities and compatible terms, authorized credential/endpoint wiring, observed provider quota behavior, clock/cadence/latency evidence and real-feed recovery qualification. No first real run is authorized or enabled by this delivery. Stop here.
