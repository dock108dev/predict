"""Independent authored EV03 storage/projection invariants; no acquisition."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from fractions import Fraction

from app.comparison.current_dependencies import profile, references, validate_profiles, digest
from app.comparison.shared_templates import ProfilePool, resolve, shared, keys, subset
from app.comparison.projection_batches import batches
from app.dashboard.current_contract import packed, serialize, snapshot_inputs, quotes_of, stamp, validate_snapshot
from app.dashboard.current_state import CurrentStore, SelectionError
from tests.current_fixture import InjectedTestProvider, fixture
from tests.ev03_workload import records, AT


def raw(games=3, count=30):
    rows,ref,_=records(games,count);envelope=fixture()
    envelope.update(events=[],clock_at=AT.isoformat(),projected_at=AT.isoformat())
    from app.dashboard.current_normalized import catalog_from_normalized
    value=catalog_from_normalized(envelope,rows,reference_records=ref)
    value['comparison_profiles']=ProfilePool(value['comparison_profiles'],compact=True).finish()
    return value


def quotes(value):
    return [q for e in value['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)]


def replace_input(value, q, kind, **changes):
    profiles=value['comparison_profiles'];old=resolve(profiles,q['comparison_input_refs']['refs'][kind])
    key,v=profile(kind,dict(old['payload'],**changes),expires_at=old['expires_at'])
    pool=ProfilePool(profiles);assert pool.add(key,v)
    value['comparison_profiles']=pool.finish();q['comparison_input_refs']['refs'][kind]=key


class Templates(unittest.TestCase):
    def test_lossless_compaction_units_authority_and_legacy_bounds(self):
        pool=ProfilePool(compact=True);original={}
        for version,unit,authority,rounding in [('v1','contracts','modeled','up'),('v1','stake_usd','modeled','up'),
                ('v2','contracts','modeled','up'),('v1','contracts','actual','up'),('v1','contracts','modeled','down')]:
            k,v=profile('fee',dict(rule=dict(rate='0',provider_version=version,unit=unit,
                authority=authority,rounding=rounding),actual=None,modeled='0'))
            original[k]=v;self.assertTrue(pool.add(k,v))
        compact=pool.finish();validate_profiles(compact)
        self.assertEqual(len(compact['templates']),5)
        self.assertEqual({k:resolve(compact,k) for k in keys(compact)},original)
        legacy={profile('fee',dict(test=str(i)))[0]:profile('fee',dict(test=str(i)))[1] for i in range(129)}
        with self.assertRaisesRegex(ValueError,'capacity'):validate_profiles(legacy)

    def test_capacity_refusal_preserves_existing_inputs_and_prunes_templates(self):
        pool=ProfilePool(compact=True);k,v=profile('buffer',dict(version='authored',ceiling='1000'))
        self.assertTrue(pool.add(k,v));before=deepcopy(pool.finish())
        fee,f=profile('fee',dict(rule=dict(version='authored',rate='0',units='usd',rounding='up')))
        with patch('app.comparison.shared_templates.MAX_SHARED_BYTES',len(packed(before))):
            self.assertFalse(pool.add(fee,f))
        self.assertEqual(pool.finish(),before)
        self.assertEqual(pool.finish(set())['templates'],{})

    def test_missing_dangling_cyclic_and_tampered_templates_reject(self):
        original=raw(1,4);graph=original['comparison_profiles']
        for mode in ('dangling','tampered','cyclic','private','float'):
            changed=deepcopy(graph);key=next(iter(changed['templates']))
            if mode=='dangling':del changed['templates'][key]
            elif mode=='tampered':changed['templates'][key]['payload']={}
            elif mode=='cyclic':changed['templates'][key]['payload']={'$comparison_template':key}
            else:
                node=changed['templates'].pop(key)
                node['payload']={'positions':{'secret':'1'}} if mode=='private' else {'rate':0.1}
                changed['templates'][digest(node)]=node
            with self.subTest(mode=mode),self.assertRaises(ValueError):validate_profiles(changed)

    def test_fair_batches_round_robin_and_bounded(self):
        items=[(event,index) for event in range(150) for index in range(14)]
        out=list(batches(items,lambda item:item[0]))
        flattened=[x for batch in out for x in batch]
        self.assertEqual([e for e,i in flattened[:150]],list(range(150)))
        self.assertEqual(set(flattened),set(items));self.assertTrue(all(len(b)<=32 for b in out))

    def test_full_incremental_cursor_coverage_and_no_acquisition(self):
        original=raw();store=CurrentStore(InjectedTestProvider(original),monotonic=lambda:0)
        before=store.snapshot();self.assertEqual(sum(q['calculations']['net_ev']['eligible'] for q in quotes(before)),27)
        changed=deepcopy(original);changed['state_revision']=2
        q=quotes(changed)[1];q['revision']+=1;q['original']['value']='0.51'
        self.assertTrue(store.commit(changed))
        self.assertEqual(store.projection_metrics['projected_groups'],1)
        self.assertEqual(store.projection_metrics['reused_groups'],2)
        delta=json.loads(store.encoded_changes(changed['runtime_id'],1));events={e['id']:e for e in before['events']}
        for event in delta['events']:events[event['id']]=event
        merged=dict(delta['snapshot'],events=sorted(events.values(),key=lambda e:(e['start_at'],e['id'])))
        self.assertEqual(packed(merged),store.encoded_snapshot())
        self.assertEqual(store.encoded_snapshot(),packed(serialize(changed,allow_synthetic=True)))
        self.assertEqual(json.loads(store.encoded_changes('prior-runtime',1))['schema'],'predict-current-1')
        self.assertEqual(json.loads(store.encoded_changes(changed['runtime_id'],99))['schema'],'predict-current-1')
        validate_snapshot(store.snapshot(),allow_synthetic=True)
        self.assertEqual(store.provider.initial_state(),original)

    def test_selective_template_identity_applicability_and_original_observations(self):
        for kind in ('identity','fee','payout','quantity','buffer','probability','reference'):
            original=raw();store=CurrentStore(InjectedTestProvider(original),monotonic=lambda:0)
            changed=deepcopy(original);changed['state_revision']=2;q=quotes(changed)[1]
            replace_input(changed,q,kind,authored_successor='2')
            with self.subTest(kind=kind):
                self.assertTrue(store.commit(changed));self.assertEqual(store.projection_metrics['projected_groups'],1)
                self.assertEqual(store.projection_metrics['reused_groups'],2)
                self.assertEqual({q['source']['native_outcome_id']:(q['source'],q['original'],q['times']) for q in quotes(store._state)},
                    {q['source']['native_outcome_id']:(q['source'],q['original'],q['times']) for q in quotes(original)})
        changed=raw();q=quotes(changed)[1];q['comparison_input_status']['fee']=dict(status='applicability_unresolved',reason='authored_applicability_missing')
        state=serialize(changed,allow_synthetic=True)
        self.assertFalse(next(x for x in quotes(state) if x['source']==q['source'])['calculations']['net_ev']['eligible'])
        self.assertTrue(references(q,changed['comparison_profiles'])['quantity'])

    def test_selected_details_full_graph_same_math_and_frozen_lease_after_pruning(self):
        original=raw(2,8);store=CurrentStore(InjectedTestProvider(original),monotonic=lambda:0)
        q=next(q for q in quotes(store._state) if q['calculations']['net_ev']['eligible'])
        selected=store.details(dict(runtime_id=original['runtime_id'],state_revision=1,quote_id=q['id']))
        self.assertEqual(selected['quote']['source'],q['source']);self.assertEqual(selected['quote']['times'],q['times'])
        self.assertEqual(selected['quote']['calculations']['net_ev']['exact'],q['calculations']['net_ev']['exact'])
        self.assertIn('costs',selected['quote']['calculations']['net_ev']['details'])
        self.assertIn('identity',selected['comparison_inputs'])
        lease=store.create(dict(schema='predict-current-1',runtime_id=original['runtime_id'],state_revision=1,
            quote_id=q['id'],quote_revision=q['revision'],client_id='authored-ev03'))
        held=deepcopy(lease['review']);changed=snapshot_inputs(store._state);changed['state_revision']=2
        changed['events']=[e for e in changed['events'] if e['id']!=selected['event']['id']]
        wanted={k for q in quotes(changed) for k in q['comparison_input_refs']['refs'].values() if k}
        changed['comparison_profiles']=ProfilePool(changed['comparison_profiles']).finish(wanted)
        self.assertTrue(store.commit(changed));self.assertEqual(store.get(lease['selection_id'])['review'],held)
        self.assertEqual(store.get(lease['selection_id'])['status'],'newer_available')
        with self.assertRaises(SelectionError):store.details(dict(runtime_id=original['runtime_id'],state_revision=1,quote_id=q['id']))

    def test_unchanged_calculation_agrees_with_expanded_legacy_and_clock_policy(self):
        original=raw(1,4);compact=serialize(original,allow_synthetic=True)
        legacy=deepcopy(original);legacy['comparison_profiles']={k:resolve(original['comparison_profiles'],k) for k in keys(original['comparison_profiles'])}
        expanded=serialize(legacy,allow_synthetic=True)
        self.assertEqual([(q['calculations']['net_ev']['exact'],q['times']) for q in quotes(compact)],
            [(q['calculations']['net_ev']['exact'],q['times']) for q in quotes(expanded)])
        ticks=[0];store=CurrentStore(InjectedTestProvider(original),monotonic=lambda:ticks[0]);ticks[0]=901
        self.assertTrue(all(not q['calculations']['net_ev']['eligible'] for q in quotes(store.snapshot())))
        self.assertEqual([q['times'] for q in quotes(compact)],[q['times'] for q in quotes(store._state)])
        validate_snapshot(store.snapshot(),allow_synthetic=True)


if __name__=='__main__':unittest.main()


from aiohttp.test_utils import AioHTTPTestCase


class DetailsRoutes(AioHTTPTestCase):
    async def get_application(self):
        from app.dashboard.multi_game_server import create_app
        from tests.test_current_state import owner
        self.raw=raw(1,4);self.provider=InjectedTestProvider(self.raw)
        return create_app(owner=owner(),sessions={},current_provider=self.provider)

    async def test_exact_details_filters_optional_size_and_cursor_refusal(self):
        from app.dashboard.current_state import CURRENT_KEY
        store=self.app[CURRENT_KEY];store.monotonic=lambda:0;store._age_origin=0
        current=await (await self.client.get('/api/current')).json()
        q=next(q for q in quotes(current) if q['calculations']['net_ev']['eligible'])
        params=dict(runtime_id=current['runtime_id'],state_revision=1,quote_id=q['id'])
        response=await self.client.get('/api/current/details',params=params)
        self.assertEqual(response.status,200);full=await response.json()
        self.assertEqual(full['quote']['calculations']['net_ev']['exact'],q['calculations']['net_ev']['exact'])
        self.assertIn('costs',full['quote']['calculations']['net_ev']['details'])
        response=await self.client.get('/api/current/details',params=dict(params,ceiling='100'))
        self.assertEqual(response.status,200);small=await response.json()
        self.assertEqual(small['estimate_policy']['capital_ceiling_usd'],'100')
        self.assertNotEqual(small['quote']['calculations']['net_ev']['details']['native_quantity'],full['quote']['calculations']['net_ev']['details']['native_quantity'])
        self.assertEqual((await self.client.get('/api/current/details',params=dict(params,state_revision=2))).status,409)
        self.assertEqual((await self.client.get('/api/current/details',params=dict(params,runtime_id='gone'))).status,410)
        self.assertEqual((await self.client.get('/api/current/details',params=dict(params,quote_id='absent'))).status,409)
        comparison=await (await self.client.get('/api/comparison?venue=polymarket_us')).json()
        self.assertTrue(comparison['rows']);self.assertTrue(all('row_ids' in g for g in comparison['groups']))
        self.assertEqual(self.provider.initial_state(),self.raw)


class SuccessorControls(unittest.TestCase):
    def test_exact_admission_memo_preserves_provider_identity(self):
        from app.comparison.shared_templates import ProfileFactory
        factory=ProfileFactory();first=factory('probability',{'version':'authored','rate':'0.005','provider':'a'})
        self.assertIs(first,factory('probability',{'rate':'0.005','version':'authored','provider':'a'}))
        second=factory('probability',{'version':'authored','rate':'0.005','provider':'b'})
        self.assertNotEqual(first[0],second[0]);self.assertEqual(factory.hits,1)

    def test_server_policy_and_selected_expiry_invalidate_held_graph(self):
        from app.comparison.estimated_policy import DEFAULT_POLICY
        from dataclasses import replace
        original=raw();ticks=[0];store=CurrentStore(InjectedTestProvider(original),monotonic=lambda:ticks[0])
        q=next(q for q in quotes(store._state) if q['calculations']['net_ev']['eligible'])
        lease=store.create(dict(schema='predict-current-1',runtime_id=original['runtime_id'],state_revision=1,
            quote_id=q['id'],quote_revision=q['revision'],client_id='authored-policy'))
        changed=replace(DEFAULT_POLICY,capital_ceiling_usd='950')
        with patch('app.comparison.estimated_policy.load',return_value=changed),patch('app.dashboard.current_incremental.load',return_value=changed):
            store.refresh_age();self.assertEqual(store.projection_metrics['projected_groups'],3)
            self.assertEqual(store.get(lease['selection_id'])['status'],'newer_available')
            self.assertEqual(store.get(lease['selection_id'])['review'],lease['review'])
            self.assertEqual([q['times'] for q in quotes(store._state)],[q['times'] for q in quotes(serialize(original,allow_synthetic=True))])

    def test_compact_selected_NO_SHORT_preserves_display_and_economic_context(self):
        from tests.test_ev02_occurrence import rows, envelope, AT as match_at
        from app.comparison.occurrence_matching import OccurrenceResolver
        from app.comparison.event_links import EventLinks
        from app.dashboard.current_normalized import catalog_from_normalized
        records=rows()+rows('polymarket_us','authored-short')
        original=catalog_from_normalized(envelope(),records,occurrence_resolver=OccurrenceResolver(links=EventLinks()))
        original['comparison_profiles']=ProfilePool(original['comparison_profiles'],compact=True).finish()
        store=CurrentStore(InjectedTestProvider(original),monotonic=lambda:0)
        for q in quotes(store._state):
            full=store.details(dict(runtime_id=original['runtime_id'],state_revision=1,quote_id=q['id']))
            self.assertEqual(full['quote']['source'],q['source'])
            self.assertEqual(full['quote']['native_contract'],q['native_contract'])
            self.assertEqual(full['group']['id'],q['binding']['selection']['group_id'])
            self.assertEqual(full['outcome']['id'],q['binding']['selection']['outcome_id'])
            self.assertEqual(full['quote']['occurrence_match'],q['occurrence_match'])
