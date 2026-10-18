"""Selected dependency equivalence and live HTTP cancellation on disposable SQL."""
import asyncio
from copy import deepcopy
from datetime import timedelta
from threading import Event
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from psycopg.types.json import Jsonb

from app.collection.runtime_client import RuntimeClient
from app.storage import latest_board as latest
from app.storage.comparison_board import ReadContext
from tests import test_latest_board_sql as sql_fixtures


@skipUnless(sql_fixtures.SOCKET,'Explicit disposable PostgreSQL lane required')
class SelectedInputGuardsSQL(IsolatedAsyncioTestCase):
    connect=classmethod(sql_fixtures.LatestBoardSQL.connect.__func__)
    setUpClass=classmethod(sql_fixtures.LatestBoardSQL.setUpClass.__func__)
    tearDownClass=classmethod(sql_fixtures.LatestBoardSQL.tearDownClass.__func__)
    asyncSetUp=sql_fixtures.LatestBoardSQL.asyncSetUp
    admit=sql_fixtures.LatestBoardSQL.admit
    reconcile=sql_fixtures.LatestBoardSQL.reconcile
    rows=sql_fixtures.LatestBoardSQL.rows

    async def setup_api(self):
        from app.dashboard.comparison_board_api import mount, READ_WORK
        self.reconcile()
        for target in ('app.dashboard.comparison_board_api.connect','app.storage.latest_board.connect'):
            change=patch(target,side_effect=self.connect);change.start();self.addCleanup(change.stop)
        app=web.Application();mount(app,RuntimeClient(connector=self.connect))
        client=TestClient(TestServer(app,handler_cancellation=True))
        await client.start_server();self.addAsyncCleanup(client.close)
        rows=self.rows();self.key=self.first['game_key'];self.saved=rows[self.key]['facts']['publication_dependencies']
        with self.connect() as db:
            b=latest.board(latest.snapshot(db,at=self.at.isoformat()),self.key,view='odds',filter='all')
        q=b['prices'][0]
        self.query=dict(game=self.key,quote=q['quote_id'],context_id=q['inputs_identity']['context_id'])
        return client,app[READ_WORK],q

    async def wait_entered(self, event):
        for _ in range(400):
            if event.is_set():return
            await asyncio.sleep(.005)
        self.fail('selected worker did not enter bounded capture')

    async def test_schedule_changes_invalidate_only_the_selected_neighborhood(self):
        from app.storage.current_rows import CurrentRowStore
        from tests.test_schedule_metadata import evidence
        client,_,q=await self.setup_api()
        reply=await client.get('/api/boards/inputs',params=self.query)
        frozen=await reply.json();self.assertEqual(reply.status,200,frozen)
        original=deepcopy(frozen)
        with self.connect() as db:
            before,ids=latest.selected_dependencies(db,self.saved)
            rows=CurrentRowStore(db).capture()['records']
            unrelated=next(r for r in rows if latest.hashed([r['quote']['source']['provider'],r['quote']['source']['native_event_id']]) not in ids)
            relevant=next(r for r in rows if latest.hashed([r['quote']['source']['provider'],r['quote']['source']['native_event_id']]) in ids)
            def revise(row):
                row=deepcopy(row)
                start=(latest.stamp(row['event']['scheduled_start'])+timedelta(minutes=8)).isoformat()
                row['event']=evidence(dict(row['event'],scheduled_start=start),self.at.isoformat())
                row['market_identity']['scheduled_start']=start
                CurrentRowStore(db).upsert_records([row],now=self.at.isoformat())
            revise(unrelated)
            self.assertEqual(before,latest.selected_dependencies(db,self.saved)[0])
        reply=await client.get('/api/boards/inputs',params=self.query)
        self.assertEqual(reply.status,200,await reply.json())
        with self.connect() as db:revise(relevant)
        reply=await client.get('/api/boards/inputs',params=self.query)
        self.assertEqual(reply.status,409,await reply.json())
        self.assertEqual(frozen,original)
        self.assertEqual(frozen['evidence']['original'],q['original'])
        self.assertEqual(frozen['evidence']['times'],q['times'])

    async def test_complete_neighborhood_rejects_relevant_changes_only(self):
        client,_,q=await self.setup_api()
        real=ReadContext.observation_bundles
        with self.connect() as db:
            before,ids=latest.selected_dependencies(db,self.saved)
            from app.storage import observation_publication as publication
            states=latest.source_states({},latest.runtime(db))
            full=publication.capture(db,states)
            narrow=publication.capture(db,states,selector=self.saved['selector'])
            self.assertEqual(publication.neighborhood(full,self.saved['selector']),publication.neighborhood(narrow,self.saved['selector']))
            self.assertEqual(publication.reasons(full,self.saved),publication.reasons(narrow,self.saved))
            self.assertEqual({cid:publication.own(full,cid) for cid in narrow['offers']},
                {cid:publication.own(narrow,cid) for cid in narrow['offers']})
            self.assertLess(len(narrow['offers']),len(full['offers']))
            all_events=db.execute('SELECT id FROM current_event').fetchall()
            unrelated=next(row['id'] for row in all_events if row['id'] not in ids)
            db.execute("UPDATE current_offer SET revision=revision||'-unrelated' WHERE contract_id IN (SELECT id FROM current_contract WHERE event_id=%s)",(unrelated,))
            self.assertEqual(before,latest.selected_dependencies(db,self.saved)[0])
        reply=await client.get('/api/boards/inputs',params=self.query)
        value=await reply.json();self.assertEqual(reply.status,200,value)
        self.assertEqual(value['evidence']['original'],q['original'])
        self.assertEqual(value['evidence']['times'],q['times'])

        # Change surrounding context after exact selected capture, even though
        # the selected original quote is untouched. Every change must revoke.
        cases=('other_contract','new_contract','benchmark_offer','book','source','stop','reset','runtime','control')
        for case in cases:
            with self.subTest(case=case):
                entered=Event();release=Event()
                def held(context,**kwargs):
                    result=real(context,**kwargs);entered.set();release.wait(3);return result
                with patch.object(ReadContext,'observation_bundles',held):
                    task=asyncio.create_task(client.get('/api/boards/inputs',params=self.query))
                    await self.wait_entered(entered)
                    with self.connect() as db:
                        # Keep the mutation committed only while verification runs;
                        # restore these explicitly disposable rows afterward.
                        if case in ('other_contract','benchmark_offer'):
                            rows=db.execute('SELECT c.id,c.revision,o.revision AS offer_revision,c.venue FROM current_contract c JOIN current_offer o ON o.contract_id=c.id WHERE c.event_id=ANY(%s)',(ids,)).fetchall()
                            from app.storage.current_rows import contract_id
                            cid=contract_id(dict(quote=q))
                            selected=next((r for r in rows if r['venue']=='pinnacle'),rows[-1]) if case=='benchmark_offer' else next(r for r in rows if r['id']!=cid)
                            if case=='other_contract':
                                db.execute("UPDATE current_contract SET revision=revision||'-context' WHERE id=%s",(selected['id'],))
                            else:db.execute("UPDATE current_offer SET revision=revision||'-benchmark' WHERE contract_id=%s",(selected['id'],))
                            restore=lambda:db.execute('UPDATE '+('current_contract' if case=='other_contract' else 'current_offer')+' SET revision=%s WHERE '+('id' if case=='other_contract' else 'contract_id')+'=%s',(selected['revision'] if case=='other_contract' else selected['offer_revision'],selected['id']))
                        elif case=='new_contract':
                            cid='authored-extra-'+uuid4().hex
                            db.execute('''INSERT INTO current_contract SELECT %s,event_id,venue,native_market_id||'-extra',native_outcome_id,native_side,facts,revision
                                FROM current_contract WHERE event_id=ANY(%s) LIMIT 1''',(cid,ids))
                            db.execute('''INSERT INTO current_offer SELECT %s,o.price_value,o.price_units,o.quantity_units,o.source_at,o.source_order,o.received_at,o.received_order,o.facts,o.revision
                                FROM current_offer o JOIN current_contract c ON c.id=o.contract_id WHERE c.event_id=ANY(%s) LIMIT 1''',(cid,ids))
                            restore=lambda:db.execute('DELETE FROM current_contract WHERE id=%s',(cid,))
                        elif case=='book':
                            book=db.execute('SELECT * FROM current_native_book WHERE event_id=ANY(%s) LIMIT 1',(ids,)).fetchone()
                            db.execute("UPDATE current_native_book SET revision=revision||'-book' WHERE venue=%s AND event_id=%s AND native_market_id=%s",(book['venue'],book['event_id'],book['native_market_id']))
                            restore=lambda:db.execute('UPDATE current_native_book SET revision=%s WHERE venue=%s AND event_id=%s AND native_market_id=%s',(book['revision'],book['venue'],book['event_id'],book['native_market_id']))
                        elif case=='source':
                            venue=q['venue'];old=self.service.states[venue]
                            self.service.states[venue]=dict(state='unavailable');self.state.write(self.service)
                            def restore():
                                self.service.states[venue]=old;self.state.write(self.service)
                        elif case=='reset':
                            old=db.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch']
                            db.execute('UPDATE current_row_epoch SET epoch=%s',(str(uuid4()),))
                            restore=lambda:db.execute('UPDATE current_row_epoch SET epoch=%s',(old,))
                        elif case=='control':
                            command=str(uuid4())
                            db.execute('''INSERT INTO data_runtime_command(id,runtime_id,action,body,expires_at,state)
                                SELECT %s,runtime_id,'stop','{}',clock_timestamp()+interval '1 minute','acknowledged' FROM data_runtime''',(command,))
                            restore=lambda:db.execute('DELETE FROM data_runtime_command WHERE id=%s',(command,))
                        else:
                            column='global_stopped' if case=='stop' else 'runtime_id'
                            old=db.execute('SELECT '+column+' FROM data_runtime').fetchone()[column]
                            db.execute('UPDATE data_runtime SET '+column+'=%s',(True if case=='stop' else str(uuid4()),))
                            restore=lambda:db.execute('UPDATE data_runtime SET '+column+'=%s',(old,))
                        release.set();reply=await task;value=await reply.json()
                        restore()
                    self.assertEqual(reply.status,409,value)
                    self.assertEqual(value['provider_requests'],0)

    async def test_http_abort_and_reopen_keep_live_capacity_and_ordinary_reader(self):
        client,work,q=await self.setup_api()
        entered=Event();release=Event();real=ReadContext.observation_bundles
        def held(context,**kwargs):
            result=real(context,**kwargs);entered.set();release.wait(3);return result
        with patch.object(ReadContext,'observation_bundles',held):
            task=asyncio.create_task(client.get('/api/boards/inputs',params=self.query))
            await self.wait_entered(entered);task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            await asyncio.sleep(.05)
            self.assertEqual(len(work.running),1)
            self.assertEqual(work.pending['selected'],1)
            reply=await client.get('/api/boards/slate?view=odds&filter=all&limit=50')
            self.assertEqual(reply.status,200,await reply.json())
            release.set()
        for _ in range(200):
            if not work.running:break
            await asyncio.sleep(.005)
        self.assertEqual(len(work.running),0)
        reply=await client.get('/api/boards/inputs',params=self.query)
        value=await reply.json();self.assertEqual(reply.status,200,value)
        self.assertEqual(value['evidence']['original'],q['original'])
        self.assertEqual(value['evidence']['times'],q['times'])
        self.assertEqual(sum(work.pending.values()),0)

    async def test_invalid_schedule_does_not_starve_other_occurrence_publication(self):
        client,_,_=await self.setup_api()
        prior=self.rows();bad=prior[self.first['game_key']]
        with self.connect() as db:
            _,ids=latest.selected_dependencies(db,bad['facts']['publication_dependencies'])
            row=db.execute('SELECT id,facts FROM current_contract WHERE event_id=ANY(%s) LIMIT 1',(ids,)).fetchone()
            facts=deepcopy(row['facts'])
            facts['market_identity']['scheduled_start']=(latest.stamp(facts['market_identity']['scheduled_start'])+timedelta(minutes=1)).isoformat()
            db.execute("UPDATE current_contract SET facts=%s,revision=revision||'-conflict' WHERE id=%s",(Jsonb(facts),row['id']))
            # Model the installed old source binding without changing any raw
            # owner input or permitting an old frame to acquire a new identity.
            db.execute("UPDATE latest_board SET facts=jsonb_set(facts,'{observation_binding}','\"authored-old-binding\"')")
            raw_marker=latest.marker(db)
            stale_bad=db.execute('SELECT * FROM latest_board WHERE game_key=%s',(self.first['game_key'],)).fetchone()
            # The retained two-game finance fixture can canonically align a
            # schedule. Inject the actual installed validator failure at the
            # occurrence boundary, independently of that fixture's matcher.
            from app.dashboard.current_normalized import catalog_from_normalized
            members=set(map(tuple,self.first['members']))
            def conflict(raw,records,**kwargs):
                if any((r['quote']['source']['provider'],r['quote']['source']['native_event_id']) in members for r in records):
                    raise ValueError('Normalized schedule conflict')
                return catalog_from_normalized(raw,records,**kwargs)
            with patch('app.dashboard.current_normalized.catalog_from_normalized',side_effect=conflict):
                result=latest.reconcile(db,at=self.at.isoformat())
            self.assertTrue(result['published'],result)
            self.assertEqual(latest.marker(db),raw_marker,'publication never guesses or edits a conflicting schedule')
            self.assertEqual(latest.hashed(db.execute('SELECT * FROM latest_board WHERE game_key=%s',(self.first['game_key'],)).fetchone()),latest.hashed(stale_bad))
            status=db.execute('SELECT facts FROM latest_board_status').fetchone()['facts']
            self.assertEqual(len(status['catalog_errors']),1)
            self.assertFalse(status['scope_complete'])
            frame=latest.snapshot(db,at=self.at.isoformat())
            good=latest.board(frame,self.second['game_key'],view='odds',filter='all')
            self.assertEqual(frame['rows'][self.second['game_key']]['facts']['observation_binding'],latest.observation_binding())
        quote=good['prices'][0]
        reply=await client.get('/api/boards/inputs',params=dict(game=good['game_key'],quote=quote['quote_id'],context_id=quote['inputs_identity']['context_id']))
        value=await reply.json();self.assertEqual(reply.status,200,value)
        self.assertEqual(value['evidence']['original'],quote['original'])
        self.assertEqual(value['evidence']['times'],quote['times'])
        reply=await client.get('/api/boards/inputs',params=self.query)
        self.assertEqual(reply.status,409,await reply.json())
