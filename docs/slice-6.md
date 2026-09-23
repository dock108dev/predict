# Slice 6 — team and league normalization

Completed September 12, 2026 UTC. Registry `2026-09-12.1`, schema 1. The next project action is **Slice 7 — canonical event matching**. This slice does not establish event equivalence, home/away orientation from title order, line equivalence, settlement compatibility or trading eligibility.

## Behavior and public API

`app.normalization` exports `Registry`, `resolve_team`, `resolve_league`, and `enrich_event`. Load a registry once and reuse it:

```python
from app.normalization import Registry, enrich_event, resolve_team
registry = Registry.load()
team = resolve_team('DAL', league='NFL', registry=registry)
normalized = enrich_event(observation, environment='production', registry=registry)
# Normalized.observation is the original immutable shared Event.
# Normalized.participants[i].resolution.canonical_id is usable by Slice 7.
```

The package includes `registry-v1.json`. Internal IDs such as `NFL:DAL` and `MLB:NYY` are assigned keys, independent of mutable display names. NFL and MLB are the only registered leagues. There are 32 NFL and 30 MLB teams; NCAAF, NBA and NHL remain planned and return unknown. No college-team completeness is implied.

Results carry `resolved`, `ambiguous`, `unknown` or `conflicting`, sorted candidate IDs, a canonical name/ID only on resolution, original input name/native ID, registry version, registry content hash and the alias/mapping source. Case, whitespace, periods, typographic apostrophes and hyphen word boundaries normalize deterministically. Digits, accents and word boundaries remain significant. No fuzzy matching, LLM, automatic learning or permanent writes occur during lookup.

Full canonical names/IDs can resolve without league context. Shorthand with one candidate still requires league context because unregistered leagues could reuse it. Multiple candidates remain ambiguous: `CIN`, `Giants`, `Cardinals`, and shared cities. `New York` in NFL yields Giants and Jets; `Los Angeles` yields Chargers and Rams. Venue-specific aliases contribute explicit candidates; they never silently override contrary global evidence.

Native mapping keys include entity kind, venue, environment, canonical league (teams only), and exact native ID. Missing native scope returns unknown. A mapped ID with a contrary or unrecognized supplied name returns conflicting. An unmapped ID can accompany independent name resolution, explicitly marked `native-id-unmapped; name-only-resolution`; it is never learned as a mapping. Synthetic tests demonstrate reuse of one native ID in different environments.

Historical names absent from these captures, such as Oakland Raiders, remain unknown. The schema can explicitly attach a historical alias to a stable entity, with league/venue scope and a source, after verification; it does not globally merge names or separate franchises. No unsupported historical mapping was added.

## Registry sources and storage

Current membership and full names were checked directly against the [NFL team directory](https://www.nfl.com/teams/) and [MLB team directory](https://www.mlb.com/team) on September 12 UTC: 32/32 and 30/30 names matched. These are membership sources; internal keys and shorthand aliases are curated local choices, not claims about official identifiers. Current MLB includes Athletics under `MLB:ATH`.

[Official check](../evidence/slice-6/official-source-check.json) records retrieval times, HTTP results, response hashes and checked names. Each registry entity/alias/mapping also names its source. [Registry builder](../evidence/slice-6/build_registry.py) reproduces the curated file and capture-derived mappings. It is a maintenance tool, never run by ingestion. Change the version when deliberately changing mapping semantics, retain old registry artifacts for historical replay, and preserve assigned IDs across display-name changes.

`Registry.load(path)` validates references, kinds, league scope, required sources, unique entities, duplicate JSON keys, canonical-name uniqueness, duplicate/conflicting alias rows and native keys. Intentional ambiguous aliases use one explicit candidate set. `save(path)` writes the validated registry via atomic replacement; restart with `load(path)`. Read-only indexes prevent accidental mutation of the active lookup snapshot. No database, Redis or administration UI is required.

## Actual observation integration

Adapters are unchanged. Enrichment consumes their shared `Event`, locates its native row by exact event ID in the retained response, and preserves the complete original observation including source, timestamps, evidence kind, raw JSON and schedule. The wrapper adds identities, extraction rules and participant positions. It never assigns `Event.canonical_id`.

| Venue | Extraction and native identity evidence |
|---|---|
| Polymarket US production | Prefer event `teams[]` with `id`, `name`, `league`; league ID/name from response `league`. Preserve array order and `ordering` only when explicitly supplied on that participant. The captured event-team arrays have no home/away labels; market-side roles are not transferred by guess. 20 established team mappings and one league mapping from Phase 0. |
| ProphetX sandbox | Prefer `data.sport_events[].competitors[]` with exact `id`, `name`, `side`; `tournament_id/name` identifies the league. Preserve competitor order, which starts with home in the sample. 55 native team IDs identify 28 teams, plus one league mapping. Multiple IDs naming one team are retained as separate mappings. No production transfer. |
| Kalshi production | For exact series `KXNFLGAME` / `KXMLBGAME`, the anchored two-name `A vs B` / `A vs. B` title rule resolves names in series league context. Multiple delimiters and other formats remain unknown. Captured milestones have home/away UUIDs but no established UUID-to-name relationship, so native roles stay separate and unmapped. No market/event ticker is treated as a team ID. |
| Novig | No live capture establishes native team mappings or a reliable title grammar. Explicit shared `Event.participants` can resolve independently; title-only observations remain unknown. Demonstration data are synthetic, with zero live coverage. |

Supplied shared league and participant names are checked against selected structured evidence; disagreements are explicit. Team/event league disagreement is conflicting. Unresolved event league prevents automatic participant resolution. IDs and home/away labels are retained separately from identity and no event matching is performed.

## Offline demonstration and measured coverage

```sh
.venv/bin/python -m app.normalization_example
```

The JSON result is intended for direct consumption by the next slice: native event identity, schedule, original-source hash, league resolution, ordered participant resolutions, explicit native roles and extraction provenance. It is not a list of matched events. Evidence class, venue, environment and league separate coverage buckets.

| Evidence class / venue | NFL events | Participant resolutions | Unique NFL teams |
|---|---:|---:|---:|
| Actual capture / Kalshi production | 5 | 10 resolved | 10 |
| Actual capture / Polymarket US production | 10 | 20 resolved | 20 |
| Actual capture / ProphetX sandbox | 32 | 64 resolved | 28 |
| Synthetic / Novig QA | 2 | 1 resolved, 1 unknown; one event has no extracted participants | 1 |

All 94 participant occurrences in 47 actual captured NFL events resolve. Counts are observation counts, not cross-venue unique games. The preserved inputs are `evidence/phase-0/pmus-nfl-events.json`, Slice 3 qualification attempt-1 `market-002.json`, and Slice 4 public `rest-00.json` / `rest-01.json`, with original capture metadata restored through existing adapter ingestion. [Output](../evidence/slice-6/normalization-example.json) contains exact input paths and provenance.

The evidence JSON inventory found no structured MLB team entities. MLB has 30 registry entries, zero actual captured MLB events in this demonstration, and two separately labeled documentation examples (Yankees / Red Sox). Synthetic edges separately show shared-city and cross-league ambiguity, unknown names, native/name conflicts and unsupported leagues. Novig synthetic success is not live qualification.

## Verification and boundary

151 offline tests pass, including 13 focused normalization tests. All five existing examples and the new normalization example exit 0. Tests cover membership, difficult aliases, unknown context, scoped IDs, conflicting evidence, validation, persistence, identical fresh-process results, captured adapter replays, observation preservation and separately labeled synthetic cases. Replay tests prohibit socket connections. Exact commands, exit statuses and logs are in [verification.json](../evidence/slice-6/verification.json).

[Artifact manifest](../evidence/slice-6/manifest.json) records SHA-256 identities. [Preservation check](../evidence/slice-6/preservation.json) verifies PLAN.md, adapter/model implementations, credentials file and all prior evidence against the pre-change snapshot. Historical artifact manifests remain unchanged.

Kalshi and Polymarket US retain their bounded qualifications. ProphetX quantity/clock/live-selection limitations remain separate. Novig venue-issued OAuth credentials and live wire qualification remain a parallel external dependency. No venue onboarding, account access, messages, trading, funds, purchases, Git operations or publishing occurred. Stop before Slice 7 implementation.
