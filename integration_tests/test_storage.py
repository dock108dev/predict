"""REAL PostgreSQL tests. Each run creates/removes only its named disposable DB."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from psycopg import sql, errors
from app.storage import Store, connect, CapturePolicy
from app.storage.store import hashed
from app.storage.workflow import packet
from app.storage.replay import detector_audit
from app.depth_example import fixture, run
from app.arbitrage_example import NOW


class PostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name='prediction_arb_test_'+uuid.uuid4().hex[:12]
        cls.admin=connect()
        cls.admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        cls.db=connect(cls.name); cls.s=Store(cls.db); cls.s.migrate()
        cls.data,cls.ladders=fixture()
        p,m,obs,ctx,_=cls.data
        cls.audit=json.loads(json.dumps(detector_audit(p,m,obs,ctx,evaluation_time=NOW,fill_grouping='single_fill_per_leg')))
        cls.depth=json.loads(json.dumps(run(cls.data,cls.ladders)))['candidates'][0]

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))
        cls.admin.close()

    def setUp(self):
        self.tx=self.db.transaction(); self.tx.__enter__()
        self.sid=self.s.start('synthetic','synthetic','integration fixture')
        self.p=packet(self.data[2][0])

    def tearDown(self):
        # Roll back only this disposable database's case, never historical evidence.
        self.tx.__exit__(RuntimeError,RuntimeError('test rollback'),None)

    def test_migrations_idempotent(self):
        self.s.migrate(); self.s.migrate()
        self.assertEqual(self.db.execute('select count(*) n from schema_migration').fetchone()['n'],6)

    def test_raw_decimal_timestamp_precision(self):
        self.p['raw']=b'{ "decimal":0.123456789012345678901234567890, "x": 1 }\n'
        self.p['received_at']='2026-09-12T02:00:00.123456789123+00:00'
        self.p['source_time']='2026-09-12T01:59:59.999999999999Z'
        self.p['normalized']['quotes'][0]['ask']='0.123456789012345678901234567890'
        self.s.receipt(self.sid,'r',self.p)
        row=self.db.execute('select * from receipt where session_id=%s',(self.sid,)).fetchone()
        body=self.db.execute('select content from artifact where hash=%s',(row['raw_hash'],)).fetchone()['content']
        self.assertEqual(bytes(body),self.p['raw'])
        self.assertEqual(row['received_text'],self.p['received_at']); self.assertEqual(row['source_time_text'],self.p['source_time'])
        self.assertEqual(self.db.execute('select ask from quote_observation where session_id=%s',(self.sid,)).fetchone()['ask'],Decimal('0.123456789012345678901234567890'))

    def test_retry_and_distinct_identical_receipts(self):
        self.s.receipt(self.sid,'one',self.p); self.s.receipt(self.sid,'one',self.p)
        self.s.receipt(self.sid,'two',self.p)
        rows=self.db.execute('select * from receipt where session_id=%s order by id',(self.sid,)).fetchall()
        self.assertEqual(len(rows),2); self.assertEqual(rows[0]['raw_hash'],rows[1]['raw_hash'])
        self.assertTrue(rows[0]['changed']); self.assertFalse(rows[1]['changed'])
        self.s.receipt(self.sid,'one',self.p)  # retry after later receipts does not change flags

    def test_identity_collision_rejected(self):
        self.s.receipt(self.sid,'one',self.p)
        p=deepcopy(self.p); p['raw']=b'{"changed":true}'
        with self.assertRaises(ValueError): self.s.receipt(self.sid,'one',p)
        self.assertEqual(self.db.execute('select count(*) n from receipt where session_id=%s',(self.sid,)).fetchone()['n'],1)

    def test_size_status_locks_clock_qualification_changes(self):
        self.s.receipt(self.sid,'0',self.p)
        for i,(k,v) in enumerate([('state','suspended'),('locks_clear',False),('source_time_problem','regressed'),('units_verified',False)],1):
            p=deepcopy(self.p); p['normalized'][k]=v
            self.s.receipt(self.sid,str(i),p)
        p=deepcopy(self.p); p['normalized']['quotes'][0]['ask_size']='42'
        self.s.receipt(self.sid,'5',p)
        self.assertEqual(self.db.execute('select count(*) n from receipt where session_id=%s and changed',(self.sid,)).fetchone()['n'],6)

    def test_periodic_full_context(self):
        for i in (0,10,20,30):
            p=deepcopy(self.p); p['received_at']=f'2026-09-12T02:00:{i:02d}+00:00'
            p['normalized']['levels']=[['0.2',str(i+1)]]
            self.s.receipt(self.sid,str(i),p)
        rows=self.db.execute('select snapshot_reason,changed from receipt where session_id=%s order by received_at',(self.sid,)).fetchall()
        self.assertEqual(rows[-1]['snapshot_reason'],'periodic')
        self.assertFalse(rows[-1]['changed'])

    def test_clock_regression_is_gap(self):
        self.s.receipt(self.sid,'one',self.p)
        p=deepcopy(self.p); p['received_at']='2026-09-11T00:00:00+00:00'
        self.s.receipt(self.sid,'two',p)
        self.assertEqual(self.db.execute("select count(*) n from coverage_event where session_id=%s and kind='gap'",(self.sid,)).fetchone()['n'],1)

    def test_scope_isolation(self):
        p=deepcopy(self.p); p['evidence_class']='historical'
        with self.assertRaises(ValueError): self.s.receipt(self.sid,'r',p)
        sid=self.s.start('production','historical','isolated historical')
        with self.assertRaises(ValueError): self.s.calculation(sid,'wrong',self.audit)

    def test_foreign_key_rollback(self):
        before=self.db.execute('select count(*) n from artifact').fetchone()['n']
        with self.assertRaises(errors.ForeignKeyViolation):
            self.s.calculation(self.sid,'broken',self.audit,['absent-receipt'])
        self.assertIsNone(self.db.execute('select 1 from calculation where session_id=%s',(self.sid,)).fetchone())
        self.assertEqual(before,self.db.execute('select count(*) n from artifact').fetchone()['n'])

    def test_transaction_rollback(self):
        with self.assertRaises(RuntimeError):
            with self.db.transaction():
                self.s.receipt(self.sid,'r',self.p); raise RuntimeError('interrupt')
        self.assertIsNone(self.db.execute('select 1 from receipt where session_id=%s',(self.sid,)).fetchone())

    def test_restart_leaves_incomplete_and_new_session(self):
        self.s.receipt(self.sid,'r',self.p)
        self.assertEqual(self.db.execute('select state from capture_session where id=%s',(self.sid,)).fetchone()['state'],'running')
        self.s.interrupt(self.sid)
        with self.assertRaises(ValueError): self.s.receipt(self.sid,'x',self.p)
        new=self.s.start('synthetic','synthetic','restarted, new timeline')
        self.assertNotEqual(self.sid,new)
        self.assertEqual(self.db.execute('select state from capture_session where id=%s',(self.sid,)).fetchone()['state'],'interrupted')

    def test_failure_and_gap_recorded(self):
        def packets():
            yield 'one',self.p
            raise RuntimeError('simulated upstream disconnect')
        with self.assertRaises(RuntimeError): self.s.ingest(self.sid,packets())
        self.assertEqual(self.db.execute('select state from capture_session where id=%s',(self.sid,)).fetchone()['state'],'failed')
        self.assertEqual(self.db.execute("select count(*) n from coverage_event where session_id=%s and kind='failure'",(self.sid,)).fetchone()['n'],1)
        self.s.event(self.sid,'disconnect',dict(reason='simulated stream disconnect'))

    def test_bounded_ingestion_and_no_silent_drop(self):
        sid=self.s.start('synthetic','synthetic','limit fixture',CapturePolicy(max_receipts=1))
        self.assertEqual(self.s.ingest(sid,[('one',self.p),('two',self.p)]),1)
        self.assertIsNotNone(self.db.execute("select 1 from coverage_event where session_id=%s and kind='limit'",(sid,)).fetchone())

    def test_oversized_payload_fails_explicitly(self):
        sid=self.s.start('synthetic','synthetic','limit fixture',CapturePolicy(max_payload_bytes=1))
        with self.assertRaises(ValueError): self.s.ingest(sid,[('one',self.p)])
        self.assertEqual(self.db.execute('select state from capture_session where id=%s',(sid,)).fetchone()['state'],'failed')

    def test_calculations_roundtrip_versions_and_retry(self):
        self.s.receipt(self.sid,'r',self.p)
        self.s.calculation(self.sid,'det',self.audit,['r']); self.s.calculation(self.sid,'det',self.audit,['r'])
        self.s.calculation(self.sid,'depth',self.depth,['r'])
        self.assertEqual(self.s.replay_all(),2)
        changed=deepcopy(self.audit); changed['input_hash']='0'*64
        with self.assertRaises(ValueError): self.s.calculation(self.sid,'bad',changed)
        self.assertEqual(self.db.execute('select count(distinct engine) n from calculation where session_id=%s',(self.sid,)).fetchone()['n'],2)

    def test_receipt_set_cannot_change_on_retry(self):
        self.s.receipt(self.sid,'r',self.p)
        self.s.calculation(self.sid,'det',self.audit,[])
        with self.assertRaises(ValueError): self.s.calculation(self.sid,'det',self.audit,['r'])

    def test_candidate_positive_negative_missing_transitions(self):
        from app.arbitrage_example import synthetic_inputs
        from datetime import timedelta
        self.s.calculation(self.sid,'det0',self.audit)
        p,m,obs,ctx,_=synthetic_inputs('0.55','0.55')
        negative=detector_audit(p,m,obs,ctx,evaluation_time=NOW+timedelta(seconds=1),fill_grouping='single_fill_per_leg')
        self.s.calculation(self.sid,'det1',negative)
        missing=detector_audit(p,m,[],ctx,evaluation_time=NOW+timedelta(seconds=2),fill_grouping='single_fill_per_leg')
        self.s.calculation(self.sid,'det2',missing)
        cid=next(c['id'] for c in self.audit['result']['candidates'] if c['conditional_calculation'])
        states=[r['state'] for r in self.s.history(self.sid,cid)['observations']]
        self.assertEqual(states,['conditional-positive','observed-nonpositive','unavailable-or-ineligible'])

    def test_candidate_disappearance_is_not_negative_price(self):
        from app.matching import Matcher
        from app.moneyline import MoneylineMatcher
        from datetime import timedelta
        self.s.calculation(self.sid,'det0',self.audit)
        empty=detector_audit(Matcher(),MoneylineMatcher(),[],{},evaluation_time=NOW+timedelta(seconds=1))
        self.s.calculation(self.sid,'det1',empty)
        cid=self.audit['result']['candidates'][0]['id']
        self.assertEqual(self.s.history(self.sid,cid)['observations'][-1]['state'],'not-observed')


    def test_shared_subtrees_exact_roundtrip(self):
        shared={'large':['abc'*2000]*3}
        with self.db.transaction():
            one=self.s.put({'one':shared,'decimal':'1.0000000000000000001'})
            two=self.s.put({'two':shared,'decimal':'2'})
        self.assertEqual(self.s.get(one),{'one':shared,'decimal':'1.0000000000000000001'})
        self.assertEqual(self.s.get(two)['two'],shared)
        self.assertIsNotNone(self.db.execute('select child from artifact_edge group by child having count(*)>1').fetchone())

    def test_history_is_censored_not_gap_duration(self):
        self.s.calculation(self.sid,'det',self.audit)
        self.s.event(self.sid,'gap',{'reason':'no observations between samples'})
        history=self.s.history(self.sid,self.audit['result']['candidates'][0]['id'])
        self.assertEqual(history['observed_duration_seconds'],'0'); self.assertTrue(history['censored'])
        self.assertTrue(history['coverage']); self.assertTrue(history['observations'][0]['liquidity_families'])

    def test_ineligible_state_retains_positive_diagnostic(self):
        from app.models.core import MarketState
        p,m,obs,ctx,_=self.data
        obs=[replace(o,quote=replace(o.quote,state=MarketState.SUSPENDED)) for o in obs]
        audit=detector_audit(p,m,obs,ctx,evaluation_time=NOW,fill_grouping='single_fill_per_leg')
        self.s.calculation(self.sid,'suspended',audit)
        row=self.db.execute('select state,conditional_positive,qualified from candidate_observation where session_id=%s and conditional_positive',(self.sid,)).fetchone()
        self.assertEqual(row['state'],'unavailable-or-ineligible'); self.assertFalse(row['qualified'])

    def test_calculation_audit_bound(self):
        sid=self.s.start('synthetic','synthetic','audit limit',CapturePolicy(max_audit_bytes=1))
        with self.assertRaises(ValueError): self.s.calculation(sid,'det',self.audit)
        self.assertIsNone(self.db.execute('select 1 from calculation where session_id=%s',(sid,)).fetchone())

    def test_metadata_versions_append_without_rewrite(self):
        self.s.metadata(self.sid,'rule-profile','market',{'version':'one','settlement':'UNKNOWN'})
        self.s.metadata(self.sid,'rule-profile','market',{'version':'two','settlement':'UNKNOWN'})
        self.s.metadata(self.sid,'rule-profile','market',{'version':'one','settlement':'UNKNOWN'})
        rows=self.db.execute('select hash from metadata_version where session_id=%s',(self.sid,)).fetchall()
        self.assertEqual({self.s.get(r['hash'])['version'] for r in rows},{'one','two'})

    def test_submicrosecond_clock_regression(self):
        self.p['received_at']='2026-09-12T02:00:00.123456789Z'
        self.s.receipt(self.sid,'one',self.p)
        self.p['received_at']='2026-09-12T02:00:00.123456788Z'
        self.s.receipt(self.sid,'two',self.p)
        self.assertTrue(self.db.execute("select changed from receipt where session_id=%s and id='two'",(self.sid,)).fetchone()['changed'])
        self.assertIsNotNone(self.db.execute("select 1 from coverage_event where session_id=%s and kind='gap'",(self.sid,)).fetchone())

    def test_numeric_float_rejected(self):
        self.p['normalized']['quotes'][0]['ask']=0.2
        with self.assertRaises(ValueError): self.s.receipt(self.sid,'one',self.p)


    def test_representative_indexes(self):
        self.db.execute('SET LOCAL enable_seqscan=off')
        queries=[('select * from receipt where session_id=%s and venue=%s and market_id=%s order by received_at',(self.sid,'kalshi','contract'),'receipt_market_time'),
            ('select * from candidate_observation where session_id=%s and candidate_id=%s and engine=%s order by observed_at',(self.sid,'c','depth-1'),'candidate_history'),
            ('select * from coverage_event where session_id=%s order by observed_at',(self.sid,),'coverage_time')]
        for q,params,index in queries:
            plan=str(self.db.execute('EXPLAIN '+q,params).fetchall())
            self.assertIn(index,plan)


if __name__=='__main__': unittest.main(verbosity=2)
