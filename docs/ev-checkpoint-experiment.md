# First observation versus ten minutes before start

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
outcome follow-ups and their dependencies are retained. The existing 128 MiB
research allocation includes legacy records, new records, operational metadata
and late-checkpoint reservations. It is not raised for this experiment. Unique
evidence is not automatically evicted; refusals remain visible. Actual bytes per
game, deduplication and remaining runway are reported by the store.

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

Research defaults to retained cases. All-game context exposes surrounding
markets and per-book main progression without turning negative/negative quotes
into cases. Observed-data plots preserve missing values, show early/late points,
and mark only source-reported main roles. Reference-only books have price plots
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
