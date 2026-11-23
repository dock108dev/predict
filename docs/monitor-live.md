# Discovery and saved-game collection

Automatic SGO discovery runs 24/7 at :20 and :50 each hour, targeting games in
the next 24 hours. Newly discovered games receive one full early research
snapshot. Saved games then wait for their scheduled T−10 snapshot; Monitor no
longer adds a separate per-game alternate pass, and viewing in Live does not
start repeated paid odds requests. Bounded postgame sporting-result follow-up
remains separate. Timing and scope remain subject to source, account and storage
controls.

Recorded Live intent, settings and historical captures are preserved. They do
not override the current discovery-and-checkpoint acquisition policy. Ordinary
SGO collection stays pregame-only even if the legacy `live_enabled` setting is
true. Kickoff, started/cancelled status and changed scope can make a request
ineligible before dispatch.

## Controls and scheduling

Data is the game-oriented received-data browser. Positive EV and arbitrage are
calculation views within Data; frozen checkpoints and saved captures keep their
own evidence clocks. Experiments contains first-observation/T−10 evaluation and
declared populations. Settings replaces the broad Admin interface with essential
operating controls. [Workspace guide](personal-data-workspace.md)

`GET /api/pregame?mode_status=1` exposes public mode status. Protected
`GET/PATCH /api/admin/activity-mode` reads or changes settings, and
`POST /api/admin/activity-mode/activity` records genuine owner interaction.
Legacy Live intent can expire without changing historical evidence. Reads,
polling, refreshes and background updates do not issue paid provider requests.
Mode changes cannot clear source Stop choices or pauses.
Settings shows the active discovery/checkpoint policy, next discovery and pending
checkpoint, reported credits/holds and finite storage. Changing settings still
requires owner authentication.

Monitor uses fixed clock slots. A restart can claim a recent slot once; older
missed startup slots are skipped to avoid catch-up bursts. Active overruns and
budget delays coalesce the latest overdue slot, then return to the clock schedule.
Timing edits preserve active work; horizon changes still revoke out-of-scope work.
Discovery pages keep one start-window cutoff across their pagination. Separate
saved-game refreshes are omitted before dispatch. The experiment's existing
collector independently owns first capture, exact T−10 timing and bounded
postgame checks; browser activity does not drive those clocks. Scheduled starts
do not imply simultaneous quote arrival or completion before every kickoff.

Fresh scope, archive-backlog and Stop/pause checks run before transport. Pending
T−10 requests keep their existing shared request/object headroom. Provably unused
reservations can be released; unknown charges retain their exposure.

## Provenance and calculations

Each admitted page retains its collection mode and run identity, scope, settings
revision and completion state. A Monitor run completes after its discovery
traversal. Delayed or interrupted runs stay partial.
Source, receipt and retained-observation clocks remain distinct.

Separate working cohorts preserve their own prices and references. Missing inputs
cannot be borrowed from the other mode to produce EV. The combined Odds set is
maintained during collection, keeping ordinary reads indexed. Recalculation or a
new capture receipt never renews the original source quote timestamp. Known
withdrawals and started/cancelled games invalidate claims across cohorts.

Retained prices adopted as a `legacy_retained` Monitor baseline remain identified
as retained evidence, not new provider observations. Authentic saved captures are
supported; production Practice navigation and synthetic replay are retired.

## Budgets and retention

The mode collector caps returned-event objects at 300 per rolling 15 minutes and
16,800 per rolling day. These counters are distinct from Odds API credits.
Stricter provider-account pacing, reserves, holds, interrupted exposure, request
rates, reset rules and source controls still apply. Wider discovery horizons
consume more allowance. Budget-delayed runs remain visible rather than being
labeled fresh, complete captures.

SGO charges returned top-level event objects, with a minimum charge for an empty
response. The existing :20/:50 clock itself saves nothing. Removing the separate
per-game alternate and Live calls saves their actual returned-object charges.
League discovery still bills saved games that it returns: the documented API
does not support excluding arbitrary known IDs. Filtering those objects after
receipt would not save credits. This preserves discovery of newly listed games
and reschedules instead of silently skipping already-scanned kickoff times.
See the provider's [billing FAQ](https://sportsgameodds.com/docs/faq) and
[event filters](https://sportsgameodds.com/docs/endpoints/getEvents). Initial
discovery and the first full checkpoint remain distinct guarded responses.

Every collected snapshot, including unchanged inputs, is staged durably and
exported with source clocks and calculation evidence. Export verifies hashes and
read-back before acknowledging staging. Verified gzip shards have no automatic
expiry deletion; working cohorts are pruned at kickoff.

Retention status reports staged bytes, verified/skipped observations, oldest
staged age and last verification time without exposing archive paths. A 32 MiB
staging backlog pauses new acquisition. Historical gaps remain disclosed but do
not permanently block collection after the backlog drains. Export preserves
512 MiB of destination free space; finite storage still requires capacity planning.
A host archive is not an off-host backup.

`deploy/configure-retention.sh` preserves an existing owner destination. To export
staged records without waiting for shard age, use:

```sh
.venv/bin/python -m app.storage.odds_archive_export --flush
```

See [archive operations](odds-archive-operations.md), [source configuration](configuration.md)
and [deployment](hetzner.md). Delayed feeds, available depth, sustained collection
cadence and actual fills remain separate limitations; see [liquidity](liquidity.md).
