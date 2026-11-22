# Reproducible probability and research records

The daily/one-hour automatic policy described here is preserved foundation
history. The new primary automatic workflow is documented in
`docs/ev-checkpoint-experiment.md`; activation records its transition without
rewriting these cohorts or their calculations and exports.

The current calculation owner retains its conservative per-bet screen under
`lowest-no-vig-two-trusted-books-2`. Its results are not a complementary event
distribution. The additional `first-complete-trusted-pair-proportional-1`
baseline selects one complete exact pair in fixed FanDuel, DraftKings, BetMGM,
Caesars order. Both outcomes use that pair. The optional
`same-book-betonline-first-1` policy adds BetOnline ahead of that order and
excludes the evaluated bookmaker. It grants reference support, not execution or
venue-settlement equivalence. New policies must receive new version names;
old registry entries and frozen inputs remain available for reproduction.

SGO's original `polymarket` bookmaker has no independently reviewed bridge to
Polymarket US. Its displayed venue label therefore cannot authorize US fees,
even when Admin has a US fee rate. The current fee owner returns
`provider_venue_fee_applicability_unestablished`, withholds applicable net EV,
and preserves the received price in the catalog. Native Polymarket US remains
on its existing path. Previously frozen arithmetic remains a conditional
witness; it is not silently relabeled as current fee-applicable research.
Before rebuilding an older numeric alias row, the owner saves its exact payload
and retained source/fee inputs as an immutable historical conditional observation
outside prospective cohorts. If retention is unavailable, the game rebuild rolls
back and the guarded reads continue withholding current EV; unique evidence is
preserved rather than deleted to make the refusal appear complete.

## Exact example

FanDuel home/away `+150/-150` gives the exact no-vig pair `2/5, 3/5`.
DraftKings `-150/+150` gives `3/5, 2/5`. The existing screen selects `2/5`
independently for either bet, so its two outputs sum to `4/5`. The coherent
baseline selects the complete FanDuel pair and sums to one.

For $100 committed, a win receipt of $275 and loss receipt of zero gives
`(2/5 * 275 + 3/5 * 0 - 100) / 100 = 1/10`. Win receipts of $225 and
$250 give `-1/10` and zero. A $250 win receipt with $101 committed gives
`-1/101`. Unknown fees leave net EV null; an intact probability pair may still
be evaluated against sporting outcomes. These calculations establish arithmetic,
not a claim that either book has good probabilities or that an order could fill.

`app/research/calculation.py` freezes source record, original clocks, observation
IDs/revisions, fee applicability/rule, quantity/rounding, state cashflows, policy
and exact results. Reopening verifies the content hash, the recorded pair policy,
cashflow arithmetic and, when supplied, the full original fee/quantity inputs.
Changing the current default policy does not change a frozen old-policy result.
Version six did not retain purchase/quantity/increment fields. Its reproduction
checks every field it did assert, leaving unasserted fields absent; an explicit
null remains an assertion and must match. Newer schemas retain full equality.

## Prospective population and clocks

`app/research/records.py` owns append-only PostgreSQL `research_record` objects:
cohort declarations, candidate observations, horizon captures, sporting results,
separate venue settlements and frozen evaluations. Migration 112 forbids changing
or deleting these rows. It does not modify personal journal entries, source
observations, applied migrations, credentials, Stop choices or financial records.

The collector's normal pregame owner invokes `automatic_turn` every 30 seconds
when acquisition is not under critical pressure. That cadence is an engineering
scheduling choice, not a completion or probability-quality gate. Once per UTC
day it freezes all exact primary normalized market identities currently known,
including unavailable calculations and every EV sign, whose starts are within
seven days and more than one hour ahead. The initial capture horizon is one hour
before the scheduled start. The declaration records these choices before values
are inspected. Later-discovered identities remain outside that frozen population
and can enter the next declaration. Raw unsupported markets remain in the wider
catalog; this cohort does not pretend they are primary-path supported identities.

Candidate snapshots are retained while known before each cutoff. Finalization
uses both the candidate's knowledge clock and its actual PostgreSQL persistence
clock. Looking at current data after an outage cannot fill an earlier prospective
horizon. Every declared event/market/horizon slot remains in coverage accounting
as scored, missing or excluded. Comparisons apply both recorded probability
policies to those same slots. Distinct event counts accompany record counts;
multiple markets or horizons from one game are dependent observations.

Sporting scores have independently retained receipt, knowledge and nullable
publication clocks. Exact source event, start, league and canonical participant
roles must match before an imported result can score a case. Ties, pushes,
cancelled games and unsupported periods/markets remain explicit exclusions.
Sporting results never imply a venue settlement or an actual fill. Corrections
append a new outcome with the superseded ID and reason. A prior saved evaluation
keeps its original outcome IDs and results; evaluating at an earlier knowledge
cutoff excludes a correction learned later.

## Archive connection

`app/research/archive.py` consumes hash-verified SGO archive changes through the
existing receipt-cutoff replay owner. It reconstructs exact source identities
and complete bookmaker pairs, checks the canonical event/roles, and retains the
change IDs used. No later receipt enters an earlier reconstruction. Compact
archive evidence cannot establish every original internal knowledge transition,
continuous freshness or missing depth. `original_knowledge_cutoff` remains null,
freshness remains `not_established`, and absent execution fee/cashflow inputs
remain null. An archive replay is explicitly retrospective, even when its prices
predate a sporting result.

## Operating commands and retention

`python -m app.research list`, `declare FILE.json`, `turn`, `capture COHORT`,
`evaluate COHORT [--as-of TIME] [--save]`, `export COHORT`, `observe COHORT CASE
FILE.json`, and `outcome COHORT CASE sporting|settlement FILE.json` expose the
same owner without acquiring data. Corrections use `--supersedes` and `--reason`.
`replay-market ARCHIVE_ROOT CASE.json --event SOURCE_EVENT --from-day DATE
--through-day DATE --as-of TIME [--cohort COHORT]` connects retained shards to an
explicit retrospective cohort.

The recorder, replay and evaluator add no provider subscription or paid request. It reserves a measured
logical 96 MiB for candidate observations and a 128 MiB total bound, with a 1 MiB
ordinary-record cap and a scoped 4 MiB evaluation-report cap, the existing
whole-database cap, an 8 MiB SQL runway and the
existing free-disk floor. Hitting a bound is reported in collector cohort status;
unique research evidence is not silently evicted. Capture scheduling failures
have their own status and cannot turn into a paid-acquisition restart loop.
These are initial retention bounds, not a claim of indefinite coverage.

The November 22 operating population filled the original 16 MiB observation
subcap while the total allowance still had room. A read-only census found 1,298
observations with distinct per-case input fingerprints, including 137 cases with
two revisions, rather than repeated identical polling writes. Existing capture
rows duplicated 2,143,816 bytes of snapshots already retained in observations.
Those immutable records remain unchanged. New captures retain an observation ID
and snapshot ID; readers resolve that immutable observation and verify the
snapshot identity. Offline exports contain both records and resolve the same link.

Migration 113 reserves a bounded disposition slot for every declared
case/horizon before collection. Its conservative 2 KiB slot allowance and fixed
accounting row are charged inside the research total. Refusal attempts,
first/last times, affected slots and recovery are updated in place, so a full
data allowance cannot consume the space needed to explain missing captures.
One oversized/refused observation does not abort later cases. Counters measure
attempts and affected slots, not distinct missed source revisions.

Accounting records when disposition-aware code starts. Refusals before that
cutover were not counted; their affected-case and attempt totals remain null.
A sourced prior incident can be attached with `note_prior_retention_gap`, using
the first retained log time and its evidence reference. It does not invent a
beginning for an outage or backfill already frozen horizons. New counts and that
prior uncounted window appear separately in operator status and evidence exports.

Current evaluation conservatively excludes a captured horizon affected by that
prior uncounted interval unless a valid observation was actually persisted after
the accounting cutover and before the horizon cutoff. Older cutoffs stay outside
the interval. Saved evaluations and captures are never rewritten. Unchanged
current inputs can receive one lightweight reaffirmation observation linking to
their existing immutable snapshot, with new knowledge and persistence clocks;
this establishes recovery without duplicating full payloads or renewing source
timestamps. Later identical polling does not create more reaffirmations.

The real 1,159-case, 259-event report measured 1,148,474 canonical bytes before
new retention annotations, exceeding the old 1 MiB record allocation. Evaluation
records therefore have a 4 MiB bound inside the research total. Ordinary
observation/source records keep their 1 MiB limit. A per-kind cap owner is reused
by admission and export validation; a forced-limit fixture proves refusal does
not mutate evidence before the restored allowance saves the complete report.

The first installed 24 MiB allowance also filled with genuine input revisions.
At 22:04 UTC a read-only serialization measured 2,583,319 additional bytes for
98 changed-input snapshots and 330 compact recovery reaffirmations; only 143
observation bytes remained. There were no duplicate full snapshot IDs. The
engineering allocation is therefore 96 MiB observations / 128 MiB total, within
the existing 4 GiB SQL cap and 1 GiB free-disk floor. The additional 96 MiB total
at the writer's conservative three-times append estimate is 301,989,888 bytes,
below the measured 1,722,221,545-byte SQL headroom. This is finite capacity for
the actual declared population, not a new operating-budget or accuracy gate.
No retention duration is promised, and no unique evidence is evicted.

## Verification

`tests/test_research_probability.py` contains independent exact positive,
negative, zero, rounding, unavailable, noncomplementary-reference, optional-book,
policy-change and Brier/log-loss examples. `tests/test_research_archive.py` checks
verified replay identity, canonical roles, unknown knowledge/depth and exclusion
of later receipts. `tests/test_research_records_sql.py` runs on disposable
PostgreSQL and checks full source/fee reproduction, declared populations,
causal cutoff capture, immutable outcome corrections/evaluations, explicit
unavailable results, population-wide policy comparison and no-eviction limits.

Current calculation version is `predict-current-pregame-7`. Saved development
snapshots from versions five/six use retained affected-game rebuilds, rather than
pretending an old scalar probability contains the newly required pair inputs.
The source/fee/control tables are read and preserved. The existing snapshot
regression also verifies that a changed recorded policy cannot hide behind an
unchanged economic input revision in either cache reuse or SQL UPSERT.
Evaluation cutoff and witness hash stay in the frozen envelope, while economic
input hashes exclude them. A forced unchanged affected-game turn at a later
clock therefore preserves complete current price/calculation rows, including
their original calculation timestamp, without losing source or policy inputs.

Collection-mode derivation rebuilds coherent and optional probability witnesses
from the mode's own batched reference inputs. Copying a public price cannot copy
probability authority from another mode. Qualified fee cashflows and original
price clocks remain unchanged. The regression deliberately corrupts copied
probability metadata and verifies the full result against the mode's actual
references while requiring just one reference-table read.

The new evaluation scope is ordinary whole- and half-point sportsbook lines.
`target()` preserves other exact fractions; it does not establish their
settlement semantics. Newly qualified baselines refuse those unsupported lines,
and ambiguous SGO odds-stake quarter lines retain their source price with
`posted_line_settlement_unestablished`. Native USD-per-contract binary threshold
prices retain their separate semantics; an unsupported sportsbook probability
is unavailable. Historical pure probability/cashflow arithmetic stays unchanged,
so old immutable conditional witnesses remain reproducible. Before an older
numeric working row is withdrawn, its original conditional calculation is saved.

## Complete evidence export

`python -m app.research export COHORT` emits canonical JSON containing the full
declaration, every retained cohort observation and capture snapshot, all sporting
or settlement revisions, and every saved evaluation. Actual PostgreSQL
`recorded_at` clocks accompany the unchanged payloads. Every payload is checked
against its original SHA256 ID and retained byte size; a bundle SHA256 covers all
top-level fields except `manifest`. The evaluation index points to saved results;
export does not silently recompute or append a replacement evaluation. Normal
cohort summary/detail reads remain separate.

Storage remains bounded at 128 MiB. Export reserves a bounded allocation of twice
that payload allowance plus 1 MiB for immutable row envelopes and metadata, so a
valid cohort near its storage cap can still be exported completely. No records
are truncated. The disposable regression closes the source database, reopens the
exported JSON, reproduces its frozen observation and capture offline, and checks
that both original and corrected outcomes/evaluations survive unchanged. A small
patched-cap example verifies metadata headroom without raising the storage cap.

The separate explicit result command
`python -m app.collection.research_result_capture SOURCE_EVENT_ID [SECOND_ID]`
can fetch one bounded page from the existing SGO source for already-declared,
started events. It requires the active source, its existing account window and
all rate, daily, operational, hold, disk and Stop/pause guards; it never opens a
new account window. It retains original bytes and imports sporting results into
exact matching declarations. A response may still lack final results. Its known
returned-event charge is separate from concurrent account-window deltas and
exempt account-usage reads. This command is not called by browser inspection.
