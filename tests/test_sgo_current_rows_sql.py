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
    async def test_sportsbook_baseline_reaches_ordinary_desk_and_expires(self):
        from app.collection.current_policy import DEFAULT
        from app.comparison.snapshot_math import assumptions
        from app.dashboard.trade_desk import page as desk
        from app.storage.comparison_snapshot import capture, defer_details
        from app.storage.ordinary_publication import prices, project
        from app.storage.sportsgameodds_reference import prepare_frames, prepare_page, upsert_frames, upsert_rows
        from app.storage.store import stamp

        data = response()
        event = data['data'][0]
        event['eventID'] = 'sportsbook-baseline-event'
        event['status'].update(startsAt='2026-11-10T19:59:55Z', started=True, live=True)
        home = event['odds']['points-home-game-sp-home']
        offer = dict(available=True, odds='+140', spread='-1.5', lastUpdatedAt=AT)
        home['byBookmaker'] = {'novig': offer, 'fanduel': dict(offer, odds='+120')}
        away = dict(home, oddID=home['opposingOddID'], opposingOddID=home['oddID'], statEntityID='away', sideID='away',
                    byBookmaker={'fanduel': dict(offer, odds='-150', spread='1.5')})
        event['odds'][away['oddID']] = away
        parsed = parse(data)
        records, _ = current_rows(parsed, parsed.receipt_sha256)
        references = prepare_page(parsed)
        config = dict(DEFAULT, aggregate_provider='sportsgameodds')
        states = {'sportsgameodds': {'state': 'available'}}
        with self.connect() as db, patch('app.collection.current_policy.load', return_value=config):
            CurrentRowStore(db).upsert_records(records, now=AT, source_status=states)
            upsert_rows(db, references)
            upsert_frames(db, prepare_frames(parsed, references))
            event_ids = [r['id'] for r in db.execute('SELECT id FROM current_event').fetchall()]
            inputs = capture(db, at=AT, ordinary=True, event_ids=event_ids)
            assert len(inputs['quotes']) == 1, inputs['issues']
            assert inputs['quotes'][0].get('sportsbook_baseline')
            publication = defer_details(prices(inputs, assumptions()[0]))
        owner = dict(healthy=True, active=True, config=config)
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

