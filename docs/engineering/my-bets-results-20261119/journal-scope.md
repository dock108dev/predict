# Personal journal discovery scope

Automatic discovery records unique, positive after-fee market-to-market arbs.
The execution venues are Kalshi, Polymarket US, Novig and ProphetX. Standalone EV
quotes and market-to-sportsbook pairs do not create automatic journal records.
Manual saved/placed bets remain eligible regardless of venue or profitability.
The live Arbitrage board continues to support its existing comparison categories.

Uniqueness uses the exact game occurrence, market/period/selection/line and venue
pair. It ignores price refreshes, native quote aliases, leg order and decorative
selection labels. Existing record IDs, saved fills, revisions and history remain
stable when matching a prior automatic opportunity. Quote-history identity stays
unchanged so existing evidence remains accessible. Additive quote-alias links keep
renamed/native-ID updates attached to the original record, including quote-only
negative updates after an arb disappears. Only the decorative label is ignored;
participant, predicate, line, venue, period and occurrence remain exact.

The same eligibility rule governs normal lists, summary counts, exports, targets
and active quote tracking. Old unpicked market-to-book arb records remain stored
but are excluded from those views and future tracking. Saved/placed EVs continue
to collect closing evidence even when their current EV becomes negative.

The owner explicitly requested removal of EV records outside My Bets. The explicit
`Journal.prune_unpicked_evs(backup_path=...)` maintenance action takes a SQLite
writer reservation, creates a new full SQLite backup, then removes only EV entries
whose current decision is neither saved nor placed, their correction events and
orphaned tracking/quote evidence. Any remaining journal record sharing a quote ID
or identity protects that evidence. The method is idempotent and is not an app
startup action. It does not touch odds archives, source databases, account state,
quota records or acquisition controls.

A read-only production audit on November 19 found 122 distinct market-to-market
arbs across 70 games, with no leg-order or label duplicates in that subset. The
4,583 market-to-book arb rows contained the label-only duplicates observed in the
broader population. These are snapshot counts; normal acquisition and owner saves
continue while the change is implemented.

Verification and the explicit production cleanup receipt are retained with the
engineering handoff. The backup remains private on the installed data volume.

Local verification for the final scope: 88 relevant backend unit/integration tests
and 28 subtests passed, plus 6 disposable PostgreSQL tests and 4 subtests. The full
integrated My Bets and price-format browser modules passed all 26 cases. The alias
regression first reproduced both missing-history cases (zero captured quotes),
then verified discovery-time aliases and quote-only negative aliases after the
pair disappears, including reopened latest/closing metrics. Wrong economic fields
and invalid clocks remain rejected. Cleanup tests restore the pre-deletion backup,
check preserved bet histories and shared alias evidence, and exercise idempotency.

The paging toolbar sits above the results and remains sticky while scanning. Its
390px and 1440px regressions verify both paging controls stay within the viewport,
remain the actual hit targets after scrolling to the bottom, and do not introduce
horizontal overflow. This avoids scrolling through 100 cards to reach Next.

Engineer-led deployed checking then found a valid historical input absent from the
first fixtures: `reference: null`. The optional probability reader attempted a
dictionary lookup and failed the entire log request. Reference and contributor
maps are now type-checked; an unavailable fair model leaves EV unknown while
fee-only paired profit remains available. The regression first reproduced the
AttributeError, then passed 37 metrics/API tests and eight subtests, including a
real Journal HTTP list. Both phone/desktop log cases now persist an explicit null
reference with valid unchanged timestamps. A private, read-only captured-input
replay covered all 128 retained eligible automatic arbs and 153 nullable reference
quotes with zero analysis exceptions. Those captured inputs remain untracked.

Unplaced arb cards show both venues, exact signed selections/lines and original
prices directly, with a Record bet action. A collapsed-details regression checks
those leg labels are visible in the card summary at 390px and 1440px, so records
for the same game remain distinguishable without another popup.
