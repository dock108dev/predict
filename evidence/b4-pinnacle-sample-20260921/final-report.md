# B4 actual Pinnacle continuation — September 21, 2026

**Independent engineering verified; full B4 IN PROGRESS. Beta NOT READY FOR SIGNOFF.** Actual model acquisition/independence and compatible actual-reference EV remain open. KenPom deferred. Novig/ProphetX replies pending.

## Executed allowance

Owner completed local hidden entry and free-500-credit plan confirmation. Keychain reference only: `keychain:prediction-arb.the-odds-api.free/nfl-pinnacle-readonly`. No account request was used for plan checking. Owner confirmation is not independent account-plan inspection.

Exactly one authorized NFL moneyline request, Pinnacle only, no retry/redirect/pagination/fallback, no historical endpoint or upgrade. HTTP 200; **1 credit used, 499 remaining**, as reported by quota headers. Response 7,163 bytes, under 256 KiB, received at `2026-09-21T16:01:45.028502+00:00`, within 20-second deadline. Original SHA256 `dc7c8df770bd9bfb38eb9865aabce0152e556dab36aeccbfcd1d4bd482e56192`.

[Preflight](preflight.json) · [Consumed attempt](attempt.json) · [Status, timing, quota and hash](result.json) · [Original body](response.bin).

Seventeen listed events: 15 populated with `pinnacle` / `Pinnacle` two-way h2h; two with no bookmakers. Extracted only 16 side references from the first eight populated events ordered by start then ID. Other returned events remain in the bounded original body; no additional extracted records. This observes NFL h2h entitlement only, not six-sport completeness, other market families, recurring quota feasibility or fixed delay. Update-to-receipt age is not proof of underlying odds delay.

## Ordinary product integration

[Prepared records](prepared-references.json) preserve whole original response, native odds, provider/origin, native IDs, participant names, timestamps and conversion. An independent rational oracle computes other-side decimal odds divided by the sum, checks each 40-digit derived value within 1e-39, and records exact fractions in [original-input reconciliation](original-input-reconciliation.json). Existing adapter rederivation validates every immutable reference.

A new stopped package uses actual import time and cutoff; no earlier evidence is rewritten or new receipt backdated. [Exact saved reopening](saved-reopening.json) · [package manifest](sessions/pinnacle-nfl-retained-20260921/manifest.json). A byte-identical package is now registered in the ordinary product history directory: [registration](ordinary-history-registration.json). Normal saved-session discovery can show it without restarting an existing beta process.

[Browser verification](browser-verification.md) covers ordinary saved Details, expandable original odds/conversion, dates, unknown delay, unavailable EV and reload. **Actual supported EV is unavailable**: no compatible prediction books or reviewed event/settlement equivalence is present. References use provider-local identity with unverified settlement rather than borrowing a prediction ID. [Retained compatibility audit](retained-compatibility-audit.json) inspected two complete established real packages from September 16, plus a [legacy export](legacy-discovery-audit.json); these precede the September 21 receipt. [Event overlap](retained-event-overlap.json) and [reviewed candidate mapping](reviewed-candidate-mapping.json) identify exact team/start matches in the September 16 listings; they are explicitly time-mismatched and fail the unreviewed settlement gate. This is not an exhaustive archive claim. No prediction collection occurred.

## Verification

- [Existing CI](check-ci.txt): 46 math/product checks, including original 18-Arb/96-EV reconciliation; 31 B2/B3/B4 checks; both JavaScript suites PASS.
- [Four focused checks](affected-checks.txt): native actual-input reconciliation, saved cutoff/reopening/tamper rejection, Arb exclusion/unavailable EV, one-call durable intent, quota failures/no redirects/no retries/body cap/secret-echo suppression and NHL mapping isolation. All network sample-runner tests use injected mock transports. No test or preview reads credentials or consumes quota.
- New checks added to `scripts/check-ci`. Existing source adapters, projection, fee/calculation engine and collector were preserved; only retained-reference presentation extended in the dashboard.
- The first read-only audit attempted eager materialization and hit the existing replay RSS guard. It was repaired to stream verified rows; no resource bound was weakened. Legacy discovery export was inspected with its own format rather than forced into a coverage package.
- [Implementation identity](implementation-identity.json) records current hashes and reconciles prior B3/B4 source identity. Old evidence remains unchanged.

## Remaining work / owner action

[Revised model proposal and exact B5 scope](../../docs/b4-model-mapping-next.md): MoneyPuck remains the NHL candidate, not an NFL replacement. Its actual current game output and dependency/outcome meaning remain to be observed. FanGraphs remains MLB; NFL FPI is market-informed, BPI unresolved; ratings remain ratings. KenPom is deferred.

The next independent engineering slice is NHL full-game winner team/event/season mappings, regulation versus overtime/shootout semantics, venue terms and existing fee/depth/history integration. The pure reviewed scope gate is offline-tested but does not enable NHL EV. No provider reply is required for that work.

Smallest owner action when ready: approve **one public MoneyPuck page GET**, zero API credits, 256 KiB/20 seconds, no secondary requests/retries, at most two explicitly published probabilities, with the documented stop rules. This proposal is not executed or authorized by the Pinnacle approval. No additional Odds API request is planned.
