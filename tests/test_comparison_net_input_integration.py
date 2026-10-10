"""Ordinary retained admission and independent hypothetical-policy checks."""
from copy import deepcopy
from fractions import Fraction
import json
import unittest
from aiohttp.test_utils import AioHTTPTestCase
from app.comparison.current_dependencies import profile, eligibility
from app.dashboard.current_contract import quotes_of, serialize, stamp
from app.dashboard.current_state import CURRENT_KEY
from app.dashboard.multi_game_server import create_app
from tests.comparison_fixture import software_fixture
from tests.comparison_retained_review import retained_inputs, RetainedProvider
from tests.test_current_state import owner


def quotes(raw):
    return [q for e in raw['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)]


class InputPolicyTests(unittest.TestCase):
    def test_modeled_one_order_retains_literal_math_without_observed_fills(self):
        raw=software_fixture()
        for q in quotes(raw):
            refs=q['comparison_input_refs']['refs'];old=raw['comparison_profiles'][refs['quantity']]['payload']
            quantity=deepcopy(old)
            quantity['fill_inputs']['basis']='hypothetical_one_order'
            quantity['fill_partition_basis']='modeled_one_order_not_observed'
            key,value=profile('quantity',quantity);raw['comparison_profiles'][key]=value;refs['quantity']=key
        state=serialize(raw,allow_synthetic=True)
        by_venue={q['venue']:q for q in quotes(state)}
        self.assertEqual(Fraction(by_venue['kalshi']['calculations']['net_ev']['value']),50)
        exact=by_venue['prophetx']['calculations']['net_ev']['exact']
        self.assertEqual(Fraction(int(exact['numerator']),int(exact['denominator'])),Fraction(-300,11))
        for q in quotes(state):
            self.assertEqual(q['calculations']['net_ev']['details']['fill_basis'],'hypothetical_one_order')
            self.assertEqual(q['calculations']['net_ev']['details']['fill_partition_basis'],'modeled_one_order_not_observed')

    def test_bound_partial_fact_is_not_calculation_applicability(self):
        raw=software_fixture();q=quotes(raw)[0]
        q['comparison_input_status']={'fee':dict(status='applicability_unresolved',reason='execution_channel_unverified')}
        self.assertIn('execution_channel_unverified',eligibility(q,raw['comparison_profiles'],stamp(raw['clock_at'])))
        state=serialize(raw,allow_synthetic=True)
        self.assertFalse(quotes(state)[0]['calculations']['net_ev']['eligible'])
        self.assertTrue(quotes(state)[1]['calculations']['net_ev']['eligible'])

    def test_original_retained_prices_clocks_and_side_ids_survive(self):
        raw=retained_inputs(historical=True);state=serialize(raw)
        native={q['venue']:q for q in quotes(state) if q['venue'] in ('kalshi','polymarket_us')}
        self.assertEqual(set(native),{'kalshi','polymarket_us'})
        for q in quotes(state):
            self.assertTrue(q.get('comparison_input_refs'))
            self.assertTrue(q.get('comparison_input_status'))
            self.assertFalse(q['calculations']['net_ev']['eligible'])
            self.assertNotIn('comparison_inputs_unbound',q['calculations']['net_ev']['reason'])
        gross=[q for q in quotes(state) if q['venue']=='novig' and q['source']['native_outcome_id']=='Toronto Maple Leafs'][0]
        self.assertEqual(gross['original']['value'],'2.53')
        self.assertEqual(gross['times']['source_at'],'2026-10-08T23:52:47Z')
        # Original odds 2.47 / 1.61 imply selected p=161/408, quote return 253/100.
        metric=gross['calculations']['ev'];exact=metric['exact']
        self.assertTrue(metric['eligible'])
        self.assertEqual(Fraction(int(exact['numerator']),int(exact['denominator'])),Fraction(-67,408))
        self.assertIn('fees excluded',metric['scope'])
        current=serialize(retained_inputs())
        self.assertTrue(all(not q['calculations']['net_ev']['eligible'] for q in quotes(current)))
        self.assertTrue(all(not q['calculations']['ev']['eligible'] for q in quotes(current)))


class RetainedRoutes(AioHTTPTestCase):
    async def get_application(self):
        self.provider=RetainedProvider(retained_inputs(historical=True))
        return create_app(owner=owner(),sessions={},current_provider=self.provider)

    async def test_same_revision_read_only_routes_and_details(self):
        store=self.app[CURRENT_KEY];store.monotonic=lambda:0;store._age_origin=0
        current=await (await self.client.get('/api/current')).json()
        comparison=await (await self.client.get('/api/comparison')).json()
        self.assertEqual(current['runtime_id'],comparison['runtime_id'])
        self.assertEqual(current['state_revision'],comparison['state_revision'])
        for path in ('/','/ev','/arbs','/current/coverage'):
            self.assertEqual((await self.client.get(path)).status,200)
        self.assertEqual(self.provider.status()['odds_api_requests'],0)
        self.assertFalse(self.provider.status()['dispatch_enabled'])
        self.assertTrue(comparison['rows'])
        self.assertTrue(all(r['net_ev']['reason'] for r in comparison['rows']))
        self.assertEqual(json.dumps(self.provider.initial_state(),sort_keys=True),json.dumps(self.provider.raw,sort_keys=True))


class SelectedAdmissionRoutes(AioHTTPTestCase):
    async def get_application(self):
        from tests.test_comparison_source_inputs import native_records, SelectedApplicability, AT
        from app.dashboard.current_normalized import catalog_from_normalized
        from tests.current_fixture import fixture, InjectedTestProvider
        self.at=AT
        records=native_records()
        self.record=records[0]
        self.record['quote']['original']['value']='0.2350'
        authored=SelectedApplicability()
        self.registry=authored.selected(self.record,{'quantity':authored.grid(self.record)})
        envelope=fixture();envelope.update(clock_at=AT.isoformat(),projected_at=AT.isoformat())
        records=[{k:deepcopy(v) for k,v in r.items() if not k.startswith('_')} for r in records]
        self.raw=catalog_from_normalized(envelope,records,selected_applicability=self.registry)
        return create_app(owner=owner(),sessions={},current_provider=InjectedTestProvider(self.raw))

    async def test_ordinary_admission_selected_partial_grid_to_API(self):
        store=self.app[CURRENT_KEY];store.monotonic=lambda:0;store._age_origin=0
        current=await (await self.client.get('/api/current')).json()
        comparison=await (await self.client.get('/api/comparison')).json()
        q=next(q for q in quotes(current) if q['source']==self.record['quote']['source'])
        self.assertEqual(q['original']['value'],'0.2350')
        self.assertEqual(q['times']['source_at'],self.record['quote']['times']['source_at'])
        self.assertEqual(q['comparison_input_status']['quantity']['status'],'contradictory')
        key=q['comparison_input_refs']['refs']['quantity']
        self.assertEqual(self.raw['comparison_profiles'][key]['payload']['native_price'],'2350')
        self.assertEqual(self.raw['comparison_profiles'][key]['payload']['unit']['price_scale'],'10000')
        # Partial legal units cannot silently qualify hypothetical payout/fee units.
        self.assertFalse(q['calculations']['net_ev']['eligible'])
        self.assertIn('source_selected_fee_quantity_unit_conflict',q['calculations']['net_ev']['reason'])
        self.assertEqual(current['state_revision'],comparison['state_revision'])
        sibling=next(q for q in quotes(current) if q['source']!=self.record['quote']['source'])
        self.assertEqual(sibling['original']['value'],'0.50')
        self.assertNotIn('binding_version',sibling['comparison_input_status']['quantity'])
