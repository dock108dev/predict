"""Ordinary admission producer: retained metadata + authored books, never live proof."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from fractions import Fraction
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.collection.current_sink import normalized_records
from app.collection.current_aggregate_admission import admit
from app.collection.current_benchmark import attach, key
from app.comparison.current_dependencies import references, validate_profiles, eligibility
from app.comparison.current_metrics import calculate_quote
from app.comparison.source_inputs import produce
from app.dashboard.current_normalized import catalog_from_normalized
from tests.current_fixture import fixture
from tests.test_current_occurrence import book
from tests.test_current_aggregate import body

ROOT=Path(__file__).resolve().parents[1]
AT=datetime(2026,10,8,12,tzinfo=timezone.utc)


def rules():
    return json.loads((ROOT/'app/fixtures/comparison-source-rules-v1.json').read_text())


def native_records(venue='polymarket_us'):
    cats=json.loads((ROOT/'tests/fixtures/current-buccaneers-cowboys-retained.json').read_text())['catalogs']
    cat=cats[venue]
    books={}
    for m in cat['markets']:
        b=book(venue,m,AT.isoformat())
        for side in b['outcomes']:side['asks']['levels'][0]['price']['value']='0.50'
        books[(venue,m['event_id'],m['id'])]={'book':b}
    projection=SimpleNamespace(inventory={venue:cat},books=books,invalid=set())
    with patch('app.collection.current_occurrence.datetime') as clock, patch('app.collection.current_sink.utc',return_value=AT.isoformat()):
        clock.now.return_value=AT
        records,excluded=normalized_records(projection,{venue:{'state':'available'}},{})
    if excluded:raise AssertionError(excluded)
    for record in records:
        record['quote']['provenance'].update(mode='synthetic', real_source=False)
    return records


def context(record, source_rules=None, reference_records=None):
    clean={k:deepcopy(v) for k,v in record.items() if not k.startswith('_') and k!='comparison_source_metadata'}
    raw=catalog_from_normalized(fixture(),[clean])
    e=raw['events'][0];g=e['groups'][0]
    o=next(o for o in g['outcomes'] if record['quote']['venue'] in o['quotes'])
    q=o['quotes'][record['quote']['venue']]
    q['id']='authored:ordinary-producer-quote'
    return dict(event=e,group=g,outcome=o,quote=q,source_rules=rules() if source_rules is None else source_rules,
                reference_records=reference_records)


def authored_opposition(record):
    """Controlled reference fields atop retained metadata, not provider quotes."""
    rows=[]
    for desc in record['outcome_selections']:
        if desc['predicate']!='win':continue
        row=deepcopy(record);row['selection']=deepcopy(desc)
        q=row['quote'];q['venue']='pinnacle';q['source'].update(provider='the_odds_api',
            native_market_id='authored:reference:'+desc['participant'],native_outcome_id=desc['participant'],
            native_side='bookmaker_outcome')
        q['original']=dict(value='2' if desc['participant']==record['selection']['participant'] else '3',
            units='decimal_odds',payout='1',payout_units='USD',quantity_units='unknown',role='comparison')
        q['provenance']=dict(mode='synthetic',real_source=False,sha256='a'*64)
        q['times']=dict(source_at=AT.isoformat(),received_at=AT.isoformat(),projected_at=AT.isoformat(),source_time_kind='provider_book')
        rows.append(row)
    if len(rows)!=2:raise AssertionError('Two direct win descriptors required')
    attach([record],rows)
    return rows


class SourceInputs(unittest.TestCase):
    def test_retained_us_short_orientation_produced_from_admission(self):
        record=next(r for r in native_records() if r['quote']['source']['native_outcome_id']=='2059747')
        original=deepcopy(record);ctx=context(record)
        result=produce(record,ctx,at=AT)
        validate_profiles(result['profiles'])
        v=references(dict(comparison_input_refs=result['comparison_input_refs']),result['profiles'])
        self.assertEqual(set(v),{'identity','payout','fee','quantity','buffer','probability'})
        selected=v['identity']['payload']['selection']
        self.assertEqual(selected['native']['side_id'],'Short')
        self.assertEqual(selected['native']['instrument_id'],'2059747')
        self.assertEqual(selected['participant_id'],'NFL:DAL')
        self.assertEqual(selected['predicate']['operator'],'gt')
        self.assertIsNone(v['payout']['payload']['equal']['value'])
        self.assertIsNone(v['payout']['payload']['noncompleted']['value'])
        self.assertEqual(v['payout']['payload']['normal_condition']['kind'],'conditional_completed_result')
        quantity=v['quantity']['payload']
        self.assertEqual(quantity['fill_inputs']['basis'],'hypothetical_one_order')
        self.assertNotIn('depth',quantity)
        self.assertEqual(record,original)
        self.assertEqual(result['gaps']['reference']['status'],'absent')

    def test_native_reconstructed_reference_and_independent_net_oracle(self):
        record=next(r for r in native_records() if r['quote']['source']['native_outcome_id']=='2059747')
        refs=authored_opposition(record);ctx=context(record,reference_records=refs)
        result=produce(record,ctx,at=AT)
        q=deepcopy(ctx['quote']);q['comparison_input_refs']=result['comparison_input_refs'];q['comparison_input_status']=result['gaps']
        out,stress=calculate_quote(q,result['profiles'],AT,event=ctx['event'],group=ctx['group'],outcome=ctx['outcome'])
        self.assertTrue(out['eligible'],out['reason'])
        # $100 ceiling, reviewed US one-order .0695 model; .50 price,
        # conservative movement .01 limits base to189 contracts. $94.50
        # acquisition +$3.28 cent-half-even fee =97.78 capital; expected
        # payout .6*189=113.4, profit15.62. Exact percent=78100/4889.
        self.assertEqual(Fraction(out['basis']['capital_denominator']),Fraction('97.78'))
        self.assertEqual(Fraction(int(out['exact']['numerator']),int(out['exact']['denominator'])),Fraction(78100,4889))
        self.assertEqual(out['basis']['conditioning'],'completed_decisive_results_only')
        self.assertFalse(out['depth_qualified'])
        self.assertFalse(stress['eligible'])
        v=references(q,result['profiles'])['reference']['payload']
        self.assertEqual(v['source_at'],[AT.isoformat(),AT.isoformat()])
        self.assertEqual(len(v['original_source_keys']),2)
        self.assertTrue(all(x['selection']['native']['market_id'].startswith('declared-reference-group:') for x in v['outcomes']))

    def test_expired_source_rule_local_null_preserves_reference_policy(self):
        record=native_records()[0];source=rules()
        for row in source['rules']:row['expires_at']='2026-10-08T11:59:00Z'
        ctx=context(record,source_rules=source)
        result=produce(record,ctx,at=AT)
        self.assertEqual(result['gaps']['fee']['status'],'expired')
        self.assertIsNone(result['comparison_input_refs']['refs']['fee'])
        self.assertIsNotNone(result['comparison_input_refs']['refs']['buffer'])
        self.assertIsNotNone(result['comparison_input_refs']['refs']['probability'])

    def test_scope_conflict_and_integer_line_refuse_semantic_inputs(self):
        record=native_records()[0]
        record['comparison_source_metadata']={'overtime':'excluded'}
        result=produce(record,context(record),at=AT)
        self.assertEqual(result['gaps']['identity']['reason'],'source_overtime_scope_conflict')
        self.assertIsNone(result['comparison_input_refs']['refs']['identity'])
        record.pop('comparison_source_metadata')
        record['market_identity'].update(family='spread',line='-8')
        result=produce(record,context(native_records()[0]),at=AT)
        self.assertEqual(result['gaps']['identity']['reason'],'integer_line_push_inputs_unqualified')

    def test_conflicting_native_ids_and_stale_metadata_are_local(self):
        record=native_records()[0];ctx=context(record)
        ctx['quote']['source']['native_outcome_id']='wrong-side'
        result=produce(record,ctx,at=AT)
        self.assertEqual(result['gaps']['identity']['status'],'contradictory')
        self.assertEqual(result['gaps']['identity']['reason'],'ordinary_source_native_attachment_conflict')
        record['comparison_source_metadata']={'effective_until':'2026-10-08T11:00:00Z'}
        result=produce(record,context(record),at=AT)
        self.assertEqual(result['gaps']['identity']['status'],'expired')

    def test_quantity_grid_gap_does_not_blank_payout_or_fee(self):
        record=native_records()[0];source=rules()
        for row in source['rules']:
            if row['venue']=='polymarket_us':row['quantity_grid']['increment_native']=None
        result=produce(record,context(record,source_rules=source),at=AT)
        self.assertEqual(result['gaps']['quantity']['reason'],'native_quantity_grid_incomplete')
        self.assertIsNotNone(result['comparison_input_refs']['refs']['payout'])
        self.assertIsNotNone(result['comparison_input_refs']['refs']['fee'])

    def test_kalshi_exact_series_hypothesis_scopes_engine_metadata(self):
        record=next(r for r in native_records('kalshi') if r['selection']['predicate']=='win')
        record.pop('comparison_source_metadata',None)
        missing=produce(record,context(record),at=AT)
        self.assertEqual(missing['gaps']['fee']['reason'],'source_series_fee_scope_missing')
        # Retained game series is an exact source catalog fact for this example.
        record['comparison_source_metadata']={'series_id':'KXNFLGAME'}
        result=produce(record,context(record),at=AT)
        self.assertEqual(result['gaps']['fee']['status'],'available_and_bound')
        payload=references(dict(comparison_input_refs=result['comparison_input_refs']),result['profiles'])['fee']['payload']
        self.assertEqual(payload['engine_context']['event_id'],record['quote']['source']['native_event_id'])
        self.assertEqual(payload['engine_context']['kalshi_metadata']['series_id'],'KXNFLGAME')
        self.assertTrue(payload['engine_context']['kalshi_metadata']['source'].startswith('modeled:'))

    def test_aggregate_admission_reference_and_channel_do_not_borrow_novig_v3(self):
        payload=body('NFL',books=('novig','pinnacle'),at=AT.isoformat())
        records=admit(payload,'NFL',AT.isoformat())
        target=next(r for r in records if r['quote']['venue']=='novig' and r['market_identity']['family']=='moneyline')
        refs=[r for r in records if r['quote']['venue']=='pinnacle' and r['market_identity']==target['market_identity']]
        attach([target],refs)
        target['comparison_source_metadata']={'overtime':'included'}
        result=produce(target,context(target,reference_records=refs),at=AT)
        self.assertIsNone(result['comparison_input_refs']['refs']['fee'])
        self.assertEqual(result['gaps']['fee']['reason'],'source_channel_rule_not_established')
        self.assertIsNotNone(result['comparison_input_refs']['refs']['reference'])
        self.assertIsNotNone(result['comparison_input_refs']['refs']['probability'])

    def test_real_receipt_keeps_named_hypothesis_visible_but_net_withheld(self):
        record=next(r for r in native_records() if r['quote']['source']['native_outcome_id']=='2059747')
        refs=authored_opposition(record)
        record['quote']['provenance'].update(mode='current',real_source=True)
        result=produce(record,context(record,reference_records=refs),at=AT)
        for kind in ('payout','fee','quantity'):
            self.assertIsNotNone(result['comparison_input_refs']['refs'][kind])
            self.assertEqual(result['gaps'][kind]['status'],'applicability_unresolved')

    def test_reference_opposition_mismatch_and_revision_expiry(self):
        record=next(r for r in native_records() if r['quote']['source']['native_outcome_id']=='2059747')
        refs=authored_opposition(record);ctx=context(record,reference_records=refs)
        good=produce(record,ctx,at=AT)
        refs[0]['quote']['original']['value']='5'
        bad=produce(record,ctx,at=AT)
        self.assertEqual(bad['gaps']['reference']['reason'],'pinnacle_original_input_conflict')
        self.assertIsNone(bad['comparison_input_refs']['refs']['reference'])
        q=deepcopy(ctx['quote']);q['comparison_input_refs']=good['comparison_input_refs']
        reasons=eligibility(q,good['profiles'],AT+timedelta(seconds=901))
        self.assertIn('reference_expired',reasons)
        self.assertIn('source_price_expired',reasons)
        self.assertEqual(q['times']['source_at'],AT.isoformat())
        later=produce(record,context(record,reference_records=authored_opposition(record)),at=AT+timedelta(seconds=1))
        self.assertEqual(good['comparison_input_refs']['refs']['payout'],later['comparison_input_refs']['refs']['payout'])

    def test_aggregate_half_line_stake_payout_and_scope_local_block(self):
        at=datetime(2026,10,9,4,tzinfo=timezone.utc)
        records=admit(body('NFL',books=('prophetx','pinnacle'),at=at.isoformat()),'NFL',at.isoformat())
        for family in ('spread','total'):
            target=next(r for r in records if r['quote']['venue']=='prophetx' and r['market_identity']['family']==family)
            refs=[r for r in records if r['quote']['venue']=='pinnacle' and r['market_identity']==target['market_identity']]
            attach([target],refs)
            ctx=context(target,reference_records=refs)
            result=produce(target,ctx,at=at)
            self.assertEqual(result['gaps']['identity']['status'],'available_and_bound',result['gaps'])
            v=references(dict(comparison_input_refs=result['comparison_input_refs']),result['profiles'])
            payout=v['payout']['payload']
            decisive=[payout[k]['value'] for k in ('below','above')]
            self.assertIn('2',decisive)
            self.assertIsNone(payout['equal']['value'])
            self.assertEqual(payout['payout_unit'],'usd_per_usd_stake')
            self.assertEqual(result['gaps']['reference']['status'],'available_and_bound',result['gaps']['reference'])
            self.assertEqual(v['reference']['payload']['conditioning'],'decisive_win_loss')
        target['market_identity']['period']='first_half'
        blocked=produce(target,ctx,at=at)
        self.assertEqual(blocked['gaps']['identity']['reason'],'source_market_scope_unsupported')


if __name__=='__main__':unittest.main()


class SelectedApplicability(unittest.TestCase):
    """Controlled selected records prove the seam, never authentic net eligibility."""
    def selected(self,record,facets=None):
        from app.comparison.source_inputs import observation, SELECTED_VERSION
        from app.comparison.current_dependencies import digest
        row=dict(native_key=observation(record['quote'])['native_key'],observation=observation(record['quote']),
            effective_from='2026-10-01T00:00:00Z',effective_until='2026-10-16T00:00:00Z',
            facets=facets or {},facts={})
        row['binding_version']=digest(row)
        return dict(version=SELECTED_VERSION,records=[row])

    def reversion(self,registry):
        from app.comparison.current_dependencies import digest
        for row in registry['records']:
            row['binding_version']=digest({k:v for k,v in row.items() if k!='binding_version'})
        return registry

    def grid(self,record,tick='50'):
        ev=dict(ref='authored:selected-US-refdata',sha256='b'*64,evidence_class='authored')
        return dict(evidence=[ev],value=dict(unit=dict(unit='fixed_point_contracts',face_usd_per_native='1',
            quantity_scale='1',price_scale='10000'),quantity_grid=dict(minimum_native='1',increment_native='1',
            legal_price_tick=tick,evidence=ev),quantity_grid_authority='selected_authored_refdata'))

    def test_exact_02350_grid_survives_missing_fee_and_scope(self):
        record=native_records()[0];record['quote']['original']['value']='0.2350'
        registry=self.selected(record,{'quantity':self.grid(record)})
        ctx=context(record,source_rules=dict(schema=1,version='comparison-source-rules-1',rules=[]))
        ctx['selected_applicability']=registry
        result=produce(record,ctx,at=AT)
        v=references(dict(comparison_input_refs=result['comparison_input_refs']),result['profiles'])
        self.assertEqual(v['quantity']['payload']['native_price'],'2350')
        self.assertEqual(v['quantity']['payload']['fills'][0]['price'],'0.235')
        self.assertEqual(record['quote']['original']['value'],'0.2350')
        self.assertEqual(result['gaps']['quantity']['status'],'available_and_bound')
        self.assertIsNone(result['comparison_input_refs']['refs']['fee'])
        self.assertIsNotNone(result['comparison_input_refs']['refs']['buffer'])

    def test_whole_cent_tick_refuses_original_quote_without_rounding(self):
        record=native_records()[0];record['quote']['original']['value']='0.2350'
        ctx=context(record);ctx['selected_applicability']=self.selected(record,{'quantity':self.grid(record,tick='100')})
        result=produce(record,ctx,at=AT)
        self.assertEqual(result['gaps']['quantity']['reason'],'source_price_off_legal_grid')
        self.assertIsNotNone(result['comparison_input_refs']['refs']['payout'])
        self.assertEqual(record['quote']['original']['value'],'0.2350')

    def test_original_revision_expiry_digest_and_sibling_are_local(self):
        record=native_records()[0];registry=self.selected(record,{'quantity':self.grid(record)})
        for mutation,reason in [('price','source_selected_observation_revision_unqualified'),
                ('expiry','source_selected_binding_expired_or_not_effective'),
                ('digest','source_selected_binding_digest_conflict')]:
            with self.subTest(mutation=mutation):
                selected=deepcopy(registry);target=deepcopy(record)
                if mutation=='price':target['quote']['original']['value']='0.51'
                elif mutation=='expiry':
                    selected['records'][0]['effective_until']='2026-10-08T11:00:00Z';self.reversion(selected)
                else:selected['records'][0]['binding_version']='0'*64
                ctx=context(target);ctx['selected_applicability']=selected
                result=produce(target,ctx,at=AT)
                self.assertEqual(result['gaps']['quantity']['reason'],reason)
                self.assertIsNotNone(result['comparison_input_refs']['refs']['buffer'])
        other=next(r for r in native_records() if r['quote']['source']['native_outcome_id']!=record['quote']['source']['native_outcome_id'])
        ctx=context(other);ctx['selected_applicability']=registry
        original=produce(other,context(other),at=AT)
        self.assertEqual(produce(other,ctx,at=AT),original)

    def test_global_flag_cannot_qualify_authentic_quote(self):
        record=native_records()[0];record['quote']['provenance'].update(mode='current',real_source=True)
        source=rules()
        for row in source['rules']:row['actual_account_net_qualified']=True
        result=produce(record,context(record,source_rules=source),at=AT)
        self.assertTrue(all(result['gaps'][kind]['status']!='available_and_bound' for kind in ('payout','fee','quantity')))

    def test_authored_facet_cannot_qualify_authentic_quote(self):
        record=native_records()[0];record['quote']['provenance'].update(mode='current',real_source=True)
        ctx=context(record);ctx['selected_applicability']=self.selected(record,{'quantity':self.grid(record)})
        result=produce(record,ctx,at=AT)
        self.assertEqual(result['gaps']['quantity']['reason'],'source_selected_authored_evidence_unqualified')

    def test_crossed_native_attachment_cannot_borrow_selected_grid(self):
        record=native_records()[0];ctx=context(record)
        ctx['selected_applicability']=self.selected(record,{'quantity':self.grid(record)})
        ctx['quote']['source']['native_outcome_id']='wrong'
        result=produce(record,ctx,at=AT)
        self.assertIsNone(result['comparison_input_refs']['refs']['quantity'])
        self.assertEqual(result['gaps']['identity']['reason'],'ordinary_source_native_attachment_conflict')

    def test_full_authored_selected_net_literal_vector(self):
        record=next(r for r in native_records() if r['quote']['source']['native_outcome_id']=='2059747')
        refs=authored_opposition(record);ctx=context(record,reference_records=refs)
        source=next(row for row in rules()['rules'] if row['venue']=='polymarket_us')
        ev=dict(ref='authored:selected-completed-terms',sha256='c'*64,evidence_class='authored')
        fee=deepcopy(source['fee_payload']);fee['rule']['unit']=self.grid(record)['value']['unit']
        fee['rule'].update(event_id=record['quote']['source']['native_event_id'],market_id=record['quote']['source']['native_market_id'])
        facets=dict(quantity=self.grid(record,tick='100'),fee=dict(evidence=[ev],value=dict(fee_payload=fee)),
            payout=dict(evidence=[ev],value=dict(payout=deepcopy(source['payout']))),
            phase=dict(evidence=[ev],value='pregame'))
        ctx['selected_applicability']=self.selected(record,facets)
        result=produce(record,ctx,at=AT);q=deepcopy(ctx['quote'])
        q['comparison_input_refs']=result['comparison_input_refs'];q['comparison_input_status']=result['gaps']
        out,stress=calculate_quote(q,result['profiles'],AT,event=ctx['event'],group=ctx['group'],outcome=ctx['outcome'])
        self.assertTrue(out['eligible'],out['reason'])
        # Independent literal:189*$0.50=$94.50; half-even one-order fee=$3.28;
        # actual deployed=$97.78; .6*189-$97.78=$15.62; percent=78100/4889.
        self.assertEqual(Fraction(out['basis']['capital_denominator']),Fraction('97.78'))
        self.assertEqual(Fraction(int(out['exact']['numerator']),int(out['exact']['denominator'])),Fraction(78100,4889))
        self.assertFalse(out['depth_qualified']);self.assertFalse(stress['eligible'])

    def test_native_reference_fields_are_independent_and_metadata_revision_coherent(self):
        from app.dashboard.session_projection import stable
        cats=json.loads((ROOT/'tests/fixtures/current-buccaneers-cowboys-retained.json').read_text())['catalogs']
        cat=deepcopy(cats['polymarket_us']);market=cat['markets'][0]
        native=market['sides'][0]['id']
        market['_native']={'instruments':[dict(id=native,priceScale=10000,minimumTradeQty=1,tickSize=50)]}
        books={( 'polymarket_us',m['event_id'],m['id']):dict(book=book('polymarket_us',m,AT.isoformat())) for m in cat['markets']}
        projection=SimpleNamespace(inventory={'polymarket_us':cat},books=books,invalid=set())
        with patch('app.collection.current_occurrence.datetime') as clock,patch('app.collection.current_sink.utc',return_value=AT.isoformat()):
            clock.now.return_value=AT
            records,_=normalized_records(projection,{'polymarket_us':{'state':'available'}},{})
            target=next(r for r in records if r['quote']['source']['native_outcome_id']==native)
            data=target['comparison_source_metadata']['selected_reference_data']
            self.assertEqual(data['values']['priceScale'],10000)
            self.assertNotIn('fractionalQtyScale',data['values'])
            sibling=next(r for r in records if r['quote']['source']['native_outcome_id']!=native)
            self.assertFalse(sibling['comparison_source_metadata']['selected_reference_data']['present'])
            previous={r['_instrument']:dict(fingerprint=r['_fingerprint'],revision=r['quote']['revision'],
                times=r['quote']['times'],original=r['quote']['original']) for r in records}
            before=target['quote']['times']['source_at'];fingerprint=target['_fingerprint']
            market['_native']['instruments'][0]['tickSize']=100
            changed,_=normalized_records(projection,{'polymarket_us':{'state':'available'}},previous)
            newer=next(r for r in changed if r['quote']['source']['native_outcome_id']==native)
            self.assertEqual(newer['quote']['revision'],target['quote']['revision'])
            self.assertEqual(newer['_fingerprint'],fingerprint)
            self.assertEqual(newer['quote']['times']['source_at'],before)
            self.assertEqual(newer['comparison_source_metadata']['selected_reference_data']['material_sha256'],stable(market['_native']['instruments'][0]))
            from app.dashboard.current_incremental import signature
            def project(row):
                clean={k:deepcopy(v) for k,v in row.items() if not k.startswith('_')}
                envelope=fixture();envelope.update(clock_at=AT.isoformat(),projected_at=AT.isoformat())
                return catalog_from_normalized(envelope,[clean])
            old_raw=project(target);new_raw=project(newer)
            old_event=old_raw['events'][0];new_event=new_raw['events'][0]
            self.assertNotEqual(signature(old_event,old_event['groups'][0],old_raw['comparison_profiles']),
                signature(new_event,new_event['groups'][0],new_raw['comparison_profiles']))

    def test_fractional_wire_minimum_cannot_claim_legal_fixed_point_grid(self):
        record=native_records()[0];facet=self.grid(record)
        facet['value']['quantity_grid']['minimum_native']='1.5'
        ctx=context(record);ctx['selected_applicability']=self.selected(record,{'quantity':facet})
        result=produce(record,ctx,at=AT)
        self.assertEqual(result['gaps']['quantity']['reason'],'source_native_wire_quantity_grid_conflict')

    def test_authentic_facet_requires_material_revision_and_exact_US_fields(self):
        record=native_records()[0];record['quote']['provenance'].update(mode='current',real_source=True)
        facet=self.grid(record);facet['evidence'][0]['evidence_class']='retained'
        registry=self.selected(record,{'quantity':facet});ctx=context(record);ctx['selected_applicability']=registry
        self.assertEqual(produce(record,ctx,at=AT)['gaps']['quantity']['reason'],'source_selected_material_revision_unqualified')
        registry['records'][0]['material_sha256']='d'*64;self.reversion(registry)
        record['comparison_source_metadata']={'material_sha256':'d'*64,
            'selected_reference_data':dict(present=True,instrument_id=record['quote']['source']['native_outcome_id'],
                market_id=record['quote']['source']['native_market_id'],values=dict(priceScale=10000,minimumTradeQty=1,tickSize=50))}
        ctx=context(record);ctx['selected_applicability']=registry
        result=produce(record,ctx,at=AT)
        self.assertEqual(result['gaps']['quantity']['status'],'available_and_bound')
        # This controlled authentic-shaped input is a boundary test; its other
        # selected actual costs/terms are unqualified, and no net is produced.
        self.assertNotEqual(result['gaps']['fee']['status'],'available_and_bound')
        record['comparison_source_metadata']['selected_reference_data']['values']['priceScale']=100
        result=produce(record,context(record)|{'selected_applicability':registry},at=AT)
        self.assertEqual(result['gaps']['quantity']['reason'],'source_selected_US_refdata_grid_conflict')
        record['comparison_source_metadata']['material_sha256']='e'*64
        result=produce(record,context(record)|{'selected_applicability':registry},at=AT)
        self.assertEqual(result['gaps']['quantity']['reason'],'source_selected_material_revision_unqualified')

    def test_factual_status_flip_cannot_qualify_named_actual_profiles(self):
        record=native_records()[0];record['quote']['provenance'].update(mode='current',real_source=True)
        registry=self.selected(record)
        registry['records'][0]['facts']={kind:dict(status='available_and_bound',reason='flipped',values={},evidence=[])
            for kind in ('payout','fee','quantity')}
        self.reversion(registry)
        result=produce(record,context(record)|{'selected_applicability':registry},at=AT)
        self.assertTrue(all(result['gaps'][kind]['status']!='available_and_bound' for kind in ('payout','fee','quantity')))
        self.assertTrue(all(result['gaps'][kind]['reason']=='source_selected_fact_is_not_numeric_qualification'
            for kind in ('payout','fee','quantity')))
