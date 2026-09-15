import unittest
from copy import deepcopy
from decimal import Decimal, localcontext, ROUND_DOWN, Inexact
from app.fees import calculate, replay, Registry, load_registry
from app.fees.engine import kalshi_terms, rounded, D
from app.fee_example import scenario, examples


class FeeTests(unittest.TestCase):
    def test_official_and_paired_examples(self):
        self.assertGreaterEqual(len(examples()),26)

    def test_decimal_context_independent(self):
        c=scenario('novig','live','0.123','12345.67')
        expected=calculate(c)
        with localcontext() as ctx:
            ctx.prec=2; ctx.rounding=ROUND_DOWN; ctx.traps[Inexact]=True
            self.assertEqual(calculate(c),expected)

    def test_floats_and_nonfinite(self):
        for bad in (0.5,'NaN','Infinity','-Infinity',True,'1e100'):
            c=scenario(); c['fills'][0]['price']=bad
            with self.assertRaises(ValueError): calculate(c)

    def test_bad_inputs(self):
        for key,bad in [('price','0'),('price','1'),('quantity','-1'),('unit','stake'),('role','unknown')]:
            c=scenario(); c['fills'][0][key]=bad
            with self.assertRaises(ValueError): calculate(c)

    def test_timezone(self):
        c=scenario(); c['trade_time']='2026-09-12T00:00:00'
        with self.assertRaises(ValueError): calculate(c)

    def test_duplicate_and_incomplete_history(self):
        c=scenario(); c['fills']*=2
        with self.assertRaises(ValueError): calculate(c)
        c=scenario(); c['complete_order_history']=False
        self.assertIsNone(calculate(c)['entry_fees'])

    def test_pmus_cumulative_can_only_reduce(self):
        c=scenario(price='0.05',quantity='1') # .00285 per fill rounds zero; total .0057 rounds .01
        c['fills'].append(dict(c['fills'][0],fill_id='f2'))
        self.assertEqual(D(calculate(c)['entry_fees']),D('0'))

    def test_pmus_maker_per_fill(self):
        c=scenario(quantity='1',role='maker')
        c['fills'].append(dict(c['fills'][0],fill_id='f2'))
        r=calculate(c)
        self.assertEqual(D(r['credits'][0]['amount']),D('0'))
        self.assertEqual(D(r['entry_cash_requirement']),D('1'))

    def test_round_half_even(self):
        self.assertEqual(rounded(D('.025'),D('.01'),'ROUND_HALF_EVEN'),D('.02'))
        self.assertEqual(rounded(D('.035'),D('.01'),'ROUND_HALF_EVEN'),D('.04'))

    def test_kalshi_official_fractional_example(self):
        # p=.055, q=1 gives model .00363825 independently of engine.
        c=scenario('kalshi',price='0.055',quantity='1')
        r=calculate(c); f=r['trace'][0]
        self.assertEqual(D(f['raw']),D('.00363825'))
        self.assertEqual(D(f['trade_fee']),D('.003639'))
        self.assertEqual(D(f['rounding_fee']),D('.001361'))
        self.assertEqual(D(r['entry_cash_requirement']),D('.06'))

    def test_kalshi_precision(self):
        c=scenario('kalshi',price='0.055',quantity='1'); c['balance_precision']='0.0001'
        self.assertEqual(D(calculate(c)['entry_cash_requirement']),D('.0587'))
        c['balance_precision']='0.001'
        self.assertIsNone(calculate(c)['entry_fees'])

    def test_kalshi_accumulator_mixed_roles_and_cap(self):
        c=scenario('kalshi',price='0.50',quantity='1')
        c['fills']=[dict(c['fills'][0],fill_id=str(i),role='maker' if i%2 else 'taker') for i in range(8)]
        r=calculate(c)
        self.assertGreater(sum(D(f['rounding_refund']) for f in r['trace']),D('0'))
        for f in r['trace']:
            self.assertGreaterEqual(D(f['trade_fee'])+D(f['rounding_fee'])-D(f['rounding_refund']),D('0'))
        separate=deepcopy(c)
        for f in separate['fills']: f['order_id']=f['fill_id']
        self.assertGreater(D(calculate(separate)['entry_cash_requirement']),D(r['entry_cash_requirement']))

    def test_kalshi_roles(self):
        for typ,expected in [('quadratic','0'),('quadratic_with_maker_fees','.44'),('quadratic_with_combo_maker_fees','.88')]:
            c=scenario('kalshi',quantity='100',role='maker'); c['kalshi_metadata']['series_changes'][0]['fee_type']=typ
            self.assertEqual(D(calculate(c)['entry_fees']),D(expected))

    def test_overrides_independent_null_clearing(self):
        c=scenario('kalshi'); m=c['kalshi_metadata']
        m['event_changes']=[dict(scheduled_ts='2026-08-01T00:00:00Z',fee_type_override='quadratic',fee_multiplier_override='2'),dict(scheduled_ts='2026-09-01T00:00:00Z',fee_type_override=None,fee_multiplier_override='0.5'),dict(scheduled_ts='2026-10-01T00:00:00Z',fee_type_override=None,fee_multiplier_override=None)]
        self.assertEqual(kalshi_terms(c,'2026-08-01T00:00:00Z'),dict(fee_type='quadratic',fee_multiplier='2'))
        self.assertEqual(kalshi_terms(c,'2026-09-01T00:00:00Z'),dict(fee_type='quadratic_with_maker_fees',fee_multiplier='0.5'))
        self.assertEqual(kalshi_terms(c,'2026-10-01T00:00:00Z'),dict(fee_type='quadratic_with_maker_fees',fee_multiplier='1'))

    def test_ambiguous_overrides(self):
        c=scenario('kalshi'); m=c['kalshi_metadata']; m['series_changes']*=2
        self.assertEqual(calculate(c)['qualification'],'unsupported')

    def test_flat_unknown_and_wrong_scope(self):
        c=scenario('kalshi'); c['kalshi_metadata']['series_changes'][0]['fee_type']='flat'
        self.assertIsNone(calculate(c)['entry_fees'])
        c=scenario('kalshi'); c['kalshi_metadata']['event_id']='other'
        self.assertIsNone(calculate(c)['entry_fees'])

    def test_schedule_boundaries_and_overlap(self):
        data=load_registry().data
        row=next(r for r in data['schedules'] if r['venue']=='polymarket_us')
        row['effective_to']='2026-10-01T00:00:00Z'
        new=dict(row,version='synthetic-future',effective_from=row['effective_to'],effective_to=None,coefficient='0.08')
        data['schedules'].append(new); reg=Registry(data)
        c=scenario(); c.pop('schedule_version'); c['trade_time']='2026-10-01T00:00:00Z'
        self.assertEqual(calculate(c,reg)['schedule']['version'],'synthetic-future')
        c['trade_time']='2026-09-30T23:59:59.999999Z'
        self.assertEqual(calculate(c,reg)['schedule']['version'],'pmus-2026-07-01')
        new['effective_from']='2026-09-01T00:00:00Z'
        with self.assertRaises(ValueError): Registry(data)

    def test_unknown_effective_requires_pin(self):
        c=scenario('novig','live'); c.pop('schedule_version')
        self.assertIsNone(calculate(c)['schedule'])

    def test_replay_independent_future_registry(self):
        r=calculate(scenario()); data=load_registry().data
        data['schedules'][1]['coefficient']='0.99'
        self.assertEqual(replay(r),r)
        tampered=deepcopy(r); tampered['entry_fees']='0'
        with self.assertRaises(ValueError): replay(tampered)
        tampered=deepcopy(r); tampered['registry']['schema']=2
        with self.assertRaises(ValueError): replay(tampered)

    def test_novig_unit_and_minimum(self):
        c=scenario('novig','live',quantity='1'); c['fills'][0]['unit']='payout_cents'
        self.assertEqual(D(calculate(c)['entry_fees']),D('.00008'))
        c['fills'][0]['quantity']='0.1'
        with self.assertRaises(ValueError): calculate(c)

    def test_novig_futures_and_exemptions(self):
        c=scenario('novig','futures','0.15','100')
        self.assertEqual(D(calculate(c)['entry_fees']),D('.765'))
        c['sport']='golf'
        self.assertEqual(D(calculate(c)['entry_fees']),D('0'))

    def test_novig_credit_separate(self):
        c=scenario('novig','live',role='maker',quantity='100'); c.update(maker_credit_eligible=True,counterparty_fee_retained='.75')
        r=calculate(c)
        self.assertEqual(D(r['credits'][0]['unrounded']),D('.375'))
        self.assertEqual(D(r['entry_cash_requirement']),D('50'))
        self.assertIsNone(r['credits'][0]['amount'])

    def test_novig_parlay_api_restriction(self):
        c=scenario('novig','parlay'); c['channel']='api'
        self.assertIsNone(calculate(c)['entry_fees'])
        c['fills'][0]['role']='maker'
        self.assertEqual(D(calculate(c)['entry_fees']),D('0'))

    def test_prophetx_market_netting(self):
        c=scenario('prophetx','straight'); c['fills']=[]
        c['market_cashflows']=dict(market_id=c['market_id'],stake_usd='70',gross_payouts={'a':'100','b':'60','push':'70'},complete_market=True)
        r=calculate(c)
        self.assertEqual(D(r['outcomes']['a']['settlement_fee_unrounded']),D('.60'))
        self.assertIsNone(r['outcomes']['a']['net_payout'])
        self.assertEqual(D(r['outcomes']['b']['settlement_fee']),D('0'))
        self.assertEqual(D(r['outcomes']['push']['settlement_fee']),D('0'))

    def test_prophetx_native_forbidden(self):
        self.assertIsNone(calculate(scenario('prophetx','straight'))['entry_fees'])

    def test_unknown_settlement_not_zero(self):
        r=calculate(scenario())
        self.assertIsNone(r['outcomes']['win']['settlement_fee'])
        self.assertEqual(r['settlement_status'],'UNKNOWN')
        c=scenario(); c['assume_no_settlement_fee']=True
        self.assertEqual(calculate(c)['qualification'],'conditional')

    def test_no_assumed_volume_rebate(self):
        r=calculate(scenario()); self.assertIsNone(r['credits'][1]['amount'])
        c=scenario(); c['taker_rebate_rate']='0.25'
        r=calculate(c); self.assertEqual(D(r['credits'][1]['unrounded']),D('3.75'))
        self.assertEqual(D(r['entry_cash_requirement']),D('515'))

    def test_input_mutation_and_sell(self):
        c=scenario(); r=calculate(c); c['market_id']='changed'
        self.assertNotEqual(r['context']['market_id'],c['market_id'])
        c['action']='sell'; self.assertIsNone(calculate(c)['entry_fees'])

    def test_prophetx_marginal_rebate_not_top_tier(self):
        c=scenario('prophetx','straight'); c['fills']=[]
        c['market_cashflows']=dict(market_id=c['market_id'],stake_usd='40',gross_payouts={'win':'100'},complete_market=True)
        c['monthly_rebate_context']=dict(make_volume_usd='75000',fees_paid_usd='1000')
        r=calculate(c)
        self.assertTrue(r['credits'][0]['unrounded'].startswith('66.6666'))
        self.assertIsNone(r['credits'][0]['amount'])
        self.assertEqual(D(r['entry_cash_requirement']),D('40'))

    def test_chronology_and_scope(self):
        c=scenario(); c['fills'][0]['market_id']='wrong'
        with self.assertRaises(ValueError): calculate(c)
        c=scenario(); c['fills'][0]['trade_time']='2026-09-11T23:00:00Z'
        c['fills'].append(dict(c['fills'][0],fill_id='f2',trade_time='2026-09-11T22:00:00Z'))
        with self.assertRaises(ValueError): calculate(c)

    def test_pmus_fractional_unsupported(self):
        c=scenario(quantity='0.5')
        self.assertIn('whole contracts',calculate(c)['unsupported'][0])

    def test_kalshi_change_inside_order(self):
        c=scenario('kalshi',quantity='100')
        c['fills'][0]['trade_time']='2026-09-11T23:00:00Z'
        c['fills'].append(dict(c['fills'][0],fill_id='f2',trade_time=c['trade_time']))
        c['kalshi_metadata']['event_changes']=[dict(scheduled_ts=c['trade_time'],fee_type_override=None,fee_multiplier_override='0.5')]
        r=calculate(c)
        self.assertEqual(D(r['trace'][0]['raw']),D('1.75'))
        self.assertEqual(D(r['trace'][1]['raw']),D('.875'))

    def test_unknown_schedule_cannot_silently_select_known(self):
        data=load_registry().data
        data['schedules'].append(dict(data['schedules'][1],version='unknown-new',effective_from=None))
        c=scenario(); c.pop('schedule_version')
        self.assertIsNone(calculate(c,Registry(data))['schedule'])
        data['schema']=2
        with self.assertRaises(ValueError): Registry(data)

    def test_native_change_scope(self):
        c=scenario('kalshi')
        c['kalshi_metadata']['series_changes'][0]['series_ticker']='WRONG'
        self.assertIn('scope mismatch',calculate(c)['unsupported'][0])
