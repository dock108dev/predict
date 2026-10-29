"""Render the dated common-snapshot inventory without merging evidence revisions."""
import json,sys
from pathlib import Path
from collections import Counter
r=json.loads(Path(sys.argv[1]).read_bytes());totals=Counter()
for v in r['cohorts'].values():totals.update(v)
lines=['# SC09-05 — captured applicability inventory','',f"Captured {r['captured_at']} in one repeatable-read SQL snapshot. Evidence: `{sys.argv[1]}`.",
'Books, observation slots, admitted contracts, price rows and directed result rows are distinct units. Counts are retained unless explicitly current; they do not establish offered denominators or 99% coverage. Raw access is independent of financial admission.',
'',f"Original-value mismatches: {r['raw_issues'].get('original_value_mismatch',0)}; quantity mismatches: {r['raw_issues'].get('quantity_mismatch',0)}. Invalid decimal-one values: {r['raw_issues'].get('aggregate_decimal_one',0)}. Polymarket Short bids not independently supplied: {r['raw_issues'].get('pm_short_bid_not_separately_supplied',0)}; these are not missing Short asks.",'','## Full received-to-published funnel','',
'| Venue | League | Family | Books | Slots | Admitted contracts | Published prices | Exact peer directions | Gross results | Conditional results |',
'| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
for key,v in r['cohorts'].items():
 fields=key.split('|');metrics=[v.get(k,0) for k in ('received_books','received_slots','admitted_contracts','published_prices','equal_contract_key_verified')]
 metrics += [v.get('independently_verified_gross',0)+v.get('independently_verified_typed_gross',0),v.get('independently_verified_conditional',0)]
 lines.append('| '+' | '.join(map(str,fields+metrics))+' |')
lines+=['','## Applicability by populated source/type class','',
'Each row retains its exact type, units, period and admission reason. Financial rule sets below apply to every row of that venue, with exact-reference and pregame requirements still enforced. A missing retained reference is not proof that a provider offers none.',
'',
'| Source | Supported result when exact comparison inputs exist | Remaining facts for full modeled net / covered arbitrage |',
'| --- | --- | --- |',
'| Kalshi | Original cents/USD prices, native YES/NO identity and compatible gross benchmark | Effective series/event fee changes and rounding binding; instrument exceptional settlement/fair value; complete outcome probabilities; quantity/funding. Selected historical NFL fee evidence does not cover every current series/event. |',
'| Polymarket US | Original USD prices and Long/Short semantics; gross and one-contract, one-fill standard taker fee scenario | Instrument exceptional settlement/fair value; complete probabilities; actual fill partition, account rebates and executable quantity/funding. Unsupplied native Short bid is separate from complemented Short acquisition cost. |',
'| Novig | Original decimal odds; exact-line gross and conditional zero pregame straight-trade fee scenario; existing hypothetical NFLWIN scenarios until unchanged review expiry | Aggregate-to-instrument/channel settlement mapping; tie/push/void and refund probabilities/cashflows; executable quantity/funding. Hypothetical probabilities remain uncalibrated. |',
'| ProphetX | Original decimal odds and exact compatible gross benchmark | Effective fee and instrument payout mapping; exceptional cashflows, complete outcome probabilities and quantity/funding. |',
'| Pinnacle | Reference originals and exact two-way decisive weights only | Full-outcome probabilities; complete retained pairs for each desired line. Never an execution venue. |','',
'| Venue | League | Family | Period | Native type | Contracts with offers | Price / quantity units | Explicit score predicates | Admission limitation |',
'| --- | --- | --- | --- | --- | ---: | --- | ---: | --- |']
for v in r['core_applicability_inventory']:
 fields=[v[k] for k in ('venue','league','family','period','native_type','contracts')]
 fields += [str(v['price_units'])+' / '+str(v['quantity_units']),v['explicit_score_predicates'],v['admission_reason'] or 'No predicate-admission refusal; other requirements remain']
 lines.append('| '+' | '.join(str('unknown' if x is None or x=='' else x).replace('|','/') for x in fields)+' |')
lines+=['','## Published result limitations by cohort','',
'Counts below are result rows, not books or offered contracts. Independent arithmetic is verified for every available gross and conditional result in the captured eligible population. Calibration and source applicability are separate. Current eligible no-positive evaluation must not be inferred from unsupported rows.',
'','| Cohort | EV rows | Availability states | Missing/unsupported reasons |','| --- | ---: | --- | --- |']
for key,v in r['cohorts'].items():
 if not v.get('published_ev_rows'):continue
 states=', '.join(f'{k[13:]}: {n}' for k,n in v.items() if k.startswith('availability:'))
 reasons=', '.join(f'{k[7:]}: {n}' for k,n in v.items() if k.startswith('reason:'))
 lines.append(f"| {key.replace('|',' / ')} | {v['published_ev_rows']} | {states} | {reasons or 'See exact captured result'} |")
lines+=['',f"Publication errors in this capture: {len(r['publication_errors'])}; calculation errors: {len(r['calculation_errors'])}.",
'Native spread/total price comparisons use their exact admitted predicates where supported. The typed native probability-reference owner currently supports winner contracts; extending exact native spread/total reference binding is a remaining implementation requirement; it also needs explicit reference scoring and equality bindings, distinct from missing fee or probability facts. Counts affected are the native spread/total EV rows and their captured `gross_decisive_winner_identity_unsupported` reasons above.',
'Full arrays, source clocks, raw links, reference originals and conditional evidence are in the bound JSON. Ordinary display is verified by a separate page read with its own token/revision; its counts must not be combined with this snapshot.',
'', 'Remaining execution ownership: domain/backend engineers bind instrument fees and settlement; quantitative QA establishes defensible full-outcome probabilities; acquisition QA establishes offered boundaries and reference availability; integration QA measures sustained publication and the original 99% target. Owner acceptance remains separate.','']
Path(sys.argv[2]).write_text('\n'.join(lines))
