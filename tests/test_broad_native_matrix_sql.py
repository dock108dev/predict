"""One disposable PostgreSQL 16 matrix through ingress, publication and HTTP."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import MagicMock,patch
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer

from app.collection.current_policy import DEFAULT
from app.collection.runtime_client import RuntimeClient
from app.collection.runtime_status import RuntimeState
from app.comparison.capabilities import SPORTS,CORE_FAMILIES
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.storage.current_rows import CurrentRowStore
from app.storage import latest_board as latest
from tests import test_latest_board_sql as fixtures
from tests.broad_pipeline_fixtures import captured_core_matrix,captured_partial,partial_case


@skipUnless(fixtures.SOCKET,'Explicit maintained disposable PostgreSQL lane required')
class BroadNativeMatrixSQL(IsolatedAsyncioTestCase):
    connect=classmethod(fixtures.LatestBoardSQL.connect.__func__)
    setUpClass=classmethod(fixtures.LatestBoardSQL.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.LatestBoardSQL.tearDownClass.__func__)

    async def asyncSetUp(self):
        self.at=datetime.now(timezone.utc)
        self.config=dict(deepcopy(DEFAULT),native_sports=list(SPORTS),native_families=list(CORE_FAMILIES))
        for target in ('app.collection.runtime_client.load','app.storage.latest_board.load','app.dashboard.comparison_board_api.load'):
            change=patch(target,return_value=self.config if target.endswith('runtime_client.load') else DEFAULT_POLICY)
            change.start();self.addCleanup(change.stop)
        for target in ('app.collection.runtime_status.clock','app.storage.current_rows.utc','app.storage.latest_board.utc',
                       'app.storage.comparison_board.utc','app.dashboard.comparison_board_api.utc','app.storage.coverage_latest.utc'):
            change=patch(target,side_effect=(lambda:self.at) if target.endswith('.clock') else (lambda:self.at.isoformat()))
            change.start();self.addCleanup(change.stop)
        self.service=SimpleNamespace(runtime_id='authored-broad-'+uuid4().hex,config=self.config,
            states={v:dict(state='available') for v in ('kalshi','polymarket_us','novig','prophetx','pinnacle')},
            dispatch=True,background_calculations=dict(board='running'),
            status=lambda:dict(issues=[],exclusions=[],database=dict(state='available')))
        self.state=RuntimeState(self.connect)
        with self.connect() as db:
            db.execute('TRUNCATE current_event CASCADE')
            db.execute('TRUNCATE current_source_status,current_refresh_scope,data_runtime,data_runtime_command,latest_board,latest_board_status,coverage_latest')
        self.state.write(self.service)

    def admit(self,rows,books):
        with self.connect() as db:
            current=CurrentRowStore(db)
            current.upsert_records(rows,now=self.at.isoformat())
            current.replace_native_books(books)

    async def read_matrix(self,expected_cells,expected_prices):
        with self.connect() as db:
            result=latest.reconcile(db,at=self.at.isoformat(),observations_only=True)
            self.assertTrue(result['published'],result)
            self.assertFalse(result.get('errors'),result)
        from app.dashboard.comparison_board_api import mount
        from app.storage.coverage_latest import reconcile
        with self.connect() as db:self.assertTrue(reconcile(db,at=self.at.isoformat())['published'])
        provider=RuntimeClient(connector=self.connect)
        provider.acquire=MagicMock(side_effect=AssertionError('read dispatched provider'))
        app=web.Application();mount(app,provider)
        with patch('app.dashboard.comparison_board_api.connect',side_effect=self.connect),\
                patch('app.dashboard.scanner_api.connect',side_effect=self.connect):
            async with TestClient(TestServer(app)) as client:
                result=await client.get('/api/boards/slate',params=dict(view='odds',filter='all',limit='50'))
                self.assertEqual(result.status,200,await result.text());page=await result.json()
                self.assertEqual(page['provider_requests'],0)
                prices=[q for b in page['boards'] for q in b['prices']]
                self.assertEqual(len(prices),expected_prices)
                self.assertEqual({(g['league'],q['venue'],'moneyline' if q['market']['market']=='winner' else q['market']['market'],q['market']['period'])
                    for b in page['boards'] for g in page['games'] if b['game_key']==g['game_key'] for q in b['prices']},expected_cells)
                # Both ordinary filters and metrics read the same retained facts.
                for query in ({},{'league':'NBA'},{'period':'first_half'}):
                    result=await client.get('/api/coverage',params=query)
                    self.assertEqual(result.status,200,await result.text())
                    self.assertEqual((await result.json())['provider_requests'],0)
                selected=prices[0]
                result=await client.get('/api/boards/inputs',params=dict(game=page['boards'][0]['game_key'],
                    context_id=selected['inputs_identity']['context_id'],quote=selected['quote_id']))
                self.assertEqual(result.status,200,await result.text());original=await result.json()
                self.assertEqual(original['evidence']['original'],selected['original'])
                self.assertEqual(original['evidence']['times'],selected['times'])
        provider.acquire.assert_not_called()
        return prices

    async def test_all_six_leagues_both_native_sources_three_core_families_publish_together(self):
        rows,books=await captured_core_matrix(self.at);self.assertEqual(len(rows),72)
        self.admit(rows,books)
        expected={(s,v,f,'full_game') for s in SPORTS for v in ('kalshi','polymarket_us') for f in CORE_FAMILIES}
        await self.read_matrix(expected,72)

    async def test_all_changed_period_representations_publish_and_keep_original_ages(self):
        rows=[];books=[];expected=set()
        scopes=[(s,f,'first_half',v) for s in ('NFL','NCAAF','NBA','NCAAB')
            for f in CORE_FAMILIES for v in ('kalshi','polymarket_us')]
        scopes += [('MLB',f,p,'kalshi') for p,families in (('first_3',('moneyline',)),('first_5',CORE_FAMILIES)) for f in families]
        for sport,family,period,venue in scopes:
            case=partial_case(sport,family,period,'joint-partial-'+sport+'-'+family+'-'+period,clock=self.at)
            records,excluded,book,_=await captured_partial(case,venue)
            self.assertEqual(excluded,[]);self.assertEqual(len(records),2)
            rows.extend(records);books.append(book);expected.add((sport,venue,family,period))
        self.admit(rows,books)
        prices=await self.read_matrix(expected,56)
        # Four leagues x three shared first-half families x two outcomes x
        # two native directions. The eight MLB single-source prices have no peer.
        self.assertEqual(sum(q['current_comparison'].get('available') and q['current_comparison'].get('display_status')=='current' for q in prices),48)
        with self.connect() as db:
            from app.storage.coverage_latest import read
            counts=read(db,at=self.at.isoformat())['global_totals']
        self.assertEqual(counts['eligible_current_pairs'],24)
        self.assertEqual(counts['displayed_current_comparison_directions'],48)
        clocks={(q['source']['native_market_id'],q['source']['native_outcome_id']):q['times'] for q in prices}
        self.at+=timedelta(seconds=31);self.state.write(self.service)
        with self.connect() as db:
            captured=latest.snapshot(db,at=self.at.isoformat())
            aged=[q for key in captured['rows'] for q in latest.board(captured,key,view='odds',filter='all')['prices']]
        self.assertEqual(len(aged),56)
        for quote in aged:
            self.assertEqual(quote['times'],clocks[(quote['source']['native_market_id'],quote['source']['native_outcome_id'])])
            self.assertNotEqual(quote['freshness']['status'],'current')
