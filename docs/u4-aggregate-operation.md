# U4 shared aggregate operation

October 3, 2026. One scheduler under ordinary `CurrentService` supplies Novig/ProphetX through The Odds API while native workers continue independently. The current policy is 500 monthly credits with a 50-credit engineering reserve. No paid subscription or larger spending policy has been enabled.

## Ordinary launch and controls

From the repository run `.venv/bin/python -m app.dashboard --port 8785`, using a free local port. Open the board to attend acquisition. All tabs share one service and acquisition owner; filters, Details and venue columns do not launch requests. Existing processes retain their loaded code until reopened. Preserve other processes and active sessions. Native configuration and the default one-hour attended deadline remain governed by [native operation](u3-native-operation.md); this is no recurring background service.

Admin at `/admin` shows per-source status, aggregate requests, provider used/remaining, unresolved reservations, evidenced reset interval and next due. Pause `the_odds_api` to stop both aggregate venues; native controls remain independent. Stop revokes dispatch before cancelling workers, closes clients and releases ownership after cleanup. Paused/failed aggregate work does not interrupt native workers. Full operator diagnostics and recovery are U5.

The scheduler makes at most one quota-free `/v4/sports` bootstrap and two shared batches per runtime, three requests and six worst-case metered credits. Each batch requests one active sport, `novig,prophetx`, and `h2h,spreads,totals`. All event rows in that sport share that call. Preferred rotation is MLB, NCAAF, NBA, NHL, NCAAB, NFL, limited to active common sports observed at bootstrap. One global slot is paced by the remaining operating allowance and remaining window, with a minimum six-hour interval. This is not six-hour polling of each sport. Missed slots do not cause catch-up. No paid idle acquisition, automatic retry or historical fallback.

## Account evidence and durable accounting

Owner account evidence confirms monthly reset on the first at 00:00 UTC. The supported October interval is October 1 through November 1, 2026. `.local/predict-odds-window.json` references the immutable `.local/predict-odds-account-evidence-20261003.json` and its SHA256. Usage headers supply used/remaining/last charge; they do not supply reset time. The account evidence is distinct from a fresh balance observation.

A future window needs supported provider/account evidence, exact starts/ends, an absolute evidence-file path and matching SHA256. The loader verifies provider, evidence kind, interval and observation timestamp. Do not edit the ledger to simulate reset. A transition must be current, non-overlapping, and have no unresolved attempts. Existing consumed attempts remain retained, and usage must be bootstrapped anew. Current October evidence does not automatically create later windows.

`.local/predict-odds/quota.json` stores a versioned checksummed ledger, written atomically with file and directory synchronization under exclusive local locking. Reservation is durable before dispatch; the possible-dispatch marker is durable before entering transport. Cancellation/timeouts keep uncertain reservations. Duplicate reconciliation cannot refund or charge twice. Out-of-band use reduces allowance. Missing/duplicate/contradictory headers, clock discontinuity, ledger corruption or unresolved charges pause metered work. Restart preserves quota, rotation and next due. A budget-delayed bootstrap remains waiting; it does not terminate the scheduler or force a new request.

Operational bounds: 512 attempts, 12 old windows and 512 KiB ledger; reaching capacity pauses work without deleting unresolved records. Ordinary service authority has its existing 64-record/256 KiB bound. Preserve consumed records before any separately authorized operational maintenance. There is no ongoing quote archive.

Historical provider observation from U4: 248 used, 252 remaining, zero unresolved reservation, 202 available above the reserve. Four requests consumed six credits: two free bootstraps and two three-credit sport batches. These are retained observations, not a promise of today's account balance. Persisted next due was October 3 at 15:31:12 UTC; the next due can change conservatively with later authorized dispatch.

## Meaning and failure handling

Novig and ProphetX admit independently. A malformed venue retains its last valid inputs; an empty venue means unobserved in that exact query. Aggregate identity binds only the provider event and exact market/line/outcome. It never joins a native event on labels. Original decimal spellings, provider event IDs, participants, schedule and both bookmaker/market update clocks remain inspectable. Market update time is preferred; bookmaker time is a fallback. Upstream delay is unknown.

The board displays delayed values, receipt/source ages and unqualified freshness. Gross original-input arithmetic remains inspectable; fees, settlement, execution depth and calibrated probability remain unknown and withhold dependent results. Mathematical unit payout used for conversion does not establish actual venue settlement. Source-local aggregate identity does not establish native overlap.

Transport: one connection, 20-second request timeout, 2 MiB per response, 4 MiB per runtime, no redirects/proxies/decompression/retry, sanitized numeric accounting headers and credential-echo suppression. Retained real Odds API collectors use the same acquisition owner and quota ledger; explicit offline/mock transports retain their original contracts.

U4's recorder repair used a separately sealed, candidate-bound, five-minute diagnostic envelope for one extra shared batch within the original total six-credit authority. Ordinary startup has no such envelope and cannot bypass due time. Do not reuse consumed diagnostic identities.

See [qualification and site issues](../evidence/u4-current-20261003/README.md) and [U5 handoff](u5-current-handoff.md). Actual ProphetX delivery was observed; Novig was unobserved in retained NCAAF data. Sustained cadence, wider offerings, aggregate Details under a live paid candidate and owner acceptance remain unqualified.

U6 adds supported pre-start `aggregate_enabled: false` for native-only runs; existing configs default to true. Disabled aggregate operation has zero Odds API dispatch through startup and guarded recovery. See [native operation](u3-native-operation.md#u6-supported-native-only-startup). No pause race, credential suppression or accounting alteration is required.

U6 normally due free bootstrap at October 3 13:14:15.583875 UTC freshly observed 248 used/252 remaining, zero unresolved reservations and zero charge. Existing attempts, rotation 2 and paid batch due 15:31:12.131870 UTC were preserved; free bootstrap due advances to 19:14:15.398802 UTC. Paid final-candidate delivery/Details remains pending. [Exact U6 evidence](../evidence/u6-current-20261003/README.md).
