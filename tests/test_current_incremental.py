"""Controlled latest-only updates: same math, selective work and cursor recovery."""
import json
from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import patch
from app.dashboard.current_contract import serialize,validate_snapshot,packed,stamp
from app.dashboard.current_state import CurrentStore
from app.dashboard.current_normalized import catalog_from_normalized
from app.collection.current_aggregate_admission import admit
from app.collection.current_benchmark import attach
from tests.test_current_aggregate import body
from tests.current_fixture import fixture,InjectedTestProvider
from tests import test_current_state as old_routes
from aiohttp.test_utils import AioHTTPTestCase

AT='2026-10-03T00:00:00Z'


def catalog(count=30):
    template=json.loads(body(books=('novig','prophetx','pinnacle'),at=AT))[0]
    events=[]
    for i in range(count):
        e=deepcopy(template);e['id']='CONTROLLED-event-'+str(i);events.append(e)
    encoded=json.dumps(events).encode()
    records=admit(encoded,'MLB',AT,venue='novig')+admit(encoded,'MLB',AT,venue='prophetx')
    attach(records,admit(encoded,'MLB',AT,venue='pinnacle'))
    for r in records:
        r.pop('_instrument');r.pop('_fingerprint')
        r['quote']['provenance']=dict(mode='synthetic',real_source=False,fixture='controlled-latest-only')
    raw=fixture();raw['clock_at']=raw['projected_at']=AT;raw['events']=[]
    return catalog_from_normalized(raw,records)


def changed(raw,event_index=0,revision=2):
    value=deepcopy(raw);value['state_revision']=revision
    q=value['events'][event_index]['groups'][0]['outcomes'][0]['quotes']['novig']
    q['revision']+=1;q['original']['value']='2.70'
    return value


class LatestOnly(unittest.TestCase):
    def test_only_changed_group_is_recomputed_and_math_reproduces(self):
        raw=catalog();store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:0)
        previous=store._state['events'][1]['groups'][0]['outcomes'][0]['quotes']['novig']['calculations']['arbitrage']
        next_raw=changed(raw)
        self.assertTrue(store.commit(next_raw))
        self.assertEqual(store.projection_metrics,dict(projected_groups=1,reused_groups=89))
        current=store._state['events'][1]['groups'][0]['outcomes'][0]['quotes']['novig']['calculations']['arbitrage']
        self.assertIs(current,previous)
        self.assertEqual(packed(store.snapshot()),packed(serialize(next_raw,allow_synthetic=True)))
        validate_snapshot(store.snapshot(),allow_synthetic=True)
    def test_clock_ticks_and_unchanged_commits_share_temporal_projection(self):
        ticks=[0];raw=catalog(1)
        tick_store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:ticks[0])
        commit_store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:0)
        from app.dashboard import current_incremental
        for elapsed in (1,1801):
            with self.subTest(elapsed=elapsed):
                ticks[0]=elapsed
                with patch.object(current_incremental,'aged',wraps=current_incremental.aged) as policy:
                    ticked=tick_store.snapshot()
                self.assertGreaterEqual(policy.call_count,len(raw['events'][0]['groups']))
                next_raw=deepcopy(raw)
                next_raw['clock_at']=(stamp(raw['clock_at'])+timedelta(seconds=elapsed)).isoformat()
                next_raw['state_revision']=commit_store._state['state_revision']+1
                self.assertTrue(commit_store.commit(next_raw))
                self.assertEqual(packed(ticked['events']),packed(commit_store._state['events']))
                self.assertEqual(ticked.get('comparison_profiles',{}),commit_store._state.get('comparison_profiles',{}))

    def test_coalesced_cursor_delivers_latest_events_without_patch_history(self):
        raw=catalog();store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:0)
        one=changed(raw,0,2);store.commit(one)
        two=changed(one,1,3);store.commit(two)
        full=store.encoded_snapshot();delta=store.encoded_changes(raw['runtime_id'],1);value=json.loads(delta)
        self.assertEqual(value['schema'],'predict-current-changes-1');self.assertEqual(value['base_revision'],1)
        self.assertEqual(len(value['events']),2);self.assertLess(len(delta),len(full)/10)
        self.assertEqual(len(store._event_versions),30)
        self.assertEqual(json.loads(store.encoded_changes(raw['runtime_id'],3))['events'],[])
        self.assertEqual(json.loads(store.encoded_changes('old-runtime',1))['schema'],'predict-current-1')
    def test_event_and_group_removals_are_delivered(self):
        raw=catalog(3);store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:0)
        next_raw=deepcopy(raw);next_raw['state_revision']=2
        removed=next_raw['events'].pop()['id'];remaining=next_raw['events'][0]['id'];next_raw['events'][0]['groups'].pop()
        store.commit(next_raw);value=json.loads(store.encoded_changes(raw['runtime_id'],1))
        self.assertEqual(value['removed_events'],[removed]);self.assertEqual([e['id'] for e in value['events']],[remaining])
        self.assertEqual(len(value['events'][0]['groups']),2)
        validate_snapshot(store.snapshot(),allow_synthetic=True)
    def test_age_expiry_changes_only_affected_eligibility_and_freezes_old_snapshots(self):
        ticks=[0];raw=catalog(3);store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:ticks[0])
        before=store.snapshot();self.assertTrue(before['events'][0]['groups'][0]['outcomes'][0]['quotes']['novig']['calculations']['ev']['eligible'])
        ticks[0]=1801;after=store.snapshot();delta=json.loads(store.encoded_changes(raw['runtime_id'],1))
        self.assertFalse(after['events'][0]['groups'][0]['outcomes'][0]['quotes']['novig']['calculations']['ev']['eligible'])
        self.assertEqual(len(delta['events']),3);self.assertTrue(before['events'][0]['groups'][0]['outcomes'][0]['quotes']['novig']['calculations']['ev']['eligible'])
        validate_snapshot(after,allow_synthetic=True)
    def test_invalid_changed_group_is_atomic(self):
        raw=catalog(3);store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:0)
        before=store.encoded_snapshot();next_raw=changed(raw)
        next_raw['events'][0]['groups'][0]['outcomes'][0]['quotes']['novig']['binding']['selection']['predicate']='not_win'
        with self.assertRaises(ValueError):store.commit(next_raw)
        self.assertEqual(store.encoded_snapshot(),before)


class ChangesRoutes(AioHTTPTestCase):
    get_application = old_routes.Routes.get_application
    async def test_changes_cursor_and_snapshot_recovery(self):
        from app.dashboard.current_state import CURRENT_KEY
        store=self.app[CURRENT_KEY];first=await (await self.client.get('/api/current')).json()
        self.assertEqual((await self.client.get('/api/current/changes')).status,422)
        url='/api/current/changes?runtime_id='+first['runtime_id']+'&state_revision=1'
        value=await (await self.client.get(url)).json();self.assertEqual(value['schema'],'predict-current-changes-1');self.assertEqual(value['events'],[])
        raw=fixture(2);store.commit(raw)
        value=await (await self.client.get(url)).json();self.assertTrue(value['events'])
        reset=await (await self.client.get('/api/current/changes?runtime_id=previous&state_revision=1')).json();self.assertEqual(reset['schema'],'predict-current-1')

    async def test_arbs_incremental_cursor_and_filter_snapshot(self):
        from app.dashboard.current_state import CURRENT_KEY
        first=await (await self.client.get('/api/arbs')).json()
        url='/api/arbs?runtime_id='+first['runtime_id']+'&state_revision='+str(first['state_revision'])
        delta=await (await self.client.get(url)).json()
        self.assertEqual(delta['schema'],'predict-arbs-changes-1');self.assertEqual(delta['pairs'],[])
        self.app[CURRENT_KEY].commit(fixture(2))
        delta=await (await self.client.get(url)).json()
        self.assertTrue(delta['changed_event_ids'])
        full=await (await self.client.get('/api/arbs?market=moneyline')).json()
        self.assertEqual(full['schema'],'predict-arbs-1')
        reset=await (await self.client.get('/api/arbs?runtime_id=old&state_revision=1')).json()
        self.assertEqual(reset['schema'],'predict-arbs-1')


class RegistryReuse(unittest.TestCase):
    def test_default_read_only_registry_reuses_and_invalidates_on_replacement(self):
        import tempfile
        from pathlib import Path
        from app.normalization import registry
        original=registry.Registry.load().to_json()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'registry.json';path.write_text(original)
            with patch.object(registry,'DEFAULT_PATH',path):
                first=registry.Registry.current();self.assertIs(first,registry.Registry.current())
                self.assertIsNot(first,registry.Registry.load(path))
                value=json.loads(original);value['version']+='-controlled-update';path.write_text(json.dumps(value))
                second=registry.Registry.current();self.assertIsNot(first,second);self.assertNotEqual(first.version,second.version)
                path.write_text('{}')
                with self.assertRaises(ValueError):registry.Registry.current()
