"""Independent authored EV04 vectors. Retained bodies are historical evidence only."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import unittest

from app.comparison.current_dependencies import KINDS, VERSION as REFS, profile, temporal_revision
from app.comparison.costs import FundingComponent, CostRegistry
from app.comparison.source_inputs import observation
from app.comparison.estimated_content import attach, catalog, resolve_content, STATES
from app.comparison.estimated_consumer import consume, resolve_component
from app.comparison.estimated_templates import fee_provider
from app.comparison.shared_templates import resolve
from app.comparison.event_links import digest
from tests.test_comparison_source_inputs import native_records, context
from tests.test_comparison_net_costs import setup_case
from tests.test_estimated_templates import contract

AT=datetime(2026,10,11,12,tzinfo=timezone.utc)
ROOT=Path(__file__).resolve().parents[1]


def case(venue='polymarket_us',predicate='win',metadata=None):
    r=native_records()[0];ctx=context(r);q=deepcopy(ctx['quote'])
    q['venue']=venue;q['source']['provider']=venue;q['source']['native_side']='YES'
    q['binding']['selection']['predicate']=predicate
    q['times'].update(source_at=AT.isoformat(),received_at=AT.isoformat())
    q['original'].update(value='2' if venue in ('novig','prophetx') else '0.5',units='decimal_odds' if venue in ('novig','prophetx') else 'usd_per_contract')
    q.pop('native_contract',None);q.pop('sharp_reference',None)
    ctx['quote']=q;ctx['outcome']['predicate']=predicate
    r['quote']=deepcopy(q);r['selection']['predicate']=predicate;r['event']['scheduled_start']=(AT+timedelta(days=1)).isoformat()
    r['comparison_source_metadata']=dict(phase='pregame',overtime='included',**(metadata or {}))
    result=dict(profiles={},comparison_input_refs=dict(version=REFS,refs={k:None for k in KINDS},phase='pregame'),
        gaps={k:dict(status='absent',reason=k+'_actual_unknown') for k in KINDS})
    attach(result,r,ctx,at=AT)
    q['comparison_input_refs']=result['comparison_input_refs'];q['comparison_input_status']=result['gaps']
    return q,result['profiles'],ctx,r


def value(result,kind,name):return result['components'][kind][name]['modeled_value']


class ContentTests(unittest.TestCase):
    def test_retained_original_hashes_dates_and_conflicts(self):
        c=catalog()
        for source in c['sources'].values():
            self.assertEqual(len(source['sha256']),64)
            self.assertTrue(source['path'])
            self.assertTrue(source['retrieved_at'])
        latest=next(t for t in c['templates'] if t['venue']=='polymarket_us')
        self.assertEqual(latest['fee']['effective_from'],'2026-10-07T14:00:00Z')
        self.assertEqual(len(c['reconciliation'][0]['versions']),3)
        self.assertEqual(c['reconciliation'][1]['status'],'provisional_successor_date_scope')
        old=json.loads((ROOT/'app/fixtures/public-contracts-v1.json').read_text())
        self.assertEqual(old['sources']['us-fees']['effective_date'],'2026-09-25T04:00:00Z')

    def test_four_venue_independent_entry_commission_and_collateral_vectors(self):
        for venue,quantity,fee,win,tie in [('kalshi','100','1.75','100','50'),
                ('polymarket_us','100','1.74','100','50'),('novig','100','0','200','100'),('prophetx','100','0','200','100')]:
            with self.subTest(venue=venue):
                q,profiles,_,_=case(venue);before=deepcopy(q)
                r=consume(q,profiles,at=AT,native_quantity=quantity)
                self.assertEqual(Fraction(value(r,'fee','entry_fee_usd')),Fraction(fee),r['reasons'])
                receipts=[value(r,'payout','receipt_usd:'+s) for s in STATES]
                self.assertIn(win,receipts[:2]);self.assertEqual(receipts[2],tie)
                commission=[value(r,'fee','settlement_fee_usd:'+s) for s in STATES]
                self.assertIn(Fraction(2),[Fraction(x) for x in commission]) if venue=='prophetx' else self.assertEqual(commission,['0']*4)
                self.assertFalse(r['actual_qualified']);self.assertEqual(q,before)
                for components in r['components'].values():
                    for cell in components.values():self.assertIsNone(cell['actual_value'])
                self.assertEqual(value(r,'fee','additional_mandatory_charges_usd'),'0')
                self.assertIn('no_evidenced_exemption',r['assumed_additional_charges'])
                for kind,key in r['profile_refs'].items():
                    self.assertEqual(resolve(r['profiles'],key)['kind'],kind)
                    self.assertEqual(resolve(r['profiles'],key)['payload']['scalar_unit'],'USD')

    def test_kalshi_tie_strike_no_and_opponent_yes_differ(self):
        no,profiles,_,_=case('kalshi','not_win',{'tie_strike_listed':True})
        yes,p2,_,_=case('kalshi','win',{'tie_strike_listed':True})
        a=consume(no,profiles,at=AT,native_quantity='100');b=consume(yes,p2,at=AT,native_quantity='100')
        self.assertEqual(value(a,'payout','receipt_usd:tie'),'100')
        self.assertEqual(value(b,'payout','receipt_usd:tie'),'0')
        ordinary,p,_,_=case('kalshi','not_win')
        self.assertEqual(value(consume(ordinary,p,at=AT,native_quantity='100'),'payout','receipt_usd:tie'),'50')

    def test_native_v3_cent_units_phase_selected_metadata_and_fair_mark(self):
        q,profiles,_,_=case('novig',metadata={'api_regime':'v3','market_fee':dict(coefficient='0.06',makerCredit='0.5',charged='WHEN_LIVE'),'fair_price':'0.3'})
        q['original'].update(units='usd_per_contract',value='0.5')
        # Native cents remain explicit. Pregame fill is zero, a supplied live
        # fill uses the selected .06 despite the generic NFL table's .03.
        pre=consume(q,profiles,at=AT,native_quantity='10000')
        live=consume(q,profiles,at=AT,native_quantity='10000',fills=[dict(fill_id='live',order_id='one',role='taker',unit='novig_v3_contracts',quantity='10000',price='0.5',event_status_at_match='OPEN_INGAME')])
        self.assertEqual(Fraction(value(pre,'fee','entry_fee_usd')),0)
        self.assertEqual(Fraction(value(live,'fee','entry_fee_usd')),Fraction('1.5'))
        self.assertEqual(value(live,'payout','receipt_usd:terminal_noncompletion'),'30')
        self.assertEqual(value(pre,'payout','receipt_usd:tie'),'50')
        self.assertEqual(pre['dependencies']['unit']['face_usd_per_native'],'0.01')
        self.assertEqual(pre['components']['fee']['fee_refund_usd:tie']['modeled_value'],'0')

    def test_half_even_caps_partition_price_and_quantity_invalidation(self):
        q,p,_,_=case();one=consume(q,p,at=AT,native_quantity='100')
        fills=[dict(fill_id=str(i),order_id='same',role='taker',unit='contracts',quantity='1',price='0.5') for i in range(100)]
        split=consume(q,p,at=AT,native_quantity='100',fills=fills)
        self.assertEqual(value(one,'fee','entry_fee_usd'),'1.74')
        # 100 separately rounded .017375 fills would charge2.00, but the
        # aggressive-order cap restricts the cumulative charge to1.74.
        self.assertEqual(value(split,'fee','entry_fee_usd'),'1.74')
        self.assertNotEqual(one['dependency_revision'],split['dependency_revision'])
        resized=consume(q,p,at=AT,native_quantity='200')
        self.assertEqual(value(resized,'fee','entry_fee_usd'),'3.48')
        self.assertNotEqual(one['profile_refs']['fee'],resized['profile_refs']['fee'])
        changed=deepcopy(q);changed['original']['value']='0.4'
        repriced=consume(changed,p,at=AT,native_quantity='100')
        self.assertEqual(value(repriced,'fee','entry_fee_usd'),'1.67')
        with self.assertRaisesRegex(ValueError,'allocation_changed'):
            resolve_component(one['profiles'],one['profile_refs']['fee'],'entry_fee_usd',dependency_revision=resized['dependency_revision'],at=AT)
        cell=resolve_component(one['profiles'],one['profile_refs']['fee'],'entry_fee_usd',dependency_revision=one['dependency_revision'],at=AT)
        self.assertEqual(cell.modeled_value,'1.74')

    def test_independent_fee_when_payout_or_grid_missing_and_expiry(self):
        q,p,_,_=case(metadata={'tie_outcome_listed':True})
        result=consume(q,p,at=AT,native_quantity='100')
        self.assertEqual(value(result,'fee','entry_fee_usd'),'1.74')
        self.assertIsNone(value(result,'payout','receipt_usd:tie'))
        self.assertIsNone(q['comparison_input_refs']['refs']['quantity'])
        expired=AT+timedelta(days=6)
        self.assertNotEqual(temporal_revision(q,p,AT),temporal_revision(q,p,expired))
        self.assertFalse(resolve_content(q,p,at=expired,kind='fee')['available'])
        with self.assertRaisesRegex(ValueError,'expired'):
            resolve_component(result['profiles'],result['profile_refs']['fee'],'entry_fee_usd',dependency_revision=result['dependency_revision'],at=expired)
        with self.assertRaisesRegex(ValueError,'disjoint_state'):
            consume(q,p,at=AT,native_quantity='100',state_cashflows={'cancelled':'50','abandoned':'50'})

    def test_prophetx_refunded_holds_ceiling_rounding_and_changed_state_base(self):
        q,p,_,_=case('prophetx')
        hold=(FundingComponent('hold','10','refundable_hold','entry'),)
        amounts=dict.fromkeys(STATES,'10')
        r=consume(q,p,at=AT,native_quantity='100',extra_funding=hold,hold_returns_usd=amounts,state_cashflows=dict(home_win='200.01',away_win='0',tie='100',terminal_noncompletion='100'))
        self.assertEqual(value(r,'fee','settlement_fee_usd:home_win'),'2.01')
        self.assertEqual(value(r,'payout','hold_return_usd:home_win'),'10')
        self.assertEqual(r['deployed_capital_usd'],'110')
        charged=consume(q,p,at=AT,native_quantity='100',extra_funding=hold+(FundingComponent('spent','3','consumed_allowance','entry'),),hold_returns_usd=amounts,
            state_cashflows=dict(home_win='200.01',away_win='0',tie='100',terminal_noncompletion='100'))
        self.assertEqual(charged['deployed_capital_usd'],'113')
        self.assertEqual(value(charged,'fee','settlement_fee_usd:home_win'),'1.95')
        unknown=consume(q,p,at=AT,native_quantity='100',extra_funding=hold)
        self.assertEqual(value(unknown,'fee','entry_fee_usd'),'0')
        self.assertIsNone(value(unknown,'fee','settlement_fee_usd:home_win'))
        self.assertNotEqual(unknown['dependency_revision'],r['dependency_revision'])

    def test_selected_conflict_local_preserves_original_refs(self):
        q,p,ctx,record=case();content=deepcopy(q['comparison_input_status']['fee']['estimate_content'])
        # Exact selected observations can be conflicting/expired; preserve the
        # conflict without overwriting it with the published standard sibling.
        bad=dict(version='comparison-selected-applicability-1',records=[dict(native_key=content['native_key'],binding_version='bad')])
        ctx['selected_applicability']=bad
        result=dict(profiles={},comparison_input_refs=deepcopy(q['comparison_input_refs']),gaps={k:dict(status='absent',reason=k+'_unknown') for k in KINDS})
        attach(result,record,ctx,at=AT);q['comparison_input_status']=result['gaps']
        r=consume(q,p,at=AT,native_quantity='100')
        self.assertIsNone(value(r,'fee','entry_fee_usd'))
        self.assertIn('source_selected_binding_digest_conflict',r['reasons']['fee'])
        self.assertEqual(q['comparison_input_refs'],result['comparison_input_refs'])

    def test_existing_bridge_withheld_charge_and_nonrefundable_allowance(self):
        request,scenario,args=setup_case('polymarket_us','100',gross_win='100')
        rules=args['registry'].data;row=rules['rules'][0]
        row.update(settlement_treatment='already_withheld_from_payout',settlement_status='known_terms',settlement_terms=dict(basis='net_gain',rate='0.02',grid_usd='0.01',rounding='half_even',aggregation=None,role='taker',allow_fee_adjustment=False))
        scenario['legs'][0]['settlement_charge_already_withheld']=True
        args['registry']=CostRegistry(rules)
        p=fee_provider(contract(scenario['legs'][0]['native_key']),request,scenario,**args)
        result=p.to_dict()['payload']['result']
        self.assertEqual(result['states']['win']['net_return_usd'],'100')
        self.assertEqual(result['states']['win']['settlement_fee_usd'],'0')

    def test_successor_base_commission_separate_from_withheld_additional_charge(self):
        q,p,_,_=case('prophetx')
        _,_,args=setup_case('prophetx','100')
        rule=args['registry'].rules[0].to_dict()
        rule.update(event_id=q['source']['native_event_id'],market_id=q['source']['native_market_id'],
            settlement_status='known_terms',settlement_treatment='already_withheld_from_payout',
            settlement_terms=dict(basis='net_gain',rate='0.03',grid_usd='0.01',rounding='half_even',aggregation='order',role='taker',allow_fee_adjustment=False))
        key,original=profile('fee',json.loads(json.dumps(dict(rule=rule))),expires_at=(AT+timedelta(hours=1)).isoformat())
        p[key]=original;q['comparison_input_refs']['refs']['fee']=key
        status=q['comparison_input_status']['fee'];status['status']='available_and_bound'
        recipe=status['estimate_content'];recipe['original_profile_ref']=key
        recipe['id']=digest({k:v for k,v in recipe.items() if k!='id'})
        unknown=consume(q,p,at=AT,native_quantity='100')
        self.assertEqual(value(unknown,'fee','entry_fee_usd'),'0')
        self.assertIsNone(value(unknown,'fee','settlement_fee_usd:home_win'))
        explicit=consume(q,p,at=AT,native_quantity='100',settlement_charge_already_withheld=True)
        self.assertIn('2',[value(explicit,'fee','settlement_fee_usd:'+s) for s in STATES])
        self.assertNotEqual(unknown['dependency_revision'],explicit['dependency_revision'])
        rule['settlement_treatment']='separate_charge'
        # Two independently payable commissions share the same net-gain base.
        key,original=profile('fee',json.loads(json.dumps(dict(rule=rule))))
        p[key]=original;q['comparison_input_refs']['refs']['fee']=key
        recipe['original_profile_ref']=key;recipe['id']=digest({k:v for k,v in recipe.items() if k!='id'})
        charged=consume(q,p,at=AT,native_quantity='100')
        self.assertIn('5',[value(charged,'fee','settlement_fee_usd:'+s) for s in STATES])


    def test_kalshi_balance_accumulation_and_scoped_replacement(self):
        q,p,_,_=case('kalshi',metadata={'balance_precision':'0.01'})
        fills=[dict(fill_id=str(i),order_id='one',role='taker',unit='contracts',quantity='1',price='0.5') for i in range(4)]
        r=consume(q,p,at=AT,native_quantity='4',fills=fills)
        self.assertEqual(value(r,'fee','entry_fee_usd'),'0.0800')
        self.assertEqual(value(r,'fee','rounding_refund_usd'),'0.01')
        self.assertEqual(value(r,'fee','net_entry_fee_usd'),'0.07')
        meta=dict(balance_precision='0.01',series_id='series',kalshi_metadata=dict(source='authored:selected-history',series_id='series',event_id=q['source']['native_event_id'],event_history_complete=True,series_changes=[dict(scheduled_ts=AT.isoformat(),fee_type='quadratic',fee_multiplier='2')],event_changes=[]))
        changed,p2,_,_=case('kalshi',metadata=meta)
        other,po,_,_=case('prophetx')
        unaffected=consume(other,po,at=AT,native_quantity='100')
        doubled=consume(changed,p2,at=AT,native_quantity='4',fills=fills)
        self.assertEqual(value(doubled,'fee','net_entry_fee_usd'),'0.14')
        self.assertNotEqual(r['profile_refs']['fee'],doubled['profile_refs']['fee'])
        self.assertEqual(consume(other,po,at=AT,native_quantity='100'),unaffected)

    def test_fixed_point_units_and_explicit_selected_terms_replace_template(self):
        q,p,ctx,record=case(metadata={'selected_reference_data':dict(present=True,market_id='bad',instrument_id='bad',values=dict(priceScale='100',fractionalQtyScale='1000'))})
        metadata=record['comparison_source_metadata']['selected_reference_data']
        metadata.update(market_id=q['source']['native_market_id'],instrument_id=q['source']['native_outcome_id'])
        result=dict(profiles={},comparison_input_refs=deepcopy(q['comparison_input_refs']),gaps={k:dict(status='absent',reason=k+'_unknown') for k in KINDS})
        attach(result,record,ctx,at=AT);q['comparison_input_status']=result['gaps']
        r=consume(q,p,at=AT,native_quantity='100000')
        self.assertEqual(value(r,'fee','entry_fee_usd'),'1.74')
        self.assertEqual(r['acquisition_usd'],'50')
        request,scenario,args=setup_case('polymarket_us','100',rate='0.06')
        rule=args['registry'].rules[0].to_dict();rule.update(event_id=q['source']['native_event_id'],market_id=q['source']['native_market_id'])
        payload=json.loads(json.dumps(dict(rule=rule,engine_context=args['engine_context'],engine_registry=args['engine_registry'].data)))
        selected=dict(native_key=q['comparison_input_status']['fee']['estimate_content']['native_key'],observation=observation(q),effective_from=AT.isoformat(),effective_until=(AT+timedelta(hours=1)).isoformat(),facets=dict(fee=dict(value=dict(fee_payload=payload),evidence=[dict(ref='authored:selected',sha256='0'*64,evidence_class='authored')])))
        selected['binding_version']=digest(selected);ctx['selected_applicability']=dict(version='comparison-selected-applicability-1',records=[selected])
        attach(result,record,ctx,at=AT);q['comparison_input_status']=result['gaps']
        selected_result=consume(q,p,at=AT,native_quantity='100')
        self.assertEqual(value(selected_result,'fee','entry_fee_usd'),'1.5',selected_result['reasons'])
        self.assertEqual(resolve(selected_result['profiles'],selected_result['profile_refs']['fee'])['payload']['content']['recipe']['applicability'],'selected_applicable_terms')
        self.assertEqual(q['comparison_input_refs']['refs'],dict.fromkeys(KINDS))
        split=consume(q,p,at=AT,native_quantity='100',fills=[dict(fill_id=str(i),order_id='same',role='taker',unit='contracts',quantity='1',price='0.5') for i in range(100)])
        self.assertEqual(Fraction(value(split,'fee','entry_fee_usd')),Fraction('1.5'))

    def test_ordinary_admission_details_and_frozen_lease_preserve_successor_scope(self):
        from app.dashboard.current_normalized import catalog_from_normalized
        from app.dashboard.current_state import CurrentStore
        from tests.current_fixture import fixture, InjectedTestProvider
        from app.dashboard.current_contract import quotes_of
        record={k:v for k,v in native_records()[0].items() if not k.startswith('_')}
        record['quote'].pop('occurrence_match',None);record['quote'].pop('occurrence_link',None);record['quote'].pop('native_predicate',None)
        record['quote']['times'].update(source_at=AT.isoformat(),received_at=AT.isoformat())
        record['comparison_source_metadata']=dict(phase='pregame',overtime='included')
        envelope=fixture();envelope.update(clock_at=AT.isoformat(),projected_at=AT.isoformat(),events=[])
        raw=catalog_from_normalized(envelope,[record]);q=next(q for e in raw['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o))
        self.assertIn('estimate_content',q['comparison_input_status']['fee'])
        originals=deepcopy(raw['comparison_profiles'])
        store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:0)
        q=next(q for e in store._state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o))
        request=dict(runtime_id=raw['runtime_id'],state_revision=1,quote_id=q['id'])
        detail=store.details(request)
        self.assertTrue(detail['estimate_content']['fee']['available'])
        self.assertEqual(detail['estimate_content']['fee']['recipe']['original_profile_ref'],q['comparison_input_refs']['refs']['fee'])
        lease=store.create(dict(schema='predict-current-1',**request,quote_revision=q['revision'],client_id='authored:ev04'))
        frozen=deepcopy(lease['review'])
        changed=deepcopy(raw);changed['state_revision']=2
        recipe=next(q for e in changed['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o))['comparison_input_status']['fee']['estimate_content']
        recipe['metadata']['balance_precision']='0.01';recipe['id']=digest({k:v for k,v in recipe.items() if k!='id'})
        self.assertTrue(store.commit(changed))
        self.assertEqual(store.get(lease['selection_id'])['review'],frozen)
        self.assertEqual(raw['comparison_profiles'],originals)
        self.assertEqual(detail['quote']['original'],q['original'])
        self.assertEqual(detail['quote']['times'],q['times'])
