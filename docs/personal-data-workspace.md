# Personal data workspace

The remembered owner login covers Dashboard, Data, Experiments, collection
controls, evidence downloads and APIs. [Open Predict](https://predict.dock108.dev/)

## Dashboard

Dashboard orders current positive EV offers by unrounded EV. Each row shows the
game, bet, venue, posted odds, fair odds, EV and source quote age. Open any row
for the bound acquisition, exact quote, reference odds, fee and cashflow evidence,
and a link to the original pull in Data.

The board uses the newest covering pull for each full-game market. Failed or
incomplete latest attempts can withhold earlier offers. Explicit withdrawals,
kickoff, unavailable calculation inputs and the current fee policy also govern
eligibility. Verification time and quote age are separate. A price can remain
unchanged between accepted responses. A pull older than the configured discovery
interval stays visible as historical evidence in Data.

## Data

- **Observations** opens readable game and market rows. Use the date, sport, game,
  source, venue and market filters to narrow the evidence. Inspect an exact
  quote for its normalized record and linked acquisition.
- **Odds pulls** shows recorded SportsGameOdds attempts, including incomplete or
  failed attempts. Open a pull, filter its captured records and inspect or
  download an original physical response where retained.
- **Captures** and **Results** show immutable first-observation and T−10
  checkpoints, sporting results and their original source evidence. Men’s D1
  coverage also shows reconciled counts and recorded evidence decisions.
- **Tables** browses PostgreSQL relations read-only with bounded rows and cell
  pages. It reports objects or contents the web reader cannot access.

Use **Create experiment from these filters** to carry supported settings into
the form. Unsupported browsing filters appear as context that requires a choice.
The activity on these pages and their exports reads stored evidence. Missing
bytes are shown separately from a stored normalized record.

## Experiments

Experiments opens Win $10 directly. Select one Eastern date and one portfolio
to see its results. The rules show the saved scope, capture timing,
reference and fee assumptions, EV threshold and sizing. Stake includes selected
trades. Return, paper P/L and ROI use graded trades. ROI includes the graded
stake denominator.

Open a game or trade to trace the exact quote, eligibility, sizing, grade and
supporting source evidence. A current result can change as grades arrive. A
saved snapshot opens with its own IDs and clocks. Pending results and capture
gaps have separate states.

Creation uses the engine's supported Men's Division I T−10 workflow. New
experiments can choose dates, minimum EV and bucket boundaries, fixed-profit
or Kelly sizing, and Best or All venue portfolios. The fixed capture, reference
and fee policies are displayed with the editable choices. Results stay paper
only. Exact legacy run links still open saved evidence.
[Paper experiment rules](paper-experiments.md)

## Collection controls

Open the collection status in the top bar to see the last odds receipt, next
scheduled pull, a current problem if one exists, and the link to controls.
Stop, Resume and source Pause use committed authority and accounting guards.
Credit usage, holds, daily source jobs, retention and display preferences are
available on the controls page. The collection schedule continues with the
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
the workspace destinations. [Route and job inventory](engineering/predict-simplification-20261125.md)

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
