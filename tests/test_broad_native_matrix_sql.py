"""One disposable PostgreSQL 16 matrix through ingress, publication and HTTP."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import MagicMock,patch
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from psycopg import OperationalError
from psycopg import sql

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
            from app.storage.pregame_cohorts import SCHEMAS, TABLES

            for schema in SCHEMAS.values():
                for table in TABLES:
                    db.execute(sql.SQL('TRUNCATE {}').format(sql.Identifier(schema, table)))
            db.execute('TRUNCATE current_event,sgo_event_evidence,sgo_quote_revision,current_pregame_work CASCADE')
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
            result = ordinary.turn(db)
            self.assertFalse(result['errors'], result)
            # The fixture holds inputs and the clock fixed. Each successful
            # turn must shrink the queue, even when its budget fits one job.
            while remaining := result['remaining_components']:
                result = ordinary.turn(db)
                self.assertFalse(result['errors'], result)
                self.assertLess(result['remaining_components'], remaining, result)
            return result


class BroadNativeMatrixSQL(NativeMatrixFixture):
    def prepare_current(self):
        from app.fees import pricing
        from app.storage import current_pregame
        from app.storage.pregame_cohorts import capture
        from app.storage.store import stamp
        from tests.test_current_pregame_sql import CurrentPregameSQL, page, AT
        from tests.test_fee_pricing import rule

        self.at = stamp(AT)
        self.config["aggregate_provider"] = "sportsgameodds"
        self.state.write(self.service)
        self.enterContext(
            patch("app.storage.current_pregame.utc", side_effect=lambda: self.at)
        )
        with self.connect() as db:
            pricing.write(db, "prophetx", [rule("prophetx")])
            data = page()
            CurrentPregameSQL.ingest(self, db, data)
            current_pregame.process(db, at=self.at)
            # Simulate the admission owner's explicit Monitor publication.
            # API reads must never adopt public rows or calculate on demand.
            capture(db, dict(kind="monitor", id="fixture-monitor"),
                    [event["eventID"] for event in data["data"]], self.at)

    async def test_current_read_failure_recovers_without_discarding_stored_values(self):
        from app.dashboard.snapshot_api import mount

        self.prepare_current()
        failed = False
        reads = 0
        timings = {}

        def connect():
            nonlocal reads
            reads += 1
            if failed:
                raise OperationalError("Authored SQL outage")
            return self.connect()

        app = web.Application()
        mount(app)
        query = dict(layout="desk", browse_odds="1", league="NBA")
        with patch("app.dashboard.snapshot_api.connect", connect):
            async with TestClient(TestServer(app)) as client:
                original = None
                for label in ("first", "warm"):
                    start = monotonic()
                    response = await client.get("/api/comparison-current", params=query)
                    self.assertEqual(response.status, 200, await response.text())
                    value = await response.json()
                    self.assertTrue(value["rows"])
                    self.assertTrue(
                        all(
                            row["source"]["provider"] == "sportsgameodds"
                            for row in value["rows"]
                        )
                    )
                    original = value["rows"]
                    timings[label + "_seconds"] = monotonic() - start
                failed = True
                for _ in range(2):
                    response = await client.get("/api/comparison-current", params=query)
                    self.assertEqual(response.status, 503)
                    self.assertNotIn("prophetx", await response.text())
                failed = False
                resumed = await client.get("/api/comparison-current", params=query)
                self.assertEqual((await resumed.json())["rows"], original)
                self.assertEqual(reads, 5)
        if report := os.environ.get("PREDICT_CI_REPORT_ROOT"):
            (Path(report) / "desk-recovery.json").write_text(
                json.dumps(
                    dict(fixture="current-pregame-committed-read", **timings), indent=2
                )
                + "\n"
            )

    async def test_selection_reads_committed_price_without_publication(self):
        from app.dashboard.snapshot_api import mount
        from app.storage import current_pregame

        self.prepare_current()
        app = web.Application()
        mount(app)
        query = dict(layout="desk", browse_odds="1", league="NBA")
        with (
            patch("app.dashboard.snapshot_api.connect", self.connect),
            patch.object(
                current_pregame,
                "process",
                side_effect=AssertionError("Read scheduled calculation"),
            ),
        ):
            async with TestClient(TestServer(app)) as client:
                response = await client.get("/api/comparison-current", params=query)
                self.assertEqual(response.status, 200, await response.text())
                packet = await response.json()
                quote = packet["rows"][0]
                selection = dict(layout="desk", id=quote["id"], data_type=packet["data_type"])
                enriched_rows = None
                for params in (selection, dict(layout="desk", quote_key=quote["id"])):
                    response = await client.get(
                        "/api/comparison-current/selection", params=params
                    )
                    self.assertEqual(response.status, 200, await response.text())
                    detail = await response.json()
                    self.assertEqual(len(detail['rows']),1)
                    # Exact inspection adds selected-only venue evidence to a
                    # copy. Every committed input, clock and result stays the
                    # same as Browse; aggregate size remains unknown, not zero.
                    selected_row = dict(detail['rows'][0])
                    size = selected_row.pop('available_size')
                    self.assertEqual(selected_row,quote)
                    self.assertEqual(size['status'],'unknown')
                    self.assertIsNone(size['quantity'])
                    self.assertTrue(size['reason'])
                    if enriched_rows is None:enriched_rows=deepcopy(detail['rows'])
                    else:self.assertEqual(detail['rows'],enriched_rows)
                    self.assertEqual(detail["provider_requests"], 0)
                    self.assertEqual(detail["scheduled_calculations"], 0)
                unchanged = await client.get('/api/comparison-current',params=query)
                self.assertEqual((await unchanged.json())['rows'],packet['rows'])
                retired = await client.get(
                    "/api/comparison-current", params=dict(query, basis="before")
                )
                self.assertEqual(retired.status, 410)
                self.state.write(
                    self.service, paused_sources=["sportsgameodds"], global_stopped=True
                )
                paused = await client.get(
                    "/api/comparison-current/selection", params=selection
                )
                self.assertEqual((await paused.json())["rows"], enriched_rows)
                missing = await client.get(
                    "/api/comparison-current/selection",
                    params=dict(selection, id="absent-contract"),
                )
                self.assertEqual((await missing.json())["rows"], [])

    async def read_matrix(self,expected_cells,expected_prices):
        from app.dashboard.comparison_board_api import mount
        from app.dashboard.snapshot_api import mount as mount_snapshots
        from app.storage.coverage_latest import reconcile
        self.publish()
        with self.connect() as db:
            self.assertTrue(reconcile(db,at=self.at.isoformat())['published'])
            result_id = ordinary.status(db)['result_id']
        provider=RuntimeClient(connector=self.connect)
        provider.acquire=MagicMock(side_effect=AssertionError('read dispatched provider'))
        app=web.Application();mount(app,provider);mount_snapshots(app)
        full_game = all(period == 'full_game' for _, _, _, period in expected_cells)

        def snapshot_offers(group):
            return [dict(quote,
                         source_clock_at=quote['times'].get('source_at'),
                         received_at=quote['times'].get('received_at'),
                         confirmed_at=(quote.get('book_confirmation') or {}).get('confirmed_at'))
                    for quote in group['quotes']]

        def offers(group):
            return [dict(quote, current=quote['price_current']) for quote in snapshot_offers(group)]

        def clocks(quotes):
            return {q['id']:(q['source_clock_at'],q['received_at'],q['confirmed_at']) for q in quotes}

        with patch('app.dashboard.comparison_board_api.connect',side_effect=self.connect),\
                patch('app.dashboard.snapshot_api.connect',side_effect=self.connect):
            async with TestClient(TestServer(app)) as client:
                # The source matrix has no complete sportsbook references.
                # Its original quotes remain available to research and replay.
                from app.storage import current_pregame

                with self.connect() as db:
                    current_pregame.process(db, at=self.at)
                desk = await client.get(
                    "/api/comparison-current",
                    params=dict(layout="desk", browse_odds="1"),
                )
                self.assertEqual(desk.status, 200, await desk.text())
                self.assertEqual((await desk.json())["rows"], [])
                query = dict(view="odds", group="outcome", limit="50")
                result=await client.get('/api/comparison-current',params=query)
                self.assertEqual(result.status,200,await result.text());page=await result.json()
                self.assertEqual(page['provider_requests'],0)
                prices=[q for g in page['rows'] for q in offers(g)]
                self.assertEqual(len(prices),expected_prices)
                if full_game:
                    self.assertTrue(all(q['current'] for q in prices))
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
                retained = [q for group in aged['rows'] for q in offers(group)]
                self.assertTrue(all(q['current'] for q in retained))
                self.assertEqual(len(retained), expected_prices)
                self.assertEqual(clocks(retained), clocks(prices))
                if full_game:
                    self.at = max(datetime.fromisoformat(group['start_at']) for group in aged['rows'])
                    self.state.write(self.service)
                    result = await client.get('/api/comparison-current', params=query)
                    self.assertEqual(result.status, 200, await result.text())
                    self.assertEqual((await result.json())['rows'], [])
                    # Kickoff only affects the current view.
                    result = await client.get('/api/comparison-snapshot', params=dict(
                        result_id=result_id, view='odds', group='outcome', limit='50'))
                    self.assertEqual(result.status, 200, await result.text())
                    saved = await result.json()
                    self.assertEqual(saved['provider_requests'], 0)
                    retained = [q for group in saved['rows'] for q in snapshot_offers(group)]
                    self.assertEqual(len(retained), expected_prices)
                    self.assertEqual(clocks(retained), clocks(prices))
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
