"""Independent rational verification of an ordinary captured EV traversal.

Usage: python scripts/sc09_result_proof.py PAGE_DIRECTORY OUTPUT_JSON
The input files are exact ordinary /api/boards/slate responses. No production
calculator, database, provider or order API is called.
"""
import json
import sys
from pathlib import Path
from fractions import Fraction as F
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.dashboard.comparison_board import expand_price_fields
from sc09_independent_math import benchmark, conditional as verify_conditional
results=[];financial=[];aggregate=[];conditional=[];identity=None;offset=0;complete=False;games_seen=set()
for path in sorted(Path(sys.argv[1]).glob('*.json')):
 page=json.loads(path.read_bytes())
 assert not complete
 key=(page['read_token'],page['read_revision'],page['read_at'])
 if identity is None:identity=key
 assert key==identity and page['provider_requests']==0
 coverage=page['coverage'];assert coverage['offset']==offset
 assert len(page['boards'])+len(page['errors'])==coverage['returned_games']
 offset+=coverage['returned_games'];complete=coverage['complete']
 assert coverage['next_offset']==(None if complete else offset)
 for compact in page['boards']:
  assert compact['game_key'] not in games_seen;games_seen.add(compact['game_key'])
  b=expand_price_fields(compact);prices={p['quote_id']:p for p in b['prices']}
  for row in b['rows']:
   p=prices[row['price_ref']];g=row.get('gross_decisive_benchmark') or {}
   if g.get('available') and g.get('reference_binding'):
    ref=g['reference_binding'];a,z=map(F,ref['odds']);prob=(z if ref['selected']==0 else a)/(a+z)
    cost=1/F(p['original']['value']);want=100*(prob-cost)/cost
    assert F(g['selected_decisive_probability'])==prob
    assert F(g['value'])==prob-cost
    assert F(g['return_percent'])==want
    aggregate.append(dict(quote=row['quote_id'],expected=str(want)))
   if g.get('available') and not g.get('reference_binding'):
    refs=g['reference_originals'];assert len(refs)==2
    prob,cost=benchmark(g,p);original=p['original'];want=100*(prob-cost)/cost
    results.append(dict(quote=row['quote_id'],expected=str(want),actual=g['return_percent'],original=original,reference=refs))
   metric=row.get('conditional_trade_benchmark') or {}
   if metric.get('available'):
    prob,_=benchmark(g,p)
    expected=verify_conditional(metric,p,prob)
    conditional.append(dict(quote=row['quote_id'],expected=str(expected),state=metric['state'],evidence=metric['evidence']))
   fm=row.get('financial_metrics') or {}
   if any(v is not None for k,v in fm.items() if k in ('net_modeled_ev_usd','conditional_net_ev_usd','buffered_ev_usd','conditional_buffered_ev_usd')):
    financial.append(dict(game=b['game_key'],row=row,price=p))
assert complete and offset==coverage['total_games']
checks=[]
for item in financial:
 row=item['row'];p=item['price'];fm=row['financial_metrics'];g=row['gross_decisive_benchmark'];ref=g['reference_binding'];a,z=map(F,ref['odds']);prob=(z if ref['selected']==0 else a)/(a+z)
 capital=F(row['funding']['deployed_usd']);odds=F(p['original']['value']);face=capital*odds;haircut=F(row['buffer_usd'])
 params=row['modeled_basis']['scenario_parameters'];tie=F(params['tie_probability']);void=F(params['void_probability']);refund=F(params['refund_given_void']);fv=params['expected_fair_value_given_nonrefund']
 assert refund==1 or fv is not None
 void_receipt=refund*capital+(1-refund)*face*(F(fv) if fv is not None else 0)
 decisive=face*prob-capital
 net=(1-tie-void)*face*prob+tie*face/2+void*void_receipt-capital
 expected=dict(gross_benchmark_ev_usd=decisive,conditional_net_ev_usd=decisive,conditional_buffered_ev_usd=decisive-haircut,net_modeled_ev_usd=net,buffered_ev_usd=net-haircut,net_modeled_return_percent=100*net/capital,buffered_return_percent=100*(net-haircut)/capital)
 for k,want in expected.items():assert F(fm[k])==want,(k,fm[k],str(want))
 corners=[]
 for corner in row['modeled_basis']['sensitivity']['corners']:
  t,v,r,f=map(lambda k:F(corner[k]),('tie_probability','void_probability','refund_given_void','expected_fair_value_given_nonrefund'))
  want=(1-t-v)*face*prob+t*face/2+v*(r*capital+(1-r)*f*face)-capital-haircut
  assert want==F(corner['buffered_ev_usd']);corners.append(str(want))
 checks.append(dict(quote=row['quote_id'],verified={k:str(v) for k,v in expected.items()},sensitivity_corners=corners))
Path(sys.argv[2]).write_text(json.dumps(dict(aggregate_gross_verified=aggregate,typed_gross_verified=results,modeled_verified=checks,conditional_verified=conditional,provider_requests=0)))
print(json.dumps(dict(aggregate_gross=len(aggregate),typed_gross=len(results),modeled=len(checks),conditional=len(conditional),sensitivity_corners=sum(len(x['sensitivity_corners']) for x in checks))))
