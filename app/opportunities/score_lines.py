"""Score partition dispatch; fee/depth cashflows reuse board.leg_value unchanged."""
from decimal import Decimal,Context,localcontext
import json
from app.normalization.score_lines import market_partitions,payout,distribution
from app.opportunities.board import contracts,leg_value,textnum,total
from app.fees.engine import number
from app.settlement import profile
from app.reference.product import time


def evaluate(point,rows,quantity,scenario,probability,selected,identity):
    with localcontext(Context(prec=100)):
        return _evaluate(point,rows,quantity,scenario,probability,selected,identity)


def _evaluate(point,rows,quantity,scenario,probability,selected,identity):
    q=number(quantity)
    if q<=0 or q!=q.to_integral_value() or q>100000000:raise ValueError('Use positive whole contracts up to 100,000,000')
    if scenario not in ('unknown','cent','direct'):raise ValueError('Unknown fee scenario')
    if selected not in identity['sides']:raise ValueError('Unknown score contract')
    i=identity['product_identity'];parts=market_partitions(i)
    assessment=dict(assessed_at=point['at'],observation_cutoff=point['at'],profiles={},sources={},pmus_coefficient=None,note='Completed-game score partitions only. Exceptional payouts and probabilities are not established.')
    bases={};assessment[i['competition'].lower()+'_fee_bases']=bases
    for venue,r in identity['score_reviews'].items():
        row=next((v for v in rows if v['source']==venue and time(v['observed_at'])<=time(point['at'])),None)
        if not row:continue
        raw=row['market']['raw']
        source=dict(url=raw['source'],sha256=r['raw_sha256'],text=json.dumps(r['terms'],sort_keys=True),priority='market-specific',received_at=raw['received_at'])
        assessment['profiles'][venue]=profile(sources=[source],actor='Explicit score-line review',dimensions={},payouts={})
        assessment['sources'][venue]=dict(source=source,known_at=row['observed_at'],market_id=r['market_id'])
        if r.get('fee_basis'):bases[venue]=r['fee_basis']
        if venue=='polymarket_us':assessment['pmus_coefficient']=r.get('fee_basis',{}).get('coefficient')
    cs=contracts(point,identity);legs={}
    for k,c in cs.items():
        side=identity['sides'][k];c['contract']=side['label']+' · '+side['domain'].replace('_',' ')+' '+{'gt':'>','ge':'≥','lt':'<','le':'≤'}[side['operator']]+' '+side['threshold']+' · equality: '+side['equality'].replace('_',' ');pays={}
        for part in parts:
            v=payout(side,part)
            pays[part['id']]=dict(kind='unknown' if v is None else 'stake_refund' if v=='refund' else 'fraction',value=v)
        leg=leg_value(c,assessment,point['at'],q,scenario,identity,score_payouts=pays)
        terms=identity['score_reviews'][c['venue']]['terms']
        issues=[]
        if any(v['kind']=='unknown' for v in pays.values()):issues.append('Equality payout or refund fee treatment unknown / unsupported; returned fees require separate economics')
        if terms['settlement_fee']!='none':issues.append('Source settlement fee is unknown or unsupported')
        if issues:
            leg['cashflows']={p['id']:None for p in parts};leg['reasons']+=issues
        leg['score_predicate']=side;leg['partition_payouts']=pays;legs[k]=leg
    candidates=[]
    for cid,title,keys in identity['candidates']:
        ls=[legs[k] for k in keys];reasons=list(dict.fromkeys(v for l in ls for v in l['reasons']))
        receipts=[time(l['received_at']) for l in ls if l['received_at']]
        if len(receipts)==2 and abs((receipts[0]-receipts[1]).total_seconds())>5:reasons.append('Books more than 5 seconds apart at cutoff')
        flows={p['id']:total([None if not l['cashflows'].get(p['id']) else l['cashflows'][p['id']]['net_cashflow'] for l in ls]) for p in parts}
        net=None if reasons or any(v is None for v in flows.values()) else min(flows.values())
        cash=total([l['cash'] for l in ls]);raw=total([l['ask'] for l in ls])
        candidates.append(dict(id=cid,title=title,legs=ls,status='Conditional scenario' if net is not None else 'Unavailable',raw_combined_price=textnum(raw),raw_gap=None,
            notional=textnum(total([l['notional'] for l in ls])),fees=textnum(total([l['fee'] for l in ls])),cash=textnum(cash),profit=textnum(net),return_pct=textnum(None if net is None or not cash else net/cash*100),normal_cashflows={k:textnum(v) for k,v in flows.items()},worst_case_all_outcomes=None,settlement={'normal':'completed full game including overtime','exceptions':{v:r['terms'] for v,r in identity['score_reviews'].items()}},relationship='Exact reachable score partition',reasons=reasons,positive_normal_scenario=net is not None and net>0,current_executable=False,score_partitions=parts))
    leg=legs[selected];ev=dict(probability=None,probability_source='Explicitly supplied score-partition scenario; manual input is not a forecast',conditional_on='Completed full-game score only; cancellation, suspension, void and other exceptions excluded',expected_payout=None,expected_profit=None,return_pct=None,break_even_pct=None,status='Assumption needed',leg=leg,score_partitions=parts,reasons=list(leg['reasons']))
    if probability not in (None,''):
        try:
            dist=distribution(probability,parts,identity['sides'][selected]);ev['probability']=probability if isinstance(probability,str) else dist;ev['probability_distribution']=dist
            fs=leg['cashflows']
            if not leg['reasons'] and all(fs.get(k) and fs[k]['net_cashflow'] is not None for k in dist):
                net=sum((Decimal(p)*Decimal(fs[k]['net_cashflow']) for k,p in dist.items()),Decimal(0));gross=sum((Decimal(p)*Decimal(fs[k]['gross_payout']) for k,p in dist.items()),Decimal(0))
                ev.update(expected_payout=textnum(gross),expected_profit=textnum(net),return_pct=textnum(net/Decimal(leg['cash'])*100),status='Conditional scenario')
            else:ev['status']='Unavailable'
        except (ValueError,TypeError) as exc:ev.update(status='Unavailable',reasons=[*ev['reasons'],str(exc)])
    return dict(cutoff=point['at'],quantity=str(q),scenario=scenario,assessment=assessment,candidates=candidates,ev=ev,contracts=list(cs.values()),score_partitions=parts,assumptions='Hypothetical equal-quantity taker fills through retained depth and source-specific fee schedules. Each reachable integer-score partition is evaluated; stake refunds return actual purchase cost and retain entry fees. Exceptional payouts/probabilities unknown. Account precision and no event fee override are explicit what-if assumptions.',ranking='Minimum completed-game partition profit; no all-outcome guarantee or executable claim.')
