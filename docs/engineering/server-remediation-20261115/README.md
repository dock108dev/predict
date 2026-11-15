# Predict server remediation

November 15, 2026 · Working copy: `main` · Baseline: `d24710c`

The collector, web and PostgreSQL were healthy on Hetzner at the baseline. Both application
images independently reported `d24710c`. The server owns dispatch; the Mac has the remote
ownership marker and its separate web process must not resume acquisition. PostgreSQL 16.16
was serving `prediction_arb`. At 2:03 a.m. Eastern, dispatch was active with no global Stop or
source pauses. The live head was generation 73,230, result
`95b90f349239425fa23c5119a196a21d`, with 141 of 375 components and finance partial.
This head does not date the live SQL overlay. Two native roster snapshots still showed 256
active instruments per source and 10,228 Kalshi / 7,233 Polymarket US deferred. Over the
preceding 45 minutes only 4 of 38 NFL SportsGameOdds delivery receipts had a recorded seal
while 6 of 14 NCAAB and 10 of 17 NCAAF receipts had one. A receipt can contain multiple
outcomes; these are delivery diagnostics and not market coverage denominators.

| Order / owner | Implementation and dependencies | Engineer verification |
| --- | --- | --- |
| 1a · Collector and ordinary publisher | Profile the real publisher plan before tuning. Give already admitted prices priority, keep exact dependencies, improve bounded native priority and map evidenced OddsLink team aliases. Live OddsLink still needs an independent exact in-play witness. Keep collector ownership, controls, quotas and both accounting ledgers. | Trace source clock, receipt, admission, exact contract, capture, seal and rendered quote. Observe the ordinary scheduled feeds, separating no upstream quote, unapplied receipt and stale quote. |
| 1b · Lifecycle and dashboard | Use one occurrence/phase eligibility test before search, ordering and paging. Treat kickoff as a firm Pregame boundary; Live also requires a current projected quote. Keep prior captures in history. Coordinate with the native overlay and browse return locator. | Disposable kickoff/final/delayed/reschedule, Stop, stale input and direct-link cases; use an eligible real transition if the schedule supplies one. |
| 2–4 · Fee, reference and replay | Keep exact venue quotes visible across calculation choices. Use one applicable fee proof, including the recorded scoped zero in saved replay; preserve original evidence internally. Remove Pinnacle from public calculations/displays, retain explicit indicative scenarios, and withhold qualified EV where reference, costs or settlement proof is missing. | Check frozen/preview/practice and exact current quote details. Owner's 99% confidence rule governs headline EV; no uncalibrated number substitutes for proof. |
| 5 · Pair publication and desk | Explain candidate-specific missing evidence. Reconcile exact prices, sizing, fees, funding and joint state cashflows. Separate completed-game models from an executable full arb. | Disposable gain, break-even, loss and unavailable cases; expired leg, fee rounding and unresolved state. Reconcile an eligible server pair if observed. |
| 6 · Phone comparison | Preserve route, exact row, scroll, focus, basis and nested pair state in current and replay flows. Reattach eligible rows after cursor expiry. | Phone-sized real browser current/saved/practice journeys, valid and expired page tokens, removed rows and browser Back. |
| 7 · Integration and rollout | Run affected offline, disposable database and browser checks. Restart local web only under remote ownership. Follow the GitHub manual deployment workflow and existing environment restrictions. Record local, GitHub, deployed revision and production behavior separately. | Verify installed revision, controls and accounting continuity, then compare fresh exact scheduled source evidence with API and rendered list. |

The production observation stops once the representative scheduled dispatches or receipts
have a traced disposition and available fresh quotes are seen in the installed interface.
The runbook's example 240-sample census is a diagnostic option. A positive arb, a fee-covered
quote, or late-night Live traffic is not required to prove deterministic product behavior.
If a scheduled source supplies no qualifying occurrence or quote, record that limitation
and the missing evidence rather than running indefinitely. The owner’s aggregate ceilings
remain 300 credits per 15-minute cycle and 16,800 per operating day, subject to the recorded
provider and account guards. No new pricing-age or duration gate is introduced.

## Baseline traces and implementation decisions

| Source | What the running deployment showed | Change |
| --- | --- | --- |
| Kalshi | At 2:18:19 a.m. there were 45 committed receipts in the previous 30 seconds, despite deferral and a backed-up raw/derived path. The audit had already traced an individual admitted Kalshi spread that expired before its ordinary capture. The earlier browser sample did not establish a fresh Kalshi render. | Keep verified in-play and exact main markets in the fixed share of the same bounded roster; maintain rotation and the original authority clocks. Read fresh committed native offers directly in both phases. |
| Polymarket US | A Detroit winner quote at +135.29 had source/confirmation 2:12:21.856 and receipt 2:12:22.831. The browser matched its exact offer at 2:12:36.737 while generation 73,244 was sealed at 2:11:54.775. Later, the socket stopped after a rotation acknowledgment timeout at 2:14; the worker remained up with no newer receipt at 2:18. | Preserve the ordered retirement and bounded reconnect. Make receiver shutdown signal a waiting reconstruction prefetch, cancel a waiting prefetch on Stop, and report which cleanup stage owns the connection. |
| SportsGameOdds (Novig and ProphetX) | For one NFL receipt, the browser matched Detroit's Novig +104 and ProphetX +105. Original source times were 2:09:46.246 and 2:10:00.069. Common receipt 2:10:24.862 → admission 2:10:30.596 → capture 2:11:45.500 → first seal 2:11:51.863 → browser 2:12:36.737. The late step was downstream of admission. The round had zero raw backlog. | Read the exact admitted Novig and ProphetX quote revisions before the ordinary head is ready; bind matching finance only when it exists. In ordinary publication, prioritize changed prices before finance-only retries and record planning stages. |
| OddsLink (ProphetX) | The polling worker reported three fixtures each in five leagues and zero MLB. The audit's failed live NCAAF captures had unresolved source team names and lacked exact independent in-play matches; a third fixture lacked a ProphetX quote. | Map the four observed school names from official team sources. Keep the same start, home/away, independent in-play and original quote clocks as conditions of admission. |
| Legacy Odds API / direct Novig | Inactive under the existing server configuration. The audit documented legacy unresolved charges. | Keep inactive, leave ledgers and provider settings in place. |

A read-only profile of the old publisher took 2.60 s in occurrence batching, 4.11 s in dependency
fingerprints and 1.36 s in receipt watermarks under concurrent load. These timings identify costs
within a single sample; the audit recorded longer total turns. The scheduling changes do not
extend any source age or increase any subscription, account or dispatch allowance.

The baseline commit also failed the hosted offline job: a Stop acknowledgement unit test opened
the developer PostgreSQL socket in clean CI. The fixture now supplies its own database connection
stub and checks that the command poller releases it after the failed acknowledgement. The production
Stop code and the release workflow are unchanged.

A later pre-release 390 px watch matched one current Pregame offer from each of the four
venues directly from the response to the rendered button. No current Live offers were available
in that watch. The disposable Live paths separately exercised exact newly admitted revisions
before the first publication, including source pause, source-clock expiry and an independent
final state withdrawing OddsLink prices.

On the first remediated deployment (`9e46881`), the NCAAB Novig spread at −113
matched the stored SportsGameOdds quote. The original was 2:43:14.059 a.m.;
receipt was 2:43:42.629 and admission was 2:43:44.702. The 390 px Browse read
rendered it at 2:43:50.910 on head 73,312. The receipt's first ordinary seal was
2:44:39.797, about 49 seconds after the browser read. The same probe traced a
ProphetX NFL spread at −111 from the OddsLink board through its own source and
receipt clocks, without attributing either price to the shared head's seal.
The production Live tab was empty at the time of the probe.
