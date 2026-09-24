"""Offline depth scenarios: invented books, existing real fee schedules; no fee stubs."""
from dataclasses import replace
from decimal import Decimal
import json

from app.arbitrage_example import synthetic_inputs, historical, NOW
from app.arbitrage import detect
from app.depth import AcquisitionLadder, Search, size_depth, book_ladders
from app.models.core import QuoteSide, Probability, Quantity


def fixture(a=(('0.2','3'),('0.65','5')), b=(('0.2','3'),('0.65','5')), steps=('1','1'), minimums=('1','1'), exception='0.5', environment='synthetic'):
    data=synthetic_inputs(a[0][0],b[0][0],exception,environment=environment)
    ladders=[]
    for i,levels in enumerate((a,b)):
        o=data[2][i]
        o=replace(o,minimum=minimums[i],increment=steps[i],quote=replace(o.quote,
            ask=QuoteSide(price=Probability(value=Decimal(levels[0][0])),quantity=Quantity(value=Decimal(levels[0][1]),unit='contracts'))))
        data[2][i]=o
        ladders.append(AcquisitionLadder(o,tuple((p,q,'synthetic:slice-11:invented-level-'+str(n)) for n,(p,q) in enumerate(levels)),
            'synthetic-acquisition-asks',True))
    return data,ladders


def run(data, ladders, search=None):
    p,m,_,c,_=data
    return size_depth(p,m,ladders,c,evaluation_time=NOW,search=search)


def selected(report):
    return next(c for c in report['candidates'] if all(c['input']['ladders']))


def historical_depth():
    def builder(p,m,l,c,*,evaluation_time,**ignored):
        return size_depth(p,m,l,c,evaluation_time=evaluation_time)
    return historical(observation_factory=book_ladders,report_builder=builder)


def change_outcome(data, name, payout):
    from copy import deepcopy
    from app.fees.engine import digest
    p,m,_,_,rows=data
    row=deepcopy(rows[0]); payout=deepcopy(payout)
    if payout['kind']!='unknown': payout['evidence']=row['profile']['sources'][0]['sha256']
    row['profile']['payouts'][name]=payout
    row['profile']['hash']=digest({k:v for k,v in row['profile'].items() if k!='hash'})
    row['hash']=digest({k:v for k,v in row.items() if k!='hash'})
    m.update(p,[row,rows[1]])


def examples():
    rows={}
    data,ladders=fixture(a=(('0.2','3'),('0.65','7')),b=(('0.2','3'),('0.65','7'))); rows['shrinking-edge-and-distinct-objectives']=run(data,ladders,Search(min_roi='0.10'))
    rows['top-screen']=detect(data[0],data[1],data[2],data[3],evaluation_time=NOW,fill_grouping='single_fill_per_leg')
    data,ladders=fixture(a=(('0.2','4'),('0.95','2')),b=(('0.2','3'),('0.7','3')),steps=('2','3'))
    rows['unequal-improves-with-incompatible-grids']=run(data,ladders)
    data,ladders=fixture(a=(('0.2','1.25'),('0.4','2.75')),b=(('0.2','4'),),steps=('0.25','1'),minimums=('0.25','1'))
    rows['fractional-final-level']=run(data,ladders)
    from app.depth import evaluate_allocation
    rows['fractional-final-level']['explicit_partial_allocation']=evaluate_allocation(selected(rows['fractional-final-level']),('2','2'))
    data,ladders=fixture(a=(('0.4','2'),('0.5','2')),b=(('0.5','1'),('0.6','3')))
    rows['order-grouped-rounding']=run(data,ladders)
    data,ladders=fixture(); rows['partial-depth-binding-cash']=run(data,ladders,Search(total_cash_limit='1.7',venue_cash_limits=('0.7',None)))
    data,ladders=fixture(); next(c for c in data[3].values() if c['venue']=='polymarket_us').pop('assume_no_settlement_fee')
    rows['unknown-fees']=run(data,ladders)
    data,ladders=fixture(); change_outcome(data,'canceled',{'kind':'unknown','reason':'synthetic missing settlement outcome'})
    rows['unknown-settlement-conditional-sizing']=run(data,ladders)
    data,ladders=fixture(); change_outcome(data,'canceled',{'kind':'refund','evidence':'synthetic acquisition-cost refund'})
    rows['multi-level-refund']=run(data,ladders)
    data,ladders=fixture(a=(('0.1','4'),),b=(('0.5','4'),)); rows['nonmonotonic-roi-from-rounding']=run(data,ladders)
    data,ladders=fixture(exception='0'); rows['exceptional-outcome-loss']=run(data,ladders)
    data,ladders=fixture(a=(('0.55','4'),),b=(('0.55','4'),)); rows['no-profitable-allocation']=run(data,ladders)
    data,ladders=fixture(); rows['search-budget-exhausted']=run(data,ladders,Search(max_evaluations=5))
    edge=selected(rows['shrinking-edge-and-distinct-objectives'])
    assert edge['solutions']['max_profit']['allocation']['quantities']==['3','3']
    assert edge['solutions']['max_deployment']['allocation']['quantities']==['6','6']
    assert Decimal(evaluate_allocation(edge,('10','10'))['worst_case_profit'])<0
    unequal=selected(rows['unequal-improves-with-incompatible-grids'])
    assert unequal['solutions']['max_profit']['allocation']['quantities']==['4','3']
    assert Decimal(unequal['solutions']['max_profit']['allocation']['worst_case_profit'])==Decimal('1.52')
    return dict(description='Offline invented depth and payout scenarios using real versioned fee models; no current opportunities or actual fill guarantees.',
        synthetic=rows,historical_production=historical_depth(),next='PostgreSQL historical capture is separate; see app.storage.workflow')

if __name__=='__main__': print(json.dumps(examples(),indent=2))
