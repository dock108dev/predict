# Coverage and freshness

Coverage answers separate questions about what a source listed, what Predict
received, which quotes are current, and which comparisons reached the desk.
View it under **Coverage**. The app reads a bounded committed coverage result.
A failed worker can leave a previous capture inspectable with its original
clock. The public view cannot enumerate every offer available at every venue.

## Scope and denominators

The configured sports can include NFL, NCAAF, NBA, NCAAB, MLB, and NHL. The
ordinary pregame scope is full-game winner, spread, and total, including
available alternate lines. Source selectors and the configured provider
determine which requests can enumerate that scope. Kalshi and Polymarket US
supply independent native prices. SportsGameOdds and The Odds API are selectable
aggregate routes with separate accounting.

An offered price unit is the provider, venue, native event, native market,
native outcome or side, line, and period. Repeated pages and reconnects can
report the same unit. Distinct native sides and lines are separate units.
Discovery can also count listing-only markets with no price. A complete
offered denominator requires all relevant pages or an authoritative inventory
boundary. A failed, capped, or partial query leaves the denominator unknown.

| Stage | What to count |
| --- | --- |
| Offered | Independently enumerated price-bearing units within the exact requested scope. |
| Received and admitted | Observations actually received and their recorded disposition. Include rejected and pending items in the accounting. |
| Current and displayed | Distinct valid original prices with supported freshness and visibility. Inspect publication and display filters separately. |
| Comparisons | Eligible matched outcomes or opposing pairs against independently enumerated inputs. Report evaluated, pending, missing, and published groups. |
| Fees and EV | Distinct displayed offers with applicable fees and exact reference comparisons. Count each type of estimate using its own eligibility rules. |

The coverage goals are 99% for offered acquisition, display, and freshness, and
99% for applicable fees and independently enumerated eligible comparisons.
Account for every received unit, including rejected and pending observations.
Report counts by venue, league, and family so one large cohort cannot hide a
missing smaller one. A retained-row fraction cannot measure offered coverage.
Report an unknown denominator as unknown. An empty, successfully covered scope
has no measurable percentage. [Fee denominator](fee-coverage-policy.md)

## Freshness and verification window

Record the original source change, receipt, admission, publication, and read
times separately. An unchanged native book can remain supported by a valid
current-generation initial image and continuous ordered updates. Connectivity
alone supplies no book confirmation. A new receipt or calculation does not
renew an old source price.

The ordinary pregame desk keeps the latest valid committed price and its
supported estimate until the latest authoritative kickoff. It keeps the
original book and receipt clocks, even if the next page is partial or the
source is temporarily unavailable. An authoritative withdrawal invalidates
the affected input. The 15-minute pregame source check measures recent
confirmation; it does not expire a committed pregame offer or estimate. Live
prices and calculations retain their separate freshness limits.
[Runtime and synchronization](data-app-runtime-contract.md#native-synchronization-and-delta-acquisition)

For an authorized local diagnostic, the following command reads retained working
rows and local sportsbook captures to check eligible pregame inputs. It can take
longer than a regular desk read and can run with acquisition off.

```sh
.venv/bin/python scripts/live_coverage_census.py --phase pregame --independent-finance
```

Compare counts only when their scope, stage, and capture times agree. Capture
enough of the source availability, polling, or restart scenario to describe
what was measured. Desktop and installed service performance require their own
evidence.

## Diagnose a gap

Start with **Admin → Sources** for source health, schedules, query limits, and
holds. **Raw Odds** shows whether the original quote was actually received. Use
the exact game and line in **Browse odds** to check admitted display coverage.
Then inspect the quote for matching, reference, settlement, and fees. A missing
price and a missing calculation are separate outcomes.

[Acquisition](acquisition.md) · [Raw Odds](raw-prices.md) ·
[Calculation basis](benchmark-ev.md) · [Data limitations](market-data-gaps.md)
