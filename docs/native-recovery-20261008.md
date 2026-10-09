# October 8 native update recovery

Owner feedback: Kalshi and Polymarket prices were unavailable on the board after the aggregate freshness repair.

## Diagnosis and repair

Kalshi's last catalog response timed out after a partial HTTP 200 delivery. The receipt path marked that transient condition terminal, bypassing the existing discovery retry budget. Native timeout/transport delivery failures now keep the source recoverable; discovery uses the configured backoff and stops after three failed discoveries. Truncated, malformed, denied and resource-exceeded inputs retain their existing refusal behavior. Partial responses never enter the catalog.

Polymarket had received current NFL full-book images, but source-to-receipt lag exceeded its existing 30-second confirmation bound. Full-board projection on every book packet was blocking catalog reads. An isolated request through the same bounded Kalshi reader completed successfully (HTTP 200 in 1.22 seconds), distinguishing local scheduling pressure from provider failure. Workers now validate/reconstruct every frame, retain at most one latest full image per selected market, and publish one atomic batch per source on a one-second timer. Quiet final images are delivered by the timer; connection loss, resync, Stop and shutdown discard queued images. All batch identities, complete outcomes, prices, depth and confirmations are validated before one atomic state commit. Original source/receipt timestamps and freshness policy are preserved.

Polymarket also had an independent admission-order defect: its predicate binding was blocked for missing season/stage before current occurrence evidence was applied. Catalog admission now rebinds identity-blocked markets only after their exact occurrence evidence has been validated, then rechecks direct-win correspondence. Prebound markets and unmatched/invalid occurrences retain their existing interpretation. A regression check proves standalone Polymarket admission without Kalshi. Detailed bounded binding exclusions are visible in Admin.

## Verification

76 focused native, confirmation, service, state and aggregate tests passed. New controls cover transient HTTP timeout recovery/backoff and bounded latest-book batching and stop/generation cleanup. The ordinary app was restarted from the repaired source. Live verification is recorded below separately from these fixture checks.

No credit/accounting reset, credential change, resource/freshness-limit increase, commit, push or release occurred. All six aggregate sports keep the existing daytime schedule. Native discovery remains NFL.

## Live verification

At 17:56 Eastern on October 8, both native sources were `available`, both catalog readers had complete HTTP 200 responses, and the current sink had zero identity exclusions. Kalshi had reconstructed 236 books and Polymarket 50 in the fresh runtime, with source-to-receipt lag approximately 1.65 seconds and 0.57 seconds respectively. The side-panel board visibly showed Kalshi and Polymarket quote buttons; Polymarket confirmed books were one second old in that observation. Kalshi rows truthfully distinguish fresh snapshot confirmations from unknown original source age. This is a brief live recovery check, not sustained multi-hour qualification or wider-sport coverage. Local memory sampled about 703 MiB, below the existing 768 MiB ceiling. Final small telemetry correction keeps queue duration separate from measured batch projection duration.
