# Monitor and Live collection

Monitor is the default collection mode. It targets games starting in the next
24 hours every 30 minutes, with scheduled starts at :20 and :50 by default.
Live is an explicit authenticated switch that adds one-minute collection for
pregame games starting within the next 60 minutes. Monitor continues during Live.
Fifteen minutes without owner interaction returns the effective mode to Monitor.
Collection settings expose the intervals, horizons, Monitor phase and inactivity
period; cadences are targets subject to source, account and storage controls.

Live describes collection intent, not in-play scope or order execution. The
ordinary SGO mode collector stays pregame-only even if the legacy `live_enabled`
setting is true. Kickoff, started/cancelled status, changed scope or revoked Live
intent can make a request ineligible before dispatch.

## Controls and scheduling

EV and Arbitrage default to the effective mode. Browse Odds consolidates the
latest observations across both modes without duplicating contracts. More filters
exposes cohort, quote age and ordering controls. Probability edge is the default
EV ranking; explicit saved ranking choices persist.

`GET /api/pregame?mode_status=1` exposes public mode status. Protected
`GET/PATCH /api/admin/activity-mode` reads or changes settings, and
`POST /api/admin/activity-mode/activity` records genuine owner interaction.
Pointer, keyboard, touch and wheel activity can renew Live. Reads, polling,
refreshes and background updates do not renew activity or collect provider data.
Mode changes cannot clear source Stop choices or pauses.

Monitor uses fixed clock slots. A restart can claim a recent slot once; older
missed startup slots are skipped to avoid catch-up bursts. Active overruns and
budget delays coalesce the latest overdue slot, then return to the clock schedule.
Timing edits preserve active work; horizon changes still revoke out-of-scope work.
Known near-start events receive alternate refreshes in kickoff order before bulk
league discovery, followed by remaining eligible events. An event is not refreshed
twice in one round. Scheduled starts do not imply simultaneous quote arrival or
completion before every kickoff.

Live and Monitor take turns when capacity is constrained. A waiting kind owns the
next released slot so frequent Live requests cannot starve Monitor. Fresh mode,
archive-backlog and Stop/pause checks run before transport. Provably unused
reservations can be released; unknown charges retain their exposure.

## Provenance and calculations

Each admitted page retains its collection mode and run identity, scope, settings
revision and completion state. A run completes only after its main traversal and
supported alternate-line pass finish. Delayed or interrupted runs stay partial.
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
rates, reset rules and source controls still apply. Wider horizons, alternate-line
passes and concurrent Live requests consume additional allowance. Budget-delayed
runs remain visible rather than being labeled fresh, complete captures.

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
