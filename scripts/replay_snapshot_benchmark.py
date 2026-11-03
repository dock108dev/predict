"""Audit fixed authentic retained inputs; never acquires prices or changes settings."""
import gzip
import json
from collections import Counter
from fractions import Fraction as F
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.comparison_snapshot import calculate
from app.storage.store import hashed

root=Path('test-results/ncaab-context')
report={}
for name,filename in [('fixed','retained-inputs.json.gz'),('larger','benchmark-inputs.json.gz')]:
    x=json.loads(gzip.decompress((root/filename).read_bytes()));digest=hashed(x)
    ncaab=[q for q in x['quotes'] if q['league']=='NCAAB']
    refs=[r for r in x['references'] if r['market']['competition']=='NCAAB']
    result=calculate(x)
    settings=dict(scenario='decisive_only',sizing='hypothetical_fractional',fees={v:'0' for v in ('kalshi','polymarket_us','novig','prophetx')})
    scenario=calculate(x,settings)
    rows=[r for r in result['rows'] if r['league']=='NCAAB']
    sr=[r for r in scenario['rows'] if r['league']=='NCAAB']
    example=next((r for r in result['rows'] if r['gross_return_percent'] is not None),None)
    checked=None
    if example:
        original=next(q for q in x['quotes'] if q['id']==example['id'])
        ref=original['reference'];a,b=map(F,ref['odds']);weights=[1/a,1/b];p=weights[ref['selected']]/sum(weights)
        cost=1/F(original['original']['value'])
        assert F(example['probability'])==p and F(example['cost_per_normal_claim'])==cost
        assert F(example['gross_return_percent'])==100*(p/cost-1)
        checked=dict(league=example['league'],game=example['game_title'],row_id=example['id'],
            reference_odds=ref['odds'],selected=ref['selected'],reference_sha256=ref['sha256'],
            source_at=ref['source_at'],received_at=ref['received_at'],original=original['original'],
            probability=str(p),cost=str(cost),gross_percent=str(100*(p/cost-1)),
            note='Authentic existing NFL arithmetic, not evidence of NCAAB binding')
    report[name]=dict(snapshot_id=x['id'],input_sha256=digest,observations=len(x['quotes']),
        ncaab_observations=len(ncaab),ncaab_by_venue=dict(Counter(q['venue'] for q in ncaab)),
        reference_observations=len(x['references']),references_by_league=dict(Counter(r['market']['competition'] for r in x['references'])),
        ncaab_reference_observations=len(refs),ncaab_complete_pairs=0,ncaab_incomplete_pairs=0,ncaab_conflicting_pairs=0,
        ncaab_absent_reference_observations=len(ncaab) if not refs else None,
        ncaab_observed_supported=sum(r['same_outcome']['supported'] for r in rows),
        ncaab_observed_numeric_ev=sum(r['gross_return_percent'] is not None for r in rows),
        ncaab_scenario_numeric_ev=sum(r['gross_return_percent'] is not None for r in sr),
        ncaab_scenario_net_ev=sum(r['net_return_percent'] is not None for r in sr),
        ncaab_numeric_opposing_minima=sum(r['league']=='NCAAB' and r['minimum_return_percent'] is not None for r in scenario['pairs']),
        diagnostics=result['benchmark_diagnostics'],authentic_existing_example=checked,scenario_assumptions=scenario['assumptions'])
    assert hashed(x)==digest
(root/'benchmark-replay.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
