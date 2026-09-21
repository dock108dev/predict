"""Captured replays and separately labeled synthetic identity edge cases."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.normalization import Registry, enrich_event, resolve_team, resolve_league
from app.normalization.names import name_key
from app.normalization_example import captured_events, report


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.r = Registry.load()

    def test_complete_membership_and_explicit_aliases(self):
        expected = set('ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LV LAC LAR MIA MIN NE NO NYG NYJ PHI PIT SF SEA TB TEN WAS'.split())
        teams = {e['id'].split(':')[1] for e in self.r.entities.values() if e.get('league')=='NFL'}
        self.assertEqual(teams, expected)
        self.assertEqual(sum(e.get('league')=='MLB' for e in self.r.entities.values()),30)
        for name in ('Dallas Cowboys','DAL','Cowboys','Dallas',' dallas  cowboys ', 'D.A.L.'):
            self.assertEqual(resolve_team(name,league='nfl',registry=self.r).canonical_id,'NFL:DAL')
        self.assertEqual(resolve_league('National Football League',registry=self.r).canonical_id,'NFL')
        self.assertEqual(resolve_team('JAC',league='NFL',registry=self.r).canonical_id,'NFL:JAX')
        self.assertEqual(resolve_team('NY Yankees',league='MLB',registry=self.r).canonical_id,'MLB:NYY')

    def test_cross_league_and_shared_city_ambiguity(self):
        for name in ('CIN','Giants','Cardinals','New York','Los Angeles'):
            with self.subTest(name=name):self.assertEqual(self.r.resolve('team',name).status,'ambiguous')
        self.assertEqual(self.r.resolve('team','CIN',league='MLB').canonical_id,'MLB:CIN')
        self.assertEqual(self.r.resolve('team','New York',league='NFL').candidates,('NFL:NYG','NFL:NYJ'))
        self.assertEqual(self.r.resolve('team','Los Angeles',league='MLB').candidates,('MLB:LAA','MLB:LAD'))
        self.assertIsNone(self.r.resolve('team','Giants').canonical_id)

    def test_missing_unknown_and_unsupported_context(self):
        for name,context in [(None,{}),('Invented',{}),('DAL',{}),('Panthers',{}),('Dallas',{'league':'NBA'}),('Oakland Raiders',{'league':'NFL'})]:
            with self.subTest(name=name):self.assertEqual(self.r.resolve('team',name,**context).status,'unknown')
        self.assertEqual(self.r.resolve('team','Dallas Cowboys').canonical_id,'NFL:DAL')
        for league in ('NBA','NHL','NCAAF'):
            self.assertEqual(self.r.resolve('league',league).status,'unknown')
        self.assertNotEqual(name_key('LA'),name_key('L A'))
        self.assertNotEqual(name_key('49ers'),name_key('ers'))
        self.assertNotEqual(name_key('é'),name_key('e'))

    def test_native_scoping_conflict_and_provenance(self):
        c=dict(league='NFL',venue='polymarket_us',environment='production',native_id='77')
        r=self.r.resolve('team',**c)
        self.assertEqual(r.canonical_id,'NFL:TB')
        self.assertTrue(any('pmus-nfl-events.json#/events/' in p for p in r.provenance))
        self.assertEqual(self.r.resolve('team','Dallas Cowboys',**c).status,'conflicting')
        self.assertEqual(self.r.resolve('team','Unrecognized',**c).status,'conflicting')
        for change in ({'environment':'sandbox'},{'venue':'kalshi'},{'league':'MLB'},{'environment':None},{'league':None}):
            self.assertEqual(self.r.resolve('team',**{**c,**change}).status,'unknown')
        self.assertEqual(self.r.resolve('league','NFL',venue='prophetx',environment='sandbox',native_id='31').canonical_id,'NFL')
        self.assertEqual(self.r.resolve('league','MLB',venue='prophetx',environment='sandbox',native_id='31').status,'conflicting')
        unmapped=self.r.resolve('team','Dallas Cowboys',**{**c,'native_id':'not-a-team-id'})
        self.assertEqual(unmapped.canonical_id,'NFL:DAL')
        self.assertIn('native-id-unmapped; name-only-resolution',unmapped.provenance)
        self.assertEqual(len(self.r.native),77)

    def test_validation_duplicate_conflicting_rows_and_targets(self):
        base=json.loads(self.r.to_json())
        mutations=[lambda d:d['entities'].append(d['entities'][0]),
          lambda d:d['aliases'].append(d['aliases'][0]),
          lambda d:d['aliases'][0].update(targets=['absent']),
          lambda d:d['native_mappings'].append({**d['native_mappings'][1],'target':'NFL:DAL'}),
          lambda d:d['native_mappings'][1].update(league='MLB'),
          lambda d:d['native_mappings'][1].update(source=''),
          lambda d:d.update(schema_version=2),
          lambda d:d['aliases'][0].update(targets=['NFL','NFL'])]
        for mutation in mutations:
            data=deepcopy(base);mutation(data)
            with self.assertRaises(ValueError):Registry(data)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.json';p.write_text('{"schema_version":1,"schema_version":2}')
            with self.assertRaises(ValueError):Registry.load(p)

    def test_synthetic_reused_id_has_independent_environment_identity(self):
        data=json.loads(self.r.to_json())
        data['native_mappings'].append({'kind':'team','venue':'polymarket_us','environment':'synthetic-env',
            'league':'NFL','native_id':'77','target':'NFL:DAL','source':'synthetic scoped ID edge'})
        r=Registry(data)
        self.assertEqual(r.resolve('team',league='NFL',venue='polymarket_us',environment='synthetic-env',native_id='77').canonical_id,'NFL:DAL')
        self.assertEqual(r.resolve('team',league='NFL',venue='polymarket_us',environment='production',native_id='77').canonical_id,'NFL:TB')

    def test_validation_malformed_and_immutable_indexes(self):
        for data in ({}, [], {'entities':None}):
            with self.assertRaises(ValueError):Registry(data)
        with self.assertRaises(TypeError):self.r.entities['NFL:DAL']['name']='Changed'
        before=self.r.to_json()
        self.r.resolve('team','Brand new unknown',league='NFL')
        self.assertEqual(before,self.r.to_json())

    def test_synthetic_scoped_alias_does_not_merge_entities(self):
        data=json.loads(self.r.to_json())
        data['aliases'].append({'kind':'team','league':'NFL','venue':'synthetic','text':'Old Harbor Club',
                                'targets':['NFL:DAL'],'source':'synthetic rename edge; not real history'})
        r=Registry(data)
        self.assertEqual(r.resolve('team','Old Harbor Club',league='NFL').status,'unknown')
        self.assertEqual(r.resolve('team','Old Harbor Club',league='NFL',venue='synthetic').canonical_id,'NFL:DAL')
        self.assertEqual(r.resolve('team','Old Harbor Club',league='MLB',venue='synthetic').status,'unknown')

    def test_persistence_and_fresh_process_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'registry.json';self.r.save(p)
            self.assertEqual(Registry.load(p).to_json(),self.r.to_json())
            code="from app.normalization import Registry; from dataclasses import asdict; import json,sys; r=Registry.load(sys.argv[1]); print(json.dumps(asdict(r.resolve('team','Giants')),sort_keys=True))"
            results=[subprocess.check_output([sys.executable,'-c',code,str(p)]) for _ in range(2)]
            self.assertEqual(results[0],results[1])
            self.assertEqual(json.loads(results[0])['registry_sha256'],self.r.fingerprint)


class ObservationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.r=Registry.load()
        # No live socket may be opened by the replay or enrichment.
        with patch('socket.socket.connect',side_effect=AssertionError('network prohibited')):
            self.events=await captured_events()

    async def test_actual_capture_coverage_order_and_preservation(self):
        expected={'polymarket_us':(10,20),'prophetx':(32,28),'kalshi':(5,10)}
        for venue,(count,unique) in expected.items():
            selected=[(e,env) for e,env,_ in self.events if e.raw.ref.venue==venue]
            self.assertEqual(len(selected),count)
            found=set()
            for e,env in selected:
                before=e.raw.json_text
                result=enrich_event(e,environment=env,registry=self.r)
                self.assertIs(result.observation,e)
                self.assertEqual(result.observation.raw.json_text,before)
                self.assertIsNone(e.canonical_id)
                self.assertEqual(result.league.status,'resolved')
                for p in result.participants:
                    self.assertEqual(p.resolution.status,'resolved')
                    self.assertTrue(p.extraction)
                    self.assertTrue(p.resolution.provenance)
                    found.add(p.resolution.canonical_id)
            self.assertEqual(len(found),unique)
        px=next((e,env) for e,env,_ in self.events if e.raw.ref.venue=='prophetx')
        r=enrich_event(px[0],environment=px[1],registry=self.r)
        self.assertEqual([(p.name,p.role) for p in r.participants],[('Carolina Panthers','home'),('Chicago Bears','away')])
        pm=next(e for e,_,_ in self.events if e.raw.ref.venue=='polymarket_us')
        self.assertTrue(all(p.role is None for p in enrich_event(pm,environment='production',registry=self.r).participants))
        k=next(e for e,_,_ in self.events if e.raw.ref.venue=='kalshi')
        self.assertTrue(all(p.native_id is None and p.role is None for p in enrich_event(k,environment='production',registry=self.r).participants))

    async def test_synthetic_mutation_native_name_and_league_conflicts(self):
        e=next(e for e,_,_ in self.events if e.raw.ref.venue=='polymarket_us')
        d=e.raw.decode();d['events'][0]['teams'][0]['name']='Dallas Cowboys'
        changed=replace(e,raw=replace(e.raw,json_text=json.dumps(d,default=str)))
        self.assertEqual(enrich_event(changed,environment='production',registry=self.r).participants[0].resolution.status,'conflicting')
        changed=replace(e,participants=('Tampa Bay Buccaneers',))
        result=enrich_event(changed,environment='production',registry=self.r)
        self.assertTrue(all(p.resolution.status=='conflicting' for p in result.participants))
        changed=replace(e,league='MLB')
        result=enrich_event(changed,environment='production',registry=self.r)
        self.assertEqual(result.league.status,'conflicting')
        self.assertTrue(all(p.resolution.status=='unknown' for p in result.participants))

    async def test_synthetic_unknown_title_format_stays_unresolved(self):
        e=next(e for e,_,_ in self.events if e.raw.ref.venue=='kalshi')
        d=e.raw.decode();d['events'][0]['title']='Atlanta vs Pittsburgh vs Dallas'
        changed=replace(e,raw=replace(e.raw,json_text=json.dumps(d,default=str)))
        result=enrich_event(changed,environment='production',registry=self.r)
        self.assertEqual(result.extraction_status,'unknown')
        # A three-team title must never become a two-team event.
        self.assertFalse(all(p.resolution.status=='resolved' for p in result.participants) and result.participants)

    async def test_example_labels_and_coverage_are_separate(self):
        r=await report()
        self.assertEqual(sum(x['events'] for x in r['coverage'] if x['evidence_class']=='actual_capture'),47)
        self.assertTrue(all(x['evidence_class']=='synthetic' for x in r['records'] if x['venue']=='novig'))
        self.assertEqual({x['result']['status'] for x in r['synthetic_edges']},{'ambiguous','unknown','conflicting'})
        self.assertTrue(all(x['evidence_class']=='documentation_example' for x in r['documentation_examples']))
