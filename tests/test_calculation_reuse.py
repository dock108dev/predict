"""Request-local shared calculation correctness and input invalidation."""
import unittest
from copy import deepcopy
from unittest.mock import patch
from pathlib import Path
FOLDER=Path(__file__).resolve().parents[1]/'evidence/live-freshness-run-b2391410-91d5-4c1a-aa19-cf5c94f6ae87/b2391410-91d5-4c1a-aa19-cf5c94f6ae87'
from app.dashboard.session_history import verified
from app.dashboard.session_projection import SessionProjection
from app.dashboard.product_view import calculate, dashboard

@unittest.skipUnless(FOLDER.exists(), 'retained local journal not distributed')
class CalculationReuse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p=SessionProjection();p.native_interpretation='native-book-comparison-3' # Sealed legacy mathematical interpretation.
        for row in list(verified(FOLDER)['rows'])[:1400]:p.apply(row)
        cls.snapshot=p.snapshot()

    def test_repeated_contracts_equal_and_avoid_depth_work(self):
        s=deepcopy(self.snapshot);s.pop('qualification_fee_policy',None);g=s['games'][0];cache={}
        from app.opportunities.board import leg_value
        with patch('app.opportunities.board.leg_value',wraps=leg_value) as legs:
            for key in g['sides']:
                for probability in (None,'0','0.37','1'):
                    q=dict(contract=key,probability=probability)
                    actual=calculate(s,g,q,reuse=cache)
                    count=legs.call_count
                    self.assertEqual(actual,calculate(s,g,q))
                    legs.reset_mock()
            self.assertEqual(count,0)
        # A caller cannot poison another contract's shared intermediate values.
        actual['assessment']['profiles'].clear()
        actual['ev']['leg']['warnings'].append('poison')
        self.assertEqual(calculate(s,g,q,reuse=cache),calculate(s,g,q))

    def test_every_input_and_time_change_recomputes(self):
        s=deepcopy(self.snapshot);g=s['games'][0];cache={};q={}
        calculate(s,g,q,reuse=cache)
        variants=[]
        for quantity in ('1','1000'):variants.append((deepcopy(s),deepcopy(g),dict(quantity=quantity)))
        for scenario in ('unknown','cent','direct'):
            x=deepcopy(s);x.pop('qualification_fee_policy',None);variants.append((x,deepcopy(g),dict(scenario=scenario)))
        x=deepcopy(s);x['points'][g['id']]['at']='2027-01-01T00:00:00+00:00';variants.append((x,deepcopy(g),{}))
        for field,value in [('connection','disconnected'),('receipt_stale',True)]:
            x=deepcopy(s);x['points'][g['id']]['cards'][0][field]=value;variants.append((x,deepcopy(g),{}))
        x=deepcopy(s);x['rows_by_game'][g['id']]=[];variants.append((x,deepcopy(g),{}))
        # Change a US ask and its matching depth atomically, then its quantity.
        for field,value in [('price','0.73'),('quantity','2.25')]:
            x=deepcopy(s)
            book=next(c['book'] for c in x['points'][g['id']]['cards'] if c['venue']=='polymarket_us')
            outcome=next(o for o in book['outcomes'] if o['depth']['asks'] and o['depth']['asks']['levels'])
            level=outcome['depth']['asks']['levels'][0]
            if field=='price':
                level['price']['value']=value;outcome['depth']['asks']['levels']=[level];outcome['quote']['ask']=value
            else:
                level['quantity']['value']=value;outcome['quote']['ask_size']=value
            variants.append((x,deepcopy(g),{}))
        x=deepcopy(s)
        for row in x['rows_by_game'][g['id']]:
            row['market']['raw']['json_text']=row['market']['raw']['json_text'].replace('within two weeks','within two days')
        variants.append((x,deepcopy(g),{}))
        game=deepcopy(g);game['sources']['kalshi']['market_id']='missing-native-contract';variants.append((deepcopy(s),game,{}))
        from app.opportunities.board import leg_value
        for x,game,query in variants:
            with patch('app.opportunities.board.leg_value',wraps=leg_value) as legs:
                result=calculate(x,game,query,reuse=cache)
            self.assertEqual(result,calculate(x,game,query))
        # Time-only change rejects old eligibility without requiring a new book.
        x=deepcopy(s)
        for card in x['points'][g['id']]['cards']:card.update(receipt_stale=True,age_seconds='60')
        stale=calculate(x,g,{},reuse=cache)
        self.assertTrue(all('Receipt stale at cutoff' in c['warnings'] for c in [stale['ev']['leg']]))
        self.assertFalse(stale['ev']['usable'])
        with self.assertRaises(ValueError):calculate(s,g,dict(probability='1.1'),reuse=cache)
        with self.assertRaises(ValueError):calculate(s,g,dict(quantity='0'),reuse=cache)

    def test_feed_views_exact_at_same_cutoff(self):
        cache={}
        for view in ('ev','arb'):
            q=dict(view=view)
            self.assertEqual(dashboard(self.snapshot,q,{},reuse=cache),dashboard(self.snapshot,q,{}))


class PortableReuse(unittest.TestCase):
    def test_exact_known_profit_probability_and_quantity(self):
        from app.dashboard.opportunity_board import load_sessions
        from app.dashboard.multi_game import default_point
        from app.opportunities.board import evaluate
        projected,rows=next(iter(load_sessions().values()))
        point=default_point(projected['timeline']);cache={}
        for probability,profit in [('0.5','15.67'),('0.2','-14.33'),('0','-34.33'),('1','65.67')]:
            actual=evaluate(point,rows,probability=probability,reuse=cache)
            self.assertEqual(actual,evaluate(point,rows,probability=probability))
            from decimal import Decimal
            self.assertEqual(Decimal(actual['ev']['expected_profit']),Decimal(profit))
        for quantity in ('1','100000000'):
            for scenario in ('cent','direct','unknown'):
                self.assertEqual(evaluate(point,rows,quantity=quantity,scenario=scenario,reuse=cache),evaluate(point,rows,quantity=quantity,scenario=scenario))
        actual['contracts'][0]['warnings'].append('poison')
        self.assertEqual(evaluate(point,rows,reuse=cache),evaluate(point,rows))
