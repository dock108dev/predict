"""S06/D10 typed projection and independent exact ranking/route oracles."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction
import json
import unittest
from unittest.mock import patch
from aiohttp.test_utils import AioHTTPTestCase
from app.comparison.current_dependencies import profile
from app.comparison.current_metrics import typed_quote, adapt_ev
from app.comparison.metrics import ranked, best, snapshot_metrics
from app.dashboard.current_contract import serialize, packed, stamp, validate_snapshot
from app.dashboard.current_state import CurrentStore, CURRENT_KEY
from tests.current_fixture import InjectedTestProvider
from tests.comparison_fixture import software_fixture
from tests.test_current_state import owner
from app.dashboard.multi_game_server import create_app


def metric(value, *, basis='one'):
    value=Fraction(value)
    return dict(eligible=True,exact=dict(numerator=str(value.numerator),denominator=str(value.denominator)),
        value=str(value),display_value='0.00 %',basis=dict(conditioning=basis,probability_basis='benchmark',
            size_basis='$100 common ceiling',fee_basis='standalone taker'))


class Metrics(unittest.TestCase):
    def test_unavailable_wrapper_preserves_original_calculation_evidence(self):
        natural=dict(available=False,reason='probability_inputs_unknown',revision='authored-original',
            gross_decisive_benchmark=dict(available=True,return_percent='25'))
        original=deepcopy(natural)
        result=adapt_ev(natural,dict(revision=1),'100',None,{}, {})
        self.assertEqual(natural,original)
        self.assertEqual(result['details']['natural'],original)
        self.assertEqual(result['details']['gross_decisive_benchmark']['value'],'25')
        result['details']['natural']['revision']='detached-inspection'
        self.assertEqual(natural,original)

    def test_exact_before_rounding_signed_null_ties_and_selected_venue(self):
        rows=[dict(id='a',venue='kalshi',net_ev=metric('100001/100000000')),
              dict(id='b',venue='polymarket_us',net_ev=metric('100002/100000000')),
              dict(id='c',venue='novig',net_ev=metric('0')),
              dict(id='d',venue='prophetx',net_ev=metric('-1')),
              dict(id='e',venue='kalshi',net_ev=dict(eligible=False,exact=None,value=None))]
        self.assertEqual([r['id'] for r in ranked(rows)],list('bacde'))
        self.assertEqual(best(rows)['selected_venue'],'polymarket_us')
        rows[1]['net_ev']=metric('100001/100000000')
        self.assertEqual(best(rows)['selected_quote_id'],'a')
        rows[1]['net_ev']=metric('1',basis='different')
        self.assertEqual(best(rows)['reason'],'incomparable_metric_bases')
        with self.assertRaises(ValueError):ranked([dict(id='x',net_ev=dict(metric('1'),exact={'numerator':'1','denominator':'-1'}))])

    def test_typed_common_ceiling_actual_capital_and_literal_net_pair(self):
        raw=software_fixture();state=serialize(raw,allow_synthetic=True);view=snapshot_metrics(state)
        values={r['venue']:r for r in view['rows']}
        self.assertEqual(Fraction(values['kalshi']['net_ev']['value']),50)
        self.assertEqual(Fraction(values['kalshi']['gross']['value']),50)
        self.assertEqual(values['kalshi']['net_ev']['details']['state_labels']['completed:0:0'],'Tie')
        exact=values['prophetx']['net_ev']['exact']
        self.assertEqual(Fraction(int(exact['numerator']),int(exact['denominator'])),Fraction(-300,11))
        self.assertEqual(values['kalshi']['net_ev']['basis']['capital_denominator'],'79.6')
        self.assertEqual(values['kalshi']['net_ev']['details']['unused_ceiling_usd'],'20.4')
        pair=view['pairs'][0]
        self.assertEqual(pair['category'],'conditional_known_states')
        self.assertEqual(Fraction(pair['details']['minimum_return_percent']),Fraction(300,97))
        self.assertEqual(pair['details']['denominator_usd'],'97')
        self.assertIn('noncompleted',pair['details']['unknown_states'])
        self.assertEqual(pair['limiting_state_labels'],['Tie','Dallas Cowboys wins','Tampa Bay Buccaneers wins'])
        self.assertEqual(pair['state_labels']['noncompleted'],'Game not completed')
        self.assertEqual(len(pair['legs']),2)
        self.assertEqual({l['venue'] for l in pair['legs']},{'kalshi','prophetx'})
        self.assertLessEqual(view['searches'][0]['allocation_evaluations'],1024)
        self.assertEqual(snapshot_metrics(state,venue='kalshi')['selections'][0]['best']['selected_venue'],'kalshi')
        self.assertTrue(snapshot_metrics(state,venue='kalshi')['pairs'])
        self.assertFalse(snapshot_metrics(state,results='unavailable')['pairs'])
        validate_snapshot(state,allow_synthetic=True)

    def test_dependency_change_expiry_retirement_and_full_incremental_equal(self):
        raw=software_fixture();ticks=[0];store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:ticks[0])
        original=store.snapshot();q=raw['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']
        ticks[0]=1;validate_snapshot(store.snapshot(),allow_synthetic=True)
        raw['clock_at']=raw['projected_at']=store._state['clock_at']
        fee=deepcopy(raw['comparison_profiles'][q['comparison_input_refs']['refs']['fee']]['payload'])
        fee['rule']['expires_at']=(stamp(raw['clock_at'])+timedelta(seconds=10)).isoformat()
        key,value=profile('fee',fee);raw['comparison_profiles'][key]=value;q['comparison_input_refs']['refs']['fee']=key
        raw['state_revision']=2;self.assertTrue(store.commit(raw))
        self.assertEqual(packed(store.snapshot()),packed(serialize(raw,allow_synthetic=True)))
        ticks[0]=11;expired=store.snapshot();rows=snapshot_metrics(expired)['rows']
        self.assertFalse(next(r for r in rows if r['venue']=='kalshi')['net_ev']['eligible'])
        self.assertTrue(next(r for r in rows if r['venue']=='prophetx')['net_ev']['eligible'])
        self.assertTrue(snapshot_metrics(original)['rows'][0]['net_ev']['eligible'])
        retired=deepcopy(raw);retired['state_revision']=store._state['state_revision']+1
        retired['events']=[];self.assertTrue(store.commit(retired))
        delta=json.loads(store.encoded_changes(raw['runtime_id'],1))
        self.assertTrue(delta['removed_events'])

    def test_reference_future_at_receipt_never_gains_authority_and_native_binding(self):
        raw=software_fixture();q=raw['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']
        ref=deepcopy(raw['comparison_profiles'][q['comparison_input_refs']['refs']['reference']]['payload'])
        later=(stamp(raw['clock_at'])+timedelta(seconds=1)).isoformat()
        ref['outcomes'][0]['book_at']=later;ref['source_at'][0]=later
        key,value=profile('reference',ref);raw['comparison_profiles'][key]=value;q['comparison_input_refs']['refs']['reference']=key
        raw['clock_at']=raw['projected_at']=(stamp(raw['clock_at'])+timedelta(seconds=2)).isoformat()
        state=serialize(raw,allow_synthetic=True)
        result=next(r for r in snapshot_metrics(state)['rows'] if r['venue']=='kalshi')
        self.assertIn('reference_clock_future',result['net_ev']['reason'])
        # Arbs require no reference/probability distribution.
        self.assertTrue(snapshot_metrics(state)['pairs'][0]['buffered_minimum_return']['eligible'])
        raw=software_fixture();q=raw['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']
        identity=deepcopy(raw['comparison_profiles'][q['comparison_input_refs']['refs']['identity']]['payload'])
        identity['current_selection_binding']['participant']='NFL:TB'
        key,value=profile('identity',identity);raw['comparison_profiles'][key]=value;q['comparison_input_refs']['refs']['identity']=key
        result=next(r for r in snapshot_metrics(serialize(raw,allow_synthetic=True))['rows'] if r['venue']=='kalshi')
        self.assertIn('comparison_current_selection_attachment_conflict',result['net_ev']['reason'])

    def test_missing_receipt_is_local_and_evidenced_scope_association_required(self):
        raw=software_fixture();q=raw['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']
        q['times']['received_at']=None
        rows=snapshot_metrics(serialize(raw,allow_synthetic=True))['rows']
        self.assertIn('source_receipt_clock_unknown',next(r for r in rows if r['venue']=='kalshi')['net_ev']['reason'])
        self.assertTrue(next(r for r in rows if r['venue']=='prophetx')['net_ev']['eligible'])
        raw=software_fixture();q=raw['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']
        identity=deepcopy(raw['comparison_profiles'][q['comparison_input_refs']['refs']['identity']]['payload'])
        identity['current_scope_binding']['occurrence_id']='different-rematch'
        key,value=profile('identity',identity);raw['comparison_profiles'][key]=value;q['comparison_input_refs']['refs']['identity']=key
        row=next(r for r in snapshot_metrics(serialize(raw,allow_synthetic=True))['rows'] if r['venue']=='kalshi')
        self.assertIn('comparison_evidenced_occurrence_scope_attachment_required',row['net_ev']['reason'])

    def test_accepted_canonical_spread_total_and_period_attachment(self):
        from tests.test_comparison_net_ev import NetEVTests
        from app.dashboard.current_contract import binding_context
        NetEVTests.setUpClass();builder=NetEVTests()
        for name,market,predicate,line,participant in (
                ('Dallas -8.50','spread','cover','-8.5','NFL:DAL'),
                ('Combined over 20.5','total','over','20.5',None)):
            with self.subTest(name=name):
                raw=software_fixture();e=raw['events'][0];g=e['groups'][0];o=g['outcomes'][0];q=o['quotes']['kalshi']
                selected=builder.selections[name];payout=builder.profiles[name]
                g.update(market=market,line=line,anchor_participant='NFL:DAL' if market=='spread' else None)
                o.update(predicate=predicate,signed_line=line,participant=participant)
                q['binding']['selection']=binding_context(e,g,o)
                q['venue']=selected.native.venue
                q['source'].update(native_event_id=selected.native.event_id,native_market_id=selected.native.market_id,
                    native_outcome_id=selected.native.instrument_id,native_side=selected.native.side_id)
                q['original'].update(value=selected.price.amount.original,units=selected.price.unit)
                refs=q['comparison_input_refs']['refs'];identity=deepcopy(raw['comparison_profiles'][refs['identity']]['payload'])
                identity.update(selection=selected.to_dict(),rule_revision=payout.rule_revision,
                    completion_context=builder.context.to_dict(),current_selection_binding=deepcopy(q['binding']['selection']))
                identity['current_scope_binding'].update(period_boundary=g['period_boundary'],scope=selected.scope.to_dict())
                for kind,payload in (('identity',identity),('payout',payout.to_dict())):
                    key,value=profile(kind,payload);raw['comparison_profiles'][key]=value;refs[kind]=key
                bound,*_=typed_quote(q,raw['comparison_profiles'],stamp(raw['clock_at']),event=e,group=g,outcome=o)
                self.assertEqual(bound.selection.predicate.threshold.value,Fraction('17/2' if market=='spread' else '41/2'))
                g['period']='first_half'
                with self.assertRaisesRegex(ValueError,'market_scope_conflict'):
                    typed_quote(q,raw['comparison_profiles'],stamp(raw['clock_at']),event=e,group=g,outcome=o)

    def test_scheduled_fee_epoch_recalculates_once_without_price_packet(self):
        raw=software_fixture();q=raw['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']
        refs=q['comparison_input_refs']['refs'];fee=deepcopy(raw['comparison_profiles'][refs['fee']]['payload'])
        fee['rule']['terms']['rate']='0.07';fee['engine_registry']['schedules'][0]['coefficient']='0.07'
        after=(stamp(raw['clock_at'])+timedelta(seconds=10)).isoformat()
        fee['engine_context']['kalshi_metadata']['series_changes'].append(dict(scheduled_ts=after,
            fee_type='quadratic',fee_multiplier='2'))
        key,value=profile('fee',fee);raw['comparison_profiles'][key]=value;refs['fee']=key
        ticks=[0];store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:ticks[0])
        initial=store.snapshot();old=next(r for r in snapshot_metrics(initial)['rows'] if r['venue']=='kalshi')
        self.assertEqual(Fraction(old['net_ev']['details']['entry_fee_usd']),Fraction('3.3432'))
        ticks[0]=11;changed=store.snapshot();new=next(r for r in snapshot_metrics(changed)['rows'] if r['venue']=='kalshi')
        self.assertEqual(Fraction(new['net_ev']['details']['entry_fee_usd']),Fraction('6.6864'))
        self.assertEqual(old['quote_revision'],new['quote_revision'])
        self.assertNotEqual(old['net_ev']['basis']['dependency_revisions'],new['net_ev']['basis']['dependency_revisions'])
        validate_snapshot(changed,allow_synthetic=True)
        revision=changed['state_revision'];ticks[0]=12
        self.assertEqual(store.snapshot()['state_revision'],revision)
        validate_snapshot(store.snapshot(),allow_synthetic=True)


class MetricRoutes(AioHTTPTestCase):
    async def test_default_and_optional_sizes_use_same_metric_assembly(self):
        from app.comparison import current_metrics
        raw=software_fixture()
        with patch.object(current_metrics,'apply_group_metrics',wraps=current_metrics.apply_group_metrics) as assembly:
            serialize(raw,allow_synthetic=True)
        self.assertEqual(assembly.call_count,sum(len(e['groups']) for e in raw['events']))
        store=self.app[CURRENT_KEY];before=store.encoded_snapshot()
        for size in ('20','100'):
            with self.subTest(size=size):
                with patch.object(current_metrics,'apply_group_metrics',wraps=current_metrics.apply_group_metrics) as assembly:
                    response=await self.client.get('/api/comparison?ceiling='+size)
                self.assertEqual(response.status,200)
                self.assertEqual(assembly.call_count,sum(len(e['groups']) for e in raw['events']))
                result=await response.json()
                values={row['venue']:row for row in result['rows']}
                self.assertGreater(Fraction(values['kalshi']['net_ev']['value']),0)
                self.assertLess(Fraction(values['prophetx']['net_ev']['value']),0)
                self.assertEqual(store.encoded_snapshot(),before)

    async def get_application(self):
        raw=software_fixture();raw['state_revision']=2
        app=create_app(owner=owner(),sessions={},current_provider=InjectedTestProvider(raw))
        app[CURRENT_KEY].monotonic=lambda:0
        app[CURRENT_KEY]._age_origin=0
        return app

    async def test_readonly_views_size_filters_and_coverage_same_revision(self):
        first=await (await self.client.get('/api/current')).json()
        before=packed(self.app[CURRENT_KEY]._state)
        view=await (await self.client.get('/api/comparison?view=ev')).json()
        self.assertEqual(view['state_revision'],first['state_revision'])
        self.assertEqual(view['acquisition_requests'],0)
        sized=await (await self.client.get('/api/comparison?ceiling=20')).json()
        row=next(r for r in sized['rows'] if r['venue']=='kalshi')
        self.assertEqual(row['net_ev']['basis']['size_basis']['ceiling_usd'],'20')
        self.assertEqual(row['net_ev']['basis']['capital_denominator'],'0.4')
        self.assertEqual(packed(self.app[CURRENT_KEY]._state),before)
        # Follow the real navigation destination, rather than testing only the
        # namespaced route directly. The retained pilot has a different page.
        import re
        for page in ('/','/ev','/arbs'):
            html=await (await self.client.get(page)).text()
            link=re.search(r'href="([^"]+)">Coverage</a>',html)
            self.assertIsNotNone(link)
            destination=await (await self.client.get(link[1])).text()
            self.assertIn('Sport and execution-source coverage',destination)
            self.assertNotIn('Start pilot',destination)
        coverage=await (await self.client.get('/api/coverage?league=NFL')).json()
        self.assertEqual(coverage['state_revision'],view['state_revision'])
        self.assertEqual(coverage['acquisition_requests'],0)
        self.assertEqual((await self.client.get('/api/comparison?ceiling=0')).status,422)
        minimum=await (await self.client.get('/api/comparison?ceiling=0.4')).json()
        self.assertIn('capital_ceiling_below_adverse_funded_native_minimum',
            next(r for r in minimum['rows'] if r['venue']=='kalshi')['net_ev']['reason'])
