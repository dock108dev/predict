# SC06 authored integrated responsiveness evidence

October 16 owner priority update: current responsiveness is sufficient for local
use. Formal 30-ticket and independent burst/churn qualification is deferred and
nonblocking; no further stress campaign is queued. This document retains the
workload, actual results and unperformed checks as evidence, not a current local
development gate. Historical failures are not relabeled as passes. Data/app
separation and the remaining actual-source/customer work proceed next.

The maintained qualification is `browser_tests/sc06_browser.cjs`, invoked by
`browser_tests/test_sc06.py`. The wrapper provisions PostgreSQL 16 through
`scripts/ci/postgres.py --sc06-browser`; it has no socket-missing success or scalar
fallback. `tests/test_sc06_performance_sql.py` verifies the three position types,
SQL depth reconstruction, a real ready selected ticket, genuine post-commit
observation, preserved expiry and missing-depth refusal. Timing qualification is
separate from this small smoke test.

## Workload and evidence class

The test owns a new database on a separately verified socket-only PostgreSQL 16
cluster, a temporary summary directory and one actual headless Chromium browser.
It does not initialize provider services, acquire sources, renew production model
reviews or read owner business tables. The Python server rejects non-loopback
network connections; the browser blocks and records external requests. The
ordinary main application and owner data are separate from these disposables.

There are 500 distinct active authored events and 1,000 exact instruments: 167
native pairs (Kalshi plus Polymarket US), 167 ordinary stake pairs (Novig plus
ProphetX) and 166 mixed stake/native pairs (Novig plus Polymarket US). Counts by
venue are 167 Kalshi, 333 Polymarket US, 333 Novig and 167 ProphetX; the actual SQL
readiness output must reconstruct exactly 500 compatible pairs. Each position
has two persisted depth levels. Native levels contain 150 and 300 contracts;
stake levels contain $80 and $160, with worse second-level prices. Authored grids
are whole purchase contracts and $20 stake increments. The finite stake grid is
exhaustive; the native discovery search retains its ordinary bounded-search
meaning and makes no global optimum or maximum-capacity claim.

Profiles are explicitly test-owned assumptions attached to the exact SQL-decoded
quote/event/selection binding. The actual shared venue fee engines calculate
nonlinear quadratic native fees with their rounding/aggregation rules; ordinary
positions use 1.5% or 2% rounded winning-gain commissions. A $0.01 authored entry
charge exercises the fee/funding reconciliation. Cash-funded purchase contracts
and independent cash stakes are included; unsupported Short collateral is not
silently qualified. Native neutral cases pay an authored $0.50 per contract;
stake neutral cases return the stake. These are financial workload assumptions,
not claims about a current venue's contracts or collateral support. Covered arb,
conditional and unavailable optional EV remain distinct under the real evaluator.

The test clock starts at the original model fixture instant, October 11, 2026,
and advances continuously with elapsed monotonic time. The event schedules are
future authored schedules. Original quote and book clocks are set once at test
admission; only deliberate material source updates advance their own originals.
The production 30-second native and 900-second ordinary age limits remain in
force. Slow initialization may therefore lose coverage and cannot become a
complete ready ranking through a clock reset or renewal.

The SQL path is `CurrentRowStore.upsert_records` plus
`replace_native_books` inside the genuine publication transaction. The receipt
observation precedes control JSON parsing and typed current-row admission. This
is a local authored intake observation, not a provider network-latency claim.
`scanner_publication.committed()` records a successful top-level post-commit
observation; it is not PostgreSQL's exact commit instant. Its UTC remains the real execution date, while the authored financial/browser wall clock is the advancing historical replay clock. Only explicitly correlated monotonic observations join latency across those domains. The complete readiness
adapter, financial evaluator, projection, summary worker, HTTP handlers and
maintained browser assets then execute normally. The only test-specific
readiness addition accepts ordinary observed depth when positive depth was
actually reconstructed from SQL. All remaining contract, source-clock, native
book, model, legal-grid and expiry checks remain active. Negative SQL smoke
checks demonstrate missing depth and expired native originals still refuse
readiness.

## Measurement contract

Cold initialization and a cached partial-scope reload are recorded separately.
The reload cannot qualify the warm complete-scope target if the scope is partial.
There are 30 sequential material updates, then 30 selected-ticket attempts. Burst
and unrelated-churn submissions retain their own disposition. A superseded or
coalesced submission is never counted as a painted sample. Every failure,
waiting period and timeout stays in the report.

Each material observation retains exact source IDs/clocks, SQL contract and
current-row revisions, the genuine post-commit observation, detached capture,
pair calculation, projection publication, HTTP scheduling/body/validation, DOM
application and second-animation-frame observation. The target DOM row must
match the dependency and economic revisions and intersect the viewport. A
delivered but hidden/offscreen row is insufficient. Selected-ticket success
requires the maintained ticket client's actual ready second-animation-frame
sample; terminal failure and timeout remain failures.

Python and browser monotonic clocks are correlated by five browser-to-loopback
clock roundtrips, selecting the minimum RTT midpoint and retaining every probe.
Half RTT is the correlation uncertainty. Correlation repeats every ten material
updates. Direct subtraction of unrelated monotonic origins is never used. Queue
waiting is bounded from detached capture completion to calculation start; that
upper bound includes dependency admission and is labeled accordingly. Original
calculation clocks remain attached to reused economics.

Percentiles use nearest rank, `ceil(p * n)`, without interpolation. The report
retains p50/p95/max, all individual observations, failures, browser version,
hardware, exact application/engine/assets/policy binding, PostgreSQL database
bytes, free disk and process resource witnesses. The server enforces 2 GiB SQL,
1 GiB free disk and 768 MiB process guards. Browser-process RSS witnesses are
retained separately from Python and Node peaks.

## Demonstrated repairs

A real SQL stake-depth test exposed the current-row adapter incorrectly applying
the native [0,1] purchase-price range to decimal odds. Decimal-odds ladders now
use their own minimum-one range, while native bounds and finite positive amounts
remain enforced. A second regression showed stake-only events lost persisted
depth during selected-event hydration; all selected quotes missing their depth
now hydrate from SQL.

The measured 500-event cold readiness capture performed the same full current-row
capture twice and then issued per-event depth reads. Scanner readiness now shares
one repeatable-read capture, including bounded ladders, with `ReadContext`.
Existing selected ordinary readers retain their normal capture behavior. The
revision guard no longer calculates an expensive fallback hash when an exact
SQL dependency revision exists. Quantity-independent reference/probability
preparation moved outside the financial allocation loop; its allocations,
cashflow states, fee owners, observed depth, legal grids and buffer are unchanged.
The existing 28 scanner/ticket arithmetic tests passed after this move.

## Retained results

Machine-readable measurements, causal traces and captures are written under
`test-results/sc06/performance/`. Earlier diagnostics remain under
`test-results/sc06/performance-diagnostic/`; they qualify their own recorded
inputs and source identity. The final report's `qualified` value and explicit
failures determine which timing targets were actually met. A passing SQL smoke
or a fast DOM application cannot close a failed complete-scope or receipt-to-paint
budget.

The first full browser recorder exceeded its process guard because it repeatedly
transferred the entire growing paint history into Node. That interrupted campaign
is retained as `resource-failed-campaign.json`, including all30 material matches,
its resource failures and four terminal ticket attempts. It is not a valid
within-cap qualification campaign. The recorder now selects the exact matching
binding inside Chromium, caps its test ring at64 entries/2MiB with explicit drop
counts, uses a256MiB Node heap, avoids full trace reads per ticket and throws
immediately on a process-cap violation. A fresh campaign records the corrected
within-cap measurements independently.

## Historical original SC06 result and then-open gates

The historical original campaign binds application
`51c8a2cb7aa8aa84cfc0c65b1f527a0fe20284b471f6da2ecf025a09b13b0a45`
and engine
`70e327fcba97ba20604782fcd6a15e1cd8e5d38d50edb77b2eb4748b356e9538`.
It used Chromium156.0.8078.4 on an Apple M3 Pro,11 logical CPUs,18GiB memory,
macOS/Darwin27 arm64. PostgreSQL16.15 used a verified separate socket-only
cluster. Source/assets/policy/runtime identities are inside the raw report.

All30 material updates matched their exact source originals, SQL post-commit
revision, pair calculation, publication and visible DOM dependency/economic
revisions. Nearest-rank results are:

| Measurement | Samples | p50 | p95 | Maximum | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Authored receipt to matching visible second-frame row |30|7,421.8ms|8,299.0ms|13,437.8ms|Fails2s/3s budgets |
| Accepted publication to second-frame application |30|11.0ms|26.1ms|30.5ms|Passes250ms p95 |
| Local filtering with required page data present |31|25.4ms|32.4ms|34.4ms|Passes100ms p95 |
| Selected request to terminal unavailable second-frame result |30|2,065.3ms|2,100.5ms|2,113.5ms|Failure evidence;0 usable tickets |

There is no selected-ready-ticket p95: zero of30 attempts produced usable
authority. Deadline responses omit expanded backend durations, so those missing
stage durations remain unknown; browser terminal observations and failed SQL
capture traces remain retained. They are not counted as usable-ticket samples.

Cold first usable output painted at7,690.3ms. The500-event scope never reached
complete coverage before original native clocks expired. The initial phase completed358 pair evaluations; pairs that expired while waiting were not counted as evaluated or painted. The cached partial
reload painted at56.4ms; it does not qualify the warm/ready complete-scope target.
The final observed category rows were167 conditional hedges and one covered arb,
with explicit partial coverage. Missing native coverage is not a checked zero.

Material-change stage p95 was7,117.5ms for detached readiness capture,26.1ms for
the actual pair financial evaluation,428.6ms for the capture-complete-to-finance
queue upper bound and6.63ms for publication. The largest retained midpoint clock
uncertainty was0.55ms. All30 exact causal proofs pass; all observations remain in
`timing.json`, with compact distributions and joins in `analysis.json`.

Observed process peaks were599,277,568 bytes for Python and357,842,944 bytes for
Node. Chromium subprocess RSS witnesses are retained individually. The test SQL
database reached17,341,463 bytes and observed free disk stayed above70GB. No
resource guard failed in the corrected campaign. Provider and external browser
request counts were both zero. The390px disclosure capture has no horizontal
overflow. The earlier recorder-cap failure remains separate and unqualified.

The separate burst phase submitted10 updates. Eight were superseded before
capture and two were captured/coalesced; the latest did not produce an exact
paint within its18-second bounded wait. Five unrelated-event submissions and
their captured/coalesced dispositions are retained. Their scope settled, but
selected-target continuity remains unknown because the burst never established
a painted current baseline. Missing before/after values cannot prove equality.
This phase failed its burst gate. `burst-unrelated.json` contains the complete
observations and screenshots.

A separate500-event profile identifies the remaining capture work. Its14.52s
profiled duration includes profiler overhead and is not a timing qualification.
Within that profile, production `ReadContext.bundles` accounted for6.34s,
`catalog_from_normalized` was called1,000 times (500 catalog passes and500 build
passes), `combined_inputs.build`500 times, `source_inputs.produce`1,000 times and
model checks1,000 times. Authored profile attachment accounted for2.03s, so the
test-specific setup cost is disclosed separately. Repeated deep copying,
profile validation and occurrence matching are visible in `capture-profile.json`.

Initial causal traces also show43 inter-turn gaps between275ms and357ms,
totaling13.41s, excluding the separate readiness recapture gap. The unconditional
250ms wait in `Scanner.run` contributes at least10.75s of these observed gaps.
At500 pairs it can add about15.5s across62 turns before financial work and
capture costs. This is a scheduling diagnosis, not a claim that removing the
wait alone would satisfy every target.

The remaining SC06 repairs are bounded, source-bound readiness reuse for
unchanged occurrences (including exact temporal/source/model authority), useful
progress scheduling while the initial financial queue is nonempty, and selected
SQL revalidation of the exact pair rather than reconstruction of the complete
500-event universe under its2s ticket deadline. Preserve current dependency,
coverage, source-age/skew, legal-grid, depth, funding, settlement and Stop checks.
Repeat affected arithmetic, causal and actual-browser campaigns after repairs;
none of these open gates is closed by the fast client paint/filter results.

The disposable PostgreSQL cluster was stopped and removed after all evidence was
retained. `postgres-cleanup.json` records the verified directory, version and
116,147,092 observed physical cluster bytes at cleanup. No ordinary owner cluster
was accessed. SC06 responsiveness remains open; source/customer qualification,
hosted CI and owner acceptance retain their separate gates.


## Main repair campaign history

The original evidence above remains under `test-results/sc06/`. Main repair
observations are separate under `test-results/sc06-repair/`; none overwrites a
prior campaign. Intermediate diagnostics qualify only their exact recorded
inputs. Early repair diagnostics used inconsistent authored native transformation
metadata and remain unqualified. The corrected fixture independently checks every
original before admission and after SQL decode: identity transformation requires
`native_value == value` and `native_units == units`. Independent tests checked all
1,000 constructed and SQL-decoded positions, retained depth, and the 500/501 scope
boundary before the corrected campaigns.

Cold startup is a separate observation. A quiet cold partial/expiry result cannot
qualify a warm complete scope, and it does not impose an extra requirement to
finish all cold financial work before a 30-second source expires. A finite genuine
price/depth feed may establish a new current complete 500-event baseline through
real finance. Required warm reload and all controlled measurements start from
that actual complete baseline; every original clock and expiry check remains
active.

The declared maintained-scope feed changes both legs' actual prices and first
depth levels. It initially admits native/mixed batches of 84, 84, 84 and 81 events
at minimum six-second spacing, then at most 84 events per minimum six-second
interval (nominal maximum 14 events/second). All 333 native-containing events
participate until the first controlled target update commits; that target then
transfers to the explicitly measured updates. The actual cadence, quiet pauses,
late duties, source revisions, calculation/publication/visible or unobserved
paint dispositions and admission waits are retained. The finite feed lasts at
most 480 seconds. Controlled latency claims concern 30 operations admitted in
complete500 quiet gaps amid this feed. Background batch publication latency is
reported separately; no universal 2/3-second background paint claim is made.

Each failed attempt retains `timing.json`, raw SQL causal JSONL, original visible
paint JSONL and a verified archive of its exact seven test helper sources:

- `performance/` retained a failed corrected-original cold observation and no
  controlled samples. Its quiet cold all500 prerequisite was subsequently removed
  as an extra test requirement; no production clock was changed.
- `performance-02/` admitted the initial333 native-containing events together,
  then overlapped steady work before that backlog settled. It did not establish
  a required warm baseline and recorded zero controlled/ticket attempts.
- `performance-03/` staggered the initial feed but excluded the controlled target
  before its first timed source update. That original expired while waiting.
- `performance-04/` kept all333 events active. Exact offline source joins found
  seven current500 publications, with128–790ms before the next SQL commit. An
  extra1200ms reservation ahead of the next test feed duty excluded every valid
  admission window. The next attempt used immediate exact-current admission and
  explicit quiet backpressure, preserving actual latency/expiry requirements.
- `performance-05/` demonstrated a complete quiet cold visible frame at28,353.8ms
  after navigation and a complete500 warm reload at59.2ms. Its four exact material
  matches took2,130.5,2,127.1,2,050.5 and2,068.3ms; the fourth after-scope was
  incomplete, and a fifth admission found no complete500 window within30s. It
  stopped with no usable-ticket campaign and does not qualify responsiveness.
  Actual changed-event capture was568–634ms and capture-complete to financial
  start492–642ms; real pair finance took43–59ms. Separate profiles identified
  duplicate encoding/copying and preparation decoding, while the browser showed
  additional scheduled polling delay. These are measured repair targets, not
  justification to relax budgets.
- `performance-06/` retained19 exact material matches, all with current500
  after-scopes, at1,581.7ms p50 and1,727.2ms maximum. It stopped before tickets
  because the recorder's2,048-request ring could discard earlier selected-frame
  proof. This is an evidence-recorder failure, not a partial qualification.
  The next recorder revision streams every product HTTP outcome, excludes test
  polling before decode, and reconstructs frame proofs from a coherent durable
  checkpoint. A regression recovered30 early/interleaved ticket proofs among
  3,330 physical JSONL records and rejected a mismatched durable count.
- `performance-07/` used that audited durable recorder. Its26 exact material
  matches retained complete500 after-scopes at1,577.2ms p50,1,632.1ms p95 and
  1,639.9ms maximum. The27th admission found no current500 window within30s;
  no selected-ticket samples were collected, and the campaign is unqualified.
  Stable84-event batches took5,306.7ms median and5,637.9ms p95 from SQL commit
  to their last financial calculation. Actual receipt intervals were7,247.1ms
  median and7,500.6ms p95 because controlled quiet work delayed feed duties.
  By batch30, the oldest native original was29.948s old at receipt, and the
  admission took1.157s, crossing the actual30s expiry before the new SQL facts
  were visible. Later admissions took1.072,2.184 and3.295s as expiry recaptures
  compounded. The original coarse admission trace cannot attribute those spikes
  to SQL, Python scheduling or input normalization. Subsequent diagnostics add
  monotonic admission-phase stamps without changing packets or transactions.

The next bounded repair removes redundant per-capture traversal/hashing and
memoizes display rows only within one owned capture and exact immutable financial
record. It retains receipt/expiry validation at every publication, count/byte
bounds, and immediate decharge when a financial record is replaced. Diagnostic09
on application`a9a37cc0…` / engine`b15a1fe8…` reached quiet cold complete500 in
26,965.8ms after navigation (28,393.0ms from initial typed receipt), with1,328.9ms
expiry headroom after clock uncertainty. Actual complete500 warm reload took
76.4ms. A new steady84-event batch—not the last initial81—retained84 exact
financial proofs and complete500 coverage5,413.2ms after commit. Capture took
1,108.4ms and materialization443.5ms, compared with the prior campaign's
1,332.5ms and600.7ms p95 stage sums. Actual finance remained3,114.9ms; last
financial completion was5,320.0ms after commit. The new admission took136.6ms:
80.0ms offer upsert,43.1ms native-book replacement,5.1ms decoded consistency
checks and5.8ms commit return. This one-batch diagnostic demonstrates stage
savings and remains explicitly unqualified; sustained currentness and all30
material/30 usable-ticket gates still require the full actual-browser campaign.

Diagnostic10 then retained six combined actual material/selected-ticket cycles,
with exact durable backend-frame and fresh two-leg SQL proofs. All18 before-
material, before-click and after-ready scopes were current500. Material latency
was1,580.3ms maximum; selected-ready second-frame latency was514.3ms maximum.
The minimum after-ready native expiry headroom was1,167.6ms, and minimum native
renewal headroom at actual SQL commit947.4ms. This bounded diagnostic remained
unqualified and was followed by the full `performance-08/` attempt.

That full attempt retained18 exact material matches with current500 after-scopes
(1,550.4ms median,2,614.7ms maximum) but could not admit the19th within30s of
waiting for a current500 window. It collected no tickets and did not qualify.
Its raw report, all2,013 background event revisions and exact executed helpers
remain separate. Background dispositions include146 exact visible observations,
1,628 published without an observed visible paint, one calculated without an
observed publication and238 superseded/unobserved financial results. These are
not counted as controlled paint samples. Native originals crossed expiry during
the23rd feed transaction: oldest age29.163s at receipt became32.756s at commit.
The24th was already32.045s old at receipt and reached40.015s at commit. The23rd
admission spent2,337.5ms in offer updates and1,122.8ms in native-book replacement;
the24th spent7,135.9ms and694.8ms. Its closed raw file has no final coherent
checkpoint, so no final zero-loss assertion is inferred from missing counters.

A separate opt-in SQL observer retains bounded wall/thread/process CPU aggregates
and exact-backend wait samples without query text or parameters. Diagnostic11
omitted the product read that starts finance and is explicitly invalid for
attribution. Corrected11b started actual finance in the500-event universe, observed
29 financial calculations and falling pending work, but did not establish a
complete500 baseline. Its one near-expiry84-event admission took1,626.1ms;
1,690 execute calls totaled1,371.0ms wall time,371.6ms ingress-thread CPU and
1,078.3ms whole-process CPU. Of24 database wait observations,22 were `ClientRead`,
one active without a wait and one idle without a wait. No lock or I/O wait was
observed. No financial evaluation interval overlapped that admission; process
contention may have come from capture/expiry reconciliation or other threads.
This supports investigating client scheduling across synchronous roundtrips. It
does not establish a server lock, index bottleneck or sustained warm-workload
equivalence. The sampler shares the client process and its own scheduling delays
are retained.

The bounded ordered-write pipeline preserves existing SQL/fetch barriers and
transactions, synchronizes at most128 issued writes and before return, and keeps
late-error rollback/publication behavior. Focused actual SQL cases passed. On
application`b33ddef1…` / engine`cc6be71e…`, the same diagnostic12 total admission
fell to699.4ms from1,626.1ms. Offer/native-book phase walls fell to390.6/252.3ms
from652.7/890.2ms. Execute count remained1,690; explicit pipeline synchronization
is outside per-execute timing, so whole admission/phase walls are the comparison.
Its actual cold backlog remained partial, with31 finance traces overall and none
overlapping that admission. This observation is not a complete500 qualification.

Diagnostic13 reused the same six-cycle actual-browser driver after that repair.
Genuine feed established actual complete500 warm reload in71.9ms after the quiet
cold observation expired. Four material/usable-ticket pairs retained exact SQL,
financial and frame proofs, with material maximum1,692.7ms and selected-ready
maximum551.0ms. It stopped at the fourth after-scope: headroom before material
was1,772.4ms, after material147.0ms and after ticket−262.5ms. Eighty other native
originals had expired, leaving420 current pairs. The target's fast usable ticket
does not qualify that failed500-event scope. Three steady84-event transactions
still needed5,166–5,302ms from commit to last finance, including3,056–3,122ms of
actual financial evaluation and1,160–1,240ms readiness capture. Their actual
receipt intervals were7,504–7,703ms under quiet backpressure. All observations,
background dispositions and coherent durable-prefix proofs remain in
`diagnostic-13/`; at that point no full `performance-09/` campaign had started. Sustained500
currentness and the complete30/30 responsiveness campaign remain open.

The next repair shares frozen preparation facts only on the private owned capture
path and reuses dependency proofs only with the same immutable instrument/input
owners and exact policy/engine/evaluator proof. Public paths remain defensive;
fresh SQL/global membership and temporal/expiry checks remain authoritative.
Diagnostic14 on application`dc37435d…` / engine`37006fec…` reused the unchanged
six-cycle driver. It retained six exact selected-frame/fresh-SQL proofs and all18
current500 scopes, with material maximum1,323.8ms, selected-ready maximum529.8ms
and actual complete500 warm reload57.9ms. After-ready expiry headroom stayed
2,520.9–3,622.5ms. Five steady84-event batches retained84/84 financial proofs;
actual receipt intervals were6,685–7,246ms, and the oldest native original was
26.544–27.637s old at SQL commit. Real financial work stayed2,922–3,119ms per
batch; this repair did not change the financial algorithm, legal grid, source
clocks or feed rate. Its bounded diagnostic remained unqualified. Subsequent
broad QA passed224 Python tests/113 subtests,140 actual SQL tests/14 subtests,
nine client suites, static/generator checks and the858-file application package.

Full `performance-09/` then retained30/30 exact material causal proofs and current
500 after-scopes:1,039.6ms median,1,374.1ms p95 and1,416.0ms maximum. Twenty
selected attempts retained exact durable selected frames and fresh two-leg SQL
proofs, with397.5ms median,612.2ms p95 and1,229.0ms maximum. These20 are partial
observations, not the required30-ticket qualification. Ticket20 began with only
67.3ms of unrelated native-original headroom and ended1,231.9ms past that expiry;
the after-scope correctly withdrew80 pairs. The21st admission found no current500
window within30s, so the run stopped without the burst/churn phase. The failed
raw report, prelaunch seven-helper archive and independent failure audit remain
retained; no final coherent-prefix or final zero-loss claim is inferred.

All4,869 background event revisions have explicit dispositions:352 exact visible
observations,4,427 published without an observed visible paint and90 superseded
or without a matching financial result. Background receipt-to-publication p95 was
5,540.5ms and maximum9,485.5ms;3,343 publications exceeded3s. These publication
observations are separate from the controlled paint distribution. The selected
target remained current; the failure is sustained global renewal margin. Timing
inside offer/native update methods, calculation/capture, feed backpressure and
unknown checkpoint-write duration remain distinct rather than assigning every
delay to one component.

A bounded real financial-owner profile retained native/stake/mixed actual SQL
input/output packs. Search counts stayed100/144/192, with an unchanged maximum256;
advancing-clock baseline and profiled outputs were identical. Unprofiled times
were26.7/49.4/46.1ms, while profiling inflated wall time about2.97–3.17 times.
Classification accounted for roughly11–12% of profiled cumulative evaluation;
exact metric presentation about4–5%, and provisional allocation deep copies less
than0.2%. Economics dominated38–63%. Those nested cumulative figures overlap and
cannot be added. The resulting presentation repair defers final formatting and
skips unused economic display fields while retaining exact gain/fee/pool/state
algebra, profit wire strings and score rounding. Independent old/new oracles for
both the captured requested-trade policy and Scanner's ceiling normalization
passed528 evaluation cases per context, including rare precision/refusal cases.
No new responsiveness qualification follows from that equivalence evidence.

On application`d07c88ac…` / engine`ad7dbeb1…`, the exclusive paired offline replay
in `finance-profile-03/` alternated original and candidate owners ten times per
retained native/stake/mixed pack. Median times fell24.213→18.898ms (21.95%),
43.734→35.203ms (19.51%) and45.546→36.099ms (20.74%). All60 outputs matched the
retained expected output; input hashes stayed unchanged and no network attempt
occurred. The original financial owner was explicitly bound to the original
economic owner. The replay uses each pack's fixed-at requested-trade policy;
it is not a live500 timing claim. Profiling inflated times3.16–3.50 times, so
the gain uses unprofiled medians. The earlier `finance-profile-02/` is retained
with possible ordinary-restart/warmup overlap and is not the primary gain
measurement.

Diagnostic15 then retained24 exact material/usable-ticket cycles and all72
current500 scopes before material, before selected click and after ready. Quiet
cold completed in23,531ms from navigation or24,482.9ms from the typed local
receipt; genuine feed established the warm baseline and reload completed in
60.8ms. Controlled material p95/max was1,377.5/1,410.3ms, selected-ready p95/max
480.7/497.0ms. The smallest after-ready expiry headroom across all24 cycles was
3,855.9ms. This is a bounded diagnostic, not the required full30/30 qualification.

Its23 steady84-event batches each retained84 exact financial results. Commit to
last finance p95/max was4,568.4/4,781.1ms, with actual finance p95/max
2,532.8/2,664.6ms. Actual receipt intervals were6,118.2–6,949.5ms under declared
quiet backpressure; the oldest native original at commit never exceeded26.585s.
The169.418s genuine feed retained all2,265 event dispositions:162 exact visible
observations and2,103 publications without an observed visible paint. Background
publication p95/max was4,541.5/5,699.6ms, including1,406 over3s; those outcomes
remain separate from the controlled quiet-gap paint distribution. Python peak
was480.0MB, below the768MiB process guard, with zero provider attempts. The
coherent4,833-entry durable prefix verified exact count/bytes/hash and no durable
recorder loss. This diagnostic driver does not persist the final visible-writer
drop counter, so it makes no overall visible-stream zero-loss claim. Broad QA and
the full30/30 plus independent burst/churn run were still unpassed at that
diagnostic boundary. Formal qualification is now deferred and nonblocking under
the owner's subsequent direction above.

The test recorder keeps bounded in-memory rings with explicit eviction counters.
Every SQL causal entry is also streamed outside projection locks through a
64-entry/4MiB queue into a physically capped64MiB JSONL file, with1GiB free-space
guard. Exact entry counts and SHA256 prefix checkpoints prove durable retention;
any durable loss/error prevents qualification. Original second-frame witnesses
require visible DOM identity and `current` authority. Five midpoint clock probes
anchor the same browser origin to advancing replay UTC; all500 expiries must lie
after the original observation plus half-RTT and1ms parse uncertainty. A later
query cannot redefine the first painted frame.
