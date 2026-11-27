# First observation versus ten minutes before start

The **Experiments** tab now starts with [paper portfolios and backtests](paper-experiments.md).
The original comparison inspector remains under **Checkpoint evidence**.

Policy `first-observed-24h-vs-tminus10-screen-ev-1` is the primary automatic
research workflow. It replaces daily population polling and the one-hour
checkpoint scheduler. Existing cohorts, observations, outcomes and exports are
preserved. An immutable activation record documents the scheduling transition.

## Timing and discovery

The first eligible observation under this policy starts tracking when a game's
scheduled start is within the next 24 hours. An event already known at policy
activation is explicitly marked `policy_activation_existing_game`; its earlier
source metadata receipt remains separate. Its early baseline comes from a new
guarded event-specific response, never a reconstructed old frame. This is the
first observation by this experiment, not a claim about the first-ever provider
observation or an assumed T−24h price. Actual discovery, dispatch, receipt,
calculation finish, knowledge, persistence and remaining-to-start clocks survive.

The late request targets T−10 minutes. Its engineering tolerance is the recorded
interval from that target through T−9 minutes. A response, calculation or
persistence after the deadline cannot fill that checkpoint. No browser action
controls scheduling. A source reschedule appends a revision and retargets the
late task; it never moves the frozen early baseline. Changed schedule/settlement
continuity and reversed observation order remain explicitly incomplete.

The owner-selected credit-saving policy keeps automatic league discovery at
:20 and :50 each hour, 24/7. Separate Monitor alternate passes and repeated Live
odds polling are retired; an already saved research game waits for its T−10
checkpoint. Discovery and the first full snapshot are distinct acquisitions.
SGO still bills known games returned by league discovery; there is no documented
exclude-known-ID filter. No source-price freshness is invented between captures.

Late discovery still receives one actual early snapshot before game start. If
discovery is already at/after the T−10 target, late is marked missing and no
second paid request invents a pre-target baseline. A positive available early
result remains an incomplete case. Cancellations, missed windows, uncertain
requests and capacity refusals have durable operational dispositions.

## Exact bets and measurements

An experiment bet includes canonical participants/event, provider, original
bookmaker, represented venue, market, period, outcome, exact selected line and
material settlement semantics. A spread of −3 and −3.5 are different bets.
Clocks, availability and main/alternate roles do not change exact bet identity.

Selection uses unrounded conservative screening EV exclusively:

`retain_case = early_screen_EV > 0 OR late_screen_EV > 0`.

Zero remains zero. Unknown fees, missing quotes and unsupported semantics remain
null with reasons. Negative/negative bets remain in shared game context without
separate cases. Coherent-baseline probability and EV retain their own labels and
policy versions. A third calculation applies the late probability to the early
cashflows, preserving original price, quantity, fees and comparison basis.

Each checkpoint requests the six supported full-game team-point outcomes and
all available alternates for four offer books plus FanDuel, DraftKings, BetMGM,
Caesars and the existing BetOnline reference capability. Coverage distinguishes
requested, received, normalized, missing and incomplete surfaces. Received lines
with no price keep their identity and source role while remaining unavailable.
Per-book main roles come from that book's SGO primary/alternate entries; native
execution and settlement authority remain unestablished. Reference books have
price context and their own main progression without acquiring offer/fee support.

## Bounded retention and outcomes

Shared event, quote, reference and fee subobjects are content-addressed immutable
dependencies. Only required early/late checkpoints, schedule changes, bounded
outcome follow-ups and their dependencies are retained. The 2 GiB
research allocation covers legacy evidence, checkpoint and market witnesses,
workspace versions, operational metadata and late reservations. The previous
128 MiB allocation filled as Data witnesses accumulated alongside the frozen
checkpoints and protected late reservations. The 4 GiB SQL guard,
1 GiB free-disk floor, 512 tracked-game limit, legacy observation
sublimit and individual response bounds still apply. Evidence stays immutable
and refusals remain visible. This finite allocation gives continued collection
room after rollout. It establishes no guaranteed collection period.

Early captures reserve space for the late research packet and its Data
publication. The estimate uses the larger of the early packet with margin and
the floor for the league. Successful hosted captures measured complete late
packets up to 5,730,514 bytes. The early packet with 25% margin was smaller
than the late packet for 156 of 175 paired captures. The largest conservative
publication estimate was 7,472,713 bytes including the checkpoint. Floors
rounded up from league estimates are 8 MiB for NBA, 7 MiB for NCAAF and NFL,
5 MiB for NCAAB, and 2 MiB for NHL. Other leagues use 8 MiB until they have
comparable evidence.

The collector tops up older reservations under the research writer lock,
charges the manifest to its own game, and checks batch SQL and disk runway
again before the paid dispatch. The captured packet and market publication
still require exact-size admission. An unusually large response can exceed
the estimate. Ordinary requests set aside the parser-bounded space required
for paid response membership and release it when the page is retained or the
in-flight lease ends. Settings reports protected reservations, estimated
top-ups from shared space, separate SQL and disk guards, and refusals.

The first deployed full-surface run measured 11.33 MB of shared-JSON evidence
for a two-checkpoint game: thousands of small records and reference hashes still
cost too much. New snapshots use deterministic lossless gzip of the canonical
witness, with shared event/fee inputs and content-addressed 512 KiB chunks. Both
the packed and original canonical bytes are checked. A 32 MiB decoded-size bound
protects memory independently of the smaller retained encoding; it is not an
observation or review gate. Existing records and exports keep their original
representation. The actual Orlando–Washington pair retained 1,729,132 bytes in
the new representation, versus 11,326,154 bytes in the same original checkpoint
dependency closure: an 84.7%
reduction, with byte-identical decoded witnesses and arithmetic. This reduces
future writes; it does not reclaim or rewrite historical rows.

If initial scheduling ever captured a late task before an untouched early task,
the earliest actual frozen page remains the only honest first baseline. Migration
115 supports an explicit append-only role correction: the original rows and
clocks remain, the earliest page becomes the baseline alias, and its duplicate
late role is non-comparable. The advanced former early point stays inspectable
as later context. Corrections are recorded when made, never backdated. The due
gate prevents this order for future acquisitions.
Complete-pair counts and measured completed-game means require distinct,
causally ordered captured checkpoints on the same current schedule; a corrected
baseline alias or superseded schedule cannot inflate those figures.

Postgame collection is an engineering allocation of at most five guarded
attempts per tracked game, at start plus 3, 4, 6, 12 and 24 hours. Each has a
15-minute eligibility window; missed windows do not cause a catch-up burst.
Ordinary final-result receipts can resolve a game earlier. Repeated not-final
polls do not append outcome history. Genuine final-score corrections append new
evidence. Sporting outcomes, venue settlement and actual fills remain separate.
Probability reports label their retained-case selection bias and dependence
among markets from the same event.

Existing source controls, account windows, object/rate/day limits, reservations,
holds, SQL and free-disk guards govern every request. The working $50/week
assumption includes $30/week SGO; hosting remains unreconciled. No additional
paid service is selected.

## Inspection and reproduction

Experiments opens all tracked games, including incomplete captures. Its retained
case view selects positive-at-either-checkpoint cases. All-game context exposes surrounding
markets and per-book main progression without turning negative/negative quotes
into cases. Observed-data plots preserve missing values, show early/late points,
and mark only source-reported main roles. Data reuses the same captured-game
inspector and keeps latest stored prices separate. Reference-only books have price plots
without invented EV or fee claims. Exact inspection includes source inputs,
policies, fees, cashflows, clocks and missing-data reasons.

Complete exports contain all retained revisions and shared dependencies for one
game, with content hashes and a bundle hash. Browser downloads are revision-bound
and remain usable after later updates. Passive commands use the same owner:

```sh
python -m app.research.experiment_cli list --all-games
python -m app.research.experiment_cli detail GAME_ID
python -m app.research.experiment_cli export GAME_ID > game.json
python -m app.research.experiment_cli reproduce game.json
```

Offline reproduction verifies hashes, dependency closure, checkpoint timing,
original calculations and both probability witnesses. It makes no provider
requests. The milestone's owner-required live proof is one eligible game through
both scheduled checkpoints. Fixtures prove sign branches even if that real game
has no positive cases. A positive edge, completed sporting outcome, full T−24h
wait or long trading history is not a completion gate. Required repository CI
and installed normal operator/export checks remain separate evidence.

## Actual installed example

The initial deployment activated this policy at 2026-11-22 23:49:35 UTC.
Orlando Magic at Washington Wizards, scheduled for 00:00 UTC, received its early
response at 23:49:40.675527, finished calculation at 23:49:44.535742 and persisted
at 23:49:49.066393. Its late target was 23:50:00, deadline 23:51:00; receipt was
23:50:18.155335, knowledge 23:50:19.723143 and persistence 23:50:22.608806.
These are actual 619.324473/581.844665-second receipt lead times, not T−24h.

Both responses requested and received nine books and all six outcome IDs,
with 1,133 quotes and 1,079 alternates: 397 offer-context bets and 736 reference
quotes. The provider returned an event pagination cursor, which remains an
explicit completeness caveat even though no requested book/ID was missing.
The captured retained case was SGO's Kalshi-labelled Orlando spread −25.5 at
+1241, alternate at both checkpoints. Its conservative and coherent probability
was 31/361, modeled committed capital $99.97, win receipt $1,259 and loss receipt
zero. Exact EV was 293983/3608917 at both checkpoints and under the late-reference
revaluation of early cashflows. The observed finding was unchanged economics
with newer source clocks. It establishes no fill, venue settlement or quality
claim. UAB–Rhode Island also completed both scheduled checkpoints.

Actual native Chrome clicking at 150% zoom downloaded the complete game export;
mobile views preserved missing values and reference-only book price context.
The initial Magic export contained 12,076 immutable records and reproduced 84
numeric results among 397 offers at each checkpoint offline, without provider
or database calls. Private evidence and later storage/correction verification
are under `.local/ev-experiment-20261122/` and `.local/ev-experiment-installed/`.

Corrective release `a8a482f` deployed in run `45088113403`, with all 115
migration hashes matching. At 00:25:20 UTC an explicit role correction made
Pittsburgh–Dallas's earliest actual receipt (23:50:51.201280 UTC) its baseline.
The advanced former early page remains context; the duplicate late role is
non-comparable. All five original game records were unchanged, two records were
appended, and the corrected complete export reproduced both historical pages
offline. This repair used zero new provider requests and did not backdate a
capture. Its one positive available case remains explicitly incomplete.

The existing research allocation is nearly full because historical evidence and
previous late reservations remain charged. Future smaller captures can consume
their own protected reservations; this is not permission to retry refused early
baselines or manufacture missed observations. Download complete game exports
before making any separately authorized archival/capacity decision. Unique
evidence is never automatically discarded. Physical server cleanup is owned by
the separate personal-server assignment and does not reclaim logical research
allocation.
