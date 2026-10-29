"""Normal financial owner in its bounded process, on disposable source facts."""
import asyncio
import sys
import json
from datetime import timedelta,timezone
from unittest import skipUnless
from unittest.mock import patch
from app.collection.coverage_worker import run,MAX_PROCESS_BYTES,resume_arguments
from app.storage import store
from tests.latest_board_fixture import LatestBoardFixture,SOCKET

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
        self.assertEqual(json.loads(restored[0]),dict(estimates_after=min(selected['publication_events'])))
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
        launch=asyncio.create_subprocess_exec
        code=f'''import sys
from pathlib import Path
from datetime import datetime
from app.storage import store
store.ROOT=Path(sys.argv[1]);original=store.connect
store.connect=lambda:original({self.name!r})
from app.collection import runtime_status
runtime_status.clock=lambda:datetime.fromisoformat({self.at.isoformat()!r})
from app.storage import latest_board,comparison_board,current_rows
latest_board.utc=lambda:{self.at.isoformat()!r}
comparison_board.utc=latest_board.utc
current_rows.utc=latest_board.utc
from app.collection.financial_worker import main
main()
'''
        async def start(*args,**kwargs):
            return await launch(sys.executable,'-c',code,*args[3:],**kwargs)
        progress={}
        with patch('app.collection.coverage_worker.asyncio.create_subprocess_exec',side_effect=start), \
             patch('app.storage.store.connect',side_effect=self.connect):
            result=await run(lambda:False,root=store.ROOT,module='app.collection.financial_worker',arguments=('{}',),on_progress=progress.update)
        self.assertTrue(result['published'],result)
        self.assertGreater(result['computed'],0,result)
        self.assertEqual(result['provider_requests'],0)
        self.assertLess(result['worker_peak_rss_bytes'],MAX_PROCESS_BYTES)
        self.assertTrue(self.rows())
        self.assertIn('estimates_after',result['worker_admission'])
        self.assertEqual(progress['estimates_after'],result['worker_admission']['estimates_after'])
