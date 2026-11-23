# Personal data workspace

Predict has three destinations: [Data](https://predict.dock108.dev/data),
[Experiments](https://predict.dock108.dev/experiments), and
[Settings](https://predict.dock108.dev/settings). The existing remembered owner
login protects all routes, assets, APIs and exports.

## Data

Find a game by search, sport or Eastern start date. All six supported sports stay
available. Games are grouped on the server before pagination. Only established
canonical occurrence identity joins provider events; source-local games remain
separate and identifiable. Source-event counts are not unique-game counts.

Open a game for books, markets, main/alternate lines and actual source/receipt
clocks. Latest stored observations and frozen first-observation/T−10 checkpoints
are separate. A frozen game remains reachable after current rows expire.

Inspect an exact observation for original price, exact line, source identity,
probability reference, fees/cashflows, EV and underlying evidence. Missing inputs
stay unavailable and received prices remain visible. Where the exact retained
identity matches, Compare this exact bet opens both frozen observations. The
conservative per-bet screening estimate and coherent evaluation estimate retain
separate labels. Different lines remain different bets even when main status
changes.

Trading is prediction-market only: market-to-book EV/comparisons and
market-to-market comparisons. Sportsbook prices are reference evidence, not
trading EV results. Sportsbook-to-sportsbook and book-to-market result views are
excluded. Positive EV is a calculation filter for market offers. Arbitrage is a Data view of the existing
fee-qualified active pregame pair reader; unsupported date/provider/EV-status
filters are disabled there. Its bounded illustrative pair arithmetic is computed
from stored inputs, with no provider request or background calculation job. A
changed pair witness requires an explicit new selection.

Links and browser Back preserve filters, game, capture and exact bet. Catalog
paging uses a repeatable-read token with a two-minute lease. An expired token can
open a new stored snapshot, but exact revisions are checked and never silently
replaced. Exporting an already opened exact input uses its captured bytes even
after the paging lease expires. Checkpoint exports stay game-revision bound and
contain the complete immutable dependency bundle for offline reproduction.

## Experiments

The existing first-observation/T−10 experiment lists tracked games, capture
coverage, missing/refused/missed cases, early/late changes and available sporting
outcomes. The same game/bet inspector is used from Data and Experiments.
Declared populations, evaluation and frozen cohort exports remain available in
contextual details. This page does not contain another received-data browser.

Sporting outcomes, quoted EV, probability quality and actual trading returns are
separate. Missing outcomes and incomplete captures remain visible. NCAAB models,
game logs and accuracy work remain deferred; no new feed or backtest engine is
enabled by this interface.

## Settings

Settings reads real collection state, next discovery/checkpoint, reported credits,
unresolved holds, source state and finite storage. It retains Stop/Resume, source
pauses and essential discovery configuration. Control eligibility still comes
from the existing authenticated backend and its recovery/accounting guards.
Detailed operating evidence is expandable. Display preferences remain local.

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
