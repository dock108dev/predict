"""One disposable PostgreSQL 16 matrix through ingress, publication and HTTP."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from threading import Event
from time import monotonic
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import MagicMock,patch
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from psycopg import OperationalError

from app.collection.current_policy import DEFAULT
from app.collection.runtime_client import RuntimeClient
from app.collection.runtime_status import RuntimeState
from app.comparison.capabilities import SPORTS,CORE_FAMILIES
from app.storage.current_rows import CurrentRowStore
from app.storage import ordinary_publication as ordinary
from tests import test_latest_board_sql as fixtures
from tests.broad_pipeline_fixtures import captured_core_matrix,captured_partial,partial_case


@skipUnless(fixtures.SOCKET,'Explicit maintained disposable PostgreSQL lane required')
class NativeMatrixFixture(IsolatedAsyncioTestCase):
    connect=classmethod(fixtures.LatestBoardSQL.connect.__func__)
    setUpClass=classmethod(fixtures.LatestBoardSQL.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.LatestBoardSQL.tearDownClass.__func__)

    async def asyncSetUp(self):
        self.at=datetime.now(timezone.utc)
        self.config=dict(deepcopy(DEFAULT),native_sports=list(SPORTS),native_families=list(CORE_FAMILIES))
        self.enterContext(patch('app.collection.runtime_client.load',return_value=self.config))
        self.enterContext(patch('app.collection.runtime_status.clock',side_effect=lambda:self.at))
        for target in ('app.storage.current_rows.utc','app.storage.current_games.utc',
                       'app.storage.comparison_snapshot.utc','app.storage.ordinary_publication.utc',
                       'app.storage.comparison_board.utc','app.storage.coverage_latest.utc'):
            self.enterContext(patch(target,side_effect=lambda:self.at.isoformat()))
        self.service=SimpleNamespace(runtime_id='authored-broad-'+uuid4().hex,config=self.config,
            states={v:dict(state='available') for v in ('kalshi','polymarket_us','novig','prophetx','pinnacle')},
            dispatch=True,background_calculations=dict(board='running'),
            status=lambda:dict(issues=[],exclusions=[],database=dict(state='available')))
        self.state=RuntimeState(self.connect)
        with self.connect() as db:
            db.execute('TRUNCATE current_event CASCADE')
            db.execute("DELETE FROM current_row_state WHERE kind<>'epoch'")
            db.execute('TRUNCATE data_runtime,data_runtime_command,comparison_publication')
            db.execute("INSERT INTO comparison_publication(kind,id,generation,facts) VALUES('live','',0,'{}')")
        self.state.write(self.service)

    def admit(self,rows,books):
        with self.connect() as db:
            current=CurrentRowStore(db)
            current.upsert_records(rows,now=self.at.isoformat())
            current.replace_native_books(books)

    def publish(self):
        with self.connect() as db:
            for _ in range(5):
                result = ordinary.turn(db)
                if result['remaining_components'] == 0:
                    break
        self.assertEqual(result['remaining_components'], 0, result)
        return result


class BroadNativeMatrixSQL(NativeMatrixFixture):
    async def test_desk_withholds_prices_during_sql_stall_and_reconnects(self):
        from app.dashboard.snapshot_api import mount

        self.config['aggregate_provider'] = 'sportsgameodds'
        self.state.write(self.service)
        rows, books = await captured_core_matrix(self.at)
        self.admit(rows, books)
        query = dict(layout='desk', view='ev', browse_odds='1', summary='1',
                     basis='before', phase='pregame', lines='all', league='NBA')
        path = '/api/comparison-current'
        waiting, release = Event(), Event()
        stalled = False
        reads = 0
        outage_budget = 0.1
        timings = {}

        def connect():
            nonlocal reads
            reads += 1
            if stalled:
                waiting.set()
                if not release.wait(5):
                    raise AssertionError('SQL read was not released')
            return self.connect()

        def poly(page):
            return next(offer for row in page['rows'] for offer in row['offers']
                        if offer['venue'] == 'polymarket_us')

        app = web.Application()
        mount(app)
        with patch('app.dashboard.snapshot_api.connect', connect):
            async with TestClient(TestServer(app)) as client:
                start = monotonic()
                response = await client.get(path, params=query)
                self.assertEqual(response.status, 200, await response.text())
                self.assertTrue(poly(await response.json())['current'])
                timings['first_seconds'] = monotonic() - start
                start = monotonic()
                warm = await client.get(path, params=query)
                self.assertEqual(warm.status, 200, await warm.text())
                self.assertTrue(poly(await warm.json())['current'])
                timings['warm_seconds'] = monotonic() - start
                stalled = True
                try:
                    with patch('app.dashboard.desk_delivery.RESPONSE_SECONDS', outage_budget):
                        outage_samples = []
                        for _ in range(2):
                            start = monotonic()
                            response = await client.get(path, params=query)
                            self.assertEqual(response.status, 503)
                            self.assertNotIn('polymarket_us', await response.text())
                            outage_samples.append(monotonic() - start)
                    timings['outage_samples'] = outage_samples
                    self.assertTrue(waiting.is_set())
                    self.assertEqual(reads, 3)
                finally:
                    stalled = False
                    release.set()
                start = monotonic()
                response = await client.get(path, params=query)
                resumed = await response.json()
                timings['resumed_seconds'] = monotonic() - start
                self.assertTrue(poly(resumed)['current'])

        restarted = web.Application()
        mount(restarted)
        with patch('app.dashboard.snapshot_api.connect', side_effect=OperationalError):
            async with TestClient(TestServer(restarted)) as client:
                start = monotonic()
                response = await client.get(path, params=query)
                self.assertEqual(response.status, 503)
                self.assertNotIn('polymarket_us', await response.text())
                timings['restart_seconds'] = monotonic() - start
        if report := os.environ.get('PREDICT_CI_REPORT_ROOT'):
            (Path(report) / 'desk-recovery.json').write_text(json.dumps(dict(
                fixture='desk-polymarket-nba-v2', outage_budget_seconds=outage_budget, **timings
            ), indent=2) + '\n')

    async def test_native_selection_before_the_first_ordinary_seal(self):
        from app.dashboard.snapshot_api import mount

        self.config['aggregate_provider'] = 'sportsgameodds'
        self.state.write(self.service)
        rows, books = await captured_core_matrix(self.at)
        self.admit(rows, books)
        app = web.Application()
        mount(app)
        query = dict(layout='desk', view='ev', browse_odds='1', summary='1',
                     basis='before', phase='pregame', lines='all', league='NBA')
        with patch('app.dashboard.snapshot_api.connect', self.connect):
            async with TestClient(TestServer(app)) as client:
                response = await client.get('/api/comparison-current', params=query)
                self.assertEqual(response.status, 200, await response.text())
                page = await response.json()
                quote = next(offer for row in page['rows'] for offer in row['offers']
                             if offer['current'] and offer['id'].startswith('native-current:'))
                selection = dict(layout='desk', basis='before', phase='pregame', id=quote['id'])
                response = await client.get('/api/comparison-current/selection', params=selection)
                self.assertEqual(response.status, 200, await response.text())
                detail = await response.json()
                self.assertEqual(detail['row']['id'], quote['id'])
                self.assertEqual(detail['row']['original'], quote['original'])
                self.assertEqual(detail['row']['source_clock_at'], quote['source_clock_at'])
                self.assertTrue(detail['evidence']['inspection'])
                self.assertEqual(detail['provider_requests'], 0)

                previous = dict(selection, id='prior-sealed-offer', quote_key=quote['desk_quote_key'])
                response = await client.get('/api/comparison-current/selection', params=previous)
                self.assertEqual(response.status, 200, await response.text())
                adopted = await response.json()
                self.assertEqual(adopted['row']['id'], quote['id'])
                self.assertEqual(adopted['row']['desk_quote_key'], quote['desk_quote_key'])
                self.assertTrue(adopted['evidence']['inspection'])

                self.state.write(self.service, paused_sources=[quote['venue']])
                paused = await client.get('/api/comparison-current/selection', params=selection)
                self.assertIsNone((await paused.json())['row'])
                paused = await client.get('/api/comparison-current/selection', params=previous)
                self.assertIsNone((await paused.json())['row'])
                selection['id'] = 'native-current:absent-contract'
                missing = await client.get('/api/comparison-current/selection', params=selection)
                self.assertIsNone((await missing.json())['row'])

    async def read_matrix(self,expected_cells,expected_prices):
        from app.dashboard.comparison_board_api import mount
        from app.dashboard.snapshot_api import mount as mount_snapshots
        from app.storage.coverage_latest import reconcile
        self.publish()
        with self.connect() as db:
            self.assertTrue(reconcile(db,at=self.at.isoformat())['published'])
        provider=RuntimeClient(connector=self.connect)
        provider.acquire=MagicMock(side_effect=AssertionError('read dispatched provider'))
        app=web.Application();mount(app,provider);mount_snapshots(app)
        full_game = all(period == 'full_game' for _, _, _, period in expected_cells)

        def offers(group):
            if full_game:
                return group['offers']
            return [dict(quote, current=quote['price_current'],
                         source_clock_at=quote['times'].get('source_at'),
                         received_at=quote['times'].get('received_at'),
                         confirmed_at=(quote.get('book_confirmation') or {}).get('confirmed_at'))
                    for quote in group['quotes']]

        with patch('app.dashboard.comparison_board_api.connect',side_effect=self.connect),\
                patch('app.dashboard.snapshot_api.connect',side_effect=self.connect):
            async with TestClient(TestServer(app)) as client:
                query=dict(view='odds',layout='desk',browse_odds='1',last_known='1',limit='50')
                if not full_game:
                    desk = await client.get('/api/comparison-current', params=query)
                    self.assertEqual(desk.status, 200, await desk.text())
                    self.assertEqual((await desk.json())['rows'], [])
                    # Partial-period representations still publish and retain
                    # their exact clocks on the ordinary Odds board.
                    query = dict(view='odds', group='outcome', limit='50')
                result=await client.get('/api/comparison-current',params=query)
                self.assertEqual(result.status,200,await result.text());page=await result.json()
                self.assertEqual(page['provider_requests'],0)
                prices=[q for g in page['rows'] for q in offers(g)]
                self.assertEqual(len(prices),expected_prices)
                self.assertEqual({(g['league'],q['venue'],'moneyline' if q['market']['market']=='winner' else q['market']['market'],q['market']['period'])
                    for g in page['rows'] for q in offers(g)},expected_cells)
                # Both ordinary filters and metrics read the same retained facts.
                for scope in ({},{'league':'NBA'},{'period':'first_half'}):
                    result=await client.get('/api/coverage',params=scope)
                    self.assertEqual(result.status,200,await result.text())
                    self.assertEqual((await result.json())['provider_requests'],0)
                selected=prices[0]
                result=await client.get('/api/comparison-snapshot/details',params=dict(
                    result_id=selected['evidence_result_id'],id=selected['id']))
                self.assertEqual(result.status,200,await result.text());original=await result.json()
                self.assertEqual(original['row']['original'],selected['original'])
                self.assertEqual(original['row']['times']['source_at'],selected['source_clock_at'])
                self.assertEqual(original['row']['times']['received_at'],selected['received_at'])
                current_directions=0
                for group in page['rows']:
                    current=[q for q in offers(group) if q['current']]
                    if len({q['venue'] for q in current})>1:
                        current_directions+=len(current)
                from app.storage.coverage_latest import read
                with self.connect() as db:
                    counts=read(db,at=self.at.isoformat())['global_totals']
                self.assertEqual(counts['displayed_current_comparison_directions'],current_directions)

                self.at+=timedelta(seconds=31);self.state.write(self.service)
                result=await client.get('/api/comparison-current',params=query)
                self.assertEqual(result.status,200,await result.text());aged=await result.json()
                old=[q for group in aged['rows'] for q in offers(group)]
                def clocks(quotes):
                    return {q['id']:(q['source_clock_at'],q['received_at'],q['confirmed_at']) for q in quotes}
                self.assertEqual(clocks(old),clocks(prices))
                self.assertTrue(all(not q['current'] for q in old))
        provider.acquire.assert_not_called()
        return counts

    async def test_coverage_event_projection_keeps_publication_dependency_semantics(self):
        from psycopg.types.json import Jsonb
        from app.storage.coverage_latest import _EVENT_SQL
        from app.storage.observation_publication import identity_index,prepare_events
        rows,books=await captured_core_matrix(self.at)
        self.admit(rows,books)
        with self.connect() as db:
            event=db.execute('SELECT id,facts FROM current_event ORDER BY id LIMIT 1').fetchone()
            for change in (
                {},dict(state='suspended',status='delayed'),dict(occurrence_conflict=True),
                dict(conflicting_duplicate=True),dict(related_game_event_id='explicit-source-game'),
                dict(_native=dict(sportradarGameId='vendor-id',originalStartTime=self.at.isoformat(),
                    replacementGameId='replacement',gameNumber=2)),
                dict(native_metadata=dict(rescheduledFromGameId='prior-game',gameNumber=1)),
                # A nonempty native object wins even when all its fields are
                # irrelevant to matching. Do not accidentally fall back.
                dict(_native=dict(unused='x'*100000),native_metadata=dict(sportradarGameId='must-not-win')),
            ):
                with self.subTest(change=tuple(change)):
                    db.execute('UPDATE current_event SET facts=%s WHERE id=%s',
                        (Jsonb(dict(event['facts'],**change)),event['id']))
                    complete=identity_index(db)['events']
                    projected=db.execute(_EVENT_SQL).fetchall();prepare_events(projected)
                    for row in projected:
                        for field in ('dependency_revision','pair','start','participants','shared','reviewed'):
                            self.assertEqual(row[field],complete[row['id']][field],field)
                    self.assertNotIn('unused',str(projected))

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
        counts=await self.read_matrix(expected,56)
        # Four leagues x three shared first-half families x two outcomes x
        # two native directions. The eight MLB single-source prices have no peer.
        self.assertEqual(counts['eligible_current_pairs'],24)
        self.assertEqual(counts['displayed_current_comparison_directions'],48)
