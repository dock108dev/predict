# SportsGameOdds operations

SportsGameOdds is a selectable aggregate collector. It supplies attributed
exchange prices and sportsbook observations alongside the independent Kalshi
and Polymarket US native streams. The example configuration selects it with
acquisition off. Follow the [configuration guide](configuration.md#source-configuration)
for credentials and opt-in.

## Collection and budget

**Admin → Sources** shows scheduled collection and provider status.
**Admin → Spending** shows object allowance, reserves, charges, and outstanding
requests. Use the provider-reported usage and account limits. Keep SportsGameOdds
and The Odds API ledgers separate.

Collection checks Stop, source pause, request rate, and the object budget before
dispatch. A request reserves objects before transport. If its charge is
unverifiable, it remains held or interrupted at its reserved exposure. A
difference in account-wide usage does not identify which request consumed it.
Use attributable provider evidence to reconcile an individual charge.
[Provider usage endpoint](https://sportsgameodds.com/docs/endpoints/getUsageData)

The worker treats `/account/usage` as rate-exempt. Balance reads do not
consume a local paid-request slot; event requests still reserve their durable
rate slot and object allowance before dispatch. Existing request history and
unresolved exposure are preserved.
[Provider usage FAQ](https://sportsgameodds.com/docs/faq)

The worker uses a first-of-month UTC pacing boundary when the provider reports
no reset. Treat this as a scheduling assumption. It does not establish actual
replenishment or resolve prior exposure. A due date shown during rolling
pacing is an estimate and the worker checks the budget again before dispatch.

## Discovery and refresh

League discovery keeps the same scope and start cutoff across its cursor walk.
A saved cursor resumes only for the matching query and phase configuration.
A parsed page containing another league records its response hash and actual
object charge. Admin reports `sgo_discovery_league_mismatch`, and the worker
keeps the last valid cursor for the next scheduled attempt. A rejected cursor
restarts the affected traversal. Exact event-ID refresh can span leagues.
Restart seeding applies phase, kickoff and terminal status before the schedule
limit. The truncation flag reports whether more eligible retained events exist.
Event refresh and discovery share the object budget. Near-start refresh can
request alternate lines for one event at a time. Only the supported book and
market inputs are eligible for the desk. [Coverage limits](broad-coverage.md)

Scheduling replans every minute, with separate wakeups for exact refresh and
time-band deadlines. This does not start another discovery walk or make a request
when no game is due. Games inside the 24-hour pregame window take priority
between discovery pages. Discovery retains its cursor and budget guards.

The planner forecasts the next 24 hours through each game's time bands, ending
pregame polling at kickoff. The target policy is one hour inside
24 hours, then one minute inside the final 30 minutes. The minute cadence is measured for information gain; provider prices may
change less often than polling.
It slows distant repeats first. If the requested schedule cannot fit, it slows
early repeat polls before stretching the late cadence in 30-second steps;
`budget_stretched` distinguishes that selected schedule from the requested one.
Active games are conservatively costed for the full horizon; a finish is never
invented. Planned discovery plus refresh stays within 90% where the slate fits;
the ledger still checks actual rolling expenditure before every request. Admin's
`schedule_budget` records the projection basis, requested and selected intervals,
advertised feed frequency,
discovery cost and headroom. These are targets, not source-latency guarantees.
[Provider plan frequencies](https://sportsgameodds.com/pricing)

## Minute-poll measurement

After successful full-alternate page admission, the collector records compact
quote-image and source-clock fingerprints for pregame events inside the final
30 minutes. Main-only fallback responses are excluded so a scope change cannot
masquerade as a changed price image. The
separate `.local/predict-odds/diagnostics/sgo-refresh-study.sqlite3` contains no
credentials, raw prices or financial accounting. It retains at most 10,000
samples and seven days. Restart loads the retained summary; a study error does
not fail acquisition or revoke committed prices.

Admin's source metrics include `late_pregame_study`: comparable polls, changed
quote images, clock-only changes, fully repeated polls, observed time gaps and
changed images observed earlier than a three-minute replay. A quote image covers
prices, lines and availability; a first sample is a baseline. The replay measures
earlier information, not order executions. Inspect the durable report without
issuing provider requests:

```sh
.venv/bin/python -m app.collection.sportsgameodds_study
```

For server measurements, run that module in the collector container. A local
snapshot app does not collect minute-poll samples.

The desk uses both original sportsbook clocks for same-book fair odds. Vendor
fair odds and book consensus have separate meanings from Predict's own estimate.
A refreshed frame does not make an old source quote fresh.
[Calculation basis](benchmark-ev.md)

## Interrupted admission and retained prices

Original HTTP responses have a separate limit of 16,384 manifest entries and
128 MiB of compressed bodies. The free-disk floor also applies. Retention counts
time- and scope-specific receipts even when their bodies share a content hash.
The Research status reports the active bounds, usage, and accumulated gaps.
When original retention is refused, ordinary prices can still be admitted.
A batched T−10 capture requires its exact retained response. Increasing
headroom allows future retention and preserves the historical gaps and files.

A PostgreSQL timeout rolls back the whole page admission. The running collector
can retry the same settled page once while Stop and pause checks still allow
it. The retry preserves the original receipt and does not issue a second
provider request. A retry that times out leaves the source status visible and
collection follows its normal retry schedule. Restart does not guarantee replay
of a settled page that never reached storage.

An exact venue closure withdraws the current quote. The later closure receipt
can prevent an older replay from restoring it while keeping the original price
and clocks inspectable. A cancellation, suspension, or final status withdraws
the occurrence. Reopening requires a later nonterminal status with a fresh
price timestamped after the closure was observed. Each offer must clear that
same cutoff before it can return to the desk.

The working history has age and space limits. Pinned
evidence and saved odds use their separate retention rules. Switching the
aggregate provider withdraws the old provider's current authority while its
retained evidence remains accessible. [Storage ownership](storage-ownership.md) ·
[Runtime controls](data-app-runtime-contract.md#lifecycle-and-controls)
