# E6 first real run — Kalshi and Polymarket US

Updated September 15, 2026. This replaces the former mandatory three-provider owner form. Prediction-market feeds are primary; external sportsbooks and The Odds API are optional and excluded from the next run.

## Engineer-prepared run specification

- Sources: Kalshi and Polymarket US only, using existing project read-only access. Verify current no-additional-cost access and official rate limits; do not assume a monetary API-credit model where none applies.
- Event: discover one unambiguous shared NFL pregame moneyline; retain native IDs, participants, kickoff and mapping evidence. Select the earliest suitable game with enough time for the bounded run. The owner need not supply technical IDs.
- Duration: maximum 300 seconds, ending before kickoff; record actual start/deadline. Use bounded discovery/subscriptions and venue-appropriate refresh. Derive eligibility thresholds from supported evidence, keeping unknowns explicit.
- Budget: zero additional spending, no subscription/upgrade; finite request, connection, frame and byte caps within existing transport ceilings. Record access basis and actual usage.
- Storage: a new isolated file observation journal and exact saved replay. No owner database migration or service restart.
- Credentials: resolve only existing project credential references through the supported local mechanism after the implementation prompt is invoked; never save values in specifications, logs or exports.
- Calculations: reference-dependent results remain unavailable. Capture and native books do not depend on E3/E4; expose Arb only through existing engines with real supported dependencies, otherwise precise diagnostics.

## Implemented prediction-only path

The legacy three-provider JSON skeleton is revised: only Kalshi and Polymarket US are required, and `reference_enabled` defaults to false. Pure preflight does not access credentials or providers. Explicit discovery and Start use only the existing dedicated project Keychain entries. See [integration and measured result](e6-prediction-only-report.md).

The isolated CLI supports `--discover --output NEW_DIRECTORY`, followed by `--start --output SAME_DIRECTORY`. Start refuses a second capture in the same output. Ctrl-C/termination requests cancellation and joined shutdown. The bounded capture from this slice consumes its one-run authorization; these commands do not authorize a new run.

The optional `reference_enabled: true` path additionally requires `sources.the_odds_api`, `reference_cadence` and the full bounded `http` policy. It reads `ODDS_API_KEY` only at explicit real Start. The engineer must establish the applicable free-plan request cost and remaining quota first, count discovery/retries within five credits, and supply zero additional dollar cost. No key, unknown quota or uncertain cost means skip references. Only `pinnacle`/`h2h` is requested; their absence or failure does not stop prediction capture. Retained responses alone do not qualify fair prices or economics.

No owner database migration or service restart is involved. The E5 preview remains accepted and unchanged. The measured capture does not establish continuous reliability or full E6 completion.
