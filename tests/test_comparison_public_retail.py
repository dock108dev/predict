"""Retained authentic market metadata; no book, current event, price clock or net proof."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction
import json
import unittest
from aiohttp.test_utils import AioHTTPTestCase

from app.comparison.public_retail import retained, validate, registry, entry_example, observation_audit
from app.comparison.current_dependencies import digest, instant, references
from app.dashboard.current_contract import serialize, quotes_of
from app.dashboard.current_normalized import catalog_from_normalized
from app.dashboard.current_state import CURRENT_KEY
from app.dashboard.multi_game_server import create_app
from tests.current_fixture import fixture, InjectedTestProvider
from tests.test_current_state import owner
from tests.test_comparison_source_inputs import context
from app.comparison.source_inputs import produce


def base_registry():
    return {'version':'comparison-selected-applicability-1','records':[]}


def state(value=None, at=None):
    value=retained() if value is None else value
    env=fixture();env.update(mode='current',clock_at=at or value['receipt']['response_at'],projected_at=at or value['receipt']['response_at'])
    return catalog_from_normalized(env,[value['normalized_record']],selected_applicability=registry(base_registry(),value))


def quote(raw):
    return next(q for e in raw['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o))


def reversion(value):
    value['binding']['binding_version']=digest({k:v for k,v in value['binding'].items() if k!='binding_version'})
    value['binding_version']=digest({k:v for k,v in value.items() if k!='binding_version'})
    return value


class RetailInputs(unittest.TestCase):
    def test_decimal_grid_and_payout_admission_preserve_source_unknown(self):
        value=retained();raw=state();q=quote(serialize(raw));profiles=references(q,raw['comparison_profiles'])
        self.assertEqual(q['original']['value'],'0.2350')
        self.assertIsNone(q['times']['source_at'])
        grid=profiles['quantity']['payload']
        self.assertEqual(grid['unit'],{'unit':'dollar_face_contracts','face_usd_per_native':'1'})
        self.assertEqual((grid['grid']['minimum_native'],grid['grid']['increment_native'],grid['grid']['legal_price_tick']),('0.01','0.01','0.0025'))
        self.assertEqual(Fraction(grid['native_price']),Fraction(47,200))
        payout=profiles['payout']['payload']
        self.assertEqual(payout['equal']['value'],'0.50')
        self.assertIsNone(payout['noncompleted']['value'])
        self.assertEqual(q['source']['native_outcome_id'],'2165646')
        self.assertEqual(value['metadata']['sibling']['id'],'2165647')
        self.assertFalse(q['calculations']['net_ev']['eligible'])
        self.assertEqual(q['comparison_input_status']['probability']['status'],'absent')
        for reason in ['source_clock_unknown','exact_pinnacle_opposition_absent','mandatory_settlement_and_other_charges_unqualified','selection_binding_unverified']:
            self.assertIn(reason,q['calculations']['net_ev']['reason'])

    def test_literal_public_entry_vectors_and_deployed_cash(self):
        value=retained();entry=entry_example(value)
        self.assertEqual(Fraction(entry['raw_entry_fee_usd']),Fraction('1.24943625'))
        self.assertEqual(entry['entry_fee_usd'],'1.25')
        self.assertEqual(Fraction('100')*Fraction('0.2350')+Fraction(entry['entry_fee_usd']),Fraction('24.75'))
        high=entry_example(value,'404.04');above=entry_example(value,'404.05')
        self.assertEqual(Fraction('404.04')*Fraction('0.2350')+Fraction(high['entry_fee_usd']),Fraction('99.9994'))
        self.assertGreater(Fraction('404.05')*Fraction('0.2350')+Fraction(above['entry_fee_usd']),100)
        self.assertIsNone(entry['settlement_fee_usd']);self.assertFalse(entry['net_qualified'])
        with self.assertRaisesRegex(ValueError,'off_grid'):entry_example(value,'0.015')

    def test_half_even_rounding_does_not_guess_account_precision(self):
        value=retained();value['metadata']['price']='0.50';value['metadata']['feeCoefficient']='0.02';reversion(value)
        self.assertEqual(entry_example(value,'1')['entry_fee_usd'],'0.00')
        self.assertEqual(entry_example(value,'3')['entry_fee_usd'],'0.02')

    def test_historical_quote_is_not_upgraded_or_reclocked(self):
        value=retained();old=value['original_historical_observation'];q=deepcopy(value['normalized_record']['quote'])
        q.update(original=old['original']);q['times'].update(source_at=old['source_at'],received_at=old['received_at']);q['provenance']['sha256']=old['provenance_sha256']
        before=deepcopy(q);audit=observation_audit(q,value)
        self.assertFalse(audit['historical_applicability']);self.assertEqual(q,before)
        record=deepcopy(value['normalized_record']);record['quote']=q
        result=produce(record,context(record,source_rules={'schema':1,'version':'comparison-source-rules-1','rules':[]})|{'selected_applicability':registry(base_registry(),value)},at=instant(value['receipt']['response_at']))
        self.assertIsNone(result['comparison_input_refs']['refs']['quantity'])
        self.assertIsNone(result['comparison_input_refs']['refs']['payout'])

    def test_sibling_cannot_borrow_selected_market_grid(self):
        value=retained();record=deepcopy(value['normalized_record']);record['quote']['source'].update(native_outcome_id='2165647',native_side='Short')
        result=produce(record,context(record)|{'selected_applicability':registry(base_registry(),value)},at=instant(value['receipt']['response_at']))
        self.assertNotEqual(result['gaps']['quantity']['status'],'available_and_bound')
        self.assertIsNone(observation_audit(record['quote'],value))

    def test_entry_fractional_grid_refuses_missing_unit_authority(self):
        value=retained();value['metadata']['quantity_alignment_authority']='undocumented';reversion(value)
        with self.assertRaisesRegex(ValueError,'engine_refused'):entry_example(value,'404.04')

    def test_partial_facet_does_not_erase_other_public_facets(self):
        value=retained();value['binding']['facets'].pop('payout');reversion(value)
        q=quote(state(value));self.assertEqual(q['comparison_input_status']['quantity']['status'],'available_and_bound')
        self.assertNotEqual(q['comparison_input_status']['payout']['status'],'available_and_bound')

    def test_metadata_interval_does_not_backdate_or_extend(self):
        value=retained()
        for at in [instant(value['binding']['effective_from'])-timedelta(microseconds=1),instant(value['binding']['effective_until'])]:
            q=quote(state(value,at.isoformat()))
            self.assertEqual(q['comparison_input_status']['quantity']['status'],'expired')
            self.assertIsNone(q['comparison_input_refs']['refs']['quantity'])

    def test_saved_qualified_profile_reports_expiry_without_price_refresh(self):
        from app.collection.current_comparison_inputs import attach
        value=retained();raw=state(value);original=deepcopy(quote(raw)['times'])
        raw['clock_at']=value['binding']['effective_until']
        raw['comparison_profiles']=attach(raw)
        q=quote(raw)
        self.assertEqual(q['comparison_input_status']['quantity']['status'],'expired')
        self.assertEqual(q['times'],original)
        self.assertFalse(quote(serialize(raw))['calculations']['net_ev']['eligible'])

    def test_wrong_unit_grid_and_material_refuse_locally(self):
        for change,reason in [('tick','decimal_grid_conflict'),('unit','decimal_contract_units_required'),('material','material_revision_unqualified')]:
            value=retained()
            if change=='tick':value['binding']['facets']['quantity']['value']['quantity_grid']['legal_price_tick']='0.005'
            elif change=='unit':value['binding']['facets']['quantity']['value']['unit']={'unit':'fixed_point_contracts','face_usd_per_native':'1','quantity_scale':'100','price_scale':'10000'}
            else:value['normalized_record']['comparison_source_metadata']['material_sha256']='b'*64
            reversion(value);q=quote(state(value))
            self.assertIn(reason,q['comparison_input_status']['quantity']['reason'])
            self.assertEqual(q['comparison_input_status']['payout']['status'],'available_and_bound' if change!='material' else 'applicability_unresolved')

    def test_metadata_revision_changes_profile_not_price(self):
        value=retained();before=state(value);oldq=quote(before)
        value['binding']['facts']['fee']['reason']='public_retail_new_mandatory_cost_review_pending';reversion(value)
        after=state(value);newq=quote(after)
        self.assertEqual(newq['original'],oldq['original']);self.assertEqual(newq['times'],oldq['times'])
        self.assertEqual(newq['revision'],oldq['revision'])
        self.assertNotEqual(newq['comparison_input_refs']['refs']['quantity'],oldq['comparison_input_refs']['refs']['quantity'])

    def test_record_revision_and_identity_conflict_fail(self):
        value=retained();value['metadata']['minimumTradeQty']='1'
        with self.assertRaisesRegex(ValueError,'revision_conflict'):validate(value)
        reversion(value);value['metadata']['instrument_id']='2165647';reversion(value)
        with self.assertRaisesRegex(ValueError,'identity_conflict'):validate(value)


class RetailRoutes(AioHTTPTestCase):
    async def get_application(self):
        self.raw=state();return create_app(owner=owner(),sessions={},current_provider=InjectedTestProvider(self.raw))

    async def test_authentic_metadata_profile_api_details_contract(self):
        store=self.app[CURRENT_KEY];store.monotonic=lambda:0;store._age_origin=0
        before=json.dumps(self.raw,sort_keys=True)
        current=await (await self.client.get('/api/current')).json()
        comparison=await (await self.client.get('/api/comparison')).json()
        self.assertEqual(current['state_revision'],comparison['state_revision'])
        q=quote(current);self.assertEqual(q['comparison_input_status']['quantity']['public_retail']['metadata']['minimumTradeQty'],'0.01')
        self.assertEqual(q['comparison_input_status']['fee']['public_entry_example']['entry_fee_usd'],'1.25')
        self.assertFalse(q['calculations']['net_ev']['eligible'])
        self.assertEqual((await self.client.get('/ev')).status,200)
        self.assertEqual(before,json.dumps(self.raw,sort_keys=True))


class FreshRetailBinding(unittest.TestCase):
    """Read-only genuine retained pair; clocks never become current acquisition."""
    def setUp(self):
        from pathlib import Path
        self.path=Path(__file__).resolve().parents[1]/'tests/fixtures/retained-retail'
        self.raw=json.loads((self.path/'projection.json').read_text())
        from app.comparison.public_retail import fresh_retained
        self.value=fresh_retained()

    def projected(self,raw=None):
        from app.collection.current_comparison_inputs import attach
        raw=deepcopy(self.raw if raw is None else raw)
        raw['comparison_profiles']=attach(raw)
        return raw

    def long(self,raw):
        return next(q for e in raw['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o) if q['source']['native_side']=='Long')

    def test_exact_receipts_and_documented_endpoint_field_pointers(self):
        from hashlib import sha256
        v=self.value;meta=v['metadata'];receipt=json.loads((self.path/'event-receipt.json').read_text())
        body=(self.path/'event-response.json').read_bytes()
        self.assertEqual(sha256(body).hexdigest(),receipt['wire_sha256'])
        self.assertEqual(receipt['wire_sha256'],receipt['decoded_sha256'])
        graph=json.loads(body,parse_float=str)
        market=graph['events'][0]['markets'][469]
        self.assertEqual(meta['market_pointer'],'/events/0/markets/469')
        self.assertEqual(meta['response_sha256'],receipt['wire_sha256'])
        for field in ('minimumTradeQty','orderPriceMinTickSize','feeCoefficient','description'):
            self.assertEqual(meta[field],market[field])
        frame=json.loads((self.path/'frame-receipt.json').read_text())
        self.assertEqual(v['binding']['observation']['received_at'],frame['received_at'])
        self.assertLess(instant(receipt['finished_at']),instant(frame['received_at']))

    def test_charge_notice_is_scoped_and_never_promotes_total_costs(self):
        from app.comparison.public_retail import charge_audit
        from hashlib import sha256
        from tests.test_comparison_reference_gap import raw as historical, selected
        raw=self.projected();q=self.long(serialize(raw));fees=q['comparison_input_status']['fee']
        audit=fees['charge_completeness']
        body=(self.path/'clearing-fees.pdf').read_bytes()
        self.assertEqual(audit['published_clearing']['sha256'],sha256(body).hexdigest())
        self.assertLess(instant(audit['published_clearing']['original_receipt_at']),instant(raw['clock_at']))
        self.assertFalse(audit['mandatory_charges_known']);self.assertEqual(audit['settlement_status'],'unknown')
        self.assertFalse(audit['published_clearing']['selected_total_cost_exemption'])
        self.assertEqual(set(audit['missing_facts']),{'settlement','additional_mandatory_charges','participant_channel','effective_date','basis_rounding'})
        self.assertEqual(references(q,raw['comparison_profiles'])['fee']['payload']['scope'],'standard_direct_site_retail')
        self.assertFalse(q['calculations']['net_ev']['eligible'])
        self.assertNotEqual(references(q,raw['comparison_profiles'])['fee'],references(self.long(self.raw),self.raw['comparison_profiles'])['fee'])
        for key, item in self.raw['comparison_profiles'].items():
            self.assertEqual(raw['comparison_profiles'][key], item)
        self.assertEqual(raw['comparison_profiles'],self.projected()['comparison_profiles'])
        self.assertIsNone(charge_audit(selected(historical())))
        changed=deepcopy(q);changed['revision']+=1;self.assertIsNone(charge_audit(changed))
        audit['missing_facts'].clear();self.assertTrue(charge_audit(q)['missing_facts'])
        expired=deepcopy(self.raw);expired['clock_at']='2026-10-09T22:58:06.160459+00:00'
        expired_q=self.long(serialize(self.projected(expired)))
        self.assertFalse(expired_q['calculations']['net_ev']['eligible'])
        self.assertEqual(expired_q['comparison_input_status']['quantity']['status'],'expired')
        self.assertIn('charge_completeness',expired_q['comparison_input_status']['fee'])

    def test_saved_observation_upgrades_only_supported_facets(self):
        before=deepcopy(self.raw);raw=self.projected();q=self.long(serialize(raw));profiles=references(q,raw['comparison_profiles'])
        for kind in ('quantity','payout'):
            self.assertEqual(q['comparison_input_status'][kind]['status'],'available_and_bound')
            self.assertEqual(profiles[kind]['expires_at'],'2026-10-09T22:58:06.160459+00:00')
        self.assertEqual(profiles['payout']['payload']['equal']['value'],'0.50')
        self.assertIsNone(profiles['payout']['payload']['noncompleted']['value'])
        self.assertEqual(profiles['quantity']['payload']['grid']['increment_native'],'0.01')
        self.assertEqual(q['original']['value'],'0.2350');self.assertEqual(q['revision'],2)
        self.assertEqual(q['times'],self.long(before)['times'])
        self.assertEqual(q['calculations']['ev']['display_value'],'+3.95 %')
        self.assertFalse(q['calculations']['net_ev']['eligible']);self.assertFalse(q['calculations']['conservative']['eligible'])
        self.assertIn('direct_site_cost_case_modeled_total_charges_unverified',q['calculations']['net_ev']['reason'])
        self.assertNotIn('public_retail_historical_applicability_unqualified',q['calculations']['net_ev']['reason'])
        self.assertEqual(q['comparison_input_status']['fee']['public_entry_example']['entry_fee_usd'],'1.25')
        self.assertFalse(q['comparison_input_status']['fee']['public_entry_example']['net_qualified'])
        self.assertTrue(q['comparison_input_status']['identity']['public_event']['status']=='available_and_bound')
        self.assertEqual(self.raw,before)
        for key,item in before['comparison_profiles'].items():
            if key in raw['comparison_profiles']:self.assertEqual(raw['comparison_profiles'][key],item)

    def test_modeled_after_cost_exact_arithmetic_and_expiry(self):
        from app.comparison.public_retail import direct_site_estimate, direct_site_case
        raw=self.projected();q=self.long(serialize(raw));at=instant(raw['clock_at'])
        result=q['calculations']['direct_site_estimate']
        self.assertTrue(result['eligible']);self.assertFalse(result['actual_net_qualified'])
        self.assertEqual(result['quantity'],'404.04');self.assertEqual(result['entry_fee_usd'],'5.05')
        self.assertEqual(Fraction(result['deployed_usd']),Fraction('99.9994'))
        p=Fraction(32,131);cost=Fraction('99.9994')
        self.assertEqual(Fraction(int(result['exact']['numerator']),int(result['exact']['denominator'])),
            (Fraction('404.04')*p-cost)/cost*100)
        small=direct_site_estimate(q,raw['comparison_profiles'],at,'20')
        self.assertTrue(small['eligible']);self.assertLessEqual(Fraction(small['deployed_usd']),20)
        for change in ('revision','price','clock','side'):
            changed=deepcopy(q)
            if change=='revision':changed['revision']+=1
            elif change=='price':changed['original']['value']='0.2375'
            elif change=='clock':changed['times']['source_at']='2026-10-09T22:42:46.669170Z'
            else:changed['source']['native_side']='Short'
            self.assertIsNone(direct_site_case(changed,at))
        expired=direct_site_estimate(q,raw['comparison_profiles'],instant(self.value['binding']['effective_until']))
        self.assertFalse(expired['eligible'])
        bad=deepcopy(q);bad['sharp_reference']=None
        self.assertFalse(direct_site_estimate(bad,raw['comparison_profiles'],at)['eligible'])
        predecessor=self.long(self.raw)['comparison_input_refs']['refs']['fee']
        self.assertIn(predecessor,raw['comparison_profiles'])

    def test_equal_price_history_and_changed_revision_never_borrow(self):
        from app.comparison.public_retail import exact_fresh
        from tests.test_comparison_reference_gap import raw as historical,selected
        old=selected(historical());self.assertEqual(old['original']['value'],'0.2350');self.assertEqual(old['revision'],9)
        self.assertFalse(exact_fresh(old))
        for field in ('revision','receipt','source','sha','side'):
            q=deepcopy(self.long(self.raw))
            if field=='revision':q['revision']+=1
            elif field=='receipt':q['times']['received_at']='2026-10-09T22:43:08.067433+00:00'
            elif field=='source':q['times']['source_at']='2026-10-09T03:55:16.261974+00:00'
            elif field=='sha':q['provenance']['sha256']='b'*64
            else:q['source'].update(native_outcome_id='2165647',native_side='Short')
            self.assertFalse(exact_fresh(q),field)

    def test_short_retains_its_independent_refusals(self):
        raw=self.projected();q=next(q for e in serialize(raw)['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o) if q['source']['native_side']=='Short')
        self.assertEqual(q['revision'],1);self.assertEqual(q['original']['value'],'0.7675')
        self.assertEqual(q['original']['native_value'],'0.2325')
        self.assertIsNone(q.get('sharp_reference'))
        self.assertNotEqual(q['comparison_input_status']['payout']['status'],'available_and_bound')
        self.assertFalse(q['calculations']['ev']['eligible'])
        self.assertNotIn('public_retail',q['comparison_input_status']['quantity'])

    def test_expired_and_before_receipt_keep_price_clocks(self):
        for at in [self.value['binding']['effective_until'],(instant(self.value['binding']['effective_from'])-timedelta(microseconds=1)).isoformat()]:
            raw=deepcopy(self.raw);raw['clock_at']=at;new=self.projected(raw);q=self.long(new)
            self.assertEqual(q['times'],self.long(self.raw)['times'])
            self.assertEqual(q['comparison_input_status']['quantity']['status'],'expired')
            self.assertFalse(self.long(serialize(new))['calculations']['net_ev']['eligible'])

    def test_material_drift_refuses_only_affected_binding(self):
        from app.comparison.source_inputs import apply_selected
        raw=self.raw;q=self.long(raw);event=raw['events'][0];group=next(g for g in event['groups'] if any(q is x for o in g['outcomes'] for x in quotes_of(o)));outcome=next(o for o in group['outcomes'] if q in quotes_of(o))
        record=deepcopy(self.value['normalized_record']);record['comparison_source_metadata']['material_sha256']='b'*64
        result=dict(profiles={},comparison_input_refs=dict(refs={k:None for k in ('identity','payout','reference','fee','quantity','buffer','probability')},phase='unknown'),gaps={})
        apply_selected(result,record,dict(quote=q,event=event,group=group,outcome=outcome,selected_applicability=registry(base_registry())),instant(raw['clock_at']))
        self.assertIsNone(result['comparison_input_refs']['refs']['quantity'])
        self.assertIn('material_revision_unqualified',result['gaps']['quantity']['reason'])
        self.assertIsNone(result['comparison_input_refs']['refs']['fee'])

    def test_receipt_and_revision_conflicts_are_rejected_even_rehashed(self):
        for field in ('receipt','revision','pointer','interval'):
            v=deepcopy(self.value)
            if field=='receipt':v['receipt']['sha256']='b'*64
            elif field=='revision':v['binding']['quote_revision']=3
            elif field=='pointer':v['metadata']['side_pointer']='/events/0/markets/469/marketSides/1'
            else:v['binding']['effective_until']='2026-10-09T23:58:06.160459+00:00'
            reversion(v)
            with self.assertRaises(ValueError):validate(v)

    def test_ordinary_sink_receiving_produces_same_grid_without_clock_changes(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from app.collection.current_sink import normalized_records
        cat=json.loads((self.path/'catalog.json').read_text());book=json.loads((self.path/'book.json').read_text())
        projection=SimpleNamespace(invalid=set(),inventory={'polymarket_us':cat},books={('polymarket_us','129629','1083081'):{'book':book}})
        with patch('app.collection.current_occurrence.datetime') as clock:
            clock.now.return_value=instant(self.raw['clock_at'])
            rows,_=normalized_records(projection,self.raw['source_status'],{})
            original=rows[0];previous={original['_instrument']:dict(fingerprint=original['_fingerprint'],revision=2,original=original['quote']['original'],times=self.value['normalized_record']['quote']['times'])}
            rows,excluded=normalized_records(projection,self.raw['source_status'],previous)
        self.assertEqual(excluded,[])
        record=rows[0];record.pop('_instrument');record.pop('_fingerprint')
        # Replay is admitted through the ordinary normalizer, not a status flip.
        raw=catalog_from_normalized(self.raw,[record]);q=self.long(raw)
        self.assertEqual(q['comparison_input_status']['quantity']['status'],'available_and_bound')
        self.assertEqual(q['times'],self.long(self.raw)['times'])
        self.assertNotEqual(q['comparison_input_status']['fee']['status'],'available_and_bound')
        self.assertFalse(self.long(serialize(raw))['calculations']['net_ev']['eligible'])


class FreshRetailRoutes(AioHTTPTestCase):
    async def get_application(self):
        case=FreshRetailBinding();case.setUp();self.raw=case.projected()
        return create_app(owner=owner(),sessions={},current_provider=InjectedTestProvider(self.raw))

    async def test_retained_evaluation_same_revision_current_and_comparison(self):
        store=self.app[CURRENT_KEY];store.monotonic=lambda:0;store._age_origin=0
        current=await (await self.client.get('/api/current')).json();comparison=await (await self.client.get('/api/comparison')).json()
        self.assertEqual(current['state_revision'],comparison['state_revision'])
        self.assertEqual(current['runtime_id'],comparison['runtime_id'])
        row=next(r for r in comparison['rows'] if r['quote']['source']['native_side']=='Long')
        self.assertEqual(row['quote_revision'],2);self.assertEqual(row['gross']['display_value'],'+3.95 %')
        self.assertEqual(row['quote']['comparison_input_status']['quantity']['status'],'available_and_bound')
        self.assertFalse(row['net_ev']['eligible'])
        self.assertEqual((await self.client.get('/ev')).status,200)
