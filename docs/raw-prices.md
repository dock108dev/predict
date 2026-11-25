# Raw prices and original inputs

The primary **Research** view at `/research` includes retained SGO bookmaker
observations, normalized offers and native/legacy raw books regardless of fee or
EV qualification. It exposes provider and original book separately from the
represented venue; the SGO `polymarket` alias has unestablished US equivalence.
Unknown facts remain null. Open a row to follow identity, reference policies,
fees/cashflows, original clocks and exact input/result revisions. Client export
retains the inspected object even after the bounded SQL read lease expires.
Positive rows remain separately accessible at `/opportunities`.

`app/dashboard/research_api.py` and `app/storage/research_catalog.py` own
`/api/research/catalog`, `/input`, `/export`, `/coverage` and `/cohorts` under
the common `/api/research` prefix. These are passive reads. The coverage panel
separates runtime liveness, actual receipt bounds, calculations and archive
content/counters; unsupported archive routes and recorded gaps remain explicit.

Original SGO HTTP-200 responses are separately retained by
`app/collection/original_receipts.py`, outside normalized ingress. The store
retains up to 128 MiB compressed and 16,384 receipt records with no automatic
eviction. Safe scope, receipt clock, parser
version and body SHA-256 link raw bytes to normalized facts. Byte/count/disk
refusals record gaps without another provider request or changes to accounting.
Existing normalized history cannot reconstruct response bytes discarded before
this feature. Received unsupported fields and never-requested markets differ.


The **Raw Odds** view at `/raw-odds` reads retained source-local books from SQL.
It does not wait for matching or financial calculations. Filters select league,
venue, family, period and available source states; search and pagination operate
on the captured result. **Original inputs** shows source identifiers, original
values, quantities and clocks. Missing values are not rendered as zero.

The raw list includes last-known and unusable observations with explicit states.
Receipt time, provider time, write time and synchronization are different facts.
Polling or recalculating cannot make an old price fresh. An optional captured
calculation comes from an immutable member of the ordinary display generation.
The raw read token pins that generation across pages. The result keeps its own
captured inputs and clocks, which may differ from the selected raw observation.
See [calculation limits](benchmark-ev.md).

## Price interpretation

Polymarket's Long bid supplies the complemented Short ask and its quantity; a
separate Short bid is labeled as not supplied. Kalshi complemented asks retain
the opposite bid as their basis. Polymarket spread sides retain their signed
lines; Kalshi scoring predicates are labeled as thresholds. These presentations
do not invent separately received ladders or settlement equivalence.

## Read lifecycle and API

`app/dashboard/raw_price_api.py` owns the read lifecycle and
`app/storage/raw_prices.py` owns selection and projection. The routes are:

| Route | Purpose |
| --- | --- |
| `GET /api/raw/prices` | Filtered captured page and continuation token |
| `GET /api/raw/inputs` | Selected original book inputs |
| `GET /api/raw/calculations` | Captured calculation overlay |
| `GET /api/raw/failures` | Retained unusable inputs and reasons |
| `GET /api/raw/export` | Stream original retained data |
| `DELETE /api/raw/read` | Release a captured read |

List pagination uses a repeatable-read, read-only transaction. At most eight
snapshots remain open for 120 seconds each. Filters are bound to the token;
changed filters or expired tokens require a refresh. The reader rechecks live
runtime authority while paging. Failed SQL reads discard their snapshot;
refresh, release and shutdown close it. The API also bounds concurrent work and
SQL execution time. Capacity refusal is visible rather than a truncated success.

`raw-odds.html`, `raw-odds.js`, `raw-odds.css` and `raw-result-view.js` are authored
assets served directly, not components of the generated `stored.js` bundle.
Restart the app after backend changes; reload the page after static changes.
`tests/test_raw_odds_controls.cjs` exercises navigation/loading controls;
`tests/test_raw_prices_sql.py` exercises reads against disposable PostgreSQL.
See [development](development.md) for the isolated test workflow.
