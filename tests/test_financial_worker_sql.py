"""Normal financial owner in its bounded process, on disposable source facts."""
import asyncio
import sys
import json
import tempfile
from pathlib import Path
from datetime import timedelta,timezone
from unittest import skipUnless
from unittest.mock import patch
from app.collection.coverage_worker import run,MAX_PROCESS_BYTES,resume_arguments
from app.storage import store
from tests.latest_board_fixture import LatestBoardFixture,SOCKET,inline_fixture_offers

@skipUnless(SOCKET,'Explicit disposable PostgreSQL lane required')
class FinancialWorkerSQL(LatestBoardFixture):
    def test_restart_resumes_committed_component_and_keeps_existing_cursor(self):
        self.reconcile()
        with self.connect() as db:
            rows=db.execute('SELECT game_key,publication_events FROM latest_board ORDER BY game_key').fetchall()
            selected=rows[-1]
            db.execute('UPDATE latest_board SET calculated_at=%s WHERE game_key=%s',
                ((self.at+timedelta(minutes=1)).astimezone(timezone(timedelta(hours=-4))).isoformat(),selected['game_key']))
            before=db.execute('SELECT game_key,calculated_at FROM latest_board ORDER BY game_key').fetchall()
        with patch('app.storage.store.connect',side_effect=self.connect):
            restored=resume_arguments('app.collection.financial_worker',('{}',))
        self.assertEqual(json.loads(restored[0]),dict(estimates_after=min(selected['publication_events']),estimates_rotation_after=min(selected['publication_events'])))
        with patch('app.storage.store.connect',side_effect=AssertionError('existing cursor must not be replaced')):
            self.assertEqual(resume_arguments('app.collection.financial_worker',restored),restored)
        with self.connect() as db:
            self.assertEqual(before,db.execute('SELECT game_key,calculated_at FROM latest_board ORDER BY game_key').fetchall())

    def test_metric_identity_ignores_receipt_provenance_but_keeps_semantics(self):
        from app.storage import observation_publication as publication
        with self.connect(self.name) as db,db.transaction():
            before=publication.capture(db,{})
            cid=next(iter(before['offers']))
            original=publication.metric_identity(before,cid)
            db.execute("UPDATE current_contract SET facts=facts || '{\"orientation_evidence\":{\"receipt\":\"new\"}}'::jsonb WHERE id=%s",(cid,))
            repeated=publication.capture(db,{})
            self.assertEqual(original,publication.metric_identity(repeated,cid))
            self.assertNotEqual(before['offers'][cid]['contract_dependency'],repeated['offers'][cid]['contract_dependency'])
            db.execute("UPDATE current_contract SET facts=jsonb_set(facts,'{verified}','false'::jsonb) WHERE id=%s",(cid,))
            changed=publication.capture(db,{},compact=True)
            self.assertNotEqual(original,publication.metric_identity(changed,cid))

    async def test_disposable_financial_owner_publishes_normal_results(self):
        # The fixture owns a named disposable database and frozen source clock.
        # Install those test-only boundaries inside the child, then run its real
        # entrypoint and normal reconciliation/publication implementation.
        from app.storage import latest_board as latest,result_inventory,observation_publication,result_dependencies
        from app.storage.comparison_board import discover
        from app.collection.background_work import BACKGROUND,AcquisitionDeferred
        # Discover real pending closures before parent admission. A source
        # pressure refusal and a stopped turn cannot consume their positions.
        with self.connect() as db:
            context=latest.read_context(db,at=self.at.isoformat())
            frame=observation_publication.capture(db,context.source_status)
            bundles=discover(context.store,context=context)
            retained_parent=max(bundles,key=lambda b:len(result_dependencies.partitions(b)))
            for bundle in sorted(bundles,key=lambda b:b is not retained_parent):
                selector=observation_publication.manifest(frame,bundle)['selector']
                proof=result_inventory.proof(frame,selector,engine=context.engine,
                    policy=latest.load().revision,owner=latest.runtime_identity(latest.runtime(db)))
                if bundle is retained_parent:
                    from copy import deepcopy
                    unknown=deepcopy(proof);unknown['selector']['events'].append('unobserved-member')
                    result_inventory.record(db,dict(bundle,game_key='retained-unselectable-occurrence'),
                        [dict(id='pending-retained-unit',groups=['unknown'])],unknown)
                    db.execute("UPDATE current_result_work SET refresh_order=nextval('current_result_refresh_order'),refresh_visit_order=visit_order WHERE unit_id='pending-retained-unit'")
                result_inventory.record(db,bundle,result_dependencies.partitions(bundle),proof)
            pending=db.execute('SELECT game_key,unit_id,visit_order,visits FROM current_result_work ORDER BY visit_order').fetchall()
        self.assertTrue(pending);self.assertTrue(all(r['visits']==0 for r in pending))
        with patch.object(BACKGROUND,'acquisition_pressure',return_value=True), \
                patch('app.collection.coverage_worker.asyncio.create_subprocess_exec',side_effect=AssertionError('deferred parent launched a worker')):
            with self.assertRaises(AcquisitionDeferred):
                await run(lambda:False,root=store.ROOT,module='app.collection.financial_worker',arguments=('{}',))
        stopped=await run(lambda:True,root=store.ROOT,module='app.collection.financial_worker',arguments=('{}',))
        self.assertEqual(stopped['reason'],'updates_stopped')
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT game_key,unit_id,visit_order,visits FROM current_result_work ORDER BY visit_order').fetchall(),pending)
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        transfer=Path(temporary.name)/'discovery.json'
        launch=asyncio.create_subprocess_exec
        code=f'''import sys
from pathlib import Path
from datetime import datetime
from app.storage import store
store.ROOT=Path(sys.argv[1]);original=store.connect
store.connect=lambda:original({self.name!r})
from app.collection import runtime_status
runtime_status.clock=lambda:datetime.fromisoformat({self.at.isoformat()!r})
from app.storage import latest_board,comparison_board,current_rows,result_publication
latest_board.utc=lambda:{self.at.isoformat()!r}
comparison_board.utc=latest_board.utc
current_rows.utc=latest_board.utc
result_publication.utc=latest_board.utc
from app.storage import discovery_index
traces=[];original_prepare=discovery_index.prepare;original_reconcile=latest_board.reconcile
def prepare(*args,**kwargs):
    value=original_prepare(*args,**kwargs)
    traces.append(value['_discovery_timings']['discovery_miss_reason'])
    return value
def reconcile(*args,**kwargs):
    value=original_reconcile(*args,**kwargs);value['test_discovery']=traces
    return value
discovery_index.prepare=prepare;latest_board.reconcile=reconcile
from app.collection import financial_worker
financial_worker.discovery_transfer_path=lambda root:Path({str(transfer)!r})
financial_worker.main()
'''
        async def start(*args,**kwargs):
            return await launch(sys.executable,'-c',code,*args[3:],**kwargs)
        progress={}
        with patch('app.collection.coverage_worker.asyncio.create_subprocess_exec',side_effect=start), \
             patch('app.storage.store.connect',side_effect=self.connect):
            result=await run(lambda:False,root=store.ROOT,module='app.collection.financial_worker',arguments=('{}',),on_progress=progress.update)
        self.assertTrue(result['published'],result)
        self.assertGreater(result['computed'],0,result)
        self.assertGreater(result['no_progress_parent_yields'],0,result)
        self.assertEqual(result['provider_requests'],0)
        self.assertLess(result['worker_peak_rss_bytes'],MAX_PROCESS_BYTES)
        self.assertTrue(self.rows())
        with self.connect() as db:
            oldest=next(r for r in pending if r['unit_id']!='pending-retained-unit')
            visit=db.execute('SELECT visits FROM current_result_work WHERE game_key=%s AND unit_id=%s',
                (oldest['game_key'],oldest['unit_id'])).fetchone()
            self.assertGreater(visit['visits'],0)
            retained=db.execute("SELECT visit_order,visits,active FROM current_result_work WHERE unit_id='pending-retained-unit'").fetchone()
            self.assertEqual(retained,dict(visit_order=pending[0]['visit_order'],visits=0,active=True))
        self.assertIn('estimates_after',result['worker_admission'])
        self.assertEqual(progress['estimates_after'],result['worker_admission']['estimates_after'])

        from app.storage import latest_board as latest
        with self.connect() as db:
            before={(r['game_key'],r['unit_id']):r['generation_id'] for r in db.execute('SELECT game_key,unit_id,generation_id FROM current_result_unit')}
            first_current=set()
            for game in {k[0] for k in before}:
                board=latest.board(latest.snapshot(db,game=game,at=self.at.isoformat()),game,view='ev',filter='all')
                first_current.update((game,u['unit_id']) for u in board.get('result_units',[]) if u['state']=='current')
        self.assertTrue(first_current)

        # A second actual process consumes the first process's structural plans.
        # Change a required executable input so ordinary reuse cannot skip work.
        old_at=self.at.isoformat()
        self.at+=timedelta(seconds=1);self.state.write(self.service)
        code=code.replace(old_at,self.at.isoformat())
        with self.connect() as db:
            cid=db.execute("SELECT o.contract_id FROM current_offer o JOIN current_contract c ON c.id=o.contract_id WHERE c.venue='kalshi' ORDER BY o.contract_id LIMIT 1").fetchone()['contract_id']
            inline_fixture_offers(db,[cid])
            changed_cid=db.execute("UPDATE current_offer SET price_value='0.37',revision=revision||'-repeat',received_at=%s WHERE contract_id=%s RETURNING contract_id",(self.at.isoformat(),cid)).fetchone()['contract_id']
        with patch('app.collection.coverage_worker.asyncio.create_subprocess_exec',side_effect=start), \
             patch('app.storage.store.connect',side_effect=self.connect):
            repeated=await run(lambda:False,root=store.ROOT,module='app.collection.financial_worker',arguments=('{}',),on_progress=progress.update)
        self.assertNotEqual(result['worker_pid'],repeated['worker_pid'])
        self.assertEqual(repeated['discovery_transfer'],'transferred')
        self.assertGreater(repeated['refresh_visits'],0,repeated)
        with self.connect() as db:
            stages=[r['facts'].get('unit_stage_timings',{}) for r in db.execute('SELECT facts FROM current_result_unit')]
        self.assertTrue(any(s.get('discovery_index_reused') for s in stages),stages)

        with self.connect() as db:
            after={(r['game_key'],r['unit_id']):r['generation_id'] for r in db.execute('SELECT game_key,unit_id,generation_id FROM current_result_unit')}
            changed={key for key in first_current if after.get(key)!=before[key]}
            self.assertTrue(changed)
            for game,unit in changed:
                board=latest.board(latest.snapshot(db,game=game,at=self.at.isoformat()),game,view='ev',filter='all')
                self.assertEqual(next(u['state'] for u in board['result_units'] if u['unit_id']==unit),'current')
        # A structural change and loss of the transfer each rebuild across a
        # fresh child launch; neither can borrow the preceding worker's cache.
        for cold in (False,True):
            old_at=self.at.isoformat()
            self.at+=timedelta(seconds=1);self.state.write(self.service)
            code=code.replace(old_at,self.at.isoformat())
            if cold:transfer.unlink()
            with self.connect() as db:
                if not cold:
                    db.execute("DELETE FROM current_offer WHERE contract_id=(SELECT o.contract_id FROM current_offer o JOIN current_contract c ON c.id=o.contract_id WHERE c.venue='pinnacle' LIMIT 1)")
                db.execute("UPDATE current_offer SET price_value=%s,revision=revision||'-changed' WHERE contract_id=%s",('0.41' if cold else '0.39',changed_cid))
            with patch('app.collection.coverage_worker.asyncio.create_subprocess_exec',side_effect=start), \
                 patch('app.storage.store.connect',side_effect=self.connect):
                rebuilt=await run(lambda:False,root=store.ROOT,module='app.collection.financial_worker',arguments=('{}',),on_progress=progress.update)
            self.assertTrue(rebuilt['published'],rebuilt)
            with self.connect() as db:
                reasons={r['facts'].get('unit_stage_timings',{}).get('discovery_miss_reason') for r in db.execute('SELECT facts FROM current_result_unit')}
            expected='cold_after_transfer_missing_or_invalid' if cold else 'dependency_invalidated'
            self.assertIn(expected,rebuilt['test_discovery'],dict(result=rebuilt,sealed_reasons=list(reasons)))
