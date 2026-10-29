"""Audit-only terminal-payoff formulation; no production calculators imported."""
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from fractions import Fraction as F


def benchmark(gross, price):
    reference=gross.get('reference_binding')
    if reference:
        a,b=map(F,reference['odds'])
        probability=(b if reference['selected']==0 else a)/(a+b)
    else:
        refs=gross['reference_originals'];assert len(refs)==2
        predicate=gross.get('selected_predicate')
        if predicate is not None:
            assert all(r['selection']['predicate']['domain']==predicate['domain'] and
                F(r['selection']['predicate']['threshold'])==F(predicate['threshold']) for r in refs)
            direction='gt' if predicate['operator'] in ('gt','ge') else 'lt'
            assert predicate['operator'] in ('gt','ge','lt','le')
            selected=[r for r in refs if r['selection']['predicate']['operator']==direction]
            assert len(selected)==1
            a=F(selected[0]['decimal_odds']);b=F(next(r for r in refs if r is not selected[0])['decimal_odds'])
            probability=b/(a+b)
            # Check actual integer outcomes on both sides; equality is excluded.
            threshold=F(predicate['threshold'])
            for score in range(int(threshold)-2,int(threshold)+3):
                if score==threshold:continue
                native={'gt':score>threshold,'ge':score>=threshold,'lt':score<threshold,'le':score<=threshold}[predicate['operator']]
                assert native==(score>threshold if direction=='gt' else score<threshold)
        else:
            selected=[r for r in refs if r['selection']['participant_id']==price['selection']['participant']]
            assert len(selected)==1
            a=F(selected[0]['decimal_odds']);b=F(next(r for r in refs if r is not selected[0])['decimal_odds'])
            probability=b/(a+b)
            if price['selection']['predicate']=='not_win':probability=1-probability
            else:assert price['selection']['predicate']=='win'
    original=price['original']
    if original.get('transformation')=='one_minus_native_bid':
        assert F(original['value'])==1-F(original['native_value'])
        assert original['native_units']=='usd_per_contract'
    cost={'decimal_odds':lambda:1/F(original['value']),'usd_per_contract':lambda:F(original['value']),
        'cents_per_contract':lambda:F(original['value'])/100}[original['units']]()
    assert F(gross['selected_decisive_probability'])==probability
    assert F(gross['return_percent'])==100*(probability-cost)/cost
    if reference:assert F(gross['value'])==probability-cost
    return probability,cost


def conditional(metric, price, probability):
    original=price['original']
    if price['venue']=='novig':
        fee=F(0);risk=F(1);receipt=F(original['value'])
    else:
        assert price['venue']=='polymarket_us'
        assert original['units']=='usd_per_contract' and original['quantity_units']=='contracts'
        assert original['payout_units']=='USD' and F(original['payout'])==1
        with localcontext() as context:
            context.prec=80
            cost=Decimal(original['value'])
            charge=(Decimal('0.0695')*cost*(1-cost)).quantize(Decimal('.01'),rounding=ROUND_HALF_EVEN)
        fee=F(charge);risk=F(original['value'])+fee;receipt=F(1)
    net=probability*(receipt-risk)+(1-probability)*(-risk)
    expected=net/risk
    assert F(metric['net_per_dollar_risk'])==expected
    assert F(metric['return_percent'])==100*expected
    assert F(metric['trade_fee_usd'])==fee
    assert F(metric['normalization_risk_usd'])==risk
    assert F(metric['normal_win_receipt_usd'])==receipt
    if 'scenario_net_usd' in metric:assert F(metric['scenario_net_usd'])==net
    assert metric['source_times']==price['times']
    assert metric['calibrated'] is False and metric['execution_qualified'] is False
    return expected
