"""New identified synthetic receipts of the existing synthetic NFL depth-book fixture.

Prices/rules remain invented; these are NOT relabeled historical observations.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from app.depth_example import fixture
from app.depth import size_depth
from app.edge_contracts import loads
from app.fees.engine import load_registry, digest
from app.pricing.baseline import restore
from app.storage.replay import observation_dump
from app.settlement import payout, SCENARIOS
from .service import POLICY

ROOT=Path(__file__).resolve().parents[2]


def inputs(price='0.2', quantity='3', model=None, estimate=None, levels=None):
    estimate=estimate or restore((ROOT/'evidence/e3/durable/estimate-4.json').read_text())
    at=estimate.data['as_of']; terms=loads(estimate.data['target']['terms_json'])
    data,ladders=fixture(a=levels or ((price,'3'),('0.95','5')), b=(('0.2','3'),('0.8','5')))
    p,m,obs,ctx,rows=data
    books=[]; fresh=[]
    for l in ladders:
        o=l.observation
        o=replace(o,quote=replace(o.quote,raw=replace(o.quote.raw,received_at=datetime.fromisoformat(at),exchange_at=datetime.fromisoformat(at),source='synthetic:E4-new-invented-book-receipt')))
        fresh.append(replace(l,observation=o))
        book=dict(observation=observation_dump(o),levels=l.levels,transformation=l.transformation,partial_final=l.partial_final,
            known_at=at,effective_at=at,evidence='synthetic:invented E4 receipt of existing NFL fixture levels')
        book['id']=digest(book); books.append(book)
    report=size_depth(p,m,fresh,ctx,evaluation_time=datetime.fromisoformat(at))
    candidate=next(c for c in report['candidates'] if all(c['input']['ladders']) and c['input']['base']['relationship']['left_side']=='yes')
    result=dict(policy=deepcopy(POLICY),estimate=estimate.export(),as_of=at,evaluated_at=at,
        candidate_id=candidate['id'],market=dict(known_at=at,effective_at=at,
        evidence='synthetic:invented contemporaneous mapping, settlement and account/fee context knowledge',
        canonical_event_id=terms.canonical_event_id,parents=p.envelope(),markets=m.envelope(),
        books=books,contexts=[[list(k),v] for k,v in ctx.items()],registry=load_registry().data),
        sizing=dict(quantity=quantity,known_at=at,effective_at=at,evidence='synthetic:invented quantity assumption; contracts per leg'),model=None)
    if model:
        row=next(r for r in rows if r['venue']==estimate.data['target']['venue'])
        side=next(s for s in row['sides'] if s['participant']==estimate.data['target']['outcome'] and s['predicate']==estimate.data['target']['predicate'])
        payouts={n:payout(side,n,row['profile']) for n in [*('winner:'+p for p in terms.outcomes),*SCENARIOS]}
        probabilities={n:'0.01' for n in SCENARIOS}
        probabilities.update({'winner:NFL:ATL':'0.60','winner:NFL:PIT':'0.33'})
        if model=='missing': probabilities.pop('canceled')
        result['model']=dict(version='invented-unconditional-scenarios-1',name='synthetic-nfl-complete-60-33-7' if model!='missing' else 'synthetic-nfl-missing-canceled',
            basis=POLICY['probability_basis'],target_hash=digest(estimate.data['target']),payouts_hash=digest(payouts),probabilities=probabilities,
            exclusive_exhaustive_assumption='synthetic:states are disjoint final resolution paths; one named exceptional state or normal winner, exhaustive by invention',
            claimed_fair_value_usd='0.635' if model!='missing' else None,
            known_at=at,effective_at=at,evidence='synthetic:separate invented unconditional model; never fills E3 missing mass')
    return result
