"""S01 independent exact diagnostic vectors and authentic retained arithmetic."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from fractions import Fraction as F
import json
from pathlib import Path
import unittest

from app.comparison.benchmark import TwoWayBenchmark, SportsbookOutcome
from app.comparison.current_dependencies import digest, instant, references
from app.comparison.domain import EvidenceReference, ExactNumber, Price
from app.comparison.estimated_policy import DEFAULT_POLICY, LEGACY_POLICY, EstimatePolicy, EstimateResult
from app.comparison.estimated_ev import evaluate as single, compact as single_compact, _reference
from app.comparison.estimated_pair import Leg, evaluate as pair_eval, compact as pair_compact
from app.comparison.effective_policy import effective_policy
from tests.test_ev05_funded import vector, bind
from tests.test_ev06_pairs import pair, exact_example
from tests.test_ev04_content import AT

FIXTURE=Path(__file__).parent/'fixtures/ev09-s01-retained.json'


def retained(policy=DEFAULT_POLICY, continuous=False):
    saved=json.loads(FIXTURE.read_text());state=saved['state'];event=state['events'][0];group=event['groups'][0]
    profiles=state['comparison_profiles'];at=instant(saved['as_of'])
    qs=[o['quotes']['novig'] for o in group['outcomes']]
    if continuous:
        for q in qs:
            bind(q,profiles,'quantity',dict(grid=dict(minimum_native='0.000001',increment_native='0',legal_price_tick=None),grid_qualification='diagnostic_continuous'))
    legs=[Leg(q,group,profiles,event,at,policy=policy) for q in qs]
    return saved,qs,legs,profiles,event,group,at


def benchmark(q,p,ctx,venue='pinnacle',prices=None):
    roles={x['role']:x['id'] for x in ctx['event']['participants']}
    _,old=_reference(q,references(q,p),roles)
    rows=[]
    for i,row in enumerate(old.outcomes):
        odds=row.decimal_odds if prices is None else ExactNumber(prices[i])
        native=replace(row.selection.native,venue=venue,evidence=(EvidenceReference('authored:two-way',old.receipt_sha256,'authored'),))
        selection=replace(row.selection,family='moneyline',native=native,price=Price(odds,'decimal_odds','usd_per_usd_stake','USD'))
        rows.append(SportsbookOutcome(selection,odds,row.book_at,row.market_at,row.received_at,row.revision))
    return TwoWayBenchmark(tuple(rows),old.receipt_sha256,'decisive_win_loss',None,venue,'proportional_no_vig','authored:one-envelope-revision')


def evaluate_single(q,p,c,**kw):
    return single(q,p,at=kw.pop('at',AT),event=c['event'],group=c['group'],**kw)


class S01Tests(unittest.TestCase):
    def test_continuous_requested_regression_exact_independent(self):
        _,q,legs,p,e,g,at=retained(continuous=True)
        r=pair_eval(legs,details=True)
        self.assertTrue(r['model_available'],r)
        a=F(35000,81);b=F(46000,81);payout=F(80500,81)
        self.assertEqual([F(x['native_quantity']) for x in r['legs']],[a,b])
        self.assertEqual(F(r['deployed_capital_usd']),1000)
        self.assertEqual(F(r['buffer_usd']),5)
        self.assertEqual(F(r['decisive_minimum_usd']),payout-1000)
        self.assertEqual(F(r['buffered_decisive_minimum_usd']),F(-905,81))
        self.assertEqual(F(r['financial_metrics']['buffered_decisive_return_percent']),F(-181,162))
        self.assertFalse(r['classification']['main_positive_eligible'])
        self.assertFalse(r['minimum_spend_solution'])
        self.assertEqual(r['size_status'],'size_unverified')

    def test_grid_retained_old_new_original_instant_and_hashes(self):
        saved,q,legs,p,e,g,at=retained()
        old_policy=EstimatePolicy.from_dict(saved['policy'])
        old_legs=[Leg(x,g,p,e,at,policy=old_policy) for x in q]
        old=pair_eval(old_legs,policy=old_policy)
        new=pair_eval(legs,details=True)
        # The retained v1 oracle predates B02's additive evaluation frame.
        self.assertEqual(digest({k:v for k,v in old.items() if k not in ('revision','evaluation_frame')}),
            saved['state']['events'][0]['funded_pairs'][0]['revision'])
        self.assertEqual(old['revision'],digest({k:v for k,v in old.items() if k!='revision'}))
        self.assertEqual(old['evaluation_frame']['evaluated_at'],at.isoformat())
        self.assertEqual([row['times'] for row in old['evaluation_frame']['quotes']],[x['times'] for x in q])
        self.assertEqual(F(old['deployed_capital_usd']),F('25.155281'))
        self.assertGreater(F(new['deployed_capital_usd']),F('999.99'))
        self.assertLessEqual(F(new['deployed_capital_usd']),1000)
        a,b=[F(x['native_quantity']) for x in new['legs']]
        capital=a+b;profit=min(a*F('2.30'),b*F('1.75'))-capital
        self.assertEqual(F(new['buffered_decisive_minimum_usd']),profit-capital/F(200))
        for row,original in zip(new['legs'],q):self.assertEqual(row['source_times'],original['times'])
        old_single=single(q[0],p,at=at,event=e,group=g,policy=old_policy,details=True)
        new_single=single(q[0],p,at=at,event=e,group=g,details=True)
        expected=F('0.994')*(F(172,395)*F('2.3')*1000-1000)
        self.assertEqual(F(new_single['financial_metrics']['net_modeled_ev_usd']),expected)
        self.assertEqual(F(old_single['buffered_profit_usd']),F(new_single['buffered_profit_usd']))
        self.assertEqual(old_single['reference_inputs'],new_single['reference_inputs'])

    def test_named_benchmark_originals_prices_and_absence(self):
        q,p,c=vector('prophetx','0.53');base=benchmark(q,p,c)
        selected=benchmark(q,p,c,'novig')
        policy=replace(DEFAULT_POLICY,benchmark_venue='novig')
        r=evaluate_single(q,p,c,benchmark=selected,policy=policy,details=True)
        pin=evaluate_single(q,p,c,benchmark=base,details=True)
        self.assertEqual(r['financial_metrics']['gross_benchmark_ev_usd'],pin['financial_metrics']['gross_benchmark_ev_usd'])
        self.assertNotEqual(r['dependency_revision'],pin['dependency_revision'])
        self.assertEqual(TwoWayBenchmark.from_dict(selected.to_dict()),selected)
        self.assertTrue(all(x['selection']['native']['venue']=='novig' for x in r['benchmark']['originals']))
        changed=evaluate_single(q,p,c,benchmark=benchmark(q,p,c,'novig',('2','3')),policy=policy)
        self.assertNotEqual(changed['buffered_profit_usd'],r['buffered_profit_usd'])
        missing=evaluate_single(q,p,c,policy=policy)
        self.assertIsNone(missing['financial_metrics']['net_modeled_ev_usd'])
        self.assertTrue(missing['states'])
        self.assertFalse(missing['classification']['main_positive_eligible'])
        wrong=evaluate_single(q,p,c,policy=policy,benchmark=base)
        self.assertIsNone(wrong['financial_metrics']['gross_benchmark_ev_usd'])

    def test_benchmark_crossed_roles_books_revisions_clocks(self):
        q,p,c=vector();ref=benchmark(q,p,c)
        row=ref.outcomes[1]
        with self.assertRaises(ValueError):replace(ref,outcomes=(ref.outcomes[0],replace(row,selection=replace(row.selection,native=replace(row.selection.native,venue='novig')))))
        with self.assertRaises(ValueError):replace(ref,outcomes=(ref.outcomes[0],replace(row,selection=replace(row.selection,participant_id=ref.outcomes[0].selection.participant_id))))
        with self.assertRaises(ValueError):replace(ref,outcomes=(ref.outcomes[0],replace(row,received_at=(AT+timedelta(seconds=1)).isoformat())))
        with self.assertRaises(ValueError):replace(ref,outcomes=(ref.outcomes[0],))
        future=replace(ref,outcomes=tuple(replace(x,book_at=(AT+timedelta(seconds=1)).isoformat(),received_at=(AT+timedelta(seconds=1)).isoformat()) for x in ref.outcomes))
        r=evaluate_single(q,p,c,benchmark=future)
        self.assertIsNone(r['financial_metrics']['net_modeled_ev_usd'])
        stale=evaluate_single(q,p,c,benchmark=ref,at=AT+timedelta(seconds=1801))
        self.assertEqual(stale['financial_metrics'],evaluate_single(q,p,c,benchmark=ref)['financial_metrics'])
        self.assertIn('reference_expired',stale['eligibility_reasons'])
        self.assertFalse(stale['ranking_eligible'])
        self.assertFalse(stale['classification']['main_positive_eligible'])
        event=replace(ref.outcomes[1].selection.event,away_id='NFL:SEA')
        with self.assertRaises(ValueError):replace(ref,outcomes=(ref.outcomes[0],replace(row,selection=replace(row.selection,event=event))))

    def test_positive_zero_negative_and_buffer_crossing(self):
        for prices,sign in [(('0.6','0.6'),-1),(('0.5','0.5'),0),(('0.24','0.74'),1),(('0.499','0.499'),1)]:
            legs,_,_=pair(prices=prices,flat='0',tick='0.001');r=pair_eval(legs)
            decisive=F(r['decisive_minimum_usd'])
            self.assertEqual((decisive>0)-(decisive<0),sign)
            if prices==('0.499','0.499'):
                self.assertLess(F(r['buffered_decisive_minimum_usd']),0)
                self.assertFalse(r['classification']['positive_rule_sensitive_eligible'])
        legs,_,_=exact_example();r=pair_eval(legs,quantities=('1010','1010'))
        self.assertGreater(F(r['buffered_decisive_minimum_usd']),0)
        self.assertLess(F(r['states']['tie']['profit_usd']),0)
        self.assertTrue(r['classification']['rule_sensitive'])
        self.assertFalse(r['classification']['is_arb'])
        self.assertFalse(r['classification']['main_positive_eligible'])

    def test_unknown_exception_and_no_reference_preserve_scenarios(self):
        legs,_,_=pair(flat='0',compatible=False);r=pair_eval(legs)
        self.assertIsNone(r['financial_metrics']['net_modeled_ev_usd'])
        self.assertIsNotNone(r['financial_metrics']['conditional_net_ev_usd'])
        self.assertEqual(r['condition'],'decisive_home_or_away_win')
        policy=replace(DEFAULT_POLICY,benchmark_venue='novig')
        r=pair_eval(legs,policy=policy)
        self.assertIsNone(r['financial_metrics']['gross_benchmark_ev_usd'])
        self.assertIsNotNone(r['financial_metrics']['decisive_opposing_margin_usd'])
        self.assertFalse(r['benchmark']['available'])

    def test_reconciliation_maximum_single_and_compact_identity(self):
        for venue in ('kalshi','polymarket_us','novig','prophetx'):
            q,p,c=vector(venue,'0.6')
            if venue in ('kalshi','polymarket_us'):
                bind(q,p,'quantity',dict(grid=dict(minimum_native='1',increment_native='1',legal_price_tick='0.01'),grid_qualification='authored_declared_grid'))
            r=evaluate_single(q,p,c,details=True)
            self.assertIn('financial_metrics',r,r)
            self.assertLessEqual(F(r['deployed_capital_usd']),1000)
            if r['size_search']['maximum_quantity_proven']:
                self.assertGreater(F(r['size_search']['next_grid_capital_usd']),1000)
            f=r['financial_metrics'];self.assertEqual(F(f['net_modeled_ev_usd']),F(f['gross_benchmark_ev_usd'])+F(f['rule_adjustment_usd'])-F(f['net_upfront_fee_usd'])-F(f['expected_settlement_fee_usd']))
            self.assertEqual(F(f['buffered_ev_usd']),F(f['net_modeled_ev_usd'])-F(f['buffer_usd']))
            compact=single_compact(r)
            for field in ('financial_metrics','benchmark','classification','funding','requested_amount_usd','sizing_mode'):self.assertEqual(compact[field],r[field])
            self.assertFalse(r['classification']['is_arb'])
        legs,_,_=pair(flat='5');r=pair_eval(legs,details=True)
        f=r['financial_metrics'];self.assertEqual(F(f['net_modeled_ev_usd']),F(f['gross_benchmark_ev_usd'])+F(f['rule_adjustment_usd'])-F(f['net_upfront_fee_usd'])-F(f['expected_settlement_fee_usd']))
        self.assertEqual(pair_compact(r)['funding'],r['funding'])
        variants=[replace(DEFAULT_POLICY,capital_ceiling_usd='900'),replace(DEFAULT_POLICY,buffer_rate='0.01'),replace(DEFAULT_POLICY,sizing_mode='ceiling'),replace(DEFAULT_POLICY,benchmark_venue='novig')]
        self.assertEqual(len({pair_eval(legs,policy=x)['revision'] for x in [DEFAULT_POLICY,*variants]}),5)
        for policy in [DEFAULT_POLICY,LEGACY_POLICY,*variants]:self.assertEqual(EstimatePolicy.from_dict(policy.to_dict()),policy)
        value=EstimateResult(DEFAULT_POLICY,'999.8','8.8668','modeled_complete','size_unverified').to_dict()
        self.assertEqual(EstimateResult.from_dict(value,policy=DEFAULT_POLICY).to_dict(),value)
        self.assertEqual(effective_policy(DEFAULT_POLICY,amount='900',benchmark_venue='novig'),variants[0].__class__(capital_ceiling_usd='900',benchmark_venue='novig'))

    def test_requested_fee_hold_final_cashflow_allocation(self):
        from app.comparison.costs import FundingComponent
        funding=[dict(extra_funding=(FundingComponent('independent-a','40','refundable_hold','entry'),),hold_returns_usd={s:'40' for s in ('home_win','away_win','tie','terminal_noncompletion')}),{}]
        legs,_,_=pair(flat='5',funding=funding);r=pair_eval(legs,details=True)
        self.assertTrue(r['model_available'],r)
        self.assertEqual(F(r['cost_breakdown']['extra_funding_usd']),40)
        self.assertLessEqual(F(r['deployed_capital_usd']),1000)
        self.assertEqual(F(r['cost_breakdown']['net_upfront_fee_usd']),10)
        for component,row in zip(r['components'],r['legs']):
            self.assertEqual(F(component['acquisition_usd']),F(row['acquisition_usd']))
        self.assertEqual(F(r['buffer_usd']),F(r['deployed_capital_usd'])/200)

    def test_final_rounded_entry_and_stake_commission_independent(self):
        from decimal import Decimal, ROUND_HALF_EVEN, ROUND_CEILING
        from tests.test_ev05_funded import cents
        for venue,rate in (('kalshi',F('.07')),('polymarket_us',F('.0695'))):
            q,p,c=vector(venue,'0.6')
            bind(q,p,'quantity',dict(grid=dict(minimum_native='1',increment_native='1',legal_price_tick='0.01'),grid_qualification='authored'))
            r=evaluate_single(q,p,c,details=True);n=F(r['native_quantity'])
            raw=rate*n/F(4)
            fee=cents(raw,ROUND_HALF_EVEN) if venue=='polymarket_us' else F((Decimal(raw.numerator)/Decimal(raw.denominator)).quantize(Decimal('.0001'),rounding=ROUND_CEILING))
            self.assertEqual(F(r['net_entry_fee_usd']),fee)
            self.assertEqual(F(r['deployed_capital_usd']),n/2+fee)
        saved=json.loads(FIXTURE.read_text());state=saved['state'];e=state['events'][0];g=e['groups'][0];p=state['comparison_profiles'];at=instant(saved['as_of'])
        qs=[g['outcomes'][0]['quotes']['prophetx'],g['outcomes'][1]['quotes']['novig']]
        legs=[Leg(q,g,p,e,at,policy=DEFAULT_POLICY) for q in qs];r=pair_eval(legs,details=True)
        self.assertTrue(r['model_available'],r)
        a,b=[F(x['native_quantity']) for x in r['legs']]
        commission=cents(F('.02')*a*(F('2.29')-1),ROUND_CEILING)
        self.assertEqual(F(r['states']['a_wins']['settlement_charge_usd']),commission)
        capital=a+b
        self.assertEqual(F(r['states']['a_wins']['profit_usd']),a*F('2.29')-capital-commission)
        self.assertEqual(F(r['states']['b_wins']['profit_usd']),b*F('1.75')-capital)
        self.assertLess(abs(F(r['states']['a_wins']['profit_usd'])-F(r['states']['b_wins']['profit_usd'])),F('.01'))

    def test_small_requested_grid_independent_balance_oracle(self):
        legs,_,_=pair(prices=('0.4','0.5'),flat='5')
        policy=replace(DEFAULT_POLICY,capital_ceiling_usd='40')
        r=pair_eval(legs,policy=policy)
        candidates=[]
        for a in range(25,76):
            for b in range(25,76):
                capital=F('.4')*a+F('.5')*b+10
                if capital<=40 and min(a,b)>=F('.2')*(a+b):
                    candidates.append((-abs(a-b),capital,a,b))
        _,capital,a,b=max(candidates)
        self.assertEqual([F(x['native_quantity']) for x in r['legs']],[a,b])
        self.assertEqual(F(r['deployed_capital_usd']),capital)
        self.assertFalse(r['search']['global_optimality_proven'])

    def test_profile_adapter_and_original_identity_roundtrip(self):
        from app.comparison.source_inputs import produce_two_way_benchmark
        from app.comparison.current_metrics import reference_set
        q,p,c=vector();ref=benchmark(q,p,c,'novig')
        supplied=produce_two_way_benchmark([x.to_dict() for x in ref.outcomes],venue='novig',receipt_sha256=ref.receipt_sha256,source_revision=ref.source_revision)
        self.assertEqual(reference_set(supplied),ref)
        bind(q,p,'reference',supplied)
        policy=replace(DEFAULT_POLICY,benchmark_venue='novig')
        attached=evaluate_single(q,p,c,policy=policy)
        explicit=evaluate_single(q,p,c,policy=policy,benchmark=ref)
        self.assertEqual(attached['financial_metrics'],explicit['financial_metrics'])
        self.assertEqual(attached['benchmark'],explicit['benchmark'])
        changed=replace(ref,source_revision='authored:next-envelope-revision')
        other=evaluate_single(q,p,c,policy=policy,benchmark=changed)
        self.assertNotEqual(other['dependency_revision'],explicit['dependency_revision'])
        self.assertEqual(other['financial_metrics'],explicit['financial_metrics'])
        with self.assertRaises(ValueError):replace(DEFAULT_POLICY,benchmark_method='unsupported_no_vig')

    def test_native_predicate_and_refusal_metadata(self):
        legs,_,_=pair(flat='0')
        r=pair_eval([legs[0],legs[0]])
        self.assertFalse(r['classification']['main_positive_eligible'])
        self.assertEqual(pair_compact(r)['sizing_mode'],'requested_trade')
        self.assertIn('duplicate',r['classification']['reason'])
        self.assertEqual(legs[1].q['binding']['selection']['predicate'],'not_win')
        _,q,retained_legs,p,e,g,at=retained()
        self.assertTrue(all(x.q['binding']['selection']['predicate']=='win' for x in retained_legs))
        self.assertEqual(pair_eval(legs)['legs'][1]['selection']['predicate'],'not_win')

    def test_final_fee_cliffs_and_native_integer_grid(self):
        from decimal import ROUND_CEILING
        from tests.test_ev05_funded import cents
        from app.comparison.costs import CostRule,FeeTerms
        legs,profiles,event=pair(prices=('0.24','0.74'),flat='0')
        changed=[]
        for x in legs:
            payload=deepcopy(references(x.q,profiles)['fee']['payload'])
            rule=CostRule.from_dict(payload['rule'])
            payload['rule']=replace(rule,terms=FeeTerms('notional','0.013','1','ceiling','order','taker')).to_dict()
            bind(x.q,profiles,'fee',json.loads(json.dumps(payload)))
            changed.append(Leg(x.q,x.group,profiles,event,x.at,policy=DEFAULT_POLICY))
        r=pair_eval(changed,details=True)
        self.assertTrue(r['model_available'],r)
        fees=[]
        for row in r['legs']:
            raw=F(row['acquisition_usd'])*F('.013')
            fee=F(-(-raw.numerator//raw.denominator))
            fees.append(fee)
            self.assertEqual(F(row['net_upfront_fee_usd']),fee)
            self.assertEqual(F(row['native_quantity']).denominator,1)
        self.assertEqual(F(r['deployed_capital_usd']),sum(F(row['acquisition_usd']) for row in r['legs'])+sum(fees))
        self.assertLessEqual(F(r['deployed_capital_usd']),1000)
        self.assertLess(F(r['unused_cash_usd']),2)

    def test_requested_pool_cap_recomputed_at_final_stakes(self):
        from app.comparison.costs import CostRule,FeeTerms,UnitSpec
        from tests.test_comparison_net_costs import setup_case
        _,qs,_,profiles,e,g,at=retained()
        _,_,kw=setup_case('novig')
        original=CostRule.from_dict(kw['registry'].data['rules'][0])
        legs=[]
        for q,price in zip(qs,('2.5','2.0')):
            q['original']['value']=price
            rule=replace(original,unit=UnitSpec('stake_usd'),event_id=None,market_id=None,
                terms=FeeTerms('net_gain','0.02','0.01','ceiling',None,'taker'))
            payload=dict(rule=rule.to_dict(),commission_pool=dict(venue='novig',channel=rule.channel,market_id='authored:common-pool',cap_usd='1'))
            bind(q,profiles,'fee',json.loads(json.dumps(payload)))
            legs.append(Leg(q,g,profiles,e,at,policy=DEFAULT_POLICY))
        r=pair_eval(legs,details=True)
        self.assertTrue(r['model_available'],r)
        a,b=[F(x['native_quantity']) for x in r['legs']];capital=a+b
        for state,payout in [('a_wins',F('2.5')*a),('b_wins',2*b)]:
            gain=payout-capital
            raw=F('.02')*max(gain,0)
            charge=min(F(-(-100*raw.numerator//raw.denominator),100),1)
            self.assertEqual(F(r['states'][state]['settlement_charge_usd']),charge)
            self.assertEqual(F(r['states'][state]['profit_usd']),gain-charge)
        self.assertGreater(capital,999)

    def test_successor_withholding_is_not_subtracted_twice(self):
        from tests.test_comparison_net_costs import setup_case
        q,p,c=vector('prophetx','0.5')
        _,_,args=setup_case('prophetx','100');rule=args['registry'].rules[0].to_dict()
        rule.update(event_id=q['source']['native_event_id'],market_id=q['source']['native_market_id'],settlement_status='known_terms',
            settlement_treatment='already_withheld_from_payout',settlement_terms=dict(basis='net_gain',rate='0.03',grid_usd='0.01',rounding='half_even',aggregation='order',role='taker',allow_fee_adjustment=False))
        bind(q,p,'fee',json.loads(json.dumps(dict(rule=rule))))
        r=evaluate_single(q,p,c,native_quantity='100',settlement_charge_already_withheld=True,
            state_cashflows=dict(home_win='0',away_win='197',tie='100',terminal_noncompletion='100'),details=True)
        self.assertEqual(F(r['states']['b_wins']['profit_usd']),F('95.06'))
        self.assertEqual(r['states']['b_wins']['receipt_charge_treatment'],'attached_net_receipt')
        f=r['financial_metrics'];self.assertEqual(F(f['net_modeled_ev_usd']),F(f['gross_benchmark_ev_usd'])+F(f['rule_adjustment_usd'])-F(f['net_upfront_fee_usd'])-F(f['expected_settlement_fee_usd']))


if __name__=='__main__':unittest.main()
