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

The desk uses both original sportsbook clocks for same-book fair odds. Vendor
fair odds and book consensus have separate meanings from Predict's own estimate.
A refreshed frame does not make an old source quote fresh.
[Calculation basis](benchmark-ev.md)

## Interrupted admission and retained prices

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
