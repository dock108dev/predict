# Finite offline integrated workload

Authorized by the owner's attached integrated validation request, September 22, 2026. Fixture-only;
no real source activation, credentials, credits or existing beta restart.

Executable: `.venv/bin/python -m tests.integrated_workload evidence/b6-offline-20260923/timed-final 180 10`.
The executable rejects durations above 180 seconds and counts above ten. Ten
bounded segments target 30 minutes total; explicit Stop precedes each unchanged
180-second cutoff by 0.7 seconds. Segment setup/cleanup is measured separately
where available. This is not a continuous single-session or all-day claim.

Each segment uses the existing ContinuousSession collector, native Kalshi/US
loopback REST/WebSocket parsers, Novig NBX and ProphetX HTTP MockTransport adapters,
ordinary CoverageOwner, journal/queue, projection, references, calculation engine
and dashboard. All market bodies are synthetic. Mock credentials are literals;
secret loading raises. Injected adapters reject non-mock mode; loopback validation
remains in force. Production defaults and prior live allowances are unchanged.

The four native roles share an NFL full-game winner. ProphetX retains unknown
quantity/economics; it is not made executable merely to produce a comparison.
Each segment also supplies one market support reviewed synthetic market through the ordinary
collector admission/queue/journal: NBA full-game spread; NFL, NCAAF and NCAAB
first-half totals; MLB and NHL full-game spreads; MLB first-five winner; NHL
second-period winner; NBA league and conference championship fields. These
annotated market support inputs are explicitly distinguished from native wire parsing.
They establish product integration, not native source availability. Existing
focused regressions cover the other selected periods and families.

Updates: native WebSocket images/deltas at approximately five seconds; native
REST polls every 30 seconds, discovery every 60 seconds. Market support book images at each
five-second tick; model and delayed Pinnacle-shaped references at initial mapping
and tick ten. A rating input must remain unsupported. Manual what-if and the
preserved real Pinnacle historical sample are separate verification cases.
First segment: quiet Kalshi native book at 35–75 seconds. Second: disconnect US
at 40–45 seconds, continue other sources, require replacement image on recovery.
Each segment checks stable group IDs, unique dashboard rows, source visibility,
explicit Stop, task/socket cleanup and identical saved snapshot/calculations.
Fresh-process replay checks retained native reconstruction and calculation oracles.

Unchanged limits: 180 seconds per product run; 48 queue records/4 MiB; 2,048
admitted ingress records/16 MiB; 32 MiB journal with terminal reserve; 128 MiB
per-run output; 256 MiB process peak RSS; 100 REST requests per venue, six
simultaneous connections, twelve connection attempts. Native adapters keep their
own stricter budgets. Ten runs plus a short second-session check are bounded by
1.5 GiB total disposable output; check available disk before Start. No prior
output is deleted. Fail/stop if a segment ends unexpectedly or a replay differs.
Do not rerun the timed workload to diagnose a deterministic failure.

Separate short fault cases cover inventory identity replacement, missing/stale/
incompatible references, Stop amid admission, interrupted verified-prefix reopening,
resource/storage stops, corrections and immutable earlier resolution/pregame views.
An isolated ordinary browser covers idle/Start/filters/Details/references/Stop,
narrow layout and saved reopening. Failed attempts remain retained and excluded
from acceptance. Record PASS/FAIL/NOT TESTED without transferring fixture success
to provider delivery, actual source qualification or beta/owner acceptance.

Evidence: pre-edit hashes; executable and workload identity; progress, resource,
coverage and cadence samples; per-segment specs/journals/native replay/reports;
immutable cutoff/calculation oracles; fresh-process verification; focused/final
regression logs; browser screenshots and assertions; fault evidence; final report.

Observed boundary: the unchanged 30-call Novig native allowance is exhausted near
150 seconds; Novig becomes unavailable while other sources continue. This is
retained controlled budget behavior, not four continuously fresh feeds for thirty
minutes. The real-data follow-up must calculate its budget before approval.
