# Bounded acquisition — Pinnacle executed; model proposal unapproved

Implementation and offline evidence are in the [handoff](reference-integration.md). This proposal consumes no Novig/ProphetX access and does not restart prediction-venue collection. Full reference integration remains open.

## Pinnacle allowance consumed — September 21

Owner completed Keychain setup and local free-plan confirmation. Reference: `keychain:prediction-arb.the-odds-api.free/nfl-pinnacle-readonly`. The single authorized call returned HTTP 200, used one credit and reported 499 remaining. Seventeen NFL events returned; 15 contain Pinnacle h2h and two have no bookmakers. Sixteen side references were retained from the first eight populated events. [Actual evidence](../evidence/b4-pinnacle-sample-20260921/final-report.md). No repeat request is authorized.

## Original executed Pinnacle bounds

Owner creates or uses **only the free** The Odds API plan and stores its key locally in a secret store, giving Codex only the local reference name. Do not put a key in chat, a checked-in file, an HTTP log or the retained request URL. Setup is complete; only the configured local Keychain reference was read for the authorized request. Account plan/entitlement must be confirmed locally before collection. Do not upgrade if Pinnacle is absent.

The owner authorized one finite read-only request to `GET https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds` with `bookmakers=pinnacle`, `markets=h2h`, `oddsFormat=decimal`, `dateFormat=iso`. API key is supplied locally at execution and omitted from retained metadata. Purpose: test free entitlement/population and retain one native response for the existing adapter. Bound: **one request, at most one planned credit, 256 KiB response, 20-second timeout, no retries, no pagination, no sport/bookmaker fallback**. Maximum 16 extracted side references, chosen deterministically by event start and ID; preserve the bounded original response, even if there are more events. No historical/paid endpoint.

Retain the sanitized request plan, allowance/reservation, HTTP status, original body, response digest, quota headers, actual UTC receipt, bookmaker/market update times, explicit event/participant mapping and generated records under a new reference integration acquisition evidence directory. Private local retention only. Never modify earlier retained packages. Import only into a separately approved active product session whose market identity matches, or a new retained-data replay package with an honest later receipt/cutoff. A new receipt must never be backdated into an older saved calculation.

Stop after that response; also stop on missing free entitlement, missing local key, 401/403/429, timeout, oversize, unexpected quota cost, missing/duplicate Pinnacle or ambiguous identity. Record missing coverage honestly. A populated response alone does not establish delay duration, broad sports coverage, independence, or full reference integration completion.

## Model acquisition, separately bounded

Selected model routes are retained published outputs, not a newly invented provider API. MoneyPuck is the first sporting-input candidate; NFL ESPN FPI is only a market-informed alternative. Propose **one GET of https://moneypuck.com/**, whose game previews are identified in its methodology, with no linked pages or data requests followed. Purpose: retain the currently published pregame-game-win output and its identity/date contract. Bound: one request, zero API credits, 20-second timeout, 256 KiB original body, at most two explicit win probabilities for the earliest upcoming NHL game with complete source identity. If the page requires additional requests, supplies only ratings/season outcomes, has no eligible game, or lacks usable date/outcome semantics, retain the gap and stop. No guessed probability conversion. Record the original body, literal offsets, visible dates (or unknown), source URL, actual receipt and mapping evidence; private local retention only, under a new reference integration acquisition directory. No account access or key is needed for this model leg. The response is not automatically proof of a compatible prediction market or permitted recurring acquisition.

MoneyPuck/FanGraphs/NBA/NCAAF/NCAAB ordinary comparison mapping remains market support. Model capture can preserve inputs before those cells become usable, but cannot count as integrated EV evidence prematurely. Current-source model independence remains a reference integration evidence gate.

KenPom is deferred by owner; no login or entitlement investigation is requested. The revised model acquisition contract and exact NHL mapping dependencies are in [model/mapping next steps](reference-data-gaps.md). The MoneyPuck proposal is not approved or executed; Pinnacle approval does not cover it.

## Completion rule

Only mark full reference integration COMPLETE after both roles have reproducible actual-source records in ordinary Details/conditional EV/history, with the chosen model's dependency qualification clearly recorded. Offline fixtures, a free plan advertisement, existing KenPom membership, or a lone response do not satisfy that gate. Venue integration requests remain sent/pending; beta remains NOT READY FOR SIGNOFF.
