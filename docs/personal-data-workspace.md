# Personal data workspace

The remembered owner login covers Dashboard, Data, Experiments, collection
controls, evidence downloads and APIs. [Open Predict](https://predict.dock108.dev/)

## Dashboard

Dashboard applies Sport, Bet type and Venue filters before ranking exact bets
by their best eligible quote’s unrounded EV. Expand a bet to compare its other
venue quotes. Open a quote for the bound acquisition, reference odds, fee and
cashflow evidence, and its original pull in Data. Use Diagnostics for Men’s D1
coverage and job details.

The board uses the newest covering pull for each full-game market. Failed or
incomplete latest attempts can withhold earlier offers. Explicit withdrawals,
kickoff, unavailable calculation inputs and the current fee policy also govern
eligibility. Verification time and quote age are separate. A price can remain
unchanged between accepted responses. A pull older than the configured discovery
interval stays visible as historical evidence in Data.

With Venue set to **Novig**, the open Dashboard receives update notices for
the selected sport and bet type. A notice causes a read of committed prices.
If the stream drops, the board keeps polling and reconnects. The saved pull and
native book clocks remain available in the quote inspector during reconnect.
The stream follows committed storage and incurs no provider calls from the page.

## Data

- **Market history** shows saved game and market rows. Filter by date, sport,
  game, source, venue or market. Open a quote for its normalized record and
  follow **Odds pulls** or **Captures** for the supporting collection evidence.
- **Game scores** shows sporting results and their retained source evidence.
- **Diagnostics** contains the PostgreSQL table browser and Men’s D1
  reconciliation, including recorded evidence decisions.

These pages and their exports read stored evidence. When original bytes are
missing, Data still shows any available normalized record.

## Experiments

Experiments opens **All trades** for the selected campaign. Open a trade in the
ledger to inspect it while keeping your filters and place. **By day** shows
campaign P/L and lets you open a date. The active-rule summary sits near Edit.
Expected paper profit uses the frozen entry EV for each selected trade.
Expected ROI divides that
profit by all selected stake. The realized ROI denominator uses graded stake.
P/L vs expected compares realized profit with the entry expectation for those
same graded trades.

Open **Games and coverage** to filter for missing finals, missed captures or
zero qualifying trades. **History & evidence** holds snapshots, exports and
raw evidence. A current result can change as grades arrive. Saved snapshots
open with their own IDs and clocks.

New experiments can use the reconciled Men's Division I slate or tracked
T−10 captures from all six supported leagues (NFL, NCAAF, NBA, NCAAB, MLB and
NHL). Choose dates, eligible markets, minimum EV, fixed-profit or Kelly sizing,
and Best or All venue portfolios. The spreads and totals filter includes main
lines and can admit verified alternate lines below an exclusive American odds
cutoff. The cutoff applies only to alternates. The Games view can show started
games without a usable final. The fixed capture, reference and fee policies are
displayed with the editable choices. Results stay paper only. Exact legacy run
links still open saved evidence.
[Paper experiment rules](paper-experiments.md)

**Win $25 · Native Liquidity · Nov 27–29** uses the all-sports native-book
policy for spreads and totals, at least 4% EV, and one trade per game. Its
original-book replay starts November 27 at 1:50 p.m. Eastern. Its prospective
capture segment starts the same day at 8:50 p.m. Eastern. Compare coverage and
the displayed clocks for the two segments in **Games and coverage**. See
**History & evidence** for the retained receipt chain and saved exports.

## Collection controls

Open the collection status in the top bar to see the last odds receipt, next
scheduled pull, a current problem if one exists, and the link to controls.
Stop, Resume and source Pause use committed authority and accounting guards.
Current collection problems, actionable credits and holds, and fee treatment
are on the controls page. Diagnostics holds job history, storage, reference
inventory and operating records. The collection schedule continues with the
browser closed. Dates use Eastern game-day boundaries.

### Fee assumption

The Include fees switch controls new current calculations. With it off, the
model assumes zero modeled fees. Turning it on uses the existing fee models
and applicability evidence. Changes revalue stored prices under the new fee
revision. Saved evidence retains its recorded assumption.

## Bookmarks and preserved capabilities

EV and Opportunities open Dashboard. Browse Odds, Odds, Raw Inputs and saved
game or replay links open Data. An exact legacy experiment or result link
opens Experiments with its pinned inputs. Retired standalone pages identify
the workspace destinations. [Architecture](architecture.md)

## Active provider and ten sportsbook references

SportsGameOdds supplies the current selection. The selected reference books
are FanDuel, DraftKings, BetMGM, Caesars, BetRivers, Hard Rock Bet,
Bookmaker.eu, BetOnline, Bovada and William Hill. Kalshi, Polymarket US, Novig
and Prophet Exchange are the four prediction-market venues. Coverage varies
by game and market. The captured probability policy identifies which eligible
reference prices were used. Data keeps historical books and source identities.

## Authorized fresh start, November 22

After the installed retained-data journey and offline export reproduction passed,
Michael authorized clearing the development server's observed market/research
population. Active observations, retained research and source-only caches were
reset with recoverable server/Mac backups. Financial journal and provider
account/quota/reservation/hold records, login, Stop/pauses, configuration and
scheduled-slot history were preserved. No storage cap or credit limit changed.

The fresh policy uses SGO, the selected ten references and four supported trading
markets. Old bookmarks still resolve through the workspace but can report that
the old observation is no longer retained. Backups are not silently reimported.
At the time, Data and Experiments started empty and filled through normal :20/:50 discovery,
initial capture and scheduled T−10. The first post-reset T−10 was captured through the normal scheduled workflow on
November 23; the pre-reset journey remains separate verification evidence.

The November 23 snapshot migration linked 43 authentic historical captures without
provider requests. The unchanged 128 MiB research-allocation guard refused 11
additional links; their original checkpoints remain in legacy evidence. At the
installed inspection, retained bytes plus protected future-capture reservations
left approximately 0.7 MiB unreserved at the final public-site check. New captures can therefore be refused by
the existing capacity guard. No cap increase or automatic eviction was applied.
