# Slice 7 — canonical event matching

Completed September 12, 2026 UTC. Matcher `event-matcher-1`, local store schema 1.
**Next project action: Slice 8 — moneyline market matching. Stop before Slice 8.**

## Implementation and use

`app.matching.observation()` consumes the existing immutable Slice 6
`NormalizedEvent`. It does not resolve aliases or interpret title order.
`Matcher.ingest()` accepts a complete batch of those observation envelopes;
`report()` adds canonical events with attached listings and pairwise evidence.
`save()` / `load()` persist the current state and its full audit history.

```python
from app.matching import Matcher, observation
from app.normalization import enrich_event

matcher = Matcher()  # or Matcher.load(path) on subsequent runs
row = observation(enrich_event(event, environment='production'), artifact=source_path)
matcher.ingest([row])
matcher.save(path)
result = matcher.report()
```

Read-only copies are returned to callers; ingestion makes its own defensive copy.
Every observation retains the full normalized wrapper and original shared Event,
including exact raw JSON text, native reference, evidence kind, source and receipt
time. Each envelope has a SHA-256 hash, raw-source SHA-256, normalization registry
version/hash, schedule source and optional artifact path. Original observations
are never edited. Registry differences block matching pending explicit migration.

The example replays the same four capture files through Slice 6's existing
`captured_events()` and `enrich_event()` path. It does not copy alias logic or
read data from a live venue. The complete immutable observations are included in
its output so every comparison can be followed back to the captured source.

```sh
.venv/bin/python -m app.matching_example
.venv/bin/python -m app.matching_example --store /tmp/slice-7-events.json
.venv/bin/python evidence/slice-7/verify.py
```

The example constructs a fresh reproducible demonstration; `--store` writes that
snapshot. It is not an incremental collection command. For incremental work,
load the existing store before calling `ingest()`.

## Decision policy

- Require a resolved league and exactly two distinct, resolved participants in
  that league. Fuzzy names, absent participants and inconsistent registries do
  not produce automatic matches.
- Scope native references by evidence kind, environment, venue and exact native
  event ID. Production, sandbox and synthetic evidence cannot merge.
- Compare unordered participant identities. Explicit home/away roles must agree,
  including partial labels which would assign both teams the same role. Missing
  roles are compatible. Unrecognized explicit role labels block confirmation;
  all original labels and unassociated native role IDs remain in the observation.
- Use aware event-start instants, with **900 seconds inclusive** as the default
  configurable tolerance. `Matcher(tolerance_seconds=...)` accepts a finite
  nonnegative value. This is a conservative local implementation policy, not
  proof of identity. UTC calendar dates are not a matching gate. This explicitly
  supersedes the example same-date requirement in the preserved PLAN.md.
- Start comes only from `Event.scheduled_start`. Captured sources are Polymarket
  US `events[].startTime`, ProphetX `data.sport_events[].scheduled`, and Kalshi
  Sports game milestone `start_date` linked by `related_event_tickers`.
  Expiration, settlement and metadata-update timestamps are never substituted.
- Missing, uncertain, postponed and canceled schedules block automatic matching.
  Callers may supply `schedule_status` and positive `game_number` only with an
  `evidence_source`. The matcher does not invent native game-number/lifecycle
  parsers from unverified fields. Current captures supply no doubleheader numbers;
  the example uses explicitly labeled synthetic fields for these cases.
- Conflicting supplied game numbers split candidate games. Time-separated repeats
  can form separate groups; equal participants and date alone never merge them.
  A listing with insufficient schedule/game evidence that connects several games
  makes the connected candidate set ambiguous.
- Generate deterministic candidate components, then require **every pair** in a
  group to satisfy constraints. A–B and B–C proximity cannot override A–C failure.
  Distinct native event IDs at the same venue make the set ambiguous, even at an
  identical time. This conservatively handles duplicate/recreated listings and
  indistinguishable repeated games. Duplicate observations of one scoped native
  reference do not count as additional listings.

Outcomes: `matched` means a confirmed cross-venue group; `candidate` means a
possible group lacks required evidence; `ambiguous` means multiple or mutually
inconsistent possibilities; `conflicting` means explicit incompatible evidence;
`unmatched` means no confirmed peer. A fully resolved, scheduled singleton gets a
canonical ID while its mapping stays unmatched. An unresolved singleton does not.

The report's comparisons are **pairwise compatibility only**, marked
`comparison_only: true`. The separate `automatic_match` flag is true only when
both current mappings are matched to the same canonical event. For example,
two sandbox listings can have compatible times yet remain ambiguous because
they are different native events at the same venue. Distant starts are recorded
as schedule conflicts with the reason that repeat-game versus reschedule identity
is unresolved; they are not automatically treated as the same game.

## Stable identity, revisions and explicit review

Initial IDs are `event-` plus 24 hex digits of SHA-256 over the sorted complete
creation set of scoped native keys. A fresh complete batch produces identical IDs,
observations, decisions and revision history regardless of input order. IDs never
include a mutable schedule or participant orientation. Store the initial batch
before collecting more data. Different **batch boundaries** can produce different
initial IDs: this is intentional because a previously persisted singleton must
retain its identity when another listing arrives. Persisted identity takes priority
over renaming it to the ID a later full rebuild might choose. Two existing
canonical IDs are never automatically collapsed.

Canonical records retain their creation keys and initial evidence. `report().events`
projects current listing schedules, roles, game numbers, mapping status and all
observation hashes onto those records. A retained ID on a conflicting mapping is
historical linkage, **not current confirmation**.

Changed evidence for an existing native reference is retained as pending and
produces a conflicting mapping, preserving its prior canonical ID and accepted
observation. Neither observation arrival order nor receipt timestamp silently
chooses a winner. A batch with mutually conflicting first observations has no
accepted current observation. Confirmed groups are checked as a whole, including
pending evidence, so a schedule change cannot bypass constraints by moving into
a different candidate component.

The bounded review API supports schedule/lifecycle corrections on an already
accepted, resolved native identity:

```python
matcher.review_schedule(
    key, new_observation_hash,
    reason='Documented schedule correction',
    actor='actual reviewer identifier',
    source='local evidence reference',
)
matcher.save(path)
```

Reason, actor and source are required and stored with old/new hashes. League,
participants, roles, game number, registry and environment must be unchanged.
Identity conflicts and ambiguous recreated listings remain unresolved; this API
cannot force them into a canonical event. Corrections affecting a cross-venue
group remain conflicting until its accepted schedules agree again. Initial and
corrected observations remain available, and the canonical ID is preserved.
The example's sole review is explicitly synthetic, not an owner decision.

Each changed mapping stores a numbered revision and prior/new decision. Identical
replay creates no new observation or revision. Explicit reviews also have their
own provenance log. Review transitions may produce a candidate revision before
final re-evaluation; each is retained in the audit chain.

The store is a single-writer local JSON snapshot with content checksum. Exported
JSON deduplicates raw response bodies into `raw_payloads`, keyed by SHA-256;
`json_text_sha256` references preserve the exact body for each observation.
`Matcher.load()` restores the original envelopes and validates their full hashes;
`expand_raw(report_without_raw_payloads, raw_payloads)` restores exported reports. Writes
use a sibling temporary file, file fsync, atomic replacement and directory fsync.
Load rejects duplicate keys, checksum changes, unsupported schema/matcher versions,
invalid observation/reference hashes, broken revisions and invalid review links.
Unchanged old snapshots survive a failed replacement; orphan temporary files are
not loaded. There is no concurrent-writer locking, automatic schema migration,
cryptographic authenticity claim or database dependency.

## Actual capture coverage

| Scope | Observations | Distinct scoped native events | Canonical events | Mapping outcomes |
|---|---:|---:|---:|---|
| Production captures | 15 | 15 | 10 | 10 matched listings in 5 pairs; 5 unmatched singletons |
| ProphetX sandbox captures | 32 | 32 | 4 | 28 ambiguous listings across 14 repeated-listing pairs; 4 unmatched singletons |

The 47 observations happen to have 47 distinct scoped native references in this
input; that is **not 47 established sporting games**. Ambiguous sandbox references
are not assigned invented game counts. The four sandbox singletons are New Orleans–
Detroit, Baltimore–Dallas, Indianapolis–Washington and Jacksonville–Philadelphia.
No sandbox reference counts as production venue coverage. No MLB or Novig live
matching coverage is established.

All five production pairs have equal starts at **2026-09-13 17:00:00 UTC**, resolved
NFL identities, no explicit mapped role conflict, and no supplied game number.
Kalshi's unassociated home/away UUIDs are retained without guessing their team
relationship. Exact native references:

| Participants | Kalshi event | Polymarket US event |
|---|---|---|
| Atlanta / Pittsburgh | KXNFLGAME-26SEP13ATLPIT | 74903 |
| Baltimore / Indianapolis | KXNFLGAME-26SEP13BALIND | 74902 |
| Buffalo / Houston | KXNFLGAME-26SEP13BUFHOU | 74908 |
| Chicago / Carolina | KXNFLGAME-26SEP13CHICAR | 74901 |
| Cleveland / Jacksonville | KXNFLGAME-26SEP13CLEJAC | 74904 |

The other production singletons are Tampa Bay–Cincinnati, New York Jets–Tennessee,
New Orleans–Detroit, Green Bay–Minnesota and Arizona–Los Angeles Chargers.

[Full report](../evidence/slice-7/matching-example.json) contains canonical IDs,
attached listings, all source hashes, registry identities, comparison deltas,
reasons and separately labeled synthetic doubleheaders, missing starts, role
conflicts, transitive conflicts, cancellation/recreation and reschedule history.
[Persistent captured store](../evidence/slice-7/captured-store.json) is restartable.

## Verification and boundary

**176 offline tests pass**, including 25 focused matcher tests. All six existing
examples and the new matching example exit 0. Matcher capture replay blocks socket
connections. Tests cover the requested identities, orientation, aware timing,
tolerance boundaries, doubleheaders, missing schedules, duplicate/recreated native
listings, transitivity, input-order independence (including actual captures),
conflicting updates, stable reschedules, provenance, environment isolation,
restart in a fresh process, audit validation and atomic-write failure recovery.

[Verification commands and logs](../evidence/slice-7/verification.json),
[artifact identities](../evidence/slice-7/manifest.json), and
[preservation check](../evidence/slice-7/preservation.json) record the result.
PLAN.md, credentials, shared models, normalization, adapters and all historical
evidence remain unchanged. README and the Desktop tracker are updated.

This slice establishes sporting-event identity only. It does not establish market
or moneyline equivalence, complementary outcomes, settlement compatibility,
tradability, fees or executable arbitrage. ProphetX quantity/clock/live-selection
limitations and Novig credentials/live verification remain separate dependencies.
No account access, live collection, venue contact, commits, pushes or publishing
occurred. **Slice 8 — moneyline market matching is next; it was not started.**
