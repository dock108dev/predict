"""Independent rational EV05 oracles; all source/allocation inputs are authored."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN
from fractions import Fraction as F
import json
from pathlib import Path
import unittest

from app.comparison.costs import FundingComponent
from app.comparison.current_dependencies import profile, digest
from app.comparison.domain import ExactNumber, NativeProvenance, ScorePredicate, Scope, Price
from app.comparison.estimated_consumer import consume
from app.comparison.estimated_ev import evaluate, compact
from app.comparison.estimated_policy import EstimatePolicy
from app.comparison.pinnacle import ReferenceOutcome, ReferenceSet
from app.comparison.source_inputs import _selection
from app.comparison.net_costs import wire
from tests.test_ev04_content import case, AT, value, STATES
from tests.test_comparison_net_costs import setup_case


def bind(q, profiles, kind, payload):
    key, p = profile(kind, payload)
    profiles[key] = p; q['comparison_input_refs']['refs'][kind] = key
    q['comparison_input_status'][kind]['status'] = 'available_and_bound'
    recipe = q['comparison_input_status'][kind].get('estimate_content')
    if recipe:
        recipe['original_profile_ref'] = key
        recipe['id'] = digest({k:v for k,v in recipe.items() if k!='id'})


def vector(venue='prophetx', c='0.53', price=None, predicate='win', metadata=None):
    q, profiles, ctx, record = case(venue, predicate, metadata)
    q['depth'] = []
    if price is not None:
        q['original']['value'] = price
    ctx['event']['start_at'] = (AT+timedelta(days=1)).isoformat()
    scope = Scope('full_game','included','conditional_completed_result')
    selected, _ = _selection(record, ctx, scope)
    # _selection uses the exact quote and declared native observation.
    bind(q, profiles, 'identity', dict(selection=selected.to_dict(),current_selection_binding=deepcopy(q['binding']['selection'])))
    home = selected.event.home_id; away = selected.event.away_id
    selected_home = q['binding']['selection']['participant']==home
    home_weight = F(c) if selected_home else 1-F(c)
    rows = []
    for participant, operator, probability in ((home,'gt',home_weight),(away,'lt',1-home_weight)):
        # Odds need terminating decimal originals; inverse probabilities can be
        # rational exact originals through ExactNumber, independently of EV.
        odds = ExactNumber(wire(1/probability))
        native = NativeProvenance('pinnacle','authored-ref-event','authored-ref-market',participant,
            'bookmaker_outcome',participant,selected.native.evidence)
        s = replace(selected, participant_id=participant, predicate=ScorePredicate('home_margin',operator,ExactNumber('0')),
            native=native, price=Price(odds,'decimal_odds','usd_per_usd_stake','USD'))
        rows.append(ReferenceOutcome(s,odds,AT.isoformat(),None,AT.isoformat(),'authored-ref:'+participant))
    reference = ReferenceSet(tuple(rows),'a'*64,'decisive_win_loss')
    bind(q,profiles,'reference',dict(outcomes=[r.to_dict() for r in rows],receipt_sha256=reference.receipt_sha256,
        conditioning='decisive_win_loss',partition_evidence_sha256=None,source_at=[r.source_at for r in rows]))
    return q, profiles, ctx


def run(q, p, ctx, **kw):
    kw.setdefault('policy',EstimatePolicy())
    return evaluate(q,p,at=kw.pop('at',AT),event=ctx['event'],group=ctx['group'],**kw)


def cents(x, rounding):
    return F((Decimal(x.numerator)/Decimal(x.denominator)).quantize(Decimal('.01'),rounding=rounding))


class FundedTests(unittest.TestCase):
    def test_unverified_source_stage_retains_disclosed_regular_season_assumption(self):
        q,p,ctx=vector()
        ctx['event']['stage']='unverified'
        result=run(q,p,ctx,details=True)
        self.assertTrue(result['model_available'],result)
        self.assertEqual(ctx['event']['stage'],'unverified')
        self.assertIn('regular_season assumed for this NFL model; actual stage unknown',result['assumptions'])

    def test_example_81_independent_and_display_rounding(self):
        q,p,ctx=vector()
        result=run(q,p,ctx,details=True)
        self.assertTrue(result['model_available'], result)
        # These constants are derived directly from the approved four cells,
        # without invoking the application's fee/probability helpers.
        ev=F('0.994')*(F('0.53')*980-F('0.47')*1000)
        self.assertEqual(ev,F('49.1036'))
        self.assertEqual(F(result['fee_adjusted_expected_profit_usd']),ev)
        self.assertEqual(F(result['buffered_profit_usd']),F('44.1036'))
        self.assertEqual(result['deployed_capital_usd'],'1000')
        self.assertEqual(sum(map(F,result['probabilities'].values())),1)
        from app.dashboard.current_contract import exact_wire, display_decimal
        self.assertEqual(display_decimal(exact_wire(F(result['buffered_return_percent']))['decimal_approx'],2,True),'+4.41')
        self.assertEqual(display_decimal('44.1036',2,True),'+44.10')
        self.assertEqual(result['actual_facts']['charges'],None)
        self.assertEqual(compact(run(q,p,ctx)),compact(result))

    def test_every_venue_fee_inclusive_maximum_and_signed_results(self):
        for venue in ('kalshi','polymarket_us','novig','prophetx'):
            for decisive in ('0.4','0.5','0.6'):
                with self.subTest(venue=venue,decisive=decisive):
                    q,p,ctx=vector(venue,decisive)
                    if venue in ('kalshi','polymarket_us'):
                        bind(q,p,'quantity',dict(grid=dict(minimum_native='1',increment_native='1',legal_price_tick='0.01'),
                            grid_qualification='authored_declared_grid'))
                        # Independent finite oracle over the full legal domain.
                        rate=F('0.07' if venue=='kalshi' else '0.0695')
                        def entry(n):
                            raw=rate*n*F('.25')
                            if venue=='polymarket_us':return cents(raw,ROUND_HALF_EVEN)
                            return F((Decimal(raw.numerator)/Decimal(raw.denominator)).quantize(Decimal('.0001'),rounding=ROUND_CEILING))
                        n=max(n for n in range(1,2001) if F(n,2)+entry(n)<=1000)
                        funded=F(n,2)+entry(n)
                        expected=F('.994')*F(decisive)*n+F('.006')*F(n,2)-funded
                    else:
                        n=1000;funded=F(1000)
                        win=F(980 if venue=='prophetx' else 1000)
                        expected=F('.994')*(F(decisive)*win-(1-F(decisive))*1000)
                    result=run(q,p,ctx)
                    self.assertTrue(result['model_available'],result)
                    self.assertEqual(F(result['native_quantity']),n)
                    self.assertEqual(F(result['deployed_capital_usd']),funded)
                    self.assertEqual(F(result['fee_adjusted_expected_profit_usd']),expected)
                    self.assertEqual(F(result['buffered_profit_usd']),expected-funded*F('.005'))
                    self.assertTrue(result['size_search']['maximum_quantity_proven'])
                    self.assertGreater(F(result['size_search']['next_grid_capital_usd']),1000)
                    if decisive=='0.4':self.assertLess(F(result['buffered_profit_usd']),0)
        q,p,ctx=vector('novig','0.5')
        result=run(q,p,ctx,policy=EstimatePolicy(buffer_rate='0'))
        self.assertEqual(F(result['buffered_profit_usd']),0)
        self.assertEqual(F(result['native_quantity']),1000)

    def test_two_observed_stake_levels_plus_residual_and_partial_level(self):
        for venue in ('novig','prophetx'):
            q,p,ctx=vector(venue,'0.53')
            q['depth']=[dict(price='2',quantity='200'),dict(price='1.9',quantity='300')]
            original=deepcopy(q)
            result=run(q,p,ctx,details=True)
            winning='a_wins' if q['binding']['selection']['participant']==ctx['event']['participants'][1]['id'] else 'b_wins'
            receipt=200*F(2)+800*F('1.9')
            self.assertEqual(F(result['states'][winning]['receipt_usd']),receipt)
            commission=F('18.4') if venue=='prophetx' else 0
            self.assertEqual(F(result['states'][winning]['separately_payable_charge_usd']),commission)
            self.assertEqual(F(result['fee_adjusted_expected_profit_usd']),F('.994')*(F('.53')*(receipt-1000-commission)-F('.47')*1000))
            self.assertEqual(result['supported_native_quantity'],'500')
            self.assertEqual(result['modeled_native_quantity'],'500')
            self.assertEqual(result['supported_capital_usd'],'500')
            self.assertEqual(q,original)
            partial=run(q,p,ctx,policy=EstimatePolicy(capital_ceiling_usd='350'),details=True)
            self.assertEqual(partial['supported_native_quantity'],'350')
            self.assertEqual(partial['modeled_native_quantity'],'0')
            self.assertEqual([f['stake_usd'] for f in partial['fills']['stake_fills']],['200','150'])
            self.assertEqual(partial['size_status'],'supported_size')
            self.assertIsNotNone(result['sensitivity']['residual_price_impact']['buffered_profit_usd'])

    def test_conditional_renormalization_and_missing_state_visibility(self):
        q,p,ctx=vector()
        result=run(q,p,ctx,native_quantity='1000',state_cashflows=dict(home_win='0',away_win='2000',tie=None,terminal_noncompletion='1000'))
        self.assertEqual(result['conditioning'],'modeled_conditional')
        self.assertEqual(result['condition'],'decisive_home_or_away_win')
        self.assertEqual(result['missing_positive_probability_states'],['tie'])
        self.assertEqual(sum(map(F,result['conditional_probabilities'].values())),1)
        self.assertEqual(F(result['fee_adjusted_expected_profit_usd']),F('49.4'))
        self.assertIsNone(result['states']['tie']['profit_usd'])

    def test_holds_allowances_withholding_and_unknown_returns(self):
        q,p,ctx=vector()
        extra=(FundingComponent('hold','10','refundable_hold','entry'),FundingComponent('allowance','3','consumed_allowance','entry'))
        result=run(q,p,ctx,extra_funding=extra,hold_returns_usd=dict.fromkeys(STATES,'10'),details=True)
        self.assertEqual(F(result['native_quantity']),987)
        win=next(row for row in result['states'].values() if row['receipt_usd']=='1974')
        self.assertEqual(F(win['separately_payable_charge_usd']),F('19.68'))
        self.assertEqual(F(win['profit_usd']),F('964.32'))
        self.assertEqual(result['deployed_capital_usd'],'1000')
        unknown=run(q,p,ctx,extra_funding=extra)
        self.assertFalse(unknown['model_available'])
        self.assertIsNone(unknown['states']['a_wins']['profit_usd'])
        _,_,args=setup_case('prophetx','100')
        rule=args['registry'].rules[0].to_dict()
        rule.update(event_id=q['source']['native_event_id'],market_id=q['source']['native_market_id'],settlement_status='known_terms',
            settlement_treatment='already_withheld_from_payout',settlement_terms=dict(basis='net_gain',rate='0.03',grid_usd='0.01',rounding='half_even',aggregation='order',role='taker',allow_fee_adjustment=False))
        bind(q,p,'fee',json.loads(json.dumps(dict(rule=rule))))
        attached=run(q,p,ctx,native_quantity='100',settlement_charge_already_withheld=True,
            state_cashflows=dict(home_win='0',away_win='197',tie='100',terminal_noncompletion='100'),details=True)
        self.assertEqual(F(attached['states']['b_wins']['profit_usd']),F('95.06'))
        self.assertEqual(attached['states']['b_wins']['receipt_charge_treatment'],'attached_net_receipt')

    def test_exceptional_positive_gain_commission_includes_returned_entry_fee(self):
        # Isolate the integration seam with an independently constructed
        # applicable fee and payout profile. Entry $10, refundable; terminal
        # receipt $120 on $100 stake => scoped gain $20, commission $0.40.
        q,p,ctx=vector()
        _,_,args=setup_case('prophetx','100')
        rule=args['registry'].rules[0].to_dict()
        rule.update(event_id=q['source']['native_event_id'],market_id=q['source']['native_market_id'],
            terms=dict(basis='notional',rate='0.1',grid_usd='0.01',rounding='half_even',aggregation='order',role='taker',allow_fee_adjustment=False),
            settlement_status='known_terms',settlement_terms=dict(basis='net_gain',rate='0.02',grid_usd='0.01',rounding='half_even',aggregation='order',role='taker',allow_fee_adjustment=False))
        bind(q,p,'fee',json.loads(json.dumps(dict(rule=rule))))
        # A selected payout is supplied through the existing binder; its scalar
        # cells and refund treatment are independent of the EV evaluator.
        from app.comparison.payouts import PayoutProfile, CompletionContext
        from app.comparison.domain import CanonicalSelection
        selected=CanonicalSelection.from_dict(p[q['comparison_input_refs']['refs']['identity']]['payload']['selection'])
        profile_data=json.loads((Path('app/fixtures/comparison-payouts-v1.json')).read_text())
        sample=deepcopy(profile_data['profile_rows'][0]['profile'])
        from app.comparison.payouts import selection_digest
        sample.update(profile_id='authored-refund',rule_revision='authored-refund-1',
            native_key=list(selected.native.key),selection_sha256=selection_digest(selected),payout_unit='usd_per_usd_stake',
            effective_from=AT.isoformat(),effective_until=(AT+timedelta(hours=1)).isoformat(),refund_fees='returned',
            below=dict(value='2',status='estimated',reason='Authored refund vector'),above=dict(value='0',status='estimated',reason='Authored refund vector'),
            equal=dict(value='1',status='estimated',reason='Authored refund vector'),noncompleted=dict(value='1',status='estimated',reason='Authored refund vector'))
        payout=PayoutProfile.from_dict(sample)
        identity=p[q['comparison_input_refs']['refs']['identity']]['payload']
        identity=dict(identity,rule_revision=payout.rule_revision,completion_context=CompletionContext(None,None,'America/New_York',selected.native.evidence).to_dict())
        bind(q,p,'identity',identity)
        bind(q,p,'payout',payout.to_dict())
        component=consume(q,p,at=AT,native_quantity='100',state_cashflows=dict(home_win='0',away_win='200',tie='100',terminal_noncompletion='120'))
        self.assertEqual(value(component,'fee','fee_refund_usd:terminal_noncompletion'),'10')
        self.assertEqual(F(value(component,'fee','settlement_fee_usd:terminal_noncompletion')),F('.4'))
        result=run(q,p,ctx,native_quantity='100',state_cashflows=dict(home_win='0',away_win='200',tie='100',terminal_noncompletion='120'))
        self.assertTrue(result['model_available'],result)
        self.assertEqual(F(result['states']['terminal_noncompletion']['profit_usd']),F('19.6'))

    def test_scope_freshness_replacement_allocation_and_historical_inputs(self):
        q,p,ctx=vector();original=deepcopy(q);result=run(q,p,ctx)
        stale=run(q,p,ctx,at=AT+timedelta(seconds=901))
        self.assertTrue(stale['model_available']);self.assertFalse(stale['ranking_eligible'])
        self.assertIn('source_price_expired',stale['eligibility_reasons'])
        self.assertEqual(stale['fee_adjusted_expected_profit_usd'],result['fee_adjusted_expected_profit_usd'])
        self.assertEqual(stale['as_of_basis'],'last_known_inputs_evaluated_together')
        self.assertEqual(run(q,p,ctx),result)
        self.assertNotEqual(stale['revision'],result['revision'])
        for name, changed in [('stage','playoffs'),('league','NBA')]:
            c=deepcopy(ctx);c['event'][name]=changed
            self.assertFalse(run(q,p,c)['model_available'])
        c=deepcopy(ctx);c['group']['period']='first_half'
        self.assertFalse(run(q,p,c)['model_available'])
        c=deepcopy(ctx);c['event']['start_at']=AT.isoformat()
        self.assertFalse(run(q,p,c)['model_available'])
        future=deepcopy(q);future['times']['source_at']=(AT+timedelta(seconds=1)).isoformat()
        self.assertFalse(run(future,p,ctx,at=AT+timedelta(seconds=10))['model_available'])
        self.assertFalse(run(q,p,ctx,at=AT+timedelta(days=6))['model_available'])
        smaller=run(q,p,ctx,policy=EstimatePolicy(capital_ceiling_usd='500'))
        self.assertNotEqual(smaller['dependency_revision'],result['dependency_revision'])
        self.assertEqual(q,original)

    def test_not_win_orientation_and_selected_replacement(self):
        q,p,ctx=vector('kalshi','0.6',predicate='not_win',metadata={'tie_strike_listed':True})
        result=run(q,p,ctx,native_quantity='100')
        self.assertEqual(result['states']['b_wins']['receipt_usd'],'0')
        self.assertEqual(result['states']['a_wins']['receipt_usd'],'100')
        self.assertEqual(result['states']['tie']['receipt_usd'],'100')
        # A selected fee schedule replaces only this instrument's component.
        q,p,ctx=vector('polymarket_us')
        other,po,co=vector('prophetx');unaffected=run(other,po,co)
        before=run(q,p,ctx,native_quantity='100')
        _,_,args=setup_case('polymarket_us','100',rate='0.04')
        rule=args['registry'].rules[0].to_dict();rule.update(event_id=q['source']['native_event_id'],market_id=q['source']['native_market_id'])
        bind(q,p,'fee',json.loads(json.dumps(dict(rule=rule,engine_context=args['engine_context'],engine_registry=args['engine_registry'].data))))
        changed=run(q,p,ctx,native_quantity='100')
        self.assertNotEqual(changed['dependency_revision'],before['dependency_revision'])
        self.assertEqual(F(changed['net_entry_fee_usd']),1)
        self.assertEqual(run(other,po,co),unaffected)

    def test_exact_legacy_prophetx_single_commission_alias_counted_once(self):
        q,p,ctx=vector()
        catalog=json.loads(Path('app/fixtures/comparison-source-rules-v1.json').read_text())
        row=next(r for r in catalog['rules'] if r['id']=='comparison-source-prophetx-site-rounding-hypothesis-1')
        original=deepcopy(row['fee_payload'])
        bind(q,p,'fee',original)
        result=run(q,p,ctx,native_quantity='1000',details=True)
        self.assertEqual(F(result['fee_adjusted_expected_profit_usd']),F('49.1036'))
        self.assertEqual(result['components']['components']['fee']['settlement_fee_usd:away_win']['modeled_value'],'20')
        self.assertEqual(row['fee_payload'],original)

    def test_reference_limit_and_permanent_future_at_receipt_rejection(self):
        q,p,ctx=vector()
        q['times'].update(source_at=(AT+timedelta(seconds=1000)).isoformat(),received_at=(AT+timedelta(seconds=1000)).isoformat())
        fresh=run(q,p,ctx,at=AT+timedelta(seconds=1800))
        expired=run(q,p,ctx,at=AT+timedelta(seconds=1801))
        self.assertTrue(fresh['ranking_eligible']);self.assertTrue(expired['model_available'])
        self.assertEqual(expired['eligibility_reasons'],['reference_expired'])
        payload=deepcopy(p[q['comparison_input_refs']['refs']['reference']]['payload'])
        payload['outcomes'][0]['book_at']=(AT+timedelta(seconds=1)).isoformat()
        payload['source_at'][0]=payload['outcomes'][0]['book_at']
        bind(q,p,'reference',payload)
        self.assertFalse(run(q,p,ctx,at=AT+timedelta(seconds=1800))['model_available'])

    def test_projection_policy_clock_and_frozen_reader(self):
        from tests.ev05_workload import workload
        from tests.current_fixture import InjectedTestProvider
        from app.dashboard.current_state import CurrentStore
        from app.dashboard.current_contract import quotes_of,validate_snapshot,serialize,packed
        from app.dashboard.current_incremental import project
        from app.comparison.estimated_policy import DEFAULT_POLICY
        from unittest.mock import patch
        raw,_,_=workload(1,4);ticks=[0];store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:ticks[0])
        qs=lambda state:[q for e in state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)]
        target=next(q for q in qs(store._state) if q['calculations']['funded_estimate']['model_available'])
        request=dict(runtime_id=raw['runtime_id'],state_revision=1,quote_id=target['id'])
        full=store.details(request)['quote']['calculations']['funded_estimate']
        self.assertEqual(compact(full),target['calculations']['funded_estimate'])
        lease=store.create(dict(schema='predict-current-1',**request,quote_revision=target['revision'],client_id='authored:ev05'))
        frozen=deepcopy(lease['review']);policy=replace(DEFAULT_POLICY,capital_ceiling_usd='500')
        with patch('app.dashboard.current_incremental.load',return_value=policy):
            revised,_,_,_,_=project(dict(raw,state_revision=2),store._state,store._fingerprints,store._group_bytes,allow_synthetic=True)
        oracle=serialize(dict(raw,state_revision=2),allow_synthetic=True,estimate_policy=policy)
        self.assertEqual(packed(revised),packed(oracle))
        self.assertNotEqual(qs(revised)[0]['calculations']['funded_estimate']['revision'],qs(store._state)[0]['calculations']['funded_estimate']['revision'])
        # Source age advances independently of the lease's monotonic TTL.
        from app.dashboard.current_contract import stamp
        store._clock_origin=AT+timedelta(seconds=901);store.refresh_age()
        self.assertTrue(all(not q['calculations']['funded_estimate']['ranking_eligible'] for q in qs(store._state)))
        self.assertEqual(store.get(lease['selection_id'])['review'],frozen)
        historical=serialize(raw,allow_synthetic=True,funded=False)
        self.assertIs(validate_snapshot(historical,allow_synthetic=True),historical)
        current=serialize(raw,allow_synthetic=True)
        self.assertIs(validate_snapshot(current,allow_synthetic=True),current)

    def test_below_minimum_grids_unknown_units_and_short_refusals(self):
        q,p,ctx=vector('polymarket_us')
        bind(q,p,'quantity',dict(grid=dict(minimum_native='10',increment_native='3',legal_price_tick='0.01'),grid_qualification='authored'))
        result=run(q,p,ctx,policy=EstimatePolicy(capital_ceiling_usd='10'))
        self.assertEqual(result['native_quantity'],'19')
        self.assertGreater(F(result['size_search']['next_grid_capital_usd']),10)
        refused=run(q,p,ctx,policy=EstimatePolicy(capital_ceiling_usd='1'))
        self.assertIn('below_minimum',refused['reasons'][0])
        q,p,ctx=vector();q['original']['units']='unknown'
        self.assertFalse(run(q,p,ctx)['model_available'])
        q,p,ctx=vector('polymarket_us');q['source']['native_side']='SHORT'
        # Crossed identity is rejected before the unsupported collateral gate.
        self.assertFalse(run(q,p,ctx)['model_available'])

    def test_buffer_prior_and_price_sensitivity_sign_changes(self):
        q,p,ctx=vector('novig','0.502')
        result=run(q,p,ctx)
        signs=[F(s['profit_usd']) for s in result['sensitivity']['buffer']]
        self.assertGreater(max(signs),0);self.assertLess(min(signs),0)
        q,p,ctx=vector('novig','0.503')
        result=run(q,p,ctx)
        self.assertGreater(F(result['buffered_profit_usd']),0)
        self.assertLess(F(result['sensitivity']['residual_price_impact']['buffered_profit_usd']),0)
        q,p,ctx=vector('novig','0.50253')
        result=run(q,p,ctx)
        signs=[F(s['buffered_profit_usd']) for s in result['sensitivity']['prior']]
        self.assertGreater(max(signs),0);self.assertLess(min(signs),0)


from aiohttp.test_utils import AioHTTPTestCase


class FundedRoutes(AioHTTPTestCase):
    async def get_application(self):
        from tests.ev05_workload import workload
        from tests.current_fixture import InjectedTestProvider
        from tests.test_current_state import owner
        from app.dashboard.multi_game_server import create_app
        self.raw,_,_=workload(1,4)
        return create_app(owner=owner(),sessions={},current_provider=InjectedTestProvider(self.raw))

    async def test_current_comparison_selected_size_and_revision(self):
        from app.dashboard.current_contract import quotes_of
        current=await (await self.client.get('/api/current')).json()
        q=next(q for e in current['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)
            if q['calculations']['funded_estimate']['model_available'])
        params=dict(runtime_id=current['runtime_id'],state_revision=current['state_revision'],quote_id=q['id'])
        response=await self.client.get('/api/current/details',params=params)
        self.assertEqual(response.status,200);details=await response.json()
        result=details['quote']['calculations']['funded_estimate']
        self.assertEqual(compact(result),q['calculations']['funded_estimate'])
        self.assertIn('components',result);self.assertIn('dependencies',result)
        small=await (await self.client.get('/api/current/details',params=dict(params,ceiling='100'))).json()
        self.assertLess(F(small['quote']['calculations']['funded_estimate']['deployed_capital_usd']),101)
        self.assertNotEqual(small['quote']['calculations']['funded_estimate']['dependency_revision'],result['dependency_revision'])
        self.assertEqual(details['quote']['source'],q['source']);self.assertEqual(details['quote']['times'],q['times'])
        comparison=await (await self.client.get('/api/comparison')).json()
        row=next(r for r in comparison['rows'] if r['id']==q['id'])
        self.assertEqual(row['quote']['calculations']['funded_estimate'],q['calculations']['funded_estimate'])
        self.assertEqual((await self.client.get('/api/current/details',params=dict(params,state_revision=999))).status,409)


if __name__=='__main__':
    unittest.main()
