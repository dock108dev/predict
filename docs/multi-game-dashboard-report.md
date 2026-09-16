# Multi-game quick-look dashboard

Completed September 15, 2026 EDT (September 16 UTC). **[Open the saved dashboard](http://127.0.0.1:8783/).** The existing opportunity board now opens on a multi-game table, with its game board and EV explorer as drilldown. The beta instance is idle; feeds are stopped.

## Coverage and real results

The single authorized scan ran **117.254 seconds**, from 2026-09-16T01:05:46.374209+00:00 to 2026-09-16T01:07:43.627849+00:00, ending by manual Stop. Both exhaustive bounded catalogs contained **32 NFL games**, with **32 exact participant/schedule overlaps**. The earliest **six distinct games** were selected; **26 were omitted by the six-game limit**, with no mapping/phase exclusions and no silent substitutions. Native side orientation is recorded in [selection.json](../evidence/multi-game/sessions/5c9b7dca-a813-4d77-80f5-0691d06068eb/selection.json).

| Included game | Kickoff (EDT) | Cross-venue net at 100 contracts | ROI | Usable at displayed cutoff? |
|---|---|---:|---:|---|
| DET Lions vs BUF Bills | Sep 17, 08:15 PM | $-3.86 | -3.72% | Yes, historical |
| CAR Panthers vs ATL Falcons | Sep 20, 01:00 PM | $-3.70 | -3.57% | Yes, historical |
| NO Saints vs BAL Ravens | Sep 20, 01:00 PM | $-2.68 | -2.61% | No: cross-leg receipts >5 seconds apart |
| MIN Vikings vs CHI Bears | Sep 20, 01:00 PM | $-2.84 | -2.76% | Yes, historical |
| CIN Bengals vs HOU Texans | Sep 20, 01:00 PM | $-4.16 | -3.99% | No: cross-leg receipts >5 seconds apart |
| CLE Browns vs TB Buccaneers | Sep 20, 01:00 PM | $-2.87 | -2.79% | No: cross-leg receipts >5 seconds apart |

**18 Arb candidates:** 12 conditional normal-winner net calculations (six cross-venue and six same-market comparisons), six unavailable alternatives requiring an unsupported US Short purchase ask. Nine candidates are usable at their displayed historical cutoffs; three conditional cross-venue calculations have excessive receipt skew. **Zero positive normal-settlement candidates and zero qualified all-outcome arbitrage results.** Best usable cross-venue result: Chicago YES $0.68 + Minnesota US Long $0.32, modeled net **−$2.84 / −2.76%**, 100 contracts each, $102.84 entry cash. Raw gaps never enter net rankings. Alternatives share liquidity and are never summed.

The 24 EV rows initially need assumptions. The browser walkthrough saved exactly one explicitly labeled what-if: **Minnesota US Long, p=40%, normal winner settlement only**, yielding **$6.69 / 20.08% expected return** and **33.31% break-even** at 100 contracts. This is an illustrative entered assumption, not an independent forecast or detected positive edge. Its basis is visible, scoped to that game/outcome and retained in this browser. Other rows receive no invented probability. Unknown-fee mode leaves net EV and break-even unavailable.

**Games outside the six-game limit:** GB Packers vs NY Jets (2026-09-20T17:00:00+00:00); PIT Steelers vs NE Patriots (2026-09-20T17:00:00+00:00); PHI Eagles vs TEN Titans (2026-09-20T17:00:00+00:00); JAC Jaguars vs DEN Broncos (2026-09-20T20:05:00+00:00); LV Raiders vs LA Chargers (2026-09-20T20:05:00+00:00); SEA Seahawks vs ARI Cardinals (2026-09-20T20:25:00+00:00); WAS Commanders vs DAL Cowboys (2026-09-20T20:25:00+00:00); MIA Dolphins vs SF 49ers (2026-09-20T20:25:00+00:00); IND Colts vs KC Chiefs (2026-09-21T00:20:00+00:00); NY Giants vs LA Rams (2026-09-22T00:15:00+00:00); Atlanta vs Green Bay (2026-09-25T00:15:00+00:00); Los Angeles C vs Buffalo (2026-09-27T17:00:00+00:00); Carolina vs Cleveland (2026-09-27T17:00:00+00:00); Cincinnati vs Pittsburgh (2026-09-27T17:00:00+00:00); New York J vs Detroit (2026-09-27T17:00:00+00:00); Houston vs Indianapolis (2026-09-27T17:00:00+00:00); New England vs Jacksonville (2026-09-27T17:00:00+00:00); Kansas City vs Miami (2026-09-27T17:00:00+00:00); Tennessee vs New York G (2026-09-27T17:00:00+00:00); Seattle vs Washington (2026-09-27T17:00:00+00:00); Arizona vs San Francisco (2026-09-27T20:05:00+00:00); Minnesota vs Tampa Bay (2026-09-27T20:05:00+00:00); Baltimore vs Dallas (2026-09-27T20:25:00+00:00); Las Vegas vs New Orleans (2026-09-27T20:25:00+00:00); Los Angeles R vs Denver (2026-09-28T00:20:00+00:00); Philadelphia vs Chicago (2026-09-29T00:15:00+00:00).

## Capture and checks

Session `5c9b7dca-a813-4d77-80f5-0691d06068eb`. **561/561 accepted records persisted**, no rejected or unresolved ingress records. **232 raw stream frames**, **231 native book images** replayed exactly (78 Kalshi / 153 US), plus **six verified derived health states**; **237 total book states / 474 quote packets**. Native replay recorded no rejected frames. Both sources completed two metadata validations per selected game. [Results and counts](../evidence/multi-game/results.json) · [Independent native and health-state replay](../evidence/multi-game/independent-replay.json).

Actual usage: **32 REST requests** (18 Kalshi / 14 US), **two total socket connections** (one per venue, six markets multiplexed on each), **2,046,160 conservatively charged body bytes**, **$0 additional spending**, no sportsbook requests. Limits were 175 seconds of collection within the authorized 180-second total, 128 aggregate REST requests, four connection attempts / two concurrent sockets, 1,200 messages, 32 MiB source body bytes, 1 MiB response/frame, and the existing finite E6 ingress/queue/journal caps. Selected games were more than five minutes from kickoff. [Pre-dispatch official limits and access basis](../evidence/multi-game/access-and-limits.md). The original single-run marker and evidence were not changed. This new allowance is now consumed; no further scan is enabled.

Focused checks: 55 initial test executions passed across board, collection and native transport tests; 28 final tests passed after integration, including saved-catalog grouping, ambiguous duplicate rejection, schedule mismatch, native orientation, cross-event isolation, Decimal fee/depth arithmetic, capped size, positive/negative/unknown ranking, EV separation, idle startup and consumed-run guard. JavaScript syntax passed. Original and new native captures reopen without network or credential use.

Actual browser walkthrough: Start → six-game live list → dollar sorting / positive filter → Minnesota candidate → enter 40% EV and explicit basis → return → Stop → saved results → repaired venue-pair filter / ROI sort → saved EV reopening. Selected candidate, quantity, fees and list filters survive the round-trip. Browser refresh and server restart remain idle with Start disabled. Both dashboard and drilldown fit **390×844** with document width **390px**. The walkthrough found and corrected malformed venue options, assumption-save behavior and an inherited minimum table width; fixes needed no additional live run. One browser polling error during the intentional beta-process restart was observed; the final UI handles that temporary unavailability.

Preservation check: all 801 preexisting files in the scoped snapshot remain present; only nine intended app/launcher files changed, and all prior captured evidence is byte-identical. [Preservation record](../evidence/multi-game/preservation.json).

## Use and limits

Launch or inspect only this beta instance:

```sh
/Users/michaelfuscoletti/Desktop/prediction-arb/scripts/opportunity-board start --port 8783
/Users/michaelfuscoletti/Desktop/prediction-arb/scripts/opportunity-board status
/Users/michaelfuscoletti/Desktop/prediction-arb/scripts/opportunity-board stop
```

Application startup is idle. The browser Start/Stop controls own collection; Start is now disabled by the durable one-attempt marker. Stop requests joined feed shutdown and saved finalization. Do not remove the marker to run again. The prior POC instance uses `--instance poc`; it and other owner services were not restarted.

The comparison uses one requested whole-contract quantity; each row shows its actual depth-capped size. Default is descending supported ROI within calculation class, with net-dollar sorting and positive, venue/pair, freshness and game filters. Live values update in held row order; Refresh list explicitly re-ranks. Drilldown freezes a retained cutoff and return preserves the list settings. After Stop, each game defaults to its latest simultaneously receipt-fresh, synchronized cutoff; individual row receipt skew can still make a cross-venue result unavailable. All saved results remain historical, never executable now.

Settlement/fee limitations remain explicit: normal winner payouts only for numeric net scenarios; unequal postponement rules and exceptional discretionary outcomes prevent complete all-outcome qualification. What-if fees assume Kalshi multiplier 1/no event override and selected account precision, US retained 0.06 schedule/no settlement levy, and one taker fill per consumed level. Fractional US fills can leave fees/net unsupported. No independent fair-value model, real fill guarantee or continuous reliability is claimed. The selected markets and bounded metadata refreshes do not cover every possible opportunity. Per-game assumptions are local to this browser, not shared across devices.

**Next step:** use this saved six-game ranking to identify the single most useful sorting, filtering or detail change for the next personal-beta iteration. No further live run, trading, account mutation, database/service change, commit, push or publishing is part of this slice.
