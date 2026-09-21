"""Offline official examples and explicitly synthetic fee scenarios."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
from app.fees import calculate, replay, load_registry, Registry


def scenario(venue='polymarket_us', product='event_contract', price='0.50', quantity='1000', role='taker'):
    versions={'kalshi':'kalshi-july7-observed-sep12','polymarket_us':'pmus-2026-07-01','prophetx':'prophetx-2026-08-19-v1','novig':'novig-'+product+'-observed-sep12'}
    c=dict(venue=venue,environment='production',market_id='synthetic-market',product=product,
           trade_time='2026-09-12T00:00:00Z',calculation_time='2026-09-12T02:00:00Z',
           schedule_version=versions[venue],complete_order_history=True,
           fills=[dict(fill_id='f1',order_id='o1',price=price,quantity=quantity,unit='contracts',role=role)],
           outcomes={'win':'1','loss':'0','half':'0.5'},settlement_status='UNKNOWN')
    if venue=='kalshi':
        c.update(series_id='KXNFLGAME',event_id='synthetic-event',balance_precision='0.01',kalshi_metadata=dict(
            source='synthetic event assumptions; series type corroborated by research/kalshi-nfl.json',
            series_id='KXNFLGAME',event_id='synthetic-event',event_history_complete=False,
            series_changes=[dict(scheduled_ts='2026-07-07T04:00:00Z',fee_type='quadratic_with_maker_fees',fee_multiplier='1')],event_changes=[]))
    return c


def examples():
    rows=[]
    def add(label,c,expected):
        r=calculate(c); replay(r)
        for key,val in expected.items():
            x=r
            for part in key.split('.'): x=x[int(part)] if isinstance(x,list) else x[part]
            if x!=val:
                try: equal = Decimal(x)==Decimal(val)
                except (TypeError, ArithmeticError): equal = False
                if not equal: raise AssertionError((label,key,x,val))
        rows.append(dict(label=label,expected=expected,result=r))
    for p,t,m in [('0.10','5.40','1.12'),('0.65','13.65','2.84'),('0.50','15.00','3.12')]:
        add('Official PMUS 1000-lot taker '+p,scenario(price=p),{'entry_fees':t})
        add('Official PMUS 1000-lot maker '+p,scenario(price=p,role='maker'),{'credits.0.amount':m})
    add('Official Kalshi general table, 100 at .50',scenario('kalshi',quantity='100'),{'entry_fees':'1.750000'})
    for q,p,fee in [('100','0.50','0.75000'),('100','0.30','0.63000'),('0.01','0.50','0.00008')]:
        add('Official Novig live '+q+' at '+p,scenario('novig','live',p,q),{'entry_fees':fee})
    for role in ('maker','taker'):
        add('Synthetic Novig pregame '+role,scenario('novig','pregame',role=role),{'entry_fees':'0.00000'})
    c=scenario(quantity='1'); c['fills']*=1
    c['fills'].append(dict(c['fills'][0],fill_id='f2'))
    add('Synthetic PMUS cumulative .015 + .015 = .03, not .04',c,{'entry_fees':'0.03'})
    c['fills'][1]['order_id']='o2'
    add('Synthetic PMUS separate orders each .02',c,{'entry_fees':'0.04'})
    c=scenario('novig','live','0.20','100'); c['fills'].append(dict(c['fills'][0],fill_id='f2',price='0.80'))
    add('Synthetic Novig unresolved aggregation',c,{'qualification':'unsupported','entry_fees':None})
    c['aggregation']='per_fill'; add('Synthetic Novig per-fill hypothesis',c,{'entry_fees':'0.96000'})
    c['aggregation']='match_vwap'
    for f in c['fills']: f['match_id']='match1'
    add('Synthetic Novig VWAP hypothesis',c,{'entry_fees':'1.50000'})
    c=scenario('prophetx','straight'); c['fills']=[]; c['market_cashflows']=dict(market_id=c['market_id'],stake_usd='40',gross_payouts={'win':'100','loss':'0'},complete_market=True)
    add('Synthetic ProphetX gain charge 1.20, not entry percentage .80',c,{'outcomes.win.settlement_fee_unrounded':'1.20','outcomes.win.settlement_fee':None,'entry_cash_requirement':'40'})
    c['settlement_rounding']='cent_half_even'; add('Synthetic ProphetX explicit rounding assumption',c,{'outcomes.win.net_payout':'98.80'})
    c=scenario('kalshi'); del c['balance_precision']; add('Unknown account precision',c,{'entry_fees':None})
    c=scenario(); c['trade_time']='2026-06-30T23:59:59Z'; add('Unknown historical PMUS schedule',c,{'schedule':None})
    c=scenario('novig','live',quantity='1'); c['fills'][0]['unit']='payout_cents'; add('Native Novig cent payout unit',c,{'entry_fees':'0.00008'})
    for p in ('0.01','0.99'):
        add('Synthetic boundary fractional PMUS '+p,scenario(price=p,quantity='0.01'),{'entry_fees':None,'qualification':'unsupported'})
    # Historical series selection uses preserved official metadata, no live access.
    c=scenario('kalshi',quantity='100'); c['series_id']='KXMLBGAME'; meta=c['kalshi_metadata']; meta['series_id']='KXMLBGAME'
    history=json.loads(Path('evidence/slice-9/research/kalshi-mlb-history.json').read_text(),parse_float=str)['series_fee_change_arr']
    meta['series_changes']=history; meta['source']='evidence/slice-9/research/kalshi-mlb-history.json'
    c['trade_time']='2026-08-07T04:59:45.130Z'; add('Historical MLB before official change',c,{'entry_fees':'1.750000'})
    c['trade_time']='2026-08-07T04:59:45.131Z'; add('Historical MLB at official change',c,{'entry_fees':'0.880000'})
    c=scenario('novig','parlay','0.10','100'); c.update(channel='app',price_basis='pre_fee')
    add('Official Novig parlay with explicit pre-fee input, not quoted all-in price',c,{'entry_cash_requirement':'10.90000'})
    return rows

if __name__=='__main__':
    print(json.dumps(dict(description='Hypothetical fee scenarios, not actual fills or opportunities',examples=examples()),indent=2))
