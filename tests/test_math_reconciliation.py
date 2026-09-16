"""Independent rational oracle over saved native inputs; never used by the app."""
from fractions import Fraction as F
from decimal import Decimal, localcontext
from datetime import datetime
from pathlib import Path
import json
import unittest
from app.dashboard.multi_game import OUTPUT, saved_rows, project_game, default_point, game_calculation, rank_filter
from app.dashboard.opportunity_board import present

SID='5c9b7dca-a813-4d77-80f5-0691d06068eb'
def stamp(s): return datetime.fromisoformat(s.replace('Z','+00:00'))
def dec(f):
    with localcontext() as c:
        c.prec=100
        return format(Decimal(f.numerator)/Decimal(f.denominator),'f')
def ceiling(f): return -(-f.numerator//f.denominator)
def nearest_even(f): return round(f)
def oracle(levels, q, venue, grid=F('0.01')):
    """Rational depth walk and documented new-order taker fee recurrence."""
    left=F(q);cost=F(0);fee=F(0);overpayment=F(0);exact=F(0);fills=[];refund=F(0)
    for p,n in sorted(levels):
        n=min(n,left)
        if not n: break
        left-=n;cost+=p*n;raw=F('0.07' if venue=='kalshi' else '0.06')*n*p*(1-p)
        if venue=='kalshi':
            trade=F(ceiling(raw*1000000),1000000)
            debit=ceiling((p*n+trade)/grid)*grid
            extra=debit-p*n-trade;overpayment+=extra
            credit=min(overpayment//grid,(trade+extra)//grid)*grid
            overpayment-=credit;refund+=credit;fee+=debit-p*n-credit
        else:
            if n.denominator!=1 or not F('.01')<=p<=F('.99'):return None
            exact+=raw
            fee+=min(F(nearest_even(raw*100),100),max(F(0),F(nearest_even(exact*100),100)-fee))
        fills.append((p,n))
    if left:return None
    return dict(cost=cost,fee=fee,cash=cost+fee,refund=refund,fills=fills)

def native_inputs(rows,g,cutoff):
    out={};proof={}
    for venue in ('kalshi','polymarket_us'):
        matches=[r for r in rows if r['type'] in ('prediction_book','market_selected') and r['source']==venue and stamp(r['observed_at'])<=stamp(cutoff) and all((r.get('book') or r.get('market'))['raw']['ref'][k]==g['sources'][venue][k] for k in ('event_id','market_id'))]
        b=[r for r in matches if r['type']=='prediction_book'][-1];m=[r for r in matches if r['type']=='market_selected'][-1]
        raw=b['book']['raw'];n=json.loads(raw['json_text']);meta=json.loads(m['market']['raw']['json_text'])
        assert stamp(raw['received_at'])<=stamp(cutoff)
        assert stamp(m['market']['raw']['received_at'])<=stamp(cutoff)
        proof[venue]=dict(book=b['ingress_id'],received_at=raw['received_at'],listing=m['ingress_id'],listing_at=m['observed_at'])
        if venue=='kalshi':
            market=next(x for x in meta['markets'] if x['ticker']==g['sources'][venue]['market_id'])
            assert market['event_ticker']==g['sources'][venue]['event_id']
            assert market['notional_value_dollars']=='1.0000'
            assert market['rules_primary'].startswith('If '+g['teams'][0].split()[0]) or market['title'].replace(' wins','') in g['teams'][0]
            for side,other in [('yes','no'),('no','yes')]:out['kalshi:'+side]=sorted((1-F(p),F(q)) for p,q in n['reconstructed_bids'][other])
        else:
            event=next(e for e in meta['events'] if str(e['id'])==g['sources'][venue]['event_id'])
            market=next(x for x in event['markets'] if str(x['id'])==g['sources'][venue]['market_id'])
            assert stamp(market['gameStartTime'])==stamp(g['scheduled_start'])
            assert F(str(market['feeCoefficient']))==F('.06')
            assert n['marketData']['marketSlug']==market['slug']
            for side in market['marketSides']:
                key='polymarket_us:'+str(side['id']);assert side['team']['name']==g['sides'][key]['participant']
                assert g['sides'][key]['native_label']==('Long' if side['long'] else 'Short')
                out[key]=sorted((F(l['px']['value']),F(l['qty'])) for l in n['marketData']['offers']) if side['long'] else []
        proof[venue]['terms']=market.get('rules_secondary',market.get('description'))
    return out,proof

class ReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved=saved_rows(OUTPUT/SID);cls.rows=cls.saved['rows'];cls.games=next(r for r in cls.rows if r['type']=='multi_game_selection')['games']
    def test_all_saved_candidates_and_ev(self):
        evidence=[];ranking=[];evchecks=[]
        for g in self.games:
            timeline,rs=project_game(self.rows,g);point=default_point(timeline)
            levels,proof=native_inputs(self.rows,g,point['at']);r=present(game_calculation(point,rs,g,'100','cent'))
            values={k:oracle(ls,100,k.split(':')[0]) if ls else None for k,ls in levels.items()}
            # Every returned ladder and top quantity must equal original retained native inputs.
            for leg in r['contracts']:
                self.assertEqual([(F(l['price']),F(l['quantity'])) for l in leg['levels'] or []],levels[leg['id']])
            for c in r['candidates']:
                vs=[values[l['id']] for l in c['legs']];available=all(v is not None for v in vs)
                expected={k:None for k in ('notional','fees','cash','profit','return_pct')}
                if available:
                    cost=sum(v['cost'] for v in vs);fee=sum(v['fee'] for v in vs);cash=cost+fee;profit=100-cash
                    expected=dict(notional=dec(cost),fees=dec(fee),cash=dec(cash),profit=dec(profit),return_pct=dec(profit/cash*100))
                    for team in g['teams']:self.assertEqual(F(c['normal_cashflows']['winner:'+team]),profit)
                    for l,v in zip(c['legs'],vs):
                        self.assertEqual([(F(f['price']),F(f['quantity'])) for f in l['fills']],v['fills'])
                        self.assertEqual(F(l['cash']),v['cash']);self.assertEqual(F(l['fee']),v['fee'])
                        for team in g['teams']:
                            side=g['sides'][l['id']];wins=(team==side['participant'])==(side['predicate']=='win');flow=l['cashflows']['winner:'+team]
                            self.assertEqual(F(flow['gross_payout']),100 if wins else 0);self.assertEqual(F(flow['net_cashflow']),(100 if wins else 0)-v['cash'])
                        self.assertEqual(F(l['cashflows']['tie']['gross_payout']),50)
                for k,e in expected.items():self.assertEqual(None if c[k] is None else Decimal(c[k]),None if e is None else Decimal(e),(g['title'],c['id'],k))
                self.assertIsNone(c['worst_case_all_outcomes']);self.assertFalse(c['current_executable'])
                times=[stamp(l['received_at']) for l in c['legs']];skew=abs((max(times)-min(times)).total_seconds())
                self.assertEqual(c['usable'],available and skew<=5)
                evidence.append(dict(game=g['title'],candidate=c['id'],cutoff=point['at'],proof=proof,legs=[dict(id=l['id'],ask=l['ask'],top_size=l['top_size'],visible_size=l['visible_size'],fills=l['fills']) for l in c['legs']],displayed=c['display'],actual={k:c[k] for k in expected},independent=expected,profit_per_contract=None if not available else dec(profit/100),usable=c['usable'],skew_seconds=str(skew),match=True))
                ranking.append(dict(c,id=g['id']+'~'+c['id'],game_title=g['title']))
            for key,v in values.items():
                self.assertIsNone(game_calculation(point,rs,g,'100','cent',None,key)['ev']['expected_profit'])
                for p in ([F(0),F('.2'),F('.4'),F(1),v['cash']/100] if v else [F('.4')]):
                    e=game_calculation(point,rs,g,'100','cent',dec(p),key)['ev']
                    if v:
                        net=p*100-v['cash'];self.assertEqual(F(e['expected_payout']),p*100);self.assertEqual(F(e['expected_profit']),net)
                        self.assertEqual(Decimal(e['return_pct']),Decimal(dec(net/v['cash']*100)));self.assertEqual(F(e['break_even_pct']),v['cash'])
                    else:self.assertIsNone(e['expected_profit']);self.assertIsNone(e['break_even_pct'])
                    evchecks.append(dict(game=g['title'],contract=key,p=dec(p),profit=e['expected_profit'],break_even_pct=e['break_even_pct'],match=True))
                e=game_calculation(point,rs,g,'100','unknown','.4',key)['ev'];self.assertIsNone(e['expected_profit']);self.assertIsNone(e['break_even_pct'])
        ranks={}
        for sort,field in [('roi','return_pct'),('dollars','profit')]:
            want=sorted(ranking,key=lambda r:(not r['usable'],r[field] is None,-F(r[field]) if r[field] is not None else F(0),r['id']))
            got=rank_filter(ranking,sort=sort);self.assertEqual([r['id'] for r in got],[r['id'] for r in want]);ranks[sort]=[r['id'] for r in got]
        self.assertEqual(json.loads(json.dumps(dict(session=SID,quantity='100',scenario='cent',journal_sha256=self.saved['sha256'],candidates=evidence,ev_scenarios=evchecks,rankings=ranks))), json.loads(Path('evidence/math-reconciliation/baseline.json').read_text()))

class BoundaryTests(unittest.TestCase):
    def test_depth_boundary_and_capping(self):
        from copy import deepcopy
        from tests.test_opportunity_board import BoardTests
        from app.opportunities.board import evaluate
        BoardTests.setUpClass();point=deepcopy(BoardTests.point)
        o=point['cards'][1]['book']['outcomes'][0]
        o['quote'].update(ask='.20',ask_size='100')
        o['depth']['asks']['levels']=[dict(price=dict(value='.20'),quantity=dict(value='100',unit='contracts')),dict(price=dict(value='.30'),quantity=dict(value='100',unit='contracts'))]
        for q,cost,fee in [('99','19.8','.95'),('100','20','.96'),('101','20.3','.97'),('200','50','2.22')]:
            e=evaluate(point,BoardTests.rows,quantity=q,probability='.4')['ev']
            self.assertEqual(F(e['leg']['notional']),F(cost));self.assertEqual(F(e['leg']['fee']),F(fee))
            self.assertEqual(F(e['expected_profit']),F(q)*F('.4')-F(cost)-F(fee))
        self.assertIsNone(evaluate(point,BoardTests.rows,quantity='201')['ev']['expected_profit'])
        from tests.test_multi_game import MultiTests
        MultiTests.setUpClass()
        capped=game_calculation(point,BoardTests.rows,MultiTests.game,'201','cent','.4')['ev']
        self.assertEqual(capped['modeled_quantity'],'200');self.assertEqual(F(capped['expected_profit']),F('27.78'))

    def test_grouped_fees_and_rounding_refund(self):
        from app.fee_example import scenario
        from app.fees import calculate
        for venue,expected_cash in [('kalshi','1.85'),('polymarket_us','1.84')]:
            c=scenario(venue,price='.5',quantity='1')
            c['fills']=[dict(c['fills'][0],price=p,fill_id=str(i)) for i,p in enumerate(('.5','.6','.7'))]
            a=calculate(c)
            self.assertEqual(F(a['entry_cash_requirement']),F(expected_cash))
            self.assertEqual(oracle([(F(p),F(1)) for p in ('.5','.6','.7')],3,venue)['cash'],F(expected_cash))
            if venue=='kalshi':self.assertEqual(sum(F(t['rounding_refund']) for t in a['trace']),F('.01'))

class ExactRankingTests(unittest.TestCase):
    def test_rank_preserves_digits_beyond_ambient_decimal_precision(self):
        base=dict(usable=True,status='Conditional scenario',game_title='test')
        rows=[dict(base,id='a-lower',profit='1.00000000000000000000000000001',return_pct='1.00000000000000000000000000001'),
              dict(base,id='z-higher',profit='1.00000000000000000000000000002',return_pct='1.00000000000000000000000000002')]
        # Exact rational inequality; both values display 1.00, ID must not decide.
        self.assertGreater(F(rows[1]['profit']),F(rows[0]['profit']))
        for sort in ('roi','dollars'):
            self.assertEqual([r['id'] for r in rank_filter(rows,sort=sort)],['z-higher','a-lower'])

if __name__=='__main__':unittest.main()
