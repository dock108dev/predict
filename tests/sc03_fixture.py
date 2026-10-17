"""Explicit authored finance plus typed discovery context for SC03 integration.

Readiness overrides below are authored assumptions; never source qualification.
"""
from copy import deepcopy
from app.comparison.current_dependencies import digest
from app.comparison.readiness_inputs import instrument
from app.comparison.scanner_projection import Projection, Filters
from app.comparison.estimated_policy import RequestedTradePolicy
from app.comparison.scanner_readiness import Selection
from tests.test_sc01_readiness import projection
from tests.test_sc03_finance import authored_finance_fixture, AT


def ready(kind='native',amount='100'):
    _,_,inputs,_=authored_finance_fixture(kind=kind,amount=amount)
    rows=[];renamed={}
    for x in inputs.values():
        q=x['quote'];clock=AT.isoformat()
        book=dict(source_at=clock,received_at=clock,sync='synchronized',state='active',quantity_unit='contracts')
        row=instrument(q,x['profiles'],x['event'],x['group'],at=clock,
            source_status=dict(state='available'),authorized=True,book=book)
        row['native_contract_id']='authored-contract:'+digest(q['binding'])
        row['terms_sha256']=digest(dict(binding=q['binding'],profiles=q['comparison_input_refs']))
        # Fixture scope/grids/source clocks are expressly authored and ready.
        for check in ('execution','contract','ev'):row['checks'][check]=dict(state='ready',reason_codes=[])
        rows.append(row);renamed[row['id']]=deepcopy(x)
    selected=Selection(venues=tuple(r['venue'] for r in rows))
    f=projection(rows,selection=selected,at=AT.isoformat());f['engine_binding']='authored-SC03-engine'
    p=Projection(clock=lambda:AT.isoformat(),policy=RequestedTradePolicy(capital_ceiling_usd=amount,sizing_mode='ceiling'))
    p.ingest(f,renamed)
    while p.pending:p.drain()
    page=p.view(filters=Filters(category='conditional_hedge'))
    assert page['rows'],p.errors
    return p,f,renamed,page['rows'][0]
