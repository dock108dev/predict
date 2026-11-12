# SportsGameOdds operations foundation

## November 11 running state and account controls

The local configuration runs SGO on Rookie alongside independent Kalshi and
Polymarket US workers. The November 11 local reload confirmed the collector
counters, batch admission and split reference and frame SQL timings. The
observed slate selected a 15-minute live target and 72-hour repeat discovery.
Its combined projection was 4,166.33 objects/day against a 4,770 allowance.
The rolling budget guard remained active. Measure spending and source-clock
freshness together over wider operating windows. The dated measurements are
in `docs/sgo-paid-observation-20261111.md`, and `NEXT_STEPS.md` tracks
the remaining integrated work.

The provider reported a 100,000-object limit, 50 requests per minute and no
reset timestamp. The worker uses the owner-directed **00:00 UTC on the first
of each month** as a provisional pacing boundary. Use fresh provider usage
and remaining allowance, retain reservations and uncertain exposure across
the boundary, and require authoritative evidence before recognizing
replenishment. Retain The Odds API's accounting separately. The startup
control checks, rejected-cursor hold and resumption after an independently
evidenced resolution have controlled coverage. Automatic request-specific
charge attribution and live rejection recovery remain unverified.

SQL verified bounded SGO history near its 32 MiB logical cap. Capacity
evictions can reduce effective retention below the seven-day age limit.
Current facts and pinned originals retain their separate authority.

The ordinary desk also supports the highest-payout same-book de-vig basis
using FanDuel, DraftKings, BetMGM and Caesars on the existing account. The
price and reference clocks govern currency independently of polling.
The [configuration guide](configuration.md) explains the SGO key and safe
opt-in. Use the [coverage contract](broad-coverage.md) for the offered-data
denominator and sustained coverage target.

## November 10 foundation and evaluation record

The following observations describe the earlier evaluation configuration and
account. The November 11 section above records the running selection and
supersedes the earlier pacing and reset requirements.

The existing protected evaluation credential was checked against the provider's
`/v2/account/usage` endpoint on November 10, 2026. The response explicitly
identified the active tier as **amateur**, with 10 requests per minute and 2,500
objects per month; 11 monthly objects had been used. It did not supply an
account reset timestamp. The credential is not reproduced here. This identifies
only the configured evaluation key, not any other account or the paid plan the
owner described. Paid coverage, limits, object reset, and update cadence remain
unverified for this key. No subscription was purchased and no event collection
was performed in this check.

The isolated scheduling primitives in `app/collection/sportsgameodds_schedule.py`
rank due live, imminent, near and distant events at illustrative intervals of
15 minutes, 30 minutes, 3 hours and 12 hours. These are starting policy values,
not an observed affordable production schedule. They suppress work on Stop or
pause, reject duplicate IDs and invalid clocks, and use receipt time only for
scheduling, never as a substitute for a quote's source clock. The accounting
helpers distinguish objects from requests, apply the minimum one object for an
empty response, reserve headroom and outstanding exposure, and require an
explicit reset time for pacing. The caller must persist a reservation before
dispatch, bound the response to the reservation, and retain uncertain exposure
until an authoritative reconciliation. A 429 should pause dispatch through its
reported retry time and must not silently release an uncertain reservation.

The separate `sportsgameodds_ledger.py` foundation persists atomic object
reservations, a conservative one-in-flight rule, bounded request-rate history and a source pause, retains uncertain requests through restart and across account windows,
and records a durable retry deadline for 429s. A response that exceeds its
reservation latches a pause until the overrun is explicitly recorded. It uses
its own prefixed tables and never changes The Odds API records. The caller must
identify one provider account window and avoid opening overlapping windows or
ignoring use by other clients; an initial usage snapshot alone cannot observe
external use. An unknown reset is retained as unknown, not guessed.

Each ledger uses a persistent, randomly assigned accounting identity independent
of the API key. Replacing a key does not reset its rate history or bypass holds.
An existing ledger with one legacy identity keeps that identity and its records;
multiple legacy identities fail closed until their accounting is reconciled.
Use a separate ledger only for a genuinely separate, reconciled account.

A guarded collector and runtime worker now bind these controls to bounded
transport and serialized current-row ingress. Provider selection and source
pause preserve the direct native workers. The worker requires a fresh matching
account usage observation and explicitly evidenced reset, counts usage calls
and event calls in one durable request-rate history, applies a rolling daily
object pace, and refuses another request while a charge is uncertain. It walks
two-event pages in bounded turns and retains incomplete cursors for later turns.
Moving or incomplete traversals never authorize removals. It retains event IDs
in memory, discards payloads after admission, and publishes only source-attributed
current rows. The two-event bound reflects the free capture size, not a paid
feed measurement or guarantee. The 15-minute polling and 12-hour discovery
intervals are provisional; account-specific affordability and paid coverage
have not been measured.

The ordinary configuration still selects The Odds API. The configured
evaluation account's response did not supply a reset, so the SportsGameOdds
worker fails closed before event requests. The current usage reader also
requires finite numeric object and request limits; unlimited-plan handling and
authoritative recovery from uncertain charges remain unverified. The runtime
worker and current-row adapter require end-to-end paid-feed, matching, reference,
EV and user-journey verification before cutover. Do not infer a reset time
from a published rolling-month description or treat provisional cadences as
proof that a 2,500-object account can sustain the requested scope.
See [provider limits](https://sportsgameodds.com/docs/info/rate-limiting).

The runtime persists a separately keyed `sportsgameodds` source status; it does
not overwrite direct Kalshi or Polymarket US source health. Successful page
admission commits product, reference facts and compact event-frame evidence together,
with receipt, event scope and exact reference-membership checks. Migration 072
is required before frame admission. Explicit source pause and global Stop revoke admission. Local
request pacing waits before trying again; a provider 429 or uncertain request
retains its reservation and does not automatically retry until reconciled.

Validation used synthetic fixtures and a disposable PostgreSQL 14 compatibility
cluster. Those tests do not establish paid entitlements, live coverage, schedule
cost or end-to-end app behavior. The configured key reports Amateur and 11 of
2,500 objects used; its documented usage endpoint returned no reset field. No
paid event requests or subscription purchases were made during integration.

When the configured aggregate provider changes, ordinary result reads mark the
other provider's retained prices historical and withdraw its reference authority.
The latest-board context excludes the inactive aggregate provider, and the raw
Odds API view labels its retained entries last-known. Direct native prices and
pinned original evidence remain intact. These are read-time safeguards; the
underlying historical rows and protected accounting records are preserved.
