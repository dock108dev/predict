# Sport-directed native game discovery

Policy `sport-directed-games-v1` uses the existing continuous collector, adapters, compact catalog, source isolation, journal, projection and saved history. Revision 4 remains consumed; its original opening failure and separate compact derivation are unchanged. No live market-data request, credential access, credit spending or restart occurred during this engineering. Public documentation was retrieved separately.

## Selector authority and coverage

| Sport | Kalshi series (observed catalog) | US league tag (observed) | Retained game-selection demonstration |
|---|---|---|---|
| NFL | KXNFLGAME | nfl | Both sources: original supported response bodies, ordinary discovery-only runtime |
| NCAAF | KXNCAAFGAME | cfb | Series/tag authority only; no retained supported game selection |
| NBA | KXNBAGAME | nba | Series/tag authority only; no retained supported game selection |
| NCAAB, men's Division I | KXNCAAMBGAME | Unestablished | Kalshi series authority only; US league identifier still missing |
| MLB | KXMLBGAME | mlb | Series/tag authority only; no retained supported game selection |
| NHL | KXNHLGAME | nhl | Series/tag authority only; game identity adapter also unqualified |

Series come from the hash-verified September 11 Sports series response. US tags/league slugs come from revision 4's complete league metadata embedded in events. NFL successful filtered-event pages and selected market responses come from the consumed September 28 supervised comparison. Those listings are historical observations, not current availability. `evidence/native-selectors-20260930/selector-input-manifest.json` identifies originals. No series ticker or league slug is constructed from a sport name.

[Kalshi's event schema](https://docs.kalshi.com/api-reference/events/get-events) supports series filters, cursor pagination, milestones and nonnested summaries. Each evidenced game series gets at most two five-event pages, open status, milestones, nested markets disabled. A local observed-kickoff window selects 5 minutes through 7 days ahead. `min_close_ts` is documented but is a market-close condition, not kickoff; it is deliberately not substituted for a game-time filter. No category-only broad fallback occurs. The Sports series category is useful identifier authority, not a reason to fetch all open events.

[US's events schema](https://docs.polymarket.us/api-reference/events/get-events) supports tag, time and market-type filters. The proven NFL query uses `tagSlug=nfl`, active/not closed, startTime ascending and the observed `football_team_full_game_winner` discovery seed. Other evidenced leagues use their observed tag and the observed `games` tag through documented `tagSlugsAll`; game finding is then checked against returned league, two participants and gameId. Each query sends startTimeMin = generation start + 5 minutes and startTimeMax = generation start + 7 days; the client repeats that time check. At most two five-event pages per league. Server behavior for the new tag conjunction and non-NFL queries still needs fresh evidence.

The [dedicated US league endpoint](https://docs.polymarket.us/api-reference/sports/get-events-by-league-slug) supports games/futures separation. However, the retained September 11 response embeds about 1.5 MB per game; the successful September 28 filtered query returned five games in about 52 KB. Therefore the implementation reuses filtered events rather than fetching the entire league-game structure. A single event can still exceed either body or parse limits; smaller pages are not a guarantee. No undocumented summary switch is added.

The [US league metadata endpoint](https://docs.polymarket.us/api-reference/sports/get-all-leagues) is captured with at most two 50-league pages. This obtains the exact missing NCAAB identifier evidence for review. It does not guess a slug or promote a league name to men's Division I qualification. All six sport slots remain in decisions; NCAAB is explicitly `selector_unestablished` on US until that evidence supports a local binding.

## Finding versus qualification

Findings report native game ID, source hash, observed or unknown schedule, sport query and exclusions. They are sorted by known kickoff, then native ID; one game per evidenced sport can justify one page of selected-event metadata (50 markets). Missing schedule is an explicitly unqualified metadata finding, not a constructed canonical event. Kalshi unknown milestone kinds, NHL identity support, college participant mappings, market family/period, settlement and cross-source identity remain separate adapter/admission gates. A known game series does not establish any of those facts.

US futures without gameId/two teams, null or conflicting league facts, inactive/unknown status, missing title/ID, outside-window schedules and duplicate/invalid pages cannot become qualified games. Complete earlier pages remain raw evidence; incomplete JSON contributes no objects. Per-sport query errors are visible while independent queries continue. Parse/body/duplicate safety failures still stop that source; shared persistence/queue/RSS/deadline failures stop globally. Full traversal is never promised by a page cap.

## Resource reconciliation

For an integrated policy (not a prepared acquisition): Kalshi 4 account attempts + 3 generations × (12 event pages + 6 market pages) × 2 attempts = 112. US 3 × (2 league pages + 10 event pages + 5 market pages) × 2 = 102. With unchanged 37 aggregate requests, the ceiling is **251 HTTP**, down from 455; 12 WS attempts remain a separate ceiling. Existing source roles and aggregate credit limits are unchanged. No integrated package or new paid refresh is prepared here.

The prepared public discovery-only probe is one generation: Kalshi (12 + 6) × 2 = 36; US (2 + 10 + 5) × 2 = 34; **70 HTTP, zero WS, zero aggregate requests, zero credits, zero purchases, zero credential access**, 90 seconds. It uses public listing/market metadata endpoints, skips account calls, and disables subscription selection. Timeout/recovery attempts consume the same lifetime allowance. One failed/interrupted attempt is consumed; no automatic restart.

Unchanged envelopes: 2 MiB discovery response, 1 MiB market metadata, 64 KiB account metadata, 256 KiB book frame; per source 6 MiB cumulative HTTP within 8 MiB shared native bytes. Compression is refused (zero decompression budget); JSON scan bounds depth to 32 and structural tokens to 100,000; duplicate keys and nonfinite numbers fail. Queue 48 records/4 MiB; normalized inventory must fit below 4 MiB minus 64 KiB before publication. Journals are bounded to 32 MiB compressed and cumulatively expanded / 4,096 rows with terminal reserve; output 128 MiB plus 4 KiB control metadata; free disk floor 1 GiB. **256 MiB RSS is a sampled stop threshold, not a hard memory ceiling.** Byte, parse, request, storage and deadline limits intersect; worst-case responses/retries need not fit simultaneously.

The captured US broad inventory is 6,145,186 bytes. Three repeats would be 18,435,558 bytes before books/details, incompatible with the unchanged 6 MiB HTTP lifetime cap. The first full-duration stress attempt correctly stopped US in generation 2 and remains retained. Successful stress qualification must use smaller later game refreshes; increasing traversal/body budgets is not the remedy.

## Verification classes and remaining gates

`selection-evidence.json` records supported versus unproven cells. The retained probe serves unmodified supported NFL response bytes through ordinary discovery, metadata lookup, Stop and saved reopening, without books or aggregate traffic. Synthetic empty non-NFL responses in that harness are controls, never absence evidence. Separate synthetic transport tests exercise subscriptions and concurrent aggregate updates. The full-duration retained-volume stress also uses labeled synthetic supported games/books; it establishes resource/control behavior only, never the validity of discovery queries.

The future native-only probe must capture complete responses to the exact series/tag/time queries and selected details, including US league metadata. It must report every sport as found, unestablished, empty within bounded query, excluded, failed or traversal-limited. An empty response does not prove seasonal absence; source listings are not qualified period/settlement/cross-source matches. Missing native schedule/participant/period/rule facts require reviewed evidence before subscriptions or economics can be qualified. Owner/commercial validation remains deferred.
