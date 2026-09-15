"""Write the readable report and artifact hashes after offline verification."""
from pathlib import Path
from hashlib import sha256
from decimal import Decimal
import json

root=Path.cwd(); out=root/'evidence/slice-10'
report=json.loads((out/'arbitrage_example.txt').read_text())
(out/'detector-example.json').write_text(json.dumps(report,indent=2)+'\n')
hist=report['historical_production']
lines=['# Slice 10 — offline detector report','',
       '**287 tests and all ten examples pass. No current production opportunity qualifies.**','',
       'Ten production structural pairs remain settlement-UNKNOWN. Twenty candidate leg combinations retain their diagnostics; related liquidity families are not independent capacity.','',
       '## Captured production diagnostics','',
       '| Native legs | Asks | Reference gap | Limitations |',
       '|---|---|---|---|']
for c in hist['candidates']:
    labels=[]; prices=[]
    for leg in c['legs']:
        # Native key is a compact JSON string retaining evidence/environment/event/market.
        key=json.loads(leg['native_market_key'])
        labels.append(key[2]+': '+key[-1]+' / '+leg['side'])
        obs=leg['observation']; prices.append(obs['ask'] if obs and obs['ask'] is not None else 'unavailable')
    gap=c['pricing_diagnostic']['unit_payout_reference_gap']
    limits=['settlement UNKNOWN']
    if any('unavailable'==p for p in prices): limits.append('one or both asks unavailable')
    if gap is not None: limits.extend(['no raw pricing edge','receipt skew '+c['pricing_diagnostic']['observation_skew_seconds']+' seconds'])
    limits.extend(['verified sizing/fee contexts unavailable','historical observations'])
    lines.append('| '+' + '.join(labels)+' | '+' + '.join(prices)+' | '+(gap or 'unknown')+' | '+'; '.join(limits)+' |')
lines+=['','The sole two-ask sum is 1.0100 ($1 reference gap −0.0100). It lacks a raw edge and also lacks qualification evidence. Available images retain their original timestamps. Source-time, status/lock and reconstruction reasons are listed per leg in the full JSON. Missing markets were not assigned synthetic historical books.','',
        '## Synthetic demonstrations','',
        '| Scenario | Quantity | Worst profit (USD) | Classification / limit |',
        '|---|---:|---:|---|']
for name,r in report['synthetic'].items():
    c=next((c for c in r['candidates'] if c['conditional_calculation']),None)
    calc=c['conditional_calculation'] if c else None
    q=calc['quantity'] if calc else 'unsized / deferred'
    profit=calc['worst_case_profit'] if calc else None
    classification=calc['classification'] if calc else 'diagnostic only'
    lines.append(f'| {name} | {q} | {profit if profit is not None else "unknown"} | {classification}; no current production qualification |')
lines+=['','Positive baseline arithmetic: 100 × (.40 + .40) = $80 acquisition cost; Kalshi modeled cash fee $1.68 plus PMUS $1.44 yields $83.12 required cash and $16.88 worst-case conditional profit. The zero example separately reserves/consumes $16.88. At .49 + .49, $98 acquisition plus $3.25 fees produces a $1.25 loss. An exceptional zero payout produces an $83.12 loss.','',
        'All real-fee-model positive scenarios remain conditional: Kalshi schedule/account assumptions and PMUS settlement-fee assumptions are not waived. Test-only synthetic zero-fee results exercise the qualification branch but are not venue fee evidence.','',
        'Defaults: 30-second receipt age, 5-second cross-leg receipt skew and 30-second source snapshot age, inclusive and configurable. Last-change age is not disconnection or latency. Fee/account unknowns remain unknown; maker-dependent orders are deferred. All calculations assume both taker legs fill once at the stated asks.','',
        '[Full results](detector-example.json) · [Verification](verification.json) · [API and limitations](../../docs/slice-10.md)','',
        '**Next: Slice 11 — full-depth arbitrage calculation and sizing. Not implemented.**','']
(out/'report.md').write_text('\n'.join(lines))
baseline=json.loads((out/'baseline.json').read_text())
changes=[p for p,h in baseline.items() if not (root/p).is_file() or sha256((root/p).read_bytes()).hexdigest()!=h]
assert not changes, changes
(out/'preservation.json').write_text(json.dumps({'checked_files':len(baseline),'changed':changes,
    'scope':'PLAN.md and all pre-existing app/tests/docs/evidence files; credentials deliberately not read',
    'result':'unchanged','baseline':'baseline.json'},indent=2)+'\n')
paths=[root/'app/arbitrage.py',root/'app/arbitrage_example.py',root/'tests/test_arbitrage.py',root/'docs/slice-10.md',root/'README.md']
paths += [p for p in out.iterdir() if p.is_file() and p.name!='manifest.json']
tracker=Path('/Users/michaelfuscoletti/Desktop/prediction_arb_next_steps.md')
manifest={'engine':'top-of-book-1','files':{str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},
          'desktop_tracker':{'path':str(tracker),'sha256':sha256(tracker.read_bytes()).hexdigest()}}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'preserved_files':len(baseline),'changed_prior_artifacts':changes,'hashed_deliverables':len(paths)},indent=2))
