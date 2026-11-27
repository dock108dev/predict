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
one native market. The two-hour window prioritizes exact sportsbook-reference
candidates and leaves capacity for the rest of the slate. Kalshi REST reads
are batched. Each venue refreshes and publishes independently. A bounded
Polymarket US subscription reuses a fresh two-sided
market image for priority slugs when the read-only stream is available.
Overlapping native HTTP consumers share one in-flight receipt and enforce their
own cutoffs. Source throttles defer work.

`app/storage/native_trading.py` owns immutable native evidence revisions and
the current offer pointer. Native event/market/outcome IDs identify an offer.
Both team roles and a unique occurrence establish a canonical game link. An
exact typed source event link can explain different schedule clocks; the
original clocks and matching method remain in the evidence. Nearby timestamps
alone do not establish such a match. Existing game identifiers, source evidence
and paper checkpoint clocks are not rewritten.

Book source time, HTTP cache-origin evidence, receive time, calculation time and
publication time remain distinct. Repeated revisions do not renew expiry.
Regressing clocks or sequences cannot replace a newer image. A temporary failed
refresh preserves the previous book only through its original expiry. Explicit
ordered lifecycle evidence can invalidate it earlier. A new sportsbook reference
can revalue the retained book without re-dating that book.

The existing exact reference policy requires two complete trusted sportsbook
pairs at the selected signed line. References have an independent source-clock
deadline. The reader also checks known reference withdrawals and schedule/phase
changes. Whole-line pushes, NFL ties and unverified settlement terms do not
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

Until credentials, entitlement and tournament IDs are qualified, runtime status
reports the specific access dependency. Native price and quantity do not imply
that an applicable fee schedule or exact settlement has been verified.

Sources: [ProphetX Market Data integration](https://docs.prophetx.co/docs/market-data-integration),
[Novig catalog and participant identity](https://docs.novig.com/api/catalog).

## Release verification

Migration 128 is additive and uses the ordinary guarded schema-maintenance
release, including its pre-migration backup. The native tables are independent
of frozen paper campaigns and results. Starting a Win $25 test or changing the
production campaign remains a separate owner action.

Use `tests/test_native_trading.py` for native-only discovery, exact reference
pairs, both-role matching, schedule skew, price audit and shared book reads.
`tests/test_native_observation.py` exercises failed, repeated and out-of-order
updates. `tests/test_native_trading_sql.py` belongs in the disposable PostgreSQL
harness. Hosted qualification additionally requires real source receipts,
coverage over several refresh cycles, signed-in desktop/phone checks and
before/after protected-state fingerprints. Fixture results do not establish
those hosted outcomes.
