# One-game page-derived EV integration

Completed September 16, 2026 UTC. [Open Detroit–Buffalo saved details](http://127.0.0.1:8783/game?session=5c9b7dca-a813-4d77-80f5-0691d06068eb%7EKXNFLGAME-26SEP17DETBUF__101466&hash=5c9b7dca-a813-4d77-80f5-0691d06068eb&cutoff=22e4cd98-7081-4a27-bd89-00c60e35b313&quantity=10&scenario=cent&probability=&basis=&contract=kalshi%3Ayes&view=arb&candidate=cross-yes). Board left open and idle; manual probability/basis blank.

**Conditional ordinary-winner EV is supported.** The [separate dated assessment](../evidence/page-ev-integration/ordinary-winner-assessment.json) binds the exact saved page, bookmaker, event, Buffalo YES contract, book and retained rules. Both refer to the ordinary completed-game winner, including overtime. This narrow semantic conclusion does not establish full settlement equivalence, a historical sportsbook ticket's jurisdictional terms, current fair value or fee applicability.

[DraftKings football rules](https://sportsbook.draftkings.com/help/sport-rules/football?sf260608803=1) explicitly include overtime. [General settlement rules](https://sportsbook.draftkings.com/help/general-betting-rules/general-rules?intendedSiteExp=US-SB) cover two-way moneylines and tie pushes. Official text was available through web search; direct HTML returned an application shell, recorded honestly in the assessment. [Kalshi NFLGAME terms](https://kalshi-public-docs.s3.amazonaws.com/contract_terms/NFLGAME.pdf), retained separately, clarify overtime; the exact saved market names Buffalo winning this game. Current rules were assessed at 2026-09-16T04:07:47.473289+00:00; neither original observation nor the earlier unassessed comparison was rewritten.

Tie treatment differs: sportsbook stake return versus Kalshi $0.50 per contract. Cancellation/interruption rules, postponement windows (calendar days versus 48 hours), refunds and fair-price/outcome-review discretion are not equivalent. Retained cancellation detail remains incomplete. Exceptional mass/cashflows remain unknown, so **unconditional EV is unavailable**.

## Independent arithmetic

Original DraftKings Detroit +180 / Buffalo −218 yield exact de-vig probabilities 795/2321 and 1526/2321; stored Buffalo probability is `0.657475226195605343`. Detroit is `0.342524773804394657`. The native opposite bid produces the original $0.68 Buffalo YES ask.

| 10 contracts, historical cent scenario | USD / return |
|---|---:|
| Purchase cost | 6.80 |
| Raw quadratic entry fee | 0.15232 |
| Charged fee under cent rounding | 0.16 |
| Entry cash / ROI denominator | 6.96 |
| Expected ordinary-winner payout | 6.574752261956053430 |
| Conditional expected profit | −0.385247738043946570 |
| ROI = net / entry cash | −5.5351686500567% |

[Independent rational calculation](../evidence/page-ev-integration/independent-ten-contract.json) reads saved native inputs rather than app output. [Full displayed result](../evidence/page-ev-integration/ten-contract-result.json) reuses existing depth, fee and cashflow functions. Fee basis remains `kalshi-july7-observed-sep12`, multiplier 1, no event override, cent balance, a hypothetical new taker order with one fill per consumed level and no extra account charges/rebates. Current fees are not substituted. The existing selector also supports its explicit 0.0001 scenario or unresolved fees; unknown material fees suppress net/ROI.

**Retrospective, time-mismatched research comparison.** Source receipt: `2026-09-16T03:26:29.205210+00:00`; target receipt: `2026-09-16 01:07:35.681097+00:00`; original target cutoff: `2026-09-16T01:07:35.685652+00:00`. Bookmaker update time and delay unknown. Proportional margin removal, upstream synchronization and independence remain limitations.

## Display and checks

The compact research section appears only on the bound saved Detroit–Buffalo game. Requested quantity and fee scenario recalculate against its original retained target ladder; insufficient depth leaves the requested-size result unavailable. The section explicitly retains that target even if the observation cutoff selector changes. It never enters earlier-cutoff inputs, live results, rankings, prediction journals or prospective scores. Manual what-if values and observed prices remain separate.

33 focused/regression tests passed, including native rational depth-boundary checks, both precision scenarios, missing fees/depth/terms, assessment binding, team reversal, timestamps, live/other-game exclusion, manual separation and the byte-identical 18-candidate/96-scenario baseline. JavaScript syntax passed. Actual browser covered dashboard → game → research Details → manual what-if; temporary p=0.4 yielded −$2.96 while research remained −$0.39, then manual fields were cleared. The 390×844 smoke check found and fixed a scoped contrast issue; document width remained 390, including expanded evidence. No browser warnings/errors; viewport reset.

All 1,715 preexisting evidence files remain byte-identical. Earlier uncommitted work is preserved. Only identified idle beta PID 4249 was restarted (replacement PID 21610); final status confirms feeds stopped and cleanup complete. Public rules research only: no market-data request, scan, credentials, backfill, database migration, unrelated service change, trading, commit, push or publishing. This is implementation verification, not owner acceptance.
