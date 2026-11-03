"""Replay the fixed November 2 input without SQL, providers or source mutations."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
from collections import Counter
from fractions import Fraction as F
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.comparison_snapshot import calculate
from app.storage.store import hashed

root=Path('test-results/ncaab-context')
payload=(root/'retained-inputs.json.gz').read_bytes()
inputs=json.loads(gzip.decompress(payload));before=hashed(inputs)
affected={q['id'] for q in inputs['quotes'] if q['league']=='NCAAB' and q['venue']=='polymarket_us' and q['same_outcome'].get('reason')=='comparison_context_missing'}
assert len(affected)==5944
report=dict(snapshot_id=inputs['id'],retained_gzip_sha256=hashlib.sha256(payload).hexdigest(),denominator=len(affected),
    baseline=dict(supported=0,context_refusals=5944),replays={})
for name,settings in [('observed',{}),('conditional',dict(scenario='decisive_only',sizing='hypothetical_fractional',fees={'polymarket_us':'0','novig':'0'})),
        ('assumed_scoring',dict(scenario='decisive_only',sizing='hypothetical_fractional',fees={'polymarket_us':'0','novig':'0'},scoring='ncaab_full_game_overtime'))]:
    result=calculate(inputs,settings);rows=[r for r in result['rows'] if r['id'] in affected]
    pairs=[p for p in result['pairs'] if set(p['legs'])<=affected]
    oracle_checked=0
    if name!='observed':
        originals={q['id']:q for q in inputs['quotes']}
        for pair in pairs:
            costs=[originals[k]['original'] for k in pair['legs']]
            assert all(c['units']=='usd_per_contract' and c['payout']=='1' for c in costs)
            deployed=F(result['assumptions']['amount']);buffer=F(result['assumptions']['buffer'])
            expected=deployed/sum(F(c['value']) for c in costs)-deployed-buffer*deployed
            assert F(pair['math']['scenario_minimum_usd'])==expected
            oracle_checked+=1
    report['replays'][name]=dict(independent_original_price_oracles=oracle_checked,supported=sum(r['same_outcome']['supported'] for r in rows),
        unavailable=dict(Counter(r['same_outcome']['reason'] for r in rows if not r['same_outcome']['supported'])),
        ambiguous=sum(r['same_outcome'].get('reason')=='snapshot_occurrence_ambiguous' for r in rows),
        cross_source_associated=sum(len(r.get('snapshot_identity',{}).get('members',[]))>1 for r in rows),
        scenario_calculations=sum(r['math']['available'] for r in rows),opposing_pairs=len(pairs),
        numeric_pair_minima=sum(p['minimum_return_percent'] is not None for p in pairs),
        numeric_ev=sum(r['gross_return_percent'] is not None for r in rows),
        promoted_strict_bindings=sum(r['binding']['verified'] for r in rows),assumptions=result['assumptions'],
        representative_pair=pairs[0] if pairs else None)
assert hashed(inputs)==before
report['originals_unchanged']=True
(root/'snapshot-boundary-replay.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:{n:v for n,v in r.items() if n not in ('representative_pair','assumptions')} for k,r in report['replays'].items()},indent=2))
