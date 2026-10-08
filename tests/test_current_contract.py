import unittest
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from app.dashboard.current_contract import serialize, quotes_of, manual_scenario, line
from app.dashboard.u0_display import quote_display
from tests.current_fixture import fixture


class CurrentContractTests(unittest.TestCase):
    def raw(self):return fixture()
    def snapshot(self):return serialize(self.raw(),allow_synthetic=True)
    def quote(self,r):return r['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']
    def test_mode_no_fallback_and_financial_types(self):
        for mode in ('synthetic','historical'):
            r=self.raw();r['mode']=mode
            with self.assertRaises(ValueError):serialize(r)
        r=self.raw();self.quote(r)['original']['value']=.48
        with self.assertRaises(ValueError):serialize(r,allow_synthetic=True)
    def test_server_exact_cues_all_subsets_and_rounding(self):
        r=self.raw();qs=r['events'][0]['groups'][0]['outcomes'][0]['quotes']
        qs['kalshi']['original']['value']='0.50001';qs['polymarket_us']['original']['value']='0.5';qs['novig']['original']['value']='2';qs['prophetx']['original']['value']='1.99'
        s=serialize(r,allow_synthetic=True);qs=s['events'][0]['groups'][0]['outcomes'][0]['quotes']
        key='kalshi+polymarket_us+novig+prophetx'
        self.assertEqual(qs['kalshi']['display']['cents'],qs['novig']['display']['cents'])
        self.assertEqual(qs['kalshi']['comparison']['contexts'][key]['cue'],'')
        self.assertEqual(qs['novig']['comparison']['contexts'][key]['cue'],'Tied quote')
        self.assertEqual(qs['novig']['calculations']['raw_difference']['value'],'0')
        self.assertEqual(qs['kalshi']['calculations']['raw_difference']['exact']['numerator'],'-1')
        self.assertEqual(qs['kalshi']['calculations']['raw_difference']['exact']['denominator'],'1000')
        self.assertEqual(len(qs['kalshi']['comparison']['contexts']),15)
        self.assertEqual(qs['kalshi']['comparison']['contexts']['kalshi']['cue'],'')
        self.assertFalse(qs['kalshi']['comparison']['contexts']['kalshi']['raw_difference']['eligible'])
    def test_identity_lines_periods_null_and_native_alternatives(self):
        s=self.snapshot();e=s['events'][0]
        from app.dashboard.current_contract import quote_identity
        q=deepcopy(self.quote(s));original_id=q['id'];q['original']['payout']='1.0000'
        self.assertEqual(quote_identity(q,q['binding']['selection']['outcome_id']),original_id)
        q['source']['native_line']='3.5000';same=deepcopy(q);same['source']['native_line']='3.5'
        self.assertEqual(quote_identity(q,'outcome'),quote_identity(same,'outcome'))
        groups=[g for g in e['groups'] if g['market']=='spread' and g['period']=='full_game']
        self.assertEqual(len({g['id'] for g in groups}),2)
        self.assertEqual({g['line'] for g in groups},{'-3.5','-4.5'})
        r=self.raw();o=r['events'][0]['groups'][0]['outcomes'][0];alt=deepcopy(o['quotes']['kalshi']);alt['source']['native_side']='no';alt['source']['native_outcome_id']='syn:opponent-no';o['alternatives']={'kalshi':[alt,deepcopy(alt)]}
        s=serialize(r,allow_synthetic=True);o=s['events'][0]['groups'][0]['outcomes'][0]
        self.assertEqual(len(o['alternatives']['kalshi']),1);self.assertEqual(o['quotes']['kalshi']['source']['native_side'],'yes')
        alt=o['alternatives']['kalshi'][0];self.assertEqual(alt['source']['native_side'],'no');self.assertEqual(alt['binding']['selection']['predicate'],'win')
        r=self.raw();r['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']['binding']['selection']['predicate']='not_win'
        with self.assertRaises(ValueError):serialize(r,allow_synthetic=True)
        self.assertEqual(line('-0.00'),'0');self.assertIsNone(line(None));self.assertEqual(line('3.5000'),'3.5')
    def test_binding_conflicts_reference_exclusion_and_duplicate(self):
        r=self.raw();self.quote(r)['original']['role']='reference';s=serialize(r,allow_synthetic=True)
        self.assertNotIn('kalshi',s['events'][0]['groups'][0]['outcomes'][0]['quotes'])
        for field,value in [('signed_line','0'),('period_boundary','regulation'),('outcome_cardinality',3),('participant','other')]:
            r=self.raw();self.quote(r)['binding']['selection'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):serialize(r,allow_synthetic=True)
        r=self.raw();o=r['events'][0]['groups'][0]['outcomes'][0];alt=deepcopy(o['quotes']['kalshi']);alt['original']['value']='.1';o['alternatives']={'kalshi':[alt]}
        with self.assertRaises(ValueError):serialize(r,allow_synthetic=True)
    def test_inspectable_stale_delayed_unknown_ineligible(self):
        for mutate in ('stale','delayed','unknown','unverified','unsupported','currency'):
            r=self.raw();q=self.quote(r)
            if mutate=='stale':q['freshness_policy']['maximum_age_seconds']=1
            if mutate=='delayed':q['state']='budget_delayed'
            if mutate=='unknown':q['times']['source_at']=None;q['times']['source_time_kind']='unknown'
            if mutate=='unverified':q['binding']['verified']=False
            if mutate=='unsupported':q['original']['units']='ticks'
            if mutate=='currency':q['original']['payout_units']='EUR'
            s=serialize(r,allow_synthetic=True);q=self.quote(s)
            self.assertFalse(q['comparison']['eligible'],mutate);self.assertFalse(q['calculations']['raw_difference']['eligible'],mutate)
            self.assertEqual(q['calculations']['raw_difference']['reason'],'; '.join(q['comparison']['reasons']))
            self.assertIsInstance(q['original']['value'],str)
    def test_numeric_bounds_payout_and_signed_results(self):
        for p in ['1e9999','9'*257,'NaN','Infinity']:
            self.assertFalse(quote_display('.5','usd_per_contract',p)['supported'])
        for v in ['1e-256','.999999999999999999999999999999999999999999999999999999999999']:
            self.assertTrue(quote_display(v,'usd_per_contract')['supported'])
        for v in ['1e257','1e-257']:
            r=self.raw();self.quote(r)['original']['value']=v
            with self.assertRaises(ValueError):serialize(r,allow_synthetic=True)
        r=self.raw();self.quote(r)['depth']=[dict(price=.5,quantity='1')]
        with self.assertRaises(ValueError):serialize(r,allow_synthetic=True)
        r=self.raw();o=r['events'][0]['groups'][0]['outcomes'][0];o['alternatives']={'kalshi':[deepcopy(o['quotes']['kalshi']) for _ in range(65)]}
        with self.assertRaises(ValueError):serialize(r,allow_synthetic=True)
    def test_manual_original_bound_inputs_no_defaults_zero_negative(self):
        s=self.snapshot();q=self.quote(s);review={'quote':q}
        a=dict(probability='.48',entry_cost='0',win_cost='0',loss_cost='0',quantity='1',acknowledge_conditional=True)
        zero=manual_scenario(review,a);self.assertTrue(zero['eligible']);self.assertEqual(Decimal(zero['value']),0)
        a['probability']='.2';negative=manual_scenario(review,a);self.assertEqual(Decimal(negative['value']),Decimal('-.28'))
        self.assertEqual(negative['basis']['inputs'][0]['quote_revision'],q['revision'])
        self.assertNotIn('what_if',q['display'])
        for missing in a:
            incomplete=dict(a);incomplete.pop(missing)
            with self.subTest(missing=missing),self.assertRaises(ValueError):manual_scenario(review,incomplete)
        a['probability']='0';self.assertEqual(Decimal(manual_scenario(review,a)['value']),Decimal('-.48'))
        a['probability']='1';self.assertEqual(Decimal(manual_scenario(review,a)['value']),Decimal('.52'))

    def test_existing_engine_supported_zero_negative_and_binding(self):
        from app.dashboard.current_contract import identity
        r=self.raw();q=self.quote(r);q['original']['value']='.5'
        q['depth']=[dict(price='.5',quantity='1',liquidity_id='syn:one')]
        qid=identity('quote',[q['venue'],q['source'],q['original']['units'],q['original']['payout'],q['original']['payout_units'],q['original']['quantity_units'],q['binding']['selection']['outcome_id']])
        original=dict(source=deepcopy(q['source']),original=deepcopy(q['original']),revision=q['revision'],selection=deepcopy(q['binding']['selection']))
        # Explicit supplied states and costs; these never qualify a real venue.
        q['engine_inputs']=dict(kind='explicit-depth-1',quantities=['1'],quote_inputs=[original],facts=dict(costs=True,settlement=True,depth=True),fact_evidence={k:['syn:assumed-explicit-inputs'] for k in ('costs','settlement','depth')},
            probability=dict(kind='model EV',independent=True,evidence=['syn:test-model-only'],model_version='syn:partition'),
            spec=dict(states=['win','loss'],complete=True,probabilities={'win':'.5','loss':'.5'},reserve='0',legs=[dict(id=qid,minimum='1',increment='1',partial_final=True,levels=deepcopy(q['depth']),fee_policy=dict(basis='notional',rate='0',grid='.01',rounding='half_up',aggregation='order'),payouts={'win':dict(kind='per_unit',value='1',settlement_fee_per_unit='0'),'loss':dict(kind='per_unit',value='0',settlement_fee_per_unit='0')})]))
        s=serialize(r,allow_synthetic=True);c=self.quote(s)['calculations'];self.assertTrue(c['ev']['eligible']);self.assertEqual(Decimal(c['ev']['value']),0)
        self.assertEqual(Decimal(c['net_arbitrage']['value']),-100);self.assertTrue(c['sizing']['eligible']);self.assertIn('calculation_inputs',self.quote(s))
        from app.dashboard.current_contract import validate_snapshot
        from app.dashboard.current_state import CurrentStore
        from tests.test_current_state import request
        from types import SimpleNamespace
        q['freshness_policy']['maximum_age_seconds']=20
        clock=[0]
        store=CurrentStore(SimpleNamespace(allow_synthetic=True,initial_state=lambda:r),monotonic=lambda:clock[0])
        held=store.create(request(store));clock[0]=13
        aged=store.snapshot();validate_snapshot(aged,allow_synthetic=True)
        self.assertFalse(self.quote(aged)['calculations']['ev']['eligible'])
        self.assertFalse(self.quote(aged)['calculations']['sizing']['eligible'])
        self.assertTrue(store.get(held['selection_id'])['review']['quote']['calculations']['ev']['eligible'])
        q['engine_inputs']['spec']['probabilities']={'win':'.2','loss':'.8'}
        s=serialize(r,allow_synthetic=True);self.assertEqual(Decimal(self.quote(s)['calculations']['ev']['value']),Decimal('-60'))
        q['engine_inputs']['probability']['independent']=False
        s=serialize(r,allow_synthetic=True);self.assertFalse(self.quote(s)['calculations']['ev']['eligible']);self.assertTrue(self.quote(s)['calculations']['arbitrage']['eligible'])
        q['engine_inputs']['spec']['legs'][0]['levels'][0]['price']='.01'
        with self.assertRaises(ValueError):serialize(r,allow_synthetic=True)

    def test_existing_normalized_event_adapter(self):
        from app.dashboard.current_normalized import catalog_from_normalized
        from app.resolution.core import event_key
        from tests.test_nfl_lines import fixture as nfl_fixture
        event=nfl_fixture()[1]['inventory']['kalshi']['events'][0]
        raw=self.raw();q=self.quote(raw)
        market=dict(event=event_key(event),sport=event['sport'],competition=event['competition'],season=event['season'],stage=event['stage'],scheduled_start=event['scheduled_start'],family='moneyline',period='full_game',line=None,outcome_set='two_way',rules={'overtime':'included'})
        records=[]
        for role in ('away','home'):
            native=deepcopy(q);native['source']['native_outcome_id']='syn:'+role
            records.append(dict(event=event,market_identity=market,period_boundary='full_game_including_overtime',anchor_participant=None,outcome_cardinality=2,
                selection=dict(participant=event[role],predicate='win',signed_line=None,label=role+' winner'),quote=native,orientation_evidence=['syn:reviewed-side'],verified=True))
        envelope={k:v for k,v in raw.items() if k!='events'}
        adapted=catalog_from_normalized(envelope,records);s=serialize(adapted,allow_synthetic=True);self.assertEqual(len(s['events']),1)
        self.assertEqual(s['events'][0]['league'],'NFL');self.assertEqual({o['participant'] for o in s['events'][0]['groups'][0]['outcomes']},{'NFL:BUF','NFL:DET'})
        records[0]['market_identity']=dict(market,event=['different'])
        with self.assertRaises(ValueError):catalog_from_normalized(envelope,records)

    def test_semantic_snapshot_validator_and_safe_unknowns(self):
        from app.dashboard.current_contract import validate_snapshot
        s=self.snapshot();self.assertIs(validate_snapshot(s,allow_synthetic=True),s)
        self.quote(s)['comparison']['contexts']['kalshi']['cue']='Better quote'
        with self.assertRaises(ValueError):validate_snapshot(s,allow_synthetic=True)
        r=self.raw();self.quote(r)['source']['url']='https://evil.test'
        with self.assertRaises(ValueError):serialize(r,allow_synthetic=True)
    def test_long_short_original_transform_and_push_policies(self):
        r=self.raw();q=self.quote(r);q['source']['native_side']='short';q['original'].update(native_value='.52',native_units='usd_per_contract',transformation='one_minus_native_bid')
        s=serialize(r,allow_synthetic=True);self.assertEqual(self.quote(s)['original']['native_value'],'.52');self.assertEqual(self.quote(s)['source']['native_side'],'short')
        q['original']['native_value']='.51'
        with self.assertRaises(ValueError):serialize(r,allow_synthetic=True)
        a=self.raw();b=self.raw();b['events'][0]['groups'][0]['result_policy']='refund-on-tie'
        # A different policy requires a different exact binding as well.
        from tests.current_fixture import fixture
        from app.dashboard.current_contract import identity,binding_context
        e=b['events'][0];g=e['groups'][0];g['id']=identity('group',[e['id'],*[g[k] for k in ('market','period','period_boundary','line','anchor_participant','outcome_cardinality')],g['result_policy']])
        for o in g['outcomes']:
            o['id']=identity('outcome',[g['id'],o['participant'],o['predicate'],o['signed_line'],'normal_win'])
            for q in o['quotes'].values():q['binding']['selection']=binding_context(e,g,o)
        self.assertNotEqual(serialize(a,allow_synthetic=True)['events'][0]['groups'][0]['id'],serialize(b,allow_synthetic=True)['events'][0]['groups'][0]['id'])
