# Monitor and Live collection

The SQL data runtime now has two collection clocks. Monitor starts by default,
collects the next 24 hours every 30 minutes, and continues while Live runs.
Live targets only pregame events starting within the next 60 minutes, every
60 seconds. Fifteen minutes without explicit owner input returns the effective
mode to Monitor. All intervals, the two horizons and inactivity are configurable.
These are acquisition targets, not test windows or promises to bypass spending,
rate, source, storage or account controls.

The mode is independent of the older `live_enabled` in-play switch. Its Live
requests remain pregame-only even if that older flag is true. A kickoff, explicit
started/live state, changed window, owner mode change or inactivity can revoke an
exact-event request before dispatch. A one-hour window includes its upper edge;
a game starting now is excluded. A game 61 minutes away can enter the next Live
run two minutes later without renewing its stored source timestamp.

## Controls and provenance

`activity_mode` stores owner intent and settings in PostgreSQL. Protected
`GET/PATCH /api/admin/activity-mode` reads/changes it. Explicit owner activity uses
`POST /api/admin/activity-mode/activity` with `{}`. Ordinary GETs, status polling,
page refresh and background updates never renew inactivity. The existing Caddy
Admin authentication and same-origin JSON boundary protect mutations. Public
`GET /api/pregame?mode_status=1` reads the status object.

Status includes effective `mode`, stored `requested_mode`, `revision`, `settings`,
`last_activity_at`, `live_until`, `reason`, latest `runs`, aggregate `retention`
and the additional operating budget's object units. It contains no archive path
or account credentials. Control/status timestamps serialize in UTC; original
quote timestamps are not changed. A disposable SQL check caught a local
PostgreSQL session returning Eastern offsets before this normalization.

Each admitted SGO page carries both `collection_mode` and a `collection_run`:
`id`, `kind`, `started_at`, `scope_start_at`, `scope_end_at`, `settings_revision`
and `completed`. Page ingestion records the run even when prices are unchanged.
Monitor first walks all configured leagues within its fixed window, then performs
the existing supported alternate-line request for every discovered eligible
event. Live uses those exact-event alternate requests for its selected near games.
Alternate requests keep the existing four market venues and trusted-book filter.
A run becomes complete only after its main traversal and alternate pass finish.
Budget/rate waits keep the run and cursor incomplete; restart or changed settings
retain partial status rather than inventing missed observations.

Monitor's due time is separate from Live's. Selecting Live does not reset Monitor's
clock. Live and Monitor take turns. If shared capacity delays one kind, that
waiting kind owns the next released slot; frequent Live work cannot repeatedly
consume Monitor's headroom. Source Stop and pause choices remain separate
authoritative controls; selecting a viewing mode cannot clear or recover them.

A fresh dispatch check is necessary even after account usage was read:

```python
status = (self.activity_reader or read_control)(at=self.now())
```

The collector supports this asynchronous eligibility check before reservation and
immediately before transport. Each check reads fresh mode settings and current
archive staging bytes. After the final await, it reads Stop/pause controls again.
Controlled barriers verify owner mode changes during account lookup and after
reservation, Stop/pause changes during the final eligibility wait, archive backlog
reaching its limit between Live and Monitor, and eligibility error/cancellation
before transport. These cases dispatch no provider request; any provably unused
reservation resolves at zero. Once transport is invoked, unknown charges still
retain exposure.

## Account, rate and retention limits

SGO charges returned event objects, with an existing minimum of one object for an
empty response. Markets and sportsbooks inside an event do not multiply this
counter. The mode collector adds conservative limits of **300 returned-event
objects per rolling 15 minutes and 16,800 per rolling day**. These are not a claim
that an SGO object equals an Odds API credit in money. Existing stricter provider
account pacing, account reserve, holds, interrupted exposure, request rate, reset
rules and Stop/pause guards remain unchanged. Denials report `budget_delayed`;
requested cadence is not silently stretched or relabeled as completed acquisition.

A read-only installed account sample at `2026-11-19T04:05:59Z` showed a 100,000-object
account, 50 requests/minute, 66,574 available objects after existing accounting,
and a computed daily allowance of about 5,970. Its December 1 pacing reset was
labeled an existing calendar-month assumption, not a provider-reported reset.
No accounting state or uncertainty was reset for this feature.

Retained schedule counts at the assessment were 45 provider events within 24 hours,
290 within 72 hours and 769 across all future dates. At 30-minute cadence:

| Scope | Main-only lower estimate/day | Main plus alternate pass/day |
| --- | ---: | ---: |
| Next 24 hours | 2,160 | 4,320 |
| Next 72 hours | 13,920 | 27,840 |
| All retained future events | 36,912 | 73,824 |

These estimates assume a constant slate and exclude empty/terminal-page and retry
cost. Empty-league overhead can add objects; Live consumes additional allowance.
The selected 24-hour default fits that sample's pacing before Live. Broader horizons
can be selected, but full 30-minute completion is unaffordable in that sample and
will wait visibly for budget. Concurrent near games can also exhaust the rolling
15-minute limit. The account's advertised feed delay remains separate from how
often requests are made; polling every minute cannot guarantee a new source price.

Retention status comes from committed SQL staging, verified export and skipped
observation counters, not the web container's environment flag. It reports
`awaiting_first_capture`, `retaining`, `delayed` or `gaps`, staged bytes, verified
and skipped observations, oldest staged age and last verification time. A backlog
of **32 MiB** pauses new paid requests with `archive_backlog` and a 30-second retry.
This leaves room below existing staging capacity for a paid page and its derived
copies. Historical skipped counts remain disclosed but do not permanently stop
collection once the current backlog drains. Persistent storage capacity and an
off-host backup are separate from source/API availability; no TTL deletion was
introduced by the mode controller.

## Evidence and practical limits

The final focused Activity mode/worker/collector check passed **61 tests**
with no failures, errors or skips in 0.702 seconds
(`.local/modes/dispatch-final.xml`). Earlier scheduler coverage also passed. They exercise Monitor continuation through Live, the 30-minute boundary,
15-minute expiry without polling renewal, kickoff/window edges, explicit in-play
exclusion, source Stop/pause, held/interrupted exposure, both operating caps,
current archive backpressure, fresh dispatch revocation, final-await Stop/pause
and cancellation boundaries, alternating progress when only one object slot is
released per cycle, and original-clock provenance. The ordinary financial ledger remains the reservation owner.

Disposable PostgreSQL owner-control/API/retention checks passed **3 tests**. They
verify settings persistence, explicit activity versus passive reads, expired Live
not reactivating on a late heartbeat, unchanged source controls/configuration,
run states, and SQL-backed retention without exposing paths. No real provider
request was made by those tests. Local mode delivery still requires the normal
integration/deployment verification recorded in the sprint handoff; these fixtures
do not establish a sustained live feed or executable order size.

Learning update: One shared receipt clock would let fast Live polls postpone Monitor, and cached mode intent could survive an owner change during account lookup | use independent run clocks and fresh durable dispatch authority, while retaining original source clocks | controlled-clock and barrier checks pass without a 30-minute observation window | deployed collection and archive verification remain separate.
