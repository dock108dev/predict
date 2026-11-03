"""Compact units-preserving summary of one pipeline_window_census result."""
from collections import Counter,defaultdict
import json,sys
from pathlib import Path
v=json.loads(Path(sys.argv[1]).read_text());totals=Counter();venues=defaultdict(Counter)
for key,counts in v['cohorts'].items():
    totals.update(counts);venues[key.split('|')[0]].update(counts)
result=dict(result_units={k:x for k,x in v.get('result_units',{}).items() if k!='records'},at=v['captured_at'],window_end=v['window_end'],engine=v['engine'],source_events=v['source_events'],games=v['games'],
    normalized_execution_offers=totals['normalized_offers']-venues['pinnacle']['normalized_offers'],
    normalized_reference_offers=venues['pinnacle']['normalized_offers'],totals=dict(totals),venues={k:dict(c) for k,c in venues.items()},
    branches={k:x for k,x in v['branch_dispositions'].items() if k!='records'},exact_groups=v['exact_cross_source_groups'],
    same_outcome_price_pairs=v['same_outcome_cross_source_price_pairs'],normal_score_complements=v['normal_score_opposing_pairs'],
    published_pair_rows=v['published_pair_rows']['total'],
    received_native_books={k:x for k,x in (v.get('native_receipt_trace') or {}).items() if k!='records'},
    matching_lookup_population=len(v.get('matching_lookup') or []),
    matching_primary=dict(Counter(x['primary_reason'] for x in v.get('matching_lookup') or [])),
    notes=['Financial current/historical counts in totals and venues are price rows; games contains frame counts.',
        'Independent same-outcome and normal-score complement enumeration does not establish complete financial eligibility.',
        'Missing models, fees, rules or payout evidence are refusals, never zeros.'])
Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:x for k,x in result.items() if k not in ('totals','venues','received_native_books')},indent=2))
