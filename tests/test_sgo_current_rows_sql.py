"""SGO retirement scopes cannot erase another provider's observations."""
from unittest import skipUnless
from copy import deepcopy
from datetime import datetime
from unittest.mock import patch

from app.collection.current_aggregate_admission import admit
from app.collection.sportsgameodds_current_rows import current_rows
from app.storage.current_rows import CurrentRowStore
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.test_current_aggregate import body
from tests.test_sportsgameodds_adapter import AT, parse, response


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class SGOScopeSQL(LatestBoardFixture):
    async def test_prophet_exchange_saved_quote_reaches_retail_desk_with_fee(self):
        from datetime import timedelta
        from app.collection.current_policy import DEFAULT
        from app.collection.runtime_status import read_runtime
        from app.comparison.snapshot_math import assumptions
        from app.dashboard.trade_desk import page as desk_page
        from app.fees import schedule_lifecycle
        from app.storage.comparison_snapshot import capture
        from app.storage.current_row_state import source_status
        from app.storage.ordinary_publication import dependencies, prices, project
        from app.storage.sportsgameodds_reference import backfill_prophetx, prepare_frames, prepare_page, upsert_frames, upsert_rows
        from app.storage.store import stamp

        at = stamp(AT)
        self.at = at
        raw = response()
        event = raw['data'][0]
        event['eventID'] = 'prophet-exchange-retail-fee-fixture'
        books = event['odds']['points-home-game-sp-home']['byBookmaker']
        books['prophetexchange'] = books.pop('book')
        page = parse(raw)
        record, = current_rows(page, page.receipt_sha256)[0]
        assert record['quote']['venue'] == 'prophetx'
        assert record['comparison_source_metadata']['provider_bookmaker_id'] == 'prophetexchange'
        config = dict(DEFAULT, aggregate_provider='sportsgameodds', aggregate_sports=['NBA'])
        states = {'sportsgameodds': {'state': 'available'}}
        self.service.config = config
        self.state.write(self.service)
        approval = schedule_lifecycle.approved()
        fee_state = dict(last_verified=dict(approval=approval, verified_at=AT,
            review_before=(at+timedelta(hours=1)).isoformat(), revision='fixture',
            retrieval=dict(document=dict(sha256=approval['document_sha256']))))
        owner = dict(healthy=True, active=True, config=config, fee_lifecycle=fee_state)
        with self.connect() as db, patch('app.storage.ordinary_publication.utc', return_value=AT):
            refs = prepare_page(page)
            upsert_rows(db, refs)
            upsert_frames(db, prepare_frames(page, refs))
            source_status(db.execute, 'sportsgameodds', states['sportsgameodds'], AT)
            schedule_lifecycle.write(db, fee_state)
            runtime = read_runtime(db)
            assert runtime['active'] and runtime['config']['aggregate_provider'] == 'sportsgameodds'
            assert db.execute('SELECT count(*) AS n FROM current_sgo_reference WHERE bookmaker_id=%s',
                              ('prophetexchange',)).fetchone()['n'] == 1
            assert db.execute('SELECT count(*) AS n FROM current_sgo_event_frame WHERE event_id=%s',
                              (event['eventID'],)).fetchone()['n'] == 1
            assert backfill_prophetx(db, at=AT) == 1
            backfill_prophetx(db, at=AT)
            physical = db.execute("""SELECT q.bookmaker_id,o.received_at,c.event_id,c.independent_depth
                FROM current_offer_storage o JOIN current_contract_storage c ON c.id=o.contract_id
                JOIN sgo_quote_revision q ON (q.id,q.revision)=(o.sgo_quote_id,o.sgo_quote_revision)
                WHERE c.venue='prophetx'""").fetchone()
            assert physical['bookmaker_id'] == 'prophetexchange'
            assert physical['received_at'] == page.quotes[0]['received_at']
            assert physical['independent_depth'] is None
            assert db.execute("SELECT count(*) AS n FROM current_contract WHERE venue='prophetx'").fetchone()['n'] == 1
            ids = [physical['event_id']]
            captured = capture(db, at=AT, ordinary=True, event_ids=ids)
            assert len(captured['quotes']) == 1, captured['issues']
            published = prices(captured, assumptions()[0])
            result = project(published, dependencies(db, ids), owner, states, at=at,
                             policy=captured['policy_identity'], epoch=captured['epoch'])
            assert len(result['rows']) == 1
            assert result['rows'][0]['price_current'], result['rows'][0]['price_reasons']
            visible = desk_page(result, dict(layout='desk', browse_odds='1', phase='pregame'), ('ev', None, 0, 25))
            offer, = visible['rows'][0]['offers']
            assert offer['venue'] == 'prophetx' and offer['original']['value'] == '-110'
            assert offer['trade_fee']['fee_cashflows'] == dict(at_fill_usd='0', winning_settlement_usd='0.01', losing_settlement_usd='0')
            assert offer['current'] and visible['provider_requests'] == 0

    async def test_exact_novig_catalog_changes_withdraw_fee_without_withdrawing_price(self):
        import json

        from app.collection.current_policy import DEFAULT
        from app.collection.sportsgameodds_adapter import parse_page
        from app.comparison.snapshot_math import assumptions
        from app.storage import sgo_native_catalog as catalog
        from app.storage.comparison_snapshot import capture
        from app.storage.ordinary_publication import dependencies, prices, project
        from app.storage.sportsgameodds_reference import prepare_frames, prepare_page, upsert_frames, upsert_rows
        from app.storage.store import stamp
        from tests.test_sgo_native_binding import AT, EVENT, HOME, SGO, START, fixture, witness

        raw = response()
        event = raw['data'][0]
        event.update(eventID=SGO, leagueID='NHL', links={'bookmakers': {
            'novig': f'https://novig.com/event-markets/{EVENT}/sportsgameodds'}})
        event['status']['startsAt'] = START
        for role, team in (('away', 'Carolina Hurricanes'), ('home', 'Seattle Kraken')):
            event['teams'][role]['names']['long'] = team
        offer = event['odds']['points-home-game-sp-home']
        offer['byBookmaker'] = {'novig': dict(available=True, odds='-135', spread='1.5',
            lastUpdatedAt=AT, deeplink=f'https://novig.com/events/{HOME}/sportsgameodds')}
        page = parse_page(json.dumps(raw).encode(), AT)
        rows, _ = current_rows(page, page.receipt_sha256)
        _, official_event, official_market = fixture()
        config = dict(DEFAULT, aggregate_provider='sportsgameodds', aggregate_sports=['NHL'])
        states = {'sportsgameodds': {'state': 'available'}}
        owner = dict(healthy=True, active=True, config=config)
        self.service.config = config
        self.state.write(self.service)
        with self.connect() as db, patch('app.storage.ordinary_publication.utc', return_value=AT):
            CurrentRowStore(db).upsert_records(rows, now=AT, source_status=states)
            catalog.write(db, SGO, witness(official_event, official_market))
            event_id = db.execute('SELECT id FROM current_event WHERE native_event_id=%s', (SGO,)).fetchone()['id']
            reference_rows = prepare_page(page)
            upsert_rows(db, reference_rows)
            upsert_frames(db, prepare_frames(page, reference_rows))
            captured = capture(db, at=AT, ordinary=True, event_ids=[event_id])
            published = prices(captured, assumptions()[0])

            def visible():
                return project(published, dependencies(db, [event_id]), owner, states, at=stamp(AT),
                               policy=captured['policy_identity'], epoch=captured['epoch'])['rows'][0]

            row = visible()
            assert row['price_current'] and row['sgo_native_contract']['available']
            assert row['trade_fee']['trade_fee_usd'] == '0'
            db.execute('DELETE FROM current_sgo_native_catalog WHERE event_id=%s', (SGO,))
            row = visible()
            assert row['price_current'] and not row['sgo_native_contract']['available']
            assert row['trade_fee']['reason'] == 'sgo_native_catalog_replaced_or_expired'

    async def test_native_sportsbook_dependencies_bind_exact_book_pair_and_frame(self):
        from types import SimpleNamespace
        from app.collection.current_policy import DEFAULT
        from app.storage.ordinary_publication import dependencies, sportsbook_dependencies
        from app.storage.sportsgameodds_reference import prepare_frames, prepare_page, upsert_frames, upsert_rows

        data = response()
        event = data['data'][0]
        home = event['odds']['points-home-game-sp-home']
        book = home['byBookmaker']['book']
        home['byBookmaker'] = {'novig':book, 'fanduel':dict(book,altLines=[dict(book,spread='-2.5')]),
                              'draftkings':book}
        away = dict(home, oddID=home['opposingOddID'], opposingOddID=home['oddID'],
                    statEntityID='away', sideID='away',
                    byBookmaker={'fanduel':dict(book,spread='1.5',altLines=[dict(book,spread='2.5')])})
        event['odds'][away['oddID']] = away
        parsed = parse(data)
        originals, _ = current_rows(parsed, parsed.receipt_sha256)
        references = prepare_page(parsed)
        config = dict(DEFAULT, aggregate_provider='sportsgameodds', aggregate_sports=['NBA'])
        reviewed = [(dict(event_id=event['eventID'],venue='fanduel',odd_id=odd['oddID'],
                          frame_id=parsed.receipt_sha256,line=line), {})
                    for odd, line in ((home, '-1.50'), (away, '1.50'))]
        self.service.config = config
        self.state.write(self.service)
        with self.connect() as db, \
                patch('app.storage.ordinary_publication.reviewed_reference_registry',return_value=SimpleNamespace(rows=reviewed)):
            CurrentRowStore(db).upsert_records(originals, now=AT)
            upsert_rows(db, references)
            upsert_frames(db, prepare_frames(parsed, references))
            event_ids = [row['id'] for row in db.execute('SELECT id FROM current_event').fetchall()]
            rows = sportsbook_dependencies(db, event_ids)
            assert len(rows) == 2 and all(row['receipt'].endswith(parsed.receipt_sha256) for row in rows)
            expected = {row['id'] for row in references if row['bookmaker_id']=='fanduel'
                        and row['facts']['line'] in ('-1.5', '1.5')}
            assert {row['contract'] for row in rows} == expected
            assert {key for key in dependencies(db,event_ids) if key.startswith('sgo-reference:')} == {row['id'] for row in rows}
            db.execute("UPDATE current_sgo_event_frame SET facts=jsonb_set(facts,'{receipt_sha256}',to_jsonb('new-frame'::text))")
            assert sportsbook_dependencies(db,event_ids) == []

    async def test_sportsbook_baseline_reaches_ordinary_desk_and_expires(self):
        from app.collection.current_policy import DEFAULT
        from app.comparison.snapshot_math import assumptions
        from app.dashboard.coverage_finance_inputs import measure_inputs
        from app.dashboard.coverage_funnel import measure
        from app.dashboard.fee_coverage import census, source_inventory
        from app.dashboard.trade_desk import add_sgo_prices, page as desk
        from app.storage.comparison_snapshot import capture, defer_details
        from app.storage.ordinary_publication import prices, project, turn
        from app.storage.sportsgameodds_reference import prepare_frames, prepare_page, upsert_frames, upsert_rows
        from app.storage.store import stamp

        data = response()
        event = data['data'][0]
        event['eventID'] = 'sportsbook-baseline-event'
        event['status'].update(startsAt='2026-11-10T19:59:55Z', started=True, live=True)
        home = event['odds']['points-home-game-sp-home']
        offer = dict(available=True, odds='+140', spread='-1.5', lastUpdatedAt=AT)
        home['byBookmaker'] = {'novig': offer, 'fanduel': dict(offer, odds='+120'),
                               'draftkings': dict(offer, odds='+130')}
        away = dict(home, oddID=home['opposingOddID'], opposingOddID=home['oddID'], statEntityID='away', sideID='away',
                    byBookmaker={'fanduel': dict(offer, odds='-150', spread='1.5')})
        event['odds'][away['oddID']] = away
        parsed = parse(data)
        records, _ = current_rows(parsed, parsed.receipt_sha256)
        references = prepare_page(parsed)
        config = dict(DEFAULT, aggregate_provider='sportsgameodds', aggregate_sports=['NBA'])
        states = {'sportsgameodds': {'state': 'available'}}
        owner = dict(healthy=True, active=True, config=config)
        settings = assumptions()[0]
        self.at = stamp(AT)
        self.service.config = config
        self.state.write(self.service)
        with self.connect() as db, patch('app.collection.current_policy.load', return_value=config):
            CurrentRowStore(db).upsert_records(records, now=AT, source_status=states)
            upsert_rows(db, references)
            upsert_frames(db, prepare_frames(parsed, references))
            event_ids = [r['id'] for r in db.execute('SELECT id FROM current_event').fetchall()]
            inputs = capture(db, at=AT, ordinary=True, event_ids=event_ids)
            assert len(inputs['quotes']) == 1, inputs['issues']
            assert inputs['quotes'][0].get('sportsbook_baseline')
            publication = defer_details(prices(inputs, settings))
            at = stamp(AT)
            projected = project(publication, inputs['dependencies'], owner, states,
                                at=at, policy=inputs['policy_identity'], epoch=inputs['epoch'])
            matrix = desk(projected, {'basis': 'sportsbooks', 'browse_odds': '1'}, ('ev', None, 0, 25))
            add_sgo_prices(db, matrix, projected['rows'], states, at=at, include_retained=False)
            prices_by_book = matrix['rows'][0]['sportsbook_quotes']
            assert prices_by_book['draftkings'][0]['price_american'] == '+130'
            assert prices_by_book['draftkings'][0]['current'] is True
            assert matrix['rows'][0]['offers'][0]['sportsbook']['book'] == 'fanduel'
            counts = census(projected, source_inventory(db, inputs['dependencies']))
            funnel = measure(db, projected, inputs['dependencies'], counts, owner, at=at)
            novig = next(row for row in funnel['cohorts'] if row['venue'] == 'novig' and row['family'] == 'spread'
                         and row['phase'] == 'in_game')
            assert novig['offered_price_units'] is None and not novig['provider_universe_complete']
            assert novig['source_originals']['fresh_at_original_receipt'] == 1
            assert novig['sql_working']['current_working_prices'] == 1
            assert novig['ordinary_publication']['sportsbook_ev'] == 1
            assert not source_inventory(db, inputs['dependencies'], phase='pregame', at=at)
            assert len(source_inventory(db, inputs['dependencies'], phase='live', at=at)) == 1
            pregame = measure(db, projected, inputs['dependencies'], counts, owner, at=at, phase='pregame')
            assert all(row['phase'] == 'pregame' and row['period'] == 'full_game'
                       for row in pregame['cohorts'])
            live_cohorts = measure(db, projected, inputs['dependencies'], counts, owner, at=at, phase='live')
            assert live_cohorts['cohorts']
            assert all(row['phase'] == 'in_game' for row in live_cohorts['cohorts'])
            audit = measure_inputs(inputs, dict(rows=[]), [], inputs['dependencies'], owner, states,
                                   settings=settings, policy=inputs['policy_identity'], epoch=inputs['epoch'], at=at)
            assert audit['ev']['eligible_indicative_sgo'] == 1
            assert audit['ev']['published_of_eligible_indicative_sgo'] == 0
            assert audit['ev']['eligible_native_before_fee'] == 0
            assert audit['arb']['eligible_before_fee'] == 0
            with patch('app.storage.ordinary_publication.utc', return_value=AT), \
                    patch('app.storage.comparison_snapshot.utc', return_value=AT):
                published = turn(db)
            assert published['live_first_price_seal'], published
            assert published['captured_components'] == 1
            assert published['price_generation'] is not None
        options = ('ev', 'gross_return_percent', 0, 25)

        def view(at):
            projected = project(publication, inputs['dependencies'], owner, states,
                                at=stamp(at), policy=inputs['policy_identity'], epoch=inputs['epoch'])
            if at == AT:
                row, = projected['rows']
                assert row['price_current'], row['price_reasons']
                assert row['sportsbook_baseline'], (row['current_authority'], inputs['dependencies'])
            return desk(projected, {'basis': 'sportsbooks'}, options)

        live = view(AT)
        assert live['coverage']['sportsbooks'] == 1
        assert live['coverage']['before'] == 0
        assert live['rows'][0]['offers'][0]['sportsbook']['book'] == 'fanduel'
        assert view('2026-11-10T20:00:16Z')['coverage']['sportsbooks'] == 0

    async def test_retained_schedule_seeds_polling_without_rewriting_offers(self):
        from app.collection.sportsgameodds_worker import retained_schedule
        from app.storage.sportsgameodds_reference import prepare_frames, prepare_page, upsert_frames
        data = response()
        odd = data['data'][0]['odds']['points-home-game-sp-home']
        odd['byBookmaker'] = {'novig': odd['byBookmaker']['book']}
        page = parse(data)
        rows, _ = current_rows(page, page.receipt_sha256)
        with self.connect() as db:
            CurrentRowStore(db).upsert_records(rows, now=AT)
            upsert_frames(db, prepare_frames(page, prepare_page(page)))
            before = db.execute("SELECT revision,received_at FROM current_offer WHERE contract_id IN "
                "(SELECT c.id FROM current_contract c JOIN current_event e ON e.id=c.event_id "
                "WHERE e.provider='sportsgameodds')").fetchall()
        with patch('app.storage.store.connect', side_effect=self.connect):
            events, truncated = retained_schedule(['NBA'], datetime.fromisoformat(AT.replace('Z', '+00:00')), 2000)
        assert not truncated and events['event']['received_at'] == AT
        assert events['event']['phase'] == 'pregame'
        with self.connect() as db:
            after = db.execute("SELECT revision,received_at FROM current_offer WHERE contract_id IN "
                "(SELECT c.id FROM current_contract c JOIN current_event e ON e.id=c.event_id "
                "WHERE e.provider='sportsgameodds')").fetchall()
        assert before == after

    async def test_native_kalshi_disconnection_does_not_change_sgo_kalshi_quote(self):
        data = response()
        odd = data['data'][0]['odds']['points-home-game-sp-home']
        odd['byBookmaker'] = {'kalshi': odd['byBookmaker']['book']}
        page = parse(data)
        rows, _ = current_rows(page, page.receipt_sha256)
        with self.connect() as db:
            store = CurrentRowStore(db)
            store.upsert_records(rows, now=AT)
            store.upsert_records([], now=AT, source_status={'kalshi': {'state': 'connecting'}})
            states = db.execute("""SELECT o.facts->>'state' state FROM current_offer o
                JOIN current_contract c ON c.id=o.contract_id JOIN current_event e ON e.id=c.event_id
                WHERE e.provider='sportsgameodds' AND c.venue='kalshi'""").fetchall()
            assert [row['state'] for row in states] == ['available']

    async def test_retirement_is_provider_event_and_venue_scoped(self):
        data = response()
        event = data['data'][0]
        event['eventID'] = 'CONTROLLED-event'
        event['leagueID'] = 'MLB'
        home = event['odds']['points-home-game-sp-home']
        home['byBookmaker'] = {'novig': home['byBookmaker']['book']}
        away = dict(home, oddID='points-away-game-sp-away', opposingOddID=home['oddID'],
                    statEntityID='away', sideID='away',
                    byBookmaker={'novig': dict(home['byBookmaker']['novig'], spread='1.5')})
        event['odds'][away['oddID']] = away
        other = deepcopy(event)
        other['eventID'] = 'OTHER-event'
        data['data'].append(other)
        page = parse(data)
        sgo, _ = current_rows(page, page.receipt_sha256)
        legacy = admit(body(books=('novig',)), 'MLB', '2026-10-03T00:00:00Z')
        with self.connect() as db:
            store = CurrentRowStore(db)
            store.upsert_records([*sgo, *legacy], now='2026-10-03T00:00:00Z')
            scope = dict(venue='novig', competition='MLB', native_event_id='CONTROLLED-event',
                         received_at=AT, aggregate_route='sgo_event')
            store.upsert_records([], now='2026-10-03T00:00:00Z', authoritative=True, scopes=[scope])
            counts = db.execute("""SELECT e.provider,count(*) n FROM current_contract c
                JOIN current_event e ON e.id=c.event_id WHERE c.venue='novig'
                AND e.native_event_id='CONTROLLED-event' GROUP BY e.provider""").fetchall()
            assert {r['provider']: r['n'] for r in counts} == {'the_odds_api': len(legacy)}
            assert db.execute("""SELECT count(*) n FROM current_contract c JOIN current_event e ON e.id=c.event_id
                WHERE e.provider='sportsgameodds' AND e.native_event_id='OTHER-event'""").fetchone()['n'] == 2
            with self.assertRaisesRegex(ValueError, 'aggregate_refresh_route'):
                store.upsert_records([], now='2026-10-03T00:00:00Z', authoritative=True,
                                     scopes=[dict(venue='novig',competition='MLB',received_at=AT,aggregate_route='sgo_event')])

