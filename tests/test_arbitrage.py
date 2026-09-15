"""Independent cashflow oracles; wholly synthetic data and offline capture replay."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext, ROUND_UP, Inexact
import unittest

from app.arbitrage import (Policy, detect, book_observations, common_quantity,
                           eligibility, sizing, total)
from app.arbitrage_example import synthetic_inputs, evaluate_fixture, selected, NOW, historical
from app.adapters.kalshi import book_from_levels
from app.models.core import (BookSync, Depth, MarketState, Quantity, Probability,
                            EvidenceKind, Venue, NativeRef)
from app.matching_example import synthetic
from app.moneyline import observe
from app.settlement import SCENARIOS


class DetectorTests(unittest.TestCase):
    def setUp(self): self.data=synthetic_inputs()
    def result(self,**kwargs): return evaluate_fixture(self.data,**kwargs)
    def candidate(self,**kwargs): return selected(self.result(**kwargs))
    def calculation(self,**kwargs): return self.candidate(**kwargs)['conditional_calculation']
    def alter(self,idx=0,**changes): self.data[2][idx]=replace(self.data[2][idx],**changes)
    def time(self,idx=0,age=0,source_age=None):
        o=self.data[2][idx]
        self.alter(idx,quote=replace(o.quote,raw=replace(o.quote.raw,
            received_at=NOW-timedelta(seconds=age),exchange_at=NOW-timedelta(seconds=age if source_age is None else source_age))))

    def test_independent_outcome_arithmetic(self):
        c=self.calculation()
        # 100*.4*2 = 80; Kalshi .07*100*.4*.6=1.68;
        # PMUS .06*100*.4*.6=1.44; every modeled outcome pays 100.
        self.assertEqual(Decimal(c['acquisition_cost']),Decimal('80'))
        self.assertEqual(Decimal(c['entry_fees']),Decimal('3.12'))
        self.assertEqual(Decimal(c['entry_cash_requirement']),Decimal('83.12'))
        for o in c['outcomes'].values():
            self.assertEqual(Decimal(o['profit']),Decimal('16.88'))
            self.assertEqual(Decimal(o['net_payout']),Decimal('100'))
        self.assertEqual(Decimal(c['worst_case_profit']),Decimal('16.88'))
        self.assertEqual(c['roi_denominator_cash_required'],c['entry_cash_requirement'])
        self.assertAlmostEqual(float(c['worst_case_roi']),16.88/83.12)

    def test_zero_and_negative_roi(self):
        c=self.calculation(policy=Policy(execution_reserve_usd='16.88'))
        self.assertEqual(Decimal(c['worst_case_roi']),0)
        self.assertFalse(self.candidate(policy=Policy(execution_reserve_usd='16.88'))['qualified_modeled_arbitrage'])
        c=self.calculation(policy=Policy(execution_reserve_usd='17'))
        self.assertLess(Decimal(c['worst_case_roi']),0)

    def test_negative_case_rounding_independent(self):
        self.data=synthetic_inputs('0.55','0.55')
        # Notional 110; Kalshi .07*100*.55*.45=1.7325 -> cash fee 1.74;
        # PMUS .06*100*.55*.45=1.485 -> half-even 1.48.
        self.assertEqual(Decimal(self.calculation()['worst_case_profit']),Decimal('-13.22'))

    def test_fee_eliminates_raw_gap(self):
        self.data=synthetic_inputs('0.49','0.49')
        c=self.candidate()
        self.assertEqual(Decimal(c['pricing_diagnostic']['unit_payout_reference_gap']),Decimal('.02'))
        # 98 + ceil-to-cent(1.7493) + round-half-even(1.4994)=101.25.
        self.assertEqual(Decimal(c['conditional_calculation']['worst_case_profit']),Decimal('-1.25'))

    def test_exceptional_outcomes_retained(self):
        self.data=synthetic_inputs(exception='0')
        c=self.calculation()
        self.assertEqual(Decimal(c['worst_case_profit']),Decimal('-83.12'))
        self.assertEqual(Decimal(c['outcomes']['tie']['profit']),Decimal('-83.12'))
        self.assertEqual(Decimal(c['minimum_known_profit']),Decimal('-83.12'))

    def test_unknown_is_not_zero(self):
        self.assertIsNone(total(['0',None]))
        self.assertEqual(total(['0','0']),0)
        self.data[3].clear()
        c=self.calculation()
        self.assertIsNone(c['entry_fees']); self.assertIsNone(c['worst_case_profit'])
        self.assertEqual(Decimal(c['acquisition_cost']),80)

    def test_fee_conditions_never_bypassed(self):
        c=self.candidate(); calc=c['conditional_calculation']
        self.assertFalse(c['qualified_modeled_arbitrage'])
        self.assertTrue(any('FCM' in r for r in c['reasons']))
        self.assertTrue(any('independent settlement fee' in r for r in c['reasons']))
        self.assertTrue(all(f['engine']=='fees-1' for f in calc['fee_audits']))

    def test_unknown_settlement_charge(self):
        next(c for c in self.data[3].values() if c['venue']=='polymarket_us').pop('assume_no_settlement_fee')
        c=self.calculation()
        self.assertEqual(Decimal(c['entry_cash_requirement']),Decimal('83.12'))
        self.assertIsNone(c['worst_case_profit'])
        self.assertTrue(all(o['profit'] is None for o in c['outcomes'].values()))

    def test_missing_account_context(self):
        next(c for c in self.data[3].values() if c['venue']=='kalshi').pop('balance_precision')
        c=self.candidate()
        self.assertIsNone(c['conditional_calculation']['entry_fees'])
        self.assertTrue(any('balance_precision' in r for r in c['reasons']))

    def test_misscoped_fee_context(self):
        next(iter(self.data[3].values()))['market_id']='different'
        self.assertTrue(any('identity-mismatch' in r for r in self.candidate()['reasons']))

    def test_explicit_single_fill_grouping(self):
        p,m,o,c,_=self.data
        r=detect(p,m,o,c,evaluation_time=NOW)
        self.assertTrue(all(x['conditional_calculation'] is None for x in r['candidates']))
        self.assertTrue(any('explicit-fill-grouping-required' in x['reasons'] for x in r['candidates']))
        f=self.calculation()['fee_audits'][0]['context']['fills']
        self.assertEqual(len(f),1); self.assertEqual(f[0]['role'],'taker')

    def test_bids_not_acquisition_asks(self):
        o=self.data[2][0]; self.alter(quote=replace(o.quote,ask=None))
        r=self.result()
        self.assertTrue(all(c['conditional_calculation'] is None for c in r['candidates']))
        self.assertTrue(all(c['pricing_diagnostic']['ask_sum'] is None for c in r['candidates']))

    def test_adapter_yes_no_direction_and_size(self):
        o=self.data[2][0]
        b=book_from_levels(o.quote.raw,{'yes':{Decimal('.8'):Decimal('3')},'no':{Decimal('.7'):Decimal('5')}},
            sync=BookSync.SYNCHRONIZED,depth=Depth.PARTIAL)
        quotes=book_observations(b,environment='synthetic',evidence_class='synthetic',source_time_semantics='snapshot')
        d={x.quote.outcome_id:x.quote for x in quotes}
        self.assertEqual(d['yes'].ask.price.value,Decimal('.3'))
        self.assertEqual(d['yes'].ask.quantity.value,5)
        self.assertEqual(d['no'].ask.price.value,Decimal('.2'))
        self.assertEqual(d['no'].ask.quantity.value,3)

    def test_exposure_direction(self):
        c=self.candidate(); self.assertEqual([l['side'] for l in c['legs']],['yes','b'])
        self.assertTrue(c['relationship']['opposing_sporting_outcomes'])
        self.assertFalse(c['relationship']['same_exposure'])

    def test_visible_size_and_common_grid(self):
        self.alter(increment='3',minimum='3')
        self.alter(1,increment='2',minimum='2')
        self.assertEqual(Decimal(self.calculation()['quantity']),96)
        self.assertEqual(common_quantity([(Decimal('5'),Decimal('6'),Decimal('2'))]*2),0)

    def test_hypothetical_quantity_cannot_qualify_beyond_size(self):
        c=self.candidate(quantity='101')
        self.assertFalse(c['qualified_modeled_arbitrage'])
        self.assertTrue(any('quantity-outside' in r for r in c['reasons']))
        self.assertEqual(c['conditional_calculation']['quantity_mode'],'hypothetical')

    def test_hypothetical_unknown_size_still_calculates(self):
        self.alter(units_verified=False)
        self.assertTrue(all(c['conditional_calculation'] is None for c in self.result()['candidates']))
        c=self.candidate(quantity='10')
        self.assertTrue(any('rules-unknown' in r for r in c['reasons']))
        self.assertEqual(Decimal(c['conditional_calculation']['quantity']),10)

    def test_unit_conversion_is_explicit(self):
        o=self.data[2][0]
        q=replace(o.quote,raw=replace(o.quote.raw,ref=replace(o.quote.raw.ref,venue=Venue.NOVIG)),
            ask=replace(o.quote.ask,quantity=Quantity(value=Decimal('100'),unit='payout_cents')))
        s=sizing(replace(o,quote=q,minimum='1',increment='1'))
        self.assertEqual(s,(Decimal('1'),Decimal('.01'),Decimal('.01')))
        self.assertIsNone(sizing(replace(o,quote=replace(q,raw=o.quote.raw))))

    def test_unknown_units_rejected(self):
        o=self.data[2][0]
        self.alter(quote=replace(o.quote,ask=replace(o.quote.ask,quantity=Quantity(value=Decimal(100),unit='USD_stake'))))
        self.assertTrue(all(c['conditional_calculation'] is None for c in self.result()['candidates']))

    def test_minimum_and_increment_validation(self):
        for value in ('0','-1'):
            self.alter(increment=value)
            with self.assertRaises(ValueError): self.result()
        for q in ('0','-1','NaN',0.1):
            with self.assertRaises(ValueError): self.result(quantity=q)

    def test_freshness_inclusive_boundary(self):
        self.time(age=30); self.time(1,age=30)
        self.assertFalse(any('stale-' in r for r in self.candidate()['reasons']))
        self.time(age=30.000001)
        self.assertTrue(any('stale-receipt' in r for r in self.candidate()['reasons']))

    def test_skew_inclusive_boundary(self):
        self.time(age=5)
        self.assertNotIn('cross-leg-observation-skew',self.candidate()['reasons'])
        self.time(age=5.000001)
        self.assertIn('cross-leg-observation-skew',self.candidate()['reasons'])

    def test_recent_receipt_cannot_clear_source_problem(self):
        self.alter(source_time_problem='earlier regression',source_time_progress='advanced')
        self.assertTrue(any('earlier regression' in r for r in self.candidate()['reasons']))
        self.alter(source_time_progress='regressed')
        self.assertTrue(any('regressed' in r for r in self.candidate()['reasons']))

    def test_quiet_last_change_is_not_disconnection(self):
        self.time(source_age=9999); self.alter(source_time_semantics='last_change')
        self.assertFalse(any('stale-source' in r for r in self.candidate()['reasons']))
        self.alter(source_time_semantics='snapshot')
        self.assertTrue(any('stale-source' in r for r in self.candidate()['reasons']))

    def test_future_receipt_and_source(self):
        self.time(age=-1)
        self.assertTrue(any('receipt-in-future' in r for r in self.candidate()['reasons']))
        self.time(age=0,source_age=-1)
        self.assertTrue(any('ahead-of-receipt' in r for r in self.candidate()['reasons']))

    def test_status_lock_and_sync(self):
        for changes,reason in [({'locks_clear':False},'locked'),({'sync':'unsynchronized'},'reconstruction'),({'depth':'unknown'},'depth-unknown')]:
            self.data=synthetic_inputs(); self.alter(**changes)
            self.assertTrue(any(reason in r for r in self.candidate()['reasons']))
        self.alter(quote=replace(self.data[2][0].quote,state=MarketState.CLOSED))
        self.assertTrue(any('market-closed' in r for r in self.candidate()['reasons']))

    def test_maker_deferred_not_calculated(self):
        self.alter(role='maker')
        self.assertTrue(all(c['conditional_calculation'] is None for c in self.result()['candidates']))
        self.assertTrue(any(any('maker-dependent' in r for r in c['reasons']) for c in self.result()['candidates']))

    def test_environment_isolation(self):
        self.alter(environment='production')
        self.assertTrue(all(c['conditional_calculation'] is None for c in self.result()['candidates']))

    def test_synthetic_is_never_current(self):
        r=self.result()
        self.assertEqual(self.candidate()['scope'],'synthetic')
        self.assertEqual(r['summary']['current_production'],0)
        self.alter(evidence_class='current')
        self.assertTrue(any('mismatch' in r for r in self.candidate()['reasons']))

    def test_deduplication_and_stable_id(self):
        first=self.result()
        self.data[2].extend(deepcopy(self.data[2])); self.data[2].reverse()
        self.assertEqual(first,self.result())
        self.time(age=1)
        self.assertEqual([c['id'] for c in first['candidates']],[c['id'] for c in self.result()['candidates']])

    def test_conflicting_duplicate_fails_closed(self):
        o=self.data[2][0]
        self.data[2].append(replace(o,quote=replace(o.quote,ask=replace(o.quote.ask,price=Probability(value=Decimal('.3'))))))
        self.assertTrue(all(c['conditional_calculation'] is None for c in self.result()['candidates']))
        self.assertTrue(any(any('conflicting-observations' in r for r in c['reasons']) for c in self.result()['candidates']))

    def test_policy_validation_and_filters(self):
        for v in ('-1','NaN',True):
            with self.assertRaises(ValueError): Policy(min_roi=v)
        c=self.candidate(policy=Policy(min_profit_usd='17'))
        self.assertFalse(c['passes_reporting_thresholds'])
        self.assertEqual(Decimal(c['conditional_calculation']['worst_case_profit']),Decimal('16.88'))

    def test_decimal_context_isolation(self):
        original=self.result()
        with localcontext() as c:
            c.prec=2; c.rounding=ROUND_UP; c.traps[Inexact]=True
            self.assertEqual(original,self.result())

    def test_replay_time_is_deterministic(self):
        self.assertEqual(self.result(),self.result())
        p,m,o,c,_=self.data
        with self.assertRaises(ValueError): detect(p,m,o,c,evaluation_time=NOW.replace(tzinfo=None))
        later=detect(p,m,o,c,evaluation_time=NOW+timedelta(seconds=31),fill_grouping='single_fill_per_leg')
        self.assertTrue(any('stale-receipt' in r for r in selected(later)['reasons']))

    def test_current_parent_revision_invalidates(self):
        before=self.candidate()
        parents=self.data[0]
        parents.ingest([synthetic('ka',Venue.KALSHI,names=('Atlanta Falcons','Pittsburgh Steelers'),league='NFL',status='canceled')])
        r=self.result()
        self.assertFalse(any(c['qualified_modeled_arbitrage'] for c in r['candidates']))
        self.assertNotEqual(before['parent_snapshot_hash'],r['matching']['parent_snapshot_hash'])
        self.assertTrue(r['withdrawn'] or any(not c['structural_match'] for c in r['matching']['pairs'].values()))

    def test_current_rule_revision_invalidates(self):
        p,m,obs,c,rows=self.data
        before=self.candidate()
        # A changed profile without a fresh native rule binding is rejected by the existing matcher.
        from app.matching import digest
        row=deepcopy(rows[0]); row['profile']['dimensions']['resumption']={'value':None,'evidence':None,'reason':'changed unknown rule','certainty':'exact'}
        row['profile']['hash']=digest({k:v for k,v in row['profile'].items() if k!='hash'})
        row['hash']=digest({k:v for k,v in row.items() if k!='hash'})
        m.update(p,[row,rows[1]])
        after=self.candidate()
        self.assertEqual(before['id'],after['id'])
        self.assertGreater(after['pair_revision'],before['pair_revision'])
        self.assertEqual(after['settlement']['status'],'UNKNOWN')
        self.assertFalse(after['qualified_modeled_arbitrage'])

    def test_unknown_outcome_keeps_known_unfavorable_minimum(self):
        self.data=synthetic_inputs(exception='0')
        p,m,_,_,rows=self.data
        from app.matching import digest
        row=deepcopy(rows[0]); row['profile']['payouts']['canceled']={'kind':'unknown','reason':'fixture uncertainty'}
        row['profile']['hash']=digest({k:v for k,v in row['profile'].items() if k!='hash'})
        row['hash']=digest({k:v for k,v in row.items() if k!='hash'})
        m.update(p,[row,rows[1]])
        c=self.calculation()
        self.assertIsNone(c['worst_case_profit'])
        self.assertEqual(Decimal(c['minimum_known_profit']),Decimal('-83.12'))
        self.assertIsNone(c['outcomes']['canceled']['profit'])
        self.assertEqual(Decimal(c['outcomes']['tie']['profit']),Decimal('-83.12'))

    @staticmethod
    def documented_fee_fixture(context, registry=None):
        # Deliberate qualification-unit-test stub, not a venue fee model or
        # integration oracle. Real-engine arithmetic is tested separately above.
        q=Decimal(context['fills'][0]['quantity']); p=Decimal(context['fills'][0]['price'])
        return {'qualification':'documented_scenario','entry_cash_requirement':str(q*p),
                'entry_fees':'0','unsupported':[],'assumptions':[],
                'outcomes':{k:{'net_payout':str(q*Decimal(v)),
                    'net_cashflow':str(q*(Decimal(v)-p)),'settlement_fee':'0'}
                    for k,v in context['outcomes'].items()},
                'scope':'SYNTHETIC zero-fee eligibility stub, not venue evidence'}

    def test_qualified_synthetic_branch_stays_nonproduction(self):
        from unittest.mock import patch
        self.data=synthetic_inputs(environment='production')
        with patch('app.arbitrage.calculate',side_effect=self.documented_fee_fixture):
            c=self.candidate()
        self.assertTrue(c['qualified_modeled_arbitrage'])
        self.assertEqual(Decimal(c['conditional_calculation']['worst_case_profit']),Decimal('20'))
        self.assertEqual(c['scope'],'synthetic')
        self.assertFalse(c['current_production_opportunity'])

    def test_nonpositive_denominator_is_not_roi(self):
        from unittest.mock import patch
        def zero_cash(context,registry=None):
            f=self.documented_fee_fixture(context,registry)
            f['entry_cash_requirement']='0'
            return f
        with patch('app.arbitrage.calculate',side_effect=zero_cash):
            c=self.candidate()
        self.assertIsNone(c['conditional_calculation']['worst_case_roi'])
        self.assertIn('nonpositive-cash-required-denominator',c['reasons'])
        self.assertFalse(c['qualified_modeled_arbitrage'])

    def test_historical_production_coverage(self):
        r=historical()
        self.assertEqual(len(r['matching']['pairs']),10)
        self.assertTrue(all(p['settlement']['status']=='UNKNOWN' for p in r['matching']['pairs'].values()))
        self.assertEqual(r['summary']['current_production'],0)
        priced=[c for c in r['candidates'] if c['pricing_diagnostic']['ask_sum'] is not None]
        self.assertTrue(priced)
        self.assertTrue(all(c['scope']=='historical' for c in priced))
        self.assertTrue(any(c['pricing_diagnostic']['ask_sum'] is None for c in r['candidates']))

if __name__=='__main__': unittest.main()
