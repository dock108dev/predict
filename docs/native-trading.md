# Native trading offers

Dashboard trading prices and displayed books come from the official Novig,
Kalshi, Polymarket US and ProphetX APIs. SportsGameOdds supplies sportsbook
references and its existing schedule/result inputs. Its trading quotes are
retained as comparison evidence; they never replace a native price.

Positive EV remains the default Dashboard view. **All venue offers** includes
native selections without a qualifying sportsbook reference or current book.
**EV unavailable** shows current books without a sized EV. A missing reference
does not erase an observed quantity. Main-line roles without native authority
are reported as unclassified.

`app/collection/native_trading.py` owns discovery and book refresh. It uses the
existing native catalog parsers and exact sizing model. Discovery traverses the
configured six-league 24-hour window separately from book refresh, alternating
the nearest window with the remaining slate. Book requests group both sides of
one native market. The two-hour window prioritizes books with exact usable
references and keeps room for upcoming offers without them and the later slate.
Kalshi REST reads are batched. Each venue refreshes and publishes independently.
Upcoming Kalshi and Polymarket US occurrences get exact-kickoff catalog refreshes ahead of
metadata expiry. Depth reads require current instrument terms. A bounded
Polymarket US subscription reuses a fresh two-sided
market image for priority slugs when the read-only stream is available.
If the stream stops advancing, the same instrument is eligible for REST on
the next turn. The stream retains its source-time watermark across reconnects,
and the publisher applies the persisted ordering rule to both transports.
Overlapping native HTTP consumers share one in-flight receipt and enforce their
own cutoffs. Source throttles defer work.

`app/storage/native_trading.py` owns immutable native evidence revisions and
the current offer pointer. Native event/market/outcome IDs identify an offer.
Both team roles and a unique occurrence establish a canonical game link. An
exact typed source event link can explain different schedule clocks; the
original clocks and matching method remain in the evidence. Nearby timestamps
alone do not establish such a match. Existing game identifiers, source evidence
and paper checkpoint clocks are not rewritten.
Contradictory typed links, team roles and doubleheader numbers are retained as
identity rejections. A typed SGO outcome link that disagrees with the selected
side or line is recorded in the price audit as an identity conflict.

Book source time, HTTP cache-origin evidence, receive time, calculation time and
publication time remain distinct. Repeated revisions do not renew expiry.
Regressing clocks or sequences cannot replace a newer image. A temporary failed
refresh preserves the previous book only through its original expiry. Explicit
ordered lifecycle evidence can invalidate it earlier. A new sportsbook reference
can revalue the retained book without re-dating that book.

The existing exact reference policy requires two complete trusted sportsbook
pairs at the selected signed line. The collector interleaves paced exact-event
requests for known exact games in the next two hours with ordinary monitor pages.
The requests use the shared source controls, account and operational budgets,
and preserve headroom for the next monitor page and protected checkpoint work.
They use the established alternate-line bookmaker scope to preserve source event
matches and audit inputs. References have an independent source-clock deadline.
New SGO admissions trigger revaluation of retained fresh books in the affected
league. Deferred revaluations retry using the current admission clock. The reader
also checks known reference withdrawals and schedule or phase changes.
Whole-line pushes, NFL ties and unverified settlement terms do not
receive invented probabilities. Quantity and observed price can still be shown
when fees or settlement prevent EV. The saved fee-mode setting is captured with
each valuation; original native fee terms remain in the receipt.

The evidence drawer and JSON export use the saved native revision. Explicit
amount requests use the latest fresh stored book for the same native instrument,
occurrence and settlement terms, and return that book's evidence and price.
Ordinary Dashboard and export reads do not acquire source data or schedule
calculations. Native evidence has a separate 384 MiB logical allowance and the
existing whole-database storage guard. Superseded native snapshots are eligible
for rotation after five minutes, or two minutes near the native allowance.
The current pointer is eligible for rotation two hours after kickoff. Export a
native revision to retain its evidence independently. This rotation applies to
the Dashboard's native evidence tables.

## ProphetX access

The read-only Market Data API requires an affiliate API key, separately from
the trading API's access/secret pair. Its documented production base is
`https://cash.api.prophetx.co/partner`. Requests send the affiliate key in
`Authorization` without a Bearer prefix. The client allows only tournament,
event and batch-market GET endpoints. It has no order, balance or account-write
routes.

The collector reads `prophetx-market-data.json` from the existing private provider
secret directory. It contains `api_key` and a `tournaments` object mapping
configured league names to reviewed official tournament IDs. On macOS the
equivalent Keychain service is `prediction-arb.prophetx.market-data.production`,
account `read-only`. Credentials must never be included in logs or Git.

The published NFL, NBA, MLB and NHL IDs are defaults. The collector verifies
each ID in the authenticated production tournament response and retains that
receipt alongside the event roles. Configure the official NCAAF and NCAAB IDs
after checking the entitled catalog. Runtime coverage reports credential and
entitlement failures for the venue and tournament mapping gaps for each league.
Duplicate IDs across leagues and names that contradict the league are refused.
The collector keeps the strike ID and provider outcome ID together. An
expired event-status receipt triggers an exact event refresh alongside depth.
Only current scheduled-event evidence can qualify the resulting book for
pregame execution.
Available quantity is recorded in USD stake. A partial affiliate response can
establish observed liquidity. Exact settlement, applicable fees and the extent
of the available book require independent evidence before sized EV can qualify.

Sources: [ProphetX affiliate tournaments](https://docs.prophetx.co/reference/get_affiliate-get-tournaments),
[ProphetX event and tournament IDs](https://docs.prophetx.co/reference/get_affiliate-get-sport-events),
[ProphetX affiliate market data](https://docs.prophetx.co/reference/get_v4-affiliate-get-multiple-markets),
[Novig catalog and participant identity](https://docs.novig.com/api/catalog).

## Protected official replay

New decisions collected under the active Win $25 pilot can carry
`official-native-book-win25-shadow-1`. Official catalog membership supplies
the shadow candidates even when the matching SGO trading quote is absent.
The pilot keeps its existing quote selection, sizing, published results and
grades. Both policies can consume the same exact book read. The shadow records
unresolved occurrences, missing fees or references, and observed capacity with
their original source, request and receipt clocks.

The pilot stages at its own completion clock. The shadow has a separate
durable spool and immutable SQL receipt linked to the original decision and
exact SGO checkpoint by game, schedule revision and T−10 target. It finishes
within its own cutoff or records a separate disposition. Both lanes use the
8 MiB per-receipt bound. Shadow payloads also use the independent optional
observation allowance and yield to protected checkpoints and ready pilot
receipts. Existing combined receipts retain their original IDs and remain
readable. A separately sampled follow-up is outside the decision.

The scheduled replay commits the original run before admitting the optional
shadow attachment. Dated run and campaign trade exports link to a separate
per-game shadow export. An oversized or deferred attachment leaves the
original report and its export available. The Win $25 calculation uses the
official ask, exact reference and applicable fees.

The post-commit SQL observation binds the exact checkpoint, game, schedule,
target and accepted SGO receipt. An observation by T−9 proves the checkpoint
committed by its deadline. The export labels late and missing observations.
A newly recorded witness can produce another replay revision. Earlier exports
retain their pinned proof status. Later revisions read the immutable witness
after acquisition retention removes the original lookup rows. Campaign creation
and policy cutover remain separate owner decisions.

## Release verification

Migration 130 adds the protected shadow receipt table. Migration 131 adds the
exact checkpoint witness and per-run shadow attachment. Install both through
the guarded schema-maintenance release, including its pre-migration backup.

Use `tests/test_native_trading.py` for native-only discovery, exact reference
pairs, both-role matching, schedule skew, price audit and shared book reads.
`tests/test_native_observation.py` exercises failed, repeated and out-of-order
updates. Use disposable PostgreSQL for `tests/test_native_trading_sql.py` and
the protected capture and replay checks. For the four-venue release, verify the
first complete naturally scheduled trace per accessible venue on the installed
candidate. Link the official book, signed-in pickup and original expiry, T−10
receipt, matching T−9 commit witness and saved replay. Record unavailable access
or a pending eligible occurrence in the release handoff.
