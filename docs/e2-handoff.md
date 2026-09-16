# E2 handoff — one reference adapter and durable receipts

E1 is the contract/audit prerequisite; **E2 is not implemented**. No provider has been selected, verified, subscribed to or contacted. This document specifies the next boundary, not permission to collect data or migrate an owner database.

## One adapter boundary

Proposed protocol (to implement in E2):

```python
class ReferenceAdapter(Protocol):
    # async generator: cancellation/errors propagate; one declared native event
    def observe(self, native_event_id: str) -> AsyncIterator[ReferenceQuote | ReferenceGap]: ...
    async def aclose(self) -> None: ...
```

`ReferenceGap` is a proposed E2 record: receipt/session ID, provider, affected native event/markets and families, aware detected/start/end times (nullable where unknown), reason, recovery/resync state, raw evidence IDs and coverage limits. Do not manufacture a gap's start or recovery time from silence alone.

The adapter boundary accepts one explicit native event, retains every delivered paired change in scope (including non-opportunities), source/native keys, raw body and source/receipt times, and emits gap/failure evidence. No trading, book snapshot, quote-side or execution method. Polling must honor verified provider rate/cost constraints and cancellation. Receipt is assigned at ingress, before queueing, normalization or matching, and never rewritten to the source timestamp. Per-side timestamps and native odds convention are retained in raw evidence and normalization metadata; conversion uses exact decimal strings and a documented version. Unsupported three-way/missing/unsynchronized lines remain explicitly unavailable for a paired estimate.

Native observations may have null canonical IDs/rule profiles. Matching then creates a separate immutable enrichment revision bound to the original receipt. It must not mutate raw history or silently remap an old estimate. `ReferenceQuote` is the shared view of a receipt plus a specific enrichment revision; E2 must persist that binding explicitly.

## Matching responsibilities

1. **Adapter:** native IDs, bookmaker keys, participant roles and schedule as reported. No generated abbreviation, fuzzy fallback or title substring becomes a canonical ID.
2. **Existing normalization registry:** resolve league/team candidates using existing aliases; retain unresolved/ambiguous inputs. Add narrowly evidenced aliases if needed, rather than import SDA tables.
3. **Existing event Matcher:** extend with a reference-observation enrichment boundary outside the prediction `Venue` enum. Assess league, participants, exact schedule, reschedule/game identity and native mapping evidence. Reuse canonical-ID/revision policy. Source ingestion cannot force an event match.
4. **Moneyline matching + settlement assessment:** validate period, pregame phase, line absence, outcome orientation, overtime/tie/void/postponement/deadline/source rules and exceptional payouts. A reference source's “h2h” label or a game's sporting result does not establish venue contract compatibility. Unknown or incompatible rules exclude that reference.
5. **Versioned source registry:** resolve provider → underlying bookmaker → information family and copies, backed by evidence. Canonical venue origin IDs identify target copies across aggregators. Unknown family/lineage is ineligible; do not claim independence from different provider names.
6. **E3:** consume only receipt-bound, target-specific eligible inputs. Implement verified pair synchronization/source freshness, de-vig and estimate weighting later. Do not count multiple aggregator deliveries of one bookmaker twice.

## Proposed storage changes — design only

Extend the existing PostgreSQL capture/replay design, with an explicit new migration and export version during E2. No SQL migration is delivered or run in E1.

| Proposed table/record | Key and retained data |
|---|---|
| `reference_source_revision` | Version/hash, provider, native source key, canonical origin/family/copy lineage, evidence artifacts, effective-from time **and known-at receipt time**. New knowledge must not silently rewrite prior estimates. |
| `reference_receipt` | Unique ingress receipt ID, existing capture session link, provider/native event/market keys, aware receipt time, nullable source time and semantics, exact raw bytes/text artifact hash, sequence if supplied, mode, collection scope, entitlement evidence. Append-only; repeated identical payloads may share an artifact but remain separate receipts. |
| `reference_quote_revision` | Receipt ID + normalization/mapping version; canonical event/market IDs or unknown, ordered native/canonical sides, two exact decimal prices (numeric or validated decimal text, never float), native odds convention, side-time evidence, term/rule-profile hash, source-registry revision, coverage/unknowns. Append-only enrichments; retain rejection reasons. |
| `reference_gap` | Session/provider/scope, detected/bounded times, missing/unknown spans, recovery evidence. Keep discovered coverage distinct from collected coverage. |
| `fair_price` and `fair_price_input` (reserve for E3) | Estimate ID/version, target, as-of/estimated time, all considered receipt/enrichment/source-registry IDs and inclusion reasons, probability, method parameters, freshness/uncertainty. Input FK/check logic must also enforce `received_at <= as_of` for included rows; source time is not the cutoff. |

Index `(provider, native_event_id, received_at, receipt_id)` and canonical market/family receipt time via enrichment. Preserve non-opportunity receipts. Preserve raw artifacts and timestamps with exact precision; hash immutable envelopes for replay. Export bundles must include source/matching/rule revisions as known at the estimate and receipt/gap records. Existing `capture-bundle-1`, detector and depth audit replay remain readable; no implicit format reinterpretation. Add isolated disposable-database checks only in authorized E2 implementation, never against owner data.

Limits/retention and subscription scope must be explicit. Do not import SDA's mutable opening/latest rows, Redis TTL history or retrospective closing snapshots as a complete receipt timeline.

## Provider capability verification matrix

Begin E2 with a small evidence matrix for **one direct-book/exchange candidate and one multi-book candidate**. Pinnacle and a multi-book source are roadmap candidates only, not selections or claims of current availability. Consult current official documentation and authorized access evidence; absence of evidence remains unknown.

| Capability | Required evidence before selection/live qualification |
|---|---|
| NFL pregame moneyline and both sides | Actual supported product/regions and field examples; two-way versus three-way markets, paired atomicity, updates to only one side, odds format and orientation. |
| Underlying source identity | Stable bookmaker IDs separate from display titles/provider; rebrands/aggregation/copies and documented source-family linkage. |
| Exact terms | Period, overtime, tie, cancellation, postponement/void treatment and native event/outcome IDs; mapping to existing prediction contracts remains an assessment. |
| Timestamps | Meaning/precision/timezone of event, market and side timestamps; snapshot versus last-change; server batching and clock quality. Preserve source time as null if absent. |
| Cadence and delivery | Poll/stream support, plan rate limits, update batching, typical/guaranteed cadence if any, latency evidence, retry/resync and limits. Do not infer subsecond lead/lag quality from a fast HTTP response. |
| History | Historical paired prices, source versus publication time, receipt-time availability, revisions, coverage/gaps and retention. Purchased historical snapshots cannot invent past local receipt times. |
| Permitted reference use | Current documented terms/entitlement for local analysis, persistence, deriving probabilities and any future display/export. Public endpoint access alone does not answer this. |
| Cost and access | Plan price/currency, quota credits per book/market/poll/history request, overages, trial restrictions, geographic/account requirements and cancellation. Unknown cost stays unknown; no signup or purchase in E1. |

**One next action:** prepare that two-candidate capability/evidence matrix in E2 and identify whether either source can supply one usable NFL paired moneyline with stable source identity and permitted durable reference use. Select only on supported evidence; leave unresolved access facts explicit and use fixtures for independent development.

E1 does not authorize E2 provider integration, live collection, accounts, owner-data access, migrations, service restarts or trading. The pending owner Start/Stop/Historical try remains a separate practical check; the deferred 250 ms gate stays deferred.
