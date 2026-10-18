"""Authored retained-case equivalents in disposable PostgreSQL, zero providers."""
from copy import deepcopy
from datetime import timedelta
import json
from unittest import TestCase
from app.storage.current_rows import contract_id, CurrentRowStore
from app.storage.current_games import GameStore
from app.storage.comparison_board import ReadContext
from app.storage.store import hashed, stamp
from psycopg.types.json import Jsonb
from tests import test_d03_current_rows as fixtures
from tests.test_d03_current_rows import future_records
from tests.test_schedule_metadata import evidence


class ScheduleReconciliationSQL(TestCase):
    setUpClass=classmethod(fixtures.CurrentRows.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.CurrentRows.tearDownClass.__func__)
    setUp=fixtures.CurrentRows.setUp

    def authored(self):
        rows=future_records('kalshi')
        for row in rows:row['event']=evidence(row['event'])
        return rows

    def later(self,row,minutes=8,receipt='2026-10-17T13:00:00Z'):
        result=deepcopy(row)
        start=(stamp(row['event']['scheduled_start'])+timedelta(minutes=minutes)).isoformat()
        result['event']=evidence(dict(row['event'],scheduled_start=start),receipt)
        result['market_identity']['scheduled_start']=start
        return result

    def test_partial_revision_retains_raw_contract_and_all_prices_clocks_depth(self):
        rows=self.authored();self.store.upsert_records(rows)
        from tests.test_ev09_n01 import envelopes
        source=rows[0]['quote']['source']
        book=deepcopy(next(o['book'] for envelope in envelopes() if envelope['record']['kind']=='admitted_books'
            for o in envelope['record']['value']['observations']
            if o['book']['raw']['ref']['venue']=='kalshi' and o['book']['raw']['ref']['market_id']==source['native_market_id']))
        self.store.replace_native_books([book])
        before=self.store.capture();frozen=deepcopy(before)
        self.assertTrue(any(r['quote'].get('depth') for r in before['records']))
        prices=self.db.execute('SELECT * FROM current_offer ORDER BY contract_id').fetchall()
        changed=self.later(rows[0]);self.store.upsert_records([changed])
        after=self.store.capture()
        self.assertTrue(ReadContext(GameStore(self.db)).catalog()['games'])
        self.assertEqual(before,frozen)
        self.assertEqual({r['event']['scheduled_start'] for r in after['records']},{changed['event']['scheduled_start']})
        self.assertTrue(all(r['market_identity']['scheduled_start']==r['event']['scheduled_start'] for r in after['records']))
        raw=self.db.execute('SELECT facts FROM current_contract WHERE id=%s',(contract_id(rows[1]),)).fetchone()['facts']
        self.assertEqual(raw['market_identity']['scheduled_start'],rows[1]['market_identity']['scheduled_start'])
        self.assertIn('schedule_reconciliation',next(r for r in after['records'] if contract_id(r)==contract_id(rows[1]))['comparison_source_metadata'])
        saved=self.db.execute('SELECT * FROM current_offer ORDER BY contract_id').fetchall()
        for a,b in zip(prices,saved):
            for key in ('price_value','price_units','quantity_units','source_at','received_at','source_order','received_order','facts'):self.assertEqual(a[key],b[key],key)
        for a,b in zip(sorted(before['records'],key=contract_id),sorted(after['records'],key=contract_id)):
            self.assertEqual(a['quote'],b['quote'])
        # Later books carrying older discovery metadata cannot roll back schedule.
        old=deepcopy(rows[1]);old['quote']['times'].update(source_at='2026-10-17T14:00:00Z',received_at='2026-10-17T14:00:01Z')
        self.store.upsert_records([old])
        self.assertTrue(all(r['event']['scheduled_start']==changed['event']['scheduled_start'] for r in self.store.records()))

    def test_new_metadata_is_admitted_even_when_its_price_source_is_older(self):
        rows=self.authored();self.store.upsert_records(rows)
        before=self.db.execute('SELECT * FROM current_offer ORDER BY contract_id').fetchall()
        revised=self.later(rows[0]);revised['quote']['times']['source_at']='2026-10-14T12:00:00Z'
        revised['quote']['original']['value']='0.123'
        self.store.upsert_records([revised])
        self.assertEqual(before,self.db.execute('SELECT * FROM current_offer ORDER BY contract_id').fetchall())
        self.assertTrue(all(r['market_identity']['scheduled_start']==revised['event']['scheduled_start'] for r in self.store.records()))

    def test_legacy_split_is_unresolved_and_invalid_group_is_isolated(self):
        rows=self.authored()
        for row in rows:row['event'].pop('schedule_metadata')
        self.store.upsert_records(rows)
        # Exact old implementation boundary: shared replacement, older contract.
        new=self.later(rows[0]);event=dict(new['event']);event.pop('schedule_metadata')
        self.db.execute('UPDATE current_event SET facts=%s,scheduled_start=%s,revision=%s',
            (Jsonb(event),event['scheduled_start'],hashed(event)))
        valid=deepcopy(rows)
        for row in valid:
            native='authored-independent-occurrence'
            row['event'].update(id=native,season=None,stage=None,observed_identity_facts=[],shared_provider_ids={})
            for key in ('game_id','original_start','game_number','replacement_game_id'):row['event'].pop(key,None)
            row['quote']['source']['native_event_id']=native
            row['verified']=False
            row['market_identity'].update(season=None,stage=None)
            row['comparison_source_metadata']['comparison_admission']=dict(supported=False,reason='comparison_context_missing',missing_fields=['season','stage'])
        self.store.upsert_records(valid)
        context=ReadContext(GameStore(self.db),tolerate_invalid_catalog=True)
        self.assertTrue(context.catalog()['games'])
        self.assertEqual(context.catalog_errors[0]['reason'],'schedule_binding_unverified')
        self.assertTrue(context.catalog_errors[0]['schedule_conflicts'])
        with self.assertRaisesRegex(ValueError,'schedule conflict'):ReadContext(GameStore(self.db)).catalog()

    def test_contradictory_equal_metadata_witness_remains_unavailable(self):
        rows=self.authored();self.store.upsert_records(rows)
        conflicting=self.later(rows[0],receipt='2026-10-17T12:00:00Z')
        self.store.upsert_records([conflicting])
        context=ReadContext(GameStore(self.db),tolerate_invalid_catalog=True)
        self.assertEqual(context.catalog()['games'],[])
        self.assertEqual(context.catalog_errors[0]['reason'],'schedule_equal_metadata_conflict')

    def test_expired_rows_cannot_be_extended_by_metadata_with_old_prices(self):
        rows=self.authored();self.store.upsert_records(rows)
        start=stamp(rows[0]['event']['scheduled_start'])
        changed=self.later(rows[0],minutes=60)
        self.store.upsert_records([changed],now=(start+timedelta(minutes=1)).isoformat())
        self.assertEqual(self.db.execute('SELECT count(*) n FROM current_event').fetchone()['n'],0)
        self.assertEqual(self.db.execute('SELECT count(*) n FROM current_offer').fetchone()['n'],0)
        self.assertEqual(CurrentRowStore(self.db).capture()['records'],[])

    def snapshot(self):
        return json.loads(json.dumps(dict(observed_at='2026-10-17T12:30:00Z',
            current_event=self.db.execute('SELECT * FROM current_event ORDER BY id').fetchall(),
            current_contract=self.db.execute('SELECT * FROM current_contract ORDER BY id').fetchall()),default=str))

    def legacy(self):
        rows=self.authored()
        for row in rows:
            row['event'].pop('schedule_metadata')
            row['event']['observed_identity_facts']=[dict(id='authored-milestone',start_date=row['event']['scheduled_start'])]
        self.store.upsert_records(rows)
        return rows

    def test_exact_retained_snapshot_recovers_lost_binding_without_rewriting_originals(self):
        rows=self.legacy();snapshot=self.snapshot()
        revised=self.later(rows[0]);self.store.upsert_records([revised])
        prices=self.db.execute('SELECT * FROM current_offer ORDER BY contract_id').fetchall()
        before=self.store.capture();frozen=deepcopy(before)
        kwargs=dict(path='authored-retained-capture.json',snapshot_sha256=hashed(snapshot))
        changed=self.store.restore_schedule_bindings(snapshot,**kwargs)
        self.assertEqual(changed,[contract_id(rows[1])])
        self.assertEqual(prices,self.db.execute('SELECT * FROM current_offer ORDER BY contract_id').fetchall())
        self.assertEqual(before,frozen)
        current=self.store.capture()['records']
        self.assertTrue(all(r['market_identity']['scheduled_start']==r['event']['scheduled_start'] for r in current))
        self.assertTrue(ReadContext(GameStore(self.db)).catalog()['games'])
        support=next(r for r in current if contract_id(r)==changed[0])['comparison_source_metadata']['schedule_binding']
        self.assertIsNone(support['metadata']['received_at'])
        self.assertEqual(support['metadata']['observed_no_later_than'],snapshot['observed_at'])
        raw=self.db.execute('SELECT facts FROM current_contract WHERE id=%s',(changed[0],)).fetchone()['facts']
        original=next(r['facts'] for r in snapshot['current_contract'] if r['id']==changed[0])
        raw['comparison_source_metadata'].pop('schedule_binding')
        self.assertEqual(raw,original)
        self.assertEqual(self.store.restore_schedule_bindings(snapshot,**kwargs),[])

    def test_retained_binding_requires_exact_contract_prior_witness_and_later_authority(self):
        rows=self.legacy();snapshot=self.snapshot()
        self.store.upsert_records([self.later(rows[0])])
        kwargs=dict(path='authored-capture.json',snapshot_sha256=hashed(snapshot))
        for variant in ('contract_changed','source_witness_changed','capture_not_earlier'):
            bad=deepcopy(snapshot)
            if variant=='capture_not_earlier':bad['observed_at']='2026-10-17T14:00:00Z'
            elif variant=='contract_changed':
                for c in bad['current_contract']:
                    c['facts']['selection']['label']='different retained selection';c['revision']=hashed(c['facts'])
            else:
                for e in bad['current_event']:
                    e['facts']['observed_identity_facts'][0]['id']='different-native-occurrence';e['revision']=hashed(e['facts'])
            with self.subTest(variant=variant):self.assertEqual(self.store.restore_schedule_bindings(bad,**kwargs),[])
