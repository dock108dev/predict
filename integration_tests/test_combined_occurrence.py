"""N01 writes only disposable SQL data; originals retain explicit envelope IDs."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from uuid import uuid4
from psycopg import sql
from app.storage.store import connect,Store,hashed
from app.storage.current_games import GameStore,calculate,age_result
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.comparison.combined_inputs import build
from tests.test_ev09_n01 import retained,AT,SELECTED

class CombinedStorage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name='prediction_arb_test_n01_'+uuid4().hex[:12]
        with connect() as db:db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        cls.db=connect(cls.name);Store(cls.db).migrate();cls.store=GameStore(cls.db)
        cls.bundle=deepcopy(retained()[0]);cls.key=cls.store.retain_combined(cls.bundle)
        cls.snapshot=cls.store.snapshot(cls.key,DEFAULT_POLICY)
        cls.result=calculate(cls.snapshot);cls.rid,published=cls.store.publish(cls.snapshot,cls.result);assert published
    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        with connect() as db:db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))
    def test_exact_original_envelopes(self):
        for e in self.bundle['envelopes']:
            row=self.db.execute('SELECT payload,payload_sha256 FROM current_envelope WHERE id=%s',(e['id'],)).fetchone()
            self.assertEqual(json.loads(row['payload']),e['record']);self.assertEqual(row['payload_sha256'],e['payload_sha256'])
    def test_sql_input_benchmark_and_result_roundtrip(self):
        row=self.db.execute('SELECT payload FROM current_game_snapshot WHERE id=%s',(self.snapshot['id'],)).fetchone()
        saved=json.loads(row['payload']);self.assertEqual(saved['projection']['inputs'],self.bundle)
        row=self.db.execute('SELECT payload,payload_sha256 FROM current_game_result WHERE id=%s',(self.rid,)).fetchone()
        self.assertEqual(json.loads(row['payload']),self.result);self.assertEqual(row['payload_sha256'],hashed(self.result))
    def test_immutable_snapshot_result_and_envelope(self):
        for table,key in [('current_game_snapshot',self.snapshot['id']),('current_game_result',self.rid),('current_envelope',self.bundle['envelope_ids'][0])]:
            with self.assertRaises(Exception),self.db.transaction():self.db.execute(sql.SQL('UPDATE {} SET payload=%s WHERE id=%s').format(sql.Identifier(table)),('{}',key))
    def test_saved_replay_keeps_original_time(self):
        a=calculate(self.snapshot);b=deepcopy(self.result)
        a.pop('calculated_at');b.pop('calculated_at');self.assertEqual(a,b)
        with self.assertRaisesRegex(ValueError,'original_evaluation_instant_conflict'):self.store.snapshot(self.key,DEFAULT_POLICY,at='2026-10-15T00:00:00Z')
    def test_policy_variant_identity_and_reader(self):
        p=replace(DEFAULT_POLICY,capital_ceiling_usd='500');snap=self.store.snapshot(self.key,p)
        self.assertNotEqual(snap['id'],self.snapshot['id'])
        later=age_result(self.result,at='2026-10-17T00:00:00Z')
        self.assertEqual(later['as_of'],AT);self.assertEqual(later['status'],'historical')
    def test_changed_input_refuses_stale_publication(self):
        key='combined:authored:'+uuid4().hex
        v=deepcopy(self.snapshot['projection']);v['game_key']=key
        self.db.execute('INSERT INTO current_game_projection VALUES (%s,%s,%s,now())',(key,v['input_version'],json.dumps(v)))
        snap=self.store.snapshot(key,DEFAULT_POLICY)
        self.db.execute('UPDATE current_game_projection SET input_version=%s WHERE game_key=%s',('authored-changed-member',key))
        result=dict(self.result,calculated_at=AT);rid,published=self.store.publish(snap,result)
        self.assertFalse(published);self.assertIsNone(self.store.result(key,DEFAULT_POLICY))
        self.assertTrue(self.db.execute('SELECT 1 FROM current_game_result WHERE id=%s',(rid,)).fetchone())
    def test_projection_association_loader(self):
        # All ingress writes belong to this disposable DB only.
        for e in self.bundle['envelopes']:self.store.import_record(e['record'],e['id'])
        rows=self.store.combined_envelopes();ids={r['id'] for r in rows}
        self.assertTrue(set(self.bundle['envelope_ids'])<=ids)
        rebuilt=build(rows,at=AT,selected=SELECTED)[0]
        self.assertEqual(rebuilt['input_version'],self.bundle['input_version'])
