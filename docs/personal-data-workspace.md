# Personal data workspace

Predict has three destinations: [Data](https://predict.dock108.dev/data),
[Experiments](https://predict.dock108.dev/experiments), and
[Settings](https://predict.dock108.dev/settings). The existing remembered owner
login protects all routes, assets, APIs and exports.

## Data

The default table has one row per established game, full-game market family and
period. Moneyline, spread and total have independent headline offers. Search,
sport, Eastern start date, positive EV and EV ordering stay visible; source, age,
market and alternate controls live under More filters. Grouping, candidate
selection, filtering, ordering and counting happen on the server before paging.

A headline is the highest eligible stored screening EV among the trading venues'
own source-designated main offers, across either selection in that acquisition.
Different exact lines remain different bets. Reference-book main status never
relabels a trading offer. Alternates enter the headline/filter/ranking population
only with Include alternates; an alternate winner is marked. Unknown main status
cannot become a default headline. Zero and negative EV remain available.

Click EV to open that exact offer, line, captured odds, probability basis, fee
assumption and same-pull supporting references. Source identities, revisions,
exact arithmetic and export evidence are expandable. Offers & history provides
focused main/positive offers, Other offers, Reference inputs, Alternates and
History, including Previous capture. Each history link carries that capture's own
market identity, including an older source-local identity before canonical linking.
A positive filter keeps sportsbook references reachable.

Each current comparison uses a durable logical acquisition `pull_id`, with child
ledger attempt IDs and accepted response membership. All required inputs share
that pull and their complete receipt span is at most 600 seconds inclusive.
Source timestamps remain separate evidence; this rule adds no source-age
threshold. Identical bytes across requests do not merge acquisition identity.
An explicit single-event request closes its requested returned surface when that
one event is returned with known membership. SGO paginates events, and may emit
a redundant cursor; this does not imply another page of odds within the returned
event. Broader discovery retains its cursor chain and uncertain omission
authority. An absent book or line is Not returned, not source withdrawal.

A newer covering attempt suppresses the current numeric headline while in
progress, partial, failed or cancelled. A complete capture with missing references
publishes null EV. Earlier positive captures remain in history. Narrow requests
cannot replace or suppress the unrestricted board, and late completion cannot
replace a newer started attempt. Frozen snapshot publication is atomic. Historical
records without proven membership remain under View → Received evidence / legacy
history and Experiments, with original provenance and calculation versions.

Trading is prediction-market only: market-to-book EV uses sportsbook evidence;
market-to-market arbitrage uses two prediction venues. The pair view shows both
actual selections/lines, odds, illustrative allocations, committed cash, captured
fees, snapshot time, modeled return and minimum modeled profit. Existing
market/book benchmarks are labeled Sportsbook reference comparison; a sportsbook
is never an executable second leg or a locked-profit claim. Pairing reads the
same latest covering frozen scopes as the market board, without provider requests
or background acquisition/calculation jobs.

Links and browser Back/reload preserve filters, row, acquisition and exact offer
revision. A repeatable SQL read token is a paging lease, not the acquisition ID.
After lease expiry, exact market inspection reopens the selected immutable pull;
it refuses an absent or changed revision instead of choosing another offer.
Exporting an opened exact input uses its captured bytes. Checkpoint exports retain
the complete immutable dependency bundle for offline reproduction.

## Experiments

The existing first-observation/T−10 experiment lists tracked games, capture
coverage, missing/refused/missed cases, early/late changes and available sporting
outcomes. Experiments retains its game/bet inspector and captured evidence; Data
opens the exact headline offer directly.
Declared populations, evaluation and frozen cohort exports remain available in
contextual details. Scheduled checkpoints show their actual due time; Capturing,
Captured, Missed, failed/refused and cancelled states come from task evidence. A
future T−10 is not a failure. Missing exact lines are separate from missing
checkpoints. With no scored completed games, a concise empty state replaces empty
scoring grids. The same scheduled/due state applies to source rows, exact-line
continuity and drilldowns; a future checkpoint contributes no missing-data graph
marker. Early-offer/late-reference diagnostics are labeled analytical views
outside current opportunity ranking and arbitrage.

Sporting outcomes, quoted EV, probability quality and actual trading returns are
separate. Missing outcomes and incomplete captures remain visible. NCAAB models,
game logs and accuracy work remain deferred; no new feed or backtest engine is
enabled by this interface.

## Settings

Settings reads real collection state, next discovery/checkpoint, reported credits,
unresolved holds, source state and finite storage. It retains Stop/Resume, source
pauses and essential discovery configuration. Control eligibility still comes
from the existing authenticated backend and its recovery/accounting guards.
Detailed operating evidence is expandable. Availability and last valid provider
receipt are separate facts; a missing diagnostic-cache quote is not a failed
acquisition. Display preferences remain local, with Eastern as the default time
zone. The date filter always uses Eastern-day boundaries.

### Fee assumption

**Include fees is off by default.** New prediction-market calculations assume
zero fees, including entry fees, settlement commissions and reserves. Turn the
setting on to use the existing fee models and their applicability checks. The
fee implementations and configured schedules remain intact.

The shared PostgreSQL setting is `public_fee_schedule['predict:fee_mode']`.
Changing it invalidates working calculations and queues recalculation from
stored prices, with no provider request. Prices, source clocks, quantity grids,
reference requirements and settlement checks still apply. Calculation payloads,
checkpoint evidence and exports carry their actual fee-mode revision. Frozen
history remains reproducible under its original assumption; each new checkpoint
captures the mode in effect when it is computed. Mixed fee modes cannot form one
arbitrage result. The Settings switch does not alter journal or accounting facts.

Discovery stays at :20/:50 under the existing configuration: one initial full
research snapshot, scheduled T−10, and bounded postgame checks. Browsing does not
start Live polling, refresh a saved game, acquire data or modify source clocks.
Logical research capacity and physical/database capacity remain distinct; no
storage cap increase or automatic eviction is introduced.

## Bookmarks and preserved capabilities

Research redirects to Experiments. Browse Odds, Odds, Raw Inputs and game/replay
bookmarks resolve into Data. Opportunities/EV maps to the positive filter and
Arbitrage maps to its calculation view. Admin/coverage bookmarks resolve to the
relevant Settings or Data section. Static HTML aliases use the same fixed local
mappings; unsupported shells return a clear retired-page response.

Scanner, My Bets, About and Trading Fees standalone interfaces are retired.
Journal/exposure records, APIs, samplers, source evidence, export readers,
calculations and scheduled acquisition remain intact. Existing source files and
archived test versions remain recoverable; removing an HTML entry point does
not remove its backend mount.

## Active provider and ten sportsbook references

SportsGameOdds is the sole active identity/data provider. Native-provider
records and old books remain preserved for explicit historical inspection;
they are not default active identities.

The selected reference sportsbooks are FanDuel, DraftKings, BetMGM, Caesars,
BetRivers, Hard Rock Bet, Bookmaker.eu, BetOnline, Bovada and William Hill.
Kalshi, Polymarket, Novig and Prophet Exchange are the existing supported trading
markets and do not consume any of these ten slots. Other known exchanges remain
trade-side historical context with unsupported calculations, never sportsbook
references.

This shortlist combines familiar retail lines and sharper price-discovery
references, with genuine retained SGO observations for every selected book. It is
an engineering selection for useful price coverage, not a measured sharpness
ranking. Contemporary [Virginia regulator operator figures](https://cdnprodpaasmedia-valottery-com.azureedge.net/-/media/val/images/promos/casinos-sports-betting/board-meetings/board_presentation_-october_2026.pdf?rev=8017bcb45bf04c439e48322d177bca57)
provide popularity context; [Unabated identifies Bookmaker as a market maker](https://www.unabated.com/post/what-is-the-unabated-line),
and [BetOnline publishes its market-specific wager limits](https://help.betonline.ag/en/articles/185201-wagering-limits).
The [SGO bookmaker reference](https://sportsgameodds.com/docs/data-types/bookmakers)
owns provider IDs. Availability remains game/market dependent.

New discovery/captures use the selected reference scope and supported trading
markets. Existing declared early/T−10 games keep their original immutable policy
and request scope through their remaining checkpoints. Actual requested/received
coverage and original exports are not relabeled. Account, credit, wire, decoded
payload and research-allocation guards remain unchanged; a broader requested
book surface can still be refused under those bounds.

Selecting ten reference sources does not change the versioned EV probability
policy. Its four trusted screening books and optional recorded comparison policy
remain as implemented; a received quote alone does not establish new probability
eligibility or sharper/calibrated predictions.

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
Data and Experiments start empty and fill through normal :20/:50 discovery,
initial capture and scheduled T−10. The first post-reset T−10 was captured through the normal scheduled workflow on
November 23; the pre-reset journey remains separate verification evidence.

The November 23 snapshot migration linked 43 authentic historical captures without
provider requests. The unchanged 128 MiB research-allocation guard refused 11
additional links; their original checkpoints remain in legacy evidence. At the
installed inspection, retained bytes plus protected future-capture reservations
left approximately 0.7 MiB unreserved at the final public-site check. New captures can therefore be refused by
the existing capacity guard. No cap increase or automatic eviction was applied.
