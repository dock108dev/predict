"""Generated events after worker startup through real native admission and SQL.

Fake transport only; disposable PostgreSQL. No application event fixtures or
admission registries are changed. Each matrix cell uses new event identifiers.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.collection.current_policy import DEFAULT
from app.collection.current_service import CurrentService
from app.collection.current_native import NativeWorker
from app.collection.current_database import DatabaseIngressSink
from app.collection.runtime_status import RuntimeState
from app.collection.runtime_client import RuntimeClient
from app.dashboard.current_state import CurrentStore
from app.storage import latest_board as latest
from app.storage.current_rows import CurrentRowStore
from app.comparison.estimated_policy import DEFAULT_POLICY
from tests import test_latest_board_sql as sql_fixtures
from tests.multisport_fixtures import SPORTS, FAMILIES, source_case, fake_discovery, current_book


@skipUnless(sql_fixtures.SOCKET, 'Explicit disposable multi-sport PostgreSQL lane required')
class AutomaticMultisportSQL(IsolatedAsyncioTestCase):
    connect=classmethod(sql_fixtures.LatestBoardSQL.connect.__func__)
    setUpClass=classmethod(sql_fixtures.LatestBoardSQL.setUpClass.__func__)
    tearDownClass=classmethod(sql_fixtures.LatestBoardSQL.tearDownClass.__func__)

    async def asyncSetUp(self):
        self.directory=TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        with self.connect() as db:
            db.execute('TRUNCATE current_event CASCADE')
            db.execute('TRUNCATE data_runtime,data_runtime_command,latest_board,latest_board_status,current_source_status,current_refresh_scope')
        self.config=dict(deepcopy(DEFAULT),native_sports=list(SPORTS),native_families=list(FAMILIES),aggregate_enabled=False)
        for target,value in (('app.collection.runtime_client.load',self.config),
            ('app.storage.latest_board.load',DEFAULT_POLICY),('app.dashboard.comparison_board_api.load',DEFAULT_POLICY)):
            patched=patch(target,return_value=value);patched.start();self.addCleanup(patched.stop)
        self.service=CurrentService(self.config,directory=self.directory.name,database_mode=True)
        self.service.dispatch=True
        self.service.background_calculations=dict(board='running',observations='running')
        self.service.status=lambda:dict(issues=[],exclusions=[],database=dict(state='available'))
        self.store=CurrentStore(self.service);self.service.store=self.store
        self.service.sink=DatabaseIngressSink(self.store,self.config)
        self.state=RuntimeState(self.connect);self.state.write(self.service)
        async def heartbeat():
            while True:
                await asyncio.to_thread(self.state.write,self.service)
                await asyncio.sleep(1)
        task=asyncio.create_task(heartbeat())
        async def stop_heartbeat():
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        self.addAsyncCleanup(stop_heartbeat)
        for target in ('app.collection.current_database.connect','app.storage.latest_board.connect','app.dashboard.comparison_board_api.connect'):
            patched=patch(target,side_effect=self.connect);patched.start();self.addCleanup(patched.stop)
        self.owner=latest.LatestBoardOwner(self.service)
        await self.owner.start()
        self.addAsyncCleanup(self.owner.close)
        self.addAsyncCleanup(self.store.close)

    async def unseen_event_after_startup(self,league,family,*,flat_season=False):
        from app.dashboard.comparison_board_api import mount
        proxy=RuntimeClient(connector=self.connect)
        app=web.Application();mount(app,proxy)
        client=TestClient(TestServer(app));await client.start_server();self.addAsyncCleanup(client.close)
        cases=[]
        workers={venue:NativeWorker(self.service,venue) for venue in ('kalshi','polymarket_us')}
        for worker in workers.values():self.addAsyncCleanup(worker.close)
        calls={venue:fake_discovery(worker,cases) for venue,worker in workers.items()}
        for worker in workers.values():await worker.discover()
        with self.connect() as db:self.assertEqual(db.execute('SELECT count(*) n FROM current_event').fetchone()['n'],0)
        # IDs are generated only after discovery and the background owner start.
        # No application registry or fixture is edited for these occurrences.
        case=source_case(league,family,uuid4().hex[:10],clock=datetime.now(timezone.utc))
        if flat_season:
            # Explicit authored source facts, matching the newly observed native
            # shape. The peer declares the same year label; this is capability
            # evidence, not a claim that current US listings supply that field.
            detail=case['milestone']['details']
            detail.pop('season')
            detail.update(season_type='REG',season_year=2026)
            case['events']['polymarket_us']['season']='2026'
        cases[:]=[case]
        for venue,worker in workers.items():
            await worker.discover()
            self.assertTrue(worker.markets,(league,family,venue,worker.catalog.get('excluded_catalog')))
            native=current_book(case,venue,price='0.48' if venue=='kalshi' else '0.53')
            native['sequence']='1'
            try:self.service.book(venue,native)
            except ValueError:
                self.fail((league,family,venue,self.service.sink.error))
        self.state.write(self.service)
        expected={case['events']['kalshi']['event_ticker'],case['events']['polymarket_us']['id']}
        board=None
        for _ in range(80):
            with self.connect() as db:frame=latest.snapshot(db)
            game=next((g for g in frame['status'].get('games',[]) if expected <= {m[1] for m in g['members']}),None)
            if game:
                board=latest.board(frame,game['game_key'],view='odds',filter='all')
                if any(q.get('current_comparison',{}).get('available') for q in board['prices']):break
            await asyncio.sleep(.1)
        self.assertIsNotNone(board,(league,family,self.owner.observation_error,frame['status'].get('errors'),frame['status'].get('games')))
        paired=[q for q in board['prices'] if q.get('current_comparison',{}).get('available')]
        self.assertTrue(paired,(league,family,[(q.get('selection'),q.get('gross_comparison')) for q in board['prices']]))
        self.assertEqual(len(paired),2 if family=='moneyline' else 4)
        for row in paired:
            value=row['current_comparison']['exact']
            self.assertEqual(Fraction(int(value['numerator']),int(value['denominator'])),
                Fraction(5 if row['venue']=='kalshi' else -5))
        reply=await client.get('/api/boards/odds',params=dict(game=game['game_key'],filter='all'))
        self.assertEqual(reply.status,200,await reply.text())
        rendered=await reply.json();self.assertEqual(rendered['provider_requests'],0)
        self.assertTrue(all(q['event']['league']==league for q in rendered['prices']))
        self.assertTrue(all(q['market']['market']==('winner' if family=='moneyline' else family) for q in rendered['prices']))
        selected=next(q for q in rendered['prices'] if q.get('current_comparison',{}).get('available'))
        reply=await client.get('/api/boards/inputs',params=dict(game=game['game_key'],quote=selected['quote_id'],context_id=selected['inputs_identity']['context_id']))
        self.assertEqual(reply.status,200,await reply.text())
        frozen=await reply.json();self.assertEqual(frozen['evidence']['times'],selected['times'])
        with self.connect() as db:
            records=CurrentRowStore(db).capture()['records']
            own=[r for r in records if r['quote']['source']['native_event_id'] in expected]
            self.assertEqual(len(own),4)
        self.assertEqual(selected['event']['league'],league)
        self.assertTrue(all(calls.values()))
        self.assertFalse(self.service.workers.get('the_odds_api'))
        return dict(case=case,workers=workers,cases=cases,client=client,game=game,board=rendered)

    async def test_infeasible_same_id_line_change_quarantines_old_sql_observation(self):
        setup=await self.unseen_event_after_startup('NFL','total')
        case=setup['case'];workers=setup['workers'];client=setup['client']
        expected={case['events']['kalshi']['event_ticker'],case['events']['polymarket_us']['id']}
        native_id=case['markets']['kalshi']['ticker']

        def own_records():
            with self.connect() as db:
                return [r for r in CurrentRowStore(db).capture()['records']
                        if r['quote']['venue']=='kalshi' and r['quote']['source']['native_market_id']==native_id]

        async def published_when(predicate):
            for _ in range(100):
                self.state.write(self.service)
                with self.connect() as db:frame=latest.snapshot(db)
                game=next((g for g in frame['status'].get('games',[])
                           if expected<={m[1] for m in g['members']}),None)
                if game:
                    board=latest.board(frame,game['game_key'],view='odds',filter='all')
                    if predicate(board):return game,board
                await asyncio.sleep(.1)
            self.fail((self.owner.observation_error,frame['status'].get('errors'),frame['status'].get('games')))

        # Seed the real worker's owned complete images, rather than bypassing
        # its lifecycle through CurrentService.book.
        for venue,worker in workers.items():
            worker.metrics['connections']=1
            worker.lifecycle.begin_connection(1)
            worker.queue_book(current_book(case,venue,price='0.48' if venue=='kalshi' else '0.53'))
            worker.flush_books()
        before=own_records()
        self.assertEqual(len(before),2)
        frozen={r['quote']['source']['native_outcome_id']:dict(
            original=deepcopy(r['quote']['original']),
            wording=deepcopy(r['comparison_source_metadata']['original_wording']),
            predicate=deepcopy(r['comparison_source_metadata']['source_predicate']),
            times={k:r['quote']['times'][k] for k in ('source_at','received_at')}) for r in before}
        _,initial=await published_when(lambda board:any(q['current_comparison']['available'] for q in board['prices']))
        self.assertTrue(all(q['market']['line']=='45.5' for q in initial['prices']))

        changed=deepcopy(case['markets']['kalshi'])
        changed['floor_strike']='46.5'
        changed['yes_sub_title']='Over 46.5'
        changed['rules_primary']=changed['rules_primary'].replace('45.5','46.5')
        feasible=deepcopy(changed)
        changed['rules_primary']+=' Complete authored source wording.'*30000
        case['markets']['kalshi']=changed
        worker=workers['kalshi']
        await worker.discover()
        self.assertEqual(worker.metrics['catalog_projection']['state'],'retained_previous')
        self.assertIn(native_id,worker.material_quarantine)

        # A new complete image for the same native ID now belongs to changed
        # terms. It cannot be admitted against the retained 45.5 predicate.
        skipped=worker.metrics.get('quarantined_books_skipped',0)
        worker.queue_book(current_book(case,'kalshi',price='0.67'))
        worker.flush_books()
        self.assertGreater(worker.metrics['quarantined_books_skipped'],skipped)
        blocked=own_records()
        self.assertEqual(len(blocked),2)
        for record in blocked:
            quote=record['quote'];original=frozen[quote['source']['native_outcome_id']]
            self.assertEqual(quote['original'],original['original'])
            self.assertEqual(record['comparison_source_metadata']['original_wording'],original['wording'])
            self.assertEqual(record['comparison_source_metadata']['source_predicate'],original['predicate'])
            self.assertEqual({k:quote['times'][k] for k in ('source_at','received_at')},original['times'])
            self.assertEqual(record['market_identity']['line'],'45.5')
            admission=record['comparison_source_metadata']['comparison_admission']
            self.assertFalse(admission['supported'])
            self.assertEqual(admission['reason'],'native_material_changed_capacity')
        game,_=await published_when(lambda board:any(q['venue']=='kalshi' and
            q['same_outcome']['reason']=='native_material_changed_capacity' for q in board['prices']))
        reply=await client.get('/api/boards/odds',params=dict(game=game['game_key'],filter='all'))
        self.assertEqual(reply.status,200,await reply.text())
        quarantined=await reply.json()
        self.assertEqual(quarantined['provider_requests'],0)
        self.assertFalse(any(q['current_comparison']['available'] or q['gross_comparison']['available']
                             for q in quarantined['prices']))
        own_prices=[q for q in quarantined['prices'] if q['venue']=='kalshi']
        self.assertEqual(len(own_prices),2)
        for quote in own_prices:
            self.assertEqual(quote['market']['line'],'45.5')
            self.assertEqual(quote['original']['value'],'0.48')
            self.assertNotEqual(quote['observation_display']['state'],'current')
            self.assertFalse(quote['same_outcome']['supported'])
            self.assertEqual(quote['same_outcome']['reason'],'native_material_changed_capacity')
            source_side=quote['source']['native_outcome_id']
            self.assertEqual({k:quote['times'][k] for k in ('source_at','received_at')},frozen[source_side]['times'])
        selected=own_prices[0]
        reply=await client.get('/api/boards/inputs',params=dict(game=game['game_key'],quote=selected['quote_id'],
            context_id=selected['inputs_identity']['context_id']))
        self.assertEqual(reply.status,200,await reply.text())
        captured=(await reply.json())['evidence']
        original=frozen[selected['source']['native_outcome_id']]
        self.assertEqual(captured['original'],original['original'])
        self.assertEqual({k:captured['times'][k] for k in ('source_at','received_at')},original['times'])
        self.assertEqual(captured['native_contract']['wording'],original['wording'])
        self.assertEqual(captured['native_contract']['same_outcome']['reason'],'native_material_changed_capacity')

        # Recover only after a complete feasible new catalog and a fresh owned
        # image. The unchanged US 45.5 observations remain different outcomes.
        case['markets']['kalshi']=feasible
        await worker.discover()
        self.assertNotIn(native_id,worker.material_quarantine)
        worker.metrics['connections']=2
        worker.lifecycle.begin_connection(2)
        worker.queue_book(current_book(case,'kalshi',price='0.67'))
        worker.flush_books()
        recovered=own_records()
        self.assertEqual(len(recovered),2)
        for record in recovered:
            self.assertEqual(record['quote']['original']['value'],'0.67')
            self.assertEqual(record['market_identity']['line'],'46.5')
            self.assertNotEqual(record['quote']['times']['source_at'],frozen[record['quote']['source']['native_outcome_id']]['times']['source_at'])
            self.assertIsNot(record['comparison_source_metadata'].get('comparison_admission',{}).get('supported'),False)
        game,_=await published_when(lambda board:any(q['venue']=='kalshi' and q['market']['line']=='46.5'
            and q['original']['value']=='0.67' for q in board['prices']))
        reply=await client.get('/api/boards/odds',params=dict(game=game['game_key'],filter='all'))
        self.assertEqual(reply.status,200,await reply.text())
        recovered_board=await reply.json()
        self.assertEqual({q['market']['line'] for q in recovered_board['prices'] if q['venue']=='kalshi'},{'46.5'})
        self.assertEqual({q['market']['line'] for q in recovered_board['prices'] if q['venue']=='polymarket_us'},{'45.5'})
        self.assertFalse(any(q['current_comparison']['available'] or q['gross_comparison']['available']
                             for q in recovered_board['prices']))


def matrix_test(league,family,*,flat_season=False):
    async def test(self):
        await self.unseen_event_after_startup(league,family,flat_season=flat_season)
    return test


for league in SPORTS:
    for family in FAMILIES:
        setattr(AutomaticMultisportSQL,'test_unseen_'+league+'_'+family,matrix_test(league,family))
        setattr(AutomaticMultisportSQL,'test_flat_season_unseen_'+league+'_'+family,
                matrix_test(league,family,flat_season=True))
