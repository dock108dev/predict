import unittest
from copy import deepcopy
from decimal import Decimal, localcontext
from pathlib import Path

from app.opportunities.fixtures import inputs
from app.opportunities.service import evaluate, replay, restore, rank, Audit
from app.fees.engine import digest
from app.reference.records import packed
from app.pricing.baseline import restore as estimate_restore
from app.matching import Matcher
from app.moneyline import MoneylineMatcher


def reidentify(book):
    book['id']=digest({k:v for k,v in book.items() if k!='id'})


def alter_rule(x, kind, value=None):
    p=Matcher.from_envelope(x['market']['parents']); m=MoneylineMatcher.from_envelope(x['market']['markets'])
    rows=list(m.snapshot['observations'].values())
    row=next(r for r in rows if r['venue']=='kalshi')
    pay={'kind':kind}
    if kind=='unknown': pay['reason']='synthetic unknown cancellation payout'
    else:
        pay['evidence']=row['profile']['sources'][0]['sha256']
        if value is not None: pay['value']=value
    row['profile']['payouts']['canceled']=pay
    row['profile']['hash']=digest({k:v for k,v in row['profile'].items() if k!='hash'})
    row['hash']=digest({k:v for k,v in row.items() if k!='hash'})
    m.update(p,rows); x['market']['markets']=m.envelope()
    return x


class OpportunitiesTest(unittest.TestCase):
    def signals(self,x): return evaluate(x).data['signals']

    def test_saved_e3_unknown_and_exact_replay(self):
        x=inputs(); a=evaluate(x); self.assertEqual(restore(a.export()),a)
        s=a.data['signals']; self.assertEqual(Decimal(s[0]['net_total_usd']),Decimal('1.73'))
        self.assertIsNone(s[1]['net_total_usd']);self.assertIsNone(s[1]['unconditional_fair_value_usd'])
        self.assertEqual(s[1]['conditional_probability'],'0.525000000000000000')
        self.assertEqual(x['estimate'],a.data['inputs']['estimate'])
        self.assertIn('exceptional_probability_mass_unknown',s[1]['reasons'])
        self.assertEqual(len(s[1]['state_cashflows']),9)

    def test_independent_positive_negative_and_units(self):
        # Invented mass .60/.33/.01 each exceptional -> payout .635/contract.
        # At 3 contracts, payout 1.905; Kalshi ceil(.07*3*.2*.8)=.04.
        # At .8 price the same .04 entry fee applies, independently of model.
        for price,expected,cash in [('0.2','1.265','0.64'),('0.8','-0.535','2.44')]:
            with self.subTest(price=price):
                s=self.signals(inputs(price=price,model='complete'))[1]
                self.assertEqual(Decimal(s['net_total_usd']),Decimal(expected))
                self.assertEqual(Decimal(s['denominator_usd']),Decimal(cash))
                self.assertEqual(Decimal(s['unconditional_fair_value_usd']),Decimal('.635'))
                with localcontext() as c:
                    c.prec=100
                    self.assertEqual(Decimal(s['net_per_contract_usd']),Decimal(expected)/3)
                    self.assertEqual(Decimal(s['return_fraction']),Decimal(expected)/Decimal(cash))
                self.assertFalse(s['current_production_opportunity'])

    def test_arb_independent_of_probability_model(self):
        self.assertEqual(self.signals(inputs())[0],self.signals(inputs(model='complete'))[0])

    def test_probability_unknown_invalid_and_target_binding(self):
        s=self.signals(inputs(model='missing'))[1]
        self.assertIsNone(s['net_total_usd']);self.assertIn('unconditional_probability_mass_incomplete',s['reasons'])
        for key,value in [('winner:NFL:ATL','NaN'),('winner:NFL:ATL','1.1'),('winner:NFL:ATL','-0.1'),('winner:NFL:ATL','0.8'),('extra','0')]:
            x=inputs(model='complete');x['model']['probabilities'][key]=value
            with self.assertRaises(ValueError):evaluate(x)
        for key in ('target_hash','payouts_hash','basis','version','claimed_fair_value_usd'):
            x=inputs(model='complete');x['model'][key]='0.9'
            with self.assertRaises(ValueError):evaluate(x)
        x=inputs(model='complete');x['model']['probabilities']['canceled']=None
        self.assertIsNone(self.signals(x)[1]['net_total_usd'])
        x=inputs(model='complete');x['model']['probabilities']['canceled']='0'
        self.assertIn('unconditional_probability_mass_incomplete',self.signals(x)[1]['reasons'])

    def test_unknown_fees_not_imputed(self):
        x=inputs(model='complete');x['market']['contexts'][0][1].pop('balance_precision')
        s=self.signals(x);self.assertIsNone(s[0]['net_total_usd']);self.assertIsNone(s[1]['net_total_usd'])
        x=inputs(model='complete');x['market']['contexts'][1][1].pop('assume_no_settlement_fee')
        s=self.signals(x);self.assertIsNone(s[0]['net_total_usd']);self.assertEqual(Decimal(s[1]['net_total_usd']),Decimal('1.265'))
        x=inputs(model='complete');x['market']['contexts']=[]
        self.assertIsNone(self.signals(x)[1]['net_total_usd'])

    def test_quantity_unknown_constraints_and_consumed_depth(self):
        for q in (None,'0.5','9'):
            self.assertTrue(all(s['net_total_usd'] is None for s in self.signals(inputs(quantity=q,model='complete'))))
        for q in ('0','-1'):
            with self.assertRaises(ValueError):evaluate(inputs(quantity=q))
        s=self.signals(inputs(quantity='4',model='complete',levels=(('0.2','3'),('0.8','5'))))[1]
        # .6+.8 cost, .06 rounded fees minus .01 order rounding refund; 2.54-1.45=1.09.
        self.assertEqual(Decimal(s['net_total_usd']),Decimal('1.09'))
        self.assertEqual(Decimal(s['denominator_usd']),Decimal('1.45'))
        self.assertEqual(len(s['fee_audit']['context']['fills']),2)
        x=inputs();x['market']['books'][0]['observation']['units_verified']=False;reidentify(x['market']['books'][0])
        self.assertIsNone(self.signals(x)[0]['net_total_usd'])

    def test_fee_grouping_existing_pmus_cumulative_rules(self):
        a=evaluate(inputs(quantity='4',levels=(('0.2','3'),('0.8','5'))))
        legs=a.data['signals'][0]['conditional_calculation']['legs']
        # PMUS .06*(3*.2*.8 + 1*.8*.2)=.0384 rounds cumulatively to .04.
        self.assertEqual(Decimal(legs[1]['entry_fees']),Decimal('.04'))
        self.assertEqual(len({f['order_id'] for f in legs[1]['fee_audit']['context']['fills']}),1)

    def test_unknown_and_refund_exceptional_cashflows(self):
        x=alter_rule(inputs(),'unknown');s=self.signals(x)
        self.assertIsNone(s[0]['net_total_usd'])
        self.assertIsNone(s[0]['conditional_calculation']['outcomes']['canceled']['profit'])
        self.assertIsNotNone(s[0]['conditional_calculation']['minimum_known_profit'])
        x=alter_rule(inputs(),'refund');s=self.signals(x)
        case=s[1]['state_cashflows']['canceled']
        self.assertEqual(case['payout']['kind'],'refund')
        self.assertEqual(Decimal(case['cashflow']['gross_payout']),Decimal('.6'))
        self.assertEqual(Decimal(case['cashflow']['net_cashflow']),Decimal('-.04'))
        self.assertIsNone(s[1]['net_total_usd'])
        x=alter_rule(inputs(),'fraction','0');s=self.signals(x)
        self.assertIn('estimate_target_settlement_incompatible_or_unknown',s[1]['reasons'])
        self.assertEqual(Decimal(s[1]['state_cashflows']['canceled']['cashflow']['gross_payout']),0)

    def test_stale_books_diagnostics_retained_but_unranked(self):
        x=inputs(model='complete');b=x['market']['books'][0]
        b['observation']['quote']['raw']['received_at']='2026-09-13T16:59:09+00:00'
        b['observation']['quote']['raw']['exchange_at']='2026-09-13T16:59:09+00:00';reidentify(b)
        a=evaluate(x)
        self.assertTrue(all(s['net_total_usd'] is None for s in a.data['signals']))
        self.assertIsNotNone(a.data['signals'][0]['conditional_calculation']['worst_case_profit'])
        self.assertEqual(rank([a])['groups'],[])

    def test_late_receipt_estimate_and_knowledge_rejected(self):
        for scope in ('book','market','sizing','model','receipt','nested'):
            x=inputs(model='complete');future='2026-09-13T16:59:41+00:00'
            if scope=='book':x['market']['books'][0]['known_at']=future;reidentify(x['market']['books'][0])
            elif scope=='receipt':x['market']['books'][0]['observation']['quote']['raw']['received_at']=future;reidentify(x['market']['books'][0])
            elif scope=='nested':x['market']['contexts'][0][1]['reviewed_at']=future
            else:x[scope]['known_at']=future
            with self.subTest(scope=scope),self.assertRaises(ValueError):evaluate(x)
        x=inputs();x['as_of']='2026-09-13T16:59:39+00:00'
        with self.assertRaises(ValueError):evaluate(x)

    def test_freshness_equality_and_source_clock(self):
        x=inputs();b=x['market']['books'][0]
        for book in x['market']['books']:
            for k in ('received_at','exchange_at'): book['observation']['quote']['raw'][k]='2026-09-13T16:59:10+00:00'
            reidentify(book)
        reidentify(b);self.assertIsNotNone(self.signals(x)[0]['net_total_usd'])
        b['observation']['quote']['raw']['exchange_at']='2026-09-13T16:59:11+00:00';reidentify(b)
        with self.assertRaises(ValueError):evaluate(x)

    def test_exact_submicrosecond_receipt_source_and_skew(self):
        x=inputs();b=x['market']['books'][0]
        b['observation']['quote']['raw']['received_at']='2026-09-13T16:59:40.000000001+00:00';reidentify(b)
        with self.assertRaises(ValueError):evaluate(x)
        x=inputs();b=x['market']['books'][0]
        b['observation']['quote']['raw']['exchange_at']='2026-09-13T16:59:40.000000001+00:00';reidentify(b)
        with self.assertRaises(ValueError):evaluate(x)
        x=inputs()
        for b in x['market']['books']:
            for k in ('received_at','exchange_at'):b['observation']['quote']['raw'][k]='2026-09-13T16:59:09.999999999+00:00'
            reidentify(b)
        self.assertIsNone(self.signals(x)[0]['net_total_usd'])
        x=inputs();b=x['market']['books'][0]
        for k in ('received_at','exchange_at'):b['observation']['quote']['raw'][k]='2026-09-13T16:59:34+00:00'
        reidentify(b);self.assertIn('book_receipt_skew_exceeded',self.signals(x)[0]['reasons'])

    def test_ranking_separate_classes_unknowns_and_overlap(self):
        a=evaluate(inputs(model='complete'));b=evaluate(inputs(price='0.8',model='complete'));u=evaluate(inputs())
        r=rank([a,b,u,a]);self.assertIsNone(r['aggregate_attainable_profit_usd']);self.assertEqual(len(r['unavailable']),1)
        self.assertEqual(len(r['groups']),2)
        ev=next(g for g in r['groups'] if g['basis'][0]=='mispricing')
        self.assertEqual([row['audit_id'] for row in ev['rows']],[a.id,b.id])
        self.assertEqual(ev['rows'][0]['liquidity_families'],ev['rows'][1]['liquidity_families'])
        c=evaluate(inputs(quantity='4',model='complete'))
        self.assertEqual(len(rank([a,c])['groups']),4)

    def test_mutations_missing_dependency_and_versions(self):
        a=evaluate(inputs());bad=a.data;bad['signals'][0]['net_total_usd']='100'
        with self.assertRaises(ValueError):replay(Audit(packed(bad)))
        bad=a.data;bad['inputs']['market']['books'][0]['levels'][0][0]='0.1'
        with self.assertRaises(ValueError):replay(Audit(packed(bad)))
        x=inputs();x['policy']['version']='future'
        with self.assertRaises(ValueError):evaluate(x)
        x=inputs();x['market']['books']=[]
        with self.assertRaises(ValueError):evaluate(x)
        x=inputs();x['market']['books']*=2
        with self.assertRaises(ValueError):evaluate(x)
        x=inputs();x['market']['books'][0]['observation']['quote']['raw']['ref']['venue']='pinnacle'
        reidentify(x['market']['books'][0])
        with self.assertRaises(ValueError):evaluate(x)

    def test_decimal_context_independence(self):
        x=inputs(model='complete');a=evaluate(x)
        with localcontext() as c:
            c.prec=6;c.rounding='ROUND_DOWN'
            self.assertEqual(evaluate(x),a)

    def test_all_saved_e3_estimates_replay_unchanged(self):
        root=Path('evidence/e3/durable')
        for n in range(6):
            e=estimate_restore((root/f'estimate-{n}.json').read_text())
            a=evaluate(inputs(estimate=e))
            self.assertIsNone(a.data['signals'][1]['net_total_usd'])
            self.assertEqual(a.data['inputs']['estimate'],e.export())

if __name__=='__main__':unittest.main()
