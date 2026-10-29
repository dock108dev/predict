"""Alternate/featured replacements remain independently authoritative in SQL."""
from unittest import skipUnless
from app.collection.current_aggregate_admission import admit,admit_alternate
from app.storage.current_rows import CurrentRowStore
from tests.latest_board_fixture import LatestBoardFixture,SOCKET
from tests.test_sc09_product import alternate_fixture,AT
from tests.test_current_aggregate import body


@skipUnless(SOCKET,'Disposable PostgreSQL required')
class AlternateAdmissionSQL(LatestBoardFixture):
    async def test_route_replacement_does_not_erase_other_route(self):
        alt,_,errors=admit_alternate(alternate_fixture(),'MLB',AT)
        self.assertFalse(errors)
        featured=admit(body(books=('novig','pinnacle')),'MLB',AT)
        scope=dict(venue='novig',competition='MLB',received_at=AT)
        with self.connect() as db:
            store=CurrentRowStore(db)
            store.upsert_records(alt,now=AT)
            store.upsert_records(featured,now=AT,authoritative=True,scopes=[dict(scope,aggregate_route='featured')])
            count=lambda:db.execute("SELECT count(*) n FROM current_contract WHERE venue='novig' AND native_market_id LIKE 'alternate:%%'").fetchone()['n']
            self.assertEqual(count(),8)
            store.upsert_records([],now=AT,authoritative=True,scopes=[dict(scope,aggregate_route='alternate')])
            self.assertEqual(count(),0)
            self.assertEqual(db.execute("SELECT count(*) n FROM current_contract c JOIN current_event e ON e.id=c.event_id WHERE c.venue='novig' AND e.competition='MLB' AND c.native_market_id NOT LIKE 'alternate:%%'").fetchone()['n'],6)

    async def test_paid_alternate_receipt_retries_local_lock_and_preserves_stop(self):
        import asyncio
        from unittest.mock import patch
        from app.storage.current_rows import LOCK
        from app.collection.alternate_acquisition import save_response, _save_response
        from app.collection.current_quota import QuotaStop
        import json
        payload=alternate_fixture();eid=json.loads(payload)['id']
        response=dict(body=payload,received_at=AT)
        def connection():
            db=self.connect();db.execute("SET lock_timeout='30ms'");return db
        with self.connect() as blocker, patch('app.storage.store.connect',side_effect=connection), \
                patch('app.storage.current_rows.utc',return_value=AT), \
                patch('app.collection.alternate_acquisition._save_response',wraps=_save_response) as attempts:
            blocker.execute('SELECT pg_advisory_lock(%s)',(LOCK,))
            task=asyncio.create_task(asyncio.to_thread(save_response,'MLB',eid,response,'authored-cycle'))
            for _ in range(100):
                if attempts.call_count>1:break
                await asyncio.sleep(.02)
            self.assertGreater(attempts.call_count,1)
            blocker.execute('SELECT pg_advisory_unlock(%s)',(LOCK,))
            await asyncio.wait_for(task,5)
            with self.connect() as db:
                raw=db.execute('SELECT received_at,disposition FROM current_acquisition_alternate WHERE event_id=%s',(eid,)).fetchone()
                from app.storage.store import stamp
                self.assertEqual(raw['received_at'],stamp(AT))
                self.assertEqual(raw['disposition'],'admitted_exact_lines')
                db.execute('UPDATE data_runtime SET global_stopped=true')
            with self.assertRaisesRegex(QuotaStop,'owner_stopped'):
                await asyncio.to_thread(save_response,'MLB',eid,response,'authored-cycle')
