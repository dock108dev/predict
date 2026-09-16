# Public NFL odds source amendment

Implemented a file-only parser for one named DraftKings column on the [VegasInsider NFL odds page](https://www.vegasinsider.com/nfl/odds/las-vegas/). One direct public-page GET returned HTTP 200 on September 16, 2026 at 03:26:29.205210 UTC. No account, key, subscription, prediction-market scan, polling loop or access-control bypass was used. Source selection was limited to this page; the web reader also inspected that same URL.

## Retained evidence

- `evidence/public-nfl-reference/vegasinsider.html`: complete raw response, 1,031,142 bytes.
- `evidence/public-nfl-reference/capture.json`: URL, retrieval time, status, size and SHA-256.
- `evidence/public-nfl-reference/parsed.json`: selected event 32144330, Detroit Lions / Buffalo Bills, September 18 at 00:15 UTC, DraftKings +180 / −218, decimal conversions and unresolved gates.

The saved page is the real parsing fixture. Tests also mutate copies in memory, explicitly as test data. Both sides come from the DraftKings header's physical column within the same moneyline event group. Opening, consensus, other-book and best-price substitutions are rejected. Missing/duplicate fields and ambiguous column counts fail closed. Layout changes require a new fixture and parser review; no selector guessing or fallback retrieval is implemented.

The page's “Last Updated Sep 15 2026, 2:41 PM” text is retained as article/page notice text. It does not establish an odds or bookmaker timestamp. No explicit delay notice was found in the captured HTML. Bookmaker update time, disclosed delay and actual upstream freshness remain unknown. The parser also retains delay text if encountered in a saved fixture, without automatically treating unscoped prose as a bookmaker clock or certified delay.

## Research policy and remaining limitations

`public-page-delayed-research-1` uses a 20-minute receipt window and, when present, a 20-minute displayed bookmaker update window. A separately evidenced approximate delay of up to 15 minutes can permit research time eligibility without inventing an update timestamp. The target age limit remains 30 seconds; allowed receipt skew is 20 minutes; the pregame buffer remains 60 seconds. This policy is isolated from the existing synthetic-only pricing policy and live freshness rules.

Outputs carry **delayed-reference research estimate** and `current_executable=false`. Time eligibility alone does not authorize a probability or EV. This capture remains unavailable for estimates: no delay/update evidence, target-independent lineage assessment, normal-winner rules assessment or prospective target record. Copy lineage remains null; co-display does not prove upstream synchronization. Settlement compatibility, exceptional probabilities and all EV outputs remain null. Delayed/newer-price discrepancies cannot be described as executable edges.

This change implements the source amendment and parsing tests, not the larger prospective prediction/outcome-record loop described in the research plan. No real target was collected or prospective prediction produced.

## Replay and validation

From the project root:

```sh
.venv/bin/python -m app.reference.public_page evidence/public-nfl-reference --event-id 32144330
.venv/bin/python -m unittest tests.test_public_page tests.test_reference tests.test_pricing tests.test_math_reconciliation -q
```

The first command only reads saved files and prints JSON. The second passed **62 tests**, including 13 new source/policy tests and the existing reference, pricing and math-reconciliation checks. Tests cover same-column extraction, missing sides, duplicate books/tables/teams, changed columns, wrong market, bad source/hash/status, timezone requirements, preserved notice text, decimal conversion, disclosed delay acceptance, unknown delay rejection, stale/future clocks, target age and pregame cutoff. Existing observations and reconciliation evidence were not rewritten.
