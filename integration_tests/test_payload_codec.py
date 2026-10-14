"""Lossless storage/history and guarded migration on disposable PostgreSQL only."""
import base64
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4
from unittest.mock import patch
import zlib

import psycopg
from psycopg import sql
from app.storage import store as storage
from app.storage.store import connect, Store, encoded
from app.storage.current_games import GameStore
from app.storage.payload_codec import PREFIX, LEGACY_PREFIX, decode, encode, logical_size_sql

PROJECT = Path(__file__).resolve().parents[1]


def legacy_encoded(payload):
    body=payload.encode()
    return LEGACY_PREFIX+str(len(body))+':'+sha256(body).hexdigest()+':'+base64.b64encode(zlib.compress(body,6)).decode()


def values():
    payload=encoded(dict(price='0.4800',clock='2026-10-14T00:00:00.000000002+00:00',
        evidence=['original immutable content']*4096,null=None)).decode()
    digest=sha256(payload.encode()).hexdigest()
    snapshot=dict(id='snapshot:'+digest,game_key='synthetic:game',input_version='original-input',
        policy_version='original-policy',as_of='2026-10-14T00:00:00+00:00',payload_sha256=digest,payload=payload)
    result=dict(id='result:'+digest,snapshot_id=snapshot['id'],payload_sha256=digest,payload=payload,
        calculated_at='2026-10-14T00:00:01+00:00')
    return snapshot,result


class EncodedHistory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name='prediction_arb_test_codec_'+uuid4().hex[:12]
        with connect() as db:db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        cls.db=connect(cls.name);Store(cls.db).migrate();cls.store=GameStore(cls.db)
        cls.snapshot,cls.result=values()
        cls.store.immutable('current_game_snapshot','id',cls.snapshot)
        cls.store.immutable('current_game_result','id',cls.result)
    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        with connect() as db:db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))

    def test_new_saved_payload_is_compact_but_every_reader_gets_original_bytes(self):
        for table,original in (('current_game_snapshot',self.snapshot),('current_game_result',self.result)):
            physical=self.db.execute(sql.SQL('SELECT payload AS stored_payload FROM {} WHERE id=%s').format(sql.Identifier(table)),(original['id'],)).fetchone()['stored_payload']
            self.assertTrue(physical.startswith(PREFIX));self.assertLess(len(physical),len(original['payload'])//10)
            logical=self.db.execute(sql.SQL('SELECT * FROM {} WHERE id=%s').format(sql.Identifier(table)),(original['id'],)).fetchone()
            self.assertEqual(logical['payload'].encode(),original['payload'].encode())
            self.assertEqual(logical['payload_sha256'],original['payload_sha256'])
            self.assertEqual(json.loads(logical['payload']),json.loads(original['payload']))

    def test_retries_keep_identity_and_reject_conflicts_without_rewriting_history(self):
        with patch('app.storage.payload_codec.encode',side_effect=AssertionError('unchanged saved bytes must be reused')):
            self.store.immutable('current_game_snapshot','id',self.snapshot)
            self.store.immutable('current_game_result','id',self.result)
        changed=dict(self.result,payload=self.result['payload']+' ',payload_sha256='0'*64)
        with self.assertRaisesRegex(ValueError,'conflicting immutable'):
            self.store.immutable('current_game_result','id',changed)
        self.assertEqual(self.db.execute('SELECT count(*) AS n FROM current_game_result').fetchone()['n'],1)
        self.assertEqual(self.db.execute('SELECT payload FROM current_game_result').fetchone()['payload'],self.result['payload'])

    def test_mixed_versions_and_plain_rows_read_exactly_without_rewriting_on_retry(self):
        with self.db.transaction(force_rollback=True):
            for index,transform in enumerate((legacy_encoded,encode,lambda v:v)):
                row=dict(self.snapshot,id='mixed-snapshot-'+str(index),payload=transform(self.snapshot['payload']))
                columns=list(row)
                self.db.execute(sql.SQL('INSERT INTO current_game_snapshot ({}) VALUES ({})').format(sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(sql.Placeholder() for _ in columns)),list(row.values()))
                logical=self.db.execute('SELECT payload FROM current_game_snapshot WHERE id=%s',(row['id'],)).fetchone()['payload']
                self.assertEqual(logical.encode(),self.snapshot['payload'].encode())
                with patch('app.storage.payload_codec.encode',side_effect=AssertionError('existing representations are immutable')):
                    self.store.immutable('current_game_snapshot','id',dict(row,payload=self.snapshot['payload']))
                physical=self.db.execute('SELECT payload AS stored_payload FROM current_game_snapshot WHERE id=%s',(row['id'],)).fetchone()['stored_payload']
                self.assertEqual(physical,row['payload'])
                logical_bytes=self.db.execute(sql.SQL('SELECT {} AS n FROM current_game_snapshot WHERE id=%s').format(logical_size_sql()),(row['id'],)).fetchone()['n']
                self.assertEqual(logical_bytes,len(self.snapshot['payload'].encode()))

    def test_envelope_codec_preserves_original_bytes_hashes_and_immutable_triggers(self):
        original=dict(source='synthetic',kind='catalog',retained_at='2026-10-14T00:00:00+00:00',value={'facts':['original']*2048})
        eid=self.store.envelope(original)
        row=self.db.execute('SELECT payload AS stored_payload FROM current_envelope WHERE id=%s',(eid,)).fetchone()
        self.assertTrue(row['stored_payload'].startswith(PREFIX))
        self.assertEqual(decode(row['stored_payload']),encoded(original).decode())
        self.assertEqual(self.db.execute('SELECT payload FROM current_envelope WHERE id=%s',(eid,)).fetchone()['payload'],encoded(original).decode())
        for table in ('current_game_snapshot','current_game_result','current_envelope'):
            with self.assertRaises(psycopg.Error):self.db.execute(sql.SQL("UPDATE {} SET payload=payload||'tamper'").format(sql.Identifier(table)))
            with self.assertRaises(psycopg.Error):self.db.execute(sql.SQL('DELETE FROM {}').format(sql.Identifier(table)))

    def test_all_capture_paths_refuse_expanded_byte_cap_before_decoding(self):
        with self.db.transaction(force_rollback=True):
            total=0
            for i in range(4):
                original=dict(source='kalshi',kind='catalog',retained_at='2026-10-14T00:00:00+00:00',
                    value={'index':i,'evidence':'x'*(7*1024*1024)})
                eid=self.store.envelope(original)
                if i%2==0:
                    self.db.execute('ALTER TABLE current_envelope DISABLE TRIGGER immutable_current_envelope')
                    self.db.execute('UPDATE current_envelope SET payload=%s WHERE id=%s',(legacy_encoded(encoded(original).decode()),eid))
                    self.db.execute('ALTER TABLE current_envelope ENABLE TRIGGER immutable_current_envelope')
                self.store.source('kalshi','catalog',str(i),original['retained_at'],eid,{})
                size=self.db.execute(sql.SQL('SELECT {} AS logical_bytes FROM current_envelope WHERE id=%s').format(logical_size_sql()),(eid,)).fetchone()['logical_bytes']
                self.assertEqual(size,len(encoded(original)));total+=size
            self.assertGreater(total,24*1024*1024)
            for reader in (self.store.combined_envelopes,self.store.combined_capture,self.store.combined_read_capture):
                with patch('app.storage.payload_codec.decode',side_effect=AssertionError('oversized rows must never reach decoding')) as decoder:
                    with self.assertRaisesRegex(ValueError,'combined_input_capacity'):reader()
                    decoder.assert_not_called()

    def test_malformed_codec_header_is_refused_in_sql_before_decode(self):
        with self.db.transaction(force_rollback=True):
            original=dict(source='kalshi',kind='catalog',retained_at='2026-10-14T00:00:00+00:00',value={'evidence':['original']*2048})
            eid=self.store.envelope(original);self.store.source('kalshi','catalog','bad-header',original['retained_at'],eid,{})
            for prefix in (PREFIX,LEGACY_PREFIX):
                self.db.execute('ALTER TABLE current_envelope DISABLE TRIGGER immutable_current_envelope')
                self.db.execute('UPDATE current_envelope SET payload=%s WHERE id=%s',(prefix+'bad-header',eid))
                self.db.execute('ALTER TABLE current_envelope ENABLE TRIGGER immutable_current_envelope')
                with patch('app.storage.payload_codec.decode',side_effect=AssertionError('malformed rows must never reach decoding')) as decoder:
                    with self.assertRaisesRegex(ValueError,'combined_input_capacity'):self.store.combined_read_capture()
                    decoder.assert_not_called()


class RepresentationMigration(unittest.TestCase):
    def test_envelope_only_migration_preserves_completed_saved_table_representations(self):
        name='prediction_arb_test_envelope_'+uuid4().hex[:12]
        with connect() as db:db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            snapshot,result=values()
            original=encoded(dict(source='kalshi',kind='catalog',retained_at='2026-10-14T00:00:00+00:00',value={'evidence':['original inventory']*4096})).decode()
            envelope=dict(id='original-envelope',payload_sha256=sha256(original.encode()).hexdigest(),payload=original,
                source='kalshi',kind='catalog',retained_at='2026-10-14T00:00:00+00:00')
            with connect(name) as db:
                Store(db).migrate()
                for table,row in (('current_game_snapshot',snapshot),('current_game_result',result),('current_envelope',envelope)):
                    stored=dict(row)
                    if table!='current_envelope':stored['payload']=encode(row['payload'])
                    names=list(stored)
                    db.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,names)),sql.SQL(',').join(sql.Placeholder() for _ in names)),list(stored.values()))
            spec=importlib.util.spec_from_file_location('compact_saved_envelopes',PROJECT/'scripts/compact_saved_payloads.py')
            migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
            with tempfile.TemporaryDirectory() as directory:
                backup=Path(directory)/'original.dump';output=Path(directory)/'rewrite'
                subprocess.run(['pg_dump','-h',str(storage.ROOT/'.local/pgsocket'),'-p','55432','-U','prediction_arb','-Fc','-f',str(backup),name],check=True,timeout=30)
                plan=migration.inspect(name,output,backup,tables=('current_envelope',))
                self.assertEqual(plan['selected_tables'],['current_envelope']);self.assertEqual(set(plan['tables']),{'current_envelope'})
                with self.assertRaisesRegex(ValueError,'payload_table_selection_conflict'):
                    migration.apply(name,output,tables=('current_game_snapshot',))
                original_summary=migration.summary;calls=[0]
                def fail_verification(db,table,*args):
                    calls[0]+=1
                    if calls[0]==2:raise ValueError('injected_after_envelope_rewrite')
                    return original_summary(db,table,*args)
                with patch.object(migration,'summary',side_effect=fail_verification),self.assertRaisesRegex(ValueError,'injected_after_envelope_rewrite'):
                    migration.apply(name,output,tables=('current_envelope',))
                with connect(name) as db:
                    self.assertEqual(db.execute('SELECT payload AS stored_payload FROM current_envelope').fetchone()['stored_payload'],original)
                    self.assertEqual(db.execute("SELECT tgenabled FROM pg_trigger WHERE tgname='immutable_current_envelope'").fetchone()['tgenabled'],'O')
                report=migration.apply(name,output,vacuum=True,tables=('current_envelope',))
                self.assertEqual(report['immutable_triggers'],[dict(tgname='immutable_current_envelope',tgenabled='O')])
                with connect(name) as db:
                    self.assertEqual(db.execute('SELECT payload FROM current_envelope').fetchone()['payload'],original)
                    self.assertTrue(db.execute('SELECT payload AS stored_payload FROM current_envelope').fetchone()['stored_payload'].startswith(PREFIX))
                    for table,row in (('current_game_snapshot',snapshot),('current_game_result',result)):
                        physical=db.execute(sql.SQL('SELECT payload AS stored_payload FROM {}').format(sql.Identifier(table))).fetchone()['stored_payload']
                        self.assertEqual(physical,encode(row['payload']))
                    GameStore(db).envelope(json.loads(original),'original-envelope')
        finally:
            with connect() as db:db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))

    def test_exact_archived_rows_latest_history_and_triggers_survive_rewrite(self):
        name='prediction_arb_test_rewrite_'+uuid4().hex[:12]
        with connect() as db:db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            snapshot,result=values()
            with connect(name) as db:
                Store(db).migrate()
                for table,row in (('current_game_snapshot',snapshot),('current_game_result',result)):
                    names=list(row)
                    db.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,names)),sql.SQL(',').join(sql.Placeholder() for _ in names)),list(row.values()))
                db.execute('INSERT INTO current_latest_result VALUES (%s,%s,%s,%s)',('synthetic:game','original-policy','original-input',result['id']))
            spec=importlib.util.spec_from_file_location('compact_saved_payloads',PROJECT/'scripts/compact_saved_payloads.py')
            migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
            with tempfile.TemporaryDirectory() as directory:
                backup=Path(directory)/'original.dump';output=Path(directory)/'rewrite'
                subprocess.run(['pg_dump','-h',str(storage.ROOT/'.local/pgsocket'),'-p','55432','-U','prediction_arb','-Fc','-f',str(backup),name],check=True,timeout=30)
                before=migration.inspect(name,output,backup)
                self.assertFalse(before['applied'])
                original_summary=migration.summary
                def fail_second_table(db,table,*args):
                    if table=='current_game_result':raise ValueError('injected_before_second_table')
                    return original_summary(db,table,*args)
                with patch.object(migration,'summary',side_effect=fail_second_table),self.assertRaisesRegex(ValueError,'injected_before_second_table'):
                    migration.apply(name,output)
                with connect(name) as db:
                    self.assertEqual(db.execute('SELECT payload AS stored_payload FROM current_game_snapshot').fetchone()['stored_payload'],snapshot['payload'])
                    states=db.execute("SELECT tgenabled FROM pg_trigger WHERE tgname IN ('immutable_current_game_snapshot','immutable_current_game_result')").fetchall()
                    self.assertTrue(all(row['tgenabled']=='O' for row in states))
                report=migration.apply(name,output,vacuum=True)
                self.assertTrue(report['applied']);self.assertTrue(report['vacuumed'])
                self.assertEqual(report['latest_pointer_sha256'],before['latest_pointer_sha256'])
                self.assertTrue(all(row['tgenabled']=='O' for row in report['immutable_triggers']))
                with connect(name) as db,db.transaction():
                    db.execute("SET LOCAL TIME ZONE 'UTC'")
                    for table,original in (('current_game_snapshot',snapshot),('current_game_result',result)):
                        after=migration.summary(db,table)
                        self.assertEqual(after['logical_rows_sha256'],before['tables'][table]['logical_rows_sha256'])
                        row=db.execute(sql.SQL('SELECT *,payload AS stored_payload FROM {}').format(sql.Identifier(table))).fetchone()
                        self.assertEqual(row['payload'],original['payload'])
                        self.assertEqual(decode(row['stored_payload']),original['payload'])
                        self.assertEqual(row['payload_sha256'],original['payload_sha256'])
                        self.assertTrue(row['stored_payload'].startswith(PREFIX))
                        with self.assertRaises(psycopg.Error),db.transaction():db.execute(sql.SQL("UPDATE {} SET payload=payload||'tamper'").format(sql.Identifier(table)))
                    self.assertEqual(db.execute('SELECT result_id FROM current_latest_result').fetchone()['result_id'],result['id'])
                with self.assertRaisesRegex(ValueError,'payload_rewrite_already_committed'):
                    migration.apply(name,output)
        finally:
            with connect() as db:db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


if __name__ == '__main__':
    unittest.main()
