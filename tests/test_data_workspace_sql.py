"""Game grouping and exact retained reads use one bounded passive snapshot."""

from copy import deepcopy
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from psycopg.types.json import Jsonb

from app.dashboard.research_api import CatalogReads, mount
from app.dashboard.request_guard import dashboard_guard
from app.research import experiment
from app.storage import research_catalog
from app.storage.store import stamp
from tests.latest_board_fixture import SOCKET
from tests.pregame_fixture import AT, PregameFixture, page
from tests import test_research_catalog_sql as fixtures


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class DataWorkspaceSQL(PregameFixture):
    ingest_linked = fixtures.ResearchCatalogSQL.ingest_linked

    async def asyncSetUp(self):
        await super().asyncSetUp()
        with self.connect() as db:
            db.execute('TRUNCATE public.ev_experiment_record CASCADE')
            db.execute('INSERT INTO public.ev_experiment_accounting(singleton) VALUES(true)')

    async def test_games_group_before_pagination_and_selected_game_keeps_exact_evidence(self):
        with self.connect() as db:
            refs = self.ingest_linked(db, page())
            self.process(db)
        reads = CatalogReads(self.connect)
        try:
            games = reads.games(dict(sport='NBA', date='2026-11-17', limit='1'))
            self.assertEqual(games['total'], 1)
            game, = games['rows']
            self.assertEqual(game['records'], len(refs))
            self.assertEqual(game['identity_status'], 'canonical')
            self.assertEqual(set(game['books']), {'prophetx', 'fanduel', 'draftkings'})
            self.assertEqual(game['markets'], ['spread'])
            selection = dict(token=games['token'], sport='NBA', date='2026-11-17', game_id=game['id'], limit='2')
            records = reads.read(selection)
            self.assertEqual(records['total'], len(refs))
            self.assertEqual(len(records['rows']), 2)
            self.assertEqual(records['game'], game)
            self.assertEqual(records['next_offset'], 2)
            selected = records['rows'][0]
            exact = reads.detail(dict(token=games['token'], id=selected['id'], revision=selected['revision']))
            self.assertEqual(exact['game_id'], game['id'])
            self.assertEqual(exact['price'], exact['source_input']['price_american'])
            all_records = reads.read(dict(selection, limit='100'))['rows']
            normalized = next(row for row in all_records if row['identity']['contract_id'])
            normalized_detail = reads.detail(dict(token=games['token'], id=normalized['id'], revision=normalized['revision']))
            from app.research.ev_movement import exact_bet_identity
            self.assertEqual(normalized_detail['checkpoint_bet_id'],
                exact_bet_identity(normalized_detail['normalized_record'])['id'])
            by_contract = reads.read(dict(selection, contract_id=normalized['identity']['contract_id']))
            self.assertEqual([row['id'] for row in by_contract['rows']], [normalized['id']])
            if normalized['exact_bet_id']:
                by_bet = reads.read(dict(selection, exact_bet_id=normalized['exact_bet_id'], limit='100'))
                self.assertIn(normalized['id'], [row['id'] for row in by_bet['rows']])
            self.assertEqual((games['provider_requests'], records['scheduled_calculations']), (0, 0))
        finally:
            reads.close()

    async def test_game_summary_counts_only_matching_trading_rows_and_scales_ev_once(self):
        data = page()
        for odd in data['data'][0]['odds'].values():
            for book in ('kalshi', 'novig'):
                odd['byBookmaker'][book] = deepcopy(odd['byBookmaker']['prophetx'])
        with self.connect() as db:
            self.ingest_linked(db, data)
            self.process(db)
            targets = list(db.execute('SELECT contract_id,payload FROM current_pregame_calculation ORDER BY contract_id'))
            self.assertEqual(len(targets), 4)
            template = next(row['payload'] for row in targets if row['payload'])
            for target, ratio in zip(targets, ('1/25', '-1/50', '0', None)):
                payload = deepcopy(template) if ratio is not None else None
                if payload:
                    payload['raw']['net_ev'] = ratio
                from fractions import Fraction
                db.execute('''UPDATE current_pregame_calculation SET payload=%s,reason=%s,net_ev=%s,
                    opportunity_score=%s WHERE contract_id=%s''',
                    (Jsonb(payload) if payload else None, 'fee_unknown' if payload is None else None,
                     float(Fraction(ratio)) if ratio is not None else None,
                     1 if ratio is not None else None, target['contract_id']))
            with patch.object(experiment, '_admit', return_value=None):
                experiment.discover(db, [dict(provider='sportsgameodds', source_event_id='event',
                    event_id='normalized-fixture', league='NBA', title='Milwaukee Bucks at Orlando Magic',
                    starts_at='2026-11-17T21:00:00Z', home='home', away='away', status={})], at=stamp(AT))
        reads = CatalogReads(self.connect)
        try:
            complete = reads.games({})['rows'][0]
            self.assertEqual(complete['records'], 10)
            self.assertEqual(complete['calculation_counts'], dict(positive=1, negative=1, zero=1,
                unavailable=3, reference_only=4))
            self.assertEqual(complete['best_net_ev_percent'], '4')
            self.assertEqual(complete['trading_book_count'], 3)
            self.assertEqual(complete['reference_book_count'], 2)
            self.assertEqual(set(complete['reference_books']), {'fanduel', 'draftkings'})
            positive_frame = reads.games(dict(calculation_status='positive'))
            positive = positive_frame['rows'][0]
            self.assertEqual(positive['records'], 10)
            self.assertEqual(positive['calculation_counts'], complete['calculation_counts'])
            self.assertEqual(positive['best_net_ev_percent'], '4')
            references = reads.games(dict(calculation_status='reference_only', original_bookmaker_id='fanduel'))['rows'][0]
            self.assertEqual(references['calculation_counts'], dict(positive=0, negative=0, zero=0,
                unavailable=0, reference_only=2))
            self.assertIsNone(references['best_net_ev_percent'])
            self.assertEqual(references['trading_books'], [])
            game_query = dict(token=positive_frame['token'], calculation_status='positive', game_id=positive['id'], limit='100')
            context = reads.read(game_query)
            self.assertEqual(context['total'], 10)
            negative = next(row for row in context['rows'] if row['calculation']['status']=='negative')
            exact_query = dict(token=positive_frame['token'], id=negative['id'], revision=negative['revision'])
            from app.dashboard.local_security import PublicRequestError
            with self.assertRaisesRegex(PublicRequestError, 'Unknown captured catalog record'):
                reads.detail(exact_query)
            bound_query = dict(exact_query, game_id=positive['id'])
            self.assertEqual(reads.detail(bound_query)['calculation']['status'], 'negative')
            app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
            with patch('app.dashboard.research_api.CatalogReads', return_value=reads):
                mount(app)
                async with TestClient(TestServer(app)) as client:
                    response = await client.get('/api/research/export', params=bound_query)
                    self.assertEqual(response.status, 200, await response.text())
                    exported = await response.json()
                    self.assertEqual(exported['calculation']['status'], 'negative')
                    self.assertEqual(exported['game_id'], positive['id'])
        finally:
            reads.close()

    async def test_expired_game_lease_returns_422_and_a_fresh_snapshot_recovers_the_selection(self):
        from time import monotonic
        with self.connect() as db:
            self.ingest_linked(db, page())
            self.process(db)
            before = list(db.execute('SELECT * FROM current_pregame_calculation ORDER BY contract_id'))
        reads = CatalogReads(self.connect)
        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        with patch('app.dashboard.research_api.CatalogReads', return_value=reads):
            mount(app)
            async with TestClient(TestServer(app)) as client:
                captured = await (await client.get('/api/research/games')).json()
                game = captured['rows'][0]
                reads.frames[captured['token']]['expires'] = monotonic()-1
                response = await client.get('/api/research/game', params=dict(token=captured['token'], game_id=game['id']))
                self.assertEqual(response.status, 422)
                self.assertEqual((await response.json())['error'], 'Catalog snapshot expired or filters changed; refresh data.')
                renewed = await (await client.get('/api/research/games')).json()
                self.assertNotEqual(renewed['token'], captured['token'])
                response = await client.get('/api/research/game', params=dict(token=renewed['token'], game_id=game['id']))
                recovered = await response.json()
                self.assertEqual(response.status, 200, recovered)
                self.assertEqual(recovered['game']['id'], game['id'])
                self.assertTrue(recovered['rows'])
                self.assertEqual((recovered['provider_requests'], recovered['scheduled_calculations']), (0, 0))
        with self.connect() as db:
            self.assertEqual(before, list(db.execute('SELECT * FROM current_pregame_calculation ORDER BY contract_id')))

    async def test_similar_names_without_established_identity_remain_separate_source_events(self):
        data = page()
        second = deepcopy(data['data'][0])
        second['eventID'] = 'source-local-distinct-event'
        second['status']['startsAt'] = '2026-11-17T22:00:00Z'
        data['data'].append(second)
        with self.connect() as db:
            self.ingest_linked(db, data)
            db.execute("UPDATE sgo_quote_revision SET facts=jsonb_set(facts,'{received_at}',%s) WHERE event_id=%s",
                (Jsonb('2026-11-17T19:59:00Z'), second['eventID']))
        reads = CatalogReads(self.connect)
        try:
            games = reads.games(dict(limit='1'))
            self.assertEqual(games['total'], 2)
            self.assertEqual(games['counts']['source_local_games'], 2)
            first, = games['rows']
            self.assertEqual(first['id'], 'source:sportsgameodds:event')
            second_page = reads.games(dict(token=games['token'], offset='1', limit='1'))
            other, = second_page['rows']
            self.assertEqual(first['title'], other['title'])
            self.assertNotEqual(first['id'], other['id'])
            self.assertEqual(len(first['source_events']), 1)
        finally:
            reads.close()

    async def test_date_filters_game_start_in_eastern_time(self):
        data = page()
        data['data'][0]['status']['startsAt'] = '2026-11-18T01:00:00Z'
        with self.connect() as db:
            self.ingest_linked(db, data)
        reads = CatalogReads(self.connect)
        try:
            self.assertEqual(reads.games(dict(date='2026-11-17'))['total'], 1)
            self.assertEqual(reads.games(dict(date='2026-11-18'))['total'], 0)
        finally:
            reads.close()

    async def test_retained_incomplete_game_remains_reachable_without_current_prices(self):
        event = dict(provider='sportsgameodds', source_event_id='historical-source', event_id='normalized-old',
            league='NCAAB', title='Away at Home', starts_at='2026-11-17T21:00:00Z', home='home', away='away', status={})
        with self.connect() as db, patch.object(experiment, '_admit', return_value=None):
            self.assertEqual(experiment.discover(db, [event], at=stamp(AT))['discovered'], 1)
        reads = CatalogReads(self.connect)
        try:
            games = reads.games(dict(sport='NCAAB', date='2026-11-17'))
            game, = games['rows']
            self.assertEqual(game['records'], 0)
            self.assertEqual(game['books'], [])
            self.assertEqual(game['identity_status'], 'source_local')
            self.assertEqual(len(game['experiment']['revision']), 64)
            records = reads.read(dict(token=games['token'], sport='NCAAB', date='2026-11-17', game_id=game['id']))
            self.assertEqual(records['rows'], [])
            self.assertEqual(records['game']['experiment'], game['experiment'])
            with self.connect() as db:
                detail = experiment.detail(db, game['experiment']['id'], revision=game['experiment']['revision'])
            self.assertIsNone(detail['early']['snapshot'])
            self.assertIsNone(detail['late']['snapshot'])
            self.assertEqual(detail['early']['status'], 'pending')
        finally:
            reads.close()

    async def test_http_game_contract_date_validation_and_nonpositive_filter_are_passive(self):
        with self.connect() as db:
            self.ingest_linked(db, page())
            self.process(db)
            db.execute("""UPDATE current_pregame_calculation SET reason='fee_unknown',payload=NULL,
                net_ev=NULL,opportunity_score=NULL WHERE contract_id=(
                SELECT contract_id FROM current_pregame_calculation LIMIT 1)""")
            before = list(db.execute('SELECT * FROM current_pregame_calculation ORDER BY contract_id'))
        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        from app.dashboard import workspace_routes
        with patch('app.dashboard.research_api.connect', side_effect=self.connect), \
                patch('app.storage.store.connect', side_effect=self.connect):
            mount(app)
            workspace_routes.mount(app, Path(__file__).resolve().parents[1] / 'app/dashboard')
            async with TestClient(TestServer(app)) as client:
                response = await client.get('/api/research/games?calculation_status=unavailable')
                self.assertEqual(response.status, 200, await response.text())
                games = await response.json()
                self.assertEqual(games['total'], 1)
                game, = games['rows']
                response = await client.get('/api/research/game', params=dict(token=games['token'],
                    calculation_status='unavailable', game_id=game['id']))
                records = await response.json()
                self.assertEqual(response.status, 200, records)
                self.assertTrue(records['rows'])
                unavailable = [row for row in records['rows'] if row['calculation']['status']=='unavailable']
                self.assertTrue(unavailable)
                self.assertTrue(all(row['calculation']['net_ev_percent'] is None for row in unavailable))
                self.assertTrue(any(row['calculation']['status']=='reference_only' for row in records['rows']))
                self.assertTrue(all(row['price'] is not None for row in records['rows']))
                self.assertEqual((await client.get('/api/research/games?date=2026-99-99')).status, 422)
                self.assertEqual((await client.get('/api/research/game')).status, 422)
                status_response = await client.get('/api/workspace/status')
                self.assertEqual(status_response.status, 200, await status_response.text())
                status = await status_response.json()
                self.assertEqual((status['provider_requests'], status['scheduled_calculations']), (0, 0))
                self.assertIn('remaining_bytes', status['storage'])
                self.assertIsNone(status['next_capture'])
        with self.connect() as db:
            self.assertEqual(before, list(db.execute('SELECT * FROM current_pregame_calculation ORDER BY contract_id')))

    async def test_reference_book_prices_never_enter_numeric_trading_filters_or_exports(self):
        with self.connect() as db:
            self.ingest_linked(db, page())
            self.process(db)
            target = db.execute('''SELECT q.id,k.contract_id,k.payload FROM current_pregame_calculation k
                JOIN current_offer_storage o USING(contract_id)
                JOIN sgo_quote_revision q ON q.id=o.sgo_quote_id AND q.revision=o.sgo_quote_revision
                WHERE k.payload IS NOT NULL LIMIT 1''').fetchone()
            # An old or inconsistent projection must not grant a reference
            # sportsbook numeric trading status merely because it has a payload.
            payload = deepcopy(target['payload'])
            payload['raw']['net_ev'] = '1/10'
            db.execute("UPDATE current_pregame_calculation SET payload=%s,net_ev=0.1 WHERE contract_id=%s",
                (Jsonb(payload), target['contract_id']))
            db.execute("""UPDATE sgo_quote_revision SET bookmaker_id='fanduel',
                facts=jsonb_set(facts,'{venue}','\"fanduel\"'::jsonb) WHERE id=%s AND is_current""", (target['id'],))
            before = db.execute('SELECT payload FROM current_pregame_calculation WHERE contract_id=%s',
                (target['contract_id'],)).fetchone()['payload']
        reads = CatalogReads(self.connect)
        try:
            filters = dict(provider='sportsgameodds', original_bookmaker_id='fanduel')
            self.assertEqual(reads.games(dict(filters, calculation_status='positive'))['total'], 0)
            received = reads.read(dict(filters, calculation_status='reference_only', limit='100'))
            selected = next(row for row in received['rows'] if row['id'] == 'sgo:'+target['id'])
            self.assertEqual(selected['trading_role'], 'reference_only')
            self.assertEqual(selected['calculation']['status'], 'reference_only')
            self.assertIsNotNone(selected['price'])
            exact = reads.detail(dict(token=received['token'], id=selected['id'], revision=selected['revision']))
            for key in ('calculation_payload', 'price_payload', 'fee_input', 'historical_conditional_calculation'):
                self.assertIsNone(exact[key], key)
            self.assertIsNone(exact['calculation']['net_ev_percent'])
            self.assertIsNone(exact['checkpoint_bet_id'])
            self.assertEqual(exact['source_input']['price_american'], selected['price'])
            app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
            with patch('app.dashboard.research_api.connect', side_effect=self.connect):
                mount(app)
                async with TestClient(TestServer(app)) as client:
                    value = await (await client.get('/api/research/catalog', params=dict(filters,
                        calculation_status='reference_only', limit='100'))).json()
                    row = next(row for row in value['rows'] if row['id'] == selected['id'])
                    response = await client.get('/api/research/export', params=dict(token=value['token'],
                        id=row['id'], revision=row['revision']))
                    self.assertEqual(response.status, 200, await response.text())
                    exported = await response.json()
                    self.assertEqual(exported['trading_role'], 'reference_only')
                    self.assertIsNone(exported['calculation_payload'])
                    self.assertIsNone(exported['calculation']['net_ev_percent'])
        finally:
            reads.close()
        with self.connect() as db:
            self.assertEqual(before, db.execute('SELECT payload FROM current_pregame_calculation WHERE contract_id=%s',
                (target['contract_id'],)).fetchone()['payload'])

    async def test_selected_reference_scope_is_sgo_only_and_history_preserves_other_books_and_exchanges(self):
        from app.comparison.reference_scope import REFERENCE_BOOKS
        from app.comparison.snapshot_fee_outcome import VENUES
        from app.collection.bulk_checkpoint import save_images
        from tests.test_current_service import native_fixture
        data = page()
        for odd in data['data'][0]['odds'].values():
            for book in ('unibet', 'matchbook'):
                odd['byBookmaker'][book] = deepcopy(odd['byBookmaker']['fanduel'])
        with self.connect() as db:
            self.ingest_linked(db, data)
        _, native = native_fixture()
        with patch('app.collection.bulk_checkpoint.connect', side_effect=self.connect):
            save_images('kalshi', [native], 'rejected')
        reads = CatalogReads(self.connect)
        try:
            current = reads.read(dict(limit='100'))
            self.assertTrue(current['rows'])
            self.assertEqual({row['provider'] for row in current['rows']}, {'sportsgameodds'})
            self.assertTrue(all(row['original_bookmaker_id'] in REFERENCE_BOOKS
                or row['represented_venue'] in VENUES for row in current['rows']))
            self.assertEqual([book['id'] for book in current['reference_scope']['books']], list(REFERENCE_BOOKS))
            historical = reads.read(dict(reference_scope='all', provider='sportsgameodds', limit='100'))
            other = next(row for row in historical['rows'] if row['original_bookmaker_id'] == 'unibet')
            self.assertEqual(other['trading_role'], 'reference_only')
            exchange = next(row for row in historical['rows'] if row['original_bookmaker_id'] == 'matchbook')
            self.assertEqual(exchange['trading_role'], 'prediction_market')
            self.assertEqual(exchange['calculation']['reason'], 'unsupported_trading_venue')
            self.assertIsNone(exchange['calculation']['net_ev_percent'])
            all_sources = reads.games(dict(reference_scope='all'))
            self.assertTrue(any('kalshi' in game['providers'] for game in all_sources['rows']))
        finally:
            reads.close()

    async def test_arbitrage_uses_selected_reference_books_and_never_book_only_pairs(self):
        from app.storage.pregame_arbs import read
        from app.comparison.reference_scope import REFERENCE_BOOKS
        data = page()
        for odd in data['data'][0]['odds'].values():
            odd['byBookmaker']['unibet'] = dict(odd['byBookmaker']['fanduel'], odds='+1000')
        with self.connect() as db:
            self.ingest_linked(db, data)
            self.process(db)
            # Current pairing owns the frozen acquisition, independently of
            # working-table omission grace and historical catalog membership.
            from tests.test_market_snapshot_arbs_sql import SnapshotArbsSQL

            db.execute('TRUNCATE public.market_pull CASCADE')
            SnapshotArbsSQL.capture(self,db,data=data)
            selected = read(db, dict(league='NBA'), at=stamp(AT))
            historical = read(db, dict(league='NBA', reference_scope='all'), at=stamp(AT))
        self.assertTrue(any(any(leg['venue']=='unibet' for leg in pair['legs']) for pair in historical['rows']))
        self.assertFalse(any(any(leg['venue']=='unibet' for leg in pair['legs']) for pair in selected['rows']))
        for pair in selected['rows']:
            self.assertIn(pair['category'], ('market_book', 'market_market'))
            self.assertTrue(any(leg['venue'] in ('kalshi','polymarket_us','novig','prophetx') for leg in pair['legs']))
            self.assertTrue(all(leg['venue'] in REFERENCE_BOOKS or leg['venue'] in ('kalshi','polymarket_us','novig','prophetx') for leg in pair['legs']))
            if pair['category'] == 'market_book':
                self.assertEqual(pair['category_label'],'Sportsbook reference comparison')
                self.assertFalse(pair['executable_legs'])

    async def test_grouping_identity_and_prices_stay_bound_to_snapshot_after_new_revision(self):
        with self.connect() as db:
            self.ingest_linked(db, page())
            self.process(db)
        reads = CatalogReads(self.connect)
        try:
            original = reads.games({})
            selected, = original['rows']
            with self.connect() as db:
                db.execute("UPDATE current_pregame_calculation SET game_key='pregame:new-occurrence'")
            frozen = reads.games(dict(token=original['token'], game_id=selected['id']))
            self.assertEqual(frozen['rows'], [selected])
            self.assertTrue(reads.read(dict(token=original['token'], game_id=selected['id']))['rows'])
            fresh = reads.games({})
            self.assertNotEqual(fresh['rows'][0]['id'], selected['id'])
        finally:
            reads.close()


    @patch('app.storage.current_pregame.configured_routes', return_value={venue: 'sportsgameodds' for venue in ('kalshi','polymarket_us','novig','prophetx')})
    async def test_zero_fee_assumption_exposes_polymarket_math_without_claiming_native_venue_identity(self, _routes):
        from fractions import Fraction
        from app.comparison import fee_mode
        data = page()
        for odd in data['data'][0]['odds'].values():
            odd['byBookmaker']['polymarket'] = deepcopy(odd['byBookmaker']['fanduel'])
        with self.connect() as db:
            self.ingest_linked(db, data)
            fee_mode.set_enabled(db, False)
            self.process(db)
            from app.storage.current_pregame import read as active_read
            active = active_read(db, dict(venue='polymarket_us', browse='1', lines='all'), at=AT)
            self.assertTrue(active['rows'], list(db.execute("SELECT venue,reason,main,payload->'fee_mode' mode FROM current_pregame_calculation")))
            self.assertTrue(all(row['fee_mode']['enabled'] is False for row in active['rows']))
        reads = CatalogReads(self.connect)
        try:
            frame = reads.read(dict(provider='sportsgameodds', original_bookmaker_id='polymarket', limit='100'))
            self.assertFalse(frame['fee_mode']['enabled'])
            numeric = [row for row in frame['rows'] if row['calculation']['net_ev_percent'] is not None]
            self.assertTrue(numeric)
            for row in numeric:
                self.assertEqual(row['venue_equivalence'], 'unestablished')
                self.assertFalse(row['fee_mode']['enabled'])
                exact = reads.detail(dict(token=frame['token'], id=row['id'], revision=row['revision']))
                self.assertFalse(exact['calculation_payload']['fee_mode']['enabled'])
                self.assertEqual(Fraction(exact['calculation_payload']['fee']['entry_usd']), 0)
                self.assertTrue(all(Fraction(state['total_fee_usd']) == 0 for state in
                    exact['calculation_payload']['fee']['cashflows'].values()))
            self.assertEqual(frame['provider_requests'], 0)
        finally:
            reads.close()


class CheckpointSourceIdentity(TestCase):
    def fixture(self):
        from app.collection.sportsgameodds_current_rows import current_rows, source_bookmaker
        from app.comparison.current_pregame import reference_key
        from tests.pregame_fixture import parse
        parsed = parse(page())
        record = current_rows(parsed, parsed.receipt_sha256)[0][0]
        source = record['quote']['source']
        family, side, _ = reference_key(record)
        header = dict(provider=source['provider'], event_id=source['native_event_id'],
            market_id=source['native_outcome_id'], original_bookmaker_id=source_bookmaker(record))
        received = dict(market=family, side=side, period='game', line=record['selection']['signed_line'])
        return record, header, received

    def match(self, record, header, received, late=None):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = dict(id='frozen-game', early_id='early', late_id='late')
        def checkpoint(_db, _game, label, _index):
            return dict(status='captured', snapshot=dict(offers=[dict(record=late if label == 'late' and late else record)]))
        with patch.object(experiment, '_closure', return_value={'retained': True}), \
                patch.object(experiment, '_checkpoint_view', side_effect=checkpoint), \
                patch.object(experiment, '_revision', return_value='frozen-revision'):
            return research_catalog.checkpoint_source_match(db, header, received)

    def test_exact_source_tuple_links_both_observations_without_current_normalization(self):
        from app.research.ev_movement import exact_bet_identity
        record, header, received = self.fixture()
        later = deepcopy(record)
        later['comparison_source_metadata']['alternate'] = True
        later['quote']['original']['value'] = '+125'
        value, reason = self.match(record, header, received, late=later)
        self.assertIsNone(reason)
        self.assertEqual(value['id'], exact_bet_identity(record)['id'])
        self.assertEqual(value['checkpoints'], ['early', 'late'])
        wrong_line = dict(received, line=str(int(float(received['line'])) + 1))
        self.assertEqual(self.match(record, header, wrong_line), (None, 'exact_source_line_not_in_checkpoint_offers'))
        self.assertEqual(self.match(record, dict(header, original_bookmaker_id='another-book'), received),
            (None, 'exact_source_line_not_in_checkpoint_offers'))

    def test_same_source_line_with_different_settlement_identity_refuses_bridge(self):
        record, header, received = self.fixture()
        later = deepcopy(record)
        later['result_policy'] = 'different-settlement-policy'
        self.assertEqual(self.match(record, header, received, late=later),
            (None, 'checkpoint_source_identity_ambiguous'))
