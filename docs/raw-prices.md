# Raw prices and original inputs

The ordinary **Odds** view at `/odds` reads retained source-local books from SQL.
It does not wait for matching or financial calculations. Filters select league,
venue, family, period and available source states; search and pagination operate
on the captured result. **Original inputs** shows source identifiers, original
values, quantities and clocks. Missing values are not rendered as zero.

The raw list includes last-known and unusable observations with explicit states.
Receipt time, provider time, write time and synchronization are different facts.
Polling or recalculating cannot make an old price fresh. An optional captured
calculation is associated with its exact input identity and does not grant
current trading eligibility. See [calculation limits](benchmark-ev.md).

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
